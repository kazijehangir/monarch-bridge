# Monarch Money Bridge

A robust, self-healing integration service between external tools (like n8n) and Monarch Money. It maintains a persistent session, handles MFA, and exposes a clean REST API.

## Features

- **Persistent Session**: Maintains your Monarch Money authentication across restarts using local storage.
- **Keep-Alive**: Automatic background pings every 15 minutes to prevent session expiration.
- **MFA Support**: Interactive MFA handling via REST endpoints.
- **n8n Friendly**: Standard JSON/HTTP interface for easy integration with automation workflows.
- **Cloudflare Bypass**: Integrated User-Agent spoofing to avoid common blocks.

## Quick Start

### 1. Build and Run with Docker

```bash
docker build -t monarch-bridge .
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/data:/data \
  -e MONARCH_EMAIL="your@email.com" \
  -e MONARCH_PASSWORD="yourpassword" \
  -e MONARCH_MFA_SECRET="yourtotpsecret" \
  --name monarch-bridge \
  monarch-bridge
```

### 2. Initial Authentication

1. Open the Swagger UI at `http://localhost:8000/docs`.
2. Use the `POST /auth/login` endpoint with your Monarch email and password.
3. If the response indicates `mfa_required`, check your email/SMS for the code and use the `POST /auth/mfa` endpoint.
4. Once authenticated, your session will be saved to `./data/monarch_session.pickle`.

### 3. API Usage

- **Get Transactions**: `GET /transactions?days=30`
- **Update Transaction**: `PATCH /transactions/{id}`
  - Body: `{"notes": "Your note", "category_id": "...", "needs_review": false}`

## Development

### Prerequisites

- Python 3.11+
- `pip`

### Local Setup

1. Create a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:

   ```bash
   uvicorn main:app --reload
   ```

## Architecture

The bridge uses the `monarchmoneycommunity` fork to interact with Monarch's GraphQL API. It leverages FastAPI for the REST layer and `asyncio` for background maintenance tasks.

See `GEMINI.md` for more technical details and n8n integration patterns.
