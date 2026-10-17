import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

for parent in Path(__file__).resolve().parents:
    env_file = parent / ".env"
    if env_file.is_file():
        load_dotenv(env_file)
        break

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=naming_convention)


def _url() -> str:
    return os.getenv("DATABASE_URL") or (
        "postgresql+asyncpg://"
        f"{os.getenv('ACADEMIC_DB_USER', 'academic_service')}:{os.getenv('ACADEMIC_DB_PASSWORD', 'academic_service_password')}@"
        f"{os.getenv('DATABASE_HOST', 'localhost')}:{os.getenv('DATABASE_PORT', '5432')}/"
        f"{os.getenv('ACADEMIC_DB_NAME', 'academic_db')}"
    )


engine = create_async_engine(_url(), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
