"""
WHERE_node: 構造化JSON → query_option の生成・検証層。
  クライアント(スマホ等、信頼できない入力元)が送る構造化条件を、サーバー側で検証して
  DB_Manager が消費する query_option / (clause, params) を組み立てる。

セキュリティ方針(最重要):
  - クライアントには生の句文字列を作らせない。構造化された条件だけを受け取る。
  - 列名は「実テーブルの列名の集合(allowed_columns)」と照合して縛る(ホワイトリスト)。
  - 演算子・論理(AND/OR)・集約関数も固定の許可集合だけ通す。
  - 値はすべて %s プレースホルダに回す(SQL文字列へ直接埋め込まない)。
  - 条件木の深さを制限(信頼できない入力に対する防御)。

条件ノードのJSON形式(WHERE):
  比較:       {"col": "age", "op": ">=", "val": 20}
  NULL判定:   {"col": "name", "op": "IS NULL"}            # val なし
  IN/NOT IN:  {"col": "status", "op": "IN", "val": ["active", "pending"]}
  LIKE:       {"col": "name", "op": "LIKE", "val": "%x%"}
  AND:        {"and": [<node>, <node>, ...]}
  OR:         {"or":  [<node>, <node>, ...]}

集約(SELECT句):
  build_select_columns で使う。列名(文字列)と集約(オブジェクト)の混在リスト。
  集約: {"func": "SUM", "column": "price", "as": "total"}  /  {"func": "COUNT", "column": "*"}

条件ノード(HAVING):
  WHERE と同じ構造だが、比較ノードの左辺に集約を書ける(GROUP BY した列も可)。
  集約左辺: {"agg": {"func": "COUNT", "column": "*"}, "op": ">=", "val": 10}
  列左辺:   {"col": "dept", "op": "=", "val": "sales"}       # GROUP BY 列
  AND/OR:   WHERE と同じ

UPDATE(build_update):
  {"set": {"is_released": 1}, "key": {"series_id": 3, "volume_number": 5}}   # 主キーで1行
  {"set": {"is_released": 1}, "where": <条件ノード>}                          # 条件で複数行
  set の列は実列と照合し、主キー列の書き換えは禁止。key/where はどちらか一方が必須。
"""
import re

# ---- ホワイトリスト(構造に直接埋め込んでよい語彙はこれだけ) ----
_BINARY_OPS = {"=", "!=", ">", ">=", "<", "<=", "LIKE"}   # 値を1つ取る
_NULL_OPS   = {"IS NULL", "IS NOT NULL"}                   # 値を取らない
_LIST_OPS   = {"IN", "NOT IN"}                             # 値はリスト
_LOGICAL    = {"and": "AND", "or": "OR"}                   # 論理結合
_ORDER_DIRS = {"ASC", "DESC"}
_AGGREGATES = {"COUNT", "SUM", "AVG", "MAX", "MIN", "STDDEV", "VARIANCE"}  # 許可する集約関数

_IDENT_RE = re.compile(r"\w+")                            # 識別子(列名・別名)の形

MAX_DEPTH = 10        # 条件木のネスト上限(過度に深い入力を弾く)


def _is_valid_identifier(name):
    return bool(name) and _IDENT_RE.fullmatch(name) is not None


class WhereError(Exception):
    """WHERE条件の検証エラー(内部用)。build_* が捕捉して error 文字列に変換する。"""


class Node:
    """検証済みの WHERE 条件木ノード。JSONから構築し (clause, params) を保持する。"""

    def __init__(self, clause, params):
        self.clause = clause
        self.params = params

    @classmethod
    def from_json(cls, spec, allowed_columns, depth=0, allow_agg=False):
        # allow_agg=True のとき、比較ノードの左辺に集約 {"agg": {...}} を書ける(HAVING用)。
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
                node = cls.from_json(child, allowed_columns, depth + 1, allow_agg)
                parts.append(node.clause)
                params.extend(node.params)
            clause = "(" + f" {_LOGICAL[key]} ".join(parts) + ")"
            return cls(clause, params)

        # --- 比較ノード ---
        op = spec.get("op")
        # 左辺を決める(HAVINGでは集約を許す)
        if allow_agg and "agg" in spec:
            if "col" in spec:
                raise WhereError("comparison cannot have both 'col' and 'agg'")
            if op is None:
                raise WhereError("comparison needs 'op'")
            left = _render_aggregate(spec["agg"], allowed_columns, allow_alias=False)
        else:
            col = spec.get("col")
            if col is None or op is None:
                raise WhereError("comparison needs 'col' and 'op'")
            if col not in allowed_columns:              # ★ 列名のホワイトリスト(最重要の防壁)
                raise WhereError(f"unknown column: {col!r}")
            left = col

        if op in _NULL_OPS:
            if "val" in spec:
                raise WhereError(f"operator {op} takes no 'val'")
            return cls(f"{left} {op}", [])

        if op in _BINARY_OPS:
            if "val" not in spec:
                raise WhereError(f"operator {op!r} needs 'val'")
            return cls(f"{left} {op} %s", [spec["val"]])   # 値はプレースホルダ

        if op in _LIST_OPS:
            vals = spec.get("val")
            if not isinstance(vals, list) or len(vals) == 0:
                raise WhereError(f"operator {op!r} needs a non-empty list 'val'")
            placeholders = ", ".join(["%s"] * len(vals))
            return cls(f"{left} {op} ({placeholders})", list(vals))

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


# ---- 集約(統計)関数 ----
def _render_aggregate(spec, allowed_columns, allow_alias=True):
    """集約1つ {"func","column","as"(任意)} を検証して "FUNC(col) AS alias" にする。
    エラーは WhereError を送出。allow_alias=False のとき別名は不可(HAVINGの左辺など)。"""
    if not isinstance(spec, dict):
        raise WhereError("aggregate must be an object")
    func = spec.get("func")
    if not func or not isinstance(func, str):
        raise WhereError("aggregate needs 'func'")
    func_up = func.upper()
    if func_up not in _AGGREGATES:
        raise WhereError(f"aggregate function not allowed: {func!r}")

    column = spec.get("column")
    if column == "*":                                   # COUNT(*) の特例
        if func_up != "COUNT":
            raise WhereError("'*' is only allowed with COUNT")
        inner = "*"
    else:
        if not column or not isinstance(column, str):
            raise WhereError(f"aggregate {func_up} needs 'column'")
        if column not in allowed_columns:
            raise WhereError(f"unknown column: {column!r}")
        inner = column

    frag = f"{func_up}({inner})"
    alias = spec.get("as")
    if alias is not None:
        if not allow_alias:
            raise WhereError("alias is not allowed here")
        if not _is_valid_identifier(alias):
            raise WhereError(f"invalid alias: {alias!r}")
        frag += f" AS {alias}"
    return frag


def build_select_columns(columns, allowed_columns):
    """取得する列(集約を含む)を SELECT 句の文字列にする。
      columns: None→"*" / 文字列→そのまま(後方互換) / リスト→検証して組み立て
        リストの要素: 文字列(列名, 実列と照合) または dict(集約)
      allowed_columns: 実テーブルの列名
    戻り値: (columns_sql, error)。error は成功時 None。"""
    if columns is None:
        return "*", None
    if isinstance(columns, str):
        return columns, None                            # 後方互換: 文字列はそのまま通す
    if not isinstance(columns, (list, tuple)) or len(columns) == 0:
        return None, "columns must be a non-empty list"

    allowed = set(allowed_columns)
    parts = []
    try:
        for item in columns:
            if isinstance(item, str):
                if item not in allowed:
                    return None, f"unknown column: {item!r}"
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(_render_aggregate(item, allowed, allow_alias=True))
            else:
                return None, "each column must be a name (str) or an aggregate (object)"
    except WhereError as e:
        return None, str(e)
    return ", ".join(parts), None


def build_having(spec, allowed_columns):
    """HAVING条件木 → (clause, params, error)。WHERE と同構造だが左辺に集約を許す。
    spec=None は HAVING なし。allowed_columns: 実テーブルの列名。"""
    if spec is None:
        return "", [], None
    try:
        node = Node.from_json(spec, set(allowed_columns), allow_agg=True)
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
        "having":   <条件ノード>,                          # build_having で検証(集約可)
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

    # having(条件木。左辺に集約を許す。通常 group_by と併用)
    if request.get("having") is not None:
        clause, params, err = build_having(request["having"], cols)
        if err:
            return _fail(f"having: {err}")
        qo["having"] = (clause, params)

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


# ---- UPDATE 用(SET 句と、主キーによる行の特定) ----
def build_set(assignments, allowed_columns, protected_columns=()):
    """SET の指定 {列名: 新しい値} → (clause, params, error)。DB_Manager.Update_Data の set_option になる。
      allowed_columns:   実テーブルの列名
      protected_columns: 書き換えを禁じる列(主キーなど)
    値はすべて %s に回す。値は単一の値(文字列・数値・真偽・None)だけ許す。"""
    if not isinstance(assignments, dict) or len(assignments) == 0:
        return None, None, "set must be a non-empty object"
    cols, protected = set(allowed_columns), set(protected_columns)
    parts, params = [], []
    for col, val in assignments.items():
        if col not in cols:                                 # ★ 列名のホワイトリスト
            return None, None, f"unknown column: {col!r}"
        if col in protected:
            return None, None, f"column {col!r} cannot be updated (primary key)"
        if isinstance(val, (dict, list)):                   # 式や入れ子を値として通さない
            return None, None, f"value for {col!r} must be a single value"
        parts.append(f"{col} = %s")
        params.append(val)
    return ", ".join(parts), params, None


def build_key_where(key, primary_keys, allowed_columns):
    """主キーの値 {主キー列: 値} → 1行を特定する WHERE の (clause, params, error)。
    複合主キーなら全列の指定が必要。条件木は Node で組み立てるので、検証は WHERE と同じ経路を通る。"""
    pks = list(primary_keys or [])
    if not pks:
        return None, None, "table has no primary key"
    if not isinstance(key, dict) or set(key.keys()) != set(pks):
        return None, None, f"key must specify exactly the primary key columns: {pks}"
    for k in pks:
        if key[k] is None or isinstance(key[k], (dict, list)):
            return None, None, f"key value for {k!r} must be a single non-null value"
    spec = {"and": [{"col": k, "op": "=", "val": key[k]} for k in pks]}
    return build_where(spec, allowed_columns)


def _fail_update(msg):
    return {"success": False, "set_option": None, "query_option": None, "error": msg}


def build_update(request, allowed_columns, primary_keys):
    """構造化リクエスト → Update_Data に渡す (set_option, query_option)(検証済み)。
    戻り値: {"success", "set_option", "query_option", "error"}

    request の形:
      {
        "set":   {"is_released": 1, "released_date": "2026-10-09"},  # 必須。主キー列は書き換え不可
        "key":   {"series_id": 3, "volume_number": 5},               # 主キーで1行を特定する、または
        "where": <条件ノード>                                         # 条件で複数行を対象にする
      }
    key と where はどちらか一方が必須(条件なしの全行更新はさせない)。"""
    if not isinstance(request, dict):
        return _fail_update("request must be an object")

    has_key, has_where = request.get("key") is not None, request.get("where") is not None
    if has_key == has_where:
        return _fail_update("specify exactly one of 'key' or 'where'")

    set_clause, set_params, err = build_set(request.get("set"), allowed_columns, primary_keys or [])
    if err:
        return _fail_update(f"set: {err}")

    if has_key:
        clause, params, err = build_key_where(request["key"], primary_keys, allowed_columns)
        label = "key"
    else:
        clause, params, err = build_where(request["where"], allowed_columns)
        label = "where"
    if err:
        return _fail_update(f"{label}: {err}")

    return {"success": True,
            "set_option": (set_clause, set_params),
            "query_option": {"where": (clause, params)},
            "error": None}