"""
表示用SQL生成のテスト(8.4)。
  _format_sql_value / _fill_placeholders / _render_display_sql と、
  _execute が結果dictに sql(表示専用)を入れることを確認する。
  ★重要な観点: 表示用SQLは「見せる用」であり、実行には %s + params が使われること。
  DB不要でそのまま実行できる。
実行: python3 test_display_sql.py
"""
import sys
import types

# ---- mysql.connector / pandas / WHERE_node をスタブ化 ----
class _Err(Exception):
    def __init__(self, msg="", errno=None):
        super().__init__(msg); self.errno = errno

_mc = types.ModuleType("mysql.connector"); _mc.Error = _Err
_mc.connect = lambda **kw: None
_m = types.ModuleType("mysql"); _m.connector = _mc
sys.modules["mysql"] = _m
sys.modules["mysql.connector"] = _mc
sys.modules["pandas"] = types.ModuleType("pandas")
_wn = types.ModuleType("WHERE_node"); _wn.Node = object
sys.modules["WHERE_node"] = _wn

import importlib.util
spec = importlib.util.spec_from_file_location("opdb", "Operation_Database.py")
opdb = importlib.util.module_from_spec(spec); spec.loader.exec_module(opdb)
DB = opdb.DB_Manager

_passed = 0
_failed = 0
def expect(label, got, exp):
    global _passed, _failed
    if got == exp:
        _passed += 1; print(f"[OK ] {label}")
    else:
        _failed += 1; print(f"[NG ] {label}\n      got: {got!r}\n      exp: {exp!r}")


print("\n===== _format_sql_value: 型別の整形 =====")
expect("None は NULL", DB._format_sql_value(None), "NULL")
expect("int はそのまま", DB._format_sql_value(20), "20")
expect("float はそのまま", DB._format_sql_value(3.5), "3.5")
expect("True は TRUE", DB._format_sql_value(True), "TRUE")
expect("False は FALSE", DB._format_sql_value(False), "FALSE")
expect("文字列は引用符で囲む", DB._format_sql_value("Alice"), "'Alice'")
expect("文字列中の ' は '' にエスケープ", DB._format_sql_value("O'Brien"), "'O''Brien'")

print("\n===== _fill_placeholders: %s の左から順の置換 =====")
expect("%s 1個", DB._fill_placeholders("age >= %s", [20]), "age >= 20")
expect("%s 2個(型混在)",
       DB._fill_placeholders("name = %s AND age >= %s", ["Alice", 20]),
       "name = 'Alice' AND age >= 20")
expect("%s なし(paramsなし)",
       DB._fill_placeholders("SELECT * FROM members", None),
       "SELECT * FROM members")
expect("NULL を含む",
       DB._fill_placeholders("INSERT INTO t (id, name) VALUES (%s, %s)", [None, "Bob"]),
       "INSERT INTO t (id, name) VALUES (NULL, 'Bob')")

print("\n===== _render_display_sql: 単一 / 多行 =====")
expect("単一: SELECT",
       DB._render_display_sql("SELECT * FROM members WHERE age >= %s", [20]),
       "SELECT * FROM members WHERE age >= 20")
# 多行(executemany): 先頭行を見せ、行数を注記
expect("多行: 先頭行 + 行数注記",
       DB._render_display_sql("INSERT INTO members (id, name) VALUES (%s, %s)",
                              [(None, "Alice"), (None, "Bob"), (None, "Carol")], many=True),
       "INSERT INTO members (id, name) VALUES (NULL, 'Alice')  -- ほか 2 行(計 3 行)")
expect("多行だが1行のみ(注記なし)",
       DB._render_display_sql("INSERT INTO members (id, name) VALUES (%s, %s)",
                              [(1, "X")], many=True),
       "INSERT INTO members (id, name) VALUES (1, 'X')")

print("\n===== _execute が結果dictに sql を入れる =====")
class FakeCursor:
    def __init__(self): self.rowcount = 0; self.lastrowid = 0
    def execute(self, q, p=None): pass
    def executemany(self, q, p=None): pass
    def fetchall(self): return []

db = DB.__new__(DB)                       # __init__(接続)を経由せずに生成
db.connection = types.SimpleNamespace(is_connected=lambda: True, commit=lambda: None)
db.cursor = FakeCursor()

r = db._execute("SELECT * FROM members WHERE age >= %s", ("20",), fetch=True)
expect("成功時に sql が入る",
       r["sql"], "SELECT * FROM members WHERE age >= '20'")
expect("sql は表示用で、result のキーとして存在", "sql" in r, True)

# 失敗(未接続)でも sql は入る
db2 = DB.__new__(DB)
db2.connection = None
db2.cursor = None
r2 = db2._execute("DELETE FROM t WHERE id = %s", (5,))
expect("未接続でも sql は入る", r2["sql"], "DELETE FROM t WHERE id = 5")
expect("未接続は success=False", r2["success"], False)

# _fail にも sql キーがある(形の一貫性)
expect("_fail にも sql キー(None)", DB._fail("x")["sql"], None)

print(f"\nRESULT: {_passed} passed, {_failed} failed")
sys.exit(0 if _failed == 0 else 1)