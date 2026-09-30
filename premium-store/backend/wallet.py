"""Append-only ledger. All mutations must hold SQLite BEGIN IMMEDIATE."""
from fastapi import HTTPException
from sqlalchemy import select,func
from .models import WalletEntry,OrderExtra,Order,CouponUse,OrderDetails,now
from . import settings

def wallet_mode():
    return 'live' if settings.ENV=='production' else 'demo'

async def balance(db,user_id,mode=None):
    return await db.scalar(select(func.coalesce(func.sum(WalletEntry.amount),0)).where(WalletEntry.user_id==user_id,WalletEntry.mode==(mode or wallet_mode())))

async def entry(db,user_id,amount,kind,reference,note='',actor=None,mode=None):
    mode=mode or wallet_mode()
    previous=await db.scalar(select(WalletEntry).where(WalletEntry.reference==reference))
    if previous:
        if previous.user_id!=user_id or previous.amount!=amount or previous.mode!=mode or previous.kind!=kind or previous.note!=note:
            raise HTTPException(409,'شناسه عملیات برای درخواست متفاوت استفاده شده است.')
        return previous
    if await balance(db,user_id,mode)+amount<0:
        raise HTTPException(409,'موجودی کیف پول کافی نیست.')
    record=WalletEntry(user_id=user_id,amount=amount,mode=mode,kind=kind,reference=reference,note=note,actor_id=actor)
    db.add(record)
    await db.flush()
    return record

async def release(db,order):
    extra=await db.get(OrderExtra,order.id)
    if extra and extra.wallet_used:
        await entry(db,order.user_id,extra.wallet_used,'release','release:'+order.id,'آزادسازی مبلغ سفارش ناموفق',mode=extra.mode)

async def expire_pending(db):
    from datetime import datetime
    rows=(await db.scalars(select(Order).where(Order.status=='pending'))).all()
    for order in rows:
        if datetime.fromisoformat(order.created_at).timestamp()<=now()-1200:
            order.status='failed'
            await release(db,order)
            use=await db.get(CouponUse,order.id)
            if use: use.status='released'
            details=await db.get(OrderDetails,order.id)
            if details: details.fulfillment='canceled'

def entry_data(e):
    return {k:getattr(e,k) for k in ['id','amount','mode','kind','note','created_at']}
