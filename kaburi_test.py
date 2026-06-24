"""
DB_Manager 重複検出テスト(DB名・テーブル名)
  設計: 重複防止は MySQL の一意性制約に委ね、_execute の except が拾って
        success=False / errno付き で返す。その errno をコードで判定する。
  判定に使うMySQLエラー番号:
    DB が既に存在    -> errorcode.ER_DB_CREATE_EXISTS   (1007)
    TABLE が既に存在 -> errorcode.ER_TABLE_EXISTS_ERROR (1050)

方式: 実MySQLサーバーに接続。接続情報は p/key.txt(3行: host / user / passwd)から読む。
実行: python3 test_duplicate_detection.py
"""
import os
import sys
import mysql.connector as sqlconn
from mysql.connector import errorcode
from Operation_Database import DB_Manager

KEY_PATH   = os.path.join(os.path.dirname(__file__), "p", "key.txt")
TEST_DB    = "dbmanager_dup_test_db"     # 重複テスト専用。前後で必ず削除する
TEST_TABLE = "dup_test_table"

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
    # 後始末は生SQL(Drop は未実装のため)
    conn = sqlconn.connect(host=creds[0], user=creds[1], passwd=creds[2])
    cur  = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    conn.commit()
    cur.close()
    conn.close()


# ============ 項目A: DB名の重複検出 ============
def test_duplicate_database(db):
    print("\n========== 項目A: DB名の重複検出 ==========")
    # 1回目: 正常に作成できる(success=True / errno=None)
    first = db.Create_DataBase(TEST_DB)
    print(f"   1回目 Create_DataBase('{TEST_DB}'): success={first['success']}, errno={first['errno']}")
    check("A-1: 1回目は作成成功", first["success"] is True, first["error"])
    check("A-1: 成功時 errno は None", first["errno"] is None, str(first["errno"]))

    # 2回目: 同名で作成 → 重複で失敗。errno が ER_DB_CREATE_EXISTS(1007)
    second = db.Create_DataBase(TEST_DB)
    print(f"   2回目 Create_DataBase('{TEST_DB}'): success={second['success']}, "
          f"errno={second['errno']}, error={second['error']}")
    check("A-2: 2回目(重複)は失敗", second["success"] is False)
    check("A-2: errno が ER_DB_CREATE_EXISTS(1007)",
          second["errno"] == errorcode.ER_DB_CREATE_EXISTS,
          f"{second['errno']} (期待 {errorcode.ER_DB_CREATE_EXISTS})")
    check("A-2: error メッセージが入っている", bool(second["error"]), "errorが空")


# ============ 項目B: テーブル名の重複検出 ============
def test_duplicate_table(db):
    print("\n========== 項目B: テーブル名の重複検出 ==========")
    sel = db.Select_DataBase(TEST_DB)
    check("B-0: 対象DBを選択", sel["success"] is True, sel["error"])

    columns = [
        {"Column_Name": "id",   "Data_Type": "INT", "Extra": "AUTO_INCREMENT"},
        {"Column_Name": "name", "Data_Type": "VARCHAR(50)"},
    ]

    # 1回目: 正常に作成できる
    first = db.Create_Table(TEST_TABLE, columns, primary_key="id")
    print(f"   1回目 Create_Table('{TEST_TABLE}'): success={first['success']}, errno={first['errno']}")
    check("B-1: 1回目は作成成功", first["success"] is True, first["error"])
    check("B-1: 成功時 errno は None", first["errno"] is None, str(first["errno"]))

    # 2回目: 同名で作成 → 重複で失敗。errno が ER_TABLE_EXISTS_ERROR(1050)
    second = db.Create_Table(TEST_TABLE, columns, primary_key="id")
    print(f"   2回目 Create_Table('{TEST_TABLE}'): success={second['success']}, "
          f"errno={second['errno']}, error={second['error']}")
    check("B-2: 2回目(重複)は失敗", second["success"] is False)
    check("B-2: errno が ER_TABLE_EXISTS_ERROR(1050)",
          second["errno"] == errorcode.ER_TABLE_EXISTS_ERROR,
          f"{second['errno']} (期待 {errorcode.ER_TABLE_EXISTS_ERROR})")
    check("B-2: error メッセージが入っている", bool(second["error"]), "errorが空")


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
        test_duplicate_database(db)
        test_duplicate_table(db)
    finally:
        if db is not None:
            db.close()
        drop_test_db_raw(creds)      # 後始末: テストDBを削除

    print(f"\nRESULT: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
