import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import bcrypt
import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from config import settings
from models.schemas import TokenPair, TokenPayload, UserLogin

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

DEMO_PASSWORD_HASH = bcrypt.hashpw("clauseguard".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
DEMO_USER = {
    "username": "clauseguard",
    "hashed_password": DEMO_PASSWORD_HASH,
}


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def authenticate_user(credentials: UserLogin) -> Optional[dict]:
    if credentials.username != DEMO_USER["username"]:
        return None
    if not verify_password(credentials.password, DEMO_USER["hashed_password"]):
        return None
    return {"username": credentials.username}


def create_token_pair(username: str) -> TokenPair:
    now = datetime.now(timezone.utc)
    access_payload = {
        "sub": username,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
    }
    refresh_payload = {
        "sub": username,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.refresh_token_expire_minutes)).timestamp()),
    }
    return TokenPair(
        access_token=jwt.encode(access_payload, settings.secret_key, algorithm=settings.algorithm),
        refresh_token=jwt.encode(refresh_payload, settings.secret_key, algorithm=settings.algorithm),
    )


def refresh_access_token(refresh_token: str) -> str:
    try:
        payload = jwt.decode(refresh_token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc

    token_data = TokenPayload(**payload)
    if token_data.type != "refresh" or not token_data.sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    now = datetime.now(timezone.utc)
    access_payload = {
        "sub": token_data.sub,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
    }
    return jwt.encode(access_payload, settings.secret_key, algorithm=settings.algorithm)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        ) from exc

    token_data = TokenPayload(**payload)
    if token_data.type != "access" or not token_data.sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        )

    return {"username": token_data.sub}


class FusionAuth:
    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self.session = session or requests.Session()
        self.login_url = settings.resolved_login_url
        self.username = settings.fusion_username
        self.password = settings.fusion_password
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at: float = 0.0
        self._set_cookies_domain()

    def _set_cookies_domain(self) -> None:
        parsed = urlparse(self.login_url)
        self.cookie_domain = parsed.hostname or ""

    def _decode_exp(self, token: str) -> float:
        try:
            payload = jwt.decode(
                token,
                key="",
                algorithms=[settings.algorithm],
                options={"verify_signature": False, "verify_aud": False},
            )
            return float(payload.get("exp", 0))
        except Exception:
            return 0.0

    def _extract_tokens(self, data: dict) -> tuple[Optional[str], Optional[str]]:
        access_token = (
            data.get("access_token")
            or data.get("accessToken")
            or data.get("token")
        )
        refresh_token = data.get("refresh_token") or data.get("refreshToken")
        return access_token, refresh_token

    def _update_tokens(self, access_token: str, refresh_token: Optional[str] = None) -> None:
        self.access_token = access_token
        if refresh_token:
            self.refresh_token = refresh_token
        self.expires_at = self._decode_exp(access_token)
        self.session.cookies.set("accessToken", access_token, domain=self.cookie_domain, path="/")
        if self.refresh_token:
            self.session.cookies.set(
                "refreshToken", self.refresh_token, domain=self.cookie_domain, path="/"
            )

    def _try_login_request(self, url: str, use_json: bool) -> Optional[requests.Response]:
        try:
            if use_json:
                response = self.session.post(
                    url,
                    json={"username": self.username, "password": self.password},
                    timeout=60,
                )
            else:
                response = self.session.post(
                    url,
                    data={"username": self.username, "password": self.password},
                    timeout=60,
                )
            if response.status_code == 200:
                return response
        except Exception:
            pass
        return None

    def login(self) -> str:
        candidates = [
            (f"{self.login_url}/api/v1/login", True),
            (f"{self.login_url}/api/v1/login", False),
            (f"{self.login_url}/api/v1/auth/login", True),
            (f"{self.login_url}/api/v1/auth/login", False),
        ]
        last_response: Optional[requests.Response] = None
        for url, use_json in candidates:
            response = self._try_login_request(url, use_json)
            if response is not None:
                last_response = response
                break
        if last_response is None:
            raise RuntimeError("All login endpoints failed")
        last_response.raise_for_status()
        data = last_response.json()
        access_token, refresh_token = self._extract_tokens(data)
        if not access_token:
            raise RuntimeError("Login response did not contain an access token")
        self._update_tokens(access_token, refresh_token)
        return access_token

    def _try_refresh_request(self, url: str, refresh_token: str) -> Optional[str]:
        try:
            response = self.session.post(
                url,
                headers={"Cookie": f"refreshToken={refresh_token}"},
                timeout=60,
            )
            if response.status_code == 200:
                data = response.json()
                access_token, new_refresh = self._extract_tokens(data)
                if access_token:
                    self._update_tokens(access_token, new_refresh)
                    return access_token
        except Exception:
            pass
        return None

    def refresh(self) -> str:
        refresh_token = self.refresh_token
        if refresh_token:
            for path in ["/api/v1/refresh", "/api/v1/auto_login", "/api/v1/auth/refresh", "/api/v1/auth/auto_login"]:
                token = self._try_refresh_request(f"{self.login_url}{path}", refresh_token)
                if token:
                    return token
        return self.login()

    def get_token(self) -> str:
        if not self.access_token:
            return self.login()
        if time.time() >= self.expires_at - 60:
            return self.refresh()
        return self.access_token
