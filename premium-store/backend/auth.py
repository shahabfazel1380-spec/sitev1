import asyncio
import os
import secrets
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.sqlite import insert
from . import settings
from .db import DB, Session
from .models import CustomerSession, OTP, Profile, Staff, StaffSession, User, now
from .schemas import Mobile, ProfileInput, StaffLogin, VerifyOTP
from .security import (Administrator, Customer, PERMISSIONS, administrator, check_password,
    client_ip, customer, digest, new_customer_session, password_hash, rate_limit, set_session_cookie)

router = APIRouter(prefix='/api')

def customer_data(context):
    return {'id':context.user.id, 'mobile':context.user.mobile, 'full_name':context.user.full_name,
            'telegram_id':context.user.telegram_id, 'registered':context.profile.registered,
            'created_at':context.user.created_at, 'csrf':context.session.csrf,
            'session_expires_at':context.session.expires_at}

async def send_code(mobile, code):
    if settings.SMS_MODE == 'disabled':
        raise HTTPException(503, 'سرویس پیامک هنوز فعال نشده است.')
    if settings.SMS_MODE == 'demo':
        return
    try:
        # Never log the URL: Kavenegar includes its API key in the path.
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post('https://api.kavenegar.com/v1/' + os.environ['KAVENEGAR_API_KEY'] + '/verify/lookup.json', data={
                'receptor':mobile, 'token':code, 'template':os.environ['KAVENEGAR_TEMPLATE'], 'type':'sms'})
        response.raise_for_status()
        if response.json().get('return',{}).get('status') != 200:
            raise ValueError('SMS provider rejected request')
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(503, 'ارسال پیامک فعلاً ممکن نیست؛ کمی بعد دوباره تلاش کنید.') from None

@router.post('/auth/otp/request')
async def request_otp(data: Mobile, request: Request, db: DB):
    if settings.SMS_MODE == 'demo' and (settings.ENV=='production' or client_ip(request) not in {'127.0.0.1','::1','testclient'}):
        raise HTTPException(503, 'ارسال پیامک هنوز فعال نشده است.')
    if settings.SMS_MODE == 'disabled':
        raise HTTPException(503, 'ارسال پیامک هنوز فعال نشده است.')
    await rate_limit('otp-ip', client_ip(request), 10, 600)
    await rate_limit('otp-mobile', data.mobile, 4, 900)
    stamp = now()
    code = f'{secrets.randbelow(1000000):06d}'
    hashed = digest(f'otp:{data.mobile}:{code}')
    statement = insert(OTP).values(mobile=data.mobile, code_hash=hashed, expires_at=stamp+180, sent_at=stamp, attempts=0, consumed=False)
    changed = await db.scalar(statement.on_conflict_do_update(index_elements=[OTP.mobile],
        set_={'code_hash':hashed,'expires_at':stamp+180,'sent_at':stamp,'attempts':0,'consumed':False},
        where=OTP.sent_at<=stamp-60).returning(OTP.mobile))
    if not changed:
        raise HTTPException(429, 'برای ارسال دوباره کد، ۶۰ ثانیه صبر کنید.', headers={'Retry-After':'60'})
    await db.commit()
    try:
        await send_code(data.mobile, code)
    except HTTPException:
        await db.execute(delete(OTP).where(OTP.mobile==data.mobile, OTP.code_hash==hashed))
        await db.commit()
        raise
    result = {'message':'کد ورود ارسال شد.', 'expires_in':180, 'retry_after':60}
    if settings.SMS_MODE=='demo':
        result.update({'demo_code':code, 'message':'محیط آزمایشی؛ پیامکی ارسال نشده است.'})
    return result

@router.post('/auth/otp/verify')
async def verify_otp(data: VerifyOTP, request: Request, response: Response, db: DB):
    await rate_limit('otp-verify', client_ip(request), 30, 600)
    await db.execute(text('BEGIN IMMEDIATE'))
    challenge = await db.get(OTP, data.mobile)
    if not challenge or challenge.consumed or challenge.expires_at<=now() or challenge.attempts>=5:
        raise HTTPException(400, 'کد ورود نامعتبر یا منقضی شده است.')
    import hmac
    if not hmac.compare_digest(challenge.code_hash, digest(f'otp:{data.mobile}:{data.code}')):
        challenge.attempts += 1
        await db.commit()
        raise HTTPException(400, 'کد ورود نامعتبر یا منقضی شده است.')
    challenge.consumed = True
    user = await db.scalar(select(User).where(User.mobile==data.mobile))
    if not user:
        user = User(mobile=data.mobile, full_name='')
        db.add(user)
        await db.flush()
    profile = await db.get(Profile, user.id)
    if not profile:
        # Legacy checkout contact data did not prove account ownership.
        user.full_name = ''
        user.telegram_id = None
        profile = Profile(user_id=user.id)
        db.add(profile)
        await db.flush()
    if profile.blocked:
        await db.commit()
        raise HTTPException(403, 'دسترسی این حساب غیرفعال است.')
    login_session = await new_customer_session(db, user.id, request, response)
    await db.commit()
    return customer_data(Customer(user, profile, login_session))

@router.get('/auth/me')
async def me(context: Customer = Depends(customer)):
    return customer_data(context)

@router.put('/account/profile')
async def profile_update(data: ProfileInput, db: DB, context: Customer = Depends(customer)):
    user = await db.get(User, context.user.id)
    profile = await db.get(Profile, user.id)
    user.full_name = data.full_name
    user.telegram_id = data.telegram_id
    profile.registered = True
    await db.commit()
    return customer_data(Customer(user, profile, context.session))

@router.post('/auth/logout')
async def logout(response: Response, db: DB, context: Customer = Depends(customer)):
    await db.execute(delete(CustomerSession).where(CustomerSession.token_hash==context.session.token_hash))
    await db.commit()
    response.delete_cookie(settings.CUSTOMER_COOKIE, path='/')
    return {'ok':True}

@router.post('/auth/logout-all')
async def logout_all(response: Response, db: DB, context: Customer = Depends(customer)):
    await db.execute(delete(CustomerSession).where(CustomerSession.user_id==context.user.id))
    await db.commit()
    response.delete_cookie(settings.CUSTOMER_COOKIE, path='/')
    return {'ok':True}

@router.get('/account/sessions')
async def sessions(db: DB, context: Customer = Depends(customer)):
    rows = (await db.scalars(select(CustomerSession).where(CustomerSession.user_id==context.user.id, CustomerSession.expires_at>now()).order_by(CustomerSession.created_at.desc()))).all()
    return [{'current':s.token_hash==context.session.token_hash, 'device':s.device, 'created_at':s.created_at, 'expires_at':s.expires_at} for s in rows]

@router.post('/admin/login')
async def admin_login(data: StaffLogin, request: Request, response: Response, db: DB):
    await rate_limit('staff-ip', client_ip(request), 10, 900)
    await rate_limit('staff-user', data.username.lower(), 8, 900)
    staff = await db.scalar(select(Staff).where(Staff.username==data.username.lower()))
    # Equal-cost verification for unknown accounts.
    dummy = 'scrypt$'+'0'*32+'$'+'0'*128
    valid = await asyncio.to_thread(check_password, data.password, staff.password_hash if staff else dummy)
    if not staff or not valid or not staff.active or staff.deleted:
        raise HTTPException(401, 'نام کاربری یا رمز عبور معتبر نیست.')
    previous = request.cookies.get(settings.ADMIN_COOKIE)
    if previous:
        await db.execute(delete(StaffSession).where(StaffSession.token_hash==digest('session:'+previous)))
    token = secrets.token_urlsafe(32)
    session = StaffSession(token_hash=digest('session:'+token), staff_id=staff.id, csrf=secrets.token_urlsafe(32), expires_at=now()+settings.ADMIN_SESSION_SECONDS)
    db.add(session)
    staff.last_seen = now()
    await db.commit()
    set_session_cookie(response, token, staff=True)
    return {'ok':True, 'csrf':session.csrf}

@router.get('/admin/me')
async def admin_me(db: DB, context: Administrator = Depends(administrator)):
    await db.execute(update(Staff).where(Staff.id==context.staff.id).values(last_seen=now()))
    await db.commit()
    return {'id':context.staff.id, 'name':context.staff.name, 'username':context.staff.username, 'owner':context.staff.owner, 'permissions':list(PERMISSIONS) if context.staff.owner else context.staff.permissions, 'csrf':context.session.csrf, 'expires_at':context.session.expires_at}

@router.post('/admin/logout')
async def admin_logout(response: Response, db: DB, context: Administrator = Depends(administrator)):
    await db.execute(delete(StaffSession).where(StaffSession.token_hash==context.session.token_hash))
    await db.commit()
    response.delete_cookie(settings.ADMIN_COOKIE, path='/')
    return {'ok':True}
