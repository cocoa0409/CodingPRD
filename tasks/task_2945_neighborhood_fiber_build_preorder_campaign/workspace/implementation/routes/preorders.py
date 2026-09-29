"""Preregistration sign-up, cancellation and conversion (PRD 3.3, 3.7)."""

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import listing
import serialize
import shape
from errors import ApiError
from store import bump, db, insert, must_find, new_row, now, ordered, rows

bp = Blueprint("preorders", __name__)

READ_ROLES = (
    "ProgramManager",
    "InstallCoordinator",
    "ClaimsAssessor",
    "ClaimsApprover",
    "Subscriber",
)
LIVE_STATUSES = ("PENDING", "QUALIFIED", "CONVERTED")


@bp.post("/preorders")
def create_preorder():
    user_id, role = auth.gate(("Subscriber",))
    data = shape.body()
    zone = listing.resolve(data, "build_zone_id", "build_zones")
    address = listing.resolve(data, "service_address_id", "service_addresses")
    account = listing.resolve(data, "account_id", "accounts")
    if account is not None:
        auth.own(user_id, role, account["id"])
    shape.req_id(data, "build_zone_id")
    shape.req_id(data, "service_address_id")
    shape.req_id(data, "account_id")
    plan_tier = shape.req_enum(data, "plan_tier", calc.PLAN_TIERS)
    unit_designator = shape.opt_str(data, "unit_designator", 1, 24)
    tendered = shape.req_int(data, "tendered_deposit_cents", 0)
    expected_version = shape.req_int(data, "expected_build_zone_version")
    if address["build_zone_id"] != zone["id"]:
        raise ApiError(
            "ERR_ADDRESS_LINKAGE_MISMATCH",
            "the address does not belong to the supplied build zone",
        )
    campaign = db.campaigns.get(zone["campaign_id"])
    if zone["campaign_status"] not in ("PREREG_OPEN", "PREREG_EXTENDED"):
        raise ApiError("ERR_PREREG_WINDOW_CLOSED", "the preregistration window is closed")
    if now() > zone["prereg_deadline_at"]:
        raise ApiError("ERR_PREREG_WINDOW_CLOSED", "the preregistration deadline has passed")
    if now() < campaign["prereg_window_open_at"]:
        raise ApiError("ERR_PREREG_WINDOW_CLOSED", "preregistration has not opened yet")
    if expected_version != zone["version"]:
        raise ApiError(
            "ERR_STALE_BUILD_ZONE_VERSION",
            "the build zone has moved on since it was read",
        )
    if address["serviceability"] == "NOT_SERVICEABLE":
        raise ApiError("ERR_ADDRESS_NOT_SERVICEABLE", "this address cannot be served")
    for existing in rows("preorders"):
        if (
            existing["service_address_id"] == address["id"]
            and existing["account_id"] == account["id"]
            and existing["preorder_status"] in LIVE_STATUSES
        ):
            raise ApiError("ERR_DUPLICATE_PREORDER", "a live preorder already exists")
    if tendered != campaign["deposit_amount_cents"]:
        raise ApiError(
            "ERR_DEPOSIT_AMOUNT_MISMATCH",
            "the tendered deposit must equal the campaign deposit exactly",
        )
    row = new_row(
        {
            "build_zone_id": zone["id"],
            "service_address_id": address["id"],
            "account_id": account["id"],
            "plan_tier": plan_tier,
            "unit_designator": unit_designator,
            "preorder_status": "PENDING",
            "deposit_status": "HELD",
            "deposit_amount_cents": campaign["deposit_amount_cents"],
            "make_ready_share_cents": None,
            "drop_method": None,
            "conversion_pre_discount_total_cents": None,
            "conversion_discount_cents": None,
            "conversion_total_due_cents": None,
            "converted_at": None,
            "cancelled_at": None,
            "lapse_reason": None,
        }
    )
    insert("preorders", row)
    cascades.move_deposit(row, "HELD", "DEPOSIT_HELD")
    bump(zone)
    return envelope.created(serialize.preorder(row))


@bp.get("/preorders/<preorder_id>")
def read_preorder(preorder_id):
    auth.gate(READ_ROLES)
    row = must_find("preorders", preorder_id)
    return envelope.ok(serialize.preorder(row))


@bp.get("/preorders")
def list_preorders():
    auth.gate(READ_ROLES)
    items = listing.apply_filters(
        ordered(rows("preorders")),
        (
            listing.fk("build_zone_id", "build_zone_id", "build_zones"),
            listing.fk("service_address_id", "service_address_id", "service_addresses"),
            listing.fk("account_id", "account_id", "accounts"),
            listing.enum("preorder_status", "preorder_status", calc.PREORDER_STATUSES),
            listing.enum("deposit_status", "deposit_status", calc.DEPOSIT_STATUSES),
        ),
    )
    return envelope.list_response(items, serialize.preorder)


@bp.post("/preorders/<preorder_id>/cancel")
def cancel_preorder(preorder_id):
    user_id, role = auth.gate(("Subscriber", "ProgramManager"))
    preorder = must_find("preorders", preorder_id)
    auth.own(user_id, role, preorder["account_id"])
    status = preorder["preorder_status"]
    if status not in ("PENDING", "QUALIFIED"):
        raise ApiError(
            "ERR_PREORDER_STATE_INVALID", "only a pending or qualified preorder can be cancelled"
        )
    preorder["preorder_status"] = "CANCELLED"
    preorder["cancelled_at"] = now()
    if preorder["deposit_status"] == "HELD":
        if status == "PENDING":
            cascades.move_deposit(preorder, "REFUNDED", "DEPOSIT_REFUNDED")
        else:
            cascades.move_deposit(preorder, "FORFEITED", "DEPOSIT_FORFEITED")
    bump(preorder)
    zone = db.build_zones.get(preorder["build_zone_id"])
    if zone is not None:
        bump(zone)
    return envelope.ok(serialize.preorder(preorder))


@bp.post("/preorders/<preorder_id>/conversion")
def convert_preorder(preorder_id):
    user_id, role = auth.gate(("Subscriber", "ProgramManager"))
    preorder = must_find("preorders", preorder_id)
    auth.own(user_id, role, preorder["account_id"])
    data = shape.body()
    drop_method = shape.req_enum(data, "drop_method", calc.DROP_METHODS)
    if preorder["preorder_status"] != "QUALIFIED":
        raise ApiError(
            "ERR_PREORDER_STATE_INVALID", "only a qualified preorder can be converted"
        )
    zone = db.build_zones.get(preorder["build_zone_id"])
    if zone is None or zone["construction_status"] not in ("IN_CONSTRUCTION", "SERVICE_READY"):
        raise ApiError(
            "ERR_BUILD_ZONE_STATE_INVALID", "the zone is not under construction"
        )
    address = db.service_addresses.get(preorder["service_address_id"])
    if address is not None and address["dwelling_type"] == "MDU":
        if not calc.has_signed_agreement(address["id"]):
            raise ApiError(
                "ERR_MDU_AGREEMENT_REQUIRED",
                "conversion requires a signed MDU owner agreement",
            )
    pre_discount, discount, due = calc.settlement(preorder, drop_method)
    preorder["drop_method"] = drop_method
    preorder["conversion_pre_discount_total_cents"] = pre_discount
    preorder["conversion_discount_cents"] = discount
    preorder["conversion_total_due_cents"] = due
    preorder["preorder_status"] = "CONVERTED"
    preorder["converted_at"] = now()
    if preorder["deposit_status"] == "HELD":
        cascades.move_deposit(preorder, "APPLIED", "DEPOSIT_APPLIED")
    bump(preorder)
    return envelope.ok(serialize.preorder(preorder))
