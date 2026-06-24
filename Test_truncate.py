"""
DB_Manager テスト: Truncate_Table(全行削除・構造は残す)
  [A] 全行削除: N行ある状態で Truncate → 0件。テーブル自体は残り、内部状態(columns等)も保持
  [B] 構造維持 + AUTO_INCREMENT リセット: truncate後に挿入できて、idが1から振り直される
      (DELETEなら続き番号になるところ。TRUNCATE特有の挙動)
  [C] 存在しないテーブルの Truncate は errno=ER_NO_SUCH_TABLE(1146)
  [D] ガード: 不正名は _fail(errno=None)

注意: Truncate は暗黙コミットされロールバックできない。確認はフロントが通す前提。
方式: 実MySQLサーバーに接続。接続情報は p/key.txt(3行: host / user / passwd)から読む。
実行: python3 test_truncate.py
"""
import os
import sys
import mysql.connector as sqlconn
from mysql.connector import errorcode
from Operation_Database import DB_Manager

KEY_PATH   = os.path.join(os.path.dirname(__file__), "p", "key.txt")
TEST_DB    = "dbmanager_trunc_test_db"
TEST_TABLE = "trunc_test_table"

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


# ===================== [A] 全行削除 + 構造/状態の保持 =====================
def test_truncate_empties(db):
    print("\n========== [A] Truncate で全行削除 ==========")
    db.Insert_Many([[None, "Alice"], [None, "Bob"], [None, "Carol"]])
    n_before = len(db.Select_Data("*")["data"])
    print(f"     truncate前の件数={n_before}")
    check("前提: 3件入っている", n_before == 3, str(n_before))

    r = db.Truncate_Table(TEST_TABLE)
    print(f"     -> success={r['success']}, message={r['message']}")
    check("Truncate success", r["success"] is True, r["error"])

    after = db.Select_Data("*")
    print(f"     truncate後の全行={after['data']}")
    check("全行が消えて0件", after["data"] == [], str(after["data"]))

    # 構造は残る:テーブル自体は一覧にある
    check("テーブルは残っている", TEST_TABLE in (db.Show_Tables()["data"] or []))
    # 内部状態は保持(Dropと違いリセットしない)
    check("table_name 保持",   db.table_name == TEST_TABLE, str(db.table_name))
    check("columns 保持",      db.columns == ["id", "name"], str(db.columns))
    check("primary_keys 保持", db.primary_keys == ["id"], str(db.primary_keys))


# ===================== [B] 構造維持 + AUTO_INCREMENT リセット =====================
def test_structure_and_autoincrement(db):
    print("\n========== [B] truncate後に挿入できて、idが1から振り直される ==========")
    # [A] のあと空 + AUTO_INCREMENT はリセット済みのはず
    i = db.Insert_Data([None, "Zoe"])
    print(f"     -> Insert success={i['success']}, lastrowid={i['lastrowid']}")
    check("truncate後も挿入できる(構造維持)", i["success"] is True, i["error"])

    rows = db.Select_Data("*")["data"]
    print(f"     挿入後の全行={rows}")
    check("1件入っている", len(rows) == 1, str(rows))
    # 直前に id=1,2,3 を使ったが、TRUNCATE でカウンタがリセットされ id は 1 に戻る
    if rows:
        check("idが1から振り直されている(TRUNCATE特有)", rows[0]["id"] == 1, str(rows[0]))


# ===================== [C] 存在しないテーブル =====================
def test_truncate_nonexistent(db):
    print("\n========== [C] 存在しないテーブルの Truncate ==========")
    r = db.Truncate_Table("no_such_table")
    print(f"     -> success={r['success']}, errno={r['errno']}, error={r['error']}")
    check("存在しないテーブルは失敗", r["success"] is False)
    check("errno が ER_NO_SUCH_TABLE(1146)",
          r["errno"] == errorcode.ER_NO_SUCH_TABLE,
          f"{r['errno']} (期待 {errorcode.ER_NO_SUCH_TABLE})")


# ===================== [D] ガード =====================
def test_truncate_guard(db):
    print("\n========== [D] 不正名のガード ==========")
    r = db.Truncate_Table("bad name;")
    print(f"     -> success={r['success']}, errno={r['errno']}, error={r['error']}")
    check("不正名は失敗", r["success"] is False)
    check("事前条件失敗なので errno は None", r["errno"] is None, str(r["errno"]))


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
        test_truncate_empties(db)
        test_structure_and_autoincrement(db)
        test_truncate_nonexistent(db)
        test_truncate_guard(db)
    finally:
        if db is not None:
            db.close()
        drop_test_db_raw(creds)      # 後始末: テストDBを削除

    print(f"\nRESULT: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()