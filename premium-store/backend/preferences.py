import json
from pydantic import Field, model_validator
from .schemas import Schema
from .models import Setting
from sqlalchemy import select

OFFLINE_MESSAGE='متاسفانه چت آنلاین فعلاً در دسترس نیست؛ با وارد شدن به اکانت خود تیکت ثبت کنید. در اسرع وقت پاسخگو خواهیم بود.'

class OperationsInput(Schema):
    store_name: str = Field(default='پریمیوم استور',min_length=2,max_length=100)
    chat_enabled: bool = True
    chat_offline_message: str = Field(default=OFFLINE_MESSAGE,min_length=10,max_length=500)
    ticket_sms_enabled: bool = False
    ticket_sms_text: str = Field(default='پاسخ تیکت شما در حساب کاربری فروشگاه ثبت شد. لطفاً برای مشاهده وارد سایت شوید.',min_length=10,max_length=500)
    sms_notifications_enabled: bool = False
    telegram_messages_enabled: bool = False
    sms_sender: str = Field(default='',max_length=30,pattern=r'^[0-9+]*$')
    wallet_enabled: bool = True
    wallet_topup_enabled: bool = True
    wallet_min_topup: int = Field(default=10000,ge=1000,le=500000000)
    wallet_max_topup: int = Field(default=10000000,ge=1000,le=500000000)
    activation_reminder_days: int = Field(default=3,ge=1,le=90)
    credential_help: str = Field(default='اطلاعات اکانتی را وارد کنید که می‌خواهید فعال شود. رمز بانکی یا کد یک‌بارمصرف وارد نکنید.',max_length=500)
    @model_validator(mode='after')
    def limits(self):
        if self.wallet_min_topup>self.wallet_max_topup: raise ValueError('حداقل شارژ نباید بیشتر از حداکثر باشد')
        return self

async def operations(db):
    row=await db.get(Setting,'operations_v3')
    return OperationsInput.model_validate_json(row.value) if row else OperationsInput()

async def save_operations(db,data):
    row=await db.get(Setting,'operations_v3')
    if row: row.value=data.model_dump_json()
    else: db.add(Setting(key='operations_v3',value=data.model_dump_json()))
