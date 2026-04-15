import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.verification.reachability import check_url_reachable, check_url_reachable_sync


# --- Sync tests ---


def test_sync_head_success():
    with patch("src.verification.reachability.httpx.Client") as MockClient:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.head.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client

        assert check_url_reachable_sync("https://arxiv.org") is True
        mock_client.head.assert_called_once()


def test_sync_head_fails_get_succeeds():
    with patch("src.verification.reachability.httpx.Client") as MockClient:
        mock_client = MagicMock()
        mock_client.head.side_effect = Exception("HEAD failed")
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_client.get.return_value = mock_get_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client

        assert check_url_reachable_sync("https://example.com") is True


def test_sync_both_fail():
    with patch("src.verification.reachability.httpx.Client") as MockClient:
        mock_client = MagicMock()
        mock_client.head.side_effect = Exception("HEAD failed")
        mock_client.get.side_effect = Exception("GET failed")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client

        assert check_url_reachable_sync("https://dead-link.com") is False


def test_sync_invalid_url():
    assert check_url_reachable_sync("") is False
    assert check_url_reachable_sync("not-a-url") is False


def test_sync_head_404_get_200():
    with patch("src.verification.reachability.httpx.Client") as MockClient:
        mock_client = MagicMock()
        mock_head_resp = MagicMock()
        mock_head_resp.status_code = 404
        mock_client.head.return_value = mock_head_resp
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_client.get.return_value = mock_get_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client

        assert check_url_reachable_sync("https://example.com/page") is True


# --- Async tests ---


@pytest.mark.asyncio
async def test_async_head_success():
    with patch("src.verification.reachability.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.head.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        assert await check_url_reachable("https://arxiv.org") is True


@pytest.mark.asyncio
async def test_async_both_fail():
    with patch("src.verification.reachability.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.head.side_effect = Exception("HEAD fail")
        mock_client.get.side_effect = Exception("GET fail")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        assert await check_url_reachable("https://dead.com") is False
