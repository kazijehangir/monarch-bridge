import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from monarchmoney import MonarchMoney, RequireMFAException, LoginFailedException

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("monarch-bridge")

# Configuration
SESSION_FILE = os.getenv("SESSION_FILE", "/data/monarch_session.pickle")
KEEP_ALIVE_INTERVAL = int(os.getenv("KEEP_ALIVE_INTERVAL", "900"))  # 15 minutes
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Automated Login Config
MONARCH_EMAIL = os.getenv("MONARCH_EMAIL")
MONARCH_PASSWORD = os.getenv("MONARCH_PASSWORD")
MONARCH_MFA_SECRET = os.getenv("MONARCH_MFA_SECRET")

# Global Monarch instance
mm = MonarchMoney()
mm._headers["User-Agent"] = USER_AGENT

def is_authenticated():
    """Checks if the Monarch instance has a token."""
    return mm.token is not None

def save_session():
    """Saves the current session to disk."""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        mm.save_session(SESSION_FILE)
        logger.info(f"Session saved to {SESSION_FILE}")
    except Exception as e:
        logger.error(f"Failed to save session: {e}")

def load_session():
    """Loads the session from disk if it exists."""
    if os.path.exists(SESSION_FILE):
        try:
            mm.load_session(SESSION_FILE)
            logger.info(f"Session loaded from {SESSION_FILE}")
            return True
        except Exception as e:
            logger.error(f"Failed to load session: {e}")
    return False

async def keep_alive_loop():
    """Background task to keep the session alive."""
    while True:
        try:
            if is_authenticated():
                logger.info("Performing keep-alive ping...")
                # Simple API call to keep session active
                await mm.get_accounts()
                logger.info("Keep-alive ping successful.")
            else:
                logger.info("Not logged in, skipping keep-alive.")
        except Exception as e:
            logger.error(f"Keep-alive ping failed: {e}")
        
        await asyncio.sleep(KEEP_ALIVE_INTERVAL)

async def perform_login(email: str, password: str, mfa_secret: Optional[str] = None):
    """Helper to perform login and handle MFA."""
    try:
        await mm.login(email=email, password=password, mfa_secret_key=mfa_secret, use_saved_session=False)
        save_session()
        return {"status": "success", "message": "Logged in successfully"}
    except RequireMFAException:
        return {"status": "mfa_required", "message": "MFA code required"}
    except LoginFailedException as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load session or perform automated login
    session_loaded = load_session()
    
    if not session_loaded and MONARCH_EMAIL and MONARCH_PASSWORD:
        logger.info("Attempting automated login on startup...")
        try:
            res = await perform_login(MONARCH_EMAIL, MONARCH_PASSWORD, MONARCH_MFA_SECRET)
            if res["status"] == "success":
                logger.info("Automated login successful")
            else:
                logger.info(f"Automated login: {res['message']}")
        except Exception as e:
            logger.error(f"Automated login failed: {e}")

    asyncio.create_task(keep_alive_loop())
    yield
    # Shutdown: Save session
    if is_authenticated():
        save_session()

app = FastAPI(
    title="Monarch Money Bridge",
    description="Sidecar service to maintain Monarch Money session and expose a REST API.",
    lifespan=lifespan
)

# Models
class LoginRequest(BaseModel):
    email: str
    password: str
    mfa_secret: Optional[str] = None

class MFARequest(BaseModel):
    email: str
    password: str # Required by the library for MFA
    code: str

class TransactionUpdate(BaseModel):
    notes: Optional[str] = None
    category_id: Optional[str] = None
    needs_review: Optional[bool] = None
    merchant_name: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None

# Endpoints
@app.get("/health")
async def health_check():
    return {"status": "ok", "logged_in": is_authenticated()}

@app.post("/auth/login")
async def login(req: LoginRequest):
    return await perform_login(req.email, req.password, req.mfa_secret)

@app.post("/auth/mfa")
async def mfa(req: MFARequest):
    try:
        await mm.multi_factor_authenticate(req.email, req.password, req.code)
        if is_authenticated():
            save_session()
            return {"status": "success", "message": "MFA successful"}
        else:
            raise HTTPException(status_code=401, detail="MFA failed")
    except Exception as e:
        logger.error(f"MFA error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/transactions")
async def get_transactions(days: int = Query(30, description="Number of days of transactions to fetch")):
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        now = datetime.now()
        start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")
        transactions = await mm.get_transactions(limit=1000, start_date=start_date, end_date=end_date)
        return transactions
    except Exception as e:
        logger.error(f"Error fetching transactions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/transactions/{transaction_id}")
async def update_transaction(transaction_id: str, update: TransactionUpdate):
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        kwargs = {k: v for k, v in update.model_dump().items() if v is not None}
        if not kwargs:
            return {"status": "no_change", "message": "No fields to update"}
            
        await mm.update_transaction(transaction_id, **kwargs)
        return {"status": "success", "message": f"Transaction {transaction_id} updated"}
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)