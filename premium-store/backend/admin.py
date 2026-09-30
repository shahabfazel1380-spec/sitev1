import asyncio
import io
import os
import secrets
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field, field_validator
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from . import settings
from .commerce import order_data, product_data, public_config
from .db import DB
from .models import (Audit, Conversation, Coupon, CustomerSession, Message, Order, OrderDetails,
                     Product, Profile, Setting, Staff, StaffSession, User, now)
from .schemas import CouponInput, MessageInput, ProductInput, Schema, StaffInput
from .security import Administrator, PERMISSIONS, administrator, allowed, owner, password_hash, rate_limit, require
from .support import conversation_data, message_data

router = APIRouter(prefix='/api/admin')

def audit(db, context, action, target):
    db.add(Audit(actor_id=context.staff.id, action=action, target=str(target)))

@router.get('/dashboard')
async def dashboard(db: DB, context: Administrator = Depends(require('dashboard.read'))):
    result = {}
    for name, model, permission in [('products',Product,'products.read'),('orders',Order,'orders.read'),('customers',Profile,'customers.read')]:
        if allowed(context.staff,permission):
            result[name] = await db.scalar(select(func.count()).select_from(model))
    for kind, permission in [('ticket','tickets.read'),('chat','chat.read')]:
        if allowed(context.staff,permission):
            result[kind] = await db.scalar(select(func.count()).select_from(Conversation).where(Conversation.kind==kind, Conversation.status=='open'))
    if allowed(context.staff,'orders.read'):
        result['real_revenue'] = await db.scalar(select(func.coalesce(func.sum(Order.total_amount),0)).where(Order.status=='success', Order.payment_mode!='demo'))
    return result

@router.get('/products')
async def admin_products(db: DB, q: str = Query('',max_length=100), page: int = Query(1,ge=1), context: Administrator = Depends(require('products.read'))):
    rows = (await db.scalars(select(Product).where(Product.title.contains(q,autoescape=True)).order_by(Product.id.desc()).offset((page-1)*30).limit(31))).all()
    return {'items':[product_data(p,True) for p in rows[:30]], 'has_more':len(rows)>30}

@router.post('/products', status_code=201)
async def create_product(data: ProductInput, db: DB, context: Administrator = Depends(require('products.create'))):
    if data.published and not allowed(context.staff,'products.publish'):
        raise HTTPException(403,'مجوز انتشار محصول را ندارید؛ محصول را پیش‌نویس ذخیره کنید.')
    product = Product(**data.model_dump(exclude={'revision'}))
    db.add(product)
    await db.flush()
    audit(db,context,'product.create',product.id)
    await db.commit()
    return product_data(product,True)

@router.put('/products/{product_id}')
async def edit_product(product_id: int, data: ProductInput, db: DB, context: Administrator = Depends(require('products.update'))):
    await db.execute(text('BEGIN IMMEDIATE'))
    product = await db.get(Product,product_id)
    if not product:
        raise HTTPException(404,'محصول پیدا نشد.')
    if data.revision!=product.revision:
        raise HTTPException(409,'محصول توسط کارمند دیگری تغییر کرده است؛ فهرست را تازه کنید.')
    if data.published!=product.published and not allowed(context.staff,'products.publish'):
        raise HTTPException(403,'مجوز تغییر انتشار محصول را ندارید.')
    for key,value in data.model_dump(exclude={'revision'}).items():
        setattr(product,key,value)
    product.revision += 1
    product.updated_at=now()
    audit(db,context,'product.update',product.id)
    await db.commit()
    return product_data(product,True)

class ArchiveInput(Schema):
    archived: bool

@router.post('/products/{product_id}/archive')
async def archive_product(product_id: int, data: ArchiveInput, db: DB, context: Administrator = Depends(require('products.archive'))):
    await db.execute(text('BEGIN IMMEDIATE'))
    product = await db.get(Product,product_id)
    if not product:
        raise HTTPException(404,'محصول پیدا نشد.')
    # Restore stays draft unless the actor can publish.
    if not data.archived and product.published and not allowed(context.staff,'products.publish'):
        raise HTTPException(403,'بازیابی محصول منتشرشده نیازمند مجوز انتشار است.')
    product.archived=data.archived
    product.revision += 1
    product.updated_at=now()
    audit(db,context,'product.archive' if data.archived else 'product.restore',product.id)
    await db.commit()
    return {'ok':True}

def store_image(data, target):
    from PIL import Image, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS=20000000
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {'JPEG','PNG','WEBP'}:
                raise ValueError('نوع تصویر مجاز نیست.')
            image.load()
            image.thumbnail((2400,2400))
            image.convert('RGB').save(target,'WEBP',quality=88)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as error:
        raise ValueError('تصویر معتبر نیست یا ابعاد بسیار بزرگی دارد.') from error

@router.post('/media', status_code=201)
async def upload_media(request: Request, context: Administrator = Depends(require('media.upload'))):
    await rate_limit('media',str(context.staff.id),20,600)
    mime = request.headers.get('content-type','').split(';')[0]
    if mime not in {'image/jpeg','image/png','image/webp','video/mp4'}:
        raise HTTPException(400,'فقط JPEG، PNG، WebP و MP4 قابل بارگذاری است.')
    size=0
    parts=[]
    async for chunk in request.stream():
        size+=len(chunk)
        if size>25*1024*1024:
            raise HTTPException(413,'حداکثر حجم فایل ۲۵ مگابایت است.')
        parts.append(chunk)
    data=b''.join(parts)
    name=secrets.token_hex(16)+('.mp4' if mime=='video/mp4' else '.webp')
    target=settings.MEDIA_DIR/name
    if mime=='video/mp4':
        if len(data)<12 or data[4:8]!=b'ftyp':
            raise HTTPException(400,'فایل MP4 معتبر نیست.')
        await asyncio.to_thread(target.write_bytes,data)
    else:
        try:
            await asyncio.to_thread(store_image,data,target)
        except ValueError as error:
            raise HTTPException(400,str(error)) from None
    return {'url':'/media/'+name}

@router.get('/orders')
async def admin_orders(db: DB, page: int = Query(1,ge=1), q: str = Query('',max_length=100), context: Administrator = Depends(require('orders.read'))):
    rows = (await db.scalars(select(Order).where((Order.id.contains(q,autoescape=True)) | (Order.mobile.contains(q,autoescape=True))).order_by(Order.created_at.desc()).offset((page-1)*20).limit(21))).all()
    return {'items':[await order_data(o,db,True) for o in rows[:20]], 'has_more':len(rows)>20}

class OrderUpdate(Schema):
    fulfillment: Literal['awaiting_payment','processing','delivered','canceled','demo_complete']
    customer_note: str = Field(default='',max_length=5000)
    internal_note: str = Field(default='',max_length=5000)

@router.put('/orders/{order_id}')
async def update_order(order_id: str, data: OrderUpdate, db: DB, context: Administrator = Depends(require('orders.update'))):
    await db.execute(text('BEGIN IMMEDIATE'))
    order=await db.get(Order,order_id)
    if not order:
        raise HTTPException(404,'سفارش پیدا نشد.')
    from .models import OrderExtra
    extra=await db.get(OrderExtra,order_id)
    if extra and extra.refunded: raise HTTPException(409,'سفارش بازپرداخت شده است و وضعیت انجام آن قابل تغییر نیست.')
    if data.fulfillment in {'processing','delivered'} and (order.status!='success' or order.payment_mode=='demo'):
        raise HTTPException(409,'سفارش آزمایشی یا پرداخت‌نشده قابل تحویل نیست.')
    if data.fulfillment=='canceled' and order.status=='pending':
        from .wallet import release
        from .models import CouponUse
        order.status='failed'
        await release(db,order)
        use=await db.get(CouponUse,order_id)
        if use: use.status='released'
    if data.fulfillment=='demo_complete' and not (order.payment_mode=='demo' and order.status=='success'):
        raise HTTPException(409,'وضعیت آزمایشی با این سفارش سازگار نیست.')
    details=await db.get(OrderDetails,order_id)
    if not details:
        details=OrderDetails(order_id=order_id,subtotal=order.total_amount)
        db.add(details)
    for key,value in data.model_dump().items():
        setattr(details,key,value)
    audit(db,context,'order.update',order_id)
    await db.commit()
    return {'ok':True}

@router.get('/customers')
async def customers(db: DB, page: int = Query(1,ge=1), q: str = Query('',max_length=100), context: Administrator = Depends(require('customers.read'))):
    rows=(await db.execute(select(User,Profile).join(Profile,User.id==Profile.user_id).where((User.mobile.contains(q,autoescape=True)) | (User.full_name.contains(q,autoescape=True))).order_by(User.id.desc()).offset((page-1)*30).limit(31))).all()
    return {'items':[{'id':u.id,'full_name':u.full_name,'mobile':u.mobile,'telegram_id':u.telegram_id,'registered':p.registered,'blocked':p.blocked,'created_at':u.created_at} for u,p in rows[:30]], 'has_more':len(rows)>30}

class BlockInput(Schema):
    blocked: bool

@router.put('/customers/{user_id}')
async def block_customer(user_id: int, data: BlockInput, db: DB, context: Administrator = Depends(require('customers.update'))):
    profile=await db.get(Profile,user_id)
    if not profile:
        raise HTTPException(404,'کاربر پیدا نشد.')
    profile.blocked=data.blocked
    if data.blocked:
        await db.execute(delete(CustomerSession).where(CustomerSession.user_id==user_id))
    audit(db,context,'customer.block' if data.blocked else 'customer.unblock',user_id)
    await db.commit()
    return {'ok':True}

@router.get('/discounts')
async def discounts(db: DB, page: int = Query(1,ge=1), context: Administrator = Depends(require('discounts.read'))):
    rows=(await db.scalars(select(Coupon).order_by(Coupon.id.desc()).offset((page-1)*30).limit(31))).all()
    return {'items':[{key:getattr(c,key) for key in ['id',*CouponInput.model_fields]} for c in rows[:30]], 'has_more':len(rows)>30}

@router.post('/discounts',status_code=201)
async def create_discount(data: CouponInput, db: DB, context: Administrator = Depends(require('discounts.write'))):
    coupon=Coupon(**data.model_dump())
    db.add(coupon)
    try:
        await db.flush()
        audit(db,context,'discount.create',coupon.id)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409,'این کد تخفیف از قبل وجود دارد.')
    return {'id':coupon.id}

@router.put('/discounts/{coupon_id}')
async def update_discount(coupon_id: int, data: CouponInput, db: DB, context: Administrator = Depends(require('discounts.write'))):
    coupon=await db.get(Coupon,coupon_id)
    if not coupon:
        raise HTTPException(404,'کد تخفیف پیدا نشد.')
    for key,value in data.model_dump().items():
        setattr(coupon,key,value)
    audit(db,context,'discount.update',coupon_id)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409,'کد تخفیف تکراری است.')
    return {'ok':True}

def check_conversation_permission(context,conversation,action):
    key=('chat' if conversation.kind=='chat' else 'tickets')+'.'+action
    if not allowed(context.staff,key):
        raise HTTPException(403,'مجوز این بخش پشتیبانی را ندارید.')

@router.get('/conversations')
async def admin_conversations(db: DB, kind: str = Query('ticket',pattern='^(ticket|chat)$'), state: str = Query('',pattern='^(|open|answered|closed)$'), page: int = Query(1,ge=1), context: Administrator = Depends(administrator)):
    permission=('chat' if kind=='chat' else 'tickets')+'.read'
    if not allowed(context.staff,permission):
        raise HTTPException(403,'مجوز مشاهده ندارید.')
    query=select(Conversation).where(Conversation.kind==kind)
    if state:
        query=query.where(Conversation.status==state)
    rows=(await db.scalars(query.order_by(Conversation.updated_at.desc()).offset((page-1)*30).limit(31))).all()
    return {'items':[conversation_data(c) for c in rows[:30]],'has_more':len(rows)>30}

@router.get('/conversations/{conversation_id}')
async def admin_conversation(conversation_id: str, db: DB, after: int = Query(0,ge=0), context: Administrator = Depends(administrator)):
    conversation=await db.get(Conversation,conversation_id)
    if not conversation:
        raise HTTPException(404,'گفت‌وگو پیدا نشد.')
    check_conversation_permission(context,conversation,'read')
    rows=(await db.scalars(select(Message).where(Message.conversation_id==conversation_id,Message.id>after).order_by(Message.id).limit(100))).all()
    return {'conversation':conversation_data(conversation),'messages':[message_data(m) for m in rows],'has_more':len(rows)==100}

@router.post('/conversations/{conversation_id}/messages')
async def admin_message(conversation_id: str, data: MessageInput, db: DB, context: Administrator = Depends(administrator)):
    conversation=await db.get(Conversation,conversation_id)
    if not conversation:
        raise HTTPException(404,'گفت‌وگو پیدا نشد.')
    check_conversation_permission(context,conversation,'reply')
    if conversation.status=='closed':
        raise HTTPException(409,'گفت‌وگو بسته است؛ ابتدا آن را باز کنید.')
    message=Message(conversation_id=conversation_id,sender='staff',staff_id=context.staff.id,body=data.body)
    db.add(message)
    conversation.status='answered'
    conversation.updated_at=now()
    await db.flush()
    config=await operations(db)
    if conversation.kind=='ticket' and config.ticket_sms_enabled:
        from .notifications import queue
        await queue(db,conversation.user_id,'sms',config.ticket_sms_text,'ticket:'+str(message.id))
    audit(db,context,'support.reply',conversation_id)
    await db.commit()
    return message_data(message)

class ConversationUpdate(Schema):
    status: Literal['open','answered','closed']
    assigned_to: int | None = Field(default=None,gt=0)

@router.put('/conversations/{conversation_id}')
async def update_conversation(conversation_id: str, data: ConversationUpdate, db: DB, context: Administrator = Depends(administrator)):
    conversation=await db.get(Conversation,conversation_id)
    if not conversation:
        raise HTTPException(404,'گفت‌وگو پیدا نشد.')
    check_conversation_permission(context,conversation,'manage')
    if data.assigned_to:
        staff=await db.get(Staff,data.assigned_to)
        if not staff or not staff.active or staff.deleted or not allowed(staff,('chat' if conversation.kind=='chat' else 'tickets')+'.reply'):
            raise HTTPException(400,'کارمند انتخاب‌شده مجوز پاسخ‌گویی ندارد.')
    conversation.status=data.status
    conversation.assigned_to=data.assigned_to
    conversation.updated_at=now()
    audit(db,context,'support.update',conversation_id)
    await db.commit()
    return {'ok':True}

@router.get('/support-staff')
async def support_staff(db: DB, context: Administrator = Depends(administrator)):
    if not any(allowed(context.staff,p) for p in ['chat.manage','tickets.manage']):
        raise HTTPException(403,'مجوز ارجاع ندارید.')
    rows=(await db.scalars(select(Staff).where(Staff.active==True,Staff.deleted==False))).all()
    return [{'id':s.id,'name':s.name,'chat':allowed(s,'chat.reply'),'tickets':allowed(s,'tickets.reply')} for s in rows if s.owner or 'chat.reply' in s.permissions or 'tickets.reply' in s.permissions]

@router.get('/staff')
async def staff_list(db: DB, context: Administrator = Depends(owner)):
    rows=(await db.scalars(select(Staff).where(Staff.deleted==False).order_by(Staff.id))).all()
    return {'permissions':PERMISSIONS,'items':[{'id':s.id,'username':s.username,'name':s.name,'permissions':s.permissions,'active':s.active,'owner':s.owner} for s in rows]}

@router.post('/staff',status_code=201)
async def create_staff(data: StaffInput, db: DB, context: Administrator = Depends(owner)):
    if not data.password:
        raise HTTPException(400,'رمز اولیه حداقل ۱۲ کاراکتر لازم است.')
    staff=Staff(username=data.username.lower(),name=data.name,password_hash=await asyncio.to_thread(password_hash,data.password),permissions=data.permissions,active=data.active)
    db.add(staff)
    try:
        await db.flush()
        audit(db,context,'staff.create',staff.id)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409,'نام کاربری تکراری است.')
    return {'id':staff.id}

@router.put('/staff/{staff_id}')
async def edit_staff(staff_id: int, data: StaffInput, db: DB, context: Administrator = Depends(owner)):
    staff=await db.get(Staff,staff_id)
    if not staff or staff.deleted:
        raise HTTPException(404,'کارمند پیدا نشد.')
    if staff.owner:
        raise HTTPException(403,'تغییر مالک از این بخش مجاز نیست؛ ابزار مدیریت سرور را استفاده کنید.')
    staff.username=data.username.lower()
    staff.name=data.name
    staff.permissions=data.permissions
    staff.active=data.active
    if data.password:
        staff.password_hash=await asyncio.to_thread(password_hash,data.password)
    await db.execute(delete(StaffSession).where(StaffSession.staff_id==staff_id))
    audit(db,context,'staff.update_and_revoke_sessions',staff_id)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409,'نام کاربری تکراری است.')
    return {'ok':True}

@router.delete('/staff/{staff_id}')
async def delete_staff(staff_id: int, db: DB, context: Administrator = Depends(owner)):
    staff=await db.get(Staff,staff_id)
    if not staff or staff.deleted:
        raise HTTPException(404,'کارمند پیدا نشد.')
    if staff.owner:
        raise HTTPException(403,'حذف مالک از پنل مجاز نیست.')
    staff.active=False
    staff.deleted=True
    await db.execute(delete(StaffSession).where(StaffSession.staff_id==staff_id))
    audit(db,context,'staff.delete',staff_id)
    await db.commit()
    return {'ok':True}

from .preferences import OperationsInput, operations, save_operations

class SettingsInput(OperationsInput):
    telegram_url: str = Field(default='',max_length=2048)
    instagram_url: str = Field(default='',max_length=2048)
    support_url: str = Field(default='',max_length=2048)
    bot_url: str = Field(default='',max_length=2048)
    support_hours: str = Field(default='',max_length=200)
    store_notice: str = Field(default='',max_length=500)

    @field_validator('telegram_url','instagram_url','support_url','bot_url')
    @classmethod
    def social_url(cls,value,info):
        if not value:
            return ''
        parsed=urlsplit(value)
        domains={'instagram.com','www.instagram.com'} if info.field_name=='instagram_url' else {'t.me','telegram.me'}
        if parsed.scheme!='https' or parsed.hostname not in domains or parsed.username or parsed.password:
            raise ValueError('لینک شبکه اجتماعی معتبر نیست')
        return value

@router.get('/settings')
async def admin_settings(db: DB, context: Administrator = Depends(require('settings.read'))):
    return {**await public_config(db), **(await operations(db)).model_dump(), 'technical':{'sms_mode':settings.SMS_MODE,'payment_mode':settings.PAYMENT_MODE,'sms_ready':bool(os.getenv('KAVENEGAR_API_KEY')),'telegram_ready':bool(os.getenv('TELEGRAM_BOT_TOKEN')),'environment':settings.ENV}}

@router.put('/settings')
async def update_settings(data: SettingsInput, db: DB, context: Administrator = Depends(require('settings.write'))):
    await save_operations(db,OperationsInput(**data.model_dump(include=set(OperationsInput.model_fields))))
    for key,value in data.model_dump(exclude=set(OperationsInput.model_fields)).items():
        row=await db.get(Setting,key)
        if row:
            row.value=value
        else:
            db.add(Setting(key=key,value=value))
    audit(db,context,'settings.update','public')
    await db.commit()
    return {'ok':True}

@router.get('/audit')
async def audit_log(db: DB, page: int = Query(1,ge=1), context: Administrator = Depends(require('audit.read'))):
    rows=(await db.scalars(select(Audit).order_by(Audit.id.desc()).offset((page-1)*50).limit(51))).all()
    return {'items':[{key:getattr(a,key) for key in ['id','actor_id','action','target','created_at']} for a in rows[:50]],'has_more':len(rows)>50}
