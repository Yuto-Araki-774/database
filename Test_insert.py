"""
DB_Manager テスト: 条件なし Select_Data と Insert_Data
  方針: 挿入の前後で件数・中身の差分を見る(0件 → 1件 → 2件)。
  ポイント: Insert_Data は self.columns の全列ぶんの値を順番どおりに要求する。
            id は AUTO_INCREMENT なので None を渡して自動採番させる。

方式: 実MySQLサーバーに接続。接続情報は p/key.txt(3行: host / user / passwd)から読む。
実行: python3 test_insert_select.py
"""
import os
import sys
import mysql.connector as sqlconn
from Operation_Database import DB_Manager

KEY_PATH   = os.path.join(os.path.dirname(__file__), "p", "key.txt")
TEST_DB    = "dbmanager_is_test_db"      # insert/select テスト専用。前後で必ず削除する
TEST_TABLE = "is_test_table"

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


def setup(db):
    # 前提: DB作成 → 選択 → テーブル作成(これで db.columns = ['id','name'])
    print("---- setup: DB/テーブルを用意 ----")
    r = db.Create_DataBase(TEST_DB)
    check("setup: Create_DataBase", r["success"], r["error"])
    r = db.Select_DataBase(TEST_DB)
    check("setup: Select_DataBase", r["success"], r["error"])
    columns = [
        {"Column_Name": "id",   "Data_Type": "INT", "Extra": "AUTO_INCREMENT"},
        {"Column_Name": "name", "Data_Type": "VARCHAR(50)"},
    ]
    r = db.Create_Table(TEST_TABLE, columns, primary_key="id")
    check("setup: Create_Table", r["success"], r["error"])
    check("setup: db.columns = ['id','name']", db.columns == ["id", "name"], str(db.columns))
    return r["success"]


# ============ Insert_Data と 条件なし Select_Data ============
def test_insert_and_select(db):
    print("\n========== Insert_Data と 条件なし Select_Data ==========")

    # 1) 初期状態: 条件なし Select_Data は 0 件
    print(" [1] 挿入前に条件なし Select_Data(空のはず)")
    r0 = db.Select_Data("*")                       # query_option 省略 = 条件なし(WHEREなし)
    print(f"     -> success={r0['success']}, data={r0['data']}")
    check("Select_Data success", r0["success"] is True, r0["error"])
    check("初期は0件", r0["data"] == [], str(r0["data"]))

    # 2) 1件挿入(id は None で自動採番)
    print("\n [2] Insert_Data([None, 'Alice'])")
    i1 = db.Insert_Data([None, "Alice"])
    print(f"     -> success={i1['success']}, rowcount={i1['rowcount']}, "
          f"lastrowid={i1['lastrowid']}, data={i1['data']}")
    check("Insert success", i1["success"] is True, i1["error"])
    check("rowcount が 1", i1["rowcount"] == 1, str(i1["rowcount"]))
    check("lastrowid が採番された(正の整数)",
          isinstance(i1["lastrowid"], int) and i1["lastrowid"] > 0, str(i1["lastrowid"]))
    check("data は挿入した行(渡した値)",
          i1["data"] == [{"id": None, "name": "Alice"}], str(i1["data"]))

    # 3) 条件なし Select_Data で 1 件返り、中身が一致
    print("\n [3] 挿入後に条件なし Select_Data(1件のはず)")
    r1 = db.Select_Data("*")
    print(f"     -> data={r1['data']}")
    check("1件になった", len(r1["data"]) == 1, str(r1["data"]))
    if r1["data"]:
        check("name が Alice", r1["data"][0]["name"] == "Alice", str(r1["data"][0]))
        # 実際にDBへ入った id は自動採番値。Insert の lastrowid と一致するはず。
        check("id が採番値(Insertのlastrowidと一致)",
              r1["data"][0]["id"] == i1["lastrowid"],
              f'{r1["data"][0]["id"]} vs {i1["lastrowid"]}')

    # 4) もう1件挿入
    print("\n [4] Insert_Data([None, 'Bob'])")
    i2 = db.Insert_Data([None, "Bob"])
    print(f"     -> success={i2['success']}, lastrowid={i2['lastrowid']}")
    check("Insert success (2件目)", i2["success"] is True, i2["error"])

    # 5) 条件なし Select_Data で 2 件返る
    print("\n [5] 条件なし Select_Data(2件のはず)")
    r2 = db.Select_Data("*")
    print(f"     -> data={r2['data']}")
    check("2件になった", len(r2["data"]) == 2, str(r2["data"]))
    names = sorted(row["name"] for row in r2["data"])
    check("名前が Alice, Bob", names == ["Alice", "Bob"], str(names))


# ============ Insert_Data のガード(列数不一致) ============
def test_insert_length_guard(db):
    print("\n========== Insert_Data のガード(列数不一致) ==========")
    # self.columns は2列(id,name)。値を1個だけ渡すと _fail を返すはず。
    print(" Insert_Data(['OnlyOne']) を実行(列数2に対し値1個)")
    bad = db.Insert_Data(["OnlyOne"])
    print(f"     -> success={bad['success']}, error={bad['error']}")
    check("列数不一致は失敗", bad["success"] is False)
    check("error が入っている", bool(bad["error"]), "errorが空")
    # ガードで弾かれるので件数は2のまま(挿入されていない)
    r = db.Select_Data("*")
    check("件数は2のまま(挿入されていない)", len(r["data"]) == 2, str(r["data"]))


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
        test_insert_and_select(db)
        test_insert_length_guard(db)
    finally:
        if db is not None:
            db.close()
        drop_test_db_raw(creds)      # 後始末: テストDBを削除

    print(f"\nRESULT: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()