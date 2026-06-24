"""
DB_Manager テスト: Insert_Many(複数行一括挿入)
  [1] 正常系: N行挿入 → 件数が N 増え、値が一致(差分方式)
  [2] 全行ロールバック: 主キー重複を含むバッチは1行も入らない(executemany + 失敗時ロールバック)
      重複時は errno=ER_DUP_ENTRY(1062)
  [3] ガード: 空リスト / 列数不一致 / 行がlistでない(いずれも _fail。DBは変更されない)

方式: 実MySQLサーバーに接続。接続情報は p/key.txt(3行: host / user / passwd)から読む。
注意: 全行ロールバックの確認は autocommit が無効(mysql.connector既定)である前提。
実行: python3 test_insert_many.py
"""
import os
import sys
import mysql.connector as sqlconn
from mysql.connector import errorcode
from Operation_Database import DB_Manager

KEY_PATH   = os.path.join(os.path.dirname(__file__), "p", "key.txt")
TEST_DB    = "dbmanager_many_test_db"
TEST_TABLE = "many_test_table"

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


def names_of(rows):
    return sorted(r["name"] for r in (rows or []))


def setup(db):
    print("---- setup: DB/テーブルを用意 ----")
    r = db.Create_DataBase(TEST_DB)
    check("setup: Create_DataBase", r["success"], r["error"])
    r = db.Select_DataBase(TEST_DB)
    check("setup: Select_DataBase", r["success"], r["error"])
    cols = [
        {"Column_Name": "id",   "Data_Type": "INT", "Extra": "AUTO_INCREMENT"},
        {"Column_Name": "name", "Data_Type": "VARCHAR(50)"},
    ]
    r = db.Create_Table(TEST_TABLE, cols, primary_key="id")
    check("setup: Create_Table", r["success"], r["error"])
    return r["success"]


# ===================== [1] 正常系: 複数行挿入 =====================
def test_insert_many_ok(db):
    print("\n========== [1] Insert_Many 正常系(3行) ==========")
    n_before = len(db.Select_Data("*")["data"])
    rows = [[None, "Alice"], [None, "Bob"], [None, "Carol"]]
    r = db.Insert_Many(rows)
    print(f"     -> success={r['success']}, rowcount={r['rowcount']}, message={r['message']}")
    print(f"        data={r['data']}")
    check("Insert_Many success", r["success"] is True, r["error"])
    check("rowcount が 3", r["rowcount"] == 3, str(r["rowcount"]))
    check("data は挿入した3行",
          r["data"] == [{"id": None, "name": "Alice"},
                        {"id": None, "name": "Bob"},
                        {"id": None, "name": "Carol"}], str(r["data"]))
    check("message が '3 rows inserted'", r["message"] == "3 rows inserted", r["message"])

    after = db.Select_Data("*")
    print(f"        挿入後の全行={after['data']}")
    check("件数が3増えた", len(after["data"]) == n_before + 3,
          f"{n_before} -> {len(after['data'])}")
    check("名前が Alice, Bob, Carol", names_of(after["data"]) == ["Alice", "Bob", "Carol"],
          str(names_of(after["data"])))


# ===================== [2] 全行ロールバック =====================
def test_insert_many_rollback(db):
    print("\n========== [2] 主キー重複を含むバッチは1行も入らない ==========")
    existing = db.Select_Data("*")["data"]
    n_before = len(existing)
    existing_id = existing[0]["id"]                 # 既存の主キー値(これと衝突させる)
    print(f"     既存件数={n_before}, 衝突に使う既存id={existing_id}")

    # 3行目で既存idと衝突 → バッチ全体が失敗 → Dave/Eve も入らない
    batch = [[None, "Dave"], [None, "Eve"], [existing_id, "Conflict"]]
    r = db.Insert_Many(batch)
    print(f"     -> success={r['success']}, errno={r['errno']}, error={r['error']}")
    check("重複バッチは失敗", r["success"] is False)
    check("errno が ER_DUP_ENTRY(1062)",
          r["errno"] == errorcode.ER_DUP_ENTRY,
          f"{r['errno']} (期待 {errorcode.ER_DUP_ENTRY})")

    after = db.Select_Data("*")
    print(f"        失敗後の全行={after['data']}")
    check("件数が変わっていない(全行ロールバック)", len(after["data"]) == n_before,
          f"{n_before} -> {len(after['data'])}")
    nm = names_of(after["data"])
    check("Dave が入っていない", "Dave" not in nm, str(nm))
    check("Eve が入っていない",  "Eve" not in nm, str(nm))


# ===================== [3] ガード =====================
def test_insert_many_guards(db):
    print("\n========== [3] Insert_Many のガード ==========")
    n_before = len(db.Select_Data("*")["data"])

    print(" [3-1] 空リスト")
    r = db.Insert_Many([])
    check("空リストは失敗", r["success"] is False, "")
    check("空リストは errno=None(事前条件)", r["errno"] is None, str(r["errno"]))

    print(" [3-2] 列数不一致の行が混ざる(2列に対し1個の行)")
    r = db.Insert_Many([[None, "X"], [None]])
    print(f"     -> success={r['success']}, error={r['error']}")
    check("列数不一致は失敗", r["success"] is False)

    print(" [3-3] 行が list/tuple でない(flatなlistを誤って渡す)")
    r = db.Insert_Many([None, "Alice"])
    print(f"     -> success={r['success']}, error={r['error']}")
    check("flatな行は失敗", r["success"] is False)

    after = db.Select_Data("*")
    check("ガードで件数が変わらない(1行も入らない)", len(after["data"]) == n_before,
          f"{n_before} -> {len(after['data'])}")


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
        test_insert_many_ok(db)
        test_insert_many_rollback(db)
        test_insert_many_guards(db)
    finally:
        if db is not None:
            db.close()
        drop_test_db_raw(creds)      # 後始末: テストDBを削除

    print(f"\nRESULT: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()