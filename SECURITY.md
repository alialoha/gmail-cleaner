# Security

## Secrets never belong in git

Do **not** commit:

- OAuth client secret JSON (`credentials.json`, `client_secret*.json`)
- OAuth token / refresh-token files (`token*.json`)
- Real `accounts.yaml` or `policy.yaml`
- `.env` files with secrets
- SQLite DB / scan reports (may contain email metadata)

This repo’s `.gitignore` blocks the common patterns. Local secrets live under:

```text
~/.gmail-cleaner/
  credentials/   # OAuth Desktop client JSON per account (optional shared client)
  tokens/        # refresh tokens per account
  data/          # SQLite history + reports
  accounts.yaml  # account registry
```

## Google Cloud setup (safe defaults)

1. Create a Google Cloud project.
2. Enable **Gmail API**.
3. Configure OAuth consent screen (External + your test users, or Internal for Workspace).
4. Create an OAuth client ID of type **Desktop app**.
5. Download the JSON and store it under `~/.gmail-cleaner/credentials/` — not inside the git working tree.
6. Prefer the least privilege scope that fits your workflow:
   - Scan + move to Trash: `gmail.modify`
   - Permanent delete: requires the broader `https://mail.google.com/` scope (re-auth)

## Local API

`gmail-cleaner serve` binds to loopback (`127.0.0.1`) by default and has **no authentication**. Do not use `--allow-remote` unless you understand that anyone who can reach the port can trigger scans and deletes.

## Revoking access

- Google Account → Security → Third-party access → remove this app
- Delete `~/.gmail-cleaner/tokens/<account>.json`

## Reporting issues

If you discover a vulnerability in this project, open a private security advisory on GitHub or contact the maintainers. Do not file a public issue that includes tokens or message contents.
