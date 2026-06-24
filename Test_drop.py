"""
DB_Manager テスト: Drop_Table / Drop_DataBase
  エリアA: Drop_Table
    - 差分: 作成 → 一覧にある → Drop → 一覧から消えた
    - 状態: 選択中テーブルを消すと table_name/columns/primary_keys が None にリセット
    - 状態: 非選択テーブルを消しても選択は保持
    - 存在しないテーブルの Drop は errno=ER_BAD_TABLE_ERROR(1051)
    - 不正名は _fail(errno=None)
  エリアB: Drop_DataBase(同様の観点。errno=ER_DB_DROP_EXISTS=1008)

注意: Drop は確認(「Delete」入力等)をフロントが通した後に呼ぶ前提。ここではバックエンド単体を検証。
方式: 実MySQLサーバーに接続。接続情報は p/key.txt(3行: host / user / passwd)から読む。
実行: python3 test_drop.py
"""
import os
import sys
import mysql.connector as sqlconn
from mysql.connector import errorcode
from Operation_Database import DB_Manager

KEY_PATH = os.path.join(os.path.dirname(__file__), "p", "key.txt")
TEST_DB  = "dbmanager_drop_test_db"
TEST_DB2 = "dbmanager_drop_test_db2"

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


def drop_test_dbs_raw(creds):
    # 後始末は対象から独立した生SQL(Drop自体をテストするので、後始末はDrop_*を使わない)
    conn = sqlconn.connect(host=creds[0], user=creds[1], passwd=creds[2])
    cur  = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB2}")
    conn.commit()
    cur.close()
    conn.close()


def cols():
    return [
        {"Column_Name": "id",   "Data_Type": "INT", "Extra": "AUTO_INCREMENT"},
        {"Column_Name": "name", "Data_Type": "VARCHAR(50)"},
    ]


# ========================= エリアA: Drop_Table =========================
def area_a_drop_table(db):
    print("\n########## エリアA: Drop_Table ##########")
    db.Create_Table("table_a", cols(), primary_key="id")
    db.Create_Table("table_b", cols(), primary_key="id")
    db.Select_Table("table_a")                      # 選択中 = table_a にする
    check("準備: 選択中は table_a", db.table_name == "table_a", str(db.table_name))

    t = db.Show_Tables()
    print(f"   作成後のテーブル一覧: {t['data']}")
    check("両テーブルが存在", set(["table_a", "table_b"]).issubset(set(t["data"] or [])), str(t["data"]))

    # [1] 非選択テーブル(table_b)を Drop → 選択は保持される
    print("\n [1] 非選択の table_b を Drop")
    r = db.Drop_Table("table_b")
    print(f"     -> success={r['success']}, table_name={db.table_name}")
    check("Drop_Table success", r["success"] is True, r["error"])
    after = db.Show_Tables()
    check("table_b が消えた", "table_b" not in (after["data"] or []), str(after["data"]))
    check("table_a は残っている", "table_a" in (after["data"] or []), str(after["data"]))
    check("選択中 table_a は保持", db.table_name == "table_a", str(db.table_name))

    # [2] 選択中テーブル(table_a)を Drop → 内部状態がリセット
    print("\n [2] 選択中の table_a を Drop(状態リセットを確認)")
    r = db.Drop_Table("table_a")
    print(f"     -> success={r['success']}, table_name={db.table_name}, "
          f"columns={db.columns}, primary_keys={db.primary_keys}")
    check("Drop_Table success", r["success"] is True, r["error"])
    check("table_a が消えた", "table_a" not in (db.Show_Tables()["data"] or []))
    check("table_name が None にリセット",   db.table_name is None, str(db.table_name))
    check("columns が None にリセット",       db.columns is None, str(db.columns))
    check("primary_keys が None にリセット",  db.primary_keys is None, str(db.primary_keys))

    # [3] 存在しないテーブルの Drop → errno=ER_BAD_TABLE_ERROR(1051)
    print("\n [3] 存在しないテーブルを Drop(errno確認)")
    r = db.Drop_Table("no_such_table")
    print(f"     -> success={r['success']}, errno={r['errno']}, error={r['error']}")
    check("存在しないテーブルDropは失敗", r["success"] is False)
    check("errno が ER_BAD_TABLE_ERROR(1051)",
          r["errno"] == errorcode.ER_BAD_TABLE_ERROR,
          f"{r['errno']} (期待 {errorcode.ER_BAD_TABLE_ERROR})")

    # [4] 不正名のガード(_fail、errno=None)
    print("\n [4] 不正なテーブル名のガード")
    r = db.Drop_Table("bad name;")
    print(f"     -> success={r['success']}, errno={r['errno']}, error={r['error']}")
    check("不正名は失敗", r["success"] is False)
    check("事前条件失敗なので errno は None", r["errno"] is None, str(r["errno"]))


# ========================= エリアB: Drop_DataBase =========================
def area_b_drop_database(db):
    print("\n########## エリアB: Drop_DataBase ##########")
    db.Select_DataBase(TEST_DB)                     # 選択中 = TEST_DB
    check("準備: 選択中は TEST_DB", db.DB_name == TEST_DB, str(db.DB_name))
    db.Create_DataBase(TEST_DB2)                    # もう1つ作る(選択は変わらない)

    d = db.Show_DataBase()
    check("両DBが存在", set([TEST_DB, TEST_DB2]).issubset(set(d["data"] or [])),
          f"{TEST_DB},{TEST_DB2} in {d['data']}")

    # [1] 非選択DB(TEST_DB2)を Drop → 選択は保持
    print(f"\n [1] 非選択の {TEST_DB2} を Drop")
    r = db.Drop_DataBase(TEST_DB2)
    print(f"     -> success={r['success']}, DB_name={db.DB_name}")
    check("Drop_DataBase success", r["success"] is True, r["error"])
    after = db.Show_DataBase()
    check(f"{TEST_DB2} が消えた", TEST_DB2 not in (after["data"] or []))
    check(f"{TEST_DB} は残っている", TEST_DB in (after["data"] or []))
    check("選択中 TEST_DB は保持", db.DB_name == TEST_DB, str(db.DB_name))

    # [2] 選択中DB(TEST_DB)を Drop → 内部状態がリセット
    print(f"\n [2] 選択中の {TEST_DB} を Drop(状態リセットを確認)")
    r = db.Drop_DataBase(TEST_DB)
    print(f"     -> success={r['success']}, DB_name={db.DB_name}, table_name={db.table_name}")
    check("Drop_DataBase success", r["success"] is True, r["error"])
    check(f"{TEST_DB} が消えた", TEST_DB not in (db.Show_DataBase()["data"] or []))
    check("DB_name が None にリセット",     db.DB_name is None, str(db.DB_name))
    check("table_name も None にリセット",  db.table_name is None, str(db.table_name))

    # [3] 存在しないDBの Drop → errno=ER_DB_DROP_EXISTS(1008)
    print("\n [3] 存在しないDBを Drop(errno確認)")
    r = db.Drop_DataBase("no_such_db_xyz")
    print(f"     -> success={r['success']}, errno={r['errno']}, error={r['error']}")
    check("存在しないDB Dropは失敗", r["success"] is False)
    check("errno が ER_DB_DROP_EXISTS(1008)",
          r["errno"] == errorcode.ER_DB_DROP_EXISTS,
          f"{r['errno']} (期待 {errorcode.ER_DB_DROP_EXISTS})")

    # [4] 不正名のガード
    print("\n [4] 不正なDB名のガード")
    r = db.Drop_DataBase("bad;name")
    print(f"     -> success={r['success']}, errno={r['errno']}")
    check("不正名は失敗", r["success"] is False)
    check("事前条件失敗なので errno は None", r["errno"] is None, str(r["errno"]))


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
    drop_test_dbs_raw(creds)         # クリーンな状態から開始

    db = None
    try:
        db = DB_Manager(creds)
        if db.connection is None or not db.connection.is_connected():
            print("接続できないため中止します。")
            return
        if not setup(db):
            print("setup に失敗したため中止します。")
            return
        area_a_drop_table(db)
        area_b_drop_database(db)
    finally:
        if db is not None:
            db.close()
        drop_test_dbs_raw(creds)     # 後始末(テストが途中で落ちても掃除する)

    print(f"\nRESULT: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()