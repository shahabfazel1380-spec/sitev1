"""Persistent delivery queue. Ambiguous deliveries require manual review, never blind retries."""
import asyncio
import os
import httpx
from sqlalchemy import select,text
from . import settings
from .db import Session
from .models import OutgoingMessage,User,CustomerContact,now
from .preferences import operations

async def queue(db,user_id,channel,body,reference):
    previous=await db.scalar(select(OutgoingMessage).where(OutgoingMessage.reference==reference))
    if previous: return previous
    msg=OutgoingMessage(user_id=user_id,channel=channel,body=body,reference=reference)
    db.add(msg)
    return msg

async def deliver_once():
    async with Session() as db:
        await db.execute(text('BEGIN IMMEDIATE'))
        msg=await db.scalar(select(OutgoingMessage).where(OutgoingMessage.status=='pending').order_by(OutgoingMessage.id).limit(1))
        if not msg: return
        config=await operations(db)
        user=await db.get(User,msg.user_id)
        contact=await db.get(CustomerContact,msg.user_id)
        enabled=config.sms_notifications_enabled if msg.channel=='sms' else config.telegram_messages_enabled
        if not enabled:
            msg.status='disabled'; msg.error='ارسال این کانال در تنظیمات غیرفعال است.'
            await db.commit(); return
        if settings.ENV!='production':
            msg.status='simulated'; msg.error='محیط آزمایشی؛ پیامی ارسال نشد.'
            await db.commit(); return
        if msg.channel=='telegram' and (not contact or not contact.telegram_chat_id):
            msg.status='failed'; msg.error='شناسه عددی تأییدشده تلگرام ثبت نشده است.'
            await db.commit(); return
        key=os.getenv('KAVENEGAR_API_KEY','') if msg.channel=='sms' else os.getenv('TELEGRAM_BOT_TOKEN','')
        if not key or (msg.channel=='sms' and settings.SMS_MODE!='kavenegar'):
            msg.status='failed'; msg.error='تنظیمات سرویس روی سرور کامل نیست.'
            await db.commit(); return
        msg.status='sending';msg.updated_at=now()
        await db.commit()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if msg.channel=='sms':
                    payload={'receptor':user.mobile,'message':msg.body}
                    if config.sms_sender: payload['sender']=config.sms_sender
                    response=await client.post(f'https://api.kavenegar.com/v1/{key}/sms/send.json',data=payload)
                    ok=response.is_success and response.json().get('return',{}).get('status')==200
                else:
                    response=await client.post(f'https://api.telegram.org/bot{key}/sendMessage',json={'chat_id':contact.telegram_chat_id,'text':msg.body})
                    ok=response.is_success and response.json().get('ok') is True
            msg.status='sent' if ok else 'failed'
            msg.error='' if ok else 'سرویس درخواست را رد کرد؛ پنل سرویس را بررسی کنید.'
        except Exception:
            msg.status='unknown'; msg.error='نتیجه ارسال نامشخص است؛ قبل از ارسال دوباره پنل سرویس را بررسی کنید.'
        msg.updated_at=now()
        await db.commit()

async def worker():
    # A process stopped after dispatch must not resend the same message automatically.
    async with Session() as db:
        rows=(await db.scalars(select(OutgoingMessage).where(OutgoingMessage.status=='sending'))).all()
        for m in rows:
            m.status='unknown';m.error='ارسال قبلی قطع شد؛ نتیجه نیازمند بررسی سرویس است.'
        await db.commit()
    while True:
        try: await deliver_once()
        except Exception:
            import logging
            logging.getLogger('premiumstore').warning('Message queue processing deferred; inspect delivery status.')
        await asyncio.sleep(2)
