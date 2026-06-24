"""
DB_Manager 単体テスト その1(項目1〜3)
  項目1: DBサーバーとコネクションが取れるか
  項目2: サーバー内のDB名を全て取得できているか(作成の前後差分で検証)
  項目3: あるDBのテーブルを全て取得できているか(作成の前後差分で検証)

方式: 実MySQLサーバーに接続して検証する。
接続情報はコードに書かず p/key.txt から読む(3行形式):
    1行目: host
    2行目: user
    3行目: passwd(無ければ空行でも可)
実行例:
    python3 test_db_manager.py

注意: テスト専用DB(下記 TEST_DB)を作成・削除する。既存の同名DBがあると
      削除対象になるので、衝突しない名前にしてある。
"""
import os
import sys
import mysql.connector as sqlconn
from Operation_Database import DB_Manager

KEY_PATH   = os.path.join(os.path.dirname(__file__), "p", "key.txt")  # p/key.txt(3行形式)
TEST_DB    = "dbmanager_test_db"     # テスト専用。実行の前後で必ず削除する(再実行可能にするため)
TEST_TABLE = "test_table"

# ---- 簡易アサート(前回のロジック検証と同じスタイル) ----
_passed = 0
_failed = 0
def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"[OK ] {label}")
    else:
        _failed += 1
        print(f"[NG ] {label}" + (f"  -> {detail}" if detail else ""))


def get_credentials():
    # p/key.txt から [host, user, passwd] を読む(3行形式: host / user / passwd)。
    # 認証情報そのものはログや例外メッセージに出さない。
    try:
        with open(KEY_PATH, encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]
    except OSError:
        print(f"接続情報ファイルを読めません: {KEY_PATH}")   # 中身は出さない
        sys.exit(2)

    host   = lines[0].strip() if len(lines) >= 1 else ""
    user   = lines[1].strip() if len(lines) >= 2 else ""
    passwd = lines[2].strip() if len(lines) >= 3 else ""     # パスワード無しは空でも可

    if not host or not user:                                 # 必須が欠けたら明確に停止
        print(f"接続情報の形式が不正です(1行目host/2行目userが必要): {KEY_PATH}")
        sys.exit(2)

    return [host, user, passwd]


def drop_test_db_raw(creds):
    # テストの前後始末。DB_Manager に Drop は未実装なので、後始末だけ生SQLで行う。
    # 将来 Drop_DataBase を実装したら、それに置き換えられる。
    conn = sqlconn.connect(host=creds[0], user=creds[1], passwd=creds[2])
    cur  = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
    conn.commit()
    cur.close()
    conn.close()


# ---- 項目1: コネクションが取れるか ----
def test_item1_connection(creds):
    db = DB_Manager(creds)
    check("1: connection established",
          db.connection is not None and db.connection.is_connected(),
          "connect に失敗。接続情報(host/user/passwd)を確認")
    check("1: cursor created", db.cursor is not None)
    return db


# ---- 項目2: DB一覧を取得できるか(作成前は無い → 作成後は有る) ----
def test_item2_show_databases(db):
    before = db.Show_DataBase()
    check("2: Show_DataBase success", before["success"] is True, before["error"])
    check("2: returns list", isinstance(before["data"], list))
    check("2: test DB absent before create",
          TEST_DB not in (before["data"] or []),
          "事前の掃除が効いていない")

    created = db.Create_DataBase(TEST_DB)
    check("2: Create_DataBase success", created["success"] is True, created["error"])

    after = db.Show_DataBase()
    check("2: Show_DataBase success (after)", after["success"] is True, after["error"])
    check("2: test DB present after create",
          TEST_DB in (after["data"] or []),
          "作成したDBが一覧に現れない=取得できていない")


# ---- 項目3: テーブル一覧を取得できるか(作成前は無い → 作成後は有る) ----
def test_item3_show_tables(db):
    selected = db.Select_DataBase(TEST_DB)
    check("3: Select_DataBase success", selected["success"] is True, selected["error"])
    check("3: DB_name set", db.DB_name == TEST_DB)

    before_t = db.Show_Tables()
    check("3: Show_Tables success", before_t["success"] is True, before_t["error"])
    check("3: returns list", isinstance(before_t["data"], list))
    check("3: test table absent before create",
          TEST_TABLE not in (before_t["data"] or []),
          "作成前なのにテーブルが存在している")

    columns = [
        {"Column_Name": "id",   "Data_Type": "INT", "Extra": "AUTO_INCREMENT"},
        {"Column_Name": "name", "Data_Type": "VARCHAR(50)"},
    ]
    created_t = db.Create_Table(TEST_TABLE, columns, primary_key="id")
    check("3: Create_Table success", created_t["success"] is True, created_t["error"])

    after_t = db.Show_Tables()
    check("3: Show_Tables success (after)", after_t["success"] is True, after_t["error"])
    check("3: test table present after create",
          TEST_TABLE in (after_t["data"] or []),
          "作成したテーブルが一覧に現れない=取得できていない")


def main():
    creds = get_credentials()
    drop_test_db_raw(creds)          # クリーンな状態から開始(再実行可能にする)

    db = None
    try:
        db = test_item1_connection(creds)
        if db.connection is None or not db.connection.is_connected():
            print("接続できないため項目2以降を中止します。")
            return
        test_item2_show_databases(db)
        test_item3_show_tables(db)
    finally:
        if db is not None:
            db.close()
        drop_test_db_raw(creds)      # 後始末: テストDBを削除

    print(f"\nRESULT: {_passed} passed, {_failed} failed")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()