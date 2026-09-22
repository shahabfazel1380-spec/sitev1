import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = os.getenv('APP_ENV', 'development')
PUBLIC_URL = os.getenv('PUBLIC_URL', 'http://127.0.0.1:8000').rstrip('/')
PAYMENT_MODE = os.getenv('PAYMENT_MODE', 'demo')
SMS_MODE = os.getenv('SMS_MODE', 'demo')
DATA_DIR = Path(os.getenv('DATA_DIR', str(ROOT / '.local')))
MEDIA_DIR = Path(os.getenv('MEDIA_DIR', str(DATA_DIR / 'media')))
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite+aiosqlite:///./premium_store.db')
SESSION_SECONDS = 172800
ADMIN_SESSION_SECONDS = 28800
CUSTOMER_COOKIE = '__Host-premium_customer' if ENV == 'production' else 'premium_customer'
ADMIN_COOKIE = '__Host-premium_staff' if ENV == 'production' else 'premium_staff'

def validate_environment():
    if ENV not in {'development', 'test', 'production'}:
        raise RuntimeError('Invalid APP_ENV')
    if PAYMENT_MODE not in {'demo', 'disabled'} or SMS_MODE not in {'demo', 'kavenegar', 'disabled'}:
        raise RuntimeError('Invalid payment or SMS mode')
    if ENV == 'production':
        if PAYMENT_MODE != 'disabled' or SMS_MODE == 'demo':
            raise RuntimeError('Demo payments and demo SMS are prohibited in production.')
        if not PUBLIC_URL.startswith('https://') or len(os.getenv('APP_SECRET', '')) < 32:
            raise RuntimeError('Production requires HTTPS and APP_SECRET with at least 32 characters.')
    if SMS_MODE == 'kavenegar' and not all(os.getenv(key) for key in ['KAVENEGAR_API_KEY', 'KAVENEGAR_TEMPLATE']):
        raise RuntimeError('Kavenegar API key and approved OTP template are required.')
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
