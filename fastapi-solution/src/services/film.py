from functools import lru_cache
from typing import Optional

import orjson
from aioredis import Redis
from db.elastic import get_elastic
from db.redis import get_redis
from elasticsearch import AsyncElasticsearch
from fastapi import Depends
from models.film import ESFilm, ListResponseFilm
from services.mixins import ServiceMixin
from services.pagination import get_by_pagination
from services.utils import (create_hash_key, get_hits,
                            get_params_films_to_elastic)


class FilmService(ServiceMixin):
    async def get_all_films(
        self,
        page: int,
        page_size: int,
        sorting: str = None,
        query: str = None,
        genre: str = None,
    ) -> Optional[dict]:
        """Производим полнотекстовый поиск по фильмам в Elasticsearch."""
        _source: tuple = ("id", "title", "imdb_rating", "genre")
        """ Получаем число фильмов из стейт """
        state_total: int = await self.get_total_count()
        params: str = f"{state_total}{page}{page_size}{query}{genre}"
        """ Пытаемся получить данные из кэша """
        instance = await self._get_result_from_cache(
            key=create_hash_key(index=self.index, params=params)
        )
        if not instance:
            """Если данных нет в кеше, то ищем его в Elasticsearch"""
            body: dict = get_params_films_to_elastic(
                page_size=page_size, page=page, genre=genre, query=query
            )
            docs: Optional[dict] = await self.search_in_elastic(
                body=body, _source=_source, sort=sorting
            )
            if not docs:
                return None
            """ Получаем фильмы из ES """
            hits = get_hits(docs=docs, schema=ESFilm)
            """ Получаем число фильмов """
            total: int = int(docs.get("hits").get("total").get("value", 0))
            """ Прогоняем данные через pydantic """
            films: list[ListResponseFilm] = [
                ListResponseFilm(
                    uuid=row.id, title=row.title, imdb_rating=row.imdb_rating
                )
                for row in hits
            ]
            """ Сохраняем фильмы в кеш """
            data = orjson.dumps([i.dict() for i in films])
            new_param: str = f"{total}{page}{page_size}{query}{genre}"
            await self._put_data_to_cache(
                key=create_hash_key(index=self.index, params=new_param), instance=data
            )
            """ Сохраняем число фильмов в стейт """
            await self.set_total_count(value=total)
            return get_by_pagination(
                name="films",
                db_objects=films,
                total=total,
                page=page,
                page_size=page_size,
            )
        films_from_cache: list[ListResponseFilm] = [
            ListResponseFilm(**row) for row in orjson.loads(instance)
        ]
        return get_by_pagination(
            name="films",
            db_objects=films_from_cache,
            total=state_total,
            page=page,
            page_size=page_size,
        )


# get_film_service — это провайдер FilmService. Синглтон
@lru_cache()
def get_film_service(
    redis: Redis = Depends(get_redis),
    elastic: AsyncElasticsearch = Depends(get_elastic),
) -> FilmService:
    return FilmService(redis=redis, elastic=elastic, index="movies")
