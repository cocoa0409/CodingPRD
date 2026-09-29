"""Statutory filings: lodgement, confirmation and the penalty dimension."""
from flask import Blueprint, g

import serial
import services
import store
import validate as v
from auth import require
from common import (
    ALL_ROLES,
    FILING_STATUSES,
    FILING_TYPES,
    GLOBAL_PAYROLL_OPS,
    PAYROLL_CONTROLLER,
    PENALTY_STATUSES,
    PROVIDER_USER,
    ApiError,
    now,
)
from response import object_response, page_response
from store import touch

bp = Blueprint("filings", __name__)


def _context(filing):
    cycle = store.get_cycle(filing["cycle_id"])
    engagement = store.engagement_of_cycle(cycle)
    return cycle, engagement, store.country_of_engagement(engagement)


def _require_provider_scope(engagement):
    if g.role == PROVIDER_USER and g.user_id != engagement["provider_id"]:
        raise ApiError(
            "ERR_PROVIDER_SCOPE_VIOLATION",
            "A provider may only act on filings of its own engagement.",
        )


@bp.get("/payroll/filings/<ident>")
@require(*ALL_ROLES)
def read_filing(ident):
    return object_response(serial.filing(store.get_filing(ident)))


@bp.get("/payroll/filings")
@require(*ALL_ROLES)
def list_filings():
    limit, offset = v.pagination()
    status = v.query_enum("status", FILING_STATUSES)
    penalty_status = v.query_enum("penalty_status", PENALTY_STATUSES)
    filing_type = v.query_enum("filing_type", FILING_TYPES)
    cycle_id = v.query_value("cycle_id")

    rows = list(store.filings.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if penalty_status is not None:
        rows = [r for r in rows if r["penalty_status"] == penalty_status]
    if filing_type is not None:
        rows = [r for r in rows if r["filing_type"] == filing_type]
    return page_response(store.ordered(rows), serial.filing, limit, offset)


@bp.post("/payroll/filings/<ident>/file")
@require(GLOBAL_PAYROLL_OPS, PROVIDER_USER)
def file_filing(ident):
    body = v.json_body()
    submission_ref = v.req_str(body, "submission_ref", 1, None)

    filing = store.get_filing(ident)
    cycle, engagement, country = _context(filing)

    if filing["responsibility"] == "PROVIDER":
        if g.role != PROVIDER_USER or g.user_id != engagement["provider_id"]:
            raise ApiError(
                "ERR_FILING_RESPONSIBILITY_MISMATCH",
                "A provider-responsible obligation must be lodged by the engaged provider.",
            )
    else:
        if g.role == PROVIDER_USER:
            raise ApiError(
                "ERR_FILING_RESPONSIBILITY_MISMATCH",
                "A client-responsible obligation may not be lodged by a provider.",
            )

    if filing["status"] not in ("PENDING", "LATE") or cycle["status"] not in (
        "RESULTS_APPROVED",
        "FUNDED",
    ):
        raise ApiError(
            "ERR_FILING_INVALID_STATE",
            "The filing or its cycle is not in a state that allows lodgement.",
        )
    if filing["status"] == "PENDING":
        if now() > filing["due_at"]:
            raise ApiError(
                "ERR_FILING_INVALID_STATE",
                "The deadline has passed; the obligation must first be swept to LATE.",
            )
        filing["status"] = "FILED"
    else:
        filing["status"] = "FILED_LATE"

    filing["filed_at"] = now()
    filing["submission_ref"] = submission_ref
    touch(filing)

    country["open_filing_obligation_count"] -= 1
    if country["open_filing_obligation_count"] < 0:
        country["open_filing_obligation_count"] = 0
    touch(country)
    return object_response(serial.filing(filing))


@bp.post("/payroll/filings/<ident>/confirm")
@require(GLOBAL_PAYROLL_OPS, PROVIDER_USER)
def confirm_filing(ident):
    body = v.json_body()
    confirmation_ref = v.req_str(body, "confirmation_ref", 1, 60)

    filing = store.get_filing(ident)
    cycle, engagement, country = _context(filing)
    _require_provider_scope(engagement)

    if filing["status"] not in ("FILED", "FILED_LATE"):
        raise ApiError(
            "ERR_FILING_INVALID_STATE",
            "Only a lodged filing can be confirmed.",
        )

    filing["status"] = "CONFIRMED"
    filing["confirmation_ref"] = confirmation_ref
    touch(filing)

    cycle["filings_confirmed_count"] += 1
    touch(cycle)

    live = [f for f in store.filings_of_cycle(cycle["id"]) if f["status"] != "VOIDED"]
    if live and all(f["status"] == "CONFIRMED" for f in live):
        services.mint_system_evidence(cycle["id"], "CTRL_FILING_CONFIRMATION")
    return object_response(serial.filing(filing))


@bp.post("/payroll/filings/<ident>/penalty-dispute")
@require(PROVIDER_USER)
def dispute_penalty(ident):
    body = v.json_body()
    reason = v.req_str(body, "dispute_reason", 1, None)

    filing = store.get_filing(ident)
    cycle, engagement, country = _context(filing)
    _require_provider_scope(engagement)

    if filing["penalty_status"] != "ASSESSED" or filing["provider_share_minor"] <= 0:
        raise ApiError(
            "ERR_PENALTY_INVALID_STATE",
            "Only an assessed penalty the provider actually bears can be disputed.",
        )
    if filing["dispute_round"] >= 2:
        raise ApiError(
            "ERR_DISPUTE_ROUNDS_EXHAUSTED",
            "The provider has exhausted its dispute rounds.",
        )

    filing["penalty_status"] = "DISPUTED"
    filing["dispute_reason"] = reason
    touch(filing)
    return object_response(serial.filing(filing))


@bp.post("/payroll/filings/<ident>/penalty-dispute-decision")
@require(PAYROLL_CONTROLLER)
def decide_penalty_dispute(ident):
    body = v.json_body()
    decision = v.req_enum(body, "decision", ["UPHOLD", "REJECT"])
    v.opt_str(body, "decision_note", 1, None)

    filing = store.get_filing(ident)
    cycle, engagement, country = _context(filing)

    if filing["penalty_status"] != "DISPUTED":
        raise ApiError(
            "ERR_PENALTY_INVALID_STATE",
            "Only a disputed penalty can be decided.",
        )

    if decision == "REJECT":
        filing["penalty_status"] = "ASSESSED"
        filing["dispute_round"] += 1
        filing["dispute_reason"] = None
        touch(filing)
        return object_response(serial.filing(filing))

    waived = filing["provider_share_minor"]
    filing["penalty_status"] = "WAIVED"
    filing["client_share_minor"] = filing["client_share_minor"] + waived
    filing["provider_share_minor"] = 0
    filing["penalty_owner"] = "CLIENT"
    touch(filing)

    provider = store.provider_of_engagement(engagement)
    if waived:
        provider["open_penalty_minor"] -= waived
        if provider["open_penalty_minor"] < 0:
            provider["open_penalty_minor"] = 0
        touch(provider)
    services.derive_provider_status(provider)
    return object_response(serial.filing(filing))
