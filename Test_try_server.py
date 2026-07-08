"""
server.py (Phase 1) のテスト。
  DB_Manager をスタブに差し替え(MySQL不要)、WHERE_node は本物のまま使う。
  確認: ルーティング / 認証(401)/ 役割(403・200)/ WHERE_node 検証(400)/ 列検証。
  → このファイルは DB なしでそのまま実行できる。
実行: python3 test_server.py
"""
import sys
import types

# ---- server が import する mysql.connector / pandas をスタブ化(本物・接続は不要) ----
class _Err(Exception):
    def __init__(self, msg="", errno=None):
        super().__init__(msg); self.errno = errno

_mc = types.ModuleType("mysql.connector")
_mc.Error = _Err
_mc.connect = lambda **kw: None
_m = types.ModuleType("mysql"); _m.connector = _mc
sys.modules["mysql"] = _m
sys.modules["mysql.connector"] = _mc
sys.modules["pandas"] = types.ModuleType("pandas")

from fastapi.testclient import TestClient
import try_server
from try_server import app, get_db


def _result(data=None, rowcount=0, lastrowid=None, message="ok",
            success=True, error=None, errno=None):
    return {"success": success, "data": data, "rowcount": rowcount,
            "lastrowid": lastrowid, "message": message, "error": error, "errno": errno}


class StubDB:
    COLS = ["id", "name", "age", "status"]

    def __init__(self):
        self.calls = []
        self.DB_name = None
        self.table_name = None
        self.columns = None

    def Show_DataBase(self):
        self.calls.append(("Show_DataBase",))
        return _result(data=["shop", "blog"])

    def Select_DataBase(self, name):
        self.calls.append(("Select_DataBase", name)); self.DB_name = name
        return _result(message=f"db {name} selected")

    def Show_Tables(self):
        self.calls.append(("Show_Tables",))
        return _result(data=["members", "orders"])

    def Get_Columns_Info(self, table=None):
        self.calls.append(("Get_Columns_Info", table))
        return _result(data=[{"COLUMN_NAME": c, "DATA_TYPE": "int"} for c in self.COLS])

    def Select_Data(self, columns="*", query_option=None):
        self.calls.append(("Select_Data", columns, query_option))
        return _result(data=[{"id": 1, "name": "a"}], rowcount=1)

    def Insert_Data(self, data):
        self.calls.append(("Insert_Data", data))
        return _result(data=[dict(zip(self.columns or self.COLS, data))],
                       rowcount=1, lastrowid=1, message="inserted")

    def Insert_Many(self, rows):
        self.calls.append(("Insert_Many", rows))
        return _result(data=[dict(zip(self.columns or self.COLS, r)) for r in rows],
                       rowcount=len(rows), message=f"{len(rows)} rows inserted")

    def Truncate_Table(self, table):
        self.calls.append(("Truncate_Table", table))
        return _result(message=f"table '{table}' truncated")

    def Drop_Table(self, table):
        self.calls.append(("Drop_Table", table))
        return _result(message=f"table '{table}' dropped")

    def close(self):
        self.calls.append(("close",))


stub = StubDB()
def override_get_db():
    yield stub
app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)
ADMIN = {"Authorization": "Bearer admin-token-demo"}
USER  = {"Authorization": "Bearer user-token-demo"}

_passed = 0
_failed = 0
def check(label, cond, detail=""):
    global _passed, _failed
    if cond: _passed += 1; print(f"[OK ] {label}")
    else:    _failed += 1; print(f"[NG ] {label}  -> {detail}")


print("\n===== 認証 =====")
r = client.get("/databases")
check("認証なしは 401", r.status_code == 401, r.status_code)
r = client.get("/databases", headers={"Authorization": "Bearer nope"})
check("不正トークンは 401", r.status_code == 401, r.status_code)

print("\n===== 読み取り =====")
r = client.get("/databases", headers=USER)
check("user で /databases は 200", r.status_code == 200, r.status_code)
check("DB一覧が返る", r.json().get("data") == ["shop", "blog"], r.text)
r = client.get("/databases/shop/tables", headers=USER)
check("テーブル一覧は 200", r.status_code == 200, r.status_code)
check("テーブル一覧が返る", r.json().get("data") == ["members", "orders"], r.text)
r = client.get("/databases/shop/tables/members/columns", headers=USER)
check("列情報は 200", r.status_code == 200, r.status_code)

print("\n===== select + WHERE_node =====")
stub.calls.clear()
r = client.post("/databases/shop/tables/members/select", headers=USER,
                json={"query": {"where": {"col": "age", "op": ">=", "val": 20}}})
check("select は 200", r.status_code == 200, r.text)
sd = [c for c in stub.calls if c[0] == "Select_Data"]
check("Select_Data に where=(\"age >= %s\",[20]) が渡る",
      bool(sd) and sd[-1][2] is not None and sd[-1][2].get("where") == ("age >= %s", [20]),
      str(sd))

r = client.post("/databases/shop/tables/members/select", headers=USER,
                json={"query": {"where": {"col": "salary", "op": "=", "val": 1}}})
check("未知列の where は 400", r.status_code == 400, r.status_code)

stub.calls.clear()
r = client.post("/databases/shop/tables/members/select", headers=USER,
                json={"columns": ["id", "name"]})
check("columns 指定は 200", r.status_code == 200, r.text)
sd = [c for c in stub.calls if c[0] == "Select_Data"]
check("Select_Data の列が 'id, name'", bool(sd) and sd[-1][1] == "id, name", str(sd))

r = client.post("/databases/shop/tables/members/select", headers=USER,
                json={"columns": ["id", "secret"]})
check("未知の columns は 400", r.status_code == 400, r.status_code)

print("\n===== insert =====")
stub.calls.clear()
r = client.post("/databases/shop/tables/members/rows", headers=USER,
                json={"rows": [[None, "Alice", 20, "active"]]})
check("insert 1行は 200", r.status_code == 200, r.text)
check("Insert_Data が呼ばれる", any(c[0] == "Insert_Data" for c in stub.calls), str(stub.calls))

stub.calls.clear()
r = client.post("/databases/shop/tables/members/rows", headers=USER,
                json={"rows": [[None, "A", 1, "x"], [None, "B", 2, "y"]]})
check("insert 複数行は 200", r.status_code == 200, r.text)
check("Insert_Many が呼ばれる", any(c[0] == "Insert_Many" for c in stub.calls), str(stub.calls))

print("\n===== 破壊的操作の役割チェック =====")
r = client.post("/databases/shop/tables/members/truncate", headers=USER)
check("user の truncate は 403", r.status_code == 403, r.status_code)
r = client.post("/databases/shop/tables/members/truncate", headers=ADMIN)
check("admin の truncate は 200", r.status_code == 200, r.text)
r = client.post("/databases/shop/tables/members/truncate")
check("認証なしの truncate は 401", r.status_code == 401, r.status_code)

r = client.delete("/databases/shop/tables/members", headers=USER)
check("user の drop table は 403", r.status_code == 403, r.status_code)
r = client.delete("/databases/shop/tables/members", headers=ADMIN)
check("admin の drop table は 200", r.status_code == 200, r.text)

print(f"\nRESULT: {_passed} passed, {_failed} failed")
sys.exit(0 if _failed == 0 else 1)