"""
DB学習アプリ API サーバー (Phase 1 + Phase 2 フロント配信)
  既存の DB_Manager(DB操作)と WHERE_node(JSON検証)を、HTTP から呼べるようにする入口。
  Phase 2 で、フロント(frontend/index.html)を同じサーバーから配信するようにした(8.5)。

  - 認証は【仮実装】(固定トークン)。Phase 3 でパスキー(WebAuthn)に置き換える。
  - 役割(admin / user)で認可。破壊的操作(Truncate / Drop)は admin のみ。
  - MySQL 接続情報はサーバー側で持つ(クライアントからは受け取らない)。
  - リクエストごとに DB_Manager を1つ用意する(利用者間で状態が混ざらないように)。

起動:
  uvicorn server:app --reload
  → ブラウザで http://127.0.0.1:8000/ を開くとテーブルビューアが表示される。
動作確認(API 単体、例):
  curl -H "Authorization: Bearer user-token-demo" http://127.0.0.1:8000/databases

注意: これは localhost / HTTP 前提。インターネット公開には TLS と本物の認証が必須。
"""
import os
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from Operation_Database import DB_Manager
from WHERE_node import build_query_option, build_update

app = FastAPI(title="DB Learning App API", version="0.1 (Phase 1)")


# ---- MySQL 接続情報(サーバー側の設定。利用者からは受け取らない) ----
def _load_db_credentials() -> List[str]:
    # 本番は環境変数等から読むのが望ましい。ここでは既存の p/key.txt(host/user/passwd)を流用。
    path = os.path.join(os.path.dirname(__file__), "p", "key.txt")
    with open(path, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f]
    if len(lines) < 2 or not lines[0] or not lines[1]:
        raise RuntimeError("p/key.txt must have host / user / passwd")
    return [lines[0], lines[1], lines[2] if len(lines) > 2 else ""]


# ---- DB_Manager をリクエストごとに用意する依存 ----
def get_db():
    # 1リクエスト = 1接続。状態(選択中DB/テーブル)が他の利用者と混ざらない。
    # 注意: 毎回接続するので効率は良くない。将来はコネクションプールに置き換える。
    db = DB_Manager(_load_db_credentials())
    try:
        if db.connection is None or not db.connection.is_connected():
            raise HTTPException(status_code=503, detail="database connection failed")
        yield db
    finally:
        db.close()


# ---- 認証(★仮実装。Phase 3 でパスキーに置き換える) ----
# 固定トークン → 利用者。【ローカル開発専用】。本番では絶対に使わないこと。
_STUB_TOKENS = {
    "admin-token-demo": {"username": "admin", "role": "admin"},
    "user-token-demo":  {"username": "alice", "role": "user"},
}


def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    # 認証情報は本文ではなく Authorization ヘッダーで受け取る(Bearer トークン)。
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed token")
    token = authorization[len("Bearer "):]
    user = _STUB_TOKENS.get(token)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid token")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    # 破壊的操作のエンドポイントに付ける。admin 以外は 403。
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


# ---- 共通処理 ----
def _respond(result: dict):
    # DB_Manager の結果dict を HTTP 応答に変換する。
    if result["success"]:
        return {
            "success": True,
            "data": result["data"],
            "rowcount": result["rowcount"],
            "message": result["message"],
            "sql": result.get("sql"),          # 表示用SQL。フロントが表示/非表示を選ぶ
        }
    # 失敗: 検証 / 事前条件エラーは 400 で返す。
    # (本番ではエラー詳細を絞り、DB内部情報を晒さないようにする)
    raise HTTPException(status_code=400, detail=result["error"])


def _use_table(db: DB_Manager, db_name: str, table: str) -> List[str]:
    # DB を選択し、テーブルの列名一覧を得て、操作の前提(table_name / columns / primary_keys)を整える。
    # 全行を取得せず列だけ得るため Get_Columns_Info を使う。
    sel = db.Select_DataBase(db_name)
    if not sel["success"]:
        raise HTTPException(status_code=404, detail=sel["error"])
    info = db.Get_Columns_Info(table)        # table 名はここで _is_valid_name 検証される
    if not info["success"]:
        raise HTTPException(status_code=400, detail=info["error"])
    cols = [c["COLUMN_NAME"] for c in info["data"]]
    if not cols:
        raise HTTPException(status_code=404, detail=f"table not found: {table}")
    db.table_name = table                    # 検証済みの名前。Select_Data / Insert_* が使う
    db.columns = cols
    # 主キー列(Update_Data の更新後の取り直しと、build_update の主キー保護に使う)。
    # 列情報に含まれる COLUMN_KEY から取るので、追加のクエリは要らない。
    db.primary_keys = [c["COLUMN_NAME"] for c in info["data"] if c.get("COLUMN_KEY") == "PRI"]
    return cols


# ---- リクエスト本文のモデル(FastAPI が形を自動検証する) ----
class SelectRequest(BaseModel):
    columns: Optional[List[str]] = None      # 取得する列。None なら全列(*)
    query: Optional[dict] = None             # where/order_by/group_by/limit などの構造化条件


MAX_INSERT_ROWS = 1000                       # 1回の挿入で受け付ける最大行数


class InsertRequest(BaseModel):
    rows: List[List[Any]]                    # 行のリスト(各行は列順の値)


class UpdateRequest(BaseModel):
    # 例: {"set": {"is_released": 1}, "key": {"series_id": 3, "volume_number": 5}}
    set: dict                                # {列名: 新しい値}。主キー列は不可(WHERE_node が弾く)
    key: Optional[dict] = None               # 主キーで1行を特定する
    where: Optional[dict] = None             # または条件ノードで複数行(key とどちらか一方)


# ========================= 読み取り(認証済みなら誰でも) =========================
@app.get("/databases")
def list_databases(user: dict = Depends(get_current_user),
                   db: DB_Manager = Depends(get_db)):
    return _respond(db.Show_DataBase())


@app.get("/databases/{db_name}/tables")
def list_tables(db_name: str,
                user: dict = Depends(get_current_user),
                db: DB_Manager = Depends(get_db)):
    sel = db.Select_DataBase(db_name)
    if not sel["success"]:
        raise HTTPException(status_code=404, detail=sel["error"])
    return _respond(db.Show_Tables())


@app.get("/databases/{db_name}/tables/{table}/columns")
def get_columns(db_name: str, table: str,
                user: dict = Depends(get_current_user),
                db: DB_Manager = Depends(get_db)):
    sel = db.Select_DataBase(db_name)
    if not sel["success"]:
        raise HTTPException(status_code=404, detail=sel["error"])
    return _respond(db.Get_Columns_Info(table))


@app.post("/databases/{db_name}/tables/{table}/select")
def select_data(db_name: str, table: str, body: SelectRequest,
                user: dict = Depends(get_current_user),
                db: DB_Manager = Depends(get_db)):
    allowed = _use_table(db, db_name, table)

    # 取得する列も検証する(SELECT 句に入るため、未知の列は弾く)
    if body.columns is None:
        columns_sql = "*"
    else:
        for c in body.columns:
            if c not in allowed:
                raise HTTPException(status_code=400, detail=f"unknown column: {c}")
        columns_sql = ", ".join(body.columns)

    # 条件JSON を WHERE_node で検証して query_option に変換する(ここが防壁)
    built = build_query_option(body.query, allowed)
    if not built["success"]:
        raise HTTPException(status_code=400, detail=built["error"])

    return _respond(db.Select_Data(columns_sql, built["query_option"]))


# ========================= 書き込み(認証済みなら誰でも) =========================
@app.post("/databases/{db_name}/tables/{table}/rows")
def insert_rows(db_name: str, table: str, body: InsertRequest,
                user: dict = Depends(get_current_user),
                db: DB_Manager = Depends(get_db)):
    cols = _use_table(db, db_name, table)
    if not body.rows:
        raise HTTPException(status_code=400, detail="rows must not be empty")
    # 一括挿入の上限。全行が1トランザクションなので、大きすぎる要求はここで止める。
    if len(body.rows) > MAX_INSERT_ROWS:
        raise HTTPException(status_code=400,
                            detail=f"too many rows: {len(body.rows)} (max {MAX_INSERT_ROWS})")
    # 列数の不一致は、DB に投げる前に「何行目か」を付けて返す(GUI で直しやすくするため)
    for i, row in enumerate(body.rows, start=1):
        if len(row) != len(cols):
            raise HTTPException(status_code=400,
                                detail=f"row {i}: expected {len(cols)} values, got {len(row)}")
    if len(body.rows) == 1:
        return _respond(db.Insert_Data(body.rows[0]))    # 1行(採番idは lastrowid に入る)
    return _respond(db.Insert_Many(body.rows))           # 複数行(全行1トランザクション)


@app.patch("/databases/{db_name}/tables/{table}/rows")
def update_rows(db_name: str, table: str, body: UpdateRequest,
                user: dict = Depends(get_current_user),
                db: DB_Manager = Depends(get_db)):
    # 権限は insert と同じく「認証済みなら誰でも」。8.2 の役割(閲覧者/編集者/管理者)を
    # 入れる段階で、insert と一緒に「編集者以上」に絞る。
    cols = _use_table(db, db_name, table)

    # SET / WHERE を WHERE_node で検証して組み立てる(ここが防壁)。
    # 列名の照合・主キー列の書き換え禁止・条件必須(key か where)はすべてここで判定する。
    built = build_update({"set": body.set, "key": body.key, "where": body.where},
                         cols, db.primary_keys)
    if not built["success"]:
        raise HTTPException(status_code=400, detail=built["error"])

    res = db.Update_Data(built["set_option"], built["query_option"])

    # 主キー指定なのに対象が無い = 画面を開いた後に誰かが削除した(一往復モデルでは起こりうる)。
    # このとき UPDATE は 0 行に対して実行されるだけなので、DB は変わっていない。
    if res["success"] and body.key is not None and not res["data"]["before"]:
        raise HTTPException(status_code=404,
                            detail="row not found (it may have been deleted by someone else)")
    return _respond(res)


# ========================= 破壊的操作(admin のみ) =========================
@app.post("/databases/{db_name}/tables/{table}/truncate")
def truncate_table(db_name: str, table: str,
                   user: dict = Depends(require_admin),
                   db: DB_Manager = Depends(get_db)):
    sel = db.Select_DataBase(db_name)
    if not sel["success"]:
        raise HTTPException(status_code=404, detail=sel["error"])
    return _respond(db.Truncate_Table(table))


@app.delete("/databases/{db_name}/tables/{table}")
def drop_table(db_name: str, table: str,
               user: dict = Depends(require_admin),
               db: DB_Manager = Depends(get_db)):
    sel = db.Select_DataBase(db_name)
    if not sel["success"]:
        raise HTTPException(status_code=404, detail=sel["error"])
    return _respond(db.Drop_Table(table))


# ========================= フロント配信(Phase 2) =========================
# 8.5 の決定に従い、フロント(HTML/CSS/JS)を同じ FastAPI から配信する(同一オリジン)。
# ★ API ルートより後に mount することで、/databases 等の API が先に一致し、
#    残り("/" など)を StaticFiles が拾って index.html を返す。
# check_dir=False: frontend ディレクトリが無くても起動時に失敗しない。
_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
app.mount("/", StaticFiles(directory=_frontend_dir, html=True, check_dir=False), name="frontend")