"""
DB_Manager 中身確認ツール(項目1〜3を1ステップずつ表示し、Enterで次へ)
  各ステップで「実際に取得した値」を表示してから合否を出す。

方式: 実MySQLサーバーに接続。接続情報は p/key.txt(3行: host / user / passwd)から読む。
実行:
    python3 inspect_db_manager.py          # 対話(各ステップでEnter待ち)
    python3 inspect_db_manager.py --auto    # 止まらずに流す(入力が無い環境向け)
"""
import os
import sys
import mysql.connector as sqlconn
from Operation_Database import DB_Manager

KEY_PATH   = os.path.join(os.path.dirname(__file__), "p", "key.txt")
TEST_DB    = "dbmanager_test_db"
TEST_TABLE = "test_table"

AUTO = "--auto" in sys.argv          # 入力待ちをスキップするか

_passed = 0
_failed = 0
def check(label, cond, detail=""):
    global _passed, _failed
    mark = "OK " if cond else "NG "
    if cond: _passed += 1
    else:    _failed += 1
    print(f"   [{mark}] {label}" + (f"  -> {detail}" if (detail and not cond) else ""))


def pause(step_title):
    # ステップ区切り。--auto 以外では Enter 待ち。EOF(入力なし)でも落ちないようにする。
    if AUTO:
        return
    try:
        input(f"\n   --- Enterで次へ ({step_title}) ---")
    except EOFError:
        pass


def show(title, value):
    # 取得した中身を見やすく表示するヘルパー
    print(f"   {title}: {value}")


def show_result(title, res):
    # result 辞書の要点(success/error と data の件数・中身)を表示
    print(f"   {title}:")
    print(f"      success : {res['success']}")
    print(f"      error   : {res['error']}")
    data = res.get("data")
    if isinstance(data, list):
        print(f"      data    : {len(data)} 件 -> {data}")
    else:
        print(f"      data    : {data}")
    if res.get("lastrowid"):
        print(f"      lastrowid: {res['lastrowid']}")


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


# ================= 項目1: コネクション =================
def step1_connection(creds):
    print("\n========== 項目1: DBサーバーとのコネクション ==========")
    db = DB_Manager(creds)                       # connect 内で "successful" が表示される
    show("connection オブジェクト", db.connection)
    show("is_connected()", db.connection.is_connected() if db.connection else None)
    show("cursor オブジェクト", db.cursor)
    check("connection established",
          db.connection is not None and db.connection.is_connected())
    check("cursor created", db.cursor is not None)
    pause("項目1おわり")
    return db


# ================= 項目2: DB一覧 =================
def step2_show_databases(db):
    print("\n========== 項目2: DB名を全て取得できているか ==========")
    print(" [2-1] 作成前のDB一覧を取得")
    before = db.Show_DataBase()
    show_result("Show_DataBase()(作成前)", before)
    check("Show_DataBase success", before["success"] is True, before["error"])
    check("returns list", isinstance(before["data"], list))
    check("test DB absent before create", TEST_DB not in (before["data"] or []))
    pause("2-1 一覧取得")

    print(f"\n [2-2] テスト用DB '{TEST_DB}' を作成")
    created = db.Create_DataBase(TEST_DB)
    show_result("Create_DataBase()", created)
    check("Create_DataBase success", created["success"] is True, created["error"])
    pause("2-2 作成")

    print("\n [2-3] 作成後のDB一覧を取得して、増えたかを確認")
    after = db.Show_DataBase()
    show_result("Show_DataBase()(作成後)", after)
    added = [d for d in (after["data"] or []) if d not in (before["data"] or [])]
    show("作成前後で増えたDB(差分)", added)
    check("test DB present after create", TEST_DB in (after["data"] or []))
    pause("項目2おわり")


# ================= 項目3: テーブル一覧 =================
def step3_show_tables(db):
    print("\n========== 項目3: テーブルを全て取得できているか ==========")
    print(f" [3-1] 対象DB '{TEST_DB}' を選択(USE)")
    selected = db.Select_DataBase(TEST_DB)
    show_result("Select_DataBase()", selected)
    show("db.DB_name(選択後の内部状態)", db.DB_name)
    check("Select_DataBase success", selected["success"] is True, selected["error"])
    check("DB_name set", db.DB_name == TEST_DB)
    pause("3-1 DB選択")

    print("\n [3-2] 作成前のテーブル一覧を取得(空のはず)")
    before_t = db.Show_Tables()
    show_result("Show_Tables()(作成前)", before_t)
    check("Show_Tables success", before_t["success"] is True, before_t["error"])
    check("returns list", isinstance(before_t["data"], list))
    check("test table absent before create", TEST_TABLE not in (before_t["data"] or []))
    pause("3-2 一覧取得")

    print(f"\n [3-3] テスト用テーブル '{TEST_TABLE}' を作成")
    columns = [
        {"Column_Name": "id",   "Data_Type": "INT", "Extra": "AUTO_INCREMENT"},
        {"Column_Name": "name", "Data_Type": "VARCHAR(50)"},
    ]
    show("作成する列定義", columns)
    created_t = db.Create_Table(TEST_TABLE, columns, primary_key="id")
    show_result("Create_Table()", created_t)
    show("db.columns(作成後の内部状態)", db.columns)
    show("db.primary_keys(作成後の内部状態)", db.primary_keys)
    check("Create_Table success", created_t["success"] is True, created_t["error"])
    pause("3-3 作成")

    print("\n [3-4] 作成後のテーブル一覧を取得して、増えたかを確認")
    after_t = db.Show_Tables()
    show_result("Show_Tables()(作成後)", after_t)
    added = [t for t in (after_t["data"] or []) if t not in (before_t["data"] or [])]
    show("作成前後で増えたテーブル(差分)", added)
    check("test table present after create", TEST_TABLE in (after_t["data"] or []))
    pause("項目3おわり")


# ================= 項目4: 列情報の取得(Get_Columns_Info) =================
def step4_columns_info(db):
    print("\n========== 項目4: 列の情報を取得できているか ==========")
    print(f" [4-1] 選択中テーブル '{db.table_name}' の列情報を取得(引数省略)")
    info = db.Get_Columns_Info()                 # table_name 省略 → 選択中テーブル
    show_result("Get_Columns_Info()", info)
    check("Get_Columns_Info success", info["success"] is True, info["error"])
    check("returns list", isinstance(info["data"], list))

    cols = info["data"] or []
    names = [c["COLUMN_NAME"] for c in cols]      # 取得できた列名
    show("取得できた列名", names)
    check("列数が2 (id, name)", len(cols) == 2, f"実際は {len(cols)} 列")
    check("id 列がある",   "id" in names)
    check("name 列がある", "name" in names)
    pause("4-1 列情報の取得")

    print("\n [4-2] 各列のメタデータ(型・キー・NULL可否)を1列ずつ表示")
    for c in cols:
        print(f"      - {c['COLUMN_NAME']}: "
              f"type={c['DATA_TYPE']}, "
              f"key={c['COLUMN_KEY']!r}, "
              f"null={c['IS_NULLABLE']}, "
              f"len={c['CHARACTER_MAXIMUM_LENGTH']}, "
              f"extra={c['EXTRA']!r}")
    # id は主キー(PRI)・name は VARCHAR(50) のはず、という観点で確認
    by_name = {c["COLUMN_NAME"]: c for c in cols}
    if "id" in by_name:
        check("id の型が int", by_name["id"]["DATA_TYPE"].lower() == "int",
              by_name["id"]["DATA_TYPE"])
        check("id が主キー(COLUMN_KEY=PRI)", by_name["id"]["COLUMN_KEY"] == "PRI",
              by_name["id"]["COLUMN_KEY"])
    if "name" in by_name:
        check("name の型が varchar", by_name["name"]["DATA_TYPE"].lower() == "varchar",
              by_name["name"]["DATA_TYPE"])
        check("name の長さが 50", by_name["name"]["CHARACTER_MAXIMUM_LENGTH"] == 50,
              str(by_name["name"]["CHARACTER_MAXIMUM_LENGTH"]))
    pause("4-2 メタデータ確認")

    print(f"\n [4-3] テーブル名を明示して取得(Get_Columns_Info('{TEST_TABLE}'))")
    info2 = db.Get_Columns_Info(TEST_TABLE)       # 引数で対象テーブルを明示
    show_result(f"Get_Columns_Info('{TEST_TABLE}')", info2)
    names2 = [c["COLUMN_NAME"] for c in (info2["data"] or [])]
    show("取得できた列名(明示指定)", names2)
    check("明示指定でも同じ列が取れる", names2 == names,
          f"省略時={names} / 明示時={names2}")
    pause("項目4おわり")


# ================= 項目5: 主キー取得 + Select_Tableの内部状態 =================
def step5_primary_key_and_select(db):
    print("\n========== 項目5: Get_Primary_Key と Select_Table の内部状態 ==========")

    # 5-1: 未選択状態を作る。Select_DataBase は table_name 等をリセットする挙動を利用。
    print(f" [5-1] '{TEST_DB}' を選び直してテーブル未選択状態にする(状態リセットの確認)")
    db.Select_DataBase(TEST_DB)
    show("db.table_name(リセット後)",   db.table_name)
    show("db.columns(リセット後)",      db.columns)
    show("db.primary_keys(リセット後)", db.primary_keys)
    check("table_name が None にリセット",   db.table_name is None, str(db.table_name))
    check("columns が None にリセット",      db.columns is None, str(db.columns))
    check("primary_keys が None にリセット", db.primary_keys is None, str(db.primary_keys))
    pause("5-1 状態リセット")

    # 5-2: テーブル未選択のまま Get_Primary_Key → _fail ガードが効くか
    print("\n [5-2] テーブル未選択のまま Get_Primary_Key を呼ぶ(_failガードの確認)")
    pk_fail = db.Get_Primary_Key()
    show_result("Get_Primary_Key()(未選択時)", pk_fail)
    check("未選択時は success=False", pk_fail["success"] is False)
    check("未選択時は error が入る", bool(pk_fail["error"]), "errorが空")
    pause("5-2 未選択ガード")

    # 5-3: Select_Table を呼び、戻り値と内部状態の両方を確認
    print(f"\n [5-3] Select_Table('{TEST_TABLE}') を呼ぶ(戻り値=全行 + 内部状態の設定)")
    rows = db.Select_Table(TEST_TABLE)
    show_result(f"Select_Table('{TEST_TABLE}')", rows)
    show("db.table_name(選択後)",   db.table_name)
    show("db.columns(選択後)",      db.columns)
    show("db.primary_keys(選択後)", db.primary_keys)
    check("Select_Table success", rows["success"] is True, rows["error"])
    check("table_name が設定される", db.table_name == TEST_TABLE, str(db.table_name))
    check("columns に列名が入る (id, name)", db.columns == ["id", "name"], str(db.columns))
    check("primary_keys に主キーが入る (id)", db.primary_keys == ["id"], str(db.primary_keys))
    pause("5-3 Select_Tableの内部状態")

    # 5-4: 選択済み状態で Get_Primary_Key → data が ['id'] か
    print("\n [5-4] 選択済み状態で Get_Primary_Key を呼ぶ(data=['id'] の確認)")
    pk = db.Get_Primary_Key()
    show_result("Get_Primary_Key()(選択時)", pk)
    check("Get_Primary_Key success", pk["success"] is True, pk["error"])
    check("data が ['id']", pk["data"] == ["id"], str(pk["data"]))
    # Get_Columns_Info の COLUMN_KEY=PRI とも突き合わせ(2経路の整合)
    info = db.Get_Columns_Info()
    pri_from_info = [c["COLUMN_NAME"] for c in (info["data"] or []) if c["COLUMN_KEY"] == "PRI"]
    show("Get_Columns_Info 由来の主キー(COLUMN_KEY=PRI)", pri_from_info)
    check("Get_Primary_Key と Get_Columns_Info の主キーが一致",
          pk["data"] == pri_from_info, f"{pk['data']} vs {pri_from_info}")
    pause("項目5おわり")


def main():
    creds = get_credentials()
    print(f"接続先host: {creds[0]} / user: {creds[1]} / passwd設定: {bool(creds[2])}")
    drop_test_db_raw(creds)          # クリーンな状態から開始

    db = None
    try:
        db = step1_connection(creds)
        if db.connection is None or not db.connection.is_connected():
            print("接続できないため中止します。")
            return
        step2_show_databases(db)
        step3_show_tables(db)
        step4_columns_info(db)
        step5_primary_key_and_select(db)
    finally:
        if db is not None:
            db.close()
        drop_test_db_raw(creds)      # 後始末: テストDBを削除

    print(f"\nRESULT: {_passed} passed, {_failed} failed")


if __name__ == "__main__":
    main()