from app.models import Company
from app.services.sender.render import render_template, template_vars


def test_render_template_replaces_vars():
    text, unknown = render_template(
        "{{company_name}}ご担当者様({{industry}})",
        {"company_name": "テスト社", "industry": "IT"},
    )
    assert text == "テスト社ご担当者様(IT)"
    assert unknown == []


def test_render_template_unknown_var_becomes_empty():
    text, unknown = render_template("こんにちは{{unknown_var}}様", {})
    assert text == "こんにちは様"
    assert unknown == ["unknown_var"]


def test_template_vars_from_company():
    company = Company(name="株式会社テスト", domain="test.example", industry=None)
    variables = template_vars(company)
    assert variables["company_name"] == "株式会社テスト"
    assert variables["domain"] == "test.example"
    assert variables["industry"] == ""
