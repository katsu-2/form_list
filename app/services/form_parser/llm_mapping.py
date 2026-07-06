"""ルールベースで判定できなかったフォーム項目を Claude API で補完する。

ルールベースの form_parser が role を決められなかったフィールドについて、
name/id/label/placeholder などの手がかりを Claude に渡し、役割を推定させる。

設計方針:
- APIキーが未設定・SDK未インストール・API失敗のいずれでもグレースフルに空補完を返し、
  呼び出し側(ルールベースの結果)を壊さない。LLMはあくまで「補助」。
- 構造化出力(output_config.format)で role→フィールド名 の対応のみを受け取り、
  未知のroleや存在しないフィールド名は破棄する。
"""
from __future__ import annotations

import json
import logging
import os

from app.services.form_parser.parser import FIELD_KEYWORDS, FormField

logger = logging.getLogger(__name__)

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

VALID_ROLES = list(FIELD_KEYWORDS.keys())


def _is_available() -> bool:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _build_prompt(unmapped: list[FormField]) -> str:
    lines = [
        "以下は日本語の問い合わせフォームのうち、ルールベースで役割を判定できなかった入力欄です。",
        "各欄に最も適切な役割(role)を割り当ててください。判定できない欄は role を \"unknown\" にしてください。",
        "",
        "利用可能な role:",
        ", ".join(VALID_ROLES),
        "",
        "入力欄:",
    ]
    for f in unmapped:
        attrs = {
            "name": f.name,
            "id": f.field_id,
            "label": f.label,
            "placeholder": f.placeholder,
            "tag": f.tag,
            "type": f.input_type,
        }
        attrs = {k: v for k, v in attrs.items() if v}
        lines.append(f"- {json.dumps(attrs, ensure_ascii=False)}")
    return "\n".join(lines)


_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field_name": {"type": "string"},
                    "role": {"type": "string", "enum": [*VALID_ROLES, "unknown"]},
                },
                "required": ["field_name", "role"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assignments"],
    "additionalProperties": False,
}


def complete_mapping(unmapped: list[FormField]) -> dict[str, str]:
    """未マッピングのフィールドに対する role→フィールド名 の補完を返す。

    利用不可・失敗時は空 dict(補完なし)。呼び出し側で既存マッピングとマージする。
    """
    candidates = [f for f in unmapped if f.name and f.input_type != "hidden"]
    if not candidates or not _is_available():
        return {}

    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
            messages=[{"role": "user", "content": _build_prompt(candidates)}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text)
    except Exception as exc:  # API失敗・パース失敗など全て握りつぶす(補助機能のため)
        logger.warning("LLMマッピング補完に失敗しました: %s", exc)
        return {}

    valid_names = {f.name for f in candidates}
    mapping: dict[str, str] = {}
    for item in data.get("assignments", []):
        role = item.get("role")
        field_name = item.get("field_name")
        if (
            role in VALID_ROLES
            and field_name in valid_names
            and role not in mapping  # 同じroleは最初の1件のみ採用
        ):
            mapping[role] = field_name
    return mapping
