from app.routers.dashboard import _reason_bucket


def test_reason_bucket_classification():
    assert _reason_bucket("CAPTCHAを検出したため手動対応が必要です") == "CAPTCHA"
    assert _reason_bucket("営業お断り文言を検出: 営業目的の") == "営業お断り"
    assert _reason_bucket("本文フィールドに入力できませんでした") == "本文欄なし"
    assert _reason_bucket("送信ボタンが見つかりませんでした") == "送信ボタンなし"
    assert _reason_bucket("送信後に完了文言を確認できませんでした。") == "完了未確認"
    assert _reason_bucket("手動で却下") == "手動却下"
    assert _reason_bucket(None) == "その他"
    assert _reason_bucket("なにか未知の理由") == "その他"
