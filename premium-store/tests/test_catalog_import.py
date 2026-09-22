import importlib.util
import sqlite3
from pathlib import Path

spec = importlib.util.spec_from_file_location('import_bot_catalog', Path(__file__).resolve().parents[1] / 'scripts/import_bot_catalog.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_import_excludes_sensitive_and_complex_products(tmp_path):
    path = tmp_path / 'bot.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE products (id INTEGER, title TEXT, description TEXT, price INTEGER, available INTEGER, is_category INTEGER, account_enabled INTEGER, request_only INTEGER, customer_password TEXT)')
        db.executemany('INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?)', [
            (1,'plain','description',1200,1,0,0,0,'must-not-export'),
            (2,'variant','description',1500,1,0,1,0,'must-not-export'),
            (3,'category','description',0,1,1,0,0,'must-not-export'),
            (4,'quote','description',0,1,0,0,1,'must-not-export'),
        ])
    before = path.read_bytes()
    products, skipped = module.export_catalog(path)
    assert len(products) == 1 and products[0]['price'] == 1200
    assert products[0]['id'] == 1
    assert 'password' not in str(products) and 'must-not-export' not in str(products)
    assert {p['id'] for p in skipped} == {2,4}
    assert path.read_bytes() == before
