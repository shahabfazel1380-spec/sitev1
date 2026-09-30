"""Wallet, customer dossier and activation management API."""
import json
import re
from typing import Annotated,Literal
from fastapi import APIRouter,Depends,HTTPException,Header,Query
from pydantic import Field,field_validator,ConfigDict
from sqlalchemy import select,func,text,or_
from .db import DB
from .models import (User,Profile,Order,OrderExtra,OrderDetails,WalletEntry,WalletTopup,CustomerContact,OutgoingMessage,ActivationCard,Activation,Audit,now)
from .schemas import Schema
from .security import Customer,Administrator,customer,require,allowed,digest
from .preferences import operations
from .wallet import balance,entry,entry_data,wallet_mode,expire_pending
from .vault import seal,unseal
from . import settings

router=APIRouter(prefix='/api')
Key=Annotated[str,Header(pattern=r'^[a-f0-9-]{36}$')]

def audit(db,c,action,target):
    db.add(Audit(actor_id=c.staff.id,action=action,target=str(target)))

async def get_user(db,uid):
    u=await db.get(User,uid)
    if not u: raise HTTPException(404,'کاربر پیدا نشد.')
    return u

async def wallet_data(db,uid,page=1):
    rows=(await db.scalars(select(WalletEntry).where(WalletEntry.user_id==uid,WalletEntry.mode==wallet_mode()).order_by(WalletEntry.id.desc()).offset((page-1)*30).limit(31))).all()
    return {'balance':await balance(db,uid),'mode':wallet_mode(),'items':[entry_data(e) for e in rows[:30]],'has_more':len(rows)>30}

@router.get('/account/wallet')
async def my_wallet(db:DB,page:int=Query(1,ge=1),c:Customer=Depends(customer)):
    return await wallet_data(db,c.user.id,page)

class TopupInput(Schema):
    amount:int=Field(strict=True,ge=1000,le=500000000)

@router.post('/account/wallet/topups',status_code=201)
async def topup(data:TopupInput,db:DB,idempotency_key:Key,c:Customer=Depends(customer)):
    await db.execute(text('BEGIN IMMEDIATE'))
    config=await operations(db)
    if not config.wallet_enabled or not config.wallet_topup_enabled: raise HTTPException(409,'شارژ کیف پول غیرفعال است.')
    if not c.profile.registered: raise HTTPException(409,'ابتدا پروفایل را تکمیل کنید.')
    if settings.PAYMENT_MODE!='demo' or settings.ENV=='production': raise HTTPException(503,'درگاه واقعی شارژ هنوز متصل نیست.')
    if not config.wallet_min_topup<=data.amount<=config.wallet_max_topup: raise HTTPException(400,'مبلغ خارج از بازه مجاز شارژ است.')
    existing=await db.scalar(select(WalletTopup).where(WalletTopup.request_key==idempotency_key))
    if existing:
        if existing.user_id!=c.user.id or existing.amount!=data.amount: raise HTTPException(409,'شناسه شارژ تکراری است.')
        return {'id':existing.id,'amount':existing.amount,'status':existing.status,'mode':existing.mode}
    row=WalletTopup(user_id=c.user.id,amount=data.amount,mode=wallet_mode(),request_key=idempotency_key)
    db.add(row);await db.commit()
    return {'id':row.id,'amount':row.amount,'status':row.status,'mode':row.mode}

class VerifyTopup(Schema):
    success:bool

@router.post('/account/wallet/topups/{tid}/verify')
async def verify_topup(tid:str,data:VerifyTopup,db:DB,c:Customer=Depends(customer)):
    if settings.ENV=='production' or settings.PAYMENT_MODE!='demo': raise HTTPException(403,'پرداخت آزمایشی غیرفعال است.')
    await db.execute(text('BEGIN IMMEDIATE'))
    row=await db.get(WalletTopup,tid)
    if not row or row.user_id!=c.user.id or row.mode!='demo': raise HTTPException(404,'شارژ پیدا نشد.')
    if row.status=='pending':
        row.status='success' if data.success and row.created_at>now()-1200 else 'failed'
        if row.status=='success': await entry(db,c.user.id,row.amount,'topup','topup:'+row.id,'شارژ آزمایشی کیف پول',mode='demo')
        await db.commit()
    return {'status':row.status,'balance':await balance(db,c.user.id),'mode':row.mode}

@router.get('/admin/customers/{uid}')
async def dossier(uid:int,db:DB,c:Administrator=Depends(require('customers.read'))):
    u=await get_user(db,uid);p=await db.get(Profile,uid)
    stats={}
    if allowed(c.staff,'orders.read'):
        for status in ['pending','success','failed']:
            stats[status]=await db.scalar(select(func.count()).select_from(Order).where(Order.user_id==uid,Order.status==status))
    contact=await db.get(CustomerContact,uid)
    return {'id':u.id,'full_name':u.full_name,'mobile':u.mobile,'telegram_id':u.telegram_id,'created_at':u.created_at,'blocked':bool(p and p.blocked),'balance':await balance(db,uid) if allowed(c.staff,'wallet.read') else None,'wallet_mode':wallet_mode(),'stats':stats,'telegram_chat_id':contact.telegram_chat_id if contact and allowed(c.staff,'messages.send') else ''}

@router.get('/admin/customers/{uid}/orders')
async def customer_orders(uid:int,db:DB,page:int=Query(1,ge=1),c:Administrator=Depends(require('orders.read'))):
    from .commerce import order_data
    await get_user(db,uid)
    rows=(await db.scalars(select(Order).where(Order.user_id==uid).order_by(Order.created_at.desc()).offset((page-1)*20).limit(21))).all()
    return {'items':[await order_data(o,db,True) for o in rows[:20]],'has_more':len(rows)>20}

@router.get('/admin/orders/{oid}')
async def order_detail(oid:str,db:DB,c:Administrator=Depends(require('orders.read'))):
    from .commerce import order_data
    o=await db.get(Order,oid)
    if not o: raise HTTPException(404,'سفارش پیدا نشد.')
    return await order_data(o,db,True)

@router.post('/admin/orders/{oid}/credentials')
async def order_credentials(oid:str,db:DB,c:Administrator=Depends(require('orders.secrets'))):
    row=await db.get(OrderExtra,oid)
    if not row: return {'items':[]}
    audit(db,c,'order.credentials_reveal',oid);await db.commit()
    return {'items':json.loads(unseal(row.credentials)) if row.credentials else []}

@router.get('/admin/customers/{uid}/wallet')
async def customer_wallet(uid:int,db:DB,page:int=Query(1,ge=1),c:Administrator=Depends(require('wallet.read'))):
    await get_user(db,uid)
    return await wallet_data(db,uid,page)

class AdjustInput(Schema):
    amount:int=Field(strict=True,ge=-500000000,le=500000000)
    note:str=Field(min_length=3,max_length=500)

@router.post('/admin/customers/{uid}/wallet')
async def adjust_wallet(uid:int,data:AdjustInput,db:DB,idempotency_key:Key,c:Administrator=Depends(require('wallet.adjust'))):
    if not data.amount: raise HTTPException(400,'مبلغ صفر مجاز نیست.')
    await db.execute(text('BEGIN IMMEDIATE'));await get_user(db,uid)
    await entry(db,uid,data.amount,'adjustment','adjust:'+idempotency_key,data.note,c.staff.id)
    audit(db,c,'wallet.adjust',uid);await db.commit()
    return {'balance':await balance(db,uid),'mode':wallet_mode()}

class RefundInput(Schema):
    note:str=Field(min_length=3,max_length=500)

@router.post('/admin/orders/{oid}/refund')
async def refund(oid:str,data:RefundInput,db:DB,c:Administrator=Depends(require('wallet.refund'))):
    await db.execute(text('BEGIN IMMEDIATE'))
    o=await db.get(Order,oid)
    if not o or o.status!='success': raise HTTPException(409,'فقط سفارش پرداخت‌شده قابل بازپرداخت است.')
    extra=await db.get(OrderExtra,oid)
    if not extra:
        extra=OrderExtra(order_id=oid,payable=o.total_amount,mode='demo' if o.payment_mode=='demo' else 'live',wallet_used=0)
        db.add(extra);await db.flush()
    if not extra.refunded:
        await entry(db,o.user_id,o.total_amount,'refund','refund:'+oid,data.note,c.staff.id,extra.mode)
        extra.refunded=True
        detail=await db.get(OrderDetails,oid)
        if detail: detail.fulfillment='refunded'
        audit(db,c,'order.wallet_refund',oid)
        await db.commit()
    return {'refunded':True,'mode':extra.mode}

class ContactInput(Schema):
    telegram_chat_id:str=Field(default='',pattern=r'^[0-9]{0,20}$')

@router.put('/admin/customers/{uid}/contact')
async def contact(uid:int,data:ContactInput,db:DB,c:Administrator=Depends(require('messages.send'))):
    await get_user(db,uid)
    row=await db.get(CustomerContact,uid)
    if not row: row=CustomerContact(user_id=uid);db.add(row)
    row.telegram_chat_id=data.telegram_chat_id
    audit(db,c,'customer.telegram_recipient',uid);await db.commit()
    return {'ok':True}

class SendInput(Schema):
    channels:list[Literal['sms','telegram']]=Field(min_length=1,max_length=2)
    body:str=Field(min_length=1,max_length=1000)

@router.post('/admin/customers/{uid}/messages')
async def send_message(uid:int,data:SendInput,db:DB,idempotency_key:Key,c:Administrator=Depends(require('messages.send'))):
    from .notifications import queue
    await db.execute(text('BEGIN IMMEDIATE'));await get_user(db,uid)
    config=await operations(db)
    for channel in set(data.channels):
        if not (config.sms_notifications_enabled if channel=='sms' else config.telegram_messages_enabled):
            raise HTTPException(409,'کانال انتخاب‌شده در تنظیمات غیرفعال است.')
        if channel=='telegram':
            contact=await db.get(CustomerContact,uid)
            if not contact or not contact.telegram_chat_id: raise HTTPException(409,'شناسه عددی تلگرام مشتری را پس از تأیید ثبت کنید؛ یوزرنیم کافی نیست.')
        ref=f'manual:{idempotency_key}:{channel}'
        existing=await db.scalar(select(OutgoingMessage).where(OutgoingMessage.reference==ref))
        if existing and (existing.user_id!=uid or existing.body!=data.body): raise HTTPException(409,'شناسه ارسال برای پیام دیگری استفاده شده است.')
        await queue(db,uid,channel,data.body,ref)
    audit(db,c,'customer.message_queued',uid);await db.commit()
    return {'ok':True}

@router.get('/admin/customers/{uid}/messages')
async def messages(uid:int,db:DB,page:int=Query(1,ge=1),c:Administrator=Depends(require('messages.read'))):
    rows=(await db.scalars(select(OutgoingMessage).where(OutgoingMessage.user_id==uid).order_by(OutgoingMessage.id.desc()).offset((page-1)*30).limit(31))).all()
    return {'items':[{k:getattr(m,k) for k in ['id','channel','body','status','error','created_at']} for m in rows[:30]],'has_more':len(rows)>30}

class CardInput(Schema):
    label:str=Field(min_length=2,max_length=100)
    kind:Literal['single_use','reloadable']='single_use'
    number:str=Field(default='',max_length=23)
    note:str=Field(default='',max_length=1000)
    active:bool=True
    revision:int|None=None
    @field_validator('number')
    @classmethod
    def number_value(cls,v):
        v=v.replace(' ','').replace('-','')
        if v and not re.fullmatch(r'[0-9]{12,19}',v): raise ValueError('شماره کارت نامعتبر است')
        return v

def card_data(c):
    return {k:getattr(c,k) for k in ['id','label','kind','last_four','note','active','revision']}

@router.get('/admin/activation-cards')
async def cards(db:DB,q:str=Query('',max_length=100),page:int=Query(1,ge=1),c:Administrator=Depends(require('activations.read'))):
    digits=q.replace(' ','').replace('-','')
    rows=(await db.scalars(select(ActivationCard).where(or_(ActivationCard.label.contains(q,autoescape=True),ActivationCard.last_four==digits,ActivationCard.number_hash==digest('card:'+digits))).order_by(ActivationCard.id.desc()).offset((page-1)*30).limit(31))).all()
    return {'items':[card_data(x) for x in rows[:30]],'has_more':len(rows)>30}

@router.post('/admin/activation-cards',status_code=201)
async def create_card(data:CardInput,db:DB,c:Administrator=Depends(require('activations.write'))):
    if not data.number: raise HTTPException(400,'شماره کارت لازم است.')
    row=ActivationCard(label=data.label,kind=data.kind,last_four=data.number[-4:],number_hash=digest('card:'+data.number),number_encrypted=seal(data.number),note=data.note,active=data.active)
    db.add(row);await db.flush();audit(db,c,'activation.card_create',row.id);await db.commit()
    return card_data(row)

@router.put('/admin/activation-cards/{cid}')
async def update_card(cid:int,data:CardInput,db:DB,c:Administrator=Depends(require('activations.write'))):
    await db.execute(text('BEGIN IMMEDIATE'))
    row=await db.get(ActivationCard,cid)
    if not row: raise HTTPException(404,'کارت پیدا نشد.')
    if row.revision!=data.revision: raise HTTPException(409,'نسخه کارت تغییر کرده؛ صفحه را تازه کنید.')
    for k in ['label','kind','note','active']: setattr(row,k,getattr(data,k))
    if data.number:
        row.last_four=data.number[-4:];row.number_hash=digest('card:'+data.number);row.number_encrypted=seal(data.number)
    row.revision+=1;audit(db,c,'activation.card_update',cid);await db.commit()
    return card_data(row)

@router.post('/admin/activation-cards/{cid}/reveal')
async def reveal_card(cid:int,db:DB,c:Administrator=Depends(require('activations.secrets'))):
    row=await db.get(ActivationCard,cid)
    if not row: raise HTTPException(404,'کارت پیدا نشد.')
    audit(db,c,'activation.card_reveal',cid);await db.commit()
    return {'number':unseal(row.number_encrypted)}

class ActivationInput(Schema):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=False)
    card_id:int=Field(gt=0)
    user_id:int=Field(gt=0)
    order_id:str|None=Field(default=None,max_length=36)
    service:str=Field(min_length=2,max_length=150)
    email:str=Field(min_length=3,max_length=254)
    account:str=Field(default='',max_length=200)
    password:str=Field(default='',max_length=256)
    paid_at:int=Field(gt=0)
    renewal_at:int=Field(default=0,ge=0)
    auto_renew:bool=False
    note:str=Field(default='',max_length=3000)
    active:bool=True
    revision:int|None=None

async def activation_data(a,db):
    u=await db.get(User,a.user_id);card=await db.get(ActivationCard,a.card_id)
    result={k:getattr(a,k) for k in ['id','card_id','user_id','order_id','service','email','account','paid_at','renewal_at','auto_renew','note','active','revision']}
    result.update({'full_name':u.full_name,'mobile':u.mobile,'card_label':card.label,'last_four':card.last_four,'has_password':bool(a.password_encrypted)})
    return result

async def reminders(db):
    cfg=await operations(db)
    query=select(Activation).where(Activation.active==True,Activation.auto_renew==True,Activation.renewal_at>0,Activation.renewal_at<=now()+cfg.activation_reminder_days*86400)
    count=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.scalars(query.order_by(Activation.renewal_at).limit(50))).all()
    return {'items':[await activation_data(a,db) for a in rows],'count':count,'days':cfg.activation_reminder_days}

@router.get('/admin/activation-reminders')
async def activation_reminders(db:DB,c:Administrator=Depends(require('activations.read'))):
    return await reminders(db)

@router.get('/admin/activations')
async def activations(db:DB,q:str=Query('',max_length=254),page:int=Query(1,ge=1),c:Administrator=Depends(require('activations.read'))):
    digits=q.replace(' ','').replace('-','')
    query=select(Activation).join(User,User.id==Activation.user_id).join(ActivationCard,ActivationCard.id==Activation.card_id).where(or_(Activation.email.contains(q,autoescape=True),Activation.service.contains(q,autoescape=True),Activation.account.contains(q,autoescape=True),User.mobile.contains(q,autoescape=True),Activation.order_id.contains(q,autoescape=True),ActivationCard.number_hash==digest('card:'+digits),ActivationCard.last_four==digits,ActivationCard.label.contains(q,autoescape=True)))
    rows=(await db.scalars(query.order_by(Activation.id.desc()).offset((page-1)*30).limit(31))).all()
    return {'items':[await activation_data(a,db) for a in rows[:30]],'has_more':len(rows)>30}

async def validate_activation(data,db,existing=None):
    await get_user(db,data.user_id)
    card=await db.get(ActivationCard,data.card_id)
    if not card or (not card.active and (not existing or existing.card_id!=data.card_id)): raise HTTPException(400,'کارت فعال پیدا نشد.')
    if data.order_id:
        order=await db.get(Order,data.order_id)
        if not order or order.user_id!=data.user_id: raise HTTPException(400,'سفارش با مشتری انتخاب‌شده همخوانی ندارد.')
    if data.auto_renew and not data.renewal_at: raise HTTPException(400,'تاریخ برداشت خودکار لازم است.')
    if card.kind=='single_use':
        used=await db.scalar(select(Activation.id).where(Activation.card_id==card.id,Activation.id!=(existing.id if existing else 0)))
        if used: raise HTTPException(409,'این کارت یک‌بارمصرف قبلاً استفاده شده است.')

@router.post('/admin/activations',status_code=201)
async def create_activation(data:ActivationInput,db:DB,c:Administrator=Depends(require('activations.write'))):
    await db.execute(text('BEGIN IMMEDIATE'));await validate_activation(data,db)
    row=Activation(**data.model_dump(exclude={'password','revision'}),password_encrypted=seal(data.password))
    db.add(row);await db.flush();audit(db,c,'activation.create',row.id);await db.commit()
    return await activation_data(row,db)

@router.put('/admin/activations/{aid}')
async def update_activation(aid:int,data:ActivationInput,db:DB,c:Administrator=Depends(require('activations.write'))):
    await db.execute(text('BEGIN IMMEDIATE'))
    row=await db.get(Activation,aid)
    if not row: raise HTTPException(404,'فعال‌سازی پیدا نشد.')
    if row.revision!=data.revision: raise HTTPException(409,'اطلاعات تغییر کرده؛ صفحه را تازه کنید.')
    await validate_activation(data,db,row)
    for k,v in data.model_dump(exclude={'password','revision'}).items(): setattr(row,k,v)
    if data.password: row.password_encrypted=seal(data.password)
    row.revision+=1;audit(db,c,'activation.update',aid);await db.commit()
    return await activation_data(row,db)

@router.post('/admin/activations/{aid}/reveal')
async def reveal_activation(aid:int,db:DB,c:Administrator=Depends(require('activations.secrets'))):
    row=await db.get(Activation,aid)
    if not row: raise HTTPException(404,'فعال‌سازی پیدا نشد.')
    audit(db,c,'activation.password_reveal',aid);await db.commit()
    return {'password':unseal(row.password_encrypted)}
