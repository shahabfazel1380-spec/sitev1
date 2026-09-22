import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import and_, func, or_, select, text, update
from . import settings
from .db import DB
from .models import Coupon, CouponUse, Order, OrderDetails, OrderItem, Product, Setting, now
from .schemas import CheckoutRequest
from .security import Customer, customer

router = APIRouter(prefix='/api')

def product_data(p, admin=False):
    fields = ['id','title','brand','category','icon','description','content','features','images','video','price','original_price','period','badge','available','sort_order']
    if admin:
        fields += ['published','archived','revision','updated_at']
    return {key:getattr(p,key) for key in fields}

async def public_config(db):
    values = {s.key:s.value for s in (await db.scalars(select(Setting))).all()}
    return {'payment_mode':settings.PAYMENT_MODE, 'sms_mode':settings.SMS_MODE,
            'support_url':values.get('support_url',''), 'bot_url':values.get('bot_url',''),
            'telegram_url':values.get('telegram_url','https://t.me/premiumstore'), 'instagram_url':values.get('instagram_url',''),
            'support_hours':values.get('support_hours','پاسخ‌گویی در اولین فرصت'), 'store_notice':values.get('store_notice','')}

@router.get('/products')
async def list_products(db: DB):
    rows = (await db.scalars(select(Product).where(Product.published==True, Product.archived==False).order_by(Product.sort_order, Product.id))).all()
    return {'products':[product_data(p) for p in rows], **await public_config(db)}

@router.get('/products/{product_id}')
async def product_detail(product_id: int, db: DB):
    product = await db.get(Product, product_id)
    if not product or not product.published or product.archived:
        raise HTTPException(404, 'محصول پیدا نشد یا هنوز منتشر نشده است.')
    return product_data(product)

async def quote(data, db, user_id):
    quantities = {}
    for item in data.items:
        quantities[item.product_id] = quantities.get(item.product_id, 0)+item.quantity
    products = {}
    subtotal = 0
    for pid, qty in quantities.items():
        product = await db.get(Product, pid)
        if not product or product.archived or not product.published or not product.available:
            raise HTTPException(400, 'یکی از محصولات موجود نیست؛ سبد خرید را به‌روز کنید.')
        if qty>10:
            raise HTTPException(400, 'حداکثر تعداد هر محصول ۱۰ عدد است.')
        products[pid] = product
        subtotal += product.price*qty
    coupon = None
    discount = 0
    if data.coupon:
        coupon = await db.scalar(select(Coupon).where(Coupon.code==data.coupon.upper()))
        stamp = now()
        if not coupon or not coupon.active or coupon.starts_at>stamp or (coupon.expires_at and coupon.expires_at<=stamp) or subtotal<coupon.min_total:
            raise HTTPException(400, 'کد تخفیف معتبر نیست، منقضی شده یا حداقل مبلغ آن رعایت نشده است.')
        usable = and_(CouponUse.coupon_id==coupon.id, or_(CouponUse.status=='redeemed', and_(CouponUse.status=='reserved', CouponUse.expires_at>stamp)))
        count = await db.scalar(select(func.count()).select_from(CouponUse).where(usable))
        personal = await db.scalar(select(func.count()).select_from(CouponUse).where(usable, CouponUse.user_id==user_id))
        if count>=coupon.max_uses or personal>=coupon.per_user:
            raise HTTPException(400, 'سقف استفاده از این کد تخفیف پر شده است.')
        discount = subtotal*coupon.value//100 if coupon.kind=='percent' else coupon.value
        if coupon.max_discount:
            discount = min(discount, coupon.max_discount)
        discount = min(discount, subtotal-1)
    return products, quantities, subtotal, discount, coupon

@router.post('/checkout/quote')
async def checkout_quote(data: CheckoutRequest, db: DB, context: Customer = Depends(customer)):
    _, _, subtotal, discount, coupon = await quote(data, db, context.user.id)
    return {'subtotal':subtotal, 'discount':discount, 'total_amount':subtotal-discount, 'coupon':coupon.code if coupon else ''}

def payment_response(order):
    return {'status':'success', 'order_id':order.id, 'total_amount':order.total_amount, 'payment_mode':order.payment_mode, 'payment_url':f'/demo-payment.html?authority={order.authority_code}'}

@router.post('/payment/request', status_code=201)
async def request_payment(data: CheckoutRequest, db: DB, idempotency_key: Annotated[str, Header(pattern=r'^[a-f0-9-]{36}$')], context: Customer = Depends(customer)):
    if not context.profile.registered:
        raise HTTPException(409, 'ابتدا اطلاعات حساب کاربری را یک بار تکمیل کنید.')
    if settings.PAYMENT_MODE!='demo':
        raise HTTPException(503, 'پرداخت آنلاین هنوز فعال نشده است.')
    fingerprint = hashlib.sha256((str(context.user.id)+':'+data.model_dump_json()).encode()).hexdigest()
    # Serializes coupon reservation + order creation across workers/processes.
    await db.execute(text('BEGIN IMMEDIATE'))
    existing = await db.scalar(select(Order).where(Order.idempotency_key==idempotency_key))
    if existing:
        if existing.request_fingerprint!=fingerprint or existing.user_id!=context.user.id:
            raise HTTPException(409, 'این شناسه برای سفارش دیگری استفاده شده است.')
        return payment_response(existing)
    products, quantities, subtotal, discount, coupon = await quote(data, db, context.user.id)
    order = Order(user_id=context.user.id, total_amount=subtotal-discount, full_name=context.user.full_name, mobile=context.user.mobile, telegram_id=context.user.telegram_id,
                  authority_code=str(uuid4()), idempotency_key=idempotency_key, request_fingerprint=fingerprint)
    db.add(order)
    await db.flush()
    for pid, qty in quantities.items():
        db.add(OrderItem(order_id=order.id, product_id=pid, title=products[pid].title, quantity=qty, unit_price=products[pid].price))
    db.add(OrderDetails(order_id=order.id, subtotal=subtotal, discount_amount=discount, coupon_code=coupon.code if coupon else ''))
    if coupon:
        db.add(CouponUse(order_id=order.id, coupon_id=coupon.id, user_id=context.user.id, expires_at=now()+1200))
    await db.commit()
    return payment_response(order)

@router.get('/payment/session/{authority}')
async def payment_session(authority: str, db: DB, context: Customer = Depends(customer)):
    order = await db.scalar(select(Order).where(Order.authority_code==authority, Order.user_id==context.user.id))
    if not order:
        raise HTTPException(404, 'سفارش پیدا نشد.')
    return {'order_id':order.id, 'total_amount':order.total_amount, 'status':order.status, 'ref_id':order.ref_id, 'payment_mode':order.payment_mode}

@router.post('/payment/verify')
async def verify_payment(Authority: str, Status: Literal['OK','NOK'], db: DB, context: Customer = Depends(customer)):
    if settings.PAYMENT_MODE!='demo':
        raise HTTPException(403, 'تأیید پرداخت آزمایشی غیرفعال است.')
    await db.execute(text('BEGIN IMMEDIATE'))
    order = await db.scalar(select(Order).where(Order.authority_code==Authority, Order.user_id==context.user.id, Order.payment_mode=='demo'))
    if not order:
        raise HTTPException(404, 'سفارش پیدا نشد.')
    if order.status=='pending':
        expired = datetime.fromisoformat(order.created_at).timestamp()<now()-1200
        order.status = 'success' if Status=='OK' and not expired else 'failed'
        order.ref_id = f'DEMO-{secrets.randbelow(90000000)+10000000}' if order.status=='success' else None
        use = await db.get(CouponUse, order.id)
        if use:
            use.status = 'redeemed' if order.status=='success' else 'released'
        details = await db.get(OrderDetails, order.id)
        if details:
            details.fulfillment = 'demo_complete' if order.status=='success' else 'canceled'
        await db.commit()
    return {'receipt_url':f'/payment-result.html?authority={Authority}'}

@router.get('/payment/verify')
async def reject_get_payment():
    raise HTTPException(405, 'تغییر وضعیت پرداخت فقط با درخواست امن از صفحه پرداخت مجاز است.', headers={'Allow':'POST'})

async def order_data(order, db, admin=False):
    details = await db.get(OrderDetails, order.id)
    items = (await db.scalars(select(OrderItem).where(OrderItem.order_id==order.id))).all()
    result = {'id':order.id, 'status':order.status, 'total_amount':order.total_amount, 'created_at':order.created_at, 'ref_id':order.ref_id,
              'payment_mode':order.payment_mode, 'fulfillment':details.fulfillment if details else 'legacy', 'customer_note':details.customer_note if details else '',
              'discount_amount':details.discount_amount if details else 0, 'coupon':details.coupon_code if details else '',
              'items':[{'title':i.title, 'quantity':i.quantity, 'unit_price':i.unit_price, 'product_id':i.product_id} for i in items]}
    if admin:
        result.update({'user_id':order.user_id,'full_name':order.full_name,'mobile':order.mobile,'telegram_id':order.telegram_id,'internal_note':details.internal_note if details else ''})
    return result

@router.get('/account/orders')
async def account_orders(db: DB, page: int = Query(1, ge=1), context: Customer = Depends(customer)):
    rows = (await db.scalars(select(Order).where(Order.user_id==context.user.id).order_by(Order.created_at.desc()).offset((page-1)*20).limit(21))).all()
    return {'items':[await order_data(o,db) for o in rows[:20]], 'has_more':len(rows)>20}

@router.get('/account/orders/{order_id}')
async def account_order(order_id: str, db: DB, context: Customer = Depends(customer)):
    order = await db.get(Order, order_id)
    if not order or order.user_id!=context.user.id:
        raise HTTPException(404, 'سفارش پیدا نشد.')
    return await order_data(order, db)
