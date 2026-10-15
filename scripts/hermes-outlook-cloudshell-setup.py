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
    try:
        res = subprocess.run(["gcloud", *args, "--project", PROJECT], check=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        return res.stdout.decode("utf-8").strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        raise SafeError("GCP-Zugriff nicht möglich. Cloud-Shell-Projekt und Berechtigungen prüfen.") from None


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
    cfg = """[accounts.outlook]
default = true
client-id = "{client}"
grant = "authorization-code"
pkce = "s256"
auto-refresh = true
endpoints.authorization = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
endpoints.token = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
endpoints.redirection = "https://localhost"
scopes = ["https://outlook.office.com/IMAP.AccessAsUser.All", "https://outlook.office.com/SMTP.Send", "offline_access"]
storage.read.command = ["cat", "{tokenfile}"]
storage.write.command = "umask 077; cat > '{tokenfile}'"
""".format(client=CLIENT, tokenfile=token_path)
    config.write_text(cfg, encoding="utf-8")
    if tomllib.loads(cfg)["accounts"]["outlook"]["client-id"] != CLIENT:
        raise SafeError("OAuth-Konfiguration ungültig.")
    base = [str(binary), "--json", "-c", str(config), "-a", "outlook"]
    start = subprocess.run([*base, "auth", "get"], capture_output=True, timeout=40)
    if start.returncode:
        raise SafeError("Microsoft-Autorisierung konnte nicht gestartet werden.")
    try:
        data = json.loads(start.stdout)
        url = recursive_find(data, "authorization_uri")
        state = recursive_find(data, "state")
        verifier = recursive_find(data, "pkce_code_verifier")
        if not all(isinstance(x, str) and x for x in (url, state, verifier)):
            raise ValueError
    except (ValueError, TypeError):
        raise SafeError("Ortie lieferte kein gültiges OAuth-Handoff.") from None
    if urllib.parse.urlparse(url).hostname != "login.microsoftonline.com":
        raise SafeError("Unbekannte Microsoft-Anmeldeseite.")
    print("\n1. Öffne diese Microsoft-Anmeldeseite auf deinem iPhone:\n" + url)
    print("\n2. Melde dich mit " + ADDRESS + " an und bestätige den Zugriff.")
    print("3. Safari kann danach 'localhost nicht erreichbar' anzeigen; das ist hier normal.")
    redirected = getpass("4. Kopiere die vollständige URL aus der Safari-Adresszeile HIER in Cloud Shell (Eingabe verborgen): ").strip()
    u = urllib.parse.urlparse(redirected)
    q = urllib.parse.parse_qs(u.query)
    if (u.scheme != "https" or u.hostname != "localhost" or
            len(redirected) > 8192 or q.get("state") != [state] or len(q.get("code", [])) != 1):
        raise SafeError("Ungültiger oder abgelaufener Microsoft-Rücksprung. Bitte neu starten.")
    # Avoid printing subprocess command/args, which contain the one-time OAuth code.
    end = subprocess.run([*base, "auth", "resume", "--state=" + state,
                          "--pkce=" + verifier, redirected],
                         capture_output=True, timeout=45)
    del redirected
    if end.returncode:
        raise SafeError("Microsoft hat den OAuth-Austausch abgelehnt. Es wurde nichts übertragen.")
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
