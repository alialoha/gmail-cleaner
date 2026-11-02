# Gmail Cleaner

Multi-account Gmail storage cleaner: **scan → report → confirm → trash**.

Phase 1 is a lightweight Python CLI + local API. A small React dashboard (Phase 2) will sit on the same API.

## Why

Free Google accounts share **7.5 GB** across Gmail, Drive, and Photos. Chat assistants only sample recent mail, so they cannot reclaim gigabytes of attachments. This tool paginates the Gmail API, ranks what is using space, and only deletes after an explicit confirmation.

## Safety model

| Action | Default | Gate |
|---|---|---|
| Scan / report | Always dry-run | None |
| Move to Trash | Off | `--confirm` / API `confirm: true` |
| Permanent delete | Off | `--permanent --confirm --i-understand-permanent` + `scope: full` |
| Empty Trash | Off | `--confirm` + `scope: full` |

**Quota note:** Messages in Trash still count toward Google storage for up to 30 days. To reclaim space immediately you need `scope: full`, then `gmail-cleaner empty-trash --confirm`. `scope: modify` can only move mail to Trash.

Secrets never live in the git repo. Runtime data is under `~/.gmail-cleaner/`.

```text
~/.gmail-cleaner/
  credentials/     # OAuth Desktop client JSON
  tokens/          # per-account refresh tokens
  data/history.db  # scan + action history
  data/reports/    # JSON reports
  accounts.yaml    # account registry
```

## Quick start

### 1. Google Cloud

1. Create a project → enable **Gmail API**
2. OAuth consent screen (add yourself as a test user if External)
3. Create OAuth client → type **Desktop app** → download JSON
4. Store it at e.g. `~/.gmail-cleaner/credentials/client_secret.json`

### 2. Install

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
gmail-cleaner doctor
```

### 3. Add accounts

```bash
# Recommended if you need to free quota now (empty trash / permanent delete):
gmail-cleaner accounts add \
  --id personal \
  --email you@gmail.com \
  --credentials ~/.gmail-cleaner/credentials/client_secret.json \
  --scope full

# Optional second mailbox
gmail-cleaner accounts add \
  --id work \
  --email you@company.com \
  --credentials ~/.gmail-cleaner/credentials/client_secret.json \
  --scope modify
```

Account ids may only contain letters, digits, `_`, and `-` (path-safe).

### 4. Scan (never deletes)

```bash
# Storage / quota X-ray (entire mailbox)
gmail-cleaner scan --account personal --mode storage --location all

# Newsletters / ads / marketing tabs
gmail-cleaner scan --account personal --mode subscriptions --location promotions
gmail-cleaner scan --account personal --mode subscriptions --location inbox

# Locations: all | inbox | primary | promotions | social | updates | forums
gmail-cleaner scan --all
gmail-cleaner history
gmail-cleaner history --run <run_id>
```

### 5. Trash after review

```bash
# Preview
gmail-cleaner trash --account personal --sender news@example.com

# Apply (move to Trash)
gmail-cleaner trash --account personal --sender news@example.com --confirm

# Or by Gmail query
gmail-cleaner trash --account personal --query "category:promotions older_than:2y" --confirm
```

Then empty Trash to free quota (permanent):

```bash
gmail-cleaner empty-trash --account personal          # shows count
gmail-cleaner empty-trash --account personal --confirm
```

### 6. Local API + dashboard (Phase 2)

Terminal 1 — API:

```bash
gmail-cleaner serve --host 127.0.0.1 --port 8787
```

Terminal 2 — UI:

```bash
cd dashboard
npm install
npm run dev
```

Open http://127.0.0.1:5173

Loopback only by default. Non-local binds require `--allow-remote` (the API has **no authentication** yet).

- `GET /api/health`
- `GET /api/accounts`
- `GET /api/accounts/{id}/trash-count`
- `GET /api/runs`
- `GET /api/runs/{id}`
- `POST /api/scan` (background by default; poll run status)
- `POST /api/preview`
- `POST /api/cleanup` (requires `confirm: true`; permanent also needs `i_understand_permanent`)
- `POST /api/empty-trash`

## CLI map

```text
gmail-cleaner accounts list|add|remove|auth
gmail-cleaner scan [--account ID | --all]
gmail-cleaner trash --account ID (--sender|--query|--ids-file) [--confirm] [--permanent --i-understand-permanent]
gmail-cleaner empty-trash --account ID [--confirm]
gmail-cleaner history [--run ID]
gmail-cleaner serve
gmail-cleaner doctor
```

## Development

```bash
pytest
ruff check src tests
```

## License

MIT — see [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md). Never commit tokens, client secrets, or real `accounts.yaml`.
