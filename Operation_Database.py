import mysql.connector as sqlconn
from mysql.connector import Error
import pandas as pd
import re
from WHERE_node import Node


class DB_Manager:                                   # データベースの基本操作を行うクラス
                                                    # connect / close 以外のメソッドは、すべて _execute を通して
                                                    # 共通の結果dict {success, data, rowcount, lastrowid, message, error} を返す。

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
                "message": "", "error": msg}

    def _execute(self, query, params=None, commit=False, fetch=False):
        # 全SQL実行の単一窓口。DB側の出力を構造化して返す。
        result = {"success": False, "data": None, "rowcount": 0, "lastrowid": None,
                  "message": "", "error": None}

        if self.connection is None or not self.connection.is_connected():
            result["error"] = "not connected"
            return result

        try:
            self.cursor.execute(query, params)
            if fetch:
                result["data"] = self.cursor.fetchall()
            result["rowcount"]  = self.cursor.rowcount      # 影響/取得行数
            result["lastrowid"] = self.cursor.lastrowid     # INSERTの採番id(他は0/None)
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
            return result

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

    def Get_Columns_Info(self):                     # 列メタデータ(型/NULL可否/キー等)。解釈はしない
        if self.DB_name is None:
            return self._fail("please select database")
        if self.table_name is None:
            return self._fail("table not selected")
        query = """
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
                   NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE,
                   COLUMN_KEY, COLUMN_DEFAULT, EXTRA
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """
        return self._execute(query, (self.DB_name, self.table_name), fetch=True)

    # ---- データ操作 --------------------------------------------------------
    # query_option = {
    #     "where":    (clause, params),   # ("age >= %s AND status = %s", [20, "active"])
    #     "group_by": "department",       # 文字列(値を持たない)
    #     "having":   (clause, params),   # ("COUNT(*) > %s", [5])  GROUP BY 使用時のみ
    # }
    def Select_Data(self, Columns="*", query_option=None):  # 条件付きでデータ取得
        if self.table_name is None:
            return self._fail("table not selected")

        query  = f"SELECT {Columns} FROM {self.table_name}"
        params = []
        if query_option:
            where = query_option.get("where")
            if where:
                query += f" WHERE {where[0]}"
                params += list(where[1]) if where[1] else []
            if query_option.get("group_by"):
                query += f" GROUP BY {query_option['group_by']}"
            having = query_option.get("having")
            if having:
                query += f" HAVING {having[0]}"
                params += list(having[1]) if having[1] else []

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

    def Delete_Data(self, query_option):            # 条件付き削除(操作完了時に実行+コミット)
        if self.table_name is None:
            return self._fail("table not selected")
        where = query_option.get("where") if query_option else None
        if not where or not where[0]:               # WHERE無しの全削除を防ぐガード
            return self._fail("please specify condition")

        params = tuple(where[1]) if where[1] else None
        sel = self._execute(f"SELECT * FROM {self.table_name} WHERE {where[0]}", params, fetch=True)        # 削除前に対象を確保=変更点
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

        all_params = (list(set_option[1]) if set_option[1] else []) + (list(where[1]) if where[1] else [])
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