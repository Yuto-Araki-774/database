"""
集約(統計)関数 + HAVING のテスト(検証は WHERE_node に一元化済み)。
  - WHERE_node.build_select_columns / _render_aggregate の検証
  - Select_Data が集約を含む SELECT を組み立てること
  - build_query_option + Select_Data で HAVING がSQLに載ること
  DB不要でそのまま実行できる。
実行: python3 test_aggregate.py
"""
import sys, os, types

# ---- mysql.connector / pandas をスタブ化(WHERE_node は実物を使う) ----
class _Err(Exception):
    def __init__(self, msg="", errno=None):
        super().__init__(msg); self.errno = errno

_mc = types.ModuleType("mysql.connector"); _mc.Error = _Err
_mc.connect = lambda **kw: None
_m = types.ModuleType("mysql"); _m.connector = _mc
sys.modules["mysql"] = _m
sys.modules["mysql.connector"] = _mc
sys.modules["pandas"] = types.ModuleType("pandas")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import WHERE_node as WN                       # 実物(集約・HAVINGの検証はここ)

import importlib.util
spec = importlib.util.spec_from_file_location("opdb", "Operation_Database.py")
opdb = importlib.util.module_from_spec(spec); spec.loader.exec_module(opdb)
DB = opdb.DB_Manager

_passed = 0; _failed = 0
def expect(label, got, exp):
    global _passed, _failed
    if got == exp:
        _passed += 1; print(f"[OK ] {label}")
    else:
        _failed += 1; print(f"[NG ] {label}\n      got: {got!r}\n      exp: {exp!r}")

COLS = ["id", "dept", "price", "age", "name"]


print("\n===== 許可リスト(WHERE_node) =====")
expect("7関数がホワイトリスト",
       WN._AGGREGATES,
       {"COUNT", "SUM", "AVG", "MAX", "MIN", "STDDEV", "VARIANCE"})

print("\n===== build_select_columns: 基本 =====")
expect("None は *", WN.build_select_columns(None, COLS), ("*", None))
expect("文字列 '*' はそのまま", WN.build_select_columns("*", COLS), ("*", None))
expect("文字列 'id, name' はそのまま", WN.build_select_columns("id, name", COLS), ("id, name", None))
expect("普通の列リスト", WN.build_select_columns(["dept", "price"], COLS), ("dept, price", None))

print("\n===== build_select_columns: 集約 =====")
expect("SUM(price) AS total",
       WN.build_select_columns([{"func": "SUM", "column": "price", "as": "total"}], COLS),
       ("SUM(price) AS total", None))
expect("COUNT(*)",
       WN.build_select_columns([{"func": "COUNT", "column": "*"}], COLS),
       ("COUNT(*)", None))
expect("小文字funcの大文字化",
       WN.build_select_columns([{"func": "avg", "column": "age", "as": "a"}], COLS),
       ("AVG(age) AS a", None))
expect("STDDEV / VARIANCE",
       WN.build_select_columns(
           [{"func": "STDDEV", "column": "price", "as": "sd"},
            {"func": "VARIANCE", "column": "price", "as": "var"}], COLS),
       ("STDDEV(price) AS sd, VARIANCE(price) AS var", None))
expect("普通の列 + 集約 の混在",
       WN.build_select_columns(["dept", {"func": "COUNT", "column": "*", "as": "cnt"}], COLS),
       ("dept, COUNT(*) AS cnt", None))

print("\n===== build_select_columns: 異常系 =====")
def bad(label, columns, needle):
    ok, err = WN.build_select_columns(columns, COLS)
    expect(label, (ok is None and needle in err), True)
bad("未知の列", ["nope"], "unknown column")
bad("許可外の関数", [{"func": "MEDIAN", "column": "price"}], "not allowed")
bad("SUM(*) は不可", [{"func": "SUM", "column": "*"}], "'*'")
bad("column欠落", [{"func": "SUM"}], "needs 'column'")
bad("func欠落", [{"column": "price"}], "needs 'func'")
bad("集約の列が未知", [{"func": "SUM", "column": "nope"}], "unknown column")
bad("別名が不正(空白)", [{"func": "SUM", "column": "price", "as": "bad alias"}], "invalid alias")
bad("空リスト", [], "non-empty")

print("\n===== Select_Data が集約SQLを組み立てる(スタブcursor) =====")
class FakeCursor:
    def __init__(self): self.rowcount = 0; self.lastrowid = 0; self.last_query = None
    def execute(self, q, p=None): self.last_query = q
    def fetchall(self): return []

def make_db():
    db = DB.__new__(DB)
    db.connection = types.SimpleNamespace(is_connected=lambda: True, commit=lambda: None)
    db.cursor = FakeCursor()
    db.table_name = "members"; db.columns = COLS
    return db

db = make_db()
db.Select_Data(["dept", {"func": "COUNT", "column": "*", "as": "cnt"}], {"group_by": "dept"})
expect("dept ごとの件数",
       db.cursor.last_query,
       "SELECT dept, COUNT(*) AS cnt FROM members GROUP BY dept")

db = make_db()
db.Select_Data([{"func": "AVG", "column": "price", "as": "avg_price"}])
expect("平均のみ", db.cursor.last_query, "SELECT AVG(price) AS avg_price FROM members")

db = make_db()
db.Select_Data("*")
expect("後方互換 '*'", db.cursor.last_query, "SELECT * FROM members")

db = make_db()
r = db.Select_Data([{"func": "MEDIAN", "column": "price"}])
expect("不正な集約は _fail", r["success"], False)
expect("不正な集約はSQL実行なし", db.cursor.last_query, None)

db2 = make_db(); db2.table_name = None
r = db2.Select_Data([{"func": "COUNT", "column": "*"}])
expect("table未選択は _fail", (r["success"] is False and r["error"] == "table not selected"), True)

print("\n===== HAVING: build_query_option + Select_Data 統合 =====")
# 件数が5以上の部署だけ
req = {"group_by": ["dept"],
       "having": {"agg": {"func": "COUNT", "column": "*"}, "op": ">=", "val": 5}}
built = WN.build_query_option(req, COLS)
expect("build_query_option 成功", built["success"], True)
expect("qo に having タプル",
       built["query_option"]["having"], ("COUNT(*) >= %s", [5]))

db = make_db()
db.Select_Data(["dept", {"func": "COUNT", "column": "*", "as": "cnt"}], built["query_option"])
expect("GROUP BY + HAVING がSQLに載る",
       db.cursor.last_query,
       "SELECT dept, COUNT(*) AS cnt FROM members GROUP BY dept HAVING COUNT(*) >= %s")

# 複合HAVING(AND) + 列左辺(GROUP BY列)も可
req2 = {"group_by": ["dept"],
        "having": {"and": [
            {"agg": {"func": "COUNT", "column": "*"}, "op": ">=", "val": 5},
            {"agg": {"func": "AVG", "column": "price"}, "op": "<", "val": 1000},
        ]}}
built2 = WN.build_query_option(req2, COLS)
expect("複合HAVING 成功", built2["success"], True)
expect("複合HAVING の句",
       built2["query_option"]["having"],
       ("(COUNT(*) >= %s AND AVG(price) < %s)", [5, 1000]))

# HAVING 異常系
def bad_having(label, having, needle):
    b = WN.build_query_option({"having": having}, COLS)
    expect(label, (b["success"] is False and needle in b["error"]), True)
bad_having("HAVINGで許可外関数", {"agg": {"func": "MEDIAN", "column": "price"}, "op": ">", "val": 1}, "not allowed")
bad_having("HAVINGで未知の列", {"agg": {"func": "SUM", "column": "nope"}, "op": ">", "val": 1}, "unknown column")
bad_having("HAVINGで col と agg 併記", {"col": "dept", "agg": {"func": "COUNT", "column": "*"}, "op": ">", "val": 1}, "both")

print(f"\nRESULT: {_passed} passed, {_failed} failed")
sys.exit(0 if _failed == 0 else 1)