# Web app

The website for the shipping document verification system (Next.js). It shows every email, the SI and BL
fields side by side, what the system decided and why, and lets a person review the cases it would not decide alone.
It talks to the backend in `../api/`; it has no data of its own.

## Run it locally

```
npm install
npm run dev          # http://localhost:3000
```

The backend must be running too (`python -m uvicorn api.main:app` from the repo root, on port 8000).
To point at a different backend, set `NEXT_PUBLIC_API_URL` (for example in `web/.env.local`), with no trailing slash.

## Check it builds

```
npm run build        # also type-checks
```

## Deploy (Vercel)

- Root Directory: `web`
- Environment variable: `NEXT_PUBLIC_API_URL` = the backend address (the Render URL). It is baked in at build time, so
  redeploy after changing it.

## What is where

| Path | What it is |
|---|---|
| `app/page.tsx` | The page: summary, filters, inbox list, details panel |
| `components/` | Details panel, email list, summary, Compose window, re-run panel |
| `lib/api.ts` | Types and calls to the backend |
| `lib/tools.ts`, `lib/samples.ts` | Email simulator and re-run calls; the ready-made example emails |
| `lib/report.ts`, `lib/textdiff.ts` | CSV report; word-level differences |
