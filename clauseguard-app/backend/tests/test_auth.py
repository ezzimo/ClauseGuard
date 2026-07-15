import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from services.auth import FusionAuth


def make_response(status_code, json_data):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def test_login_json_success():
    auth = FusionAuth()
    auth.session.post = MagicMock(return_value=make_response(200, {
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjo5OTk5OTk5OTk5fQ.token",
        "refresh_token": "refresh",
    }))
    token = auth.login()
    assert token.startswith("eyJ")
    assert auth.refresh_token == "refresh"
    assert auth.session.post.call_args.kwargs.get("json") is not None


def test_login_form_fallback():
    auth = FusionAuth()
    json_resp = make_response(400, {})
    form_resp = make_response(200, {
        "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjo5OTk5OTk5OTk5fQ.token",
        "refreshToken": "refresh",
    })
    auth.session.post = MagicMock(side_effect=[json_resp, form_resp])
    token = auth.login()
    assert token.startswith("eyJ")
    assert auth.session.post.call_count == 2
    second_call = auth.session.post.call_args_list[1]
    assert second_call.kwargs.get("data") is not None


def test_get_token_auto_refresh_near_expiry(monkeypatch):
    auth = FusionAuth()
    auth.access_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxfQ.token"
    auth.expires_at = time.time() + 30
    auth.session.post = MagicMock(return_value=make_response(200, {
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjo5OTk5OTk5OTk5fQ.new",
        "refresh_token": "new_refresh",
    }))
    token = auth.get_token()
    assert token == "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjo5OTk5OTk5OTk5fQ.new"


def test_get_token_valid_no_refresh(monkeypatch):
    auth = FusionAuth()
    auth.access_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjo5OTk5OTk5OTk5fQ.token"
    auth.expires_at = time.time() + 3600
    auth.login = MagicMock()
    token = auth.get_token()
    assert token == auth.access_token
    auth.login.assert_not_called()


def test_refresh_falls_back_to_login():
    auth = FusionAuth()
    auth.refresh_token = "refresh"
    auth.session.post = MagicMock(return_value=make_response(401, {}))
    auth.login = MagicMock(return_value="new_access")
    token = auth.refresh()
    assert token == "new_access"
