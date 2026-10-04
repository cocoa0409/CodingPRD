"""Warranty transfer routes: change of homeowner at property sale (PRD 3.9)."""

import db
import shapes
from approval import as_enum, as_instant, as_nonempty_str_optional, as_str, body
from auth import (
    ROLE_HOMEOWNER,
    ROLE_INSTALLER,
    ROLE_PLATFORM_ADMIN,
    get_system,
    get_transfer,
    require,
)
from errors import fail
from respond import months_between_floor_zero, ok, ok_list, paginate, parse_iso
from services import common

TRANSFER_KINDS = ("SALE", "INHERITANCE", "FORECLOSURE")


def create_transfer():
    data = body()
    system_id = as_str(data, "system_id")
    transfer_kind = as_enum(data, "transfer_kind", TRANSFER_KINDS)
    new_owner_name = as_str(data, "new_owner_name")
    new_owner_email = as_str(data, "new_owner_email")
    effective_date = as_instant(data, "effective_date")

    system = db.DB.systems.get(system_id)
    if system is None:
        fail("ERR_RESOURCE_NOT_FOUND", "system %s does not exist" % system_id)

    figures = common.coverage_figures(system)
    common.recompute_system(system)
    end_at = figures["extended_warranty_end_at"]
    preserved_months = 0
    if end_at:
        preserved_months = months_between_floor_zero(
            effective_date, parse_iso(end_at))

    transfer = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "system_id": system_id,
        "transfer_kind": transfer_kind,
        "new_owner_name": new_owner_name,
        "new_owner_email": new_owner_email,
        "effective_date": common.iso(effective_date),
        "preserved_months": preserved_months,
        "approval_source": "AUTO" if preserved_months <= 0 else "HOMEOWNER_APPROVAL",
        "status": "SUBMITTED",
        "rejection_reason": None,
        "previous_owner_name": system.get("homeowner_name"),
        "previous_owner_email": system.get("homeowner_email"),
    }
    db.DB.transfers[transfer["id"]] = transfer
    return ok(shapes.warranty_transfer(transfer), 201)


def list_transfers():
    from flask import request

    system_id = request.args.get("system_id")
    status = request.args.get("status")

    rows = list(db.DB.transfers.values())
    if system_id:
        rows = [t for t in rows if t.get("system_id") == system_id]
    if status:
        rows = [t for t in rows if t.get("status") == status]
    rows = db.by_created_at(rows)
    window, meta = paginate(rows, request.args)
    return ok_list([shapes.warranty_transfer(t) for t in window], pagination=meta)


def read_transfer(transfer_id):
    transfer = get_transfer(transfer_id)
    return ok(shapes.warranty_transfer(transfer))


def approve_transfer(transfer_id):
    transfer = get_transfer(transfer_id)
    if transfer.get("status") != "SUBMITTED":
        fail("ERR_INVALID_STATE", "only a SUBMITTED transfer can be approved")

    system = get_system(transfer["system_id"])
    if system.get("warranty_status") not in ("ACTIVE", "EXPIRED"):
        fail("ERR_INVALID_STATE", "the system's warranty_status does not admit approval")

    preserved_months = transfer.get("preserved_months", 0)
    common.set_many(transfer, {
        "status": "APPROVED",
        "approval_source": "AUTO" if preserved_months <= 0 else "HOMEOWNER_APPROVAL",
    })
    common.set_many(system, {
        "warranty_status": "TRANSFERRED",
        "homeowner_name": transfer.get("new_owner_name"),
        "homeowner_email": transfer.get("new_owner_email"),
        "owner_change_count": int(system.get("owner_change_count", 0)) + 1,
    })
    common.recompute_units_of_system(system["id"])
    installer = db.DB.installers.get(system.get("installer_id"))
    if installer is not None:
        common.recompute_installer(installer)
    return ok(shapes.warranty_transfer(transfer))


def reject_transfer(transfer_id):
    data = body()
    rejection_reason = as_nonempty_str_optional(data, "rejection_reason")
    if rejection_reason is None:
        fail("ERR_INVALID_REQUEST_BODY", "missing required field `rejection_reason`")

    transfer = get_transfer(transfer_id)
    if transfer.get("status") != "SUBMITTED":
        fail("ERR_INVALID_STATE", "only a SUBMITTED transfer can be rejected")
    common.set_many(transfer, {
        "status": "REJECTED",
        "rejection_reason": rejection_reason,
    })
    return ok(shapes.warranty_transfer(transfer))


def reopen_transfer(transfer_id):
    transfer = get_transfer(transfer_id)
    if transfer.get("status") != "APPROVED":
        fail("ERR_INVALID_STATE", "only an APPROVED transfer can be reopened")

    system = get_system(transfer["system_id"])
    common.set_many(transfer, {"status": "SUBMITTED"})
    common.set_many(system, {
        "homeowner_name": transfer.get("previous_owner_name"),
        "homeowner_email": transfer.get("previous_owner_email"),
        "owner_change_count": max(0, int(system.get("owner_change_count", 0)) - 1),
    })
    common.recompute_units_of_system(system["id"])
    installer = db.DB.installers.get(system.get("installer_id"))
    if installer is not None:
        common.recompute_installer(installer)
    return ok(shapes.warranty_transfer(transfer))


def register(app):
    app.add_url_rule("/warranty/warranty-transfers", "create_transfer",
                     require(ROLE_HOMEOWNER)(create_transfer), methods=["POST"])
    app.add_url_rule("/warranty/warranty-transfers", "list_transfers",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_HOMEOWNER)(list_transfers),
                     methods=["GET"])
    app.add_url_rule("/warranty/warranty-transfers/<transfer_id>", "read_transfer",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_HOMEOWNER)(read_transfer),
                     methods=["GET"])
    app.add_url_rule("/warranty/warranty-transfers/<transfer_id>/approve", "approve_transfer",
                     require(ROLE_PLATFORM_ADMIN)(approve_transfer), methods=["POST"])
    app.add_url_rule("/warranty/warranty-transfers/<transfer_id>/reject", "reject_transfer",
                     require(ROLE_PLATFORM_ADMIN)(reject_transfer), methods=["POST"])
    app.add_url_rule("/warranty/warranty-transfers/<transfer_id>/reopen", "reopen_transfer",
                     require(ROLE_PLATFORM_ADMIN)(reopen_transfer), methods=["POST"])