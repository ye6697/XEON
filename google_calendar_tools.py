import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover - handled at runtime
    Request = None
    Credentials = None
    InstalledAppFlow = None
    build = None


SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarTools:
    def __init__(
        self,
        client_secret_file: str = "",
        token_file: str = "data/google-calendar-token.json",
        calendar_id: str = "primary",
        timezone: str = "Europe/Berlin",
    ):
        self.client_secret_file = client_secret_file
        self.token_file = token_file
        self.calendar_id = calendar_id or "primary"
        self.timezone = timezone
        self._service = None

    @property
    def dependencies_available(self) -> bool:
        return all([Request, Credentials, InstalledAppFlow, build])

    def _tz(self):
        return ZoneInfo(self.timezone)

    def _parse_dt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self._tz())
        return dt

    def _service_client(self):
        if not self.dependencies_available:
            raise RuntimeError(
                "Google Calendar API Pakete fehlen. Installiere: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            )
        if self._service:
            return self._service

        token_path = Path(self.token_file)
        client_secret_path = Path(self.client_secret_file) if self.client_secret_file else None
        creds = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not client_secret_path or not client_secret_path.exists():
                    raise RuntimeError(
                        "Google Calendar API ist noch nicht verbunden. Lege eine OAuth-Client-Datei ab und setze `google_calendar_client_secret_file` in config.json."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def list_events(self, start: str | None = None, end: str | None = None, max_results: int = 20) -> str:
        now = datetime.now(self._tz())
        start_dt = self._parse_dt(start) or now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = self._parse_dt(end) or (start_dt + timedelta(days=7))

        service = self._service_client()
        result = service.events().list(
            calendarId=self.calendar_id,
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            maxResults=max(1, min(int(max_results or 20), 50)),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = result.get("items", [])
        if not events:
            return f"Keine Termine von {start_dt:%d.%m.%Y %H:%M} bis {end_dt:%d.%m.%Y %H:%M} gefunden."

        lines = []
        for event in events:
            start_value = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            end_value = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
            title = event.get("summary", "Ohne Titel")
            lines.append(f"- {start_value} bis {end_value}: {title}")
        return "Kalendertermine:\n" + "\n".join(lines)

    def create_event(
        self,
        title: str,
        start: str,
        end: str | None = None,
        duration_minutes: int = 30,
        description: str = "",
    ) -> str:
        if not title or not start:
            return "Fuer einen Kalendertermin brauche ich mindestens Titel und Startzeit."

        start_dt = self._parse_dt(start)
        if not start_dt:
            return "Startzeit konnte nicht gelesen werden."
        end_dt = self._parse_dt(end) if end else start_dt + timedelta(minutes=int(duration_minutes or 30))

        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": self.timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": self.timezone},
        }
        event = self._service_client().events().insert(calendarId=self.calendar_id, body=body).execute()
        link = event.get("htmlLink", "")
        return f"Termin erstellt: {title}, {start_dt:%d.%m.%Y %H:%M} bis {end_dt:%H:%M}. {link}".strip()

    def execute_plan(self, plan: dict) -> str:
        operation = str(plan.get("operation", "list")).lower()
        if operation in {"list", "read"}:
            return self.list_events(plan.get("start"), plan.get("end"), plan.get("max_results", 20))
        if operation in {"create", "insert"}:
            return self.create_event(
                title=plan.get("title") or plan.get("summary") or "",
                start=plan.get("start") or "",
                end=plan.get("end"),
                duration_minutes=plan.get("duration_minutes", 30),
                description=plan.get("description", ""),
            )
        return "Diese Kalenderoperation ist in der direkten Google API noch nicht freigegeben. Erlaubt sind: list/read und create."
