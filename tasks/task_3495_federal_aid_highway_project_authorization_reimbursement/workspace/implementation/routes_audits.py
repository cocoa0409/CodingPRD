"""Audit endpoints: closeout audit, repayment, and the three-link closeout
cascade (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint

from calculations import AUDIT_FINDINGS_RESPONSE_DAYS, ledger_reconciliation
from db import STORE, clock, new_id, now_bookkeeping, touch
from errors import err
from helpers import as_int, as_str, get_body, paginate, req_field, resolve_body_fk
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from routes_authorizations import project_authorization, recompute_cell
from routes_projects import _resolve_project
from serializers import serialize_audit

bp = Blueprint("audits", __name__)


def _apply_closeout_cascade(audit, auth, project):
    """Audit CLOSED: (1) authorization deobligates to net federal outlay and
    closes; (2) the apportionment cell releases the deobligation; (3) the
    project closes out. Field mutations only — callers touch() each mutated
    resource exactly once per operation."""
    net_federal_outlay = auth["reimbursed_cents"] - auth["repaid_cents"]
    deobligation = auth["obligated_cents"] - net_federal_outlay
    auth["obligated_cents"] = net_federal_outlay
    auth["closed_at"] = clock.raw
    auth["status"] = "CLOSED"
    cell = STORE["apportionments"][auth["apportionment_id"]]
    cell["obligated_cents"] -= deobligation
    recompute_cell(cell)
    project["status"] = "CLOSED_OUT"
    audit["status"] = "CLOSED"
    audit["closed_at"] = clock.raw
    return cell


@bp.route("/federal-aid/audits", methods=["POST"])
@require_roles("FHWAReviewer")
def create_audit(user_id, user_role):
    body = get_body()
    # Body FK resolution precedes body well-formedness on plain creates.
    if "project_id" in body and body["project_id"] is not None:
        resolve_body_fk("projects", body["project_id"], "project_id")
    project_id = req_field(body, "project_id")
    project = STORE["projects"][project_id]
    if project["status"] != "COMPLETE":
        raise err(
            "ERR_INVALID_STATE", "An audit may only be initiated for a COMPLETE project"
        )
    for a in STORE["audits"].values():
        if a["project_id"] == project_id:
            raise err(
                "ERR_INVALID_STATE", "A Project hosts exactly one audit"
            )
    # Segregation of duties: the auditor must differ from the reviewer who
    # approved the final voucher.
    auth = project_authorization(project_id)
    final_voucher = None
    if auth is not None:
        for v in STORE["vouchers"].values():
            if (
                v["authorization_id"] == auth["id"]
                and v["is_final"]
                and v["status"] == "APPROVED"
            ):
                final_voucher = v
                break
    if final_voucher is not None and final_voucher["decided_by_user_id"] == user_id:
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "The auditor must differ from the final voucher's deciding reviewer",
        )
    now = now_bookkeeping()
    rec = {
        "id": new_id(),
        "project_id": project_id,
        "auditor_user_id": user_id,
        "status": "INITIATED",
        "findings_text": None,
        "ineligible_amount_cents": None,
        "findings_issued_at": None,
        "_findings_dt": None,
        "final_eligible_federal_share_cents": None,
        "repayment_due_cents": None,
        "repaid_cents": 0,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["audits"][rec["id"]] = rec
    return success_object(serialize_audit(rec), status=201)


@bp.route("/federal-aid/audits/<aid>/issue-findings", methods=["POST"])
@require_roles("FHWAReviewer")
def issue_findings(aid, user_id, user_role):
    audit = STORE["audits"].get(aid)
    if audit is None:
        raise err("ERR_NOT_FOUND", "Audit not found")
    body = get_body()
    findings_text = as_str(req_field(body, "findings_text"), "findings_text")
    ineligible = as_int(
        req_field(body, "ineligible_amount_cents"), "ineligible_amount_cents"
    )
    if ineligible < 0:
        raise err("ERR_INVALID_REQUEST", "ineligible_amount_cents must be >= 0")
    if audit["status"] != "INITIATED":
        raise err("ERR_INVALID_STATE", "Audit is not in INITIATED")
    audit["findings_text"] = findings_text
    audit["ineligible_amount_cents"] = ineligible
    audit["findings_issued_at"] = clock.raw
    audit["_findings_dt"] = clock.dt
    audit["status"] = "FINDINGS_ISSUED"
    touch(audit)
    return success_object(serialize_audit(audit))


@bp.route("/federal-aid/audits/<aid>/finalize", methods=["POST"])
@require_roles("FHWAReviewer")
def finalize_audit(aid, user_id, user_role):
    audit = STORE["audits"].get(aid)
    if audit is None:
        raise err("ERR_NOT_FOUND", "Audit not found")
    get_body()
    if audit["status"] != "FINDINGS_ISSUED":
        raise err("ERR_INVALID_STATE", "Audit is not in FINDINGS_ISSUED")
    if clock.dt < audit["_findings_dt"] + timedelta(
        days=AUDIT_FINDINGS_RESPONSE_DAYS
    ):
        raise err(
            "ERR_AUDIT_RESPONSE_WINDOW_OPEN",
            "The 30-day audit response window has not elapsed",
        )
    project = STORE["projects"][audit["project_id"]]
    auth = project_authorization(audit["project_id"])
    approved_eligible_total = sum(
        v["eligible_amount_cents"]
        for v in STORE["vouchers"].values()
        if v["authorization_id"] == auth["id"] and v["status"] == "APPROVED"
    )
    final_eligible, repayment_due = ledger_reconciliation(
        auth, approved_eligible_total, audit["ineligible_amount_cents"]
    )
    audit["final_eligible_federal_share_cents"] = final_eligible
    audit["repayment_due_cents"] = repayment_due
    audit["status"] = "FINAL"
    closed = repayment_due == 0
    cell = None
    if closed:
        # Zero repayment due: immediately continue FINAL -> CLOSED with the
        # closeout cascade in the same operation.
        cell = _apply_closeout_cascade(audit, auth, project)
    touch(audit)
    if closed:
        touch(auth)
        touch(cell)
        touch(project)
    return success_object(serialize_audit(audit))


@bp.route("/federal-aid/audits/<aid>/record-repayment", methods=["POST"])
@require_roles("FHWAReviewer")
def record_repayment(aid, user_id, user_role):
    audit = STORE["audits"].get(aid)
    if audit is None:
        raise err("ERR_NOT_FOUND", "Audit not found")
    body = get_body()
    amount = as_int(req_field(body, "amount_cents"), "amount_cents")
    if amount <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be greater than 0")
    if audit["status"] != "FINAL":
        raise err("ERR_INVALID_STATE", "Audit is not in FINAL")
    outstanding = audit["repayment_due_cents"] - audit["repaid_cents"]
    if amount > outstanding:
        raise err(
            "ERR_REPAYMENT_EXCEEDS_DUE",
            "Repayment exceeds the outstanding amount due",
        )
    project = STORE["projects"][audit["project_id"]]
    auth = project_authorization(audit["project_id"])
    audit["repaid_cents"] += amount
    auth["repaid_cents"] += amount
    closed = audit["repaid_cents"] == audit["repayment_due_cents"]
    cell = None
    if closed:
        cell = _apply_closeout_cascade(audit, auth, project)
    touch(audit)
    touch(auth)
    if closed:
        touch(cell)
        touch(project)
    return success_object(serialize_audit(audit))


@bp.route("/federal-aid/projects/<pid>/audits", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_project_audits(pid, user_id, user_role):
    _resolve_project(pid)
    items = [a for a in STORE["audits"].values() if a["project_id"] == pid]
    items.sort(key=lambda a: a["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list([serialize_audit(a) for a in page], total, limit, offset)
