from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import threading
import urllib.parse
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import jwt
from jwt import PyJWKClient

AUTH_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
AGENT_NAME = "XEON Work Engine"


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def parse_args():
    p = argparse.ArgumentParser(description="Authorize XEON Work Engine to use your ChatGPT plan.")
    p.add_argument("--output", default="chatgpt-plan.json")
    p.add_argument("--port", type=int, default=1455)
    p.add_argument("--host-id", default="", help="Stable ext_agent_host_id for the target VM. Defaults to a new urn:uuid.")
    return p.parse_args()


def main():
    args = parse_args()
    host_id = args.host_id.strip() or ("urn:uuid:" + str(uuid.uuid4()))
    redirect_uri = f"http://127.0.0.1:{args.port}/auth/callback"
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    result: dict[str, str] = {}
    done = threading.Event()

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_response(404); self.end_headers(); return
            params = urllib.parse.parse_qs(parsed.query)
            for key, values in params.items():
                if values:
                    result[key] = values[0]
            ok = result.get("state") == state and bool(result.get("code")) and not result.get("error")
            self.send_response(200 if ok else 400)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            message = "XEON Work wurde autorisiert. Dieses Fenster kann geschlossen werden." if ok else "Autorisierung fehlgeschlagen. Zurück zum Terminal."
            self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'><h2>{message}</h2></body></html>".encode())
            done.set()

        def log_message(self, *_):
            return

    server = HTTPServer(("127.0.0.1", args.port), Callback)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    query = {
        "client_id": "dynamic_agent_client",
        "agent_name_hint": AGENT_NAME,
        "ext_agent_host_id": host_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(query)
    print("Öffne ChatGPT-Anmeldung im Browser …")
    print(url)
    webbrowser.open(url)
    if not done.wait(timeout=600):
        server.shutdown()
        raise SystemExit("Timeout: keine OAuth-Rückmeldung erhalten.")
    server.shutdown()

    if result.get("state") != state:
        raise SystemExit("OAuth state mismatch.")
    if result.get("error"):
        raise SystemExit("OAuth abgelehnt: " + result["error"])
    issued_client_id = result.get("client_id")
    if not issued_client_id or issued_client_id == "dynamic_agent_client":
        raise SystemExit("Kein ausgestellter client_id erhalten.")

    with httpx.Client(timeout=30) as client:
        response = client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": issued_client_id,
                "code": result["code"],
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "resource": RESOURCE,
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    if response.status_code != 200:
        raise SystemExit(f"Token exchange fehlgeschlagen: {response.status_code} {response.text[:800]}")
    token = response.json()
    id_token = token.get("id_token")
    if not id_token:
        raise SystemExit("ID token fehlt.")

    signing_key = PyJWKClient(JWKS_URL).get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=issued_client_id,
        issuer=ISSUER,
        options={"require": ["exp", "iss", "sub"]},
    )
    if claims.get("nonce") != nonce:
        raise SystemExit("OIDC nonce mismatch.")

    scopes = str(token.get("scope") or result.get("scope") or "").split()
    if "chatgpt.tokens.use.direct" not in scopes:
        raise SystemExit("ChatGPT-Plan-Nutzung wurde nicht freigegeben.")

    credential = {
        "email": claims.get("email", ""),
        "issuer": ISSUER,
        "subject": claims["sub"],
        "client_id": issued_client_id,
        "ext_agent_host_id": host_id,
        "id_token": id_token,
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "token_type": token.get("token_type", "Bearer"),
        "expires_in": token.get("expires_in", 3600),
        "earliest_refresh_at": token.get("earliest_refresh_at"),
        "scopes": scopes,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    if not credential["access_token"] or not credential["refresh_token"]:
        raise SystemExit("Access- oder Refresh-Token fehlt.")

    path = Path(args.output).expanduser().resolve()
    path.write_text(json.dumps(credential, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    print(f"Gespeichert: {path}")
    print(f"VM Host ID: {host_id}")
    print("Diese Datei enthält Zugangsdaten. Nicht in Git committen oder weitergeben.")


if __name__ == "__main__":
    main()
