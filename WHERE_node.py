"""
WHERE_node: 構造化JSON → query_option の生成・検証層。
  クライアント(スマホ等、信頼できない入力元)が送る構造化条件を、サーバー側で検証して
  DB_Manager が消費する query_option / (clause, params) を組み立てる。

セキュリティ方針(最重要):
  - クライアントには生の句文字列を作らせない。構造化された条件だけを受け取る。
  - 列名は「実テーブルの列名の集合(allowed_columns)」と照合して縛る(ホワイトリスト)。
  - 演算子・論理(AND/OR)も固定の許可集合だけ通す。
  - 値はすべて %s プレースホルダに回す(SQL文字列へ直接埋め込まない)。
  - 条件木の深さを制限(信頼できない入力に対する防御)。

条件ノードのJSON形式:
  比較:       {"col": "age", "op": ">=", "val": 20}
  NULL判定:   {"col": "name", "op": "IS NULL"}            # val なし
  IN/NOT IN:  {"col": "status", "op": "IN", "val": ["active", "pending"]}
  LIKE:       {"col": "name", "op": "LIKE", "val": "%x%"}
  AND:        {"and": [<node>, <node>, ...]}
  OR:         {"or":  [<node>, <node>, ...]}
"""

# ---- ホワイトリスト(構造に直接埋め込んでよい語彙はこれだけ) ----
_BINARY_OPS = {"=", "!=", ">", ">=", "<", "<=", "LIKE"}   # 値を1つ取る
_NULL_OPS   = {"IS NULL", "IS NOT NULL"}                   # 値を取らない
_LIST_OPS   = {"IN", "NOT IN"}                             # 値はリスト
_LOGICAL    = {"and": "AND", "or": "OR"}                   # 論理結合
_ORDER_DIRS = {"ASC", "DESC"}

MAX_DEPTH = 10        # 条件木のネスト上限(過度に深い入力を弾く)


class WhereError(Exception):
    """WHERE条件の検証エラー(内部用)。build_* が捕捉して error 文字列に変換する。"""


class Node:
    """検証済みの WHERE 条件木ノード。JSONから構築し (clause, params) を保持する。"""

    def __init__(self, clause, params):
        self.clause = clause
        self.params = params

    @classmethod
    def from_json(cls, spec, allowed_columns, depth=0):
        if depth > MAX_DEPTH:
            raise WhereError(f"condition too deeply nested (max {MAX_DEPTH})")
        if not isinstance(spec, dict):
            raise WhereError("each condition must be an object")

        has_and = "and" in spec
        has_or  = "or" in spec
        if has_and and has_or:
            raise WhereError("a node cannot have both 'and' and 'or'")

        # --- 論理ノード(and / or) ---
        if has_and or has_or:
            key = "and" if has_and else "or"
            children = spec[key]
            if not isinstance(children, list) or len(children) == 0:
                raise WhereError(f"'{key}' must be a non-empty list")
            parts, params = [], []
            for child in children:
                node = cls.from_json(child, allowed_columns, depth + 1)
                parts.append(node.clause)
                params.extend(node.params)
            clause = "(" + f" {_LOGICAL[key]} ".join(parts) + ")"
            return cls(clause, params)

        # --- 比較ノード ---
        col = spec.get("col")
        op  = spec.get("op")
        if col is None or op is None:
            raise WhereError("comparison needs 'col' and 'op'")
        if col not in allowed_columns:                  # ★ 列名のホワイトリスト(最重要の防壁)
            raise WhereError(f"unknown column: {col!r}")

        if op in _NULL_OPS:
            if "val" in spec:
                raise WhereError(f"operator {op} takes no 'val'")
            return cls(f"{col} {op}", [])

        if op in _BINARY_OPS:
            if "val" not in spec:
                raise WhereError(f"operator {op!r} needs 'val'")
            return cls(f"{col} {op} %s", [spec["val"]])   # 値はプレースホルダ

        if op in _LIST_OPS:
            vals = spec.get("val")
            if not isinstance(vals, list) or len(vals) == 0:
                raise WhereError(f"operator {op!r} needs a non-empty list 'val'")
            placeholders = ", ".join(["%s"] * len(vals))
            return cls(f"{col} {op} ({placeholders})", list(vals))

        raise WhereError(f"operator not allowed: {op!r}")  # ★ 演算子のホワイトリスト


def build_where(spec, allowed_columns):
    """JSON条件木 → (clause, params, error)。error は成功時 None、spec=None は条件なし。
    allowed_columns: 実テーブルの列名の集合(DB_Manager.Get_Columns_Info から作る)。"""
    if spec is None:
        return "", [], None
    try:
        node = Node.from_json(spec, set(allowed_columns))
        return node.clause, node.params, None
    except WhereError as e:
        return None, None, str(e)


# ---- query_option 全体の組み立て ----
def _ok(qo):
    return {"success": True, "query_option": qo, "error": None}

def _fail(msg):
    return {"success": False, "query_option": None, "error": msg}


def build_query_option(request, allowed_columns):
    """構造化リクエスト → query_option(検証済み)。
    戻り値: {"success": bool, "query_option": dict|None, "error": str|None}

    request の形(各キーは任意):
      {
        "where":    <条件ノード>,                         # build_where で検証
        "group_by": ["dept", ...],                        # 列名のリスト
        "order_by": [{"col": "age", "dir": "DESC"}, ...],  # 列名 + ASC/DESC
        "limit":    10,                                    # 非負整数(DB_Manager側で最終検証)
        "offset":   20
      }
    """
    if request is None:
        return _ok(None)
    if not isinstance(request, dict):
        return _fail("request must be an object")

    cols = set(allowed_columns)
    qo = {}

    # where(条件木)
    if request.get("where") is not None:
        clause, params, err = build_where(request["where"], cols)
        if err:
            return _fail(f"where: {err}")
        qo["where"] = (clause, params)

    # group_by(列名のリスト)
    gb = request.get("group_by")
    if gb is not None:
        if not isinstance(gb, list) or len(gb) == 0:
            return _fail("group_by must be a non-empty list")
        for c in gb:
            if c not in cols:
                return _fail(f"group_by: unknown column {c!r}")
        qo["group_by"] = ", ".join(gb)

    # order_by([{col, dir}] の形。dir は ASC/DESC、省略時 ASC)
    ob = request.get("order_by")
    if ob is not None:
        if not isinstance(ob, list) or len(ob) == 0:
            return _fail("order_by must be a non-empty list")
        parts = []
        for item in ob:
            if not isinstance(item, dict) or "col" not in item:
                return _fail("order_by item needs 'col'")
            c = item["col"]
            if c not in cols:
                return _fail(f"order_by: unknown column {c!r}")
            d = (item.get("dir") or "ASC").upper()
            if d not in _ORDER_DIRS:
                return _fail(f"order_by: dir must be ASC or DESC (got {item.get('dir')!r})")
            parts.append(f"{c} {d}")
        qo["order_by"] = ", ".join(parts)

    # limit / offset(ここでは素通し。非負整数の最終検証は DB_Manager._build_tail が行う)
    if request.get("limit") is not None:
        qo["limit"] = request["limit"]
    if request.get("offset") is not None:
        qo["offset"] = request["offset"]

    return _ok(qo)