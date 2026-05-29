"""FastAPI web application.

Intended to run in a homelab behind Tailscale + Caddy. It has no built-in
authentication; network access control is delegated to Tailscale. Never expose
it directly to the public internet.

Flow: upload -> parse -> preview (dry run) -> explicit import to the Firefly
III API. Uploads are written to ``<DATA_DIR>/uploads`` only and re-read for the
import step (so the preview the user confirms is exactly what gets imported).
"""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__
from .config import settings
from .firefly import FireflyClient, FireflyError
from .firefly.mapper import MapOptions, build_proposals
from .history import ImportHistory
from .models import ExportType, ImportMode, ImportProposal, ImportStatus
from .parsers import ParseError, parse
from .rules import load_rules

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="MoneyBuster -> Firefly III", version=__version__)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

history = ImportHistory(settings.history_db_path)


def _rules():
    return load_rules(settings.rules_path)


async def _asset_accounts() -> tuple[list[str], str | None]:
    """Best-effort asset account list for the dropdown; never raises."""

    if not settings.firefly_configured:
        return [], "Firefly III ist nicht konfiguriert."
    try:
        client = FireflyClient(settings.firefly_url, settings.token)
        return await client.list_account_names("asset"), None
    except (FireflyError, Exception) as exc:  # noqa: BLE001 - UI must stay up
        return [], f"Firefly nicht erreichbar: {exc}"


def _save_upload(content: bytes, filename: str) -> str:
    token = secrets.token_hex(8)
    suffix = Path(filename).suffix or ".dat"
    (settings.uploads_path / f"{token}{suffix}").write_bytes(content)
    return f"{token}{suffix}"


def _read_upload(token: str) -> tuple[bytes, str]:
    # token is a filename produced by _save_upload; guard against traversal.
    name = Path(token).name
    path = settings.uploads_path / name
    if not path.is_file():
        raise FileNotFoundError("Upload nicht gefunden (bitte erneut hochladen).")
    return path.read_bytes(), name


def _map_options(self_name: str, asset_account: str, mode: str) -> MapOptions:
    # The asset account is the user's own source/destination account. It must
    # NEVER fall back to the expense account; use the configured default asset
    # account (which may be empty -> surfaced as a warning in the preview).
    return MapOptions(
        self_name=self_name.strip() or settings.self_name,
        asset_account=asset_account.strip() or settings.default_asset_account,
        mode=ImportMode(mode),
        import_tag=settings.import_tag,
    )


def _build(
    content: bytes, filename: str, export_type: str, opts: MapOptions
) -> tuple[list[ImportProposal], ParseResult]:
    result = parse(content, filename, ExportType(export_type))
    proposals = build_proposals(result.bills, opts, _rules())
    known = history.known_ids([p.external_id for p in proposals])
    for p in proposals:
        if p.external_id in known:
            p.should_import = False
            p.status = ImportStatus.probably_imported
            p.status_message = "Bereits importiert (lokale Import-Historie)."
    return proposals, result


# --- routes ---------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    accounts, ff_error = await _asset_accounts()
    ff_info = None
    if settings.firefly_configured and not ff_error:
        try:
            client = FireflyClient(settings.firefly_url, settings.token)
            ff_info = await client.test_connection()
        except FireflyError as exc:
            ff_error = str(exc)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "version": __version__,
            "settings": settings,
            "accounts": accounts,
            "ff_error": ff_error,
            "ff_info": ff_info,
            "modes": list(ImportMode),
            "export_types": list(ExportType),
            "history_count": history.count(),
        },
    )


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz():
    return "ok"


@app.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request):
    return templates.TemplateResponse(
        "rules.html",
        {
            "request": request,
            "version": __version__,
            "rules": _rules(),
            "rules_path": str(settings.rules_path),
        },
    )


@app.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    file: UploadFile = File(...),
    export_type: str = Form("auto"),
    self_name: str = Form(""),
    asset_account: str = Form(""),
    mode: str = Form("real_payment"),
):
    content = await file.read()
    opts = _map_options(self_name, asset_account, mode)
    try:
        proposals, result = _build(content, file.filename or "", export_type, opts)
    except ParseError as exc:
        return _error(request, str(exc), status=400)

    orig_filename = file.filename or "upload.csv"
    token = _save_upload(content, orig_filename)
    importable = sum(1 for p in proposals if p.should_import)
    return templates.TemplateResponse(
        "preview.html",
        {
            "request": request,
            "version": __version__,
            "proposals": proposals,
            "warnings": result.warnings,
            "equal_shares_note": result.fmt == "csv",
            "asset_missing": not opts.asset_account,
            "count": len(proposals),
            "importable": importable,
            "token": token,
            "filename": orig_filename,
            "export_type": export_type,
            "self_name": opts.self_name,
            "asset_account": opts.asset_account,
            "mode": mode,
            "firefly_configured": settings.firefly_configured,
        },
    )


@app.post("/import", response_class=HTMLResponse)
async def do_import(request: Request):
    form = await request.form()
    token = str(form.get("token", ""))
    filename = str(form.get("filename", "")) or "upload.csv"
    export_type = str(form.get("export_type", "auto"))
    self_name = str(form.get("self_name", ""))
    asset_account = str(form.get("asset_account", ""))
    mode = str(form.get("mode", "real_payment"))
    selected = set(form.getlist("selected"))

    if not settings.firefly_configured:
        return _error(
            request,
            "Firefly III ist nicht konfiguriert (FIREFLY_URL / FIREFLY_TOKEN).",
            status=400,
        )

    try:
        content, _ = _read_upload(token)
    except FileNotFoundError as exc:
        return _error(request, str(exc), status=400)

    opts = _map_options(self_name, asset_account, mode)
    try:
        proposals, _result = _build(content, filename, export_type, opts)
    except ParseError as exc:
        return _error(request, str(exc), status=400)

    to_import = [
        p
        for p in proposals
        if p.should_import and (not selected or p.external_id in selected)
    ]

    outcomes = []
    summary = {"created": 0, "duplicate": 0, "skipped": 0, "error": 0}
    try:
        client = FireflyClient(settings.firefly_url, settings.token)
        if settings.auto_create_expense_accounts:
            for name in {p.destination_account for p in to_import}:
                await client.ensure_expense_account(name)
        if settings.auto_create_categories:
            for name in {p.category for p in to_import if p.category}:
                await client.ensure_category(name)

        for proposal in to_import:
            outcome = await client.create_transaction(
                proposal,
                error_if_duplicate=settings.error_if_duplicate,
                apply_rules=settings.apply_rules,
            )
            if outcome.status == "created":
                history.record(
                    proposal.external_id,
                    date=proposal.date,
                    amount=str(proposal.import_amount),
                    description=outcome.description,
                    firefly_transaction_id=outcome.firefly_id,
                )
            summary[outcome.status] = summary.get(outcome.status, 0) + 1
            outcomes.append(outcome)
    except FireflyError as exc:
        return _error(request, str(exc), status=502)

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "version": __version__,
            "outcomes": outcomes,
            "summary": summary,
            "firefly_url": settings.firefly_url,
        },
    )


def _error(request: Request, message: str, status: int = 400):
    return templates.TemplateResponse(
        "result.html",
        {"request": request, "version": __version__, "error": message},
        status_code=status,
    )
