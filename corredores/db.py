from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from corredores.config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


engine: Engine = create_engine(
    settings.database_url, future=True, **_engine_kwargs(settings.database_url)
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def configure_engine(url: str) -> Engine:
    """Rebind global engine/session (used by pytest against corredores_test)."""
    global engine, SessionLocal
    engine = create_engine(url, future=True, **_engine_kwargs(url))
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine
