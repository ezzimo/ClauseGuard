import logging
import time
from typing import Any, Optional

import requests

from config import settings
from services.auth import FusionAuth

logger = logging.getLogger(__name__)


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
        retry_on_5xx: bool = True,
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

        logger.info(
            "Executing Fusion flow flow_id=%s (session_id=%s, payload_bytes=%d)",
            flow_id,
            session_id,
            len(message.encode("utf-8")),
        )

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
                    logger.warning("Fusion API 401 Unauthorized for flow_id=%s, refreshing token...", flow_id)
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
                logger.info(
                    "Fusion flow flow_id=%s succeeded in %d ms (status=%d)",
                    flow_id,
                    duration_ms,
                    response.status_code,
                )
                return {
                    "response_text": text,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }

            except requests.exceptions.HTTPError as exc:
                last_error = exc
                logger.error(
                    "Fusion flow flow_id=%s failed attempt %d/3: status=%d, error=%s",
                    flow_id,
                    attempt + 1,
                    last_status,
                    exc,
                )
                if attempt < 2 and 500 <= last_status < 600 and retry_on_5xx:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
            except Exception as exc:
                last_error = exc
                logger.error("Fusion flow flow_id=%s failed with exception: %s", flow_id, exc)
                raise

        raise RuntimeError(
            f"Flow {flow_id} failed after 3 attempts: status={last_status}, error={last_error}"
        )
