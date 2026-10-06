from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from chatgpt_plan import access_token, prompt_architect

APP_NAME = "xeon_work_engine"
ROOT = Path(os.environ.get("XEON_WORK_ROOT", "/var/lib/xeon-work"))
JOBS_DIR = ROOT / "jobs"
WORKSPACES_DIR = ROOT / "workspaces"
ALLOWED_REPOS = {x.strip() for x in os.environ.get("XEON_ALLOWED_REPOS", "ye6697/mysuppliexAppcode").split(",") if x.strip()}
WORKER_SECRET = os.environ.get("XEON_WORKER_SECRET", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CODEX_MODEL = os.environ.get("XEON_CODEX_MODEL", "")
MAX_CONCURRENCY = max(1, int(os.environ.get("XEON_WORK_MAX_CONCURRENCY", "1")))
MAX_JOB_SECONDS = max(300, int(os.environ.get("XEON_WORK_MAX_JOB_SECONDS", "5400")))
semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
tasks: dict[str, asyncio.Task] = {}
app = FastAPI(title="XEON Work Engine", version="0.1.0")

for directory in (ROOT, JOBS_DIR, WORKSPACES_DIR):
    directory.mkdir(parents=True, exist_ok=True)


class JobCreate(BaseModel):
    task_id: str
    user_request: str = Field(min_length=4, max_length=12000)
    requested_outcome: str = Field(default="", max_length=12000)
    risk_class: str = "CAT3"
    context: dict[str, Any] = Field(default_factory=dict)
    repository: str
    base_branch: str = "main"
    permissions: dict[str, bool] = Field(default_factory=dict)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def load_job(job_id: str) -> dict[str, Any]:
    path = job_path(job_id)
    if not path.exists():
        raise HTTPException(404, "job_not_found")
    return json.loads(path.read_text(encoding="utf-8"))


def save_job(job: dict[str, Any]) -> dict[str, Any]:
    job["updated_at"] = utcnow()
    path = job_path(job["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return job


def update_job(job_id: str, **patch: Any) -> dict[str, Any]:
    job = load_job(job_id)
    job.update(patch)
    return save_job(job)


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id","status","risk_class","prompt_architect_brief","codex_thread_id","branch","commit_sha",
        "pull_request_url","progress","result","error","created_at","started_at","updated_at","completed_at"
    }
    return {k:v for k,v in job.items() if k in allowed}


async def authenticate(request: Request, body: bytes) -> None:
    if not WORKER_SECRET:
        raise HTTPException(503, "worker_secret_not_configured")
    stamp = request.headers.get("x-xeon-timestamp", "")
    signature = request.headers.get("x-xeon-signature", "")
    try:
        age = abs(int(time.time() * 1000) - int(stamp))
    except ValueError:
        raise HTTPException(401, "invalid_timestamp")
    if age > 5 * 60 * 1000:
        raise HTTPException(401, "stale_request")
    expected = hmac.new(WORKER_SECRET.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "invalid_signature")


async def signed_request(request: Request) -> bytes:
    body = await request.body()
    await authenticate(request, body)
    return body


def git_env(workspace: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if GITHUB_TOKEN:
        askpass = workspace.parent / f".askpass-{workspace.name}.sh"
        askpass.write_text(
            '#!/bin/sh\ncase "$1" in\n  *Username*) echo "x-access-token" ;;\n  *Password*) printf "%s\\n" "$GITHUB_TOKEN" ;;\n  *) echo "" ;;\nesac\n',
            encoding="utf-8",
        )
        askpass.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        env["GIT_ASKPASS"] = str(askpass)
    return env


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), env=env, text=True, capture_output=True, timeout=timeout, check=False)


def redact(value: str) -> str:
    value = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "[REDACTED]", value)
    value = re.sub(r"(?i)(refresh_token|access_token|authorization)\s*[:=]\s*[^\s,]+", r"\1=[REDACTED]", value)
    return value[-12000:]


def ensure_clean_secret_scan(workspace: Path) -> None:
    diff = run(["git", "diff", "--cached", "--no-ext-diff"], workspace, timeout=60)
    text = diff.stdout
    patterns = [
        r"sk-[A-Za-z0-9_-]{20,}",
        r"(?i)refresh_token\s*[:=]",
        r"(?i)access_token\s*[:=]",
        r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]{30,}",
    ]
    if any(re.search(pattern, text) for pattern in patterns):
        run(["git", "reset"], workspace, timeout=30)
        raise RuntimeError("secret_scan_failed")


async def create_pull_request(repository: str, branch: str, base_branch: str, title: str, body: str) -> str:
    if not GITHUB_TOKEN:
        return ""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.github.com/repos/{repository}/pulls",
            headers={
                "authorization": f"Bearer {GITHUB_TOKEN}",
                "accept": "application/vnd.github+json",
                "x-github-api-version": "2022-11-28",
            },
            json={"title": title[:240], "head": branch, "base": base_branch, "body": body[:60000]},
        )
    if response.status_code == 422:
        return ""
    if response.status_code not in (200, 201):
        raise RuntimeError(f"github_pr_failed:{response.status_code}:{response.text[:1000]}")
    return str(response.json().get("html_url") or "")


def codex_command(brief: str) -> list[str]:
    cmd = [
        "codex", "exec", "--json", "--full-auto",
        "-c", 'model_provider="openai_chatgpt_plan"',
        "-c", 'model_providers.openai_chatgpt_plan.name="ChatGPT plan"',
        "-c", 'model_providers.openai_chatgpt_plan.base_url="https://api.openai.com/v1"',
        "-c", 'model_providers.openai_chatgpt_plan.env_key="ACCESS_TOKEN"',
        "-c", 'model_providers.openai_chatgpt_plan.wire_api="responses"',
        "-c", 'model_providers.openai_chatgpt_plan.requires_openai_auth=false',
        "-c", 'model_providers.openai_chatgpt_plan.supports_websockets=false',
    ]
    if CODEX_MODEL:
        cmd += ["--model", CODEX_MODEL]
    cmd.append(brief)
    return cmd


async def run_codex(job_id: str, workspace: Path, brief: str) -> dict[str, Any]:
    token = await access_token()
    env = os.environ.copy()
    env["ACCESS_TOKEN"] = token
    env.pop("OPENAI_API_KEY", None)
    process = await asyncio.create_subprocess_exec(
        *codex_command(brief),
        cwd=str(workspace),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    final_text = ""
    events = 0
    started = time.monotonic()
    while True:
        if time.monotonic() - started > MAX_JOB_SECONDS:
            process.kill()
            await process.wait()
            raise RuntimeError("codex_timeout")
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=2)
        except asyncio.TimeoutError:
            current = load_job(job_id)
            if current.get("status") == "cancelled":
                process.terminate()
                await process.wait()
                raise RuntimeError("cancelled")
            continue
        if not line:
            break
        events += 1
        raw = line.decode("utf-8", "replace").strip()
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        et = str(event.get("type") or "")
        if et in {"item.started","item.completed","turn.started"}:
            item = event.get("item") or {}
            kind = str(item.get("type") or et)
            update_job(job_id, status="testing" if "test" in json.dumps(event).lower() else "executing",
                       progress={"stage":kind,"message":str(item.get("command") or item.get("text") or "")[:500],"events":events})
        if et in {"turn.completed","item.completed"}:
            candidate = event.get("result") or event.get("item",{}).get("text") or event.get("message")
            if candidate:
                final_text = str(candidate)
    stderr = (await process.stderr.read()).decode("utf-8", "replace")
    code = await process.wait()
    if code != 0:
        raise RuntimeError(f"codex_failed:{code}:{redact(stderr)}")
    return {"summary": redact(final_text)[:12000], "events": events, "stderr_tail": redact(stderr)[-3000:]}


async def execute_job(job_id: str) -> None:
    async with semaphore:
        job = load_job(job_id)
        if job.get("status") == "cancelled":
            return
        workspace = WORKSPACES_DIR / job_id
        try:
            update_job(job_id, status="planning", started_at=utcnow(), progress={"stage":"prompt_architect","message":"XEON bereitet den technischen Auftrag aus dem relevanten Kontext vor."})
            architect_input = {
                "task_id": job_id,
                "user_request": job["user_request"],
                "requested_outcome": job.get("requested_outcome") or job["user_request"],
                "risk_class": job["risk_class"],
                "context": job.get("context") or {},
                "permissions": job.get("permissions") or {},
            }
            brief = await prompt_architect(architect_input)
            update_job(job_id, prompt_architect_brief=brief, progress={"stage":"repository","message":"Arbeitskopie wird vorbereitet."})

            repository = job["repository"]
            if repository not in ALLOWED_REPOS:
                raise RuntimeError("repository_not_allowed")
            if workspace.exists():
                shutil.rmtree(workspace)
            workspace.parent.mkdir(parents=True, exist_ok=True)
            env = git_env(workspace)
            clone = run(["git","clone","--branch",job["base_branch"],"--single-branch",f"https://github.com/{repository}.git",str(workspace)], workspace.parent, env=env, timeout=900)
            if clone.returncode != 0:
                raise RuntimeError("git_clone_failed:" + redact(clone.stderr))

            branch = "xeon/work-" + re.sub(r"[^a-zA-Z0-9-]", "-", job_id)[-32:]
            checks = [
                run(["git","config","user.name","XEON Work Engine"],workspace),
                run(["git","config","user.email","xeon-work@users.noreply.github.com"],workspace),
                run(["git","checkout","-b",branch],workspace),
            ]
            if any(x.returncode != 0 for x in checks):
                raise RuntimeError("git_branch_setup_failed")
            update_job(job_id, status="executing", branch=branch, progress={"stage":"codex","message":"Codex untersucht das Repository, plant und setzt die Änderung um."})

            result = await run_codex(job_id, workspace, brief)
            if load_job(job_id).get("status") == "cancelled":
                return
            update_job(job_id, status="reviewing", progress={"stage":"review","message":"Änderungen und Repository-Zustand werden geprüft."})

            status = run(["git","status","--porcelain"],workspace,timeout=60)
            changed = bool(status.stdout.strip())
            commit_sha = ""
            pr_url = ""
            if changed:
                add = run(["git","add","-A"],workspace,timeout=60)
                if add.returncode != 0:
                    raise RuntimeError("git_add_failed:" + redact(add.stderr))
                ensure_clean_secret_scan(workspace)
                commit = run(["git","commit","-m",f"XEON Work: {job['user_request'][:72]}"],workspace,timeout=120)
                if commit.returncode != 0:
                    raise RuntimeError("git_commit_failed:" + redact(commit.stderr))
                commit_sha = run(["git","rev-parse","HEAD"],workspace,timeout=30).stdout.strip()
                push = run(["git","push","-u","origin",branch],workspace,env=env,timeout=900)
                if push.returncode != 0:
                    raise RuntimeError("git_push_failed:" + redact(push.stderr))
                pr_url = await create_pull_request(
                    repository, branch, job["base_branch"],
                    "XEON Work: " + job["user_request"][:180],
                    "Autonomer XEON-Work-Run.\n\n" + (result.get("summary") or "Codex hat die Änderung umgesetzt.")[:12000],
                )

            final_status = "approval_required" if job["risk_class"] == "CAT1" and changed else "completed"
            update_job(
                job_id, status=final_status, commit_sha=commit_sha, pull_request_url=pr_url,
                result={**result,"changed":changed,"repository":repository,"base_branch":job["base_branch"]},
                progress={"stage":"complete","message":"Codex-Run abgeschlossen; Änderungen sind auf einem separaten Branch gesichert."},
                completed_at=utcnow(),
            )
        except Exception as exc:
            if str(exc) == "cancelled":
                update_job(job_id,status="cancelled",completed_at=utcnow(),error="")
            else:
                update_job(job_id,status="failed",error=redact(str(exc)),completed_at=utcnow(),progress={"stage":"failed","message":"Work-Run fehlgeschlagen."})
        finally:
            askpass = workspace.parent / f".askpass-{workspace.name}.sh"
            if askpass.exists():
                askpass.unlink(missing_ok=True)


@app.get("/health")
async def health():
    credentials = Path(os.environ.get("XEON_CHATGPT_CREDENTIALS", "/var/lib/xeon-work/chatgpt-plan.json"))
    return {"ok": True, "chatgpt_plan_credentials": credentials.exists(), "allowed_repositories": sorted(ALLOWED_REPOS)}


@app.post("/v1/jobs")
async def create_job(request: Request):
    raw = await signed_request(request)
    payload = JobCreate.model_validate_json(raw)
    if payload.repository not in ALLOWED_REPOS:
        raise HTTPException(403, "repository_not_allowed")
    job_id = payload.task_id or ("job-" + uuid.uuid4().hex)
    if job_path(job_id).exists():
        return public_job(load_job(job_id))
    job = {
        "id": job_id, "status": "dispatched", "risk_class": payload.risk_class,
        "user_request": payload.user_request, "requested_outcome": payload.requested_outcome,
        "context": payload.context, "repository": payload.repository, "base_branch": payload.base_branch,
        "permissions": payload.permissions, "progress": {"stage":"queued","message":"Cloud-Worker hat den Auftrag angenommen."},
        "created_at": utcnow(), "updated_at": utcnow(), "prompt_architect_brief": "", "result": {}, "error": ""
    }
    save_job(job)
    tasks[job_id] = asyncio.create_task(execute_job(job_id))
    return public_job(job)


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    await signed_request(request)
    return public_job(load_job(job_id))


@app.post("/v1/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    await signed_request(request)
    job = load_job(job_id)
    if job.get("status") in {"completed","failed","cancelled"}:
        return public_job(job)
    task = tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    return public_job(update_job(job_id,status="cancelled",completed_at=utcnow(),progress={"stage":"cancelled","message":"Vom Nutzer abgebrochen."}))


@app.on_event("startup")
async def recover_jobs():
    for path in JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if job.get("status") in {"dispatched","planning","executing","testing","reviewing"}:
            job["status"] = "queued"
            save_job(job)
            tasks[job["id"]] = asyncio.create_task(execute_job(job["id"]))
