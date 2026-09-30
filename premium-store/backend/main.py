"""Premium Store v2 — customers, staff permissions, support and commerce."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select, update, text
from starlette.exceptions import HTTPException
from . import admin, auth, commerce, settings, support
from .notifications import worker
from . import extensions
from .vault import cipher
from .db import Base, Session, engine
from .models import (CouponUse, CustomerSession, OTP, Product, RateLimit, SchemaVersion,
                     Setting, StaffSession, now)
from .security import secret

async def migrate():
    # v2 is additive: preserve all v1 user/order tables and introduce new tables.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns=(await conn.execute(text('PRAGMA table_info(store_products)'))).all()
        if 'require_credentials' not in {c[1] for c in columns}:
            await conn.execute(text('ALTER TABLE store_products ADD COLUMN require_credentials BOOLEAN NOT NULL DEFAULT 0'))
    async with Session() as db:
        if not await db.get(SchemaVersion,3):
            db.add(SchemaVersion(version=3))
            await db.commit()
        if not await db.get(SchemaVersion,2):
            if not await db.scalar(select(Product.id).limit(1)):
                for value in json.loads((settings.ROOT/'catalog.json').read_text(encoding='utf-8')):
                    db.add(Product(**value, published=True, content=value['description']+'\n\n'+ '\n'.join(value['features'])+'\n\nپیش از خرید، نوع اشتراک و شرایط فعال‌سازی را با پشتیبانی هماهنگ کنید.'))
            if not await db.get(Setting,'telegram_url'):
                db.add(Setting(key='telegram_url',value='https://t.me/premiumstore'))
            db.add(SchemaVersion(version=2))
            await db.commit()

async def housekeeping():
    while True:
        try:
            async with Session() as db:
                await db.execute(text('BEGIN IMMEDIATE'))
                from .wallet import expire_pending
                await expire_pending(db)
                stamp=now()
                for model in [CustomerSession,StaffSession,RateLimit]:
                    await db.execute(delete(model).where(model.expires_at<stamp))
                await db.execute(delete(OTP).where(OTP.expires_at<stamp-900))
                await db.execute(update(CouponUse).where(CouponUse.status=='reserved',CouponUse.expires_at<=stamp).values(status='released'))
                await db.commit()
        except Exception:
            logging.getLogger('premiumstore').warning('Scheduled cleanup deferred.')
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app):
    settings.validate_environment()
    secret()
    cipher()
    await migrate()
    tasks=[asyncio.create_task(worker()),asyncio.create_task(housekeeping())]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
    await engine.dispose()

app=FastAPI(title='Premium Store API',version='3.0.0',lifespan=lifespan,
    docs_url='/api/docs' if settings.ENV!='production' else None,redoc_url=None,
    openapi_url='/api/openapi.json' if settings.ENV!='production' else None)

@app.middleware('http')
async def security_headers(request: Request, call_next):
    if request.method not in {'GET','HEAD','OPTIONS'}:
        if request.headers.get('origin') not in {None,settings.PUBLIC_URL} or request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'مبدأ درخواست مجاز نیست.'},status_code=403)
    response=await call_next(request)
    response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
        'Permissions-Policy':'camera=(), microphone=(), geolocation=()',
        'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' https: data:; media-src 'self' https:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    else:
        response.headers['Cache-Control']='no-cache'
    if settings.ENV=='production':
        response.headers['Strict-Transport-Security']='max-age=31536000'
    return response

class BodyLimit:
    def __init__(self,app):
        self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method'] in {'GET','HEAD','OPTIONS'}:
            return await self.app(scope,receive,send)
        limit=25*1024*1024 if scope['path']=='/api/admin/media' else 128*1024
        parts=[]
        size=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect':
                return
            chunk=message.get('body',b'')
            size+=len(chunk)
            if size>limit:
                return await JSONResponse({'detail':'حجم درخواست بیش از حد مجاز است.'},status_code=413)(scope,receive,send)
            parts.append(chunk)
            if not message.get('more_body',False):
                break
        sent=False
        async def replay():
            nonlocal sent
            if not sent:
                sent=True
                return {'type':'http.request','body':b''.join(parts),'more_body':False}
            return await receive()
        await self.app(scope,replay,send)

app.add_middleware(BodyLimit)

@app.exception_handler(HTTPException)
async def http_error(request,exc):
    return JSONResponse({'detail':exc.detail},status_code=exc.status_code,headers=exc.headers)

@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    fields=sorted({str(error['loc'][-1]) for error in exc.errors()})
    return JSONResponse({'detail':'اطلاعات واردشده معتبر نیست. فیلدهای فرم را بررسی کنید.','fields':fields},status_code=422)

@app.exception_handler(Exception)
async def server_error(request,exc):
    logging.getLogger('premiumstore').error('Request failed: %s',type(exc).__name__)
    return JSONResponse({'detail':'خطایی رخ داد؛ دوباره تلاش کنید.'},status_code=500)

@app.get('/api/health')
async def health():
    return {'status':'ok','version':'3.0.0'}

app.include_router(extensions.router)
app.include_router(auth.router)
app.include_router(commerce.router)
app.include_router(support.router)
app.include_router(admin.router)
app.mount('/media',StaticFiles(directory=settings.MEDIA_DIR,check_dir=False),name='media')
app.mount('/',StaticFiles(directory=settings.ROOT/'public',html=True),name='storefront')
