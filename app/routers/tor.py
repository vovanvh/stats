from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.config import settings
from app.proxy import rotate_session, get_proxy, get_session_id
import requests
import socket
import time

router = APIRouter(prefix="/proxy", tags=["proxy"])


@router.get("/test")
async def test_proxy_connection(
    isFree: Optional[bool] = Query(False, description="Test free Tor proxy instead of paid residential proxy")
):
    """Test if the proxy is working by checking external IP"""
    try:
        # Get direct IP first
        direct_response = requests.get("https://httpbin.org/ip", timeout=10, proxies={})
        direct_ip = direct_response.json().get("origin")

        # Get proxy config and test it
        proxy_config = get_proxy(is_free=isFree)
        proxies = {
            'http': proxy_config.http_url,
            'https': proxy_config.https_url
        }

        proxied_response = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=30)
        proxied_ip = proxied_response.json().get("origin")

        return {
            "provider": proxy_config.provider,
            "session_id": proxy_config.session_id if not isFree else None,
            "direct_ip": direct_ip,
            "proxied_ip": proxied_ip,
            "proxy_working": direct_ip != proxied_ip
        }
    except Exception as e:
        return {
            "error": str(e),
            "provider": "tor" if isFree else settings.PROXY_PROVIDER
        }


@router.post("/new-identity")
async def request_new_identity(
    isFree: Optional[bool] = Query(False, description="Rotate free Tor proxy instead of paid residential proxy")
):
    """
    Request a new IP address from the current proxy provider.

    - isFree=true: Sends NEWNYM signal to Tor to switch circuit (rate-limited to ~10 seconds)
    - isFree=false: Rotates session ID for paid residential proxy (instant new IP)
    """
    if isFree:
        return await _rotate_tor_identity()
    else:
        return await _rotate_paid_proxy_session()


async def _rotate_paid_proxy_session():
    """Rotate session ID for paid residential proxy to get a new IP"""
    provider = settings.PROXY_PROVIDER.lower()
    old_session = get_session_id()

    print(f"[PROXY] Rotating session for {provider}, old session: {old_session}")

    # Generate new session ID
    new_session = rotate_session()

    print(f"[PROXY] New session ID: {new_session}")

    # Verify new IP
    new_ip = None
    try:
        proxy_config = get_proxy(is_free=False)
        proxies = {
            'http': proxy_config.http_url,
            'https': proxy_config.https_url
        }
        response = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=30)
        new_ip = response.json().get("origin")
    except Exception as e:
        print(f"[PROXY] Could not verify new IP: {e}")

    return {
        "status": "success",
        "provider": provider,
        "old_session_id": old_session,
        "new_session_id": new_session,
        "new_ip": new_ip,
        "message": f"Session rotated for {provider}. New requests will use a different IP."
    }


async def _rotate_tor_identity():
    """Send NEWNYM signal to Tor to get a new circuit/IP"""
    control_port = 9051
    control_password = "my-stats-tor-2026"

    try:
        print(f"[TOR] Requesting new identity via control port {settings.TOR_PROXY_HOST}:{control_port}")

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((settings.TOR_PROXY_HOST, control_port))

        auth_cmd = f'AUTHENTICATE "{control_password}"\r\n'
        s.send(auth_cmd.encode())
        response = s.recv(1024).decode()

        if "250 OK" not in response:
            s.close()
            print(f"[TOR] Authentication failed: {response}")
            raise HTTPException(
                status_code=500,
                detail=f"Tor control port authentication failed: {response.strip()}"
            )

        s.send(b'SIGNAL NEWNYM\r\n')
        response = s.recv(1024).decode()

        if "250 OK" not in response:
            s.close()
            print(f"[TOR] NEWNYM signal failed: {response}")
            raise HTTPException(
                status_code=500,
                detail=f"Tor NEWNYM signal failed: {response.strip()}"
            )

        s.send(b'GETINFO circuit-status\r\n')
        s.recv(4096)

        s.send(b'QUIT\r\n')
        s.close()

        print("[TOR] New identity requested successfully")

        time.sleep(1)

        new_ip = None
        try:
            proxy_config = get_proxy(is_free=True)
            proxies = {
                'http': proxy_config.http_url,
                'https': proxy_config.https_url
            }
            response = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=15)
            new_ip = response.json().get("origin")
        except Exception as e:
            print(f"[TOR] Could not verify new IP: {e}")

        return {
            "status": "success",
            "provider": "tor",
            "new_ip": new_ip,
            "message": "New Tor identity requested. New circuit established.",
            "note": "Tor rate-limits this request to approximately once per 10 seconds."
        }

    except socket.timeout:
        print("[TOR] Connection timeout to control port")
        raise HTTPException(
            status_code=504,
            detail=f"Timeout connecting to Tor control port at {settings.TOR_PROXY_HOST}:{control_port}"
        )
    except ConnectionRefusedError:
        print("[TOR] Connection refused to control port")
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Tor control port at {settings.TOR_PROXY_HOST}:{control_port}. Ensure control port is enabled in torrc."
        )
    except Exception as e:
        print(f"[TOR] Error requesting new identity: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error requesting new Tor identity: {str(e)}"
        )
