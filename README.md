# フォーム営業ツール + リスト作成ツール

企業サイトの問い合わせフォーム経由の営業(フォーム営業)を効率化するツール。
設計・ロードマップは [docs/PLAN.md](docs/PLAN.md) を参照。

## 現在の実装状況(Phase 1: リスト作成 MVP)

- 企業リストの CSV インポート/エクスポート(正規化・重複排除・NGリスト照合つき)
- 問い合わせフォームURLの自動探索(典型パス試行 + トップページのリンク解析、robots.txt 尊重)
- フォーム解析: フィールドの役割推定(会社名/氏名/メール/本文 等)、CAPTCHA検出、営業お断り文言の検出
- 管理画面: 企業一覧(検索・ステータスフィルタ)、フォーム探索実行、NG登録

## セットアップ

```bash
uv sync --extra dev   # または: pip install -e ".[dev]"
```

## 起動

```bash
uv run uvicorn app.main:app --reload
```

http://localhost:8000 で管理画面が開きます。

## テスト

```bash
uv run pytest
```

## CSVインポート形式

ヘッダ行必須。`name` のみ必須、他は任意。

```csv
name,url,corporate_number,industry,address
株式会社サンプル,https://example.co.jp,1234567890123,IT,東京都...
```
