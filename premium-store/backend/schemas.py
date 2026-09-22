import re
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Schema(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Mobile(Schema):
    mobile: str = Field(pattern=r'^09[0-9]{9}$')

class VerifyOTP(Mobile):
    code: str = Field(pattern=r'^[0-9]{6}$')

class ProfileInput(Schema):
    full_name: str = Field(min_length=3, max_length=100)
    telegram_id: str | None = Field(default=None, max_length=33)

    @field_validator('telegram_id')
    @classmethod
    def telegram(cls, value):
        if not value:
            return None
        if not re.fullmatch(r'@?[A-Za-z][A-Za-z0-9_]{4,31}', value):
            raise ValueError('شناسه تلگرام نامعتبر است')
        return value.lstrip('@')

class CartItemSchema(Schema):
    product_id: int = Field(strict=True, gt=0)
    quantity: int = Field(strict=True, ge=1, le=10)

class CheckoutRequest(Schema):
    items: list[CartItemSchema] = Field(min_length=1, max_length=30)
    coupon: str = Field(default='', max_length=40, pattern=r'^[A-Za-z0-9_-]*$')

def media_url(value):
    if not value:
        return ''
    if re.fullmatch(r'/media/[a-f0-9]{32}\.(webp|mp4)', value):
        return value
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or len(value)>2048:
        raise ValueError('رسانه باید فایل بارگذاری‌شده یا لینک مستقیم HTTPS باشد')
    return value

class ProductInput(Schema):
    title: str = Field(min_length=2, max_length=200)
    brand: str = Field(default='', max_length=100)
    category: Literal['ai','vpn','stream','tools'] = 'ai'
    icon: Literal['gpt','gemini','spotify','nord','trading','adobe'] = 'gpt'
    description: str = Field(min_length=10, max_length=500)
    content: str = Field(default='', max_length=30000)
    features: list[str] = Field(default_factory=list, max_length=10)
    images: list[str] = Field(default_factory=list, max_length=10)
    video: str = Field(default='', max_length=2048)
    price: int = Field(strict=True, ge=1000, le=500000000)
    original_price: int = Field(default=0, strict=True, ge=0, le=500000000)
    period: str = Field(default='اشتراک یک‌ماهه', min_length=1, max_length=100)
    badge: str = Field(default='', max_length=80)
    available: bool = True
    published: bool = False
    sort_order: int = Field(default=0, ge=0, le=10000)
    revision: int | None = Field(default=None, ge=1)

    @field_validator('images')
    @classmethod
    def image_urls(cls, values):
        return [media_url(v) for v in values if v]

    @field_validator('video')
    @classmethod
    def video_url(cls, value):
        return media_url(value)

    @field_validator('features')
    @classmethod
    def feature_lengths(cls, values):
        if any(len(v)>200 for v in values):
            raise ValueError('ویژگی طولانی است')
        return [v.strip() for v in values if v.strip()]

    @model_validator(mode='after')
    def price_consistency(self):
        if self.original_price and self.original_price<self.price:
            raise ValueError('قیمت قبل از تخفیف نباید کمتر از قیمت فروش باشد')
        return self

class CouponInput(Schema):
    code: str = Field(pattern=r'^[A-Za-z0-9_-]{3,40}$')
    kind: Literal['percent','fixed']
    value: int = Field(strict=True, gt=0, le=500000000)
    min_total: int = Field(default=0, ge=0, le=500000000)
    max_discount: int = Field(default=0, ge=0, le=500000000)
    max_uses: int = Field(default=100, ge=1, le=1000000)
    per_user: int = Field(default=1, ge=1, le=1000)
    starts_at: int = Field(default=0, ge=0)
    expires_at: int = Field(default=0, ge=0)
    active: bool = True

    @model_validator(mode='after')
    def consistent(self):
        self.code = self.code.upper()
        if self.kind=='percent' and self.value>90:
            raise ValueError('تخفیف درصدی حداکثر ۹۰ درصد است')
        if self.expires_at and self.expires_at<=self.starts_at:
            raise ValueError('زمان پایان باید بعد از شروع باشد')
        return self

class ConversationInput(Schema):
    kind: Literal['ticket','chat'] = 'ticket'
    subject: str = Field(min_length=3, max_length=150)
    body: str = Field(min_length=1, max_length=5000)
    order_id: str | None = Field(default=None, max_length=36)
    priority: Literal['normal','high'] = 'normal'

class MessageInput(Schema):
    body: str = Field(min_length=1, max_length=5000)

class StaffLogin(Schema):
    username: str = Field(min_length=3, max_length=50, pattern=r'^[A-Za-z0-9_.-]+$')
    password: str = Field(min_length=1, max_length=128)

class StaffInput(Schema):
    username: str = Field(min_length=3, max_length=50, pattern=r'^[A-Za-z0-9_.-]+$')
    name: str = Field(min_length=2, max_length=100)
    password: str | None = Field(default=None, min_length=12, max_length=128)
    permissions: list[str] = Field(default_factory=list, max_length=40)
    active: bool = True

    @field_validator('permissions')
    @classmethod
    def valid_permissions(cls, values):
        from .security import PERMISSIONS
        if any(v not in PERMISSIONS for v in values):
            raise ValueError('مجوز ناشناخته است')
        return sorted(set(values))
