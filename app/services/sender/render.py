"""テンプレート本文への変数差し込み。

利用できる変数(送信先企業の情報):
    {{company_name}}  企業名
    {{domain}}        ドメイン
    {{industry}}      業種

未定義の変数はそのまま残さず空文字に置換し、warning として返す。
"""
import re

from app.models import Company

_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def template_vars(company: Company) -> dict[str, str]:
    return {
        "company_name": company.name,
        "domain": company.domain or "",
        "industry": company.industry or "",
    }


def render_template(text: str, variables: dict[str, str]) -> tuple[str, list[str]]:
    """変数を差し込み、(結果, 未定義変数のリスト) を返す。"""
    unknown: list[str] = []

    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name in variables:
            return variables[name]
        unknown.append(name)
        return ""

    return _VAR_PATTERN.sub(replace, text), unknown
