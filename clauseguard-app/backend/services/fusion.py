import time
from typing import Any, Optional

import requests

from config import settings
from services.auth import FusionAuth


class FusionClient:
    def __init__(self, auth: Optional[FusionAuth] = None) -> None:
        self.auth = auth or FusionAuth()
        self.base_url = settings.fusion_base_url.rstrip("/")

    def _extract_response_text(self, payload: dict) -> str:
        outputs = payload.get("outputs", [])[0]
        inner = outputs.get("outputs", [])[0]
        return inner["results"]["message"]["text"]

    def run_flow(
        self,
        flow_id: str,
        message: str,
        session_id: Optional[str] = None,
    ) -> dict:
        url = f"{self.base_url}/api/v1/run/{flow_id}"
        body: dict[str, Any] = {
            "input_value": message,
            "input_type": "chat",
            "output_type": "chat",
        }
        if session_id:
            body["session_id"] = session_id

        last_status: int = 0
        last_error: Optional[Exception] = None

        for attempt in range(3):
            start = time.perf_counter()
            try:
                response = self.auth.session.post(
                    url,
                    headers={"Authorization": f"Bearer {self.auth.get_token()}"},
                    json=body,
                    timeout=(10, 600),
                )
                duration_ms = int((time.perf_counter() - start) * 1000)
                last_status = response.status_code

                if response.status_code == 401:
                    self.auth.refresh()
                    response = self.auth.session.post(
                        url,
                        headers={"Authorization": f"Bearer {self.auth.get_token()}"},
                        json=body,
                        timeout=300,
                    )
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    last_status = response.status_code

                if 500 <= response.status_code < 600:
                    response.raise_for_status()

                response.raise_for_status()
                payload = response.json()
                text = self._extract_response_text(payload)
                return {
                    "response_text": text,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }

            except requests.exceptions.HTTPError as exc:
                last_error = exc
                if attempt < 2 and 500 <= last_status < 600:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
            except Exception as exc:
                last_error = exc
                raise

        raise RuntimeError(
            f"Flow {flow_id} failed after 3 attempts: status={last_status}, error={last_error}"
        )
