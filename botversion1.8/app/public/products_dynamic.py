from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from . import router
from .channel_gate import ensure_member_for_message
from .helpers import _notify_admins
from ..config import CURRENCY
from ..db import (
    create_order,
    ensure_user,
    get_user,
    set_order_customer_message,
    set_order_payment_type,
    set_order_status,
)
from ..keyboards import (
    REPLY_BTN_PRODUCTS,
    ik_cart_actions,
    ik_dynamic_products,
    ik_product_actions,
    reply_main,
)
from ..products import find_public_product, list_public_children
from ..states import CatalogStates
from ..utils import mention


def _format_price(amount: int) -> str:
    if amount <= 0:
        return "قیمت تنظیم نشده"
    return f"{amount:,} {CURRENCY}".replace(",", "،")


def _resolve_price(product: dict, mode: str | None) -> tuple[int, bool]:
    if product.get("account_enabled"):
        if mode == "self":
            return int(product.get("self_price") or product.get("price") or 0), bool(
                product.get("self_available")
            )
        if mode == "pre":
            return int(product.get("pre_price") or product.get("price") or 0), bool(
                product.get("pre_available")
            )
    return int(product.get("price") or 0), bool(product.get("available"))


async def _show_root(message: Message) -> None:
    items = list_public_children()
    if not items:
        await message.answer("هیچ محصول فعالی ثبت نشده است.", reply_markup=reply_main())
        return
    await message.answer("به فروشگاه خوش آمدید. دسته مورد نظر را انتخاب کنید:", reply_markup=ik_dynamic_products(items))


async def _create_order_and_confirm(
    message: Message,
    tg_user: User,
    *,
    product: dict,
    product_id: int,
    mode: str,
    price: int,
    username: str | None,
    password: str | None,
) -> None:
    # Use tg_user explicitly instead of message.from_user to ensure we get the buyer, not the bot
    ensure_user(tg_user.id, tg_user.username, tg_user.first_name or "")
    user = get_user(tg_user.id)
    
    # Determine which requirement flags to store in order based on mode
    req_user = False
    req_pass = False
    if mode == "MY_ACCOUNT":
        req_user = bool(product.get("self_require_username"))
        req_pass = bool(product.get("self_require_password"))
    elif mode == "PREBUILT":
        req_user = False
        req_pass = False
    else:
        req_user = bool(product.get("require_username"))
        req_pass = bool(product.get("require_password"))

    order_id = create_order(
        user=user,
        title=product.get("title") or f"محصول #{product_id}",
        amount_total=price,
        currency=CURRENCY,
        service_category="CATALOG",
        service_code=f"product:{product_id}",
        account_mode=mode,
        customer_email=None,
        notes=product.get("description") or "",
        require_username=req_user,
        require_password=req_pass,
        customer_username=username,
        customer_password=password,
        allow_first_plan=bool(product.get("allow_first_plan")),
        cashback_percent=(product.get("cashback_percent") if product.get("cashback_enabled") else 0) or 0,
        allow_free=price <= 0,
    )
    if not order_id:
        await message.answer(
            "ثبت سفارش با مشکل مواجه شد. لطفاً دوباره تلاش کنید یا به پشتیبانی اطلاع دهید.",
            reply_markup=reply_main(),
        )
        return
    
    await message.answer(
        f"✅ سفارش #{order_id} برای «{product.get('title')}» ثبت شد و به سبد خرید اضافه شد. برای ادامه و پرداخت به سبد خرید مراجعه کنید.",
        reply_markup=reply_main(),
    )


async def _begin_purchase(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    product: dict,
    product_id: int,
    mode: str | None,
):
    if product.get("request_only"):
        await callback.answer("این مورد فقط به صورت درخواست ثبت می‌شود.", show_alert=True)
        return

    if product.get("account_enabled") and mode not in {"self", "pre"}:
        await callback.answer("لطفاً نوع اکانت را انتخاب کنید.", show_alert=True)
        return

    price, available = _resolve_price(product, mode)
    if not available:
        await callback.answer("این گزینه فعلاً موجود نیست.", show_alert=True)
        return
    if price <= 0:
        await callback.message.answer("قیمت این سرویس صفر است و به‌صورت رایگان ثبت می‌شود.")

    # --- اصلاح شده: تعیین نیاز به یوزر/پسورد بر اساس مود ---
    require_username = False
    require_password = False

    if product.get("account_enabled"):
        if mode == "self":
            # در حالت اکانت خودم، از فیلدهای جدید استفاده کن
            require_username = bool(product.get("self_require_username"))
            require_password = bool(product.get("self_require_password"))
        elif mode == "pre":
            # در حالت اکانت آماده، نیازی به یوزر و پسورد نیست
            require_username = False
            require_password = False
    else:
        # حالت عادی (بدون اکانت مود)
        require_username = bool(product.get("require_username"))
        require_password = bool(product.get("require_password"))
    # -----------------------------------------------------

    await state.clear()
    account_mode = ""
    if product.get("account_enabled"):
        account_mode = "MY_ACCOUNT" if mode == "self" else "PREBUILT"

    if require_username:
        await state.update_data(
            pending_purchase=dict(
                product_id=product_id,
                mode=account_mode,
                price=price,
                require_password=require_password,
                product_title=product.get("title"),
                description=product.get("description") or "",
                # Store flags for checking later
                _req_user=True,
                _req_pass=require_password
            )
        )
        await state.set_state(CatalogStates.wait_username)
        await callback.message.answer("لطفاً نام کاربری/یوزر/ایمیل مورد نظر را ارسال کنید:")
        await callback.answer()
        return

    if require_password:
        await state.update_data(
            pending_purchase=dict(
                product_id=product_id,
                mode=account_mode,
                price=price,
                username="",
                product_title=product.get("title"),
                description=product.get("description") or "",
                _req_user=False,
                _req_pass=True
            )
        )
        await state.set_state(CatalogStates.wait_password)
        await callback.message.answer("لطفاً پسورد مورد نیاز را ارسال کنید:")
        await callback.answer()
        return

    # Pass callback.from_user to correctly identify the buyer
    await _create_order_and_confirm(
        callback.message,
        tg_user=callback.from_user,
        product=product,
        product_id=product_id,
        mode=account_mode,
        price=price,
        username=None,
        password=None,
    )
    await callback.answer()


@router.message(F.text == REPLY_BTN_PRODUCTS)
async def on_reply_products(message: Message, state: FSMContext) -> None:
    if not await ensure_member_for_message(message):
        return
    await state.clear()
    await _show_root(message)


@router.callback_query(F.data == "prod:root")
async def cb_products_root(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("به فروشگاه خوش آمدید.")
    await callback.message.answer("منو:", reply_markup=ik_dynamic_products(list_public_children()))
    await callback.answer()


@router.callback_query(F.data.startswith("prod:open:"))
async def cb_open_category(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        target_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return

    parent_id = target_id or None
    items = list_public_children(parent_id)
    if not items:
        await callback.answer("موردی یافت نشد.", show_alert=True)
        return

    back_parent = None
    if parent_id:
        parent = find_public_product(parent_id)
        title = parent.get("title") if parent else "دسته"
        back_parent = parent.get("parent_id") if parent else None
    else:
        title = "منو اصلی محصولات"
    await callback.message.edit_text(title, reply_markup=ik_dynamic_products(items, parent_id=back_parent))
    await callback.answer()


@router.callback_query(F.data.startswith("prod:view:"))
async def cb_view_product(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        product_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return

    product = find_public_product(product_id)
    if not product or product.get("is_category"):
        await callback.answer("این گزینه در دسترس نیست.", show_alert=True)
        return
    await state.clear()
    description = (product.get("description") or "").strip()
    text = f"<b>{product.get('title')}</b>\n"
    if description:
        text += f"\n{description}\n"
    if product.get("account_enabled"):
        text += "\n💡 این خدمت دارای حالت اکانت است."
    elif product.get("request_only"):
        text += "\n📝 این خدمت به‌صورت ثبت درخواست انجام می‌شود."
    text += f"\n💰 قیمت: <b>{_format_price(product.get('price') or 0)}</b>"
    text += "\nبرای ادامه روی دکمهٔ زیر بزنید."
    await callback.message.edit_text(
        text, reply_markup=ik_product_actions(product, product.get("parent_id"))
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod:mode:"))
async def cb_choose_mode(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        _, _, mode, product_raw = callback.data.split(":", 3)
        product_id = int(product_raw)
    except (ValueError, IndexError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return

    product = find_public_product(product_id)
    if not product or product.get("is_category"):
        await callback.answer("این گزینه در دسترس نیست.", show_alert=True)
        return
    await _begin_purchase(callback, state, product=product, product_id=product_id, mode=mode)


@router.callback_query(F.data.startswith("prod:buy:"))
async def cb_buy_product(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        product_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return

    product = find_public_product(product_id)
    if not product or product.get("is_category"):
        await callback.answer("این مورد در دسترس نیست.", show_alert=True)
        return
    await _begin_purchase(callback, state, product=product, product_id=product_id, mode=None)


@router.callback_query(F.data.startswith("prod:req:"))
async def cb_request_product(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        product_id = int(callback.data.split(":")[2])
    except (IndexError, ValueError):
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return
    product = find_public_product(product_id)
    if not product or product.get("is_category"):
        await callback.answer("این مورد در دسترس نیست.", show_alert=True)
        return
    if not product.get("request_only"):
        await callback.answer("این مورد حالت درخواست ندارد.", show_alert=True)
        return

    await state.set_state(CatalogStates.wait_request)
    await state.update_data(product_id=product_id)
    await callback.message.answer("لطفاً توضیحات خود را درباره این خدمت ارسال کنید:")
    await callback.answer()


@router.message(CatalogStates.wait_request)
async def on_request_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = int(data.get("product_id") or 0)
    product = find_public_product(product_id)
    if not product:
        await message.answer("این درخواست دیگر در دسترس نیست.", reply_markup=reply_main())
        await state.clear()
        return

    ensure_user(message.from_user.id, message.from_user.username, message.from_user.first_name or "")
    user = get_user(message.from_user.id)
    order_id = create_order(
        user=user,
        title=product.get("title") or f"محصول #{product_id}",
        amount_total=0,
        currency=CURRENCY,
        service_category="CATALOG_REQUEST",
        service_code=f"request:{product_id}",
        account_mode="REQUEST",
        notes=product.get("description") or "",
        allow_free=True,
    )
    if not order_id:
        await message.answer("ثبت درخواست با مشکل مواجه شد. لطفاً دوباره تلاش کنید.", reply_markup=reply_main())
        await state.clear()
        return

    set_order_customer_message(order_id, message.text or "")
    set_order_payment_type(order_id, "REQUEST")
    set_order_status(order_id, "IN_PROGRESS")
    await _notify_admins(
        message.bot,
        "\n".join(
            [
                "📨 درخواست جدید ثبت شد.",
                f"کاربر: {mention(message.from_user)}",
                f"عنوان: {product.get('title')}",
                f"توضیحات کاربر: {message.text or '—'}",
            ]
        ),
    )
    await message.answer(
        f"✅ درخواست شما برای «{product.get('title')}» ثبت شد و توسط پشتیبانی بررسی می‌شود.",
        reply_markup=reply_main(),
    )
    await state.clear()


@router.message(CatalogStates.wait_username)
async def on_username(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    pending = data.get("pending_purchase") or {}
    product_id = int(pending.get("product_id") or 0)
    product = find_public_product(product_id)
    if not product:
        await message.answer("این محصول دیگر در دسترس نیست.", reply_markup=reply_main())
        await state.clear()
        return
    username = (message.text or "").strip()
    if not username:
        await message.answer("لطفاً یک یوزرنیم معتبر ارسال کنید.")
        return

    if pending.get("require_password"):
        pending["username"] = username
        await state.update_data(pending_purchase=pending)
        await state.set_state(CatalogStates.wait_password)
        await message.answer("لطفاً پسورد مورد نیاز را ارسال کنید:")
        return

    await _create_order_and_confirm(
        message,
        tg_user=message.from_user,
        product=product,
        product_id=product_id,
        mode=pending.get("mode") or "",
        price=int(pending.get("price") or 0),
        username=username,
        password=None,
    )
    await state.clear()


@router.message(CatalogStates.wait_password)
async def on_password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    pending = data.get("pending_purchase") or {}
    product_id = int(pending.get("product_id") or 0)
    product = find_public_product(product_id)
    if not product:
        await message.answer("این محصول دیگر در دسترس نیست.", reply_markup=reply_main())
        await state.clear()
        return
    password = (message.text or "").strip()
    username = (pending.get("username") or "").strip() or None

    await _create_order_and_confirm(
        message,
        tg_user=message.from_user,
        product=product,
        product_id=product_id,
        mode=pending.get("mode") or "",
        price=int(pending.get("price") or 0),
        username=username,
        password=password or None,
    )
    await state.clear()