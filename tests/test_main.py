import pytest
from httpx import AsyncClient, ASGITransport
from main import app, mm, is_authenticated, lifespan, perform_login, load_session, save_session, keep_alive_loop
from unittest.mock import AsyncMock, patch
from monarchmoney import RequireMFAException, LoginFailedException
from fastapi import HTTPException
import asyncio

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.mark.anyio
async def test_health_check_logged_in():
    with patch("main.is_authenticated", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "logged_in": True}

@pytest.mark.anyio
async def test_health_check_logged_out():
    with patch("main.is_authenticated", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "logged_in": False}

@pytest.mark.anyio
async def test_login_success():
    with patch("main.mm.login", new_callable=AsyncMock) as mock_login, \
         patch("main.save_session") as mock_save:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/auth/login", json={"email": "test@example.com", "password": "password"})
        
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_login.assert_called_once()
        mock_save.assert_called_once()

@pytest.mark.anyio
async def test_login_mfa_required():
    with patch("main.mm.login", side_effect=RequireMFAException):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/auth/login", json={"email": "test@example.com", "password": "password"})
        
        assert response.status_code == 200
        assert response.json()["status"] == "mfa_required"

@pytest.mark.anyio
async def test_login_failed():
    with patch("main.mm.login", side_effect=LoginFailedException("Invalid credentials")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/auth/login", json={"email": "test@example.com", "password": "password"})
        
        assert response.status_code == 401
        assert "Invalid credentials" in response.json()["detail"]

@pytest.mark.anyio
async def test_get_transactions_success():
    mock_transactions = [{"id": "1", "amount": 10.0}]
    with patch("main.is_authenticated", return_value=True), \
         patch("main.mm.get_transactions", new_callable=AsyncMock, return_value=mock_transactions):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/transactions?days=30")
        
        assert response.status_code == 200
        assert response.json() == mock_transactions

@pytest.mark.anyio
async def test_get_transactions_unauthenticated():
    with patch("main.is_authenticated", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/transactions")
        assert response.status_code == 401

@pytest.mark.anyio
async def test_update_transaction_success():
    with patch("main.is_authenticated", return_value=True), \
         patch("main.mm.update_transaction", new_callable=AsyncMock) as mock_update:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.patch("/transactions/123", json={"notes": "Updated note"})
        
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_update.assert_called_once_with("123", notes="Updated note")

@pytest.mark.anyio
async def test_update_transaction_no_fields():
    with patch("main.is_authenticated", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.patch("/transactions/123", json={})
        
        assert response.status_code == 200
        assert response.json()["status"] == "no_change"

@pytest.mark.anyio
async def test_mfa_success():
    with patch("main.mm.multi_factor_authenticate", new_callable=AsyncMock) as mock_mfa, \
         patch("main.is_authenticated", return_value=True), \
         patch("main.save_session"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/auth/mfa", json={"email": "t@e.com", "password": "p", "code": "123456"})
        
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        mock_mfa.assert_called_once()

def test_save_session():
    with patch("main.mm.save_session") as mock_save, \
         patch("os.makedirs"):
        save_session()
        mock_save.assert_called_once()

def test_load_session_exists():
    with patch("os.path.exists", return_value=True), \
         patch("main.mm.load_session") as mock_load:
        assert load_session() is True
        mock_load.assert_called_once()

def test_load_session_not_exists():
    with patch("os.path.exists", return_value=False):
        assert load_session() is False

@pytest.mark.anyio
async def test_keep_alive_loop_logged_in():
    with patch("main.is_authenticated", side_effect=[True, Exception("Stop loop")]), \
         patch("main.mm.get_accounts", new_callable=AsyncMock) as mock_get, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(Exception, match="Stop loop"):
            await keep_alive_loop()
        mock_get.assert_called_once()
        mock_sleep.assert_called_once()

@pytest.mark.anyio
async def test_keep_alive_loop_logged_out():
    with patch("main.is_authenticated", side_effect=[False, Exception("Stop loop")]), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(Exception, match="Stop loop"):
            await keep_alive_loop()
        mock_sleep.assert_called_once()

@pytest.mark.anyio
async def test_keep_alive_loop_exception():
    with patch("main.is_authenticated", side_effect=[True, Exception("Stop loop")]), \
         patch("main.mm.get_accounts", side_effect=Exception("API Error")), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(Exception, match="Stop loop"):
            await keep_alive_loop()
        mock_sleep.assert_called_once()

@pytest.mark.anyio

async def test_perform_login_generic_exception():

    with patch("main.mm.login", side_effect=Exception("Unknown Error")):

        with pytest.raises(HTTPException) as exc:

            await perform_login("e", "p")

        assert exc.value.status_code == 500
