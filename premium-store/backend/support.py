from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from .db import DB
from .models import Conversation, Message, Order, Staff, now
from .schemas import ConversationInput, MessageInput
from .security import Customer, customer, rate_limit

router = APIRouter(prefix='/api')

def conversation_data(c):
    return {key:getattr(c,key) for key in ['id','user_id','kind','subject','order_id','priority','status','assigned_to','created_at','updated_at']}

def message_data(m):
    return {'id':m.id,'sender':m.sender,'body':m.body,'created_at':m.created_at}

@router.get('/support/presence')
async def presence(db: DB):
    staff = (await db.scalars(select(Staff).where(Staff.active==True, Staff.deleted==False, Staff.last_seen>now()-65))).all()
    return {'online':any(s.owner or 'chat.reply' in s.permissions for s in staff)}

@router.get('/account/conversations')
async def conversations(db: DB, kind: str = Query('ticket', pattern='^(ticket|chat)$'), page: int = Query(1, ge=1), context: Customer = Depends(customer)):
    rows = (await db.scalars(select(Conversation).where(Conversation.user_id==context.user.id, Conversation.kind==kind).order_by(Conversation.updated_at.desc()).offset((page-1)*20).limit(21))).all()
    return {'items':[conversation_data(c) for c in rows[:20]], 'has_more':len(rows)>20}

@router.post('/account/conversations', status_code=201)
async def create_conversation(data: ConversationInput, db: DB, context: Customer = Depends(customer)):
    await rate_limit('support-create', str(context.user.id), 10, 600)
    await db.execute(text('BEGIN IMMEDIATE'))
    if data.order_id:
        order = await db.get(Order, data.order_id)
        if not order or order.user_id!=context.user.id:
            raise HTTPException(404, 'سفارش متعلق به این حساب نیست.')
    if data.kind=='chat':
        existing = await db.scalar(select(Conversation).where(Conversation.user_id==context.user.id, Conversation.kind=='chat', Conversation.status!='closed'))
        if existing:
            db.add(Message(conversation_id=existing.id, sender='customer', body=data.body))
            existing.status='open'
            existing.updated_at=now()
            await db.commit()
            return conversation_data(existing)
    conversation = Conversation(user_id=context.user.id, kind=data.kind, subject=data.subject, order_id=data.order_id, priority=data.priority)
    db.add(conversation)
    await db.flush()
    db.add(Message(conversation_id=conversation.id, sender='customer', body=data.body))
    await db.commit()
    return conversation_data(conversation)

@router.get('/account/conversations/{conversation_id}')
async def get_conversation(conversation_id: str, db: DB, after: int = Query(0, ge=0), context: Customer = Depends(customer)):
    conversation = await db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id!=context.user.id:
        raise HTTPException(404, 'گفت‌وگو پیدا نشد.')
    rows = (await db.scalars(select(Message).where(Message.conversation_id==conversation_id, Message.id>after).order_by(Message.id).limit(100))).all()
    return {'conversation':conversation_data(conversation), 'messages':[message_data(m) for m in rows], 'has_more':len(rows)==100}

@router.post('/account/conversations/{conversation_id}/messages')
async def post_message(conversation_id: str, data: MessageInput, db: DB, context: Customer = Depends(customer)):
    await rate_limit('support-message', str(context.user.id), 30, 60)
    conversation = await db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id!=context.user.id:
        raise HTTPException(404, 'گفت‌وگو پیدا نشد.')
    if conversation.status=='closed':
        raise HTTPException(409, 'این گفت‌وگو بسته شده است؛ تیکت یا گفت‌وگوی تازه بسازید.')
    message = Message(conversation_id=conversation_id, sender='customer', body=data.body)
    db.add(message)
    conversation.status='open'
    conversation.updated_at=now()
    await db.commit()
    return message_data(message)

@router.post('/account/conversations/{conversation_id}/close')
async def close_conversation(conversation_id: str, db: DB, context: Customer = Depends(customer)):
    conversation = await db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id!=context.user.id:
        raise HTTPException(404, 'گفت‌وگو پیدا نشد.')
    conversation.status='closed'
    conversation.updated_at=now()
    await db.commit()
    return {'ok':True}
