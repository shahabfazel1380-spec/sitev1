import asyncio
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from . import settings
from .db import Session
from .models import CustomerSession, Profile, RateLimit, Staff, StaffSession, User, now

PERMISSIONS = {
 'dashboard.read':'داشبورد: مشاهده',
 'products.read':'محصولات: مشاهده', 'products.create':'محصولات: ایجاد', 'products.update':'محصولات: ویرایش', 'products.publish':'محصولات: انتشار', 'products.archive':'محصولات: بایگانی', 'media.upload':'رسانه: بارگذاری',
 'orders.read':'سفارش‌ها: مشاهده', 'orders.update':'سفارش‌ها: پیگیری و یادداشت',
 'customers.read':'کاربران: مشاهده', 'customers.update':'کاربران: مسدودسازی و رفع مسدودی',
 'tickets.read':'تیکت‌ها: مشاهده', 'tickets.reply':'تیکت‌ها: پاسخ', 'tickets.manage':'تیکت‌ها: وضعیت و ارجاع',
 'chat.read':'چت: مشاهده', 'chat.reply':'چت: پاسخ', 'chat.manage':'چت: وضعیت و ارجاع',
 'discounts.read':'تخفیف‌ها: مشاهده', 'discounts.write':'تخفیف‌ها: ایجاد و ویرایش',
 'settings.read':'تنظیمات: مشاهده', 'settings.write':'تنظیمات: ویرایش',
 'wallet.read':'کیف پول: مشاهده', 'wallet.adjust':'کیف پول: اصلاح و جایزه', 'wallet.refund':'کیف پول: بازپرداخت سفارش',
 'messages.read':'پیام‌ها: تاریخچه', 'messages.send':'پیام‌ها: ارسال',
 'activations.read':'فعال‌سازی: مشاهده', 'activations.write':'فعال‌سازی: ثبت و ویرایش', 'activations.secrets':'فعال‌سازی: مشاهده رمز و شماره کارت', 'orders.secrets':'سفارش: مشاهده اطلاعات ورود',
 'audit.read':'گزارش فعالیت: مشاهده',
}
_secret = None

def secret():
    global _secret
    if _secret is None:
        value = os.getenv('APP_SECRET')
        if not value:
            if settings.ENV == 'production':
                raise RuntimeError('APP_SECRET is required')
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            path = settings.DATA_DIR / 'development-secret'
            if not path.exists():
                try:
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, 'w') as file:
                        file.write(secrets.token_hex(32))
                except FileExistsError:
                    pass
            value = path.read_text().strip()
        _secret = value.encode()
    return _secret

def digest(value):
    return hmac.new(secret(), value.encode(), hashlib.sha256).hexdigest()

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=128*1024*1024).hex()
    return f'scrypt${salt}${derived}'

def check_password(password, hashed):
    try:
        _, salt, _ = hashed.split('$')
        return hmac.compare_digest(password_hash(password, salt), hashed)
    except (ValueError, TypeError):
        return False

async def rate_limit(scope, identity, limit, seconds):
    stamp = now()
    key = digest(f'rate:{scope}:{identity}:{stamp // seconds}')
    async with Session() as db:
        statement = insert(RateLimit).values(key=key, count=1, expires_at=stamp+seconds)
        count = await db.scalar(statement.on_conflict_do_update(index_elements=[RateLimit.key], set_={'count':RateLimit.count+1}).returning(RateLimit.count))
        await db.commit()
    if count > limit:
        raise HTTPException(429, 'تعداد درخواست‌ها زیاد است. کمی صبر کنید.', headers={'Retry-After':str(seconds)})

def client_ip(request):
    # Uvicorn trusts forwarded headers only from the configured reverse proxy.
    return request.client.host if request.client else 'unknown'

def csrf_check(request, expected):
    if request.method not in {'GET','HEAD','OPTIONS'}:
        if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''), expected):
            raise HTTPException(403, 'نشست یا کد امنیتی معتبر نیست؛ صفحه را دوباره باز کنید.')

@dataclass
class Customer:
    user: User
    profile: Profile
    session: CustomerSession

async def customer(request: Request):
    token = request.cookies.get(settings.CUSTOMER_COOKIE, '')
    if not token:
        raise HTTPException(401, 'ابتدا با شماره موبایل وارد حساب شوید.')
    async with Session() as db:
        session = await db.get(CustomerSession, digest('session:'+token))
        if not session or session.expires_at <= now():
            raise HTTPException(401, 'نشست شما پایان یافته؛ دوباره وارد شوید.')
        user = await db.get(User, session.user_id)
        profile = await db.get(Profile, session.user_id)
        if not user or not profile or profile.blocked:
            raise HTTPException(403, 'دسترسی این حساب غیرفعال است.')
        csrf_check(request, session.csrf)
        return Customer(user, profile, session)

@dataclass
class Administrator:
    staff: Staff
    session: StaffSession

async def administrator(request: Request):
    token = request.cookies.get(settings.ADMIN_COOKIE, '')
    async with Session() as db:
        session = await db.get(StaffSession, digest('session:'+token)) if token else None
        if not session or session.expires_at <= now():
            raise HTTPException(401, 'ورود به پنل مدیریت لازم است.')
        staff = await db.get(Staff, session.staff_id)
        if not staff or not staff.active or staff.deleted:
            raise HTTPException(403, 'دسترسی کارمند غیرفعال شده است.')
        csrf_check(request, session.csrf)
        return Administrator(staff, session)

def allowed(staff, permission):
    return staff.owner or permission in staff.permissions

def require(permission):
    async def dependency(context: Administrator = Depends(administrator)):
        if not allowed(context.staff, permission):
            raise HTTPException(403, 'دسترسی لازم برای این عملیات را ندارید.')
        return context
    return dependency

async def owner(context: Administrator = Depends(administrator)):
    if not context.staff.owner:
        raise HTTPException(403, 'مدیریت کارمندان فقط برای مالک مجاز است.')
    return context

def set_session_cookie(response: Response, token, staff=False):
    response.set_cookie(settings.ADMIN_COOKIE if staff else settings.CUSTOMER_COOKIE, token, max_age=settings.ADMIN_SESSION_SECONDS if staff else settings.SESSION_SECONDS, httponly=True, secure=settings.ENV=='production', samesite='lax', path='/')

async def new_customer_session(db, user_id, request, response):
    # Rotate the current device token to prevent fixation and orphaned sessions.
    previous = request.cookies.get(settings.CUSTOMER_COOKIE)
    if previous:
        await db.execute(delete(CustomerSession).where(CustomerSession.token_hash==digest('session:'+previous)))
    token = secrets.token_urlsafe(32)
    session = CustomerSession(token_hash=digest('session:'+token), user_id=user_id, csrf=secrets.token_urlsafe(32), expires_at=now()+settings.SESSION_SECONDS, device=request.headers.get('user-agent','')[:180])
    db.add(session)
    set_session_cookie(response, token)
    return session
