"""LLMマッピング補完のテスト。

実APIは呼ばず、可用性チェックとレスポンス処理(バリデーション)を検証する。
"""
from app.services.form_parser import llm_mapping
from app.services.form_parser.parser import FormField


def _field(name, role=None, tag="input", input_type="text"):
    return FormField(
        tag=tag, input_type=input_type, name=name, field_id=None,
        label=None, placeholder=None, required=True, role=role,
    )


def test_returns_empty_when_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    result = llm_mapping.complete_mapping([_field("company")])
    assert result == {}


def test_returns_empty_for_no_candidates(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # hidden や name無しは候補にならないため、API可用でも空
    hidden = _field("token", input_type="hidden")
    noname = _field(None)
    assert llm_mapping.complete_mapping([hidden, noname]) == {}


def test_validates_and_filters_llm_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class FakeBlock:
        type = "text"
        text = (
            '{"assignments": ['
            '{"field_name": "kaisha", "role": "company_name"},'
            '{"field_name": "denwa", "role": "phone"},'
            '{"field_name": "unknown_field", "role": "email"},'   # 存在しないフィールド→破棄
            '{"field_name": "nazo", "role": "invalid_role"}'      # 不正なrole→破棄
            ']}'
        )

    class FakeResponse:
        content = [FakeBlock()]

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    class FakeAnthropicModule:
        Anthropic = staticmethod(lambda: FakeClient())

    monkeypatch.setitem(__import__("sys").modules, "anthropic", FakeAnthropicModule())

    fields = [_field("kaisha"), _field("denwa"), _field("nazo")]
    result = llm_mapping.complete_mapping(fields)
    assert result == {"company_name": "kaisha", "phone": "denwa"}


def test_swallows_api_errors(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class FakeMessages:
        def create(self, **kwargs):
            raise RuntimeError("boom")

    class FakeClient:
        messages = FakeMessages()

    class FakeAnthropicModule:
        Anthropic = staticmethod(lambda: FakeClient())

    monkeypatch.setitem(__import__("sys").modules, "anthropic", FakeAnthropicModule())
    assert llm_mapping.complete_mapping([_field("x")]) == {}
