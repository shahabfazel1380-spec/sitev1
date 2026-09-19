# bot

ربات تلگرامی با پنل مدیریت تحت وب.

## اجرای ربات تلگرام

```bash
pip install -r requirements.txt  # در صورت استفاده از فایل نیازمندی‌ها
python -m app.main
```

## اجرای پنل وب ادمین

1. در فایل `.env` مقادیر زیر را تنظیم کنید:
   ```env
   ADMIN_WEB_USER=admin
   ADMIN_WEB_PASS=very-secret
   ADMIN_WEB_BIND=0.0.0.0
   ADMIN_WEB_PORT=8080
   ```
2. پیش‌نیازها را نصب کنید:
   ```bash
   pip install fastapi uvicorn jinja2 python-dotenv
   ```
3. سرور وب را اجرا کنید:
   ```bash
   python admin_web.py
   ```

پنل وب شامل داشبورد، مدیریت سفارش‌ها، مشاهده کاربران و گزارش تراکنش‌های کیف پول است و به صورت پیش‌فرض روی پورت 8080 در دسترس خواهد بود.
