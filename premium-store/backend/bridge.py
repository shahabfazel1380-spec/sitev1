"""Transactional outbox to the existing bot's dynamic SQLite catalog.

Only records created by this integration are modified. No Telegram messages are
sent and no customer/order/credential tables in the bot are read.
"""
import asyncio
import html
import os
import sqlite3
from pathlib import Path
from sqlalchemy import select
from . import settings
from .db import Session
from .models import Product, SyncJob, now

def export_to_bot(path, product):
    database = Path(path).resolve()
    if not database.is_file():
        raise ValueError('BOT_DATABASE_NOT_FOUND')
    with sqlite3.connect(database.as_uri()+'?mode=rw', uri=True, timeout=15) as bot:
        bot.execute('PRAGMA foreign_keys=ON')
        bot.execute('BEGIN IMMEDIATE')
        columns = {row[1] for row in bot.execute('PRAGMA table_info(products)')}
        if not {'id','title','description','price','available','is_category','parent_id','sort_order'} <= columns:
            raise ValueError('BOT_SCHEMA_UNSUPPORTED')
        bot.execute('CREATE TABLE IF NOT EXISTS premium_web_product_map (web_id INTEGER PRIMARY KEY, bot_id INTEGER UNIQUE NOT NULL, revision INTEGER NOT NULL)')
        previous = bot.execute('SELECT bot_id, revision FROM premium_web_product_map WHERE web_id=?',(product['id'],)).fetchone()
        if previous and previous[1]>=product['revision']:
            return previous[0]
        visible = product['published'] and product['available'] and not product['archived']
        title = html.escape(product['title'])
        description = html.escape(product['description'])+'\n'+settings.PUBLIC_URL+'/product.html?id='+str(product['id'])
        if previous:
            cursor = bot.execute('UPDATE products SET title=?,description=?,price=?,available=?,sort_order=? WHERE id=?',
                (title,description,product['price'],int(visible),product['sort_order'],previous[0]))
            if cursor.rowcount!=1:
                raise ValueError('BOT_MAPPED_PRODUCT_MISSING')
            bot.execute('UPDATE premium_web_product_map SET revision=? WHERE web_id=?',(product['revision'], product['id']))
            return previous[0]
        cursor = bot.execute('INSERT INTO products (title,description,price,available,is_category,parent_id,sort_order) VALUES (?,?,?,?,0,NULL,?)',
            (title,description,product['price'],int(visible),product['sort_order']))
        bot.execute('INSERT INTO premium_web_product_map VALUES (?,?,?)',(product['id'],cursor.lastrowid,product['revision']))
        return cursor.lastrowid

async def sync_once():
    path = os.getenv('BOT_DATABASE_PATH')
    if not path:
        return
    async with Session() as db:
        jobs = (await db.scalars(select(SyncJob).where(SyncJob.status.in_(['pending','failed']), SyncJob.attempts<6).order_by(SyncJob.id).limit(30))).all()
        for job in jobs:
            product = await db.get(Product, job.product_id)
            if not product:
                continue
            payload = {key:getattr(product,key) for key in ['id','revision','title','description','price','available','published','archived','sort_order']}
            try:
                await asyncio.to_thread(export_to_bot, path, payload)
                job.status='done'
                job.last_error=''
            except Exception as error:
                job.status='failed'
                job.last_error=str(error) if isinstance(error,ValueError) else type(error).__name__
            job.attempts += 1
            await db.commit()

async def worker():
    while True:
        try:
            await sync_once()
        except Exception:
            import logging
            logging.getLogger('premiumstore').warning('Catalog sync deferred; inspect admin sync status.')
        await asyncio.sleep(10)
