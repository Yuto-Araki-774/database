"""
DB_Manager 内部のクエリ組み立てロジックの単体テスト
  対象: _build_tail / _render_clause / _render_subquery
  これらは純粋関数(DB接続を使わず、入力から SQL文字列とparamsを作って返すだけ)。
  そのため MySQL も接続情報も不要で、mysql.connector 等をスタブ化して実行する。
  → このファイルは DB なしでそのまま実行・再実行できる(リグレッション検出用)。
実行: python3 test_query_builders.py
"""
import sys
import types

# ---- DB系モジュールをスタブ化(本物が無くても、また接続せずに実行するため) ----
class _Err(Exception):
    def __init__(self, msg="", errno=None):
        super().__init__(msg); self.errno = errno; self.msg = msg

_fake_conn = types.ModuleType("mysql.connector")
_fake_conn.Error = _Err
def _connect(**kw):
    class _C:
        def is_connected(self): return False     # 接続しない(純粋関数のテストなので不要)
        def cursor(self, dictionary=False): return None
    return _C()
_fake_conn.connect = _connect
_fake_mysql = types.ModuleType("mysql"); _fake_mysql.connector = _fake_conn
sys.modules["mysql"] = _fake_mysql
sys.modules["mysql.connector"] = _fake_conn
sys.modules["pandas"] = types.ModuleType("pandas")
_wn = types.ModuleType("WHERE_node"); _wn.Node = object
sys.modules["WHERE_node"] = _wn

from Operation_Database import DB_Manager

db = DB_Manager(["dummy", "dummy", "dummy"])     # connect は no-op(is_connected=False)

_passed = 0
_failed = 0
def expect(label, got, exp):
    global _passed, _failed
    if got == exp:
        _passed += 1
        print(f"[OK ] {label}")
    else:
        _failed += 1
        print(f"[NG ] {label}\n      got: {got!r}\n      exp: {exp!r}")


print("\n===== _build_tail: 基本の句 =====")
expect("query_option=None は空",
       db._build_tail(None), ("", [], None))
expect("WHERE のみ",
       db._build_tail({"where": ("age >= %s", [20])}),
       (" WHERE age >= %s", [20], None))
expect("WHERE 複数値",
       db._build_tail({"where": ("a = %s AND b = %s", [1, "x"])}),
       (" WHERE a = %s AND b = %s", [1, "x"], None))
expect("空のWHEREは無視(where[0]が空)",
       db._build_tail({"where": ("", [])}),
       ("", [], None))
expect("GROUP BY(値なし)",
       db._build_tail({"group_by": "dept"}),
       (" GROUP BY dept", [], None))
expect("GROUP BY + HAVING",
       db._build_tail({"group_by": "dept", "having": ("COUNT(*) > %s", [5])}),
       (" GROUP BY dept HAVING COUNT(*) > %s", [5], None))
expect("ORDER BY(値なし)",
       db._build_tail({"order_by": "age DESC, name"}),
       (" ORDER BY age DESC, name", [], None))
expect("LIMIT(値はプレースホルダ)",
       db._build_tail({"limit": 10}),
       (" LIMIT %s", [10], None))
expect("LIMIT + OFFSET",
       db._build_tail({"limit": 10, "offset": 20}),
       (" LIMIT %s OFFSET %s", [10, 20], None))
expect("WHERE→GROUP BY→HAVING→ORDER BY→LIMIT の順と値の順",
       db._build_tail({"where": ("a = %s", [1]),
                       "group_by": "g",
                       "having": ("SUM(x) > %s", [2]),
                       "order_by": "a DESC",
                       "limit": 5}),
       (" WHERE a = %s GROUP BY g HAVING SUM(x) > %s ORDER BY a DESC LIMIT %s",
        [1, 2, 5], None))

print("\n===== _build_tail: LIMIT/OFFSET の検証 =====")
expect("OFFSET単独はエラー",
       db._build_tail({"offset": 5}), (None, None, "offset requires limit"))
expect("LIMIT に bool はエラー",
       db._build_tail({"limit": True}), (None, None, "limit must be a non-negative integer"))
expect("LIMIT 負数はエラー",
       db._build_tail({"limit": -1}), (None, None, "limit must be a non-negative integer"))
expect("OFFSET 負数はエラー",
       db._build_tail({"limit": 5, "offset": -1}), (None, None, "offset must be a non-negative integer"))
expect("LIMIT 0 は許可",
       db._build_tail({"limit": 0}), (" LIMIT %s", [0], None))

print("\n===== _render_clause: プレースホルダとparams =====")
expect("%s 1個",
       db._render_clause(("a = %s", [1]), None), ("a = %s", [1], None))
expect("%s 2個",
       db._render_clause(("a = %s AND b = %s", [1, 2]), None), ("a = %s AND b = %s", [1, 2], None))
expect("%s 0個(値なし条件)",
       db._render_clause(("a IS NOT NULL", []), None), ("a IS NOT NULL", [], None))
expect("params不足はエラー",
       db._render_clause(("a = %s AND b = %s", [1]), None),
       (None, None, "clause: not enough params for placeholders"))
expect("params過剰はエラー",
       db._render_clause(("a = %s", [1, 2]), None),
       (None, None, "clause: too many params for placeholders"))
expect("未知のサブクエリ名はエラー",
       db._render_clause(("a IN {nope}", []), {}),
       (None, None, "clause: unknown subquery 'nope'"))

print("\n===== _render_subquery: 単体 =====")
expect("WHERE付きサブクエリ",
       db._render_subquery({"select": "id", "from": "customers", "where": ("city = %s", ["Tokyo"])}),
       ("SELECT id FROM customers WHERE city = %s", ["Tokyo"], None))
expect("WHEREなしサブクエリ",
       db._render_subquery({"select": "id", "from": "customers"}),
       ("SELECT id FROM customers", [], None))
expect("集約+GROUP BY+HAVINGのサブクエリ",
       db._render_subquery({"select": "dept", "from": "emp",
                            "group_by": "dept", "having": ("COUNT(*) > %s", [3])}),
       ("SELECT dept FROM emp GROUP BY dept HAVING COUNT(*) > %s", [3], None))
expect("select 欠落はエラー",
       db._render_subquery({"from": "x"}), (None, None, "subquery requires select"))
expect("空のサブクエリはエラー",
       db._render_subquery({}), (None, None, "empty subquery"))
expect("不正な from 名はエラー",
       db._render_subquery({"select": "id", "from": "bad name"}),
       (None, None, "invalid subquery table"))
expect("サブクエリ内 subqueries は深さ3で拒否",
       db._render_subquery({"select": "id", "from": "x", "subqueries": {"y": {"select": "id", "from": "z"}}}),
       (None, None, "subquery nesting too deep (max depth 2)"))
expect("サブクエリ内 JOIN は拒否",
       db._render_subquery({"select": "id", "from": "x",
                            "joins": [{"type": "INNER", "table": "z", "on": "x.a=z.a"}]}),
       (None, None, "joins inside subquery not supported"))

print("\n===== _build_tail 経由のサブクエリ展開(paramsの混在順序) =====")
expect("外側%s + サブクエリ + 外側%s の順序",
       db._build_tail({
           "where": ("total >= %s AND customer_id IN {sub1} AND status = %s", [100, "active"]),
           "subqueries": {"sub1": {"select": "id", "from": "customers",
                                   "where": ("city = %s AND age > %s", ["Tokyo", 20])}},
       }),
       (" WHERE total >= %s AND customer_id IN "
        "(SELECT id FROM customers WHERE city = %s AND age > %s) AND status = %s",
        [100, "Tokyo", 20, "active"], None))
expect("HAVING でもサブクエリ参照できる",
       db._build_tail({
           "group_by": "dept",
           "having": ("COUNT(*) > %s AND dept IN {d}", [2]),
           "subqueries": {"d": {"select": "dept", "from": "targets", "where": ("active = %s", [1])}},
       }),
       (" GROUP BY dept HAVING COUNT(*) > %s AND dept IN "
        "(SELECT dept FROM targets WHERE active = %s)", [2, 1], None))
expect("深さ3(トップ→sub→subのsubqueries)は _build_tail 経由でも拒否",
       db._build_tail({
           "where": ("a IN {s}", []),
           "subqueries": {"s": {"select": "id", "from": "t",
                                "where": ("b IN {inner}", []),
                                "subqueries": {"inner": {"select": "id", "from": "u"}}}},
       }),
       (None, None, "subquery nesting too deep (max depth 2)"))


print(f"\nRESULT: {_passed} passed, {_failed} failed")
sys.exit(0 if _failed == 0 else 1)