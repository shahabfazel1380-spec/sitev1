# پریمیوم استور — نسخه ۲

فروشگاه فارسی و راست‌به‌چپ اکانت‌های دیجیتال با FastAPI، SQLite و رابط HTML/CSS/JavaScript. پروژه ربات اصلی جدا و محفوظ است؛ این پوشه وب‌سایت و پل همگام‌سازی محصولات را دارد.

## وضعیت واقعی نسخه

ورود موبایلی، حساب مشتری، سبد، تخفیف، سفارش، پنل کارکنان، تیکت و گفت‌وگوی آنلاین پیاده شده‌اند. **درگاه بانکی واقعی هنوز متصل نیست؛ پرداخت فقط شبیه‌ساز محلی است و در production غیرفعال می‌شود.** سرویس پیامکی هنوز توسط مالک انتخاب نشده است؛ آداپتور کاوه‌نگار آماده است، اما ارسال واقعی نیازمند حساب، اعتبار و الگوی تأییدشده است. محصولات و قیمت‌های اولیه نمونه‌اند. فعال‌سازی واقعی اکانت خودکار نیست.

## امکانات

- ورود بدون رمز با کد ۶ رقمی؛ کد ۳ دقیقه اعتبار، حداکثر ۵ تلاش و محدودیت ارسال دارد.
- نشست مشتری ۴۸ ساعت از زمان ورود، بدون تمدید نامحدود؛ خروج از همه دستگاه‌ها؛ نشست کارکنان ۸ ساعت.
- نام و شناسه اختیاری تلگرام یک بار ذخیره می‌شود؛ خرید بعدی از پروفایل استفاده می‌کند.
- دکمه خرید در صفحه اصلی وارد صفحه محصول می‌شود؛ متن، تصاویر و ویدیوی محصول و افزودن به سبد در آن صفحه است.
- قیمت نهایی سمت سرور، کوپن درصدی/مبلغی، محدودیت مصرف و رزرو تراکنشی کد هنگام سفارش.
- پروفایل، تاریخچه سفارش‌ها، تیکت‌های جداگانه و گفت‌وگوی آنلاین با بررسی پیام‌ها هر چند ثانیه.
- مدیریت محصولات، رسانه، سفارش، کاربران، تخفیف، تنظیمات، گزارش فعالیت و صف همگام‌سازی.
- مالک می‌تواند کارمند با نام کاربری/رمز و مجوزهای جزئی بسازد، ویرایش، غیرفعال یا حذف کند. تغییر دسترسی نشست‌های قبلی را باطل می‌کند.
- کانال: https://t.me/premiumstore؛ لینک اینستاگرام از تنظیمات قابل افزودن است و تا آن زمان نمایش داده نمی‌شود.

## اجرای محلی ویندوز

Python 3.11 یا جدیدتر نصب کنید. داخل همین پوشه:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m backend.manage create-owner --username owner
.\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

رمز مالک را در ترمینال دو بار وارد کنید؛ حداقل ۱۲ کاراکتر. رمز پیش‌فرض وجود ندارد. سایت: http://127.0.0.1:8000/، پنل: http://127.0.0.1:8000/admin/ و مستندات API در محیط محلی: http://127.0.0.1:8000/api/docs.

در حالت پیش‌فرض، کد ورود فقط در اتصال محلی به‌صورت آزمایشی نمایش داده می‌شود و پیامکی ارسال نمی‌شود. برای تست از شماره ساختگی استفاده کنید. دکمه پرداخت نیز برداشت وجه ندارد. دیتابیس و رسانه‌ها محلی هستند و وارد Git نمی‌شوند.

فایل `.env.example` نمونه است و **خودکار بارگذاری نمی‌شود**. در PowerShell متغیرها را قبل از اجرای برنامه تنظیم کنید، برای مثال:

```powershell
$env:PUBLIC_URL = 'http://127.0.0.1:8000'
$env:SMS_MODE = 'demo'
$env:PAYMENT_MODE = 'demo'
```

برای بازیابی رمز مالک (روی سرور و با همان متغیرهای محیطی و دیتابیس):

```powershell
.\.venv\Scripts\python -m backend.manage reset-owner --username owner
```

## راهنمای پنل

۱. وارد `/admin/` شوید. در محصولات، محصول جدید بسازید؛ عنوان، دسته، قیمت **تومان**، توضیح کوتاه، متن کامل، ویژگی‌ها و وضعیت را تکمیل کنید. تصاویر JPEG/PNG/WebP به WebP تبدیل می‌شوند؛ ویدیو MP4 و سقف بارگذاری ۲۵ مگابایت است. لینک HTTPS رسانه نیز قابل استفاده است. HTML دلخواه اجرا نمی‌شود.

۲. پیش‌نویس را بررسی و سپس منتشر کنید. بایگانی محصول برگشت‌پذیر است و محصول را از خرید جدید خارج می‌کند. سفارش‌های قبلی snapshot خود را حفظ می‌کنند.

۳. در تخفیف‌ها، نوع، مقدار، حداقل خرید، تاریخ اعتبار و سقف مصرف را تعیین کنید. مصرف نهایی به تأیید پرداخت وابسته است؛ رزرو لغوشده یا منقضی آزاد می‌شود.

۴. در کارکنان، حساب بسازید و مجوزهای موردنیاز را تیک بزنید. برای مثال پشتیبان: مشاهده/پاسخ/مدیریت تیکت، مشاهده سفارش و مشاهده کاربران. مجوز مشاهده و تغییر مستقل است؛ برای استفاده از صفحه، مجوز مشاهده مرتبط را هم بدهید. فقط مالک کارکنان را مدیریت می‌کند. مجوزها در API هم بررسی می‌شوند.

۵. چت و تیکت صندوق‌های جدا دارند؛ پاسخ، بستن و ارجاع به کارمند از همان صفحه انجام می‌شود. آنلاین‌بودن پشتیبان از فعالیت اخیر حساب دارای مجوز پاسخ چت تشخیص داده می‌شود. این نسخه polling دارد و اعلان بیرون از سایت ارسال نمی‌کند.

۶. تنظیمات کانال، اینستاگرام و پیام فروشگاه را ویرایش کنید. گزارش فعالیت‌ها برای پیگیری تغییرات مدیریتی است. سفارش آزمایشی اجازه تحویل واقعی ندارد.

## راه‌اندازی Ubuntu با دامنه و HTTPS

دستورات زیر برای Ubuntu 24.04 و یک سرویس تک‌پردازه هستند. دامنه نمونه `shop.example.com` را با دامنه خود عوض کنید و رکورد A/AAAA را به سرور متصل کنید. پوشه وب‌سایت را در `/var/www/premiumstore` قرار دهید؛ اگر ریپو را clone کرده‌اید، محتوای پوشه `premium-store` را منتقل کنید، نه کل پوشه ربات.

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx certbot python3-certbot-nginx sqlite3
sudo useradd --system --home /var/lib/premiumstore --shell /usr/sbin/nologin premiumstore
sudo install -d -o premiumstore -g premiumstore -m 700 /var/lib/premiumstore
sudo install -d -m 755 /var/www/premiumstore
# فایل‌های این پروژه را اکنون در /var/www/premiumstore قرار دهید.
cd /var/www/premiumstore
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example /etc/premiumstore.env
sudo chmod 600 /etc/premiumstore.env
sudo nano /etc/premiumstore.env
```

مقادیر production:

```dotenv
APP_ENV=production
PUBLIC_URL=https://shop.example.com
DATABASE_URL=sqlite+aiosqlite:////var/lib/premiumstore/store.db
DATA_DIR=/var/lib/premiumstore
MEDIA_DIR=/var/lib/premiumstore/media
PAYMENT_MODE=disabled
SMS_MODE=disabled
APP_SECRET=REPLACE_WITH_A_RANDOM_SECRET
BOT_DATABASE_PATH=
```

برای تولید APP_SECRET، `python3 -c 'import secrets; print(secrets.token_hex(32))'` را روی سرور اجرا و خروجی را فقط در فایل تنظیمات خصوصی ذخیره کنید. این کلید را در چت، ریپو یا اسکرین‌شات قرار ندهید. مقدار ثابت نگه دارید؛ تغییر آن نشست‌ها را باطل می‌کند. `SMS_MODE=disabled` یعنی تا انتخاب سرویس، ورود مشتری فعال نیست. برای کاوه‌نگار، `SMS_MODE=kavenegar` و `KAVENEGAR_API_KEY` و `KAVENEGAR_TEMPLATE` را تنظیم کنید. اتصال سرویس دیگر نیازمند آداپتور جدید در `backend/auth.py` است.

برای ساخت مالک با همان تنظیمات سرور:

```bash
sudo bash -c 'set -a; source /etc/premiumstore.env; set +a; cd /var/www/premiumstore; runuser -u premiumstore -m -- .venv/bin/python -m backend.manage create-owner --username owner'
sudo cp deploy/premiumstore.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now premiumstore
sudo cp deploy/nginx.conf /etc/nginx/sites-available/premiumstore
sudo nano /etc/nginx/sites-available/premiumstore
# server_name _ را به دامنه خود تغییر دهید.
sudo ln -s /etc/nginx/sites-available/premiumstore /etc/nginx/sites-enabled/premiumstore
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d shop.example.com
sudo certbot renew --dry-run
```

اگر سایت پیش‌فرض Nginx با دامنه تداخل دارد، لینک آن را از `sites-enabled` خارج کنید. روی فایروال فقط SSH موردنیاز و ۸۰/۴۴۳ را باز کنید؛ پورت ۸۰۰۰ باید فقط localhost باشد. فایل systemd از یک worker استفاده می‌کند. Nginx فایل‌های public را سرو می‌کند و API و رسانه را به برنامه می‌فرستد. کوکی‌های production فقط روی HTTPS کار می‌کنند؛ با HTTP ورود را امتحان نکنید.

بررسی سرویس:

```bash
sudo systemctl status premiumstore --no-pager
sudo journalctl -u premiumstore -n 60 --no-pager
sudo nginx -t
```

قبل از فروش واقعی باید آداپتور درگاه معتبر، تأیید مبلغ/شناسه تراکنش از سرور درگاه، فرایند تحویل و آزمون‌های آن اضافه شود. تغییر صرف نام PAYMENT_MODE درگاه واقعی ایجاد نمی‌کند؛ مقادیر ناشناخته رد می‌شوند.

## اتصال محصولات به ربات موجود

این پل با جدول `products` ربات نسخه موجود سازگار است. **یک‌طرفه از پنل سایت به ربات** است؛ کیف پول، کاربران و سفارش‌های ربات مستقل می‌مانند. از توکن تلگرام استفاده نمی‌کند و پیام ارسال نمی‌کند. ربات و سایت باید روی یک سرور به دیتابیس واقعی ربات دسترسی داشته باشند.

۱. ابتدا از دیتابیس ربات با SQLite backup نسخه پشتیبان تهیه کنید؛ روی کپی غیرعملیاتی آزمایش کنید.
۲. در `/etc/premiumstore.env` مسیر مطلق `BOT_DATABASE_PATH` را مشخص کنید. هرگز مسیر دیتابیس سایت یا فایل نمونه قدیمی را وارد نکنید.
۳. کاربر سرویس باید به فایل و پوشه دیتابیس ربات دسترسی خواندن/نوشتن داشته باشد؛ SQLite برای journal/WAL به پوشه نیز نیاز دارد. دسترسی را با گروه مشترک یا ACL محدود بدهید؛ از chmod 777 استفاده نکنید.
۴. برای محدودیت systemd، `sudo systemctl edit premiumstore` و بخش زیر را با مسیر واقعی پوشه دیتابیس اضافه کنید:

```ini
[Service]
ReadWritePaths=/absolute/path/to/bot-data
```

مسیر زیر `/home` با `ProtectHome=true` قابل دسترسی نیست؛ داده ربات را با توقف کنترل‌شده و اصلاح مسیر خود ربات به پوشه سرویس مثل `/var/lib/premiumbot` منتقل کنید. انتقال را بدون بکاپ انجام ندهید.

۵. سرویس را restart و یک محصول آزمایشی ایجاد/ویرایش کنید. صف تقریباً هر ۱۰ ثانیه پردازش می‌شود؛ وضعیت را در «همگام‌سازی ربات» ببینید. پس از رفع خطا، اجرای مجدد را بزنید.

پل فقط محصولات ساخته‌شده توسط خودش را تغییر می‌دهد و در `premium_web_product_map` نگاشت نگه می‌دارد؛ محصولات قدیمی خودکار ادغام نمی‌شوند. رباتی که فهرست را در حافظه cache کند نیازمند بازخوانی فهرست است. تصاویر و ویدیوی کامل در صفحه سایت می‌مانند؛ ربات عنوان/توضیح/قیمت/موجودی و لینک صفحه را دریافت می‌کند. تغییر مستقیم محصولات نگاشت‌شده در پنل قدیمی ربات در ویرایش بعدی سایت بازنویسی می‌شود.

اسکریپت `scripts/import_bot_catalog.py` صرفاً ابزار خروجی خواندنی از محصولات قدیمی برای بررسی مهاجرت است؛ import خودکار به دیتابیس زنده سایت نیست. شناسه‌ها و محصولات دارای تنوع/درخواست اختصاصی قبل از مهاجرت نیازمند نگاشت هستند.

## نگهداری، بکاپ و به‌روزرسانی

از دیتابیس سایت، پوشه media، کلید APP_SECRET و دیتابیس ربات همراه جدول نگاشت بکاپ هماهنگ بگیرید. بکاپ خصوصی و خارج web root نگه دارید. برای SQLite زنده از فرمان `.backup` استفاده کنید، نه کپی تنها فایل db هنگام نوشتن:

```bash
sudo install -d -m 700 /var/backups/premiumstore
sudo sqlite3 /var/lib/premiumstore/store.db '.backup /var/backups/premiumstore/store.db'
sudo cp -a /var/lib/premiumstore/media /var/backups/premiumstore/
```

برای بکاپ کاملاً هماهنگ سایت/ربات، هر دو نویسنده را موقتاً متوقف کنید. کلید محیطی را جدا و رمزگذاری‌شده نگه دارید. بازیابی را روی محیط آزمایشی بررسی کنید. در به‌روزرسانی ابتدا بکاپ، سپس جایگزینی کد/نصب requirements و restart؛ پوشه داده را جایگزین نکنید. مهاجرت نسخه۲ افزایشی است و جداول قدیمی سفارش را پاک نمی‌کند. نسخه‌های آتی نیازمند migration بررسی‌شده‌اند.

## امنیت و آزمون

نشست سمت سرور با توکن هش‌شده، HttpOnly/SameSite و Secure در production؛ CSRF برای عملیات احرازشده؛ کنترل مبدأ؛ هش scrypt برای رمز کارکنان؛ کنترل دسترسی روی هر API؛ محدودیت اندازه فایل/درخواست؛ ثبت رویداد؛ escape خروجی؛ جلوگیری از پرداخت تکراری و مصرف همزمان کوپن.

```powershell
.\.venv\Scripts\python -m pytest -q
Get-ChildItem public -Filter *.js -Recurse | ForEach-Object { node --check $_.FullName }
```

آزمون‌ها از دیتابیس موقت و اطلاعات ساختگی استفاده می‌کنند. گزارش محدوده بررسی: `docs/verification.md`. این تست‌ها جای آزمون عملی روی سرور، سرویس پیامکی، درگاه و نسخه واقعی ربات را نمی‌گیرند.

## ساختار

`backend/`: API و امنیت و همگام‌سازی؛ `public/`: سایت و پنل؛ `tests/`: تست؛ `deploy/`: Nginx و systemd؛ `catalog.json`: داده اولیه فقط در اولین راه‌اندازی؛ `.env.example`: تنظیمات نمونه. ویرایش catalog.json بعد از ایجاد دیتابیس، محصولات موجود را تغییر نمی‌دهد؛ از پنل استفاده کنید. دیتابیس، کلیدها، محیط مجازی، رسانه مشتری و فایل env را commit نکنید.
