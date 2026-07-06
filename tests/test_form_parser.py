from app.services.form_parser.parser import (
    detect_captcha,
    detect_sales_prohibited,
    parse_form_page,
)

CONTACT_FORM_HTML = """
<html><body>
<form action="/contact/confirm" method="post">
  <table>
    <tr><th>会社名</th><td><input type="text" name="company" required></td></tr>
    <tr><th>お名前</th><td><input type="text" name="your_name" required></td></tr>
    <tr><th>メールアドレス</th><td><input type="email" name="email" required></td></tr>
    <tr><th>電話番号</th><td><input type="tel" name="tel"></td></tr>
    <tr><th>お問い合わせ内容</th><td><textarea name="message" required></textarea></td></tr>
  </table>
  <input type="hidden" name="csrf_token" value="x">
  <input type="submit" value="確認画面へ">
</form>
</body></html>
"""

SEARCH_FORM_HTML = """
<html><body>
<form action="/search" method="get">
  <input type="text" name="q" placeholder="検索">
  <input type="submit" value="検索">
</form>
</body></html>
"""

CAPTCHA_FORM_HTML = """
<html><body>
<form action="/contact" method="post">
  <input type="email" name="email">
  <textarea name="body"></textarea>
  <div class="g-recaptcha" data-sitekey="xxx"></div>
</form>
</body></html>
"""

PROHIBITED_HTML = """
<html><body>
<p>営業目的のお問い合わせはお断りしております。</p>
<form action="/contact" method="post">
  <input type="email" name="email">
  <textarea name="inquiry"></textarea>
</form>
</body></html>
"""


def test_parse_contact_form_maps_fields():
    forms = parse_form_page(CONTACT_FORM_HTML)
    assert len(forms) == 1
    form = forms[0]
    assert form.method == "post"
    mapping = form.field_mapping
    assert mapping["company_name"] == "company"
    assert mapping["person_name"] == "your_name"
    assert mapping["email"] == "email"
    assert mapping["phone"] == "tel"
    assert mapping["body"] == "message"
    assert form.unmapped_required_fields == []
    assert not form.has_captcha
    assert not form.sales_prohibited


def test_search_form_is_not_contact_form():
    assert parse_form_page(SEARCH_FORM_HTML) == []


def test_captcha_detected():
    forms = parse_form_page(CAPTCHA_FORM_HTML)
    assert len(forms) == 1
    assert forms[0].has_captcha
    assert detect_captcha(CAPTCHA_FORM_HTML)


def test_sales_prohibited_detected():
    forms = parse_form_page(PROHIBITED_HTML)
    assert len(forms) == 1
    assert forms[0].sales_prohibited
    assert forms[0].prohibited_phrase is not None
    assert detect_sales_prohibited("営業目的のお問い合わせはお断り") is not None
    assert detect_sales_prohibited("お気軽にお問い合わせください") is None


def test_hidden_fields_have_no_role():
    forms = parse_form_page(CONTACT_FORM_HTML)
    hidden = [f for f in forms[0].fields if f.input_type == "hidden"]
    assert len(hidden) == 1
    assert hidden[0].role is None
