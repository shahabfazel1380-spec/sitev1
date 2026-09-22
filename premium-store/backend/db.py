from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from fastapi import Depends
from typing import Annotated
from . import settings

engine = create_async_engine(settings.DATABASE_URL, connect_args={'check_same_thread':False, 'timeout':20})
Session = async_sessionmaker(engine, expire_on_commit=False)

@event.listens_for(engine.sync_engine, 'connect')
def sqlite_settings(connection, _):
    cursor = connection.cursor()
    cursor.execute('PRAGMA foreign_keys=ON')
    cursor.execute('PRAGMA journal_mode=WAL')
    cursor.close()

class Base(DeclarativeBase):
    pass

async def session():
    async with Session() as db:
        yield db

DB = Annotated[AsyncSession, Depends(session)]
