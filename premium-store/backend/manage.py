"""Server-side owner bootstrap/recovery; no default admin credentials."""
import argparse
import asyncio
import getpass
import re
from sqlalchemy import delete, select
from . import settings
from .db import Session
from .main import migrate
from .models import Staff, StaffSession
from .security import password_hash, secret

async def run(args):
    settings.validate_environment()
    secret()
    await migrate()
    password=getpass.getpass('Password (12+ characters): ')
    if len(password)<12 or len(password)>128 or password!=getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords must match and contain 12–128 characters.')
    async with Session() as db:
        existing=await db.scalar(select(Staff).where(Staff.username==args.username.lower()))
        if args.command=='create-owner':
            if existing:
                raise SystemExit('Username already exists; use reset-owner for owner recovery.')
            db.add(Staff(username=args.username.lower(),name=args.name,password_hash=password_hash(password),owner=True))
        else:
            if not existing or not existing.owner:
                raise SystemExit('Owner not found.')
            existing.password_hash=password_hash(password)
            existing.active=True
            await db.execute(delete(StaffSession).where(StaffSession.staff_id==existing.id))
        await db.commit()
    print('Owner credentials saved. Sign in at /admin/. Password was not logged.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['create-owner','reset-owner'])
    parser.add_argument('--username',required=True)
    parser.add_argument('--name',default='مدیر فروشگاه')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,50}',args.username):
        parser.error('Invalid username')
    asyncio.run(run(args))
