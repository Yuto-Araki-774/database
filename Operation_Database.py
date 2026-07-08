import mysql.connector as sqlconn
from mysql.connector import Error
import pandas as pd
import re
from WHERE_node import Node


class DB_Manager:                                   # データベースの基本操作を行うクラス
    # connect / close 以外のメソッドは、すべて _execute を通して
    # 共通の結果dict {success, data, rowcount, lastrowid, message, error} を返す。

    _ALLOWED_JOINS = ("INNER", "LEFT")              # JOINで許可する結合の種類(ホワイトリスト)

    def __init__(self, DB_path):                    # DB_path...[host, user, passwd]
        self.connection   = None
        self.cursor       = None
        self.DB_name      = None
        self.table_name   = None
        self.columns      = None
        self.primary_keys = None
        self.connect(DB_path)

    # ---- 接続管理(ここだけは _execute を通さない) -------------------------
    def connect(self, DB_path):                     # サーバーへ接続する(DBはまだ選択しない)
        try:
            self.connection = sqlconn.connect(
                host   = DB_path[0],
                user   = DB_path[1],
                passwd = DB_path[2],
            )
            if self.connection.is_connected():
                print("MySQL Database connection successful")
                self.cursor = self.connection.cursor(dictionary=True)
        except Error as err:
            print(f"Connection error: {err}")

    def close(self):                                # コネクションを閉じる。作業終了時に必ず実行
        if self.connection is not None and self.connection.is_connected():
            self.cursor.close()
            self.connection.close()
            print("MySQL Database connection closed")

    # ---- 共通ユーティリティ ------------------------------------------------
    @staticmethod
    def _is_valid_name(name):                       # 識別子(DB名・テーブル名)の検証
        return bool(name) and re.fullmatch(r'\w+', name) is not None

    @staticmethod
    def _fail(msg):                                 # 実行前の失敗を結果dictと同じ形で返す
        return {"success": False, "data": None, "rowcount": 0, "lastrowid": None,
                "message": "", "error": msg, "errno": None, "sql": None}

    # ---- 表示用SQLの組み立て(★表示専用。実行には絶対に使わない) --------------
    @staticmethod
    def _format_sql_value(value):
        # 1つの値を、表示用のSQLリテラルに整形する。
        # None→NULL / 真偽→TRUE,FALSE / 数値→そのまま / それ以外→引用符で囲む。
        if value is None:
            return "NULL"
        if isinstance(value, bool):                 # bool は int より先に判定する
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"   # 文字列: ' を '' にして囲む

    @staticmethod
    def _fill_placeholders(query, params):
        # query 内の %s を、params の値(整形済み)で左から順に置き換える。
        # テンプレートは値にのみ %s を使い、識別子は直接埋め込む前提なので、%s 分割で安全。
        if not params:
            return query
        values = list(params)
        parts = query.split("%s")
        out = []
        i = 0
        for idx, part in enumerate(parts):
            out.append(part)
            if idx < len(parts) - 1:                # パーツの間に値を挿入
                if i < len(values):
                    out.append(DB_Manager._format_sql_value(values[i]))
                    i += 1
                else:
                    out.append("%s")               # 値が足りない(想定外)場合はそのまま
        return "".join(out)

    @staticmethod
    def _render_display_sql(query, params, many=False):
        # 実際に実行されるSQLを、値を埋め込んだ「見せる用」の文字列にする。
        # ★この文字列は実行に使わない。実行は _execute が %s + params で行う。
        if many:                                    # executemany: 先頭行を代表として見せ、行数を注記
            rows = list(params or [])
            if not rows:
                return query
            base = DB_Manager._fill_placeholders(query, rows[0])
            if len(rows) > 1:
                return f"{base}  -- ほか {len(rows) - 1} 行(計 {len(rows)} 行)"
            return base
        return DB_Manager._fill_placeholders(query, params)

    def _execute(self, query, params=None, commit=False, fetch=False, many=False):
        # 全SQL実行の単一窓口。DB側の出力を構造化して返す。
        # many=True のとき params は「行のlist」で、executemany により一括実行する。
        result = {"success": False, "data": None, "rowcount": 0, "lastrowid": None,
                  "message": "", "error": None, "errno": None,    # errno: MySQLエラー番号(成功時None)
                  "sql": None}                                    # sql: 表示専用の実行SQL(実行には使わない)

        result["sql"] = self._render_display_sql(query, params, many)  # 成否に関わらず入れる

        if self.connection is None or not self.connection.is_connected():
            result["error"] = "not connected"
            return result

        try:
            if many:
                self.cursor.executemany(query, params)      # 複数行を一括実行
            else:
                self.cursor.execute(query, params)
            if fetch:
                result["data"] = self.cursor.fetchall()
            result["rowcount"]  = self.cursor.rowcount      # 影響/取得行数
            result["lastrowid"] = self.cursor.lastrowid     # INSERTの採番id(複数行では先頭idで不確実)
            if commit:
                self.connection.commit()
            result["success"] = True
            return result
        except Error as err:
            if commit:
                try:
                    self.connection.rollback()              # 書き込み失敗時はロールバックして状態を汚さない
                except Error:
                    pass
            result["error"] = str(err)
            result["errno"] = getattr(err, "errno", None)   # 重複等の判定に使う(例: 1007/1050)
            return result

    # ---- 句の組み立て(WHERE 〜 LIMIT を共有。サブクエリもここで展開) -------
    def _render_clause(self, clause, subqueries):
        # clause = (template, params)。template には %s(値)と {name}(サブクエリ参照)が混在しうる。
        # subqueries = {name: 入れ子query_option} または None。
        # template を左から走査し、%s には外側paramsを、{name} には展開したサブクエリを順に当てる。
        # これにより %s の出現順とparamsの順が常に一致する。戻り値: (clause_str, params, error)
        template     = clause[0]
        outer_params = list(clause[1]) if clause[1] else []

        rendered = {}                               # name -> (sub_sql, sub_params)
        if subqueries:
            for name, opt in subqueries.items():
                sub_sql, sub_params, err = self._render_subquery(opt)
                if err:
                    return None, None, err
                rendered[name] = (sub_sql, sub_params)

        out_sql    = []
        out_params = []
        oi  = 0                                     # 外側paramsのインデックス
        pos = 0
        for m in re.finditer(r'%s|\{(\w+)\}', template):
            out_sql.append(template[pos:m.start()])
            if m.group(0) == "%s":                  # 値 → 外側paramsから1つ消費
                if oi >= len(outer_params):
                    return None, None, "clause: not enough params for placeholders"
                out_sql.append("%s")
                out_params.append(outer_params[oi])
                oi += 1
            else:                                   # {name} → サブクエリを括弧付きで埋め込む
                name = m.group(1)
                if name not in rendered:
                    return None, None, f"clause: unknown subquery '{name}'"
                sub_sql, sub_params = rendered[name]
                out_sql.append(f"({sub_sql})")
                out_params.extend(sub_params)       # サブクエリのparamsをその位置に挿入
            pos = m.end()
        out_sql.append(template[pos:])

        if oi != len(outer_params):                 # 余った外側params=指定ミス
            return None, None, "clause: too many params for placeholders"

        return "".join(out_sql), out_params, None

    def _render_subquery(self, opt):
        # 入れ子の query_option を SELECT 文字列に展開する。
        # 深さはここで構造的に制限する:サブクエリは自身に subqueries を持てない(=深さ3を禁止)。
        # 戻り値: (sql, params, error)
        if not opt:
            return None, None, "empty subquery"
        if opt.get("subqueries"):                   # サブクエリの中のサブクエリ → 深さ3
            return None, None, "subquery nesting too deep (max depth 2)"
        if opt.get("joins"):                        # サブクエリ内のJOINは未対応(明示的に弾く)
            return None, None, "joins inside subquery not supported"

        select = opt.get("select")
        if not select:                              # IN/比較で使う列(または集約)。生成側が検証
            return None, None, "subquery requires select"
        base = opt.get("from")
        if not self._is_valid_name(base):
            return None, None, "invalid subquery table"

        tail, params, err = self._build_tail(opt)   # where/group_by/having/order_by/limit を共有
        if err:
            return None, None, err
        return f"SELECT {select} FROM {base}{tail}", params, None

    def _build_tail(self, query_option):
        # WHERE / GROUP BY / HAVING / ORDER BY / LIMIT / OFFSET を組み立てる共通処理。
        # SELECT本体(と JOIN句)の後ろに付く部分を作る。Select_Data / Select_Join / サブクエリで共有。
        # 戻り値: (sql, params, error)  error は成功時 None
        sql, params = "", []
        if not query_option:
            return sql, params, None

        subqueries = query_option.get("subqueries")  # この階層のサブクエリ定義

        where = query_option.get("where")
        if where and where[0]:                        # 列は生成側が検証済み、値はプレースホルダ
            clause, p, err = self._render_clause(where, subqueries)
            if err:
                return None, None, err
            sql += f" WHERE {clause}"
            params += p

        if query_option.get("group_by"):             # 値を持たない文字列
            sql += f" GROUP BY {query_option['group_by']}"

        having = query_option.get("having")
        if having and having[0]:                      # GROUP BY 使用時のみ。サブクエリ参照も可
            clause, p, err = self._render_clause(having, subqueries)
            if err:
                return None, None, err
            sql += f" HAVING {clause}"
            params += p

        if query_option.get("order_by"):             # 列名+ASC/DESC。値を持たない文字列
            sql += f" ORDER BY {query_option['order_by']}"

        limit  = query_option.get("limit")
        offset = query_option.get("offset")
        if offset is not None and limit is None:     # OFFSET単独はMySQLで不可
            return None, None, "offset requires limit"
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                return None, None, "limit must be a non-negative integer"
            sql += " LIMIT %s"                        # 件数は値なのでプレースホルダ
            params.append(limit)
            if offset is not None:
                if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
                    return None, None, "offset must be a non-negative integer"
                sql += " OFFSET %s"
                params.append(offset)

        return sql, params, None

    # ---- データベース階層 --------------------------------------------------
    def Show_DataBase(self):                        # サーバー内のDB一覧
        res = self._execute("SHOW DATABASES", fetch=True)
        if res["success"]:
            res["data"] = [row["Database"] for row in res["data"]]
        return res

    def Create_DataBase(self, DB_name):             # DBを新規作成(切り替えはしない)
        if not self._is_valid_name(DB_name):
            return self._fail("invalid database name")
        res = self._execute(f"CREATE DATABASE {DB_name}")
        if res["success"]:
            res["message"] = f"database '{DB_name}' created"
        return res

    def Select_DataBase(self, DB_name):             # 操作対象のDBを選択する(USE)
        if not self._is_valid_name(DB_name):
            return self._fail("invalid database name")
        res = self._execute(f"USE {DB_name}")
        if res["success"]:
            self.DB_name      = DB_name
            self.table_name   = None                # DBを変えたらテーブル選択はリセット
            self.columns      = None
            self.primary_keys = None
            res["message"] = f"database '{DB_name}' selected"
        return res

    def Drop_DataBase(self, DB_name):               # DBを削除する(確認はフロント側で行う前提)
        # IF EXISTS は付けない:存在しないDBの削除は errno(1008)で顕在化させる(Create と対称)
        if not self._is_valid_name(DB_name):
            return self._fail("invalid database name")
        res = self._execute(f"DROP DATABASE {DB_name}")
        if res["success"]:
            if DB_name == self.DB_name:             # 選択中DBを消したら内部状態をリセット
                self.DB_name      = None
                self.table_name   = None
                self.columns      = None
                self.primary_keys = None
            res["message"] = f"database '{DB_name}' dropped"
        return res

    # ---- テーブル階層 ------------------------------------------------------
    def Show_Tables(self):                          # 選択中DB内のテーブル一覧
        if self.DB_name is None:
            return self._fail("please select database")
        res = self._execute("SHOW TABLES", fetch=True)
        if res["success"]:
            res["data"] = [list(row.values())[0] for row in res["data"]]
        return res

    def Create_Table(self, table_name, columns, primary_key="id"):  # テーブルを作る
        if not self._is_valid_name(table_name):
            return self._fail("invalid table name")
        if self.DB_name is None:
            return self._fail("please select database")

        query = f"CREATE TABLE {table_name} ("
        for column in columns:
            query += (f"{column['Column_Name']} {column['Data_Type']} "
                      f"{column.get('Key', '')} {column.get('Not_Null', '')} "
                      f"{column.get('Default', '')} {column.get('Extra', '')}, ")
        query += f"PRIMARY KEY ({primary_key}))"

        res = self._execute(query)
        if res["success"]:                          # 成功時のみ内部状態を更新
            self.table_name   = table_name
            self.columns      = [c["Column_Name"] for c in columns]
            self.primary_keys = [p.strip() for p in primary_key.split(",")]
            res["message"]    = f"table '{table_name}' created"
        return res

    def Drop_Table(self, table_name):               # テーブルを削除する(確認はフロント側で行う前提)
        # IF EXISTS は付けない:存在しないテーブルの削除は errno(1051)で顕在化させる
        if not self._is_valid_name(table_name):
            return self._fail("invalid table name")
        if self.DB_name is None:
            return self._fail("please select database")
        res = self._execute(f"DROP TABLE {table_name}")
        if res["success"]:
            if table_name == self.table_name:       # 選択中テーブルを消したら内部状態をリセット
                self.table_name   = None
                self.columns      = None
                self.primary_keys = None
            res["message"] = f"table '{table_name}' dropped"
        return res

    def Truncate_Table(self, table_name):           # 全行削除(構造は残す。確認はフロント側で行う前提)
        # TRUNCATE は暗黙コミットされ、ロールバックできない。だから確認はフロントで必ず通すこと。
        # Delete_Data は条件必須で全削除を禁じているので、意図的な全消去はこちらが正規の入口。
        # 構造は残るため、選択中テーブルを truncate しても内部状態(columns等)はリセットしない。
        if not self._is_valid_name(table_name):
            return self._fail("invalid table name")
        if self.DB_name is None:
            return self._fail("please select database")
        res = self._execute(f"TRUNCATE TABLE {table_name}")   # 存在しない場合は errno(1146)で返る
        if res["success"]:
            res["message"] = f"table '{table_name}' truncated"
        return res

    def Select_Table(self, table_name):             # テーブルを選択し、全行を返す
        if not self._is_valid_name(table_name):
            return self._fail("invalid table name")
        if self.DB_name is None:
            return self._fail("please select database")

        res = self._execute(f"SELECT * FROM {table_name}", fetch=True)
        if not res["success"]:
            return res

        self.table_name = table_name
        info = self.Get_Columns_Info()              # 列名(空テーブルでも確実に取れる)
        self.columns = [c["COLUMN_NAME"] for c in info["data"]] if info["success"] else None
        pk = self.Get_Primary_Key()                 # 主キー
        self.primary_keys = pk["data"] if pk["success"] else None
        return res

    def Get_Primary_Key(self):                      # 選択中テーブルの主キー列
        if self.table_name is None:
            return self._fail("table not selected")
        res = self._execute(
            f"SHOW KEYS FROM {self.table_name} WHERE Key_name = 'PRIMARY'", fetch=True)
        if res["success"]:
            res["data"] = [row["Column_name"] for row in res["data"]]
        return res

    def Get_Columns_Info(self, table_name=None):    # 列メタデータ(型/NULL可否/キー等)。解釈はしない
        # table_name 省略時は選択中テーブル。JOIN/サブクエリ相手の列集合を引くため明示テーブルも受ける。
        name = table_name if table_name is not None else self.table_name
        if self.DB_name is None:
            return self._fail("please select database")
        if name is None:
            return self._fail("table not selected")
        if not self._is_valid_name(name):
            return self._fail("invalid table name")
        query = """
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
                   NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE,
                   COLUMN_KEY, COLUMN_DEFAULT, EXTRA
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """
        return self._execute(query, (self.DB_name, name), fetch=True)

    # ---- データ操作 --------------------------------------------------------
    # 単一テーブル版 query_option:
    # query_option = {
    #     "where":    (clause, params),   # ("age >= %s AND status = %s", [20, "active"])
    #     "group_by": "department",       # 文字列(値を持たない)
    #     "having":   (clause, params),   # ("COUNT(*) > %s", [5])  GROUP BY 使用時のみ
    #     "order_by": "age DESC, name",   # 文字列(列名+ASC/DESC、値を持たない)
    #     "limit":    10,                 # 非負整数(%sで渡す)
    #     "offset":   20,                 # 非負整数。limit と併用時のみ
    #     "subqueries": {                 # 任意。where/having から {name} で参照する
    #         "sub1": {                   # 入れ子の query_option(深さ2まで=この中に subqueries 不可)
    #             "select": "id",         # サブクエリが返す列(IN は単一列、比較はスカラ/集約)
    #             "from":   "customers",
    #             "where":  ("city = %s", ["Tokyo"]),
    #         },
    #     },
    # }
    # 例: "where": ("customer_id IN {sub1} AND total >= %s", [100])  → IN (SELECT ...) に展開
    def Select_Data(self, Columns="*", query_option=None):  # 単一テーブルから取得
        if self.table_name is None:
            return self._fail("table not selected")

        tail, params, err = self._build_tail(query_option)
        if err:
            return self._fail(err)

        query = f"SELECT {Columns} FROM {self.table_name}{tail}"
        return self._execute(query, tuple(params) if params else None, fetch=True)

    # JOIN版 query_option(上の各キーに from / joins を追加。列はすべて修飾必須):
    # query_option = {
    #     "from":  "orders",                                  # 基点テーブル(識別子)
    #     "joins": [                                           # 上から順に結合(空でJOINなし)
    #         {"type": "INNER", "table": "customers",
    #          "on": "orders.customer_id = customers.id"},     # on は列=列の構造(値を持たない)
    #     ],
    #     "where":    ("orders.total >= %s", [100]),           # 列は orders.x / customers.x
    #     "order_by": "customers.name ASC",
    #     # group_by / having / limit / offset / subqueries も従来どおり
    # }
    def Select_Join(self, Columns, query_option):   # 複数テーブルを結合して取得(読み取り専用)
        if query_option is None:
            return self._fail("query_option required")
        if not Columns:                             # JOINでは修飾付きの列指定が必須("*"は避ける)
            return self._fail("columns required for join")

        base = query_option.get("from")
        if not self._is_valid_name(base):           # 基点テーブル名(直接埋め込むので検証)
            return self._fail("invalid base table")

        query = f"SELECT {Columns} FROM {base}"

        for j in query_option.get("joins", []):     # 結合句を順に組み立て
            jtype = (j.get("type") or "").upper()
            if jtype not in self._ALLOWED_JOINS:    # 種類はホワイトリストで縛る
                return self._fail(f"join type not allowed: {j.get('type')}")
            jtable = j.get("table")
            if not self._is_valid_name(jtable):     # 結合相手のテーブル名も検証
                return self._fail("invalid join table")
            on = j.get("on")
            if not on:                              # ON無しの結合(意図しない直積)を防ぐ
                return self._fail("join requires on condition")
            query += f" {jtype} JOIN {jtable} ON {on}"   # on の列名は生成側が検証済み

        tail, params, err = self._build_tail(query_option)   # WHERE〜LIMIT(サブクエリ含む)は共通
        if err:
            return self._fail(err)

        query += tail
        return self._execute(query, tuple(params) if params else None, fetch=True)

    def Insert_Data(self, data):                    # 1行挿入(操作完了時に実行+コミット)
        if self.table_name is None or self.columns is None:
            return self._fail("table not selected")
        if len(data) != len(self.columns):
            return self._fail("data length does not match column length")

        query = (f"INSERT INTO {self.table_name} ({', '.join(self.columns)}) "
                 f"VALUES ({', '.join(['%s'] * len(self.columns))})")
        res = self._execute(query, tuple(data), commit=True)
        if res["success"]:
            res["data"]    = [dict(zip(self.columns, data))]   # 変更点=挿入した行
            res["message"] = "inserted"                        # 採番idは res["lastrowid"]
        return res

    def Insert_Many(self, data_rows):               # 複数行を一括挿入(executemany)
        # data_rows は「行のlist」: [[None, "Alice"], [None, "Bob"], ...]
        # 全行が1トランザクション。1行でも失敗すれば全行ロールバックされる。
        if self.table_name is None or self.columns is None:
            return self._fail("table not selected")
        if not isinstance(data_rows, (list, tuple)) or len(data_rows) == 0:
            return self._fail("data_rows must be a non-empty list of rows")

        n = len(self.columns)
        for i, row in enumerate(data_rows):         # 全行を事前検証(1行でも崩れると全体が失敗するため)
            if not isinstance(row, (list, tuple)):
                return self._fail(f"row {i}: each row must be a list/tuple")
            if len(row) != n:
                return self._fail(f"row {i}: data length does not match column length ({len(row)} != {n})")

        query = (f"INSERT INTO {self.table_name} ({', '.join(self.columns)}) "
                 f"VALUES ({', '.join(['%s'] * n)})")
        params = [tuple(row) for row in data_rows]  # executemany 用の行のlist
        res = self._execute(query, params, commit=True, many=True)
        if res["success"]:
            res["data"]    = [dict(zip(self.columns, row)) for row in data_rows]  # 挿入した行
            res["message"] = f"{len(data_rows)} rows inserted"
        return res

    def Delete_Data(self, query_option):            # 条件付き削除(操作完了時に実行+コミット)
        if self.table_name is None:
            return self._fail("table not selected")
        where = query_option.get("where") if query_option else None
        if not where or not where[0]:               # WHERE無しの全削除を防ぐガード
            return self._fail("please specify condition")

        params = tuple(where[1]) if where[1] else None
        sel = self._execute(f"SELECT * FROM {self.table_name} WHERE {where[0]}",
                            params, fetch=True)        # 削除前に対象を確保=変更点
        if not sel["success"]:
            return sel

        res = self._execute(f"DELETE FROM {self.table_name} WHERE {where[0]}",
                           params, commit=True)
        if res["success"]:
            res["data"]    = sel["data"]               # 削除した行
            res["message"] = "deleted"
        return res

    def Update_Data(self, set_option, query_option):  # 条件付き更新(操作完了時に実行+コミット)
        # set_option = ("name = %s, age = %s", ["Tanaka", 30])   SET の (構造, 値)
        if self.table_name is None:
            return self._fail("table not selected")
        where = query_option.get("where") if query_option else None
        if not where or not where[0]:               # 全行更新を防ぐガード
            return self._fail("please specify condition")

        where_params = tuple(where[1]) if where[1] else None
        pk = self.primary_keys[0] if self.primary_keys else None   # 単一PK前提の簡易版

        before = self._execute(f"SELECT * FROM {self.table_name} WHERE {where[0]}",
                               where_params, fetch=True)            # 更新前
        if not before["success"]:
            return before

        all_params = (list(set_option[1]) if set_option[1] else []) + \
                     (list(where[1]) if where[1] else [])
        res = self._execute(f"UPDATE {self.table_name} SET {set_option[0]} WHERE {where[0]}",
                           tuple(all_params), commit=True)
        if not res["success"]:
            return res

        after = before["data"]
        if pk and before["data"]:                   # 条件列が変わっても拾えるようPKで取り直す
            ids = [row[pk] for row in before["data"]]
            ph  = ", ".join(["%s"] * len(ids))
            a = self._execute(f"SELECT * FROM {self.table_name} WHERE {pk} IN ({ph})",
                             tuple(ids), fetch=True)                # 更新後
            if a["success"]:
                after = a["data"]

        res["data"]    = {"before": before["data"], "after": after}
        res["message"] = "updated"
        return res