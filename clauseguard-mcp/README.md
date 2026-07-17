# ClauseGuard MCP Server

Serveur MCP local pour les outils ClauseGuard : sauvegarde de rapports, envoi d'email au juriste, lecture de rapport et journal d'audit.

## Prérequis

- Python 3.12+
- Windows PowerShell
- Compte Gmail avec mot de passe d'application pour l'envoi d'emails

## Setup

```powershell
cd clauseguard-mcp
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Configuration

```powershell
copy .env.example .env
```

Editez `.env` :

```env
GMAIL_SENDER=votre.email@gmail.com
GMAIL_APP_PASSWORD=xxxx yyyy zzzz aaaa
JURISTE_EMAIL=juriste@exemple.com
SQLITE_PATH=reports.db
FASTMCP_HOST=127.0.0.1
FASTMCP_PORT=8001
```

## Démarrage

```powershell
START.bat
```

Ou manuellement :

```powershell
python init_sqlite.py
python mcp_server.py
```

Le serveur écoute sur `http://127.0.0.1:8001` avec le endpoint SSE à `/sse`.

## Tunnel public (serveo.net)

Pour enregistrer le serveur sur la plateforme Fusion :

```powershell
ssh -o StrictHostKeyChecking=no -R 80:127.0.0.1:8001 serveo.net
```

Le serveur MCP active par defaut une protection DNS rebinding qui refuse les
en-tetes `Host` publics. Autorisez les tunnels en ajoutant dans `.env` :

```env
MCP_DISABLE_DNS_PROTECTION=true
```

Puis dans l'interface : **Add MCP Server** → onglet **Streamable HTTP/SSE** → URL `https://<sous-domaine-serveo>.net/sse`.

## Outils exposés

- `sauvegarder_rapport(contract_id, request_id, report_json)` — upsert SQLite + audit (idempotent par `contract_id`), `request_id` corrèle la ligne SQLite avec l'`audit_log.jsonl` de l'app et les logs de session de la plateforme
- `envoyer_email_juriste(contract_id, overall_risk, resume, request_id="")` — SMTP Gmail (idempotent par `(contract_id, request_id)`)
- `lire_rapport(contract_id)` — lecture SQLite
- `journal_audit(limit=20)` — dernières lignes d'audit

### Idempotence des outils

- `sauvegarder_rapport` écrase la ligne existante pour le même `contract_id` (`INSERT OR REPLACE`).
- `envoyer_email_juriste` stocke chaque envoi dans `sent_emails(contract_id, request_id, sent_at)`.
  Si le couple `(contract_id, request_id)` existe déjà, l'appel retourne `déjà envoyé, ignoré`
  sans déclencher de nouvel email. Le prompt/canvas d'orchestration doit transmettre un
  `request_id` unique à chaque appel (par exemple l'identifiant de run Fusion).
