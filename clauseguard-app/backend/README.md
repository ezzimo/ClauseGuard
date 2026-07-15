# ClauseGuard Backend

FastAPI backend for contract upload, AI analysis, human-in-the-loop decisions, and report generation.

## Setup (Windows PowerShell)

```powershell
cd clauseguard-app\backend
copy .env.example .env
# Edit .env with your Fusion credentials
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If Python 3.11 is not installed, replace `py -3.11` with `py` to use the default interpreter.

## Run

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## Endpoints

- `POST /api/auth/login` — local JWT login
- `POST /api/contracts/upload` — upload PDF/DOCX/TXT
- `POST /api/contracts/{id}/analyze` — run Fusion analysis flow
- `POST /api/contracts/{id}/decisions` — record human HITL decisions
- `POST /api/contracts/{id}/report` — generate final report via Fusion report flow
- `GET /api/contracts/{id}/report` — retrieve stored report
- `GET /api/contracts/{id}` — contract state

## Test

```powershell
pytest tests/test_full_sequence.py -v
python tests/test_validation.py
python tests/test_parse_error.py
python tests/test_response_extract.py
```

Live Fusion login can be verified with:

```powershell
python -c "from services.auth import FusionAuth; a=FusionAuth(); print(a.login())"
```

## Optional NER layer (GLiNER)

Set `ANONYMIZER_NER=on` to enable an advanced person-detection layer based on
GLiNER (`urchade/gliner_medium-v2.1`).  The model is lazy-loaded on the first
call and downloads ~500MB on first run.

```powershell
$env:ANONYMIZER_NER="on"
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Default is `off`; the pipeline behaves exactly as in the standard configuration.
NER detects person names even when they are not supplied in `party_names[]`.
If NER fails (download error, OOM, import error, etc.) the pipeline logs a
warning and continues unchanged.
