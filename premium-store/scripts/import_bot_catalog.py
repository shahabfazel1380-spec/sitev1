"""Export public products from a read-only copy of the legacy bot database.

Does not access users/orders/credentials or write to the bot database.
Account variants and request-only products require explicit business mapping.
"""
import argparse
import json
import sqlite3
from pathlib import Path

def export_catalog(database: Path):
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(products)')}
        required = {'id', 'title', 'description', 'price', 'available', 'is_category'}
        if not required <= columns:
            raise ValueError('Unsupported bot schema; required public product columns are missing.')
        allowed = sorted(required | ({'request_only','account_enabled','self_available','pre_available','parent_id'} & columns))
        # Identifiers come only from the fixed allowlist above, never user input.
        rows = connection.execute('SELECT ' + ','.join(allowed) + ' FROM products').fetchall()
        products, skipped = [], []
        for row in rows:
            p = dict(row)
            if p['is_category']:
                continue
            if p.get('request_only') or p.get('account_enabled') or p.get('self_available') or p.get('pre_available') or int(p.get('price') or 0) <= 0:
                skipped.append({'id':p['id'], 'reason':'Requires variant, credential, custom-price or request-only mapping'})
                continue
            products.append({'id':p['id'], 'title':p['title'], 'brand':'', 'description':p['description'] or 'جزئیات این اشتراک را پیش از خرید از پشتیبانی بپرسید.', 'category':'tools', 'icon':'gpt', 'features':['برگرفته از کاتالوگ ربات'], 'price':int(p['price']), 'original_price':int(p['price']), 'available':bool(p['available']), 'badge':'', 'period':'طبق مشخصات محصول'})
        return products, skipped
    finally:
        connection.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('catalog.imported.json'))
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new filename to avoid overwriting reviewed prices.')
    if not args.database.is_file():
        parser.error('Database file does not exist.')
    products, skipped = export_catalog(args.database)
    args.output.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'exported':len(products),'skipped':skipped,'next_step':'Review currency (toman), period, category and stock before setting CATALOG_PATH.'}, ensure_ascii=False))
