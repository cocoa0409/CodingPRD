"""WageStatement endpoints + annual summary."""

from datetime import datetime, timezone

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles, check_client_identity
from response import success_object, success_list
from services_common import new_entity, paginate, touch, now_iso, now_dt, public

bp = Blueprint("wage_statements", __name__)

READ_ROLES = {"BureauCompliance", "BureauTaxFiler", "ClientPayrollAdmin"}


def _get_statement(statement_id):
    s = store.wage_statements.get(statement_id)
    if not s:
        raise errors.not_found("Wage statement not found")
    return s


def _active_exists(client_id, tax_year, employee_ref, exclude_id=None):
    for s in store.wage_statements.values():
        if s["client_id"] == client_id and s["tax_year"] == tax_year \
                and s["employee_ref"] == employee_ref \
                and s["status"] == "ISSUED" \
                and s["id"] != exclude_id:
            return True
    return False


@bp.route("/wage-statements", methods=["POST"])
def create_statement():
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    body = request.get_json(silent=True) or {}

    client_id = body.get("client_id")
    if not client_id:
        raise errors.invalid_request("client_id is required")
    if client_id not in store.clients:
        raise errors.not_found("Client not found")

    tax_year = body.get("tax_year")
    if tax_year is None:
        raise errors.invalid_request("tax_year is required")
    if not isinstance(tax_year, int) or isinstance(tax_year, bool):
        raise errors.invalid_request("tax_year must be an integer")

    employee_ref = body.get("employee_ref")
    if not employee_ref:
        raise errors.invalid_request("employee_ref is required")

    for f in ("wages_cents", "withheld_cents"):
        v = body.get(f)
        if v is None:
            raise errors.invalid_request(f"{f} is required")
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise errors.invalid_request(f"{f} must be a non-negative integer")

    corrects_id = body.get("corrects_statement_id")
    kind = "ORIGINAL"
    if corrects_id is not None:
        target = store.wage_statements.get(corrects_id)
        if not target:
            raise errors.not_found("Correction target statement not found")
        if target["status"] != "ISSUED":
            raise errors.invalid_state("Correction target must be ISSUED")
        kind = "CORRECTION"
    else:
        # ORIGINAL creation while an active statement exists is rejected
        if _active_exists(client_id, tax_year, employee_ref):
            raise errors.duplicate_active_statement("An active statement exists for this key")

    s = new_entity({
        "client_id": client_id,
        "tax_year": tax_year,
        "employee_ref": employee_ref,
        "wages_cents": body["wages_cents"],
        "withheld_cents": body["withheld_cents"],
        "statement_kind": kind,
        "corrects_statement_id": corrects_id,
        "status": "DRAFT",
        "issued_at": None,
    })
    store.wage_statements[s["id"]] = s
    return success_object(public(s), status=201)


@bp.route("/wage-statements", methods=["GET"])
def list_statements():
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    items = list(store.wage_statements.values())
    if auth.role == "ClientPayrollAdmin":
        items = [s for s in items if s["client_id"] == auth.user_id]
    cid = request.args.get("client_id")
    if cid is not None:
        items = [s for s in items if s["client_id"] == cid]
    ty = request.args.get("tax_year")
    if ty is not None:
        try:
            ty_int = int(ty)
        except ValueError:
            raise errors.invalid_request("tax_year must be an integer")
        items = [s for s in items if s["tax_year"] == ty_int]
    er = request.args.get("employee_ref")
    if er is not None:
        items = [s for s in items if s["employee_ref"] == er]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    csid = request.args.get("corrects_statement_id")
    if csid is not None:
        items = [s for s in items if s.get("corrects_statement_id") == csid]
    iv = request.args.get("include_voided")
    if iv is not None and iv.lower() != "true":
        items = [s for s in items if s["status"] != "VOIDED"]
    page, limit, offset, total = paginate(items)
    return success_list([public(s) for s in page], limit, offset, total)


@bp.route("/wage-statements/<statementId>", methods=["GET"])
def get_statement(statementId):
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    s = _get_statement(statementId)
    check_client_identity(auth, s["client_id"])
    return success_object(public(s))


@bp.route("/wage-statements/<statementId>/issue", methods=["POST"])
def issue_statement(statementId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    s = _get_statement(statementId)
    if s["status"] != "DRAFT":
        raise errors.invalid_state("Statement must be DRAFT to issue")
    # Year-close gate: logical clock on/after Jan 1 of tax_year + 1
    gate = datetime(s["tax_year"] + 1, 1, 1, tzinfo=timezone.utc)
    if now_dt() < gate:
        raise errors.year_not_closed("Tax year is not closed")
    # Uniqueness: no other currently-active (ISSUED) statement for the key.
    # CORRECTED rows are superseded predecessors (PRD §3.10: "exactly one
    # statement is ever active per employee key" and a CORRECTED row is the
    # already-flipped target), so they do not block a further correction in
    # the chain. A CORRECTION's own target is exempt — issuing the correction
    # flips it in the same transition.
    exempt_ids = {s["id"]}
    if s["statement_kind"] == "CORRECTION" and s.get("corrects_statement_id"):
        exempt_ids.add(s["corrects_statement_id"])
    for other in store.wage_statements.values():
        if other["client_id"] == s["client_id"] and other["tax_year"] == s["tax_year"] \
                and other["employee_ref"] == s["employee_ref"] \
                and other["status"] == "ISSUED" \
                and other["id"] not in exempt_ids:
            raise errors.duplicate_active_statement("An active statement exists for this key")
    s["status"] = "ISSUED"
    s["issued_at"] = now_iso()
    touch(s)
    # Correction cascade: target ISSUED -> CORRECTED
    if s["statement_kind"] == "CORRECTION" and s.get("corrects_statement_id"):
        target = store.wage_statements.get(s["corrects_statement_id"])
        if target and target["status"] == "ISSUED":
            target["status"] = "CORRECTED"
            touch(target)
    return success_object(public(s))


@bp.route("/wage-statements/<statementId>/void", methods=["POST"])
def void_statement(statementId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    s = _get_statement(statementId)
    if s["status"] not in ("ISSUED", "CORRECTED"):
        raise errors.invalid_state("Statement must be ISSUED or CORRECTED to void")
    s["status"] = "VOIDED"
    touch(s)
    return success_object(public(s))


@bp.route("/clients/<clientId>/wage-statements/summary", methods=["GET"])
def wage_summary(clientId):
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    if clientId not in store.clients:
        raise errors.not_found("Client not found")
    check_client_identity(auth, clientId)
    ty = request.args.get("tax_year")
    if ty is None:
        raise errors.invalid_request("tax_year is required")
    try:
        tax_year = int(ty)
    except ValueError:
        raise errors.invalid_request("tax_year must be an integer")
    include_voided = (request.args.get("include_voided") or "").lower() == "true"

    issued = [s for s in store.wage_statements.values()
              if s["client_id"] == clientId and s["tax_year"] == tax_year and s["status"] == "ISSUED"]
    voided = [s for s in store.wage_statements.values()
              if s["client_id"] == clientId and s["tax_year"] == tax_year and s["status"] == "VOIDED"]

    total_wages = sum(s["wages_cents"] for s in issued)
    total_withheld = sum(s["withheld_cents"] for s in issued)
    voided_total = sum(s["wages_cents"] for s in voided)
    if include_voided:
        total_wages += sum(s["wages_cents"] for s in voided)
        total_withheld += sum(s["withheld_cents"] for s in voided)

    return success_object({
        "tax_year": tax_year,
        "total_wages_cents": total_wages,
        "total_withheld_cents": total_withheld,
        "active_statement_count": len(issued),
        "voided_total_cents": voided_total,
    })
