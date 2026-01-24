from fastapi import APIRouter, HTTPException
from app.config import settings
import requests
import socket
import time

router = APIRouter(prefix="/tor", tags=["tor"])


@router.get("/test")
async def test_tor_connection():
    """Test if Tor proxy is working by checking external IP"""
    try:
        direct_response = requests.get("https://httpbin.org/ip", timeout=10, proxies={})
        direct_ip = direct_response.json().get("origin")

        if settings.USE_TOR_PROXY:
            proxied_response = requests.get("https://httpbin.org/ip", timeout=30)
            proxied_ip = proxied_response.json().get("origin")

            return {
                "tor_enabled": True,
                "tor_proxy": f"{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}",
                "direct_ip": direct_ip,
                "proxied_ip": proxied_ip,
                "tor_working": direct_ip != proxied_ip
            }
        else:
            return {
                "tor_enabled": False,
                "direct_ip": direct_ip
            }
    except Exception as e:
        return {"error": str(e), "tor_enabled": settings.USE_TOR_PROXY}


@router.post("/new-identity")
async def request_new_tor_identity():
    """
    Force Tor to switch to a new circuit and exit IP address

    Sends NEWNYM signal to Tor control port to request a new identity.
    This is useful when the current exit node is blocked by YouTube or other services.

    Note: Tor rate-limits this signal to approximately once per 10 seconds.
    """
    if not settings.USE_TOR_PROXY:
        raise HTTPException(
            status_code=400,
            detail="Tor proxy is not enabled. Set USE_TOR_PROXY=True to use this endpoint."
        )

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
            proxies = {
                'http': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}',
                'https': f'socks5://{settings.TOR_PROXY_HOST}:{settings.TOR_PROXY_PORT}'
            }
            response = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=15)
            new_ip = response.json().get("origin")
        except Exception as e:
            print(f"[TOR] Could not verify new IP: {e}")

        return {
            "status": "success",
            "message": "New Tor identity requested. New circuit should be established within 1-2 seconds.",
            "new_exit_ip": new_ip,
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
