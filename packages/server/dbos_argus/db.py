from sqlalchemy.ext.asyncio import create_async_engine

from .settings import settings

_url, _connect_args = settings.asyncpg_engine_args()
engine = create_async_engine(_url, echo=False, future=True, connect_args=_connect_args)
