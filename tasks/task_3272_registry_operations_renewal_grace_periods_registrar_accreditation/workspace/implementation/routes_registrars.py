from datetime import timedelta

import db
import clock
import fiscal
from util import fmt_iso, parse_iso, round_half_up_cents
from services import registrar_view, ledger_view, notice_view, domain_view
from middleware import require_roles, body_json, require_fields, pagination_params
from response import success_object, success_list
from errors import (
    err_invalid_request, err_not_found, err_invalid_state, err_stale_version, ApiError,
)
from flask import Blueprint, request

bp = Blueprint("registrars", __name__)

INT_FIELDS = ["iana_number", "application_fee_cents", "annual_fee_cents",
              "escrow_deposit_cents", "technical_test_score"]


def _validate_int(data, name, lo=None, hi=None):
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{name} must be an integer")
    if lo is not None and v < lo:
        raise err_invalid_request(f"{name} below minimum")
    if hi is not None and v > hi:
        raise err_invalid_request(f"{name} above maximum")
    return v


@bp.post("/registrars")
def create_registrar():
    require_roles("RegistryAdmin")
    data = body_json()
    require_fields(data, ["iana_number", "legal_name", "application_fee_cents",
                          "annual_fee_cents", "escrow_deposit_cents",
                          "technical_test_score", "financial_statement_verified"])
    iana = _validate_int(data, "iana_number", 1, 99999)
    _validate_int(data, "application_fee_cents", 0)
    _validate_int(data, "annual_fee_cents", 0)
    _validate_int(data, "escrow_deposit_cents", 0)
    _validate_int(data, "technical_test_score", 0, 100)
    if not isinstance(data["legal_name"], str) or not data["legal_name"]:
        raise err_invalid_request("legal_name must be a non-empty string")
    if not isinstance(data["financial_statement_verified"], bool):
        raise err_invalid_request("financial_statement_verified must be boolean")
    credit_hold = data.get("credit_hold", False)
    if not isinstance(credit_hold, bool):
        raise err_invalid_request("credit_hold must be boolean")
    for r in db.registrars.values():
        if r["iana_number"] == iana:
            raise ApiError("ERR_DUPLICATE_IANA_NUMBER", "iana_number already registered", 409)
    now = clock.now()
    rec = db.new_common(now)
    rec.update({
        "iana_number": iana,
        "legal_name": data["legal_name"],
        "application_fee_cents": data["application_fee_cents"],
        "annual_fee_cents": data["annual_fee_cents"],
        "escrow_deposit_cents": data["escrow_deposit_cents"],
        "technical_test_score": data["technical_test_score"],
        "financial_statement_verified": data["financial_statement_verified"],
        "credit_hold": credit_hold,
        "status": "PENDING_TESTS",
        "accredited_on": None,
        "accredited_version": None,
        "all_in_cost_cents": None,
        "annual_fee_mode": None,
    })
    db.registrars[rec["id"]] = rec
    return success_object(registrar_view(rec), 201)


@bp.get("/registrars")
def list_registrars():
    require_roles("RegistryAdmin", "RegistrarOperator", "RegistryFinance", "AbuseAnalyst")
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = sorted(db.registrars.values(), key=lambda r: r["created_at"])
    if status:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([registrar_view(r) for r in page], limit, offset, total)


@bp.get("/registrars/<rid>")
def get_registrar(rid):
    require_roles("RegistryAdmin", "RegistrarOperator", "RegistryFinance")
    r = db.registrars.get(rid)
    if r is None:
        raise err_not_found()
    return success_object(registrar_view(r))


@bp.patch("/registrars/<rid>")
def patch_registrar(rid):
    require_roles("RegistryAdmin")
    r = db.registrars.get(rid)
    if r is None:
        raise err_not_found()
    data = body_json()
    if "expected_registrar_version" not in data or data["expected_registrar_version"] is None:
        raise err_invalid_request("expected_registrar_version is required")
    ev = data["expected_registrar_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err_invalid_request("expected_registrar_version must be an integer")
    if ev != r["version"]:
        raise err_stale_version()
    if "credit_hold" in data:
        if not isinstance(data["credit_hold"], bool):
            raise err_invalid_request("credit_hold must be boolean")
        r["credit_hold"] = data["credit_hold"]
    if "legal_name" in data:
        if not isinstance(data["legal_name"], str) or not data["legal_name"]:
            raise err_invalid_request("legal_name must be a non-empty string")
        r["legal_name"] = data["legal_name"]
    db.touch(r, clock.now())
    return success_object(registrar_view(r))


def _get_registrar_or_404(rid):
    r = db.registrars.get(rid)
    if r is None:
        raise err_not_found()
    return r


@bp.post("/registrars/<rid>/accredit")
def accredit(rid):
    require_roles("RegistryAdmin")
    r = _get_registrar_or_404(rid)
    if r["status"] != "PENDING_TESTS":
        raise err_invalid_state()
    if r["technical_test_score"] < 80:
        raise ApiError("ERR_TECHNICAL_TEST_FAILED", "technical_test_score < 80", 409)
    if not r["financial_statement_verified"]:
        raise ApiError("ERR_FINANCIAL_STANDING_UNVERIFIED", "financial statements not verified", 409)
    now = clock.now()
    r["status"] = "ACTIVE"
    r["accredited_on"] = fmt_iso(now)
    r["accredited_version"] = r["version"]  # snapshot BEFORE increment
    r["annual_fee_mode"] = "PROVISIONAL"
    r["all_in_cost_cents"] = fiscal.accreditation_cost_provisional(r)
    db.touch(r, now)
    fiscal.mint_invoice(r["id"], None, "ACCREDITATION", r["all_in_cost_cents"], 0, None)
    return success_object(registrar_view(r))


@bp.post("/registrars/<rid>/suspend")
def suspend(rid):
    require_roles("RegistryAdmin")
    r = _get_registrar_or_404(rid)
    if r["status"] != "ACTIVE":
        raise err_invalid_state()
    r["status"] = "SUSPENDED"
    db.touch(r, clock.now())
    return success_object(registrar_view(r))


@bp.post("/registrars/<rid>/reinstate")
def reinstate(rid):
    require_roles("RegistryAdmin")
    r = _get_registrar_or_404(rid)
    if r["status"] != "SUSPENDED":
        raise err_invalid_state()
    r["status"] = "ACTIVE"
    r["annual_fee_mode"] = "AUDIT"
    r["all_in_cost_cents"] = fiscal.accreditation_cost_audit(r)
    db.touch(r, clock.now())
    return success_object(registrar_view(r))


@bp.post("/registrars/<rid>/terminate")
def terminate(rid):
    from services import LIVE_DOMAIN_STATUSES
    require_roles("RegistryAdmin")
    r = _get_registrar_or_404(rid)
    if r["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err_invalid_state()
    for d in db.domains.values():
        if d["registrar_id"] == r["id"] and d["status"] in LIVE_DOMAIN_STATUSES:
            raise ApiError("ERR_REGISTRAR_HAS_LIVE_DOMAINS",
                           "Registrar still sponsors non-terminal domains", 409)
    r["status"] = "TERMINATED"
    db.touch(r, clock.now())
    if r["escrow_deposit_cents"] > 0:
        fiscal.mint_ledger(r["id"], None, r["escrow_deposit_cents"], "WRITE_OFF")
    return success_object(registrar_view(r))


@bp.post("/registrars/<rid>/ledger-topups")
def ledger_topup(rid):
    require_roles("RegistryFinance")
    r = _get_registrar_or_404(rid)
    data = body_json()
    require_fields(data, ["amount_cents"])
    amt = data["amount_cents"]
    if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
        raise err_invalid_request("amount_cents must be a positive integer")
    e = fiscal.mint_ledger(r["id"], None, amt, "TOP_UP")
    return success_object(ledger_view(e), 201)


@bp.get("/registrars/<rid>/ledger")
def list_ledger(rid):
    require_roles("RegistryAdmin", "RegistryFinance", "RegistrarOperator")
    r = _get_registrar_or_404(rid)
    limit, offset = pagination_params()
    rows = sorted([e for e in db.ledger_entries.values() if e["registrar_id"] == r["id"]],
                  key=lambda e: e["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([ledger_view(e) for e in page], limit, offset, total)


@bp.get("/registrars/<rid>/domains")
def list_registrar_domains(rid):
    require_roles("RegistryAdmin", "RegistrarOperator", "RegistryFinance")
    r = _get_registrar_or_404(rid)
    limit, offset = pagination_params()
    status = request.args.get("status")
    rows = sorted([d for d in db.domains.values() if d["registrar_id"] == r["id"]],
                  key=lambda d: d["created_at"])
    if status:
        rows = [d for d in rows if d["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([domain_view(d) for d in page], limit, offset, total)


@bp.get("/registrars/<rid>/accreditation-notices")
def list_registrar_notices(rid):
    require_roles("RegistryAdmin", "RegistrarOperator")
    r = _get_registrar_or_404(rid)
    limit, offset = pagination_params()
    rows = sorted([n for n in db.notices.values() if n["registrar_id"] == r["id"]],
                  key=lambda n: n["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([notice_view(n) for n in page], limit, offset, total)


@bp.get("/accreditation-notices")
def list_notices():
    require_roles("RegistryAdmin", "RegistrarOperator")
    limit, offset = pagination_params()
    rows = sorted(db.notices.values(), key=lambda n: n["created_at"])
    rid = request.args.get("registrar_id")
    sid = request.args.get("price_schedule_id")
    if rid:
        rows = [n for n in rows if n["registrar_id"] == rid]
    if sid:
        rows = [n for n in rows if n["price_schedule_id"] == sid]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([notice_view(n) for n in page], limit, offset, total)


@bp.get("/accreditation-notices/<nid>")
def get_notice(nid):
    require_roles("RegistryAdmin", "RegistrarOperator")
    n = db.notices.get(nid)
    if n is None:
        raise err_not_found()
    return success_object(notice_view(n))
