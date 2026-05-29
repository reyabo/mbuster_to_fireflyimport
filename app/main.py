"""FastAPI web application.

Designed to run in a homelab behind Tailscale: it binds to all interfaces but
expects the network layer (Tailscale ACLs) to handle access control, so it
adds no authentication of its own. Do **not** expose it directly to the public
internet.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

from . import __version__
from .config import settings
from .csvexport import to_config, to_csv
from .firefly import FireflyClient, FireflyError
from .models import FireflyTransaction
from .parser import ParseError, parse_export
from .transform import TransformOptions, transform_bills

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="MoneyBuster -> Firefly III importer", version=__version__)


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _options_from_form(
    asset_account: str,
    expense_account: str,
    revenue_account: str,
    currency: str,
    import_tag: str,
    invert_sign: bool,
) -> TransformOptions:
    base = TransformOptions.from_settings(settings)
    return TransformOptions(
        asset_account=asset_account.strip() or base.asset_account,
        expense_account=expense_account.strip() or base.expense_account,
        revenue_account=revenue_account.strip() or base.revenue_account,
        currency=currency.strip() or base.currency,
        import_tag=import_tag.strip(),
        invert_sign=invert_sign,
    )


async def _parse_and_transform(
    file: UploadFile, opts: TransformOptions
) -> list[FireflyTransaction]:
    raw = await file.read()
    text = _decode(raw)
    bills = parse_export(text)
    return transform_bills(bills, opts)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "settings": settings,
            "firefly_configured": settings.firefly_configured,
            "version": __version__,
        },
    )


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz():
    return "ok"


@app.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    file: UploadFile = File(...),
    asset_account: str = Form(""),
    expense_account: str = Form(""),
    revenue_account: str = Form(""),
    currency: str = Form(""),
    import_tag: str = Form("moneybuster"),
    invert_sign: bool = Form(False),
):
    opts = _options_from_form(
        asset_account, expense_account, revenue_account, currency, import_tag,
        invert_sign,
    )
    try:
        transactions = await _parse_and_transform(file, opts)
    except ParseError as exc:
        return templates.TemplateResponse(
            "result.html",
            {"request": request, "error": str(exc), "version": __version__},
            status_code=400,
        )
    return templates.TemplateResponse(
        "preview.html",
        {
            "request": request,
            "transactions": transactions,
            "count": len(transactions),
            "firefly_configured": settings.firefly_configured,
            "version": __version__,
        },
    )


@app.post("/import")
async def do_import(
    request: Request,
    file: UploadFile = File(...),
    asset_account: str = Form(""),
    expense_account: str = Form(""),
    revenue_account: str = Form(""),
    currency: str = Form(""),
    import_tag: str = Form("moneybuster"),
    invert_sign: bool = Form(False),
):
    opts = _options_from_form(
        asset_account, expense_account, revenue_account, currency, import_tag,
        invert_sign,
    )
    try:
        transactions = await _parse_and_transform(file, opts)
    except ParseError as exc:
        return templates.TemplateResponse(
            "result.html",
            {"request": request, "error": str(exc), "version": __version__},
            status_code=400,
        )

    if not settings.firefly_configured:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "error": "Firefly III is not configured. Set FIREFLY_BASE_URL "
                "and FIREFLY_TOKEN, or use the CSV download instead.",
                "version": __version__,
            },
            status_code=400,
        )

    try:
        client = FireflyClient(settings.firefly_base_url, settings.firefly_token)
        results = await client.create_transactions(
            transactions,
            error_if_duplicate=settings.error_if_duplicate,
            apply_rules=settings.apply_rules,
        )
    except FireflyError as exc:
        return templates.TemplateResponse(
            "result.html",
            {"request": request, "error": str(exc), "version": __version__},
            status_code=502,
        )

    summary = {
        "created": sum(1 for r in results if r.status == "created"),
        "duplicate": sum(1 for r in results if r.status == "duplicate"),
        "error": sum(1 for r in results if r.status == "error"),
    }
    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "results": results,
            "summary": summary,
            "version": __version__,
        },
    )


@app.post("/download/csv")
async def download_csv(
    file: UploadFile = File(...),
    asset_account: str = Form(""),
    expense_account: str = Form(""),
    revenue_account: str = Form(""),
    currency: str = Form(""),
    import_tag: str = Form("moneybuster"),
    invert_sign: bool = Form(False),
):
    opts = _options_from_form(
        asset_account, expense_account, revenue_account, currency, import_tag,
        invert_sign,
    )
    transactions = await _parse_and_transform(file, opts)
    data = to_csv(transactions)
    return Response(
        content=data,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=firefly_import.csv"
        },
    )


@app.post("/download/config")
async def download_config(
    currency: str = Form(""),
    import_tag: str = Form("moneybuster"),
):
    opts = _options_from_form("", "", "", currency, import_tag, False)
    data = to_config(opts)
    return Response(
        content=data,
        media_type="application/json",
        headers={
            "Content-Disposition": "attachment; filename=firefly_import.json"
        },
    )
