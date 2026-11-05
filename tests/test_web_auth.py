import hashlib
import hmac
import json
from urllib.parse import urlencode

from clashbot.web import auth

TOKEN = "42:finto"
NOW = 1789000000
CODE = "abcdef0123456789"


def signed(fields, token=TOKEN, secret_key=None):
    check = auth.check_string(fields.items())
    secret = secret_key or hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})


def init(extra=None, **kwargs):
    fields = {"auth_date": str(NOW), "query_id": "AAA",
              "user": json.dumps({"id": 777, "first_name": "Mario"}, separators=(",", ":"))}
    fields.update(extra or {})
    return auth.init_data(signed(fields, **kwargs), TOKEN, NOW)


def test_the_check_string_is_sorted_and_joined_with_newlines():
    assert auth.check_string({"b": "2", "a": "1"}.items()) == "a=1\nb=2"


def test_a_good_init_data_gives_back_the_user():
    checked = init()
    assert checked["user"] == {"id": 777, "first_name": "Mario"}
    assert auth.user_id(checked) == 777


def test_the_signature_of_another_bot_is_refused():
    other = hmac.new(b"WebAppData", b"43:altro", hashlib.sha256).digest()
    assert init(secret_key=other) is None
    assert auth.init_data(signed({"auth_date": str(NOW)}), "", NOW) is None
    assert auth.init_data("", TOKEN, NOW) is None
    assert auth.init_data("auth_date=1&hash=deadbeef", TOKEN, NOW) is None


def test_a_field_changed_after_the_signature_is_refused():
    raw = signed({"auth_date": str(NOW), "user": json.dumps({"id": 777})})
    assert auth.init_data(raw.replace("777", "778"), TOKEN, NOW) is None


def test_old_or_future_init_data_is_refused():
    assert auth.init_data(signed({"auth_date": str(NOW)}), TOKEN, NOW + auth.MINIAPP_MAX_AGE + 1) is None
    assert auth.init_data(signed({"auth_date": str(NOW)}), TOKEN, NOW - auth.SKEW - 1) is None
    assert auth.init_data(signed({"auth_date": "pinco"}), TOKEN, NOW) is None
    assert auth.init_data(signed({"pinco": "1"}), TOKEN, NOW) is None


def test_the_code_of_the_clan_travels_inside_the_signature():
    checked = init({"start_param": CODE})
    assert checked["start_param"] == CODE
    assert auth.start_param(checked) == CODE
    raw = signed({"auth_date": str(NOW), "start_param": CODE})
    assert auth.init_data(raw.replace(CODE, "0123456789abcdef"), TOKEN, NOW) is None


def test_a_start_param_that_is_not_a_code_is_thrown_away():
    assert auth.start_param(init({"start_param": "../etc/passwd"})) == ""
    assert auth.start_param(init({"start_param": "un codice"})) == ""
    assert auth.start_param(init({"start_param": ""})) == ""
    assert auth.start_param(init()) == ""
    assert auth.start_param(None) == "" and auth.start_param({"start_param": 7}) == ""


def test_a_broken_user_field_is_refused_and_a_missing_one_gives_no_id():
    assert auth.init_data(signed({"auth_date": str(NOW), "user": "{"}), TOKEN, NOW) is None
    assert auth.user_id(auth.init_data(signed({"auth_date": str(NOW)}), TOKEN, NOW)) == 0
    assert auth.user_id(None) == 0
