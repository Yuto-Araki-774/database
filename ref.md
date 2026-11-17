# DB_Manager 実装済み機能一覧

対象ファイル: `Operation_Database.py`（クラス `DB_Manager`）
このファイルは「クラスとして実装済みの機能」の一覧。すべてテスト済み（実行できるテストで検証、または実MySQL用テストを用意済み）。

**共通の戻り値**: `connect` / `close` を除く全メソッドは、次の形の結果dictを返す。
`{success: bool, data, rowcount: int, lastrowid, message: str, error, errno, sql}`
（`errno` = MySQLエラー番号／成功時 None、`sql` = 表示用の実行SQL。以下の表では戻り値の「特記事項」だけ記す）

> 注: 破壊的操作（Drop / Truncate）の「本当に削除するか」の確認はフロント側の責任。クラスは実行のみ行う。

---

## 接続管理
`_execute` を通さない唯一の例外。結果dictではなく print で成否を報告する。

| メソッド | 機能 | 主な引数 | 特記事項 |
|---|---|---|---|
| `connect(DB_path)` | サーバーへ接続（DBはまだ選択しない） | `[host, user, passwd]` | `self.connection` / `self.cursor` を設定。`__init__` から自動で呼ばれる |
| `close()` | コネクションを閉じる | なし | 作業終了時に必ず実行 |

---

## DB階層

| メソッド | 機能 | 主な引数 | 特記事項 |
|---|---|---|---|
| `Show_DataBase()` | サーバー内のDB一覧 | なし | `data` = DB名の文字列リスト |
| `Create_DataBase(DB_name)` | DBを新規作成 | DB名 | 切り替えはしない。`IF NOT EXISTS` は付けない → 重複は `errno 1007` |
| `Select_DataBase(DB_name)` | 操作対象DBを選択（USE） | DB名 | 成功で `DB_name` 設定。テーブル選択状態はリセット |
| `Drop_DataBase(DB_name)` | DBを削除 | DB名 | 破壊的。存在しないと `errno 1008`。選択中DBを消すと内部状態をリセット |

---

## テーブル階層

| メソッド | 機能 | 主な引数 | 特記事項 |
|---|---|---|---|
| `Show_Tables()` | 選択中DB内のテーブル一覧 | なし | DB選択が前提。`data` = テーブル名リスト |
| `Create_Table(table_name, columns, primary_key="id")` | テーブルを作成 | テーブル名 / 列定義リスト / 主キー | 成功で内部状態（table_name / columns / primary_keys）を更新。重複は `errno 1050` |
| `Drop_Table(table_name)` | テーブルを削除 | テーブル名 | 破壊的。DB選択が前提。存在しないと `errno 1051`。選択中テーブルを消すと状態リセット |
| `Truncate_Table(table_name)` | 全行削除（構造は残す） | テーブル名 | 破壊的。**暗黙コミットでロールバック不可**。AUTO_INCREMENT はリセット。構造・内部状態は保持。存在しないと `errno 1146` |
| `Select_Table(table_name)` | テーブルを選択し全行を返す | テーブル名 | `self.columns` / `self.primary_keys` を設定。`data` = 全行 |
| `Get_Primary_Key()` | 選択中テーブルの主キー列 | なし | `data` = 主キー列名 |
| `Get_Columns_Info(table_name=None)` | 列メタデータ（型 / NULL可否 / キー等） | テーブル名（省略時は選択中） | 検証・入力ルール用。キーは `COLUMN_NAME` / `DATA_TYPE` 等 |

---

## データ操作

| メソッド | 機能 | 主な引数 | 特記事項 |
|---|---|---|---|
| `Select_Data(Columns="*", query_option=None)` | 単一テーブルから取得 | 取得列 / `query_option` | `Columns` は文字列(後方互換)またはリスト(集約対応)。`query_option` で where / group_by / having / order_by / limit / offset / subqueries に対応。サブクエリのネストは深さ2まで。`data` = 行リスト |
| `build_select_columns(columns, allowed_columns)` | 取得列(集約含む)を検証して SELECT 句の文字列にする | 構造化指定 / 実列 | **`WHERE_node` の関数**（`DB_Manager` は呼ぶだけ）。`None`→`*`／文字列→そのまま／リスト→検証。下の「集約の指定」を参照 |
| `Select_Join(Columns, query_option)` | 複数テーブルを結合して取得 | 取得列 / `query_option`（from・joins を含む） | **読み取り専用**。結合は **INNER / LEFT のみ**。列は修飾必須（`orders.id`）、ON 必須。テーブル数に上限なし（ただし2テーブルまでテスト済、3以上は未検証） |
| `Insert_Data(data)` | 1行挿入（実行＋コミット） | `self.columns` 順の値リスト | `data` = 挿入した行、`lastrowid` = 採番id |
| `Insert_Many(data_rows)` | 複数行を一括挿入（executemany） | 行のリスト（各行は列順の値） | 全行を事前検証。**全行が1トランザクション**（1行でも失敗すれば全行ロールバック） |
| `Delete_Data(query_option)` | 条件付き削除（実行＋コミット） | `query_option` | **条件必須**（空WHEREは拒否＝全削除禁止）。`data` = 削除した行（削除前にSELECT） |
| `Update_Data(set_option, query_option)` | 条件付き更新（実行＋コミット） | `set_option`（SET句とparams）/ `query_option` | **条件必須**。`data` = `{before, after}`（after は主キーで再取得） |

---

## 集約（統計）関数の指定
`Select_Data` の `Columns` に**リスト**を渡すと、集約関数を使える（文字列で渡す従来の呼び方も引き続き有効）。
**検証・組み立ては `WHERE_node`（`build_select_columns` / `_render_aggregate`）に一元化**。`DB_Manager` はそれを呼ぶだけ。

**許可する関数（ホワイトリスト）**: `COUNT` / `SUM` / `AVG` / `MAX` / `MIN` / `STDDEV` / `VARIANCE` の7つ。（`WHERE_node._AGGREGATES`）

**リストの各要素**:
- 文字列 … 普通の列名（実列と照合）。例: `"dept"`
- オブジェクト … 集約。`{"func": 関数名, "column": 対象列, "as": 別名（任意）}`

**例**:
| 指定 | 生成されるSQL断片 |
|---|---|
| `{"func": "SUM", "column": "price", "as": "total"}` | `SUM(price) AS total` |
| `{"func": "COUNT", "column": "*"}` | `COUNT(*)` |
| `["dept", {"func": "COUNT", "column": "*", "as": "cnt"}]` | `dept, COUNT(*) AS cnt` |

```python
# 部署ごとの人数
db.Select_Data(["dept", {"func": "COUNT", "column": "*", "as": "cnt"}], {"group_by": "dept"})
# → SELECT dept, COUNT(*) AS cnt FROM members GROUP BY dept
```

**検証**: 関数名はホワイトリスト照合、対象列は実列と照合（`COUNT(*)` のみ `*` を特例で許可、他関数の `*` は拒否）、別名は識別子（`\w+`）として検証。`func` / `column` の欠落、未知の列・関数はエラー。GROUP BY は必須ではない（集約のみなら全体の集約が1行返る）。

## HAVING（集約結果での絞り込み）
`query_option` の `having` に条件ノードを渡す。**検証は `WHERE_node`（`build_having`）**。通常は GROUP BY と併用。
WHERE と同じ構造だが、比較ノードの左辺に**集約**を書ける（GROUP BY した列も可）。値は `%s` プレースホルダ。

| 指定（条件ノード） | 生成される HAVING |
|---|---|
| `{"agg": {"func": "COUNT", "column": "*"}, "op": ">=", "val": 10}` | `COUNT(*) >= %s`（params: `[10]`） |
| `{"col": "dept", "op": "=", "val": "sales"}` | `dept = %s`（GROUP BY 列を左辺に） |
| `{"and": [ {"agg":{"func":"COUNT","column":"*"},"op":">=","val":5}, {"agg":{"func":"AVG","column":"price"},"op":"<","val":1000} ]}` | `(COUNT(*) >= %s AND AVG(price) < %s)` |

```python
# 件数が5以上の部署だけ（build_query_option で検証してから渡す）
req = {"group_by": ["dept"],
       "having": {"agg": {"func": "COUNT", "column": "*"}, "op": ">=", "val": 5}}
qo = build_query_option(req, allowed_columns)["query_option"]
db.Select_Data(["dept", {"func": "COUNT", "column": "*", "as": "cnt"}], qo)
# → SELECT dept, COUNT(*) AS cnt FROM members GROUP BY dept HAVING COUNT(*) >= %s
```

AND/OR による複合条件に対応。`op` は WHERE と同じ許可リスト。左辺の集約は SELECT 句と同じ検証（別名は不可）。

---

## 内部メソッド（private・直接は呼ばない）

| メソッド | 機能 | 特記事項 |
|---|---|---|
| `_execute(query, params, commit, fetch, many)` | 全SQL実行の単一窓口 | 結果dictを組み立てて返す。`many=True` で executemany。失敗時ロールバック、`errno` 取得、表示用 `sql` の格納 |
| `_build_tail(query_option)` | クエリ末尾（WHERE〜LIMIT）を組み立てる | 純粋関数。LIMIT/OFFSET を検証 |
| `_render_clause(clause, subqueries)` | WHERE/HAVING句を組み立てサブクエリを展開 | 純粋関数。`%s` と `{name}` を左から解決 |
| `_render_subquery(opt)` | サブクエリSELECTを組み立てる | 純粋関数。ネスト深さ2・サブクエリ内JOIN禁止 |
| `_is_valid_name(name)` | 識別子（DB名・テーブル名）の検証 | 正規表現 `\w+` |
| `_fail(msg)` | 実行前の失敗を結果dictと同じ形で返す | `errno` は None |
| `_format_sql_value(value)` | 値を表示用SQLリテラルに整形 | None→NULL / 真偽→TRUE,FALSE / 数値→そのまま / 他→引用符。**表示専用** |
| `_fill_placeholders(query, params)` | `%s` を整形済みの値で左から置換 | **表示専用**（実行には使わない） |
| `_render_display_sql(query, params, many)` | 実行SQLの「見せる用」文字列を生成 | **実行には使わない**。多行は先頭行＋行数注記 |

---

## 補足: クラスにはあるが、まだAPIから叩けないもの
`Select_Join` / `Update_Data` / `Delete_Data` / `Create_Table` / `Create_DataBase` は **DB_Manager には実装済みだが、API エンドポイントとしては未公開**。API層（`server.py`）が現在公開しているのは、DB一覧・テーブル一覧・列情報・select・insert・truncate・drop table の7つ。残りは同じパターンで追加可能。