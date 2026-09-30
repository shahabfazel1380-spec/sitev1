import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from backend import auth, settings
from backend.db import Session
from backend.main import app
from backend.models import CustomerSession, OTP, Order, Product, RateLimit, now
from conftest import checkout, login_customer, order_payload

def database(action):
    async def execute():
        async with Session() as db:
            result=await action(db)
            await db.commit()
            return result
    return asyncio.run(execute())

def test_guest_checkout_requires_login(client):
    assert checkout(client).status_code==401

def test_session_48h_cookie_and_profile(customer_client):
    me=customer_client.get('/api/auth/me').json()
    assert me['registered'] and me['full_name']=='مشتری آزمایشی'
    assert 172790<=me['session_expires_at']-now()<=172800
    client=TestClient(app)
    client.cookies.update(customer_client.cookies)
    assert client.get('/api/auth/me').json()['id']==me['id']

def test_otp_one_use_and_cookie_flags(client):
    database(lambda db:db.execute(delete(RateLimit)))
    mobile='09190000001'
    response=client.post('/api/auth/otp/request',json={'mobile':mobile})
    code=response.json()['demo_code']
    response=client.post('/api/auth/otp/verify',json={'mobile':mobile,'code':code})
    assert response.status_code==200
    cookie=response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Max-Age=172800' in cookie and 'SameSite=lax' in cookie
    assert client.post('/api/auth/otp/verify',json={'mobile':mobile,'code':code}).status_code==400

def test_otp_cooldown_attempt_limit_and_expiry(client):
    database(lambda db:db.execute(delete(RateLimit)))
    mobile='09190000002'
    first=client.post('/api/auth/otp/request',json={'mobile':mobile})
    code=first.json()['demo_code']
    assert client.post('/api/auth/otp/request',json={'mobile':mobile}).status_code==429
    wrong='000000' if code!='000000' else '111111'
    for _ in range(5):
        assert client.post('/api/auth/otp/verify',json={'mobile':mobile,'code':wrong}).status_code==400
    assert client.post('/api/auth/otp/verify',json={'mobile':mobile,'code':code}).status_code==400
    database(lambda db:db.execute(update(OTP).where(OTP.mobile==mobile).values(attempts=0,expires_at=now()-1)))
    assert client.post('/api/auth/otp/verify',json={'mobile':mobile,'code':code}).status_code==400

def test_csrf_and_cross_origin(customer_client):
    assert customer_client.put('/api/account/profile',json={'full_name':'نام جدید'},headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert customer_client.put('/api/account/profile',json={'full_name':'نام جدید'},headers={'Origin':'https://evil.example'}).status_code==403
    assert customer_client.post('/api/auth/otp/request',json={'mobile':'09111111111'},headers={'Sec-Fetch-Site':'cross-site'}).status_code==403

def test_expired_session(customer_client):
    uid=customer_client.get('/api/auth/me').json()['id']
    database(lambda db:db.execute(update(CustomerSession).where(CustomerSession.user_id==uid).values(expires_at=now()-1)))
    assert customer_client.get('/api/auth/me').status_code==401

def test_logout_all_revokes_copied_session(customer_client):
    copy=TestClient(app);copy.cookies.update(customer_client.cookies)
    assert customer_client.post('/api/auth/logout-all').status_code==200
    assert copy.get('/api/auth/me').status_code==401

def test_incomplete_profile_cannot_checkout(client):
    login_customer(client,registered=False)
    assert checkout(client).status_code==409

def test_checkout_uses_saved_identity_and_server_prices(customer_client):
    response=checkout(customer_client)
    assert response.status_code==201,response.text
    assert response.json()['total_amount']==2980000
    assert checkout(customer_client,order_payload(full_name='spoof',mobile='09999999999')).status_code==422
    assert checkout(customer_client,order_payload(total_amount=1)).status_code==422
    assert checkout(customer_client,{'items':[{'product_id':1,'quantity':1,'unit_price':1}]}).status_code==422

def test_invalid_quantities_and_products(customer_client):
    for quantity in [-1,0,11,True]:
        assert checkout(customer_client,{'items':[{'product_id':1,'quantity':quantity}]}).status_code==422
    assert checkout(customer_client,{'items':[]}).status_code==422
    assert checkout(customer_client,{'items':[{'product_id':99999,'quantity':1}]}).status_code==400
    assert checkout(customer_client,{'items':[{'product_id':1,'quantity':6},{'product_id':1,'quantity':6}]}).status_code==400

def test_idempotency_and_concurrency(customer_client):
    key=str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:checkout(customer_client,key=key),range(2)))
    assert all(r.status_code==201 for r in results),[r.text for r in results]
    assert results[0].json()['order_id']==results[1].json()['order_id']
    assert checkout(customer_client,{'items':[{'product_id':1,'quantity':1}]},key).status_code==409

def test_receipt_and_order_access_isolated(customer_client):
    order=checkout(customer_client).json()
    code=order['payment_url'].split('authority=')[1]
    other=TestClient(app);login_customer(other)
    assert other.get('/api/account/orders/'+order['order_id']).status_code==404
    assert other.get('/api/payment/session/'+code).status_code==404
    result=customer_client.get('/api/account/orders/'+order['order_id']).json()
    assert 'internal_note' not in result and 'mobile' not in result
    assert customer_client.get('/api/account/orders').headers['cache-control']=='no-store'

def test_payment_is_post_only_monotonic_and_owned(customer_client):
    order=checkout(customer_client).json();code=order['payment_url'].split('authority=')[1]
    assert customer_client.get(f'/api/payment/verify?Authority={code}&Status=OK').status_code==405
    assert customer_client.post(f'/api/payment/verify?Authority={code}&Status=OK').status_code==200
    first=customer_client.get('/api/payment/session/'+code).json()
    assert first['ref_id'].startswith('DEMO-')
    customer_client.post(f'/api/payment/verify?Authority={code}&Status=NOK')
    assert customer_client.get('/api/payment/session/'+code).json()==first

def test_canceled_and_expired_orders(customer_client):
    for expired in [False,True]:
        order=checkout(customer_client).json();code=order['payment_url'].split('authority=')[1]
        if expired:
            database(lambda db:db.execute(update(Order).where(Order.id==order['order_id']).values(created_at='2020-01-01T00:00:00+00:00')))
        else:
            customer_client.post(f'/api/payment/verify?Authority={code}&Status=NOK')
        customer_client.post(f'/api/payment/verify?Authority={code}&Status=OK')
        assert customer_client.get('/api/payment/session/'+code).json()['status']=='failed'

def test_coupon_reservation_limits_and_release(owner_client):
    code='SAVE'+uuid4().hex[:8]
    response=owner_client.post('/api/admin/discounts',json={'code':code,'kind':'percent','value':10,'max_uses':1,'per_user':1})
    assert response.status_code==201,response.text
    c=TestClient(app);login_customer(c)
    payload=order_payload(coupon=code)
    quote=c.post('/api/checkout/quote',json=payload).json()
    assert quote['discount']==298000 and quote['total_amount']==2682000
    order=checkout(c,payload).json()
    other=TestClient(app);login_customer(other)
    assert checkout(other,payload).status_code==400
    authority=order['payment_url'].split('authority=')[1]
    c.post(f'/api/payment/verify?Authority={authority}&Status=NOK')
    assert checkout(other,payload).status_code==201

def test_concurrent_coupon_cannot_oversubscribe(owner_client):
    code='ONE'+uuid4().hex[:8]
    owner_client.post('/api/admin/discounts',json={'code':code,'kind':'fixed','value':1000,'max_uses':1})
    a=TestClient(app);b=TestClient(app);login_customer(a);login_customer(b)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda c:checkout(c,order_payload(coupon=code)),[a,b]))
    assert sorted(r.status_code for r in results)==[201,400]

def test_ticket_ownership_and_chat_separation(customer_client):
    ticket=customer_client.post('/api/account/conversations',json={'kind':'ticket','subject':'مشکل اشتراک','body':'پیام آزمایشی'}).json()
    other=TestClient(app);login_customer(other)
    assert other.get('/api/account/conversations/'+ticket['id']).status_code==404
    assert other.post('/api/account/conversations/'+ticket['id']+'/messages',json={'body':'spoof'}).status_code==404
    assert len(customer_client.get('/api/account/conversations?kind=ticket').json()['items'])==1
    assert customer_client.get('/api/account/conversations?kind=chat').json()['items']==[]
    assert customer_client.post('/api/account/conversations/'+ticket['id']+'/close').status_code==200
    assert customer_client.post('/api/account/conversations/'+ticket['id']+'/messages',json={'body':'new'}).status_code==409

def test_staff_permissions_and_immediate_revocation(owner_client):
    username='staff_'+uuid4().hex[:8]
    data={'username':username,'name':'کارمند تست','password':'long-staff-password-42','permissions':['tickets.read','tickets.reply','orders.read','customers.read']}
    response=owner_client.post('/api/admin/staff',json=data)
    assert response.status_code==201,response.text
    sid=response.json()['id']
    staff=TestClient(app)
    login=staff.post('/api/admin/login',json={'username':username,'password':data['password']})
    staff.headers['X-CSRF-Token']=login.json()['csrf']
    assert staff.get('/api/admin/orders').status_code==200
    assert staff.get('/api/admin/conversations?kind=ticket').status_code==200
    assert staff.get('/api/admin/conversations?kind=chat').status_code==403
    assert staff.get('/api/admin/staff').status_code==403
    assert staff.get('/api/admin/products').status_code==403
    data['permissions']=['tickets.read'];data['password']=None
    assert owner_client.put(f'/api/admin/staff/{sid}',json=data).status_code==200
    assert staff.get('/api/admin/orders').status_code==401

def test_unknown_permissions_and_owner_protection(owner_client):
    assert owner_client.post('/api/admin/staff',json={'username':'badstaff','name':'تست','password':'long-enough-password','permissions':['staff.manage']}).status_code==422
    owner=owner_client.get('/api/admin/me').json()
    assert owner_client.delete('/api/admin/staff/'+str(owner['id'])).status_code==403

def test_support_reply_flow_and_presence(owner_client):
    customer=TestClient(app);login_customer(customer)
    chat=customer.post('/api/account/conversations',json={'kind':'chat','subject':'راهنمای خرید','body':'سلام'}).json()
    assert owner_client.post('/api/admin/conversations/'+chat['id']+'/messages',json={'body':'سلام، در خدمت شما هستیم.'}).status_code==200
    messages=customer.get('/api/account/conversations/'+chat['id']).json()
    assert [m['sender'] for m in messages['messages']]==['customer','staff']
    owner_client.get('/api/admin/me')
    assert customer.get('/api/support/presence').json()['online']

def product_payload(**kwargs):
    return {'title':'محصول تست','description':'توضیحات کوتاه محصول برای تست','price':150000,'published':False,**kwargs}

def test_product_draft_publish_revision_and_archive(owner_client):
    created=owner_client.post('/api/admin/products',json=product_payload()).json()
    pid=created['id']
    assert owner_client.get('/api/products/'+str(pid)).status_code==404
    assert owner_client.put('/api/admin/products/'+str(pid),json=product_payload(published=True,revision=created['revision'])).status_code==200
    assert owner_client.get('/api/products/'+str(pid)).status_code==200
    assert owner_client.put('/api/admin/products/'+str(pid),json=product_payload(published=True,revision=1)).status_code==409
    assert owner_client.post(f'/api/admin/products/{pid}/archive',json={'archived':True}).status_code==200
    assert owner_client.get('/api/products/'+str(pid)).status_code==404
    assert owner_client.get('/api/admin/sync').status_code==404

def test_block_customer_revokes_sessions(owner_client):
    customer=TestClient(app);data=login_customer(customer)
    assert owner_client.put('/api/admin/customers/'+str(data['id']),json={'blocked':True}).status_code==200
    assert customer.get('/api/auth/me').status_code==401

def test_safe_media_urls_and_uploads(owner_client):
    assert owner_client.post('/api/admin/products',json=product_payload(images=['javascript:alert(1)'])).status_code==422
    assert owner_client.post('/api/admin/media',content=b'<script>alert(1)</script>',headers={'Content-Type':'image/png'}).status_code==400
    assert owner_client.post('/api/admin/media',content=b'<svg/>',headers={'Content-Type':'image/svg+xml'}).status_code==400
    import io
    from PIL import Image
    buffer=io.BytesIO();Image.new('RGB',(10,10),'purple').save(buffer,'PNG')
    response=owner_client.post('/api/admin/media',content=buffer.getvalue(),headers={'Content-Type':'image/png'})
    assert response.status_code==201,response.text
    asset=owner_client.get(response.json()['url'])
    assert asset.status_code==200 and asset.headers['content-type']=='image/webp'

def test_production_rejects_demo_and_sms_disabled(client,monkeypatch):
    monkeypatch.setattr(settings,'ENV','production')
    import pytest
    with pytest.raises(RuntimeError):settings.validate_environment()
    monkeypatch.setattr(settings,'SMS_MODE','disabled')
    assert client.post('/api/auth/otp/request',json={'mobile':'09123456789'}).status_code==503

def test_security_headers_body_limit_and_private_files(client):
    assert client.get('/').status_code==200
    assert client.get('/admin/').status_code==200
    assert client.get('/.env').status_code==404
    assert client.get('/.local/development-secret').status_code==404
    assert 'frame-ancestors' in client.get('/').headers['content-security-policy']
    assert client.post('/api/auth/otp/request',content=b'x'*140000).status_code==413
