#!/usr/bin/env python3
"""Public, reusable, credential-free installer: Microsoft OAuth via Cloud Shell -> private Hermes.
No Microsoft credentials, callback URLs, tokens, or refresh tokens are printed,
put in shell history, sent to GitHub, or stored in permanent Cloud Shell files.
"""
from __future__ import annotations
import json
from getpass import getpass
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.parse
import urllib.request
import urllib.error

PROJECT = os.environ.get("XEON_GCP_PROJECT", "") or subprocess.run(
    ["gcloud", "config", "get-value", "project"], capture_output=True,
    text=True, check=False).stdout.strip()
REGION = "europe-west3"
SERVICE = "xeon-personal-hermes"
ADDRESS = os.environ.get("XEON_OUTLOOK_ADDRESS", "")
ORTIE_ASSET = "https://github.com/pimalaya/ortie/releases/download/v2.3.0/ortie.x86_64-linux.tgz"
CLIENT = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"


class SafeError(Exception):
    pass


def gcloud(*args):
    # Never print secret values or full diagnostic output. Classify errors only
    # and tell the owner WHICH Google Cloud permission boundary failed.
    stage = "Cloud Run (XEON-Dienst lesen)" if args[:2] == ("run", "services") else (
        "Secret Manager (Hermes-Zugriffsschlüssel lesen)")
    try:
        res = subprocess.run(["gcloud", *args, "--project", PROJECT],
                             check=False, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=90)
    except FileNotFoundError:
        raise SafeError("Google Cloud CLI ist hier nicht installiert.") from None
    except subprocess.TimeoutExpired:
        raise SafeError(stage + ": Google Cloud antwortet nicht rechtzeitig.") from None
    if res.returncode != 0:
        error = res.stderr.decode("utf-8", "replace").lower()
        if any(x in error for x in ("permission_denied", "permission denied",
                                      "does not have permission", "403", "forbidden")):
            kind = "Zugriff verweigert (IAM-Berechtigung fehlt)"
        elif any(x in error for x in ("unauthenticated", "please run: gcloud auth login",
                                       "no active account", "invalid_grant", "login required")):
            kind = "Google-Cloud-Anmeldung fehlt oder ist abgelaufen"
        elif any(x in error for x in ("not_found", "not found", "404")):
            kind = "Dienst oder Secret-Version nicht gefunden"
        elif "api" in error and ("disabled" in error or "not enabled" in error):
            kind = "Google-Cloud-API nicht aktiviert"
        else:
            kind = "Cloud-CLI-Fehler (Exitcode " + str(res.returncode) + ")"
        raise SafeError(stage + ": " + kind + ". Bitte die genaue Stufe mitteilen; keine Secrets oder Tokens posten.") from None
    return res.stdout.decode("utf-8").strip()


def runtime():
    value = json.loads(gcloud("run", "services", "describe", SERVICE,
                              "--region", REGION, "--format=json"))
    container = value["spec"]["template"]["spec"]["containers"][0]
    envs = {item["name"]: item for item in container.get("env", [])}
    ref = envs["XEON_HERMES_BRIDGE_TOKEN"]["valueFrom"]["secretKeyRef"]
    owner = envs["XEON_PERSONAL_OWNER_ID"]["value"]
    url = value["status"]["url"].rstrip("/")
    secret = gcloud("secrets", "versions", "access", ref["key"], "--secret", ref["name"])
    if not secret or not owner or not url.startswith("https://"):
        raise SafeError("Hermes-Laufzeitkonfiguration unvollständig.")
    return url, owner, secret


def request(url, owner, secret, operation, token=None):
    body = {"owner_id": owner, "operation": operation}
    if token is not None:
        body["email"] = ADDRESS
        body["token"] = token
    data = json.dumps(body, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url + "/integrations/outlook/setup", data=data, method="POST",
        headers={"Authorization": "Bearer " + secret,
                 "Content-Type": "application/json", "Cache-Control": "no-store"})
    try:
        with urllib.request.urlopen(req, timeout=70) as res:
            result = json.load(res)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise SafeError("Der Einrichtungsendpunkt ist noch nicht deployed.") from None
        raise SafeError("Hermes hat die Verbindung abgelehnt (HTTP " + str(err.code) + ").") from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise SafeError("Hermes ist momentan nicht erreichbar.") from None
    return result


def recursive_find(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            result = recursive_find(v, key)
            if result is not None:
                return result
    if isinstance(obj, list):
        for v in obj:
            result = recursive_find(v, key)
            if result is not None:
                return result
    return None


def authorize(tmp: Path):
    binary = tmp / "ortie"
    archive = tmp / "ortie.tgz"
    try:
        urllib.request.urlretrieve(ORTIE_ASSET, archive)
        with tarfile.open(archive, "r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.name == "ortie" and m.isfile()), None)
            if not member or member.size > 100_000_000:
                raise SafeError("Ortie-Archiv nicht wie erwartet.")
            with tar.extractfile(member) as stream, binary.open("wb") as target:
                while data := stream.read(65536):
                    target.write(data)
        binary.chmod(0o700)
        archive.unlink()
    except (OSError, ValueError, StopIteration, urllib.error.URLError):
        raise SafeError("Offizieller Ortie-Download fehlgeschlagen.") from None
    token_path = tmp / "token.json"
    config = tmp / "ortie.toml"
    # The read/write commands belong to upstream Ortie; raw JSON never appears
    # on stdout or in a shell variable and is deleted at the end of this process.
    # Official Microsoft device authorization grant, handled entirely by
    # the unchanged upstream Ortie CLI. No Safari localhost callback, no
    # long authorize URL, no reimplementation of token exchange.
    cfg = """[accounts.outlook]
default = true
client-id = "{client}"
grant = "device"
auto-refresh = true
endpoints.device-authorization = "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode"
endpoints.token = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
scopes = ["https://outlook.office.com/IMAP.AccessAsUser.All", "https://outlook.office.com/SMTP.Send", "offline_access"]
storage.read.command = ["cat", "{tokenfile}"]
storage.write.command = "umask 077; cat > '{tokenfile}'"
""".format(client=CLIENT, tokenfile=token_path)
    config.write_text(cfg, encoding="utf-8")
    if (tomllib.loads(cfg)["accounts"]["outlook"]["client-id"] != CLIENT or
            tomllib.loads(cfg)["accounts"]["outlook"]["grant"] != "device"):
        raise SafeError("OAuth-Konfiguration ungültig.")
    base = [str(binary), "--json", "-c", str(config), "-a", "outlook"]
    start = subprocess.run([*base, "auth", "get"], capture_output=True, timeout=40)
    if start.returncode:
        raise SafeError(
            "Microsoft verweigert die Gerätecode-Anmeldung für diese Anwendung "
            "oder die Berechtigungen. Kein Outlook-Token wurde übertragen.")
    try:
        result = json.loads(start.stdout)
    except (ValueError, TypeError):
        raise SafeError(
            "Ortie antwortet nicht im erwarteten JSON-Format. "
            "Bitte die Ortie-Version prüfen (ohne Ausgabe von Tokens).") from None
    code = recursive_find(result, "user_code")
    device_code = recursive_find(result, "device_code")
    lifetime = recursive_find(result, "expires_in")
    if not isinstance(code, str) or not code.strip():
        raise SafeError(
            "Ortie hat keinen Benutzer-Anmeldecode ausgegeben. "
            "Die Microsoft-Autorisierung wurde noch nicht bestätigt.")
    if not isinstance(device_code, str) or not device_code.strip():
        raise SafeError(
            "Ortie hat keinen Geräte-Token ausgegeben. "
            "Die Microsoft-Autorisierung wurde noch nicht bestätigt.")
    if len(code) > 80 or len(device_code) > 4096:
        raise SafeError("Die Microsoft-Gerätecode-Antwort hat eine ungültige Länge.")
    # Always show the known Microsoft device login page. Do not reject a
    # legitimate authorization just because the provider returns a different
    # alias for verification_uri, and never open a URL from untrusted output.
    verification_url = "https://microsoft.com/devicelogin"
    print("\nMicrosoft-Anmeldung – ohne lange Links oder Safari-Downloads:")
    print("1. Öffne auf deinem iPhone: " + verification_url)
    print("2. Gib diesen kurzen Code ein: " + code)
    print("3. Melde dich mit " + ADDRESS + " an und bestätige den Zugriff.")
    print("4. Lasse diese Cloud Shell geöffnet. Sie wartet auf die Microsoft-Freigabe.")
    try:
        wait = int(lifetime) if isinstance(lifetime, (int, float)) else 900
    except (ValueError, OverflowError):
        wait = 900
    wait = min(max(wait, 60), 900) + 30
    try:
        end = subprocess.run([*base, "auth", "resume", device_code],
                             capture_output=True, timeout=wait)
    except subprocess.TimeoutExpired:
        raise SafeError("Der Microsoft-Gerätecode ist abgelaufen. Bitte erneut starten.") from None
    if end.returncode:
        raise SafeError("Microsoft hat die Anmeldung nicht bestätigt "
                        "oder die Gerätecode-Autorisierung ist abgelaufen.")
    del code, device_code
    if not token_path.is_file():
        raise SafeError("Ortie hat keinen Token gespeichert.")
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("refresh_token"):
            raise ValueError
        return data
    except (OSError, ValueError):
        raise SafeError("Ortie hat keinen dauerhaft erneuerbaren Token geliefert.") from None


def main():
    os.umask(0o077)
    global ADDRESS
    if not PROJECT or PROJECT == "(unset)":
        raise SafeError("Bitte zuerst das richtige Google-Cloud-Projekt auswählen.")
    if not ADDRESS:
        ADDRESS = input("Welche Outlook-/Live-Mailadresse soll XEON verbinden? ").strip()
    if not __import__("re").fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", ADDRESS):
        raise SafeError("Ungültige Mailadresse.")
    print("XEON: einmalige Outlook-Einrichtung (" + ADDRESS + ")")
    url, owner, secret = runtime()
    status = request(url, owner, secret, "status")
    if not status.get("ok"):
        raise SafeError("Hermes-Outlook-Einrichtung ist noch nicht einsatzbereit.")
    if status.get("authorized"):
        print("Outlook ist bereits autorisiert. Prüfe die bestehende Verbindung ...")
        checked = request(url, owner, secret, "check")
        print("Postfach erreichbar." if checked.get("verified") else "Verbindung muss überprüft werden.")
        return
    if status.get("configured"):
        raise SafeError("Hermes hat bereits eine unvollständige Einrichtung. Nicht überschrieben.")
    with tempfile.TemporaryDirectory(prefix="xeon-outlook-") as directory:
        token = authorize(Path(directory))
        result = request(url, owner, secret, "bootstrap", token)
        token = None
        if not result.get("ok") or not result.get("checkpointed"):
            raise SafeError("Hermes hat den OAuth-Token nicht dauerhaft übernommen.")
    checked = request(url, owner, secret, "check")
    if checked.get("verified"):
        print("\nFertig: XEON kann den Outlook-Posteingang über originales Himalaya lesen.")
    else:
        print("\nAutorisierung gespeichert, aber Outlook-Posteingang noch nicht bestätigt.")
        print("Bitte Verbindungseinstellungen prüfen, bevor XEON Nachrichten versendet.")


if __name__ == "__main__":
    try:
        main()
    except (SafeError, KeyboardInterrupt) as err:
        print("\nEinrichtung nicht abgeschlossen: " + (str(err) if isinstance(err, SafeError) else "abgebrochen"), file=sys.stderr)
        sys.exit(1)
