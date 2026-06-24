"""
DB_Manager テスト: Update_Data / Delete_Data / 条件付きSelect_Data / サブクエリ / Select_Join
  エリア1: Update_Data・Delete_Data(変更点 before/after・削除行・全削除防止ガード)
  エリア2: 条件付き Select_Data(where / order_by / limit / offset / 複合)
  エリア3: サブクエリ(他テーブルを条件に)と Select_Join(INNER / LEFT)

各エリアは自分用のテーブルを作るので順序に依存しない(差分・往復で検証)。
方式: 実MySQLサーバーに接続。接続情報は p/key.txt(3行: host / user / passwd)から読む。
実行: python3 test_crud_and_queries.py
"""
import os
import sys
import mysql.connector as sqlconn
from Operation_Database import DB_Manager

KEY_PATH = os.path.join(os.path.dirname(__file__), "p", "key.txt")
TEST_DB  = "dbmanager_crud_test_db"

_passed = 0
_failed = 0
def check(label, cond, detail=""):
    global _passed, _failed
    mark = "OK " if cond else "NG "
    if cond: _passed += 1
    else:    _failed += 1
    print(f"[{mark}] {label}" + (f"  -> {detail}" if (detail and not cond) else ""))


def get_credentials():
    try:
        with open(KEY_PATH, encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]
    except OSError:
        print(f"接続情報ファイルを読めません: {KEY_PATH}")
        sys.exit(2)
    host   = lines[0].strip() if len(lines) >= 1 else ""
    user   = lines[1].strip() if len(lines) >= 2 else ""
    passwd = lines[2].strip() if len(lines) >= 3 else ""
    if not host or not user:
        print(f"接続情報の形式が不正です(1行目host/2行目userが必要): {KEY_PATH}")
        sys.exit(2)
    return [host, user, passwd]


def drop_test_db_raw(creds):
    conn = sqlconn.connect(host=creds[0], user=creds[1], passwd=creds[2])
    cur  = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    conn.commit()
    cur.close()
    conn.close()


def make_columns(*specs):
    # ("name","VARCHAR(50)") のようなタプルから列定義dictを作る簡易ヘルパー
    cols = [{"Column_Name": "id", "Data_Type": "INT", "Extra": "AUTO_INCREMENT"}]
    for name, dtype in specs:
        cols.append({"Column_Name": name, "Data_Type": dtype})
    return cols


# ========================= エリア1: Update_Data / Delete_Data =========================
def area1_update_delete(db):
    print("\n########## エリア1: Update_Data と Delete_Data ##########")
    db.Create_Table("members", make_columns(("name", "VARCHAR(50)"),
                                             ("age", "INT"),
                                             ("status", "VARCHAR(20)")), primary_key="id")
    for n, a, s in [("Alice", 30, "active"), ("Bob", 25, "inactive"),
                    ("Carol", 40, "active"), ("Dave", 20, "active")]:
        db.Insert_Data([None, n, a, s])

    # [1] Update_Data: Alice の status を active -> inactive(before/after を確認)
    print("\n [1] Update_Data: Alice の status を inactive に")
    up = db.Update_Data(("status = %s", ["inactive"]), {"where": ("name = %s", ["Alice"])})
    print(f"     -> success={up['success']}, data={up['data']}")
    check("Update success", up["success"] is True, up["error"])
    if up["success"]:
        bef = up["data"]["before"]
        aft = up["data"]["after"]
        check("before の status が active",  bool(bef) and bef[0]["status"] == "active",  str(bef))
        check("after の status が inactive", bool(aft) and aft[0]["status"] == "inactive", str(aft))
    chk = db.Select_Data("*", {"where": ("name = %s", ["Alice"])})
    check("DB上もinactiveになっている",
          bool(chk["data"]) and chk["data"][0]["status"] == "inactive", str(chk["data"]))

    # [2] Update_Data ガード: 条件なしは _fail(全行更新の防止)
    print("\n [2] Update_Data ガード(条件なし)")
    g = db.Update_Data(("status = %s", ["x"]), {})
    print(f"     -> success={g['success']}, error={g['error']}")
    check("条件なしUpdateは失敗", g["success"] is False)
    check("error が入っている", bool(g["error"]))

    # [3] Delete_Data: Bob を削除(削除行・件数減を確認)
    print("\n [3] Delete_Data: Bob を削除")
    n_before = len(db.Select_Data("*")["data"])
    dl = db.Delete_Data({"where": ("name = %s", ["Bob"])})
    print(f"     -> success={dl['success']}, data(削除行)={dl['data']}")
    check("Delete success", dl["success"] is True, dl["error"])
    check("削除行が Bob", bool(dl["data"]) and dl["data"][0]["name"] == "Bob", str(dl["data"]))
    after = db.Select_Data("*")
    names = [r["name"] for r in after["data"]]
    check("Bob が消えた", "Bob" not in names, str(names))
    check("件数が1減った", len(after["data"]) == n_before - 1, f"{n_before} -> {len(after['data'])}")

    # [4] Delete_Data ガード: 条件なしは _fail(全削除の防止)
    print("\n [4] Delete_Data ガード(条件なし=全削除防止)")
    g2 = db.Delete_Data({})
    print(f"     -> success={g2['success']}, error={g2['error']}")
    check("条件なしDeleteは失敗", g2["success"] is False)
    check("error が入っている", bool(g2["error"]))
    check("ガードで件数が変わらない", len(db.Select_Data("*")["data"]) == n_before - 1)


# ========================= エリア2: 条件付き Select_Data =========================
def area2_conditional_select(db):
    print("\n########## エリア2: 条件付き Select_Data ##########")
    db.Create_Table("query_tbl", make_columns(("name", "VARCHAR(50)"), ("age", "INT")),
                    primary_key="id")
    for n, a in [("A", 30), ("B", 25), ("C", 40), ("D", 20), ("E", 35)]:
        db.Insert_Data([None, n, a])

    print("\n [1] WHERE age >= 30")
    r = db.Select_Data("*", {"where": ("age >= %s", [30])})
    ages = sorted(row["age"] for row in r["data"])
    print(f"     -> ages={ages}")
    check("WHERE: ages == [30, 35, 40]", ages == [30, 35, 40], str(ages))

    print("\n [2] ORDER BY age DESC")
    r = db.Select_Data("*", {"order_by": "age DESC"})
    ages = [row["age"] for row in r["data"]]
    print(f"     -> ages={ages}")
    check("ORDER BY DESC: [40, 35, 30, 25, 20]", ages == [40, 35, 30, 25, 20], str(ages))

    print("\n [3] ORDER BY age DESC LIMIT 2")
    r = db.Select_Data("*", {"order_by": "age DESC", "limit": 2})
    ages = [row["age"] for row in r["data"]]
    print(f"     -> ages={ages}")
    check("LIMIT 2: [40, 35]", ages == [40, 35], str(ages))

    print("\n [4] ORDER BY age DESC LIMIT 2 OFFSET 1")
    r = db.Select_Data("*", {"order_by": "age DESC", "limit": 2, "offset": 1})
    ages = [row["age"] for row in r["data"]]
    print(f"     -> ages={ages}")
    check("LIMIT/OFFSET: [35, 30]", ages == [35, 30], str(ages))

    print("\n [5] WHERE age >= 25 ORDER BY age ASC LIMIT 2(複合)")
    r = db.Select_Data("*", {"where": ("age >= %s", [25]), "order_by": "age ASC", "limit": 2})
    ages = [row["age"] for row in r["data"]]
    print(f"     -> ages={ages}")
    check("複合: [25, 30]", ages == [25, 30], str(ages))


# ========================= エリア3: サブクエリ / Select_Join =========================
def area3_subquery_join(db):
    print("\n########## エリア3: サブクエリ と Select_Join ##########")
    # customers(Dave は注文なし)
    db.Create_Table("customers", make_columns(("name", "VARCHAR(50)"), ("city", "VARCHAR(50)")),
                    primary_key="id")
    cust = {}
    for n, c in [("Alice", "Tokyo"), ("Bob", "Osaka"), ("Carol", "Tokyo"), ("Dave", "Nagoya")]:
        cust[n] = db.Insert_Data([None, n, c])["lastrowid"]
    # orders(Alice×2, Bob×1, Carol×1。Dave は0件)
    db.Create_Table("orders", make_columns(("customer_id", "INT"), ("total", "INT")),
                    primary_key="id")
    for cname, total in [("Alice", 100), ("Alice", 200), ("Bob", 300), ("Carol", 150)]:
        db.Insert_Data([None, cust[cname], total])

    # [1] サブクエリ: Tokyo の客の注文だけ取得
    print("\n [1] サブクエリ: customer_id IN (SELECT id FROM customers WHERE city='Tokyo')")
    db.Select_Table("orders")                       # Select_Data の対象を orders に
    r = db.Select_Data("*", {
        "where": ("customer_id IN {tokyo}", []),
        "subqueries": {"tokyo": {"select": "id", "from": "customers",
                                 "where": ("city = %s", ["Tokyo"])}},
    })
    print(f"     -> data={r['data']}")
    check("サブクエリ success", r["success"] is True, r["error"])
    totals = sorted(row["total"] for row in (r["data"] or []))
    # Tokyo客 = Alice(100,200), Carol(150) → [100,150,200]
    check("Tokyoの注文 totals == [100, 150, 200]", totals == [100, 150, 200], str(totals))

    # [2] INNER JOIN: 注文 + 客名(対応する行だけ)
    print("\n [2] INNER JOIN: orders と customers")
    r = db.Select_Join("orders.id, orders.total, customers.name", {
        "from": "orders",
        "joins": [{"type": "INNER", "table": "customers",
                   "on": "orders.customer_id = customers.id"}],
        "order_by": "orders.total ASC",
    })
    print(f"     -> data={r['data']}")
    check("INNER JOIN success", r["success"] is True, r["error"])
    check("4件(全注文に客が対応)", len(r["data"] or []) == 4, str(len(r["data"] or [])))
    row100 = [x for x in (r["data"] or []) if x["total"] == 100]
    check("total=100 の客名は Alice", bool(row100) and row100[0]["name"] == "Alice", str(row100))
    row300 = [x for x in (r["data"] or []) if x["total"] == 300]
    check("total=300 の客名は Bob", bool(row300) and row300[0]["name"] == "Bob", str(row300))

    # [3] LEFT JOIN: 全客 + 注文(注文なしの Dave も NULL で残る)
    print("\n [3] LEFT JOIN: customers と orders(注文なしの客も残る)")
    r = db.Select_Join("customers.name, orders.total", {
        "from": "customers",
        "joins": [{"type": "LEFT", "table": "orders",
                   "on": "customers.id = orders.customer_id"}],
    })
    print(f"     -> data={r['data']}")
    check("LEFT JOIN success", r["success"] is True, r["error"])
    # Alice2 + Bob1 + Carol1 + Dave1(NULL) = 5行
    check("5件(Daveのnull行を含む)", len(r["data"] or []) == 5, str(len(r["data"] or [])))
    dave = [x for x in (r["data"] or []) if x["name"] == "Dave"]
    check("Dave の total は NULL", bool(dave) and dave[0]["total"] is None, str(dave))


def setup(db):
    print("---- setup: テスト用DBを作成して選択 ----")
    r = db.Create_DataBase(TEST_DB)
    check("setup: Create_DataBase", r["success"], r["error"])
    r = db.Select_DataBase(TEST_DB)
    check("setup: Select_DataBase", r["success"], r["error"])
    return r["success"]


def main():
    creds = get_credentials()
    print(f"接続先host: {creds[0]} / user: {creds[1]} / passwd設定: {bool(creds[2])}")
    drop_test_db_raw(creds)          # クリーンな状態から開始

    db = None
    try:
        db = DB_Manager(creds)
        if db.connection is None or not db.connection.is_connected():
            print("接続できないため中止します。")
            return
        if not setup(db):
            print("setup に失敗したため中止します。")
            return
        area1_update_delete(db)
        area2_conditional_select(db)
        area3_subquery_join(db)
    finally:
        if db is not None:
            db.close()
        drop_test_db_raw(creds)      # 後始末: テストDBを削除

    print(f"\nRESULT: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()