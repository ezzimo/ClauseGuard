import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.fusion import FusionClient


def main() -> int:
    payload = {
        "outputs": [
            {
                "outputs": [
                    {
                        "results": {
                            "message": {
                                "text": "```json\n" + json.dumps({"audit_status": "ok"}) + "\n```"
                            }
                        }
                    }
                ]
            }
        ]
    }
    client = FusionClient()
    text = client._extract_response_text(payload)
    assert "audit_status" in text
    print("Response extraction: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
