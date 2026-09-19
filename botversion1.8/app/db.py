import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
import logging

from .config import DB_PATH, ORDER_ID_MIN_VALUE, PAYMENT_TIMEOUT_MIN

def _connect():
    db_path = Path(DB_PATH)
    parent = db_path.parent
    if parent and str(parent) not in {"", "."}:
        parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con

def db_execute(
    sql,
    params=(),
    *,
    fetchone=False,
    fetchall=False,
    return_lastrowid=False,
    commit: bool | None = None,
):
    with closing(_connect()) as con:
        cur = con.cursor()
        # خاموش کردن موقت چک کلید خارجی برای جلوگیری از کرش‌های ناخواسته در دیتابیس‌های قدیمی
        try:
            cur.execute("PRAGMA foreign_keys=OFF;")
        except:
            pass
            
        cur.execute(sql, params)
        do_commit = True if commit is None else bool(commit)
        if do_commit:
            con.commit()
        if return_lastrowid:
            return cur.lastrowid
        if fetchone:
            r = cur.fetchone()
            return dict(r) if r else None
        if fetchall:
            return [dict(x) for x in cur.fetchall()]
    return None


def _ensure_order_sequence_min(min_order_id: int) -> None:
    try:
        target = int(min_order_id or 0)
    except (TypeError, ValueError):
        target = 0
    if target <= 0:
        return

    target_seq = target - 1
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("SELECT IFNULL(MAX(id), 0) FROM orders")
        current_max = cur.fetchone()[0] or 0
        if current_max >= target:
            return
        try:
            cur.execute("SELECT seq FROM sqlite_sequence WHERE name='orders'")
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO sqlite_sequence(name, seq) VALUES(?, ?)",
                    ("orders", target_seq),
                )
            else:
                cur.execute(
                    "UPDATE sqlite_sequence SET seq=? WHERE name='orders'",
                    (target_seq,),
                )
            con.commit()
        except sqlite3.OperationalError:
            cur.execute("INSERT INTO orders(id) VALUES(?)", (target_seq,))
            con.commit()
            cur.execute("DELETE FROM orders WHERE id=?", (target_seq,))
            con.commit()


def ensure_order_id_floor(min_order_id: int | None = None) -> None:
    if min_order_id is None:
        min_order_id = ORDER_ID_MIN_VALUE
    _ensure_order_sequence_min(min_order_id)
            
def _table_exists(con, name):
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

def _col_exists(con, table, col):
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    return col in cols


def _get_table_columns(cur, table: str) -> list[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]


def _create_orders_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, username TEXT, first_name TEXT,
            plan_id TEXT, plan_title TEXT, price TEXT,
            receipt_file_id TEXT, receipt_text TEXT,
            status TEXT, created_at TEXT, updated_at TEXT
        );
        """
    )


def _add_missing_columns(con, cur) -> None:
    add_cols = [
        ("orders", "service_category", "TEXT"),
        ("orders", "service_code", "TEXT"),
        ("orders", "account_mode", "TEXT"),
        ("orders", "customer_email", "TEXT"),
        ("orders", "customer_secret_encrypted", "TEXT"),
        ("orders", "amount_total", "INTEGER"),
        ("orders", "currency", "TEXT"),
        ("orders", "payment_type", "TEXT"),
        ("orders", "wallet_used_amount", "INTEGER DEFAULT 0"),
        ("orders", "wallet_reserved_amount", "INTEGER DEFAULT 0"),
        ("orders", "await_deadline", "TEXT"),
        ("orders", "notes", "TEXT"),
        ("orders", "customer_message", "TEXT"),
        ("orders", "manager_note", "TEXT"),
        ("orders", "internal_cost", "INTEGER DEFAULT 0"),
        ("orders", "net_revenue", "INTEGER DEFAULT 0"),
        ("orders", "require_username", "INTEGER DEFAULT 0"),
        ("orders", "require_password", "INTEGER DEFAULT 0"),
        ("orders", "customer_username", "TEXT"),
        ("orders", "customer_password", "TEXT"),
        ("orders", "allow_first_plan", "INTEGER DEFAULT 0"),
        ("orders", "cashback_percent", "INTEGER DEFAULT 0"),
        ("orders", "cashback_applied_amount", "INTEGER DEFAULT 0"),
        ("orders", "discount_id", "INTEGER"),
        ("orders", "discount_code", "TEXT"),
        ("orders", "discount_amount", "INTEGER DEFAULT 0"),
        ("products", "description", "TEXT DEFAULT ''"),
        ("products", "price", "INTEGER DEFAULT 0"),
        ("products", "available", "INTEGER DEFAULT 1"),
        ("products", "is_category", "INTEGER DEFAULT 0"),
        ("products", "request_only", "INTEGER DEFAULT 0"),
        ("products", "account_enabled", "INTEGER DEFAULT 0"),
        ("products", "self_available", "INTEGER DEFAULT 0"),
        ("products", "self_price", "INTEGER DEFAULT 0"),
        # ستون‌های جدید برای نیازهای خاص مود "اکانت خودم"
        ("products", "self_require_username", "INTEGER DEFAULT 0"),
        ("products", "self_require_password", "INTEGER DEFAULT 0"),
        
        ("products", "pre_available", "INTEGER DEFAULT 0"),
        ("products", "pre_price", "INTEGER DEFAULT 0"),
        ("products", "require_username", "INTEGER DEFAULT 0"),
        ("products", "require_password", "INTEGER DEFAULT 0"),
        ("products", "allow_first_plan", "INTEGER DEFAULT 0"),
        ("products", "cashback_enabled", "INTEGER DEFAULT 0"),
        ("products", "cashback_percent", "INTEGER DEFAULT 0"),
        ("products", "sort_order", "INTEGER DEFAULT 0"),
        ("products", "created_at", "TEXT"),
        ("products", "updated_at", "TEXT"),
        ("users", "contact_phone", "TEXT"),
        ("users", "contact_verified", "INTEGER DEFAULT 0"),
        ("users", "contact_shared_at", "TEXT"),
        ("users", "is_blocked", "INTEGER DEFAULT 0"),
        ("service_messages", "updated_at", "TEXT"),
        ("coupons", "is_active", "INTEGER DEFAULT 1"),
        ("coupons", "usage_limit_per_user", "INTEGER DEFAULT 1"),
        ("coupon_redemptions", "times_used", "INTEGER DEFAULT 1"),
        # ستون‌های حیاتی برای رفع خطای شما
        ("discount_redemptions", "order_id", "INTEGER"),
        ("discount_redemptions", "times_used", "INTEGER DEFAULT 1"),
        ("discount_redemptions", "redeemed_at", "TEXT"),
        ("discount_redemptions", "status", "TEXT DEFAULT 'CONFIRMED'"),
    ]
    for t, c, typ in add_cols:
        if _table_exists(con, t) and not _col_exists(con, t, c):
            try:
                cur.execute(f"ALTER TABLE {t} ADD COLUMN {c} {typ};")
            except Exception:
                pass


def _ensure_orders_have_id(con, cur) -> None:
    if not _table_exists(con, "orders"):
        return
    cols = _get_table_columns(cur, "orders")
    if "id" in cols:
        return
    cur.execute("ALTER TABLE orders RENAME TO orders_old;")
    _create_orders_table(cur)
    _add_missing_columns(con, cur)
    old_cols = set(_get_table_columns(cur, "orders_old"))
    new_cols = _get_table_columns(cur, "orders")
    dest_cols = []
    select_cols = []
    if "id" in new_cols:
        dest_cols.append("id")
        select_cols.append("rowid")
    for col in new_cols:
        if col == "id" or col not in old_cols:
            continue
        dest_cols.append(col)
        select_cols.append(col)
    if dest_cols:
        cols_sql = ",".join(dest_cols)
        select_sql = ",".join(select_cols)
        cur.execute(f"INSERT INTO orders ({cols_sql}) SELECT {select_sql} FROM orders_old;")
    cur.execute("DROP TABLE orders_old;")
    con.commit()

def init_db():
    with closing(_connect()) as con:
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT, first_name TEXT,
            wallet_balance INTEGER DEFAULT 0,
            ref_by INTEGER, ref_count INTEGER DEFAULT 0,
            earnings_total INTEGER DEFAULT 0,
            created_at TEXT, updated_at TEXT
        );
        """)
        _create_orders_table(cur)
        _ensure_orders_have_id(con, cur)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS products(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                price INTEGER DEFAULT 0,
                available INTEGER DEFAULT 1,
                is_category INTEGER DEFAULT 0,
                request_only INTEGER DEFAULT 0,
                account_enabled INTEGER DEFAULT 0,
                self_available INTEGER DEFAULT 0,
                self_price INTEGER DEFAULT 0,
                self_require_username INTEGER DEFAULT 0,
                self_require_password INTEGER DEFAULT 0,
                pre_available INTEGER DEFAULT 0,
                pre_price INTEGER DEFAULT 0,
                require_username INTEGER DEFAULT 0,
                require_password INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_products_parent ON products(parent_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_products_sort ON products(sort_order);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS service_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                category TEXT,
                message_text TEXT,
                attachment_file_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                is_resolved INTEGER DEFAULT 0
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_service_messages_category ON service_messages(category);")
        _add_missing_columns(con, cur)
        con.commit()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_tx(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            order_id INTEGER,
            amount INTEGER NOT NULL,
            type TEXT NOT NULL,
            note TEXT,
            created_at TEXT
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_wallet_user ON wallet_tx(user_id);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS order_manager_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                user_id INTEGER,
                message_text TEXT,
                created_at TEXT
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_order_manager_messages_order ON order_manager_messages(order_id);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS service_message_replies(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_message_id INTEGER NOT NULL,
                user_id INTEGER,
                message_text TEXT,
                created_at TEXT
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_service_message_replies_msg ON service_message_replies(service_message_id);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_manager_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message_text TEXT,
                created_at TEXT
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_manager_messages_user ON user_manager_messages(user_id);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS coupons(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                amount INTEGER NOT NULL,
                usage_limit INTEGER NOT NULL,
                usage_limit_per_user INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                expires_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS coupon_redemptions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coupon_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                times_used INTEGER DEFAULT 1,
                redeemed_at TEXT,
                UNIQUE(coupon_id, user_id),
                FOREIGN KEY(coupon_id) REFERENCES coupons(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_coupon ON coupon_redemptions(coupon_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_coupon_redemptions_user ON coupon_redemptions(user_id);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS discounts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                amount INTEGER NOT NULL,
                usage_limit INTEGER NOT NULL,
                usage_limit_per_user INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                applies_all INTEGER DEFAULT 0,
                product_ids TEXT DEFAULT '',
                expires_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS discount_redemptions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discount_id INTEGER NOT NULL,
                order_id INTEGER,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                times_used INTEGER DEFAULT 1,
                redeemed_at TEXT,
                status TEXT DEFAULT 'CONFIRMED',
                UNIQUE(discount_id, user_id),
                FOREIGN KEY(discount_id) REFERENCES discounts(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_discount_redemptions_discount ON discount_redemptions(discount_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_discount_redemptions_user ON discount_redemptions(user_id);")


def ensure_user(user_id: int, username: str, first_name: str):
    now = datetime.now().isoformat(timespec="seconds")
    row = db_execute("SELECT user_id FROM users WHERE user_id=?", (user_id,), fetchone=True)
    if not row:
        db_execute(
            "INSERT INTO users(user_id, username, first_name, created_at, updated_at) VALUES(?,?,?,?,?)",
            (user_id, username, first_name or "", now, now),
        )
    else:
        db_execute(
            "UPDATE users SET username=?, first_name=?, updated_at=? WHERE user_id=?",
            (username, first_name or "", now, user_id),
        )


def get_user(user_id: int):
    return db_execute("SELECT * FROM users WHERE user_id=?", (user_id,), fetchone=True)


def is_user_contact_verified(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    return bool(int(user.get("contact_verified") or 0))


def set_user_contact_verified(user_id: int, phone_number: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    db_execute(
        "UPDATE users SET contact_phone=?, contact_verified=1, contact_shared_at=?, updated_at=? WHERE user_id=?",
        (phone_number or "", now, now, user_id),
    )

def change_wallet(user_id: int, delta: int, tx_type: str, note: str = "", order_id: int | None = None):
    u = get_user(user_id)
    if not u:
        return False
    new_bal = int(u["wallet_balance"]) + int(delta)
    if new_bal < 0:
        return False
    now = datetime.now().isoformat(timespec="seconds")
    db_execute("UPDATE users SET wallet_balance=?, updated_at=? WHERE user_id=?", (new_bal, now, user_id))
    db_execute(
        "INSERT INTO wallet_tx(user_id, order_id, amount, type, note, created_at) VALUES(?,?,?,?,?,?)",
        (user_id, order_id, abs(delta), tx_type, note, now)
    )
    return True


def refresh_order_deadline(order_id: int, minutes: int | None = None) -> str:
    if minutes is None:
        minutes = PAYMENT_TIMEOUT_MIN
    now = datetime.now()
    refreshed_deadline = (now + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    db_execute(
        "UPDATE orders SET await_deadline=?, updated_at=? WHERE id=?",
        (refreshed_deadline, now.isoformat(timespec="seconds"), order_id),
    )
    return refreshed_deadline

def create_order(
    user,
    title: str,
    amount_total: int,
    currency: str,
    service_category: str,
    service_code: str,
    account_mode: str | None = None,
    customer_email: str | None = None,
    notes: str | None = None,
    customer_secret: str | None = None,
    *,
    require_username: bool = False,
    require_password: bool = False,
    customer_username: str | None = None,
    customer_password: str | None = None,
    allow_first_plan: bool = False,
    cashback_percent: int = 0,
    allow_free: bool = False,
) -> int | None:
    if isinstance(amount_total, str):
        amount_total = amount_total.replace(",", "").replace("،", "")
    try:
        amount_total = int(amount_total)
    except (TypeError, ValueError):
        return None

    if amount_total <= 0 and not allow_free:
        return None
    now = datetime.now()
    ensure_order_id_floor()
    oid = db_execute("""
        INSERT INTO orders(
            user_id, username, first_name,
            plan_id, plan_title, price,
            status, created_at, updated_at,
            amount_total, currency, service_category, service_code,
            account_mode, customer_email, notes,
            customer_secret_encrypted,
            require_username, require_password,
            customer_username, customer_password,
            allow_first_plan, cashback_percent,
            discount_id, discount_code, discount_amount
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        user["user_id"], user["username"], user["first_name"] or "",
        None, title, str(amount_total),
        "AWAITING_PAYMENT", now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"),
        amount_total, currency, service_category, service_code,
        account_mode or "", customer_email or "", notes or "",
        customer_secret or "",
        1 if require_username else 0,
        1 if require_password else 0,
        customer_username or "",
        customer_password or "",
        1 if allow_first_plan else 0,
        max(int(cashback_percent or 0), 0),
        None,
        "",
        0,
    ), return_lastrowid=True)
    await_deadline = (now + timedelta(minutes=PAYMENT_TIMEOUT_MIN)).isoformat(timespec="seconds")
    db_execute("UPDATE orders SET await_deadline=? WHERE id=?", (await_deadline, oid))
    return oid

def set_order_status(order_id: int, status: str):
    previous = get_order(order_id)
    db_execute(
        "UPDATE orders SET status=?, updated_at=? WHERE id=?",
        (status, datetime.now().isoformat(timespec="seconds"), order_id),
    )
    updated = get_order(order_id)
    cashback_statuses = {"DELIVERED", "COMPLETED"}
    if (
        updated
        and previous
        and previous.get("status") != updated.get("status")
        and updated.get("status") in cashback_statuses
    ):
        apply_order_cashback(order_id)

def set_order_receipt(order_id: int, file_id: str | None, text: str | None):
    db_execute("UPDATE orders SET receipt_file_id=?, receipt_text=?, updated_at=? WHERE id=?",
               (file_id, text, datetime.now().isoformat(timespec="seconds"), order_id))

def set_order_payment_type(order_id: int, ptype: str):
    db_execute("UPDATE orders SET payment_type=?, updated_at=? WHERE id=?", (ptype, datetime.now().isoformat(timespec="seconds"), order_id))

def set_order_wallet_reserved(order_id: int, amount: int):
    db_execute("UPDATE orders SET wallet_reserved_amount=?, updated_at=? WHERE id=?", (amount, datetime.now().isoformat(timespec="seconds"), order_id))

def set_order_wallet_used(order_id: int, amount: int):
    db_execute("UPDATE orders SET wallet_used_amount=?, updated_at=? WHERE id=?", (amount, datetime.now().isoformat(timespec="seconds"), order_id))

def set_order_customer_message(order_id: int, message: str | None):
    db_execute(
        "UPDATE orders SET customer_message=?, updated_at=? WHERE id=?",
        (message or "", datetime.now().isoformat(timespec="seconds"), order_id),
    )

def set_order_manager_note(order_id: int, note: str | None):
    db_execute(
        "UPDATE orders SET manager_note=?, updated_at=? WHERE id=?",
        (note or "", datetime.now().isoformat(timespec="seconds"), order_id),
    )


def apply_order_cashback(order_id: int) -> int:
    order = get_order(order_id)
    if not order:
        return 0
    try:
        percent = max(int(order.get("cashback_percent") or 0), 0)
    except (TypeError, ValueError):
        percent = 0
    if percent <= 0:
        return 0
    base_amount = int(order.get("amount_total") or order.get("price") or 0)
    cashback_total = max((base_amount * percent) // 100, 0)
    already_applied = int(order.get("cashback_applied_amount") or 0)
    remaining = max(cashback_total - already_applied, 0)
    if remaining <= 0 or not order.get("user_id"):
        return 0
    success = change_wallet(
        order["user_id"], remaining, "CREDIT", note=f"CASHBACK:ORDER:{order_id}", order_id=order_id
    )
    if not success:
        return 0
    db_execute(
        "UPDATE orders SET cashback_applied_amount=?, updated_at=? WHERE id=?",
        (cashback_total, datetime.now().isoformat(timespec="seconds"), order_id),
    )
    return remaining


def add_order_manager_message(order_id: int, user_id: int | None, message: str) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    return db_execute(
        """
        INSERT INTO order_manager_messages(order_id, user_id, message_text, created_at)
        VALUES(?,?,?,?)
        """,
        (order_id, user_id, message or "", now),
        return_lastrowid=True,
    )


def list_order_manager_messages(order_id: int, limit: int = 50) -> list[dict[str, Any]]:
    return db_execute(
        """
        SELECT * FROM order_manager_messages
        WHERE order_id=?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (order_id, limit),
        fetchall=True,
    )


def add_user_manager_message(user_id: int, message_text: str) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    return db_execute(
        """
        INSERT INTO user_manager_messages(user_id, message_text, created_at)
        VALUES(?,?,?)
        """,
        (user_id, message_text or "", now),
        return_lastrowid=True,
    )


def list_user_manager_messages(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    return db_execute(
        """
        SELECT * FROM user_manager_messages
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
        fetchall=True,
    )


def set_order_financials(order_id: int, cost_amount: int) -> None:
    order = get_order(order_id)
    if not order:
        return
    try:
        cost = max(int(cost_amount or 0), 0)
    except (TypeError, ValueError):
        cost = 0
    total = int(order.get("amount_total") or order.get("price") or 0)
    net = max(total - cost, 0)
    db_execute(
        "UPDATE orders SET internal_cost=?, net_revenue=?, updated_at=? WHERE id=?",
        (cost, net, datetime.now().isoformat(timespec="seconds"), order_id),
    )

def set_order_customer_secret(order_id: int, secret: str | None):
    db_execute(
        "UPDATE orders SET customer_secret_encrypted=?, updated_at=? WHERE id=?",
        (secret or "", datetime.now().isoformat(timespec="seconds"), order_id),
    )

def get_order(order_id: int):
    return db_execute("SELECT * FROM orders WHERE id=?", (order_id,), fetchone=True)


def get_order_payable_amount(order: dict | None) -> int:
    if not order:
        return 0
    try:
        base = int(order.get("amount_total") or order.get("price") or 0)
    except (TypeError, ValueError):
        base = 0
    try:
        discount = max(int(order.get("discount_amount") or 0), 0)
    except (TypeError, ValueError):
        discount = 0
    return max(base - discount, 0)

def user_has_delivered_order(user_id: int) -> bool:
    row = db_execute(
        """
        SELECT 1 FROM orders
        WHERE user_id=? AND status IN ('DELIVERED','COMPLETED')
        LIMIT 1
        """,
        (user_id,),
        fetchone=True,
    )
    return bool(row)

def _normalize_cart_orders(user_id: int, order_id: int | None = None):
    now = datetime.now()
    now_iso = now.isoformat(timespec="seconds")

    filters = ["user_id=?", "status IN ('AWAITING_PAYMENT','PENDING_CONFIRM','', 'در انتظار پرداخت')"]
    params: list[int | str] = [user_id]
    if order_id:
        filters.append("id=?")
        params.append(order_id)

    candidates = db_execute(
        f"""
        SELECT * FROM orders
        WHERE {' AND '.join(filters)}
        """,
        tuple(params),
        fetchall=True,
    ) or []

    valid_ids: list[int] = []
    for o in candidates:
        oid = int(o.get("id"))
        status = (o.get("status") or "").strip()
        if status in {"", "در انتظار پرداخت"}:
            set_order_status(oid, "AWAITING_PAYMENT")
            o["status"] = "AWAITING_PAYMENT"
        elif status not in {"AWAITING_PAYMENT", "PENDING_CONFIRM"}:
            continue

        deadline_raw = (o.get("await_deadline") or "").strip()
        if not deadline_raw:
            deadline_raw = refresh_order_deadline(oid)
            o["await_deadline"] = deadline_raw
        try:
            if deadline_raw and datetime.fromisoformat(deadline_raw) <= now:
                set_order_status(oid, "EXPIRED")
                continue
        except ValueError:
            deadline_raw = refresh_order_deadline(oid)
            o["await_deadline"] = deadline_raw

        valid_ids.append(oid)

    if not valid_ids:
        return []

    placeholders = ",".join("?" for _ in valid_ids)
    return db_execute(
        f"""
        SELECT * FROM orders
        WHERE id IN ({placeholders})
          AND (await_deadline IS NULL OR await_deadline='' OR await_deadline > ?)
        ORDER BY await_deadline ASC
        """,
        (*valid_ids, now_iso),
        fetchall=True,
    )


def list_cart_orders(user_id: int):
    return _normalize_cart_orders(user_id)


def get_cart_order(order_id: int, user_id: int):
    orders = _normalize_cart_orders(user_id, order_id)
    return orders[0] if orders else None

def expire_orders_and_refund():
    expired = db_execute("""
        SELECT * FROM orders
        WHERE status='AWAITING_PAYMENT' AND await_deadline IS NOT NULL AND await_deadline <= ?
    """, (datetime.now().isoformat(timespec="seconds"),), fetchall=True)
    for o in expired:
        rid = int(o["id"])
        reserved = int(o.get("wallet_reserved_amount") or 0)
        if reserved > 0:
            change_wallet(o["user_id"], reserved, "REFUND", note=f"Expire order #{rid}", order_id=rid)
            set_order_wallet_reserved(rid, 0)
        set_order_status(rid, "EXPIRED")
    return expired


def create_coupon(
    code: str,
    amount: int,
    usage_limit: int,
    expires_at: str | None = None,
    *,
    usage_limit_per_user: int | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    normalized = (code or "").strip().upper()
    if not normalized:
        raise ValueError("Coupon code cannot be empty")
    per_user = 1 if usage_limit_per_user is None else int(usage_limit_per_user)
    return db_execute(
        """
        INSERT INTO coupons(code, amount, usage_limit, usage_limit_per_user, used_count, expires_at, created_at, updated_at, is_active)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (normalized, int(amount), int(usage_limit), per_user, 0, expires_at, now, now, 1),
        return_lastrowid=True,
    )


def update_coupon(
    coupon_id: int,
    *,
    code: str,
    amount: int,
    usage_limit: int,
    usage_limit_per_user: int,
    expires_at: str | None,
    is_active: bool | int | None = None,
) -> bool:
    now = datetime.now().isoformat(timespec="seconds")
    normalized = (code or "").strip().upper()
    if not normalized:
        return False
    updates = [
        "code=?",
        "amount=?",
        "usage_limit=?",
        "usage_limit_per_user=?",
        "expires_at=?",
        "updated_at=?",
    ]
    params: list[Any] = [normalized, int(amount), int(usage_limit), int(usage_limit_per_user), expires_at, now]
    if is_active is not None:
        updates.append("is_active=?")
        params.append(1 if bool(is_active) else 0)
    params.append(coupon_id)
    db_execute(
        f"""
        UPDATE coupons
        SET {', '.join(updates)}
        WHERE id=?
        """,
        tuple(params),
    )
    return True


def set_coupon_active(coupon_id: int, active: bool) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    db_execute(
        "UPDATE coupons SET is_active=?, updated_at=? WHERE id=?",
        (1 if active else 0, now, coupon_id),
    )


def delete_coupon(coupon_id: int) -> None:
    db_execute("DELETE FROM coupons WHERE id=?", (coupon_id,))


def list_coupons(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    rows = db_execute(
        """
        SELECT * FROM coupons
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
        fetchall=True,
    ) or []
    for row in rows:
        if not row.get("expires_at"):
            row["expires_at"] = None
        row["usage_limit_per_user"] = int(row.get("usage_limit_per_user") or 1)
        row["is_active"] = bool(int(row.get("is_active") or 0))
    return rows


def get_coupon(coupon_id: int):
    row = db_execute("SELECT * FROM coupons WHERE id=?", (coupon_id,), fetchone=True)
    if row:
        if not row.get("expires_at"):
            row["expires_at"] = None
        row["usage_limit_per_user"] = int(row.get("usage_limit_per_user") or 1)
        row["is_active"] = bool(int(row.get("is_active") or 0))
    return row


def list_coupon_redemptions(coupon_id: int) -> list[dict[str, Any]]:
    return db_execute(
        """
        SELECT user_id, amount, redeemed_at, times_used
        FROM coupon_redemptions
        WHERE coupon_id=?
        ORDER BY redeemed_at DESC
        """,
        (coupon_id,),
        fetchall=True,
    ) or []


def get_coupon_by_code(code: str):
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    row = db_execute("SELECT * FROM coupons WHERE UPPER(code)=?", (normalized,), fetchone=True)
    if row:
        if not row.get("expires_at"):
            row["expires_at"] = None
        row["usage_limit_per_user"] = int(row.get("usage_limit_per_user") or 1)
        row["is_active"] = bool(int(row.get("is_active") or 0))
    return row


def redeem_coupon(user_id: int, code: str) -> tuple[bool, dict[str, Any] | None, str | None]:
    normalized = (code or "").strip().upper()
    if not normalized:
        return False, None, "کد کوپن نامعتبر است."

    coupon = get_coupon_by_code(normalized)
    if not coupon:
        return False, None, "چنین کدی وجود ندارد."

    if not coupon.get("is_active"):
        return False, None, "این کوپن غیرفعال است."

    try:
        amount = int(coupon.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return False, None, "مبلغ این کوپن معتبر نیست."

    limit = int(coupon.get("usage_limit") or 0)
    used = int(coupon.get("used_count") or 0)
    if limit and used >= limit:
        return False, None, "ظرفیت استفاده از این کوپن تکمیل شده است."

    expires_at = coupon.get("expires_at")
    if expires_at:
        try:
            expire_dt = datetime.fromisoformat(str(expires_at))
            if datetime.now() > expire_dt:
                return False, None, "تاریخ انقضای این کوپن گذشته است."
        except ValueError:
            pass

    redemption = db_execute(
        "SELECT id, times_used FROM coupon_redemptions WHERE coupon_id=? AND user_id=?",
        (coupon["id"], user_id),
        fetchone=True,
    )
    per_user_limit = int(coupon.get("usage_limit_per_user") or 1)
    existing_uses = int(redemption.get("times_used") or 0) if redemption else 0
    if per_user_limit and existing_uses >= per_user_limit:
        return False, None, "سقف استفاده شما از این کد تکمیل شده است."

    success = change_wallet(user_id, amount, "CREDIT", note=f"COUPON:{coupon['code']}")
    if not success:
        return False, None, "امکان واریز مبلغ کوپن وجود ندارد."

    now = datetime.now().isoformat(timespec="seconds")
    if redemption:
        new_uses = existing_uses + 1
        db_execute(
            "UPDATE coupon_redemptions SET times_used=?, redeemed_at=? WHERE id=?",
            (new_uses, now, redemption["id"]),
        )
    else:
        db_execute(
            """
            INSERT INTO coupon_redemptions(coupon_id, user_id, amount, times_used, redeemed_at)
            VALUES(?,?,?,?,?)
            """,
            (coupon["id"], user_id, amount, 1, now),
        )
    db_execute(
        "UPDATE coupons SET used_count=used_count+1, updated_at=? WHERE id=?",
        (now, coupon["id"]),
    )
    user = get_user(user_id)
    balance = int(user.get("wallet_balance") or 0) if user else 0
    return True, {"amount": amount, "balance": balance, "code": coupon["code"]}, None


def _serialize_product_ids(product_ids: Iterable[int]) -> str:
    return ",".join(str(int(pid)) for pid in product_ids if str(pid).isdigit())


def _parse_product_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    items = []
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            items.append(int(part))
    return items


def create_discount(
    code: str,
    amount: int,
    usage_limit: int,
    *,
    usage_limit_per_user: int | None = None,
    applies_all: bool = False,
    product_ids: Iterable[int] | None = None,
    expires_at: str | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    normalized = (code or "").strip().upper()
    if not normalized:
        raise ValueError("Discount code cannot be empty")
    per_user = 1 if usage_limit_per_user is None else int(usage_limit_per_user)
    product_list = _serialize_product_ids(product_ids or [])
    return db_execute(
        """
        INSERT INTO discounts(
            code, amount, usage_limit, usage_limit_per_user,
            used_count, is_active, applies_all, product_ids, expires_at,
            created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            normalized,
            int(amount),
            int(usage_limit),
            per_user,
            0,
            1,
            1 if applies_all else 0,
            product_list,
            expires_at,
            now,
            now,
        ),
        return_lastrowid=True,
    )


def update_discount(
    discount_id: int,
    *,
    code: str,
    amount: int,
    usage_limit: int,
    usage_limit_per_user: int,
    applies_all: bool,
    product_ids: Iterable[int] | None,
    expires_at: str | None,
    is_active: bool | int | None = None,
) -> bool:
    now = datetime.now().isoformat(timespec="seconds")
    normalized = (code or "").strip().upper()
    if not normalized:
        return False
    updates = [
        "code=?",
        "amount=?",
        "usage_limit=?",
        "usage_limit_per_user=?",
        "applies_all=?",
        "product_ids=?",
        "expires_at=?",
        "updated_at=?",
    ]
    params: list[Any] = [
        normalized,
        int(amount),
        int(usage_limit),
        int(usage_limit_per_user),
        1 if applies_all else 0,
        _serialize_product_ids(product_ids or []),
        expires_at,
        now,
    ]
    if is_active is not None:
        updates.append("is_active=?")
        params.append(1 if bool(is_active) else 0)
    params.append(discount_id)
    db_execute(
        f"""
        UPDATE discounts
        SET {', '.join(updates)}
        WHERE id=?
        """,
        tuple(params),
    )
    return True


def set_discount_active(discount_id: int, active: bool) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    db_execute(
        "UPDATE discounts SET is_active=?, updated_at=? WHERE id=?",
        (1 if active else 0, now, discount_id),
    )


def delete_discount(discount_id: int) -> None:
    db_execute("DELETE FROM discounts WHERE id=?", (discount_id,))


def list_discounts(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    rows = db_execute(
        """
        SELECT * FROM discounts
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
        fetchall=True,
    ) or []
    for row in rows:
        if not row.get("expires_at"):
            row["expires_at"] = None
        row["usage_limit_per_user"] = int(row.get("usage_limit_per_user") or 1)
        row["is_active"] = bool(int(row.get("is_active") or 0))
        row["applies_all"] = bool(int(row.get("applies_all") or 0))
        row["product_ids"] = _parse_product_ids(row.get("product_ids"))
    return rows


def get_discount(discount_id: int):
    row = db_execute("SELECT * FROM discounts WHERE id=?", (discount_id,), fetchone=True)
    if row:
        if not row.get("expires_at"):
            row["expires_at"] = None
        row["usage_limit_per_user"] = int(row.get("usage_limit_per_user") or 1)
        row["is_active"] = bool(int(row.get("is_active") or 0))
        row["applies_all"] = bool(int(row.get("applies_all") or 0))
        row["product_ids"] = _parse_product_ids(row.get("product_ids"))
    return row


def get_discount_by_code(code: str):
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    row = db_execute("SELECT * FROM discounts WHERE UPPER(code)=?", (normalized,), fetchone=True)
    if row:
        if not row.get("expires_at"):
            row["expires_at"] = None
        row["usage_limit_per_user"] = int(row.get("usage_limit_per_user") or 1)
        row["is_active"] = bool(int(row.get("is_active") or 0))
        row["applies_all"] = bool(int(row.get("applies_all") or 0))
        row["product_ids"] = _parse_product_ids(row.get("product_ids"))
    return row


def list_discount_redemptions(discount_id: int) -> list[dict[str, Any]]:
    return db_execute(
        """
        SELECT user_id, order_id, amount, redeemed_at, times_used
        FROM discount_redemptions
        WHERE discount_id=?
        ORDER BY redeemed_at DESC
        """,
        (discount_id,),
        fetchall=True,
    ) or []


def _order_product_id(order: dict | None) -> int | None:
    if not order:
        return None
    code = order.get("service_code") or ""
    if code.startswith("product:"):
        try:
            return int(code.split(":", 1)[1])
        except (IndexError, ValueError):
            return None
    return None


def _repair_discount_table(con, cur) -> None:
    """Checks and repairs the discount_redemptions table structure to prevent errors."""
    try:
        cur.execute("PRAGMA table_info(discount_redemptions)")
        columns = {row["name"] for row in cur.fetchall()}
        
        if "order_id" not in columns:
            cur.execute("ALTER TABLE discount_redemptions ADD COLUMN order_id INTEGER")
        
        if "times_used" not in columns:
            cur.execute("ALTER TABLE discount_redemptions ADD COLUMN times_used INTEGER DEFAULT 1")
        
        if "redeemed_at" not in columns:
            cur.execute("ALTER TABLE discount_redemptions ADD COLUMN redeemed_at TEXT")
            
        if "status" not in columns:
            cur.execute("ALTER TABLE discount_redemptions ADD COLUMN status TEXT DEFAULT 'CONFIRMED'")
            
        con.commit()
    except Exception:
        pass


def apply_discount_to_order(
    order_id: int, user_id: int, code: str
) -> tuple[bool, dict[str, Any] | None, str | None]:
    try:
        with closing(_connect()) as con:
            _repair_discount_table(con, con.cursor())
    except Exception:
        pass

    order = get_order(order_id)
    if not order or order.get("user_id") != user_id:
        return False, None, "سفارش نامعتبر است."
    if order.get("status") != "AWAITING_PAYMENT":
        return False, None, "وضعیت سفارش اجازه ثبت تخفیف نمی‌دهد."
    if (order.get("discount_code") or "").strip():
        return False, None, "روی این سفارش قبلاً کد تخفیف ثبت شده است."

    normalized = (code or "").strip().upper()
    if not normalized:
        return False, None, "کد تخفیف نامعتبر است."
    discount = get_discount_by_code(normalized)
    if not discount:
        return False, None, "کد تخفیف یافت نشد."
    if not discount.get("is_active"):
        return False, None, "این کد تخفیف غیرفعال است."

    try:
        amount = int(discount.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return False, None, "مبلغ تخفیف معتبر نیست."

    limit = int(discount.get("usage_limit") or 0)
    used = int(discount.get("used_count") or 0)
    if limit and used >= limit:
        return False, None, "ظرفیت استفاده از این کد تکمیل شده است."

    expires_at = discount.get("expires_at")
    if expires_at:
        try:
            expire_dt = datetime.fromisoformat(str(expires_at))
            if datetime.now() > expire_dt:
                return False, None, "تاریخ انقضای این کد گذشته است."
        except ValueError:
            pass

    product_id = _order_product_id(order)
    allowed_products = discount.get("product_ids") or []
    if isinstance(allowed_products, str):
        allowed_products = _parse_product_ids(allowed_products)

    if (not discount.get("applies_all")) and allowed_products and product_id is not None:
        if product_id not in allowed_products:
            return False, None, "این کد برای محصول انتخاب‌شده معتبر نیست."

    redemption = db_execute(
        "SELECT id, times_used FROM discount_redemptions WHERE discount_id=? AND user_id=?",
        (discount["id"], user_id),
        fetchone=True,
    )
    per_user_limit = int(discount.get("usage_limit_per_user") or 1)
    existing_uses = int(redemption.get("times_used") or 0) if redemption else 0
    if per_user_limit and existing_uses >= per_user_limit:
        return False, None, "سقف استفاده شما از این کد تکمیل شده است."

    base_amount = int(order.get("amount_total") or order.get("price") or 0)
    discount_value = min(max(amount, 0), max(base_amount, 0))
    payable = max(base_amount - discount_value, 0)

    now = datetime.now().isoformat(timespec="seconds")

    db_execute(
        """
        UPDATE orders
        SET discount_id=?, discount_code=?, discount_amount=?, updated_at=?
        WHERE id=?
        """,
        (discount["id"], discount["code"], discount_value, now, order_id),
    )

    if redemption:
        new_uses = existing_uses + 1
        db_execute(
            """
            UPDATE discount_redemptions 
            SET times_used=?, order_id=?, redeemed_at=?, status=? 
            WHERE id=?
            """,
            (new_uses, order_id, now, "CONFIRMED", redemption["id"]),
        )
    else:
        db_execute(
            """
            INSERT INTO discount_redemptions(
                discount_id, user_id, order_id, amount, 
                times_used, redeemed_at, status
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (discount["id"], user_id, order_id, discount_value, 1, now, "CONFIRMED"),
        )

    db_execute(
        "UPDATE discounts SET used_count=used_count+1, updated_at=? WHERE id=?",
        (now, discount["id"]),
    )

    return True, {"discount": discount_value, "payable": payable, "code": discount["code"]}, None


# ====== Stats & History ======
def get_user_stats(user_id: int):
    u = db_execute("SELECT * FROM users WHERE user_id=?", (user_id,), fetchone=True) or {}
    total = db_execute("SELECT COUNT(*) AS c FROM orders WHERE user_id=?", (user_id,), fetchone=True)["c"]
    inprog = db_execute("""
        SELECT COUNT(*) AS c FROM orders
        WHERE user_id=? AND status IN ('PENDING_CONFIRM','PENDING_PLAN','APPROVED','IN_PROGRESS','READY_TO_DELIVER')
    """, (user_id,), fetchone=True)["c"]
    done = db_execute("""
        SELECT COUNT(*) AS c FROM orders
        WHERE user_id=? AND status IN ('DELIVERED','COMPLETED')
    """, (user_id,), fetchone=True)["c"]
    return {
        "wallet_balance": int(u.get("wallet_balance") or 0),
        "ref_count": int(u.get("ref_count") or 0),
        "earnings_total": int(u.get("earnings_total") or 0),
        "orders_total": int(total or 0),
        "orders_inprog": int(inprog or 0),
        "orders_done": int(done or 0),
    }

def list_orders_by_category(user_id: int, category: str, limit: int = 10, offset: int = 0):
    where = "user_id=?"
    params = [user_id]
    if category == "inprog":
        where += " AND status IN ('PENDING_CONFIRM','PENDING_PLAN','APPROVED','IN_PROGRESS','READY_TO_DELIVER')"
    elif category == "done":
        where += " AND status IN ('DELIVERED','COMPLETED')"
    elif category == "all":
        where += " AND 1=1"
    else:
        where += " AND 1=0"

    sql = f"SELECT * FROM orders WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    return db_execute(sql, tuple(params), fetchall=True)

def count_orders_by_category(user_id: int, category: str):
    where = "user_id=?"
    params = [user_id]
    if category == "inprog":
        where += " AND status IN ('PENDING_CONFIRM','PENDING_PLAN','APPROVED','IN_PROGRESS','READY_TO_DELIVER')"
    elif category == "done":
        where += " AND status IN ('DELIVERED','COMPLETED')"
    elif category == "all":
        where += " AND 1=1"
    else:
        where += " AND 1=0"
    sql = f"SELECT COUNT(*) AS c FROM orders WHERE {where}"
    r = db_execute(sql, tuple(params), fetchone=True)
    return int(r["c"] if r else 0)

def set_user_phone_verified(user_id: int, phone: str):
    try:
        db_execute("ALTER TABLE users ADD COLUMN phone TEXT", (), commit=True)
    except Exception:
        pass
    try:
        db_execute("ALTER TABLE users ADD COLUMN phone_verified INTEGER DEFAULT 0", (), commit=True)
    except Exception:
        pass
    db_execute("UPDATE users SET phone=?, phone_verified=1 WHERE id=?", (phone, user_id))
    return True


# ====== Admin web helpers =====

ORDER_STATUS_LABELS: dict[str, str] = {
    "AWAITING_PAYMENT": "در انتظار پرداخت",
    "PENDING_CONFIRM": "در انتظار تایید پرداخت",
    "PENDING_PLAN": "در انتظار تایید طرح",
    "PLAN_CONFIRMED": "طرح تایید شد",
    "APPROVED": "پرداخت تایید شد",
    "IN_PROGRESS": "در حال انجام",
    "READY_TO_DELIVER": "آماده تحویل",
    "DELIVERED": "تحویل شد",
    "COMPLETED": "تکمیل‌شده",
    "EXPIRED": "منقضی",
    "REJECTED": "رد شده",
    "CANCELED": "لغو شده",
}

PAYMENT_TYPE_LABELS: dict[str, str] = {
    "CARD": "پرداخت کارت",
    "WALLET": "کیف پول",
    "MIXED": "ترکیبی",
    "FIRST_PLAN": "طرح خرید اول",
}


def _build_where(parts: Iterable[str]) -> str:
    clauses = [p for p in parts if p]
    return " AND ".join(clauses) if clauses else "1=1"


def get_dashboard_snapshot():
    now = datetime.now()
    last_7_days = (now - timedelta(days=7)).isoformat(timespec="seconds")
    last_30_days = (now - timedelta(days=30)).isoformat(timespec="seconds")

    totals = db_execute(
        "SELECT COUNT(*) AS total FROM orders",
        fetchone=True,
    ) or {"total": 0}
    users = db_execute("SELECT COUNT(*) AS total FROM users", fetchone=True) or {"total": 0}
    status_counts = {
        row["status"]: row["c"]
        for row in db_execute(
            "SELECT status, COUNT(*) AS c FROM orders GROUP BY status",
            fetchall=True,
        )
    }
    awaiting = status_counts.get("AWAITING_PAYMENT", 0)
    pending = status_counts.get("PENDING_CONFIRM", 0)
    in_queue = sum(
        status_counts.get(code, 0)
        for code in ("APPROVED", "IN_PROGRESS", "READY_TO_DELIVER")
    )
    delivered = sum(
        status_counts.get(code, 0)
        for code in ("DELIVERED", "COMPLETED")
    )

    revenue_total = db_execute(
        """
        SELECT COALESCE(SUM(amount_total), 0) AS total
        FROM orders
        WHERE status IN ('APPROVED','IN_PROGRESS','READY_TO_DELIVER','DELIVERED','COMPLETED')
        """,
        fetchone=True,
    )["total"]
    revenue_30 = db_execute(
        """
        SELECT COALESCE(SUM(amount_total), 0) AS total
        FROM orders
        WHERE created_at >= ?
    """,
        (last_30_days,),
        fetchone=True,
    )["total"]
    new_orders_week = db_execute(
        "SELECT COUNT(*) AS c FROM orders WHERE created_at >= ?",
        (last_7_days,),
        fetchone=True,
    )["c"]

    wallet_totals = {
        row["type"]: row["total"]
        for row in db_execute(
            "SELECT type, COALESCE(SUM(amount), 0) AS total FROM wallet_tx GROUP BY type",
            fetchall=True,
        )
    }

    return {
        "orders_total": totals["total"],
        "users_total": users["total"],
        "awaiting_payment": awaiting,
        "pending_confirm": pending,
        "in_queue": in_queue,
        "delivered": delivered,
        "revenue_total": revenue_total or 0,
        "revenue_30_days": revenue_30 or 0,
        "new_orders_week": new_orders_week or 0,
        "wallet_totals": wallet_totals,
        "status_counts": status_counts,
    }


def list_recent_orders(limit: int = 8):
    return db_execute(
        "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?",
        (limit,),
        fetchall=True,
    )


def list_recent_users(limit: int = 6):
    return db_execute(
        "SELECT * FROM users ORDER BY created_at DESC LIMIT ?",
        (limit,),
        fetchall=True,
    )


def list_recent_wallet_tx(limit: int = 10):
    return db_execute(
        "SELECT * FROM wallet_tx ORDER BY created_at DESC LIMIT ?",
        (limit,),
        fetchall=True,
    )


def list_orders(
    *,
    status: str | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
    user_id: int | None = None,
):
    where_parts: list[str] = []
    params: list[Any] = []

    if user_id is not None:
        where_parts.append("user_id=?")
        params.append(user_id)
    if status and status != "all":
        where_parts.append("status=?")
        params.append(status)

    if search:
        term = search.strip()
        if term.startswith("#"):
            term = term[1:]
        if term.isdigit():
            where_parts.append("id=?")
            params.append(int(term))
        else:
            like = f"%{term.lower()}%"
            where_parts.append(
                "(LOWER(username) LIKE ? OR LOWER(first_name) LIKE ? OR LOWER(plan_title) LIKE ? OR LOWER(customer_email) LIKE ?)"
            )
            params.extend([like, like, like, like])

    where_sql = _build_where(where_parts)
    sql = f"SELECT * FROM orders WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return db_execute(sql, tuple(params), fetchall=True)


def count_orders(status: str | None = None, search: str | None = None, user_id: int | None = None) -> int:
    where_parts: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        where_parts.append("user_id=?")
        params.append(user_id)
    if status and status != "all":
        where_parts.append("status=?")
        params.append(status)
    if search:
        term = search.strip()
        if term.startswith("#"):
            term = term[1:]
        if term.isdigit():
            where_parts.append("id=?")
            params.append(int(term))
        else:
            like = f"%{term.lower()}%"
            where_parts.append(
                "(LOWER(username) LIKE ? OR LOWER(first_name) LIKE ? OR LOWER(plan_title) LIKE ? OR LOWER(customer_email) LIKE ?)"
            )
            params.extend([like, like, like, like])

    where_sql = _build_where(where_parts)
    sql = f"SELECT COUNT(*) AS c FROM orders WHERE {where_sql}"
    result = db_execute(sql, tuple(params), fetchone=True)
    return int(result["c"] if result else 0)


def update_order_notes(order_id: int, notes: str) -> None:
    set_order_manager_note(order_id, notes)


def list_wallet_tx_for_order(order_id: int) -> list[dict[str, Any]]:
    return db_execute(
        "SELECT * FROM wallet_tx WHERE order_id=? ORDER BY created_at DESC",
        (order_id,),
        fetchall=True,
    )


def list_users(search: str | None = None, limit: int = 20, offset: int = 0):
    where_parts: list[str] = []
    params: list[Any] = []
    if search:
        term = search.strip()
        like = f"%{term.lower()}%"
        if term.isdigit():
            where_parts.append("user_id=?")
            params.append(int(term))
        where_parts.append("(LOWER(username) LIKE ? OR LOWER(first_name) LIKE ?)")
        params.extend([like, like])
    where_sql = _build_where(where_parts)
    sql = f"SELECT * FROM users WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return db_execute(sql, tuple(params), fetchall=True)


def count_users(search: str | None = None) -> int:
    where_parts: list[str] = []
    params: list[Any] = []
    if search:
        term = search.strip()
        like = f"%{term.lower()}%"
        if term.isdigit():
            where_parts.append("user_id=?")
            params.append(int(term))
        where_parts.append("(LOWER(username) LIKE ? OR LOWER(first_name) LIKE ?)")
        params.extend([like, like])
    where_sql = _build_where(where_parts)
    sql = f"SELECT COUNT(*) AS c FROM users WHERE {where_sql}"
    result = db_execute(sql, tuple(params), fetchone=True)
    return int(result["c"] if result else 0)


def set_user_blocked(user_id: int, blocked: bool) -> None:
    db_execute(
        "UPDATE users SET is_blocked=?, updated_at=? WHERE user_id=?",
        (1 if blocked else 0, datetime.now().isoformat(timespec="seconds"), user_id),
    )


def is_user_blocked(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    return bool(int(user.get("is_blocked") or 0))


def list_wallet_tx_for_user(user_id: int, limit: int = 20):
    return db_execute(
        "SELECT * FROM wallet_tx WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
        fetchall=True,
    )


def get_wallet_summary():
    totals = db_execute(
        "SELECT type, COALESCE(SUM(amount), 0) AS total FROM wallet_tx GROUP BY type",
        fetchall=True,
    )
    by_type = {row["type"]: row["total"] for row in totals}
    balance_total = db_execute(
        "SELECT COALESCE(SUM(wallet_balance), 0) AS total FROM users",
        fetchone=True,
    )["total"]
    return {
        "by_type": by_type,
        "user_balances": balance_total or 0,
    }


def create_service_message(
    user_id: int,
    username: str | None,
    first_name: str | None,
    category: str,
    message_text: str,
    attachment_file_id: str | None = None,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    return db_execute(
        """
        INSERT INTO service_messages(user_id, username, first_name, category, message_text, attachment_file_id, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            user_id,
            username or "",
            first_name or "",
            category,
            message_text or "",
            attachment_file_id or "",
            now,
            now,
        ),
        return_lastrowid=True,
    )


def list_service_messages(
    *,
    category: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where_parts: list[str] = []
    params: list[Any] = []
    if category:
        where_parts.append("category=?")
        params.append(category)
    where_sql = _build_where(where_parts)
    sql = f"SELECT * FROM service_messages WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return db_execute(sql, tuple(params), fetchall=True)


def count_service_messages(category: str | None = None) -> int:
    where_parts: list[str] = []
    params: list[Any] = []
    if category:
        where_parts.append("category=?")
        params.append(category)
    where_sql = _build_where(where_parts)
    sql = f"SELECT COUNT(*) AS c FROM service_messages WHERE {where_sql}"
    result = db_execute(sql, tuple(params), fetchone=True)
    return int(result["c"] if result else 0)


def get_service_message(message_id: int) -> dict[str, Any] | None:
    return db_execute(
        "SELECT * FROM service_messages WHERE id=?",
        (message_id,),
        fetchone=True,
    )


def add_service_message_reply(message_id: int, user_id: int | None, text: str) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    return db_execute(
        """
        INSERT INTO service_message_replies(service_message_id, user_id, message_text, created_at)
        VALUES(?,?,?,?)
        """,
        (message_id, user_id, text or "", now),
        return_lastrowid=True,
    )


def list_service_message_replies(message_id: int) -> list[dict[str, Any]]:
    return db_execute(
        """
        SELECT * FROM service_message_replies
        WHERE service_message_id=?
        ORDER BY created_at DESC
        """,
        (message_id,),
        fetchall=True,
    )


def set_service_message_status(message_id: int, resolved: bool) -> None:
    db_execute(
        "UPDATE service_messages SET is_resolved=?, updated_at=? WHERE id=?",
        (1 if resolved else 0, datetime.now().isoformat(timespec="seconds"), message_id),
    )


# ====== Products Catalog ======


def list_products(parent_id: int | None = None) -> list[dict[str, Any]]:
    return db_execute(
        """
        SELECT * FROM products
        WHERE COALESCE(parent_id, 0)=COALESCE(?, 0)
        ORDER BY sort_order ASC, title ASC
        """,
        (parent_id,),
        fetchall=True,
    )


def list_all_products() -> list[dict[str, Any]]:
    return db_execute("SELECT * FROM products ORDER BY sort_order ASC, title ASC", fetchall=True)


def get_product(product_id: int) -> dict[str, Any] | None:
    return db_execute("SELECT * FROM products WHERE id=?", (product_id,), fetchone=True)


def has_sort_conflict(
    *, parent_id: int | None, is_category: bool, sort_order: int, exclude_id: int | None = None
) -> bool:
    query = """
        SELECT 1 FROM products
        WHERE (parent_id IS ? OR parent_id=?)
          AND is_category=?
          AND sort_order=?
    """
    params: list[Any] = [parent_id, parent_id, 1 if is_category else 0, sort_order]
    if exclude_id:
        query += " AND id != ?"
        params.append(exclude_id)
    row = db_execute(query + " LIMIT 1", tuple(params), fetchone=True)
    return bool(row)


def create_product(
    title: str,
    *,
    is_category: bool = False,
    parent_id: int | None = None,
    price: int = 0,
    available: bool = True,
    description: str = "",
    request_only: bool = False,
    account_enabled: bool = False,
    self_available: bool = False,
    self_price: int = 0,
    self_require_username: bool = False,
    self_require_password: bool = False,
    pre_available: bool = False,
    pre_price: int = 0,
    require_username: bool = False,
    require_password: bool = False,
    allow_first_plan: bool = False,
    cashback_enabled: bool = False,
    cashback_percent: int = 0,
    sort_order: int = 0,
) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    return db_execute(
        """
        INSERT INTO products(
            parent_id, title, description, price, available, is_category, request_only, account_enabled,
            self_available, self_price, self_require_username, self_require_password,
            pre_available, pre_price, require_username, require_password,
            allow_first_plan, cashback_enabled, cashback_percent,
            sort_order, created_at, updated_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            parent_id,
            title.strip(),
            description or "",
            max(int(price), 0),
            1 if available else 0,
            1 if is_category else 0,
            1 if request_only else 0,
            1 if account_enabled else 0,
            1 if self_available else 0,
            max(int(self_price), 0),
            1 if self_require_username else 0,
            1 if self_require_password else 0,
            1 if pre_available else 0,
            max(int(pre_price), 0),
            1 if require_username else 0,
            1 if require_password else 0,
            1 if allow_first_plan else 0,
            1 if cashback_enabled else 0,
            max(int(cashback_percent or 0), 0),
            sort_order,
            now,
            now,
        ),
        return_lastrowid=True,
    )


def update_product(
    product_id: int,
    *,
    title: str | None = None,
    is_category: bool | None = None,
    parent_id: int | None = None,
    price: int | None = None,
    available: bool | None = None,
    description: str | None = None,
    request_only: bool | None = None,
    account_enabled: bool | None = None,
    self_available: bool | None = None,
    self_price: int | None = None,
    self_require_username: bool | None = None,
    self_require_password: bool | None = None,
    pre_available: bool | None = None,
    pre_price: int | None = None,
    require_username: bool | None = None,
    require_password: bool | None = None,
    allow_first_plan: bool | None = None,
    cashback_enabled: bool | None = None,
    cashback_percent: int | None = None,
    sort_order: int | None = None,
) -> bool:
    current = get_product(product_id)
    if not current:
        return False
    fields = {
        "title": title if title is not None else current.get("title"),
        "description": description if description is not None else current.get("description"),
        "price": max(int(price), 0) if price is not None else int(current.get("price") or 0),
        "available": 1 if (available if available is not None else current.get("available")) else 0,
        "is_category": 1 if (is_category if is_category is not None else current.get("is_category")) else 0,
        "request_only": 1 if (request_only if request_only is not None else current.get("request_only")) else 0,
        "account_enabled": 1 if (account_enabled if account_enabled is not None else current.get("account_enabled")) else 0,
        "self_available": 1 if (self_available if self_available is not None else current.get("self_available")) else 0,
        "self_price": max(int(self_price), 0) if self_price is not None else int(current.get("self_price") or 0),
        
        "self_require_username": 1 if (self_require_username if self_require_username is not None else current.get("self_require_username")) else 0,
        "self_require_password": 1 if (self_require_password if self_require_password is not None else current.get("self_require_password")) else 0,
        
        "pre_available": 1 if (pre_available if pre_available is not None else current.get("pre_available")) else 0,
        "pre_price": max(int(pre_price), 0) if pre_price is not None else int(current.get("pre_price") or 0),
        "require_username": 1 if (require_username if require_username is not None else current.get("require_username")) else 0,
        "require_password": 1 if (require_password if require_password is not None else current.get("require_password")) else 0,
        "allow_first_plan": 1 if (allow_first_plan if allow_first_plan is not None else current.get("allow_first_plan")) else 0,
        "cashback_enabled": 1 if (cashback_enabled if cashback_enabled is not None else current.get("cashback_enabled")) else 0,
        "cashback_percent": max(int(cashback_percent), 0)
        if cashback_percent is not None
        else int(current.get("cashback_percent") or 0),
        "sort_order": sort_order if sort_order is not None else int(current.get("sort_order") or 0),
        "parent_id": parent_id if parent_id is not None else current.get("parent_id"),
    }
    db_execute(
        """
        UPDATE products
        SET title=?, description=?, price=?, available=?, is_category=?, request_only=?, account_enabled=?,
            self_available=?, self_price=?, self_require_username=?, self_require_password=?, 
            pre_available=?, pre_price=?, require_username=?, require_password=?,
            allow_first_plan=?, cashback_enabled=?, cashback_percent=?,
            sort_order=?, parent_id=?, updated_at=?
        WHERE id=?
        """,
        (
            fields["title"],
            fields["description"],
            fields["price"],
            fields["available"],
            fields["is_category"],
            fields["request_only"],
            fields["account_enabled"],
            fields["self_available"],
            fields["self_price"],
            fields["self_require_username"],
            fields["self_require_password"],
            fields["pre_available"],
            fields["pre_price"],
            fields["require_username"],
            fields["require_password"],
            fields["allow_first_plan"],
            fields["cashback_enabled"],
            fields["cashback_percent"],
            fields["sort_order"],
            fields["parent_id"],
            datetime.now().isoformat(timespec="seconds"),
            product_id,
        ),
    )
    return True


def delete_product(product_id: int) -> None:
    db_execute("DELETE FROM products WHERE id=?", (product_id,))
# در انتهای فایل app/db.py این تابع را اضافه کنید

def remove_order_discount(order_id: int) -> bool:
    """Removes discount from an order and cleans up redemption records."""
    order = get_order(order_id)
    if not order:
        return False
    
    discount_id = order.get("discount_id")
    if not discount_id:
        return True  # قبلاً تخفیف نداشته

    # 1. حذف رکورد استفاده از جدول discount_redemptions
    db_execute("DELETE FROM discount_redemptions WHERE order_id=?", (order_id,))

    # 2. کاهش شمارنده استفاده در جدول discounts
    db_execute("UPDATE discounts SET used_count = MAX(0, used_count - 1) WHERE id=?", (discount_id,))

    # 3. صفر کردن فیلدهای تخفیف در جدول orders
    db_execute(
        """
        UPDATE orders 
        SET discount_id=NULL, discount_code='', discount_amount=0, updated_at=?
        WHERE id=?
        """,
        (datetime.now().isoformat(timespec="seconds"), order_id)
    )
    return True

# در فایل app/db.py اضافه شود

def delete_service_message(message_id: int) -> None:
    # حذف پیام اصلی
    db_execute("DELETE FROM service_messages WHERE id=?", (message_id,))
    # حذف پاسخ‌های مرتبط با آن پیام (برای تمیز ماندن دیتابیس)
    db_execute("DELETE FROM service_message_replies WHERE service_message_id=?", (message_id,))