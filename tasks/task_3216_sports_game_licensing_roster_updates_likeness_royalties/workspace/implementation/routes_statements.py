"""Royalty statement endpoints."""
from __future__ import annotations

from datetime import date

from flask import Blueprint

import helpers as H
import services as S
from db import db
from errors import (err_fiscal, err_invalid_input, err_invalid_state,
                    err_temporal)
from middleware import require_roles
from response import (body_json, ok_list, ok_obj, pagination_params,
                      parse_date, require_fields, require_int, stamp_new, touch)

bp = Blueprint("statements", __name__)

FC = ("FinanceController",)

# tiered accrual constants
TIER1_CAP = 50000000
TIER2_CAP = 200000000
TIER1_BPS = 1000
TIER2_BPS = 1200
TIER3_BPS = 1500


def _round_half_up_div(numer: int, denom: int) -> int:
    """round_half_up(numer / denom); numer may be negative (handle sign)."""
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def compute_accrual(agreement, statement, variant: str) -> int:
    """Compute accrued_royalty_cents for the given variant (PROVISIONAL/FINAL)."""
    gross = statement["gross_sales_cents"]
    if variant == "FINAL":
        gross = gross - statement["pending_sales_cents"]
    net = max(0, gross - statement["returns_cents"])
    units = statement.get("units_sold") or 0
    unit_rate = statement.get("unit_royalty_cents") or 0
    model = agreement["royalty_model"]
    if model == "PERCENT_OF_NET":
        base = net
    elif model == "PER_UNIT":
        base = units * unit_rate
    else:  # HYBRID
        base = max(net * 0.5, units * unit_rate)
    tier1 = min(base, TIER1_CAP) * TIER1_BPS / 10000
    tier2 = max(0, min(base, TIER2_CAP) - TIER1_CAP) * TIER2_BPS / 10000
    tier3 = max(0, base - TIER2_CAP) * TIER3_BPS / 10000
    raw = tier1 + tier2 + tier3
    if (agreement["mg_recoupable"]
            and agreement["recouped_against_mg_cents"] < agreement["minimum_guarantee_cents"]):
        room = agreement["minimum_guarantee_cents"] - agreement["recouped_against_mg_cents"]
        payable = max(0, raw - room)
    else:
        payable = raw
    # single round-half-up at the final step only
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(payable)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@bp.post("/licensing/royalty-statements")
def create_statement():
    require_roles(*FC)
    body = body_json()
    require_fields(body, ["agreement_id", "period_start_on", "period_end_on",
                          "gross_sales_cents", "returns_cents", "pending_sales_cents"])
    agreement = H.get_agreement(body["agreement_id"])
    ps = parse_date(body["period_start_on"], "period_start_on")
    pe = parse_date(body["period_end_on"], "period_end_on")
    gross = require_int(body, "gross_sales_cents", 0)
    returns = require_int(body, "returns_cents", 0)
    pending = require_int(body, "pending_sales_cents", 0)
    units = body.get("units_sold")
    if units is not None:
        units = require_int(body, "units_sold", 0)
    unit_rate = body.get("unit_royalty_cents")
    if unit_rate is not None:
        unit_rate = require_int(body, "unit_royalty_cents", 0)
    rec = {
        "agreement_id": agreement["id"],
        "period_start_on": body["period_start_on"],
        "period_end_on": body["period_end_on"],
        "statement_status": "OPEN",
        "gross_sales_cents": gross,
        "returns_cents": returns,
        "pending_sales_cents": pending,
        "accrued_royalty_cents": None,
        "held_royalty_cents": 0,
        "paid_royalty_cents": 0,
        "units_sold": units,
        "unit_royalty_cents": unit_rate,
        "_period_end": pe,
        "_finalized_on": None,
    }
    stamp_new(rec)
    db.royalty_statements[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/royalty-statements/<statement_id>")
def get_statement(statement_id):
    require_roles("LicensingAdmin", "FinanceController", "LeagueAuditor", "UnionAuditor")
    st = H.get_statement(statement_id)
    return ok_obj(H.serialize(st))


@bp.post("/licensing/royalty-statements/<statement_id>/compute-provisional")
def compute_provisional(statement_id):
    require_roles(*FC)
    st = H.get_statement(statement_id)
    if st["statement_status"] != "OPEN":
        raise err_invalid_state("Statement must be OPEN to compute provisional")
    agreement = H.get_agreement(st["agreement_id"])
    st["accrued_royalty_cents"] = compute_accrual(agreement, st, "PROVISIONAL")
    st["statement_status"] = "PROVISIONAL"
    touch(st)
    return ok_obj(H.serialize(st))


@bp.post("/licensing/royalty-statements/<statement_id>/finalize")
def finalize_statement(statement_id):
    require_roles(*FC)
    st = H.get_statement(statement_id)
    if st["statement_status"] != "PROVISIONAL":
        raise err_invalid_state("Statement must be PROVISIONAL to finalize")
    if db.now_date() <= st["_period_end"]:
        raise err_temporal("Clock date must be past period_end_on")
    agreement = H.get_agreement(st["agreement_id"])
    st["accrued_royalty_cents"] = compute_accrual(agreement, st, "FINAL")
    st["statement_status"] = "FINALIZED"
    st["_finalized_on"] = db.now_date()
    touch(st)
    agreement["outstanding_royalty_cents"] = (
        agreement["outstanding_royalty_cents"]
        + st["accrued_royalty_cents"] - (st["held_royalty_cents"] or 0))
    touch(agreement)
    return ok_obj(H.serialize(st))


@bp.post("/licensing/royalty-statements/<statement_id>/pay")
def pay_statement(statement_id):
    require_roles(*FC)
    st = H.get_statement(statement_id)
    if st["statement_status"] not in ("FINALIZED", "DISPUTED"):
        raise err_invalid_state("Statement must be FINALIZED or DISPUTED to pay")
    cases = S.cases_of_statement(st["id"])
    if st["statement_status"] == "FINALIZED":
        for c in cases:
            if c["audit_status"] in ("OPEN", "FINDINGS_FILED"):
                raise err_fiscal("An OPEN or FINDINGS_FILED audit case blocks payment")
    else:  # DISPUTED
        if not any(c["audit_status"] in ("SETTLED", "CLOSED") for c in cases):
            raise err_fiscal("DISPUTED statement requires a settled audit before payment")
    agreement = H.get_agreement(st["agreement_id"])
    paid = (st["accrued_royalty_cents"] or 0) - (st["held_royalty_cents"] or 0)
    st["paid_royalty_cents"] = paid
    st["statement_status"] = "PAID"
    touch(st)
    agreement["outstanding_royalty_cents"] = (
        agreement["outstanding_royalty_cents"] - paid)
    if agreement["mg_recoupable"] and agreement["recouped_against_mg_cents"] < agreement["minimum_guarantee_cents"]:
        room = agreement["minimum_guarantee_cents"] - agreement["recouped_against_mg_cents"]
        bump = min(room, max(0, paid))
        agreement["recouped_against_mg_cents"] = agreement["recouped_against_mg_cents"] + bump
    touch(agreement)
    return ok_obj(H.serialize(st))


@bp.get("/licensing/royalty-statements/<statement_id>/audit-cases")
def list_statement_cases(statement_id):
    require_roles("LicensingAdmin", "FinanceController", "LeagueAuditor", "UnionAuditor")
    st = H.get_statement(statement_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.cases_of_statement(st["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)
