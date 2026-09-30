import time
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now():
    return int(time.time())

def iso_now():
    return datetime.now(timezone.utc).isoformat()

class User(Base):
    __tablename__ = 'web_users'
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100), default='')
    mobile: Mapped[str] = mapped_column(String(11), unique=True)
    telegram_id: Mapped[str | None] = mapped_column(String(33))
    created_at: Mapped[str] = mapped_column(default=iso_now)

class Profile(Base):
    __tablename__ = 'customer_profiles'
    user_id: Mapped[int] = mapped_column(ForeignKey('web_users.id'), primary_key=True)
    registered: Mapped[bool] = mapped_column(default=False)
    blocked: Mapped[bool] = mapped_column(default=False)

class CustomerSession(Base):
    __tablename__ = 'customer_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('web_users.id'), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int]
    created_at: Mapped[int] = mapped_column(default=now)
    device: Mapped[str] = mapped_column(String(180), default='')

class OTP(Base):
    __tablename__ = 'otp_challenges'
    mobile: Mapped[str] = mapped_column(String(11), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int]
    sent_at: Mapped[int]
    attempts: Mapped[int] = mapped_column(default=0)
    consumed: Mapped[bool] = mapped_column(default=False)

class RateLimit(Base):
    __tablename__ = 'rate_limits'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int]
    expires_at: Mapped[int] = mapped_column(index=True)

class Product(Base):
    __tablename__ = 'store_products'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    brand: Mapped[str] = mapped_column(String(100), default='')
    category: Mapped[str] = mapped_column(String(30), default='ai')
    icon: Mapped[str] = mapped_column(String(20), default='gpt')
    description: Mapped[str] = mapped_column(Text, default='')
    content: Mapped[str] = mapped_column(Text, default='')
    features: Mapped[list] = mapped_column(JSON, default=list)
    images: Mapped[list] = mapped_column(JSON, default=list)
    video: Mapped[str] = mapped_column(String(2048), default='')
    price: Mapped[int]
    original_price: Mapped[int] = mapped_column(default=0)
    period: Mapped[str] = mapped_column(String(100), default='اشتراک یک‌ماهه')
    badge: Mapped[str] = mapped_column(String(80), default='')
    available: Mapped[bool] = mapped_column(default=True)
    require_credentials: Mapped[bool] = mapped_column(default=False)
    published: Mapped[bool] = mapped_column(default=False)
    archived: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(default=0)
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[int] = mapped_column(default=now)

class Order(Base):
    # Kept compatible with v1: no destructive migration of existing orders.
    __tablename__ = 'web_orders'
    __table_args__ = (CheckConstraint("status IN ('pending','success','failed')"), CheckConstraint('total_amount > 0'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda:str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey('web_users.id'))
    total_amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default='pending')
    authority_code: Mapped[str] = mapped_column(String(36), unique=True)
    ref_id: Mapped[str | None] = mapped_column(String(32))
    payment_mode: Mapped[str] = mapped_column(String(10), default='demo')
    full_name: Mapped[str] = mapped_column(String(100))
    mobile: Mapped[str] = mapped_column(String(11))
    telegram_id: Mapped[str | None] = mapped_column(String(33))
    idempotency_key: Mapped[str] = mapped_column(String(36), unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(default=iso_now)

class OrderItem(Base):
    __tablename__ = 'web_order_items'
    __table_args__ = (CheckConstraint('quantity > 0 AND quantity <= 10'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('web_orders.id'), index=True)
    product_id: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int]
    unit_price: Mapped[int]

class OrderDetails(Base):
    __tablename__ = 'order_details'
    order_id: Mapped[str] = mapped_column(ForeignKey('web_orders.id'), primary_key=True)
    subtotal: Mapped[int]
    discount_amount: Mapped[int] = mapped_column(default=0)
    coupon_code: Mapped[str] = mapped_column(String(40), default='')
    fulfillment: Mapped[str] = mapped_column(String(30), default='awaiting_payment')
    customer_note: Mapped[str] = mapped_column(Text, default='')
    internal_note: Mapped[str] = mapped_column(Text, default='')

class Coupon(Base):
    __tablename__ = 'store_coupons'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    kind: Mapped[str] = mapped_column(String(10))
    value: Mapped[int]
    min_total: Mapped[int] = mapped_column(default=0)
    max_discount: Mapped[int] = mapped_column(default=0)
    max_uses: Mapped[int] = mapped_column(default=100)
    per_user: Mapped[int] = mapped_column(default=1)
    starts_at: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(default=True)

class CouponUse(Base):
    __tablename__ = 'coupon_uses'
    order_id: Mapped[str] = mapped_column(ForeignKey('web_orders.id'), primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey('store_coupons.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('web_users.id'), index=True)
    status: Mapped[str] = mapped_column(String(15), default='reserved')
    expires_at: Mapped[int]

class Staff(Base):
    __tablename__ = 'staff_accounts'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(256))
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    owner: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    deleted: Mapped[bool] = mapped_column(default=False)
    last_seen: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[int] = mapped_column(default=now)

class StaffSession(Base):
    __tablename__ = 'staff_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey('staff_accounts.id'), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int]
    created_at: Mapped[int] = mapped_column(default=now)

class Conversation(Base):
    __tablename__ = 'support_conversations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda:str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey('web_users.id'), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    subject: Mapped[str] = mapped_column(String(150))
    order_id: Mapped[str | None] = mapped_column(ForeignKey('web_orders.id'))
    priority: Mapped[str] = mapped_column(String(10), default='normal')
    status: Mapped[str] = mapped_column(String(20), default='open')
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey('staff_accounts.id'))
    created_at: Mapped[int] = mapped_column(default=now)
    updated_at: Mapped[int] = mapped_column(default=now)

class Message(Base):
    __tablename__ = 'support_messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('support_conversations.id'), index=True)
    sender: Mapped[str] = mapped_column(String(10))
    staff_id: Mapped[int | None] = mapped_column(ForeignKey('staff_accounts.id'))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(default=now)

class Setting(Base):
    __tablename__ = 'store_settings'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

class Audit(Base):
    __tablename__ = 'admin_audit'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('staff_accounts.id'))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[int] = mapped_column(default=now, index=True)

class SchemaVersion(Base):
    __tablename__ = 'schema_versions'
    version: Mapped[int] = mapped_column(primary_key=True)
    applied_at: Mapped[int] = mapped_column(default=now)

class WalletEntry(Base):
    __tablename__ = 'wallet_entries'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('web_users.id'), index=True)
    amount: Mapped[int]
    mode: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(30))
    reference: Mapped[str] = mapped_column(String(150), unique=True)
    note: Mapped[str] = mapped_column(String(500), default='')
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('staff_accounts.id'))
    created_at: Mapped[int] = mapped_column(default=now)

class OrderExtra(Base):
    __tablename__ = 'order_extras'
    order_id: Mapped[str] = mapped_column(ForeignKey('web_orders.id'), primary_key=True)
    wallet_used: Mapped[int] = mapped_column(default=0)
    payable: Mapped[int]
    mode: Mapped[str] = mapped_column(String(10))
    refunded: Mapped[bool] = mapped_column(default=False)
    credentials: Mapped[str] = mapped_column(Text, default='')

class WalletTopup(Base):
    __tablename__ = 'wallet_topups'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda:str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey('web_users.id'), index=True)
    amount: Mapped[int]
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(15), default='pending')
    request_key: Mapped[str] = mapped_column(String(36), unique=True)
    created_at: Mapped[int] = mapped_column(default=now)

class CustomerContact(Base):
    __tablename__ = 'customer_contacts'
    user_id: Mapped[int] = mapped_column(ForeignKey('web_users.id'), primary_key=True)
    telegram_chat_id: Mapped[str] = mapped_column(String(30), default='')

class OutgoingMessage(Base):
    __tablename__ = 'outgoing_messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('web_users.id'), index=True)
    channel: Mapped[str] = mapped_column(String(10))
    body: Mapped[str] = mapped_column(Text)
    reference: Mapped[str] = mapped_column(String(150), unique=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    error: Mapped[str] = mapped_column(String(200), default='')
    created_at: Mapped[int] = mapped_column(default=now)
    updated_at: Mapped[int] = mapped_column(default=now)

class ActivationCard(Base):
    __tablename__ = 'activation_cards'
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    last_four: Mapped[str] = mapped_column(String(4))
    number_hash: Mapped[str] = mapped_column(String(64), index=True)
    number_encrypted: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(String(1000), default='')
    active: Mapped[bool] = mapped_column(default=True)
    revision: Mapped[int] = mapped_column(default=1)

class Activation(Base):
    __tablename__ = 'account_activations'
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey('activation_cards.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('web_users.id'), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey('web_orders.id'), index=True)
    service: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(254), index=True)
    account: Mapped[str] = mapped_column(String(200), default='')
    password_encrypted: Mapped[str] = mapped_column(Text, default='')
    paid_at: Mapped[int]
    renewal_at: Mapped[int] = mapped_column(default=0, index=True)
    auto_renew: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str] = mapped_column(String(3000), default='')
    active: Mapped[bool] = mapped_column(default=True)
    revision: Mapped[int] = mapped_column(default=1)
