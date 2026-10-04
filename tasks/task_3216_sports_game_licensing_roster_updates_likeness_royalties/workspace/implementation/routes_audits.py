"""Audit case endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import helpers as H
import services as S
from db import db
from errors import (err_audit_window, err_invalid_input, err_invalid_state,
                    err_not_found, err_sod)
from middleware import require_roles
from response import body_json, ok_obj, require_enum, require_fields, stamp_new, touch

bp = Blueprint("audits", __name__)

AUDITORS = ("LeagueAuditor", "UnionAuditor")
OPENED_BY = {"LEAGUE_AUDITOR", "UNION_AUDITOR"}


@bp.post("/licensing/audit-cases")
def open_case():
    uid, role = require_roles(*AUDITORS)
    body = body_json()
    require_fields(body, ["agreement_id", "statement_id", "opened_by_role"])
    agreement = H.get_agreement(body["agreement_id"])
    statement = H.get_statement(body["statement_id"])
    if statement["agreement_id"] != agreement["id"]:
        raise err_not_found("Statement does not belong to the agreement")
    opened_by = require_enum(body, "opened_by_role", OPENED_BY)
    if statement["statement_status"] != "FINALIZED":
        raise err_invalid_state("Statement must be FINALIZED to open an audit")
    fin = statement.get("_finalized_on")
    if fin is None:
        raise err_audit_window("Statement has no recorded finalization date")
    if db.now_date() > fin + timedelta(days=agreement["audit_window_days"]):
        raise err_audit_window()
    rec = {
        "agreement_id": agreement["id"],
        "statement_id": statement["id"],
        "opened_by_role": opened_by,
        "audit_status": "OPEN",
        "finding_delta_cents": None,
        "_opened_by_id": uid,
    }
    stamp_new(rec)
    db.audit_cases[rec["id"]] = rec
    statement["statement_status"] = "DISPUTED"
    touch(statement)
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/audit-cases/<case_id>")
def get_case(case_id):
    require_roles("LicensingAdmin", "FinanceController", "LeagueAuditor", "UnionAuditor")
    c = H.get_case(case_id)
    return ok_obj(H.serialize(c))


@bp.post("/licensing/audit-cases/<case_id>/file-findings")
def file_findings(case_id):
    require_roles(*AUDITORS)
    c = H.get_case(case_id)
    body = body_json()
    require_fields(body, ["finding_delta_cents"])
    delta = body["finding_delta_cents"]
    if isinstance(delta, bool) or not isinstance(delta, int):
        raise err_invalid_input("finding_delta_cents must be an integer")
    if c["audit_status"] != "OPEN":
        raise err_invalid_state("Case must be OPEN to file findings")
    c["finding_delta_cents"] = delta
    c["audit_status"] = "FINDINGS_FILED"
    touch(c)
    return ok_obj(H.serialize(c))


@bp.post("/licensing/audit-cases/<case_id>/settle")
def settle_case(case_id):
    uid, _ = require_roles("FinanceController")
    c = H.get_case(case_id)
    if c["audit_status"] != "FINDINGS_FILED":
        raise err_invalid_state("Case must be FINDINGS_FILED to settle")
    if c.get("_opened_by_id") == uid:
        raise err_sod("Settling controller must differ from the auditor who opened the case")
    statement = H.get_statement(c["statement_id"])
    delta = c.get("finding_delta_cents") or 0
    statement["accrued_royalty_cents"] = (statement["accrued_royalty_cents"] or 0) + delta
    touch(statement)
    agreement = db.agreements.get(c["agreement_id"])
    if agreement is not None:
        agreement["outstanding_royalty_cents"] = agreement["outstanding_royalty_cents"] + delta
        touch(agreement)
    c["audit_status"] = "SETTLED"
    touch(c)
    return ok_obj(H.serialize(c))


@bp.post("/licensing/audit-cases/<case_id>/close")
def close_case(case_id):
    require_roles("FinanceController")
    c = H.get_case(case_id)
    if c["audit_status"] != "SETTLED":
        raise err_invalid_state("Case must be SETTLED to close")
    statement = H.get_statement(c["statement_id"])
    if statement["statement_status"] != "PAID":
        raise err_invalid_state("Referenced statement must be PAID before closing")
    c["audit_status"] = "CLOSED"
    touch(c)
    return ok_obj(H.serialize(c))
