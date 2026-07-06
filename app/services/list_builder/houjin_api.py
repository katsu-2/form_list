"""国税庁 法人番号システム Web-API 連携によるリスト収集。

法人名・所在地の一次データを取得する。フォームURLや業種は含まれないため、
取り込み後に別途フォーム探索を行う前提。

利用には国税庁が発行するアプリケーションID(app_id)が必要(無料)。
未設定時は例外ではなく空結果+案内メッセージを返し、呼び出し側を壊さない。

参考: https://www.houjin-bangou.nta.go.jp/webapi/
CSV(type=12, Shift_JIS)のname検索レスポンス列(1始まり):
  2:法人番号 7:商号又は名称 10:都道府県名 11:市区町村名 12:丁目番地等
"""
from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field

import httpx

API_BASE = "https://api.houjin-bangou.nta.go.jp/4"
REQUEST_TIMEOUT = 15.0

# CSVの0始まり列インデックス
_COL_CORPORATE_NUMBER = 1
_COL_NAME = 6
_COL_PREFECTURE = 9
_COL_CITY = 10
_COL_STREET = 11


@dataclass
class HoujinCompany:
    corporate_number: str
    name: str
    address: str


@dataclass
class HoujinFetchResult:
    companies: list[HoujinCompany] = field(default_factory=list)
    error: str | None = None


def _app_id() -> str | None:
    return os.environ.get("HOUJIN_API_APP_ID")


def _parse_csv(text: str) -> list[HoujinCompany]:
    companies: list[HoujinCompany] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) <= _COL_STREET:
            continue
        corporate_number = row[_COL_CORPORATE_NUMBER].strip()
        name = row[_COL_NAME].strip()
        if not corporate_number or not name:
            continue
        address = "".join(
            row[i].strip() for i in (_COL_PREFECTURE, _COL_CITY, _COL_STREET) if row[i].strip()
        )
        companies.append(
            HoujinCompany(corporate_number=corporate_number, name=name, address=address)
        )
    return companies


def fetch_by_name(
    name: str,
    *,
    prefecture_code: str | None = None,
    mode: str = "2",  # 1:前方一致 2:部分一致
    client: httpx.Client | None = None,
) -> HoujinFetchResult:
    """法人名で検索して法人情報を取得する。"""
    app_id = _app_id()
    if not app_id:
        return HoujinFetchResult(
            error="環境変数 HOUJIN_API_APP_ID が未設定です。"
            "国税庁でアプリケーションIDを取得して設定してください。"
        )
    if not name.strip():
        return HoujinFetchResult(error="検索する法人名を入力してください")

    params = {
        "id": app_id,
        "name": name.strip(),
        "type": "12",  # CSV Shift_JIS
        "mode": mode,
    }
    if prefecture_code:
        params["address"] = prefecture_code

    owns_client = client is None
    client = client or httpx.Client(timeout=REQUEST_TIMEOUT)
    try:
        resp = client.get(f"{API_BASE}/name", params=params)
        if resp.status_code != 200:
            return HoujinFetchResult(error=f"APIエラー: HTTP {resp.status_code}")
        text = resp.content.decode("shift_jis", errors="replace")
        return HoujinFetchResult(companies=_parse_csv(text))
    except httpx.HTTPError as exc:
        return HoujinFetchResult(error=f"通信エラー: {exc}")
    finally:
        if owns_client:
            client.close()
