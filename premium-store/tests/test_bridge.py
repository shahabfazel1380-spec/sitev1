import sqlite3
from backend.bridge import export_to_bot

def test_bot_sync_idempotent_revisioned_and_non_destructive(tmp_path):
    path=tmp_path/'bot.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE products (id INTEGER PRIMARY KEY, title TEXT, description TEXT, price INTEGER, available INTEGER, is_category INTEGER, parent_id INTEGER, sort_order INTEGER)')
        db.execute("INSERT INTO products VALUES (1,'existing','untouched',123,1,0,NULL,0)")
    product={'id':1,'revision':1,'title':'وب جدید','description':'توضیح','price':150000,'available':True,'published':True,'archived':False,'sort_order':1}
    bot_id=export_to_bot(path,product)
    assert bot_id!=1
    assert export_to_bot(path,product)==bot_id
    product.update(revision=2,price=160000)
    export_to_bot(path,product)
    product.update(revision=1,price=1000)
    export_to_bot(path,product)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM products').fetchone()[0]==2
        assert db.execute('SELECT price FROM products WHERE id=1').fetchone()[0]==123
        assert db.execute('SELECT price FROM products WHERE id=?',(bot_id,)).fetchone()[0]==160000
    product.update(revision=3,archived=True)
    export_to_bot(path,product)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT available FROM products WHERE id=?',(bot_id,)).fetchone()[0]==0
