from __future__ import annotations

from typing import Iterable

from .catalog import get_variant, list_admin_rows
from .db import (
    create_product,
    delete_product,
    get_product,
    list_all_products,
    list_products,
    update_product,
)


def _normalize_item(raw: dict) -> dict:
    item = dict(raw)
    item["available"] = bool(item.get("available"))
    item["is_category"] = bool(item.get("is_category"))
    item["request_only"] = bool(item.get("request_only"))
    item["account_enabled"] = bool(item.get("account_enabled"))
    item["self_available"] = bool(item.get("self_available"))
    item["pre_available"] = bool(item.get("pre_available"))
    item["require_username"] = bool(item.get("require_username"))
    item["require_password"] = bool(item.get("require_password"))
    
    # --- تغییرات جدید: خواندن تنظیمات اختصاصی اکانت شخصی ---
    item["self_require_username"] = bool(item.get("self_require_username"))
    item["self_require_password"] = bool(item.get("self_require_password"))
    # -------------------------------------------------------

    item["allow_first_plan"] = bool(item.get("allow_first_plan"))
    item["cashback_enabled"] = bool(item.get("cashback_enabled"))
    item["price"] = int(item.get("price") or 0)
    item["self_price"] = int(item.get("self_price") or 0)
    item["pre_price"] = int(item.get("pre_price") or 0)
    item["cashback_percent"] = int(item.get("cashback_percent") or 0)
    if item["self_available"] or item["pre_available"]:
        item["account_enabled"] = True
    return item


def seed_default_catalog() -> None:
    """Populate the catalog based on legacy variants if it is empty."""

    if list_all_products():
        return

    # Create top-level groups based on legacy admin rows
    group_ids: dict[str, int] = {}
    for idx, row in enumerate(list_admin_rows(), start=1):
        title = str(row.get("title") or row.get("code") or f"دسته {idx}")
        group_ids[row["code"]] = create_product(title, is_category=True, sort_order=idx)

        for position, variant_meta in enumerate(row.get("variants", []), start=1):
            variant = get_variant(variant_meta["code"])
            create_product(
                variant["display_name"],
                is_category=False,
                parent_id=group_ids[row["code"]],
                price=int(variant.get("amount") or 0),
                available=bool(variant.get("available")),
                description="",
                sort_order=position,
            )


def get_admin_tree() -> list[dict]:
    """Return a flattened tree suitable for admin rendering."""

    all_items = [_normalize_item(item) for item in list_all_products()]

    def _children(parent: int | None) -> Iterable[dict]:
        return [
            item
            for item in all_items
            if (item.get("parent_id") or 0) == (parent or 0)
        ]

    def _walk(parent: int | None, depth: int, trail: list[str]):
        for child in sorted(_children(parent), key=lambda x: (x.get("sort_order") or 0, x.get("title") or "")):
            path = trail + [child.get("title") or ""]
            normalized = {**child, "depth": depth, "path_display": " / ".join(path)}
            yield normalized
            yield from _walk(child.get("id"), depth + 1, path)

    return list(_walk(None, 0, []))


def list_public_children(parent_id: int | None = None) -> list[dict]:
    """List visible children for the given parent."""

    children = [_normalize_item(item) for item in list_products(parent_id)]
    visible: list[dict] = []

    for child in sorted(children, key=lambda x: (x.get("sort_order") or 0, x.get("title") or "")):
        if child["is_category"]:
            grand_children = list_public_children(child.get("id"))
            if grand_children:
                child = {**child, "has_children": True}
                visible.append(child)
        else:
            option_available = child["available"]
            if child.get("account_enabled"):
                option_available = child.get("self_available") or child.get("pre_available")
            if child.get("request_only"):
                option_available = True
            if option_available:
                visible.append(child)
    return visible


def find_public_product(product_id: int) -> dict | None:
    item = get_product(product_id)
    if not item:
        return None
    normalized = _normalize_item(item)
    if normalized["is_category"]:
        return normalized
    option_available = normalized.get("available")
    if normalized.get("account_enabled"):
        option_available = normalized.get("self_available") or normalized.get("pre_available")
    if normalized.get("request_only"):
        option_available = True
    if not option_available:
        return None
    return normalized