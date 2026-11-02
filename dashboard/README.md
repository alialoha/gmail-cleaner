# Gmail Cleaner dashboard

Lightweight React UI for local scans, history, and confirm-to-trash.

## Run

1. Start the API from the repo root:

```bash
gmail-cleaner serve --host 127.0.0.1 --port 8787
```

2. Start the UI:

```bash
npm install
npm run dev
```

Open http://127.0.0.1:5173

Vite proxies `/api` to the API on port 8787.
