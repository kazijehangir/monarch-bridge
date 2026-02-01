# Project: Monarch Money Bridge & Amazon Sync

## 1. Executive Summary

This project implements a robust, self-healing integration between **Amazon Orders** (via Gmail/n8n) and **Monarch Money**. It bypasses the limitations of Monarch's lack of a public write API by running a local "Sidecar" service that maintains a persistent session, handles MFA, and exposes a clean REST API for n8n to consume.

## 2. Technical Architecture

### High-Level Diagram

```mermaid
graph LR
    subgraph "Unraid / Proxmox Host"
        A[n8n Workflow] -- "HTTP GET/PATCH" --> B[Monarch Bridge Container]
        B -- "Keep-Alive Pings" --> C[Monarch Money API]
        D[Volume: /data] <--> B
    end
    
    subgraph "External"
        E[Gmail (Amazon Orders)] --> A
        C -- "GraphQL" --> F[Monarch Servers]
    end

```

### Components

1. **Monarch Bridge (The "Sidecar"):**

* **Framework:** Python 3.11 + FastAPI.
* **Library:** `monarchmoneycommunity` (Fork) for up-to-date API endpoints.
* **Role:** Maintains the authenticated session in RAM/Disk, handles Cloudflare spoofing, and keeps the connection alive.

1. **n8n Workflow:**

* **Trigger:** Gmail (New Order).
* **Logic:** LLM (Gemini) extracts order details -> Matches transaction in Monarch via Bridge -> Pushes updates back via Bridge.
* **Protocol:** Uses standard HTTP Request nodes instead of executing ephemeral Python scripts.

## 3. Nuances & "Gotchas"

* **The "1-Hour" Timeout:** Monarch aggressively invalidates sessions after ~1 hour of inactivity. The Bridge service runs a background thread (`keep_alive`) that pings the API every 15 minutes to prevent this.
* **Cloudflare Blocking (Error 525/403):** Monarch blocks standard Python User-Agents. We must inject a "Chrome on MacOS" User-Agent header into the `MonarchMoney` instance headers to bypass this.
* **API Endpoint Changes:** Monarch migrated from `api.monarchmoney.com` to `api.monarch.com`. The `monarchmoneycommunity` fork addresses this, but we must ensure we are installing the fork, not the stale PyPI package.
* **GraphQL Compatibility:** The `monarchmoneycommunity` fork has been updated to support `gql>=4.0`, resolving previous breaking changes. We use `gql>=4.0` for stability.
* **Asynchronous Implementation:** The community fork is fully asynchronous. The Bridge service is built with `async/await` to match this, improving performance and compatibility.
* **MFA Handling:** The initial login requires Multi-Factor Authentication. The Bridge exposes an `/auth/mfa` endpoint to handle this interactively.
* **Automated Login & MFA:** If `MONARCH_EMAIL`, `MONARCH_PASSWORD`, and optionally `MONARCH_MFA_SECRET` (TOTP secret) are provided as environment variables, the Bridge will attempt to authenticate automatically on startup if no saved session exists.

## 4. Implementation Plan

### Phase 1: The Bridge Service (Docker)

**Goal:** Get a container running that listens on port 8000 and can talk to Monarch.

1. **Create Project Directory:**

* `mkdir /mnt/user/appdata/monarch-bridge` (or your preferred location).
* Create `main.py` (The FastAPI app).
* Create `Dockerfile`.

1. **Develop `main.py`:**

* Initialize FastAPI.
* Import `MonarchMoney` from the community fork.
* Implement `POST /auth/login` and `POST /auth/mfa`.
* Implement `GET /transactions` and `PATCH /transactions/{id}`.
* **Crucial:** Add the background `asyncio` loop for keep-alive pings.

1. **Dockerize with the Fork:**

* In the `Dockerfile`, use this installation command to get the active fork:

```dockerfile
RUN pip install git+https://github.com/bradleyseanf/monarchmoneycommunity.git
RUN pip install "gql>=4.0" fastapi uvicorn pydantic

```

1. **Deployment:**

* Build: `docker build -t monarch-bridge .`
* Run: `docker run -d -p 8000:8000 -v ./data:/data --name monarch-bridge monarch-bridge`

### Phase 2: Authentication & Testing

**Goal:** Authenticate the bridge once and verify session persistence.

1. **Initial Login:**

* Open Swagger UI: `http://<server-ip>:8000/docs`.
* Use `/auth/login` endpoint with your credentials.
* If 401 (MFA Required), use `/auth/mfa` with the code sent to email/SMS.

1. **Verify Persistence:**

* Check that `monarch_session.pickle` exists in the mapped `/data` volume.
* Restart the container.
* Call `GET /transactions` *without* logging in again. It should work immediately.

### Phase 3: n8n Workflow Refactor

**Goal:** Replace fragile script nodes with robust HTTP nodes.

1. **Refactor "Fetch" Step:**

* Delete the `Execute Command` node running `monarch_fetch.py`.
* Add **HTTP Request** node:
* Method: `GET`
* URL: `http://monarch-bridge:8000/transactions?days=30`

1. **Refactor "Update" Step:**

* Delete the `Execute Command` node running `monarch_update.py`.
* Add **HTTP Request** node:
* Method: `PATCH`
* URL: `http://monarch-bridge:8000/transactions/{{ $json.monarch_id }}`
* Body: `{"note": "{{ $json.new_note }}"}`

1. **Simplify Logic:**

* Remove "Split in Batches" loops if the API handles updates fast enough (FastAPI is async, so it handles concurrent requests well, though Monarch might rate-limit. Keep batch size 1 for safety initially).

### Phase 4: Maintenance

1. **Watchdog:**

* Add a simple check in n8n: If the HTTP Request fails with 401, send a notification (Email/Telegram) saying "Monarch Session Expired - Login Required".

1. **Updates:**

* Periodically rebuild the container to pull the latest commits from `monarchmoneycommunity`.

---

## 5. Code Snippets

### Dockerfile (Optimized)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install git to clone the fork
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install dependencies
# We install the fork directly to get the latest API fixes
RUN pip install git+https://github.com/bradleyseanf/monarchmoneycommunity.git
RUN pip install "gql>=4.0" fastapi uvicorn pydantic requests

COPY main.py .

# Persistence volume
VOLUME /data

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

```
