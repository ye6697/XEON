#!/usr/bin/env bash
# Persistent iPhone-friendly setup: official Ortie device-code OAuth with a
# Cloud Shell tmux session so switching apps does not stop the token poll.
# Never prints Google credentials, OAuth tokens, refresh tokens or callbacks.
set -euo pipefail

INSTALLER_URL='https://raw.githubusercontent.com/ye6697/XEON/cd4c7bc1aa6333d6fa225241a0ff5bd894ea30d4/scripts/hermes-outlook-cloudshell-setup.py'
SESSION='xeon-outlook'
if ! command -v tmux >/dev/null 2>&1; then
  printf '%s\n' 'Fehler: tmux ist in dieser Cloud Shell nicht verfügbar.' >&2
  exit 1
fi
if ! command -v gcloud >/dev/null 2>&1; then
  printf '%s\n' 'Fehler: Google Cloud CLI ist nicht verfügbar.' >&2
  exit 1
fi
if ! tmux has-session -t "=${SESSION}" 2>/dev/null; then
  address="${XEON_OUTLOOK_ADDRESS:-}"
  if [ -z "$address" ]; then
    read -r -p 'Welche Outlook-/Live-Mailadresse soll XEON verbinden? ' address
  fi
  if [[ ! "$address" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
    echo 'Ungültige E-Mail-Adresse.' >&2
    exit 1
  fi
  dir="${HOME}/.cache/xeon-outlook-onboarding"
  mkdir -p "$dir"
  chmod 0700 "$dir"
  curl --fail --show-error --silent --location "$INSTALLER_URL" -o "$dir/setup.py"
  chmod 0600 "$dir/setup.py"
  printf -v quoted_address '%q' "$address"
  printf -v quoted_script '%q' "$dir/setup.py"
  # The script runs in tmux's own session, not in the mobile terminal process.
  # After it exits, keep the pane for reading only its sanitized status.
  command="XEON_OUTLOOK_ADDRESS=${quoted_address} python3 -u ${quoted_script}; result=\$?; echo; echo \"Einrichtung beendet (Status \$result). Keine OAuth-Tokens hier posten.\"; exec bash"
  tmux new-session -d -s "$SESSION" "$command"
  echo 'Die Outlook-Einrichtung läuft in einer wiederverbindbaren Cloud-Shell-Sitzung.'
else
  echo 'Bestehende Outlook-Sitzung gefunden. Verbinde erneut ...'
fi

echo 'Beim Wechsel zu Safari bleibt der Vorgang in tmux aktiv.'
echo 'Microsoft ausschließlich über https://microsoft.com/devicelogin öffnen.'
echo 'Wenn Safari 127.0.0.1 aufruft, nicht den alten Link wiederverwenden.'
echo 'Nach Rückkehr zu Cloud Shell den gleichen Befehl erneut ausführen, um die Sitzung wieder zu öffnen.'
# Cloud Shell itself may already be inside tmux. Avoid nested session warning.
env -u TMUX tmux attach-session -t "$SESSION"
