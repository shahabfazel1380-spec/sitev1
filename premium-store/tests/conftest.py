import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

temp=TemporaryDirectory()
os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+(Path(temp.name)/'store.db').as_posix()
os.environ['DATA_DIR']=str(Path(temp.name)/'data')
os.environ['APP_ENV']='test'
os.environ['PAYMENT_MODE']='demo'
os.environ['SMS_MODE']='demo'
os.environ['APP_SECRET']='test-secret-not-valid-for-deployment-123456789'
os.environ.pop('BOT_DATABASE_PATH',None)

from backend.main import app
from backend.db import Session
from backend.models import Staff
from backend.security import password_hash

@pytest.fixture(scope='session')
def running_app():
    with TestClient(app) as instance:
        async def seed():
            async with Session() as db:
                db.add(Staff(username='test_owner',name='مالک آزمایشی',owner=True,password_hash=password_hash('test-password-owner-42')))
                await db.commit()
        asyncio.run(seed())
        yield instance
    temp.cleanup()

@pytest.fixture
def client(running_app):
    instance=TestClient(app)
    yield instance
    instance.close()

mobile_counter=10000000

def login_customer(client,registered=True):
    global mobile_counter
    mobile_counter+=1
    mobile='091'+str(mobile_counter)
    # Use unique proxy-test IP to isolate unrelated tests' rate limits.
    from backend import auth
    original=auth.client_ip
    auth.client_ip=lambda request:'testclient'
    from backend.models import RateLimit
    from sqlalchemy import delete
    async def clear_ip():
        async with Session() as db:
            await db.execute(delete(RateLimit))
            await db.commit()
    asyncio.run(clear_ip())
    response=client.post('/api/auth/otp/request',json={'mobile':mobile})
    auth.client_ip=original
    assert response.status_code==200,response.text
    code=response.json()['demo_code']
    response=client.post('/api/auth/otp/verify',json={'mobile':mobile,'code':code})
    assert response.status_code==200,response.text
    data=response.json()
    client.headers['X-CSRF-Token']=data['csrf']
    if registered:
        response=client.put('/api/account/profile',json={'full_name':'مشتری آزمایشی','telegram_id':'@test_person'})
        assert response.status_code==200,response.text
        data=response.json()
    return data

@pytest.fixture
def customer_client(client):
    login_customer(client)
    return client

@pytest.fixture
def owner_client(client):
    from backend.models import RateLimit
    from sqlalchemy import delete
    async def reset():
        async with Session() as db:
            await db.execute(delete(RateLimit))
            await db.commit()
    asyncio.run(reset())
    response=client.post('/api/admin/login',json={'username':'test_owner','password':'test-password-owner-42'})
    assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=response.json()['csrf']
    return client

def order_payload(**kwargs):
    return {'items':[{'product_id':1,'quantity':2}],**kwargs}

def checkout(client,payload=None,key=None):
    return client.post('/api/payment/request',json=payload or order_payload(),headers={'Idempotency-Key':key or str(uuid4())})
