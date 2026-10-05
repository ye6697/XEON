# XEON Work Engine — Cloud Worker

This worker lets the Base44 XEON app hand off software-engineering jobs to a remote Linux VM.

Flow:

```
XEON/Base44 -> signed job -> Prompt Architect (ChatGPT plan) -> Codex CLI -> tests -> Git branch/PR -> Base44 publisher
```

The worker deliberately does **not** use `OPENAI_API_KEY`. It uses OpenAI's Sign in with ChatGPT OAuth flow for eligible ChatGPT-plan requests and refreshes that OAuth session on the VM.

## Security model

- Base44 talks to this service with HMAC-signed requests (`XEON_WORKER_SECRET`).
- Only repositories in `XEON_ALLOWED_REPOS` can be cloned.
- ChatGPT access/refresh tokens stay in `/var/lib/xeon-work/chatgpt-plan.json`, mode 0600.
- The worker removes `OPENAI_API_KEY` from the Codex subprocess environment.
- A secret scan runs before commit.
- Codex works on a new `xeon/work-...` branch. It does not merge or deploy production itself.
- CAT1 jobs stop in `approval_required` after coding/testing.
- Base44 production publishing remains a separate controlled path.

## One-time ChatGPT authorization

OpenAI's self-hosted VM flow requires the browser OAuth step to happen locally because the callback uses `127.0.0.1`. Afterward, transfer the protected credential file to the VM and let the VM perform refreshes.

On a trusted computer:

```bash
python -m venv .venv
. .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python siwc_login.py --output chatgpt-plan.json
```

Approve **ChatGPT plan usage** in the browser. Then copy `chatgpt-plan.json` over SSH to:

```
<worker-dir>/data/chatgpt-plan.json
```

Never commit that file.

## Run on the VM

```bash
cp .env.example .env
# set XEON_WORKER_SECRET and GITHUB_TOKEN
mkdir -p data
chmod 700 data
docker compose up -d --build
```

The container listens on port 8787. Put it behind HTTPS (reverse proxy / provider firewall) before setting `XEON_WORKER_URL` in Base44.

## Base44 variables

Set these as Base44 secrets:

- `XEON_WORKER_URL=https://<worker-host>`
- `XEON_WORKER_SECRET=<same random secret>`

The `xeonWork` backend never stores the secret in an entity or sends it to Codex.

## GitHub / Base44 production path

The MySupplyX repository already contains a self-hosted Base44 publisher workflow. The XEON Work branch extends it to push entity schemas and deploy `xeonWork` before building and publishing the site.

Do not configure the Codex worker to deploy production directly. Let the existing Base44 publishing path remain the final deployment boundary.
