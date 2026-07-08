"""
WHERE_node の単体テスト(build_where / build_query_option)
  純粋関数(DB接続なし)なので、このファイルはそのまま実行・再実行できる。
  検証の主眼: 列名ホワイトリスト・演算子ホワイトリスト・値のプレースホルダ化・
              AND/OR・深さ制限・query_option の組み立て。
実行: python3 test_where_node.py
"""
import sys
from WHERE_node import build_where, build_query_option, MAX_DEPTH

COLS = {"id", "name", "age", "status"}     # 実テーブルの列名の集合に相当

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

def expect_err(label, result_tuple_or_dict):
    # エラーが返っている(clause=None かつ error 有り、または success=False)ことだけ確認
    global _passed, _failed
    if isinstance(result_tuple_or_dict, tuple):
        ok = result_tuple_or_dict[0] is None and bool(result_tuple_or_dict[2])
    else:
        ok = result_tuple_or_dict["success"] is False and bool(result_tuple_or_dict["error"])
    if ok: _passed += 1; print(f"[OK ] {label}")
    else:  _failed += 1; print(f"[NG ] {label}  -> {result_tuple_or_dict!r}")


print("\n===== build_where: 比較ノード =====")
expect("= 比較", build_where({"col": "age", "op": "=", "val": 20}, COLS),
       ("age = %s", [20], None))
expect(">= 比較", build_where({"col": "age", "op": ">=", "val": 20}, COLS),
       ("age >= %s", [20], None))
expect("LIKE", build_where({"col": "name", "op": "LIKE", "val": "%山%"}, COLS),
       ("name LIKE %s", ["%山%"], None))
expect("IS NULL(値なし)", build_where({"col": "name", "op": "IS NULL"}, COLS),
       ("name IS NULL", [], None))
expect("IN(リスト)", build_where({"col": "status", "op": "IN", "val": ["active", "pending"]}, COLS),
       ("status IN (%s, %s)", ["active", "pending"], None))
expect("条件なし(None)", build_where(None, COLS), ("", [], None))

print("\n===== build_where: AND / OR とネスト =====")
expect("AND 2条件",
       build_where({"and": [{"col": "age", "op": ">=", "val": 20},
                            {"col": "status", "op": "=", "val": "active"}]}, COLS),
       ("(age >= %s AND status = %s)", [20, "active"], None))
expect("OR 2条件",
       build_where({"or": [{"col": "age", "op": "<", "val": 18},
                           {"col": "age", "op": ">", "val": 65}]}, COLS),
       ("(age < %s OR age > %s)", [18, 65], None))
expect("AND(OR) のネストと値の順序",
       build_where({"and": [{"col": "status", "op": "=", "val": "active"},
                            {"or": [{"col": "age", "op": "<", "val": 18},
                                    {"col": "age", "op": ">", "val": 65}]}]}, COLS),
       ("(status = %s AND (age < %s OR age > %s))", ["active", 18, 65], None))

print("\n===== build_where: 検証(フールプルーフ) =====")
expect_err("未知の列は拒否", build_where({"col": "salary", "op": "=", "val": 1}, COLS))
expect_err("許可外の演算子は拒否", build_where({"col": "age", "op": "BETWEEN", "val": 1}, COLS))
expect_err("col/op 欠落は拒否", build_where({"val": 1}, COLS))
expect_err("IN にリスト以外は拒否", build_where({"col": "status", "op": "IN", "val": "active"}, COLS))
expect_err("IN に空リストは拒否", build_where({"col": "status", "op": "IN", "val": []}, COLS))
expect_err("比較に val 欠落は拒否", build_where({"col": "age", "op": ">="}, COLS))
expect_err("IS NULL に val があれば拒否", build_where({"col": "age", "op": "IS NULL", "val": 1}, COLS))
expect_err("and と or 両方は拒否", build_where({"and": [], "or": []}, COLS))
expect_err("and が空リストは拒否", build_where({"and": []}, COLS))
expect_err("ノードがdictでない", build_where("age >= 20", COLS))

# 深さ制限: MAX_DEPTH を超える and のネストを作って拒否されるか
deep = {"col": "age", "op": "=", "val": 1}
for _ in range(MAX_DEPTH + 2):
    deep = {"and": [deep]}
expect_err(f"深さ {MAX_DEPTH} 超は拒否", build_where(deep, COLS))

# インジェクション例: 列名に細工しても、ホワイトリスト照合で弾かれる
expect_err("列名にSQLを仕込んでも拒否", build_where({"col": "age; DROP TABLE x; --", "op": "=", "val": 1}, COLS))

print("\n===== build_query_option: 組み立て =====")
expect("where + order_by + limit",
       build_query_option({"where": {"col": "age", "op": ">=", "val": 20},
                           "order_by": [{"col": "age", "dir": "DESC"}, {"col": "name"}],
                           "limit": 10}, COLS),
       {"success": True,
        "query_option": {"where": ("age >= %s", [20]),
                         "order_by": "age DESC, name ASC",
                         "limit": 10},
        "error": None})
expect("group_by",
       build_query_option({"group_by": ["status"]}, COLS),
       {"success": True, "query_option": {"group_by": "status"}, "error": None})
expect("空リクエスト(None)",
       build_query_option(None, COLS),
       {"success": True, "query_option": None, "error": None})
expect("limit/offset 素通し",
       build_query_option({"limit": 5, "offset": 10}, COLS),
       {"success": True, "query_option": {"limit": 5, "offset": 10}, "error": None})

print("\n===== build_query_option: 検証 =====")
expect_err("order_by の未知列は拒否",
           build_query_option({"order_by": [{"col": "salary"}]}, COLS))
expect_err("order_by の dir 不正は拒否",
           build_query_option({"order_by": [{"col": "age", "dir": "UP"}]}, COLS))
expect_err("group_by の未知列は拒否",
           build_query_option({"group_by": ["salary"]}, COLS))
expect_err("where の未知列は query_option でも拒否",
           build_query_option({"where": {"col": "salary", "op": "=", "val": 1}}, COLS))
expect_err("request が dict でない",
           build_query_option(["not", "a", "dict"], COLS))

print(f"\nRESULT: {_passed} passed, {_failed} failed")
sys.exit(0 if _failed == 0 else 1)