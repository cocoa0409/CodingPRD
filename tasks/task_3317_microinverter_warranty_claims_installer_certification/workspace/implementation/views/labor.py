"""Labor reimbursement routes: filing, listing, the read-only quote, and the
after-the-fact reversal (PRD 3.8)."""

import db
import shapes
from approval import as_nonempty_str_optional, as_number, as_str, body
from auth import ROLE_INSTALLER, ROLE_PLATFORM_ADMIN, get_reimbursement, require
from errors import fail
from respond import ok, ok_list, paginate
from services import common
from services import labor as labor_service
from services import orders as order_service


def create_reimbursement():
    data = body()
    claim_id = as_str(data, "claim_id")
    claimed_hours = as_number(data, "claimed_hours", exclusive_minimum=0)

    claim = db.DB.claims.get(claim_id)
    if claim is None:
        fail("ERR_RESOURCE_NOT_FOUND", "claim %s does not exist" % claim_id)

    for existing in db.reimbursements_of_claim(claim_id):
        if existing.get("status") == "PENDING":
            fail("ERR_LABOR_ALREADY_PENDING")

    installer = db.DB.installers.get(claim.get("installer_id"))
    if installer is None:
        fail("ERR_RESOURCE_NOT_FOUND")

    if common.dec(installer.get("claim_approval_rate_pct")) <= common.CLAIM_RATE_FLOOR_PCT:
        fail("ERR_CLAIM_RATE_FLOOR")

    unit = db.DB.units.get(claim.get("unit_id"))
    if unit is None:
        fail("ERR_RESOURCE_NOT_FOUND")

    # Backstop: the variant actually shipped to the unit must be compatible
    # with the generation it replaced.  Dispatch refuses an incompatible pair
    # earlier, so this stands only as a guard.
    for order in db.orders_of_claim(claim_id):
        if order.get("compatibility_class") == "INCOMPATIBLE":
            fail("ERR_INCOMPATIBLE_REPLACEMENT")

    system = db.DB.systems.get(unit.get("system_id"))
    level = installer.get("certification_level")
    figures = labor_service.snapshot(level, claimed_hours, system, common.now())

    reimbursement = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "updated_at": common.now_iso(),
        "version": 1,
        "claim_id": claim_id,
        "installer_id": claim.get("installer_id"),
        "claimed_hours": figures["claimed_hours"],
        "allowed_hours": figures["allowed_hours"],
        "cap_applied": figures["cap_applied"],
        "hourly_rate_cents": figures["hourly_rate_cents"],
        "age_factor": figures["age_factor"],
        "level_factor": figures["level_factor"],
        "labor_component_cents": figures["labor_component_cents"],
        "diagnostic_component_cents": figures["diagnostic_component_cents"],
        "net_amount_cents": figures["net_amount_cents"],
        "status": "PENDING",
        "rejection_reason": None,
        "reversed": False,
        "paid_at": None,
        "level_at_filing": figures["level_used"],
        "filed_at": common.now_iso(),
    }
    db.DB.reimbursements[reimbursement["id"]] = reimbursement
    common.recompute_installer(installer)
    return ok(shapes.labor_reimbursement(reimbursement), 201)


def list_reimbursements():
    from flask import request

    claim_id = request.args.get("claim_id")
    installer_id = request.args.get("installer_id")

    rows = list(db.DB.reimbursements.values())
    if claim_id:
        rows = [r for r in rows if r.get("claim_id") == claim_id]
    if installer_id:
        rows = [r for r in rows if r.get("installer_id") == installer_id]
    rows = db.by_created_at(rows)
    window, meta = paginate(rows, request.args)
    return ok_list([shapes.labor_reimbursement(r) for r in window], pagination=meta)


def read_reimbursement(reimbursement_id):
    row = get_reimbursement(reimbursement_id)
    return ok(shapes.labor_reimbursement(row))


def read_quote(reimbursement_id):
    row = get_reimbursement(reimbursement_id)
    figures = labor_service.recompute_for_reimbursement(row)
    return ok(shapes.labor_quote(row, figures))


def reject_reimbursement(reimbursement_id):
    data = body()
    rejection_reason = as_nonempty_str_optional(data, "rejection_reason")
    if rejection_reason is None:
        fail("ERR_INVALID_REQUEST_BODY", "missing required field `rejection_reason`")

    row = get_reimbursement(reimbursement_id)
    if row.get("status") != "APPROVED":
        fail("ERR_INVALID_STATE", "only an APPROVED reimbursement can be reversed")

    claim = db.DB.claims.get(row.get("claim_id"))
    if claim is None or claim.get("status") not in ("DISPATCHED", "CLOSED", "REOPENED"):
        fail("ERR_INVALID_STATE",
             "the source claim is not DISPATCHED, CLOSED or REOPENED")

    common.set_many(row, {
        "status": "REJECTED",
        "rejection_reason": rejection_reason,
        "reversed": True,
    })
    installer = db.DB.installers.get(row.get("installer_id"))
    if installer is not None:
        common.recompute_installer(installer)
    return ok(shapes.labor_reimbursement(row))


def register(app):
    app.add_url_rule("/warranty/labor-reimbursements", "create_reimbursement",
                     require(ROLE_INSTALLER)(create_reimbursement), methods=["POST"])
    app.add_url_rule("/warranty/labor-reimbursements", "list_reimbursements",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER)(list_reimbursements),
                     methods=["GET"])
    app.add_url_rule("/warranty/labor-reimbursements/<reimbursement_id>",
                     "read_reimbursement",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER)(read_reimbursement),
                     methods=["GET"])
    app.add_url_rule("/warranty/labor-reimbursements/<reimbursement_id>/quote",
                     "read_quote",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER)(read_quote),
                     methods=["GET"])
    app.add_url_rule("/warranty/labor-reimbursements/<reimbursement_id>/reject",
                     "reject_reimbursement",
                     require(ROLE_PLATFORM_ADMIN)(reject_reimbursement), methods=["POST"])