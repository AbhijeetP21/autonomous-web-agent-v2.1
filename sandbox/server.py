"""Local, deterministic sandbox site for the autonomous web agent.

Three flows with stable, accessible labels:
  - /todo            client-side todo app (add / complete / delete)
  - /shop -> /checkout/{shipping,payment,confirm,complete}   multi-step form
  - /login -> /dashboard   authentication flow

State (checkout + auth) is kept in an in-memory session dict keyed by a cookie,
so the site is fully offline and resets on restart. Run with:  python -m sandbox.server
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
SESSIONS: dict[str, dict] = {}
VALID_USER, VALID_PASS = "standard_user", "secret_sauce"

app = FastAPI(title="Agent Sandbox")


def _get_session(request: Request) -> tuple[str, dict]:
    sid = request.cookies.get("sid")
    if not sid or sid not in SESSIONS:
        sid = secrets.token_hex(8)
        SESSIONS[sid] = {}
    return sid, SESSIONS[sid]


def _with_cookie(response: Response, sid: str) -> Response:
    response.set_cookie("sid", sid, httponly=True, samesite="lax")
    return response


def _render(request: Request, name: str, sid: str | None = None, **ctx) -> HTMLResponse:
    page = TEMPLATES.TemplateResponse(request, name, ctx)
    if sid is not None:
        _with_cookie(page, sid)
    return page


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return _render(request, "home.html")


@app.get("/todo", response_class=HTMLResponse)
def todo(request: Request):
    return _render(request, "todo.html")


# --- Checkout flow -----------------------------------------------------------
@app.get("/shop", response_class=HTMLResponse)
def shop(request: Request):
    return _render(request, "shop.html")


@app.get("/checkout/shipping", response_class=HTMLResponse)
def shipping_get(request: Request):
    sid, data = _get_session(request)
    return _render(request, "shipping.html", sid=sid, data=data)


@app.post("/checkout/shipping")
def shipping_post(request: Request, full_name: str = Form(""), address: str = Form("")):
    sid, data = _get_session(request)
    if not full_name.strip() or not address.strip():
        return _render(request, "shipping.html", sid=sid,
                       data={"full_name": full_name, "address": address},
                       error="Both name and address are required.")
    data.update(full_name=full_name.strip(), address=address.strip())
    return _with_cookie(RedirectResponse("/checkout/payment", status_code=303), sid)


@app.get("/checkout/payment", response_class=HTMLResponse)
def payment_get(request: Request):
    sid, data = _get_session(request)
    return _render(request, "payment.html", sid=sid, data=data)


@app.post("/checkout/payment")
def payment_post(request: Request, card_number: str = Form(""), card_name: str = Form("")):
    sid, data = _get_session(request)
    if not card_number.strip() or not card_name.strip():
        return _render(request, "payment.html", sid=sid,
                       data={"card_number": card_number, "card_name": card_name},
                       error="Card number and name are required.")
    data.update(card_number=card_number.strip(), card_name=card_name.strip())
    return _with_cookie(RedirectResponse("/checkout/confirm", status_code=303), sid)


@app.get("/checkout/confirm", response_class=HTMLResponse)
def confirm_get(request: Request):
    sid, data = _get_session(request)
    return _render(request, "confirm.html", sid=sid, data=data)


@app.post("/checkout/complete", response_class=HTMLResponse)
def complete_post(request: Request):
    sid, data = _get_session(request)
    order_id = data.get("order_id") or secrets.randbelow(90000) + 10000
    data["order_id"] = order_id
    return _render(request, "complete.html", sid=sid, data=data, order_id=order_id)


# --- Auth flow ---------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return _render(request, "login.html")


@app.post("/login")
def login_post(request: Request, username: str = Form(""), password: str = Form("")):
    sid, data = _get_session(request)
    if username == VALID_USER and password == VALID_PASS:
        data["user"] = username
        return _with_cookie(RedirectResponse("/dashboard", status_code=303), sid)
    return _render(request, "login.html", sid=sid, error="Invalid credentials. Try again.")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    sid, data = _get_session(request)
    if not data.get("user"):
        return _with_cookie(RedirectResponse("/login", status_code=303), sid)
    return _render(request, "dashboard.html", sid=sid, username=data["user"])


@app.get("/logout")
def logout(request: Request):
    sid, data = _get_session(request)
    data.pop("user", None)
    return _with_cookie(RedirectResponse("/login", status_code=303), sid)


def main() -> None:
    port = int(os.getenv("SANDBOX_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
