import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,text
from backend.main import app
from backend.db import Session
from backend.models import OrderExtra,WalletEntry,ActivationCard,Activation,OutgoingMessage,now
from backend import settings
from backend.wallet import entry,wallet_mode
from backend.notifications import deliver_once
from conftest import login_customer,checkout
from test_platform import product_payload

@pytest.fixture
def buyer(running_app):
    with TestClient(app) as c:
        u=login_customer(c)
        yield c,u

def grant(owner,uid,amount,key=None):
    return owner.post(f'/api/admin/customers/{uid}/wallet',json={'amount':amount,'note':'اعتبار تست'},headers={'Idempotency-Key':key or str(uuid4())})

def config(owner,**changes):
    data=owner.get('/api/admin/settings').json()
    for key in ['technical','payment_mode','sms_mode']: data.pop(key,None)
    data.update(changes)
    response=owner.put('/api/admin/settings',json=data)
    assert response.status_code==200,response.text
    return data

def test_wallet_adjust_idempotency_and_no_negative(owner_client,buyer):
    c,u=buyer;key=str(uuid4())
    assert grant(owner_client,u['id'],10000,key).status_code==200
    assert grant(owner_client,u['id'],10000,key).status_code==200
    assert grant(owner_client,u['id'],20000,key).status_code==409
    assert grant(owner_client,u['id'],-10001).status_code==409
    assert c.get('/api/account/wallet').json()['balance']==10000

def test_full_wallet_purchase_refund_once(owner_client,buyer):
    c,u=buyer;price=c.get('/api/products/1').json()['price']
    grant(owner_client,u['id'],price)
    payload={'items':[{'product_id':1,'quantity':1}],'use_wallet':True}
    result=checkout(c,payload).json();oid=result['order_id']
    assert '/payment-result.html?' in result['payment_url']
    assert c.get('/api/account/wallet').json()['balance']==0
    d=c.get('/api/account/orders/'+oid).json()
    assert d['status']=='success' and d['wallet_used']==price and d['payable']==0
    for _ in range(2):
        assert owner_client.post(f'/api/admin/orders/{oid}/refund',json={'note':'انجام نشد'}).status_code==200
    assert c.get('/api/account/wallet').json()['balance']==price
    assert c.get('/api/account/orders/'+oid).json()['refunded']
    assert owner_client.put('/api/admin/orders/'+oid,json={'fulfillment':'demo_complete'}).status_code==409

def test_partial_wallet_cancel_releases_once(owner_client,buyer):
    c,u=buyer;grant(owner_client,u['id'],15000)
    r=checkout(c,{'items':[{'product_id':1,'quantity':1}],'use_wallet':True}).json()
    authority=r['payment_url'].split('authority=')[1]
    assert c.get('/api/account/wallet').json()['balance']==0
    for _ in range(2): assert c.post('/api/payment/verify',params={'Authority':authority,'Status':'NOK'}).status_code==200
    assert c.get('/api/account/wallet').json()['balance']==15000
    assert owner_client.post('/api/admin/orders/'+r['order_id']+'/refund',json={'note':'لغو شده'}).status_code==409

def test_wallet_cannot_overspend_with_concurrent_orders(owner_client,buyer):
    c,u=buyer;grant(owner_client,u['id'],10000)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:checkout(c,{'items':[{'product_id':1,'quantity':1}],'use_wallet':True}),range(2)))
    assert all(r.status_code==201 for r in results)
    used=sum(c.get('/api/account/orders/'+r.json()['order_id']).json()['wallet_used'] for r in results)
    assert used==10000 and c.get('/api/account/wallet').json()['balance']==0

def test_topup_no_credit_before_verified_and_one_use(buyer):
    c,u=buyer
    r=c.post('/api/account/wallet/topups',json={'amount':25000},headers={'Idempotency-Key':str(uuid4())})
    assert r.status_code==201,r.text
    assert c.get('/api/account/wallet').json()['balance']==0
    tid=r.json()['id']
    other=TestClient(app);login_customer(other)
    assert other.post(f'/api/account/wallet/topups/{tid}/verify',json={'success':True}).status_code==404
    for _ in range(2):assert c.post(f'/api/account/wallet/topups/{tid}/verify',json={'success':True}).status_code==200
    assert c.get('/api/account/wallet').json()['balance']==25000
    other.close()

def test_expired_order_returns_wallet(owner_client,buyer):
    c,u=buyer;grant(owner_client,u['id'],30000)
    r=checkout(c,{'items':[{'product_id':1,'quantity':1}],'use_wallet':True}).json()
    async def expire():
        async with Session() as db:
            await db.execute(text("UPDATE web_orders SET created_at='2000-01-01T00:00:00+00:00' WHERE id=:id"),{'id':r['order_id']})
            from backend.wallet import expire_pending
            await expire_pending(db);await db.commit()
    asyncio.run(expire())
    assert c.get('/api/account/wallet').json()['balance']==30000

def test_live_and_demo_money_are_separate(buyer):
    c,u=buyer
    async def seed():
        async with Session() as db:
            await db.execute(text('BEGIN IMMEDIATE'))
            await entry(db,u['id'],9999,'adjustment','live-test:'+str(uuid4()),mode='live')
            await db.commit()
    asyncio.run(seed())
    assert c.get('/api/account/wallet').json()['balance']==0

def test_credential_requirement_encryption_and_reveal(owner_client,buyer):
    c,u=buyer
    p=owner_client.post('/api/admin/products',json=product_payload(published=True,require_credentials=True)).json()
    payload={'items':[{'product_id':p['id'],'quantity':2}]}
    assert checkout(c,payload).status_code==400
    payload['credentials']=[{'product_id':p['id'],'username':'test@example.com','password':'  private-secret  '}]*2
    r=checkout(c,payload);assert r.status_code==201,r.text
    oid=r.json()['order_id']
    async def stored():
        async with Session() as db:return (await db.get(OrderExtra,oid)).credentials
    encrypted=asyncio.run(stored())
    assert 'private-secret' not in encrypted and 'test@example.com' not in encrypted
    assert 'private-secret' not in c.get('/api/account/orders/'+oid).text
    assert c.post(f'/api/admin/orders/{oid}/credentials').status_code==401
    d=owner_client.post(f'/api/admin/orders/{oid}/credentials').json()
    assert d['items'][0]['password']=='  private-secret  '

def test_chat_toggle_enforced_on_server(owner_client,buyer):
    c,u=buyer
    conversation=c.post('/api/account/conversations',json={'kind':'chat','subject':'گفتگو','body':'سلام'}).json()
    config(owner_client,chat_enabled=False)
    assert c.get('/api/support/presence').json()['enabled'] is False
    assert c.post('/api/account/conversations',json={'kind':'chat','subject':'جدید','body':'سلام'}).status_code==409
    assert c.post('/api/account/conversations/'+conversation['id']+'/messages',json={'body':'تست'}).status_code==409
    assert c.post('/api/account/conversations',json={'kind':'ticket','subject':'درخواست','body':'سلام'}).status_code==201
    config(owner_client,chat_enabled=True)

def test_ticket_sms_queue_is_generic_and_simulated(owner_client,buyer):
    c,u=buyer;config(owner_client,ticket_sms_enabled=True,sms_notifications_enabled=True)
    ticket=c.post('/api/account/conversations',json={'kind':'ticket','subject':'درخواست تست','body':'سلام'}).json()
    response=owner_client.post(f"/api/admin/conversations/{ticket['id']}/messages",json={'body':'جزئیات خصوصی پاسخ'})
    assert response.status_code==200
    asyncio.run(deliver_once())
    messages=owner_client.get(f"/api/admin/customers/{u['id']}/messages").json()['items']
    assert len(messages)==1 and 'جزئیات خصوصی' not in messages[0]['body'] and messages[0]['status']=='simulated'
    config(owner_client,ticket_sms_enabled=False,sms_notifications_enabled=False)

def test_manual_message_disabled_and_idempotent(owner_client,buyer):
    c,u=buyer;path=f"/api/admin/customers/{u['id']}/messages"
    key={'Idempotency-Key':str(uuid4())};payload={'channels':['sms'],'body':'پیام آزمایشی'}
    assert owner_client.post(path,json=payload,headers=key).status_code==409
    config(owner_client,sms_notifications_enabled=True)
    assert owner_client.post(path,json=payload,headers=key).status_code==200
    assert owner_client.post(path,json=payload,headers=key).status_code==200
    assert owner_client.post(path,json={**payload,'body':'متن دیگر'},headers=key).status_code==409
    assert len(owner_client.get(path).json()['items'])==1
    config(owner_client,sms_notifications_enabled=False)

def test_activation_search_masking_reminder_and_single_use(owner_client,buyer):
    c,u=buyer
    card=owner_client.post('/api/admin/activation-cards',json={'label':'کارت آزمایشی','number':'4242424242424242','kind':'single_use'}).json()
    data={'card_id':card['id'],'user_id':u['id'],'service':'سرویس تست','email':'qa@example.com','password':'secret-account','paid_at':now(),'renewal_at':now()+1000,'auto_renew':True}
    r=owner_client.post('/api/admin/activations',json=data);assert r.status_code==201,r.text
    aid=r.json()['id']
    assert owner_client.post('/api/admin/activations',json=data).status_code==409
    for q in ['4242424242424242','qa@example.com',u['mobile']]:
        result=owner_client.get('/api/admin/activations',params={'q':q})
        assert any(a['id']==aid for a in result.json()['items'])
        assert 'secret-account' not in result.text and '4242424242424242' not in result.text
    assert any(a['id']==aid for a in owner_client.get('/api/admin/activation-reminders').json()['items'])
    assert owner_client.post(f'/api/admin/activations/{aid}/reveal').json()['password']=='secret-account'
    async def encrypted():
        async with Session() as db:return (await db.get(ActivationCard,card['id'])).number_encrypted
    assert '4242424242424242' not in asyncio.run(encrypted())

def test_granular_finance_and_secrets_permissions(owner_client,buyer):
    c,u=buyer;username='staff_'+uuid4().hex[:8]
    r=owner_client.post('/api/admin/staff',json={'username':username,'name':'کارمند تست','password':'test-password-strong','permissions':['customers.read','orders.read','activations.read'],'active':True})
    assert r.status_code==201,r.text
    staff=TestClient(app);login=staff.post('/api/admin/login',json={'username':username,'password':'test-password-strong'}).json();staff.headers['X-CSRF-Token']=login['csrf']
    assert staff.get(f"/api/admin/customers/{u['id']}").json()['balance'] is None
    assert grant(staff,u['id'],1000).status_code==403
    assert staff.get(f"/api/admin/customers/{u['id']}/messages").status_code==403
    assert staff.post('/api/admin/activations/1/reveal').status_code==403
    assert staff.post('/api/admin/activation-cards/1/reveal').status_code==403
    staff.close()

def test_production_topup_cannot_use_mock(buyer,monkeypatch):
    c,u=buyer;monkeypatch.setattr(settings,'ENV','production')
    assert c.post('/api/account/wallet/topups',json={'amount':10000},headers={'Idempotency-Key':str(uuid4())}).status_code==503
    assert c.post('/api/account/wallet/topups/any/verify',json={'success':True}).status_code==403

def test_production_can_spend_only_full_live_wallet(owner_client,buyer,monkeypatch):
    c,u=buyer;price=c.get('/api/products/1').json()['price']
    monkeypatch.setattr(settings,'ENV','production');monkeypatch.setattr(settings,'PAYMENT_MODE','disabled')
    grant(owner_client,u['id'],price)
    result=checkout(c,{'items':[{'product_id':1,'quantity':1}],'use_wallet':True})
    assert result.status_code==201,result.text
    detail=c.get('/api/account/orders/'+result.json()['order_id']).json()
    assert detail['payment_mode']=='wallet' and detail['status']=='success'
    assert c.get('/api/account/wallet').json()['balance']==0
    grant(owner_client,u['id'],1000)
    assert checkout(c,{'items':[{'product_id':1,'quantity':1}],'use_wallet':True}).status_code==503
    assert c.get('/api/account/wallet').json()['balance']==1000

def test_staff_cancellation_releases_reserved_wallet(owner_client,buyer):
    c,u=buyer;grant(owner_client,u['id'],7000)
    r=checkout(c,{'items':[{'product_id':1,'quantity':1}],'use_wallet':True}).json()
    assert owner_client.put('/api/admin/orders/'+r['order_id'],json={'fulfillment':'canceled'}).status_code==200
    assert c.get('/api/account/wallet').json()['balance']==7000
    authority=r['payment_url'].split('authority=')[1]
    c.post('/api/payment/verify',params={'Authority':authority,'Status':'OK'})
    assert c.get('/api/account/orders/'+r['order_id']).json()['status']=='failed'
    assert c.get('/api/account/wallet').json()['balance']==7000

def test_topup_boundaries_and_disabled_settings(owner_client,buyer):
    c,u=buyer
    def topup(amount):return c.post('/api/account/wallet/topups',json={'amount':amount},headers={'Idempotency-Key':str(uuid4())})
    assert topup(1000).status_code==400
    config(owner_client,wallet_topup_enabled=False)
    assert topup(20000).status_code==409
    config(owner_client,wallet_topup_enabled=True)
