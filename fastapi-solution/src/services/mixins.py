from typing import Optional, Union

from aioredis import Redis
from core.config import CACHE_EXPIRE_IN_SECONDS
from elasticsearch import AsyncElasticsearch, NotFoundError
from models.film import ESFilm
from models.genre import ElasticGenre
from models.person import ElasticPerson

Schemas: tuple = (ESFilm, ElasticGenre, ElasticPerson)
ES_schemas = Union[Schemas]


class ServiceMixin:
    def __init__(self, redis: Redis, elastic: AsyncElasticsearch, index: str):
        self.redis = redis
        self.elastic = elastic
        self.index = index
        self.total_count: int = 0

    async def get_total_count(self) -> int:
        return self.total_count

    async def set_total_count(self, value: int):
        self.total_count = value

    async def search_in_elastic(
        self, body: dict, _source=None, sort=None, _index=None
    ) -> Optional[dict]:
        if not _index:
            _index = self.index

        sort_field = sort[0] if not isinstance(sort, str) and sort else sort
        if sort_field:
            order = "desc" if sort_field.startswith("-") else "asc"
            sort_field = f"{sort_field.removeprefix('-')}:{order}"
        try:
            return await self.elastic.search(
                index=_index, _source=_source, body=body, sort=sort_field
            )
        except NotFoundError:
            return None

    async def get_by_id(self, target_id: str, schema: Schemas) -> Optional[ES_schemas]:
        """Пытаемся получить данные из кеша, потому что оно работает быстрее"""
        instance = await self._get_result_from_cache(key=target_id)
        if not instance:
            """Если данных нет в кеше, то ищем его в Elasticsearch"""
            instance = await self._get_data_from_elastic_by_id(
                target_id=target_id, schema=schema
            )
            if not instance:
                return None
            """ Сохраняем фильм в кеш """
            await self._put_data_to_cache(key=instance.id, instance=instance.json())
            return instance
        return schema.parse_raw(instance)

    async def _get_data_from_elastic_by_id(
        self, target_id: str, schema: Schemas
    ) -> Optional[ES_schemas]:
        """Если он отсутствует в Elastic, значит объекта вообще нет в базе"""
        try:
            doc = await self.elastic.get(index=self.index, id=target_id)
            return schema(**doc["_source"])
        except NotFoundError:
            return None

    async def _get_result_from_cache(self, key: str) -> Optional[bytes]:
        """Пытаемся получить данные об объекте из кеша"""
        data = await self.redis.get(key=key)
        return data or None

    async def _put_data_to_cache(self, key: str, instance: Union[bytes, str]) -> None:
        """Сохраняем данные об объекте в кеш, время жизни кеша — 5 минут"""
        await self.redis.set(key=key, value=instance, expire=CACHE_EXPIRE_IN_SECONDS)
