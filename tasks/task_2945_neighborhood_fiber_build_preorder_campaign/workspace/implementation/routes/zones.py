"""Build zones: carving, policy levers, ground-break, suspension, sign-off."""

import re

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import listing
import serialize
import shape
from errors import ApiError
from store import add_days, bump, db, insert, must_find, new_row, now, ordered, rows

bp = Blueprint("zones", __name__)

ZONE_CODE_RE = re.compile(r"^[A-Z0-9_]+$")


def _campaign_of(zone):
    return db.campaigns.get(zone["campaign_id"])


def _window_open(zone):
    """Ladder step 16."""
    if zone["campaign_status"] not in ("PREREG_OPEN", "PREREG_EXTENDED"):
        raise ApiError("ERR_PREREG_WINDOW_CLOSED", "the preregistration window is closed")
    if now() > zone["prereg_deadline_at"]:
        raise ApiError("ERR_PREREG_WINDOW_CLOSED", "the preregistration deadline has passed")


@bp.post("/build-zones")
def create_zone():
    auth.gate(("ProgramManager",))
    data = shape.body()
    campaign = listing.resolve(data, "campaign_id", "campaigns")
    shape.req_id(data, "campaign_id")
    name = shape.req_str(data, "name", 1, 120)
    zone_code = shape.req_str(data, "zone_code", 1, 16)
    if not ZONE_CODE_RE.match(zone_code):
        shape.bad("zone_code", "must use uppercase letters, digits and underscores")
    household_count = shape.req_int(data, "household_count", 1)
    threshold = shape.opt_dec(data, "threshold_pct", "0.01", "100.00")
    permit_types = shape.opt_enum_list(
        data, "required_permit_types", calc.PERMIT_TYPES, default=["ROW"]
    )
    bury_cap = shape.opt_int(data, "max_concurrent_bury_ops", 1, 10, 2)
    for existing in rows("build_zones"):
        if existing["campaign_id"] == campaign["id"] and existing["zone_code"] == zone_code:
            shape.bad("zone_code", "is already used by another zone of this campaign")
    row = new_row(
        {
            "campaign_id": campaign["id"],
            "name": name,
            "zone_code": zone_code,
            "household_count": household_count,
            "threshold_pct": threshold if threshold is not None else campaign["default_threshold_pct"],
            "required_permit_types": permit_types,
            "max_concurrent_bury_ops": bury_cap,
            "prereg_deadline_at": campaign["prereg_window_close_at"],
            "extension_count": 0,
            "cumulative_extension_days": 0,
            "campaign_status": "PREREG_OPEN",
            "construction_status": "NOT_STARTED",
            "suspension_reason": None,
            "final_qualifying_count": None,
            "final_rate_pct": None,
            "readiness_score": None,
            "build_sequence_index": None,
        }
    )
    insert("build_zones", row)
    return envelope.created(serialize.build_zone(row))


@bp.get("/build-zones/<zone_id>")
def read_zone(zone_id):
    auth.gate(auth.ALL_ROLES)
    zone = must_find("build_zones", zone_id)
    cascades.touch_zone(zone)
    return envelope.ok(serialize.build_zone(zone))


@bp.get("/build-zones")
def list_zones():
    auth.gate(auth.ALL_ROLES)
    items = ordered(rows("build_zones"))
    for zone in items:
        cascades.touch_zone(zone)
    items = listing.apply_filters(
        items,
        (
            listing.fk("campaign_id", "campaign_id", "campaigns"),
            listing.enum("campaign_status", "campaign_status", calc.CAMPAIGN_STATUSES),
            listing.enum("construction_status", "construction_status", calc.CONSTRUCTION_STATUSES),
        ),
    )
    return envelope.list_response(items, serialize.build_zone)


@bp.patch("/build-zones/<zone_id>/threshold")
def adjust_threshold(zone_id):
    auth.gate(("ProgramManager",))
    zone = must_find("build_zones", zone_id)
    data = shape.body()
    threshold = shape.req_dec(data, "threshold_pct", "0.01", "100.00")
    _window_open(zone)
    if threshold >= zone["threshold_pct"]:
        raise ApiError(
            "ERR_THRESHOLD_INCREASE_FORBIDDEN",
            "a threshold adjustment may only lower the bar",
        )
    zone["threshold_pct"] = threshold
    bump(zone)
    return envelope.ok(serialize.build_zone(zone))


@bp.post("/build-zones/<zone_id>/extend-deadline")
def extend_deadline(zone_id):
    auth.gate(("ProgramManager",))
    zone = must_find("build_zones", zone_id)
    campaign = _campaign_of(zone)
    _window_open(zone)
    if zone["extension_count"] >= campaign["max_deadline_extensions"]:
        raise ApiError("ERR_EXTENSION_LIMIT_REACHED", "this zone has used every extension")
    grant = campaign["extension_grant_days"]
    zone["prereg_deadline_at"] = add_days(zone["prereg_deadline_at"], grant)
    zone["extension_count"] += 1
    zone["cumulative_extension_days"] += grant
    zone["campaign_status"] = "PREREG_EXTENDED"
    bump(zone)
    return envelope.ok(serialize.build_zone(zone))


@bp.post("/build-zones/<zone_id>/construction-start")
def construction_start(zone_id):
    auth.gate(("ProgramManager",))
    zone = must_find("build_zones", zone_id)
    if zone["campaign_status"] != "QUALIFIED" or zone["construction_status"] != "SEQUENCED":
        raise ApiError(
            "ERR_BUILD_ZONE_STATE_INVALID",
            "ground-break requires a QUALIFIED, SEQUENCED zone",
        )
    cascades.touch_zone(zone)
    approved = calc.approved_required_types(zone)
    for permit_type in zone["required_permit_types"]:
        if permit_type not in approved:
            raise ApiError(
                "ERR_PERMIT_READINESS_UNMET",
                "permit type %s has no approved, unexpired application" % permit_type,
            )
    if not any(pole["status"] == "ATTACHED" for pole in calc.zone_poles(zone["id"])):
        raise ApiError("ERR_POLE_READINESS_UNMET", "no pole attachment is confirmed")
    _allocate_make_ready(zone)
    zone["construction_status"] = "IN_CONSTRUCTION"
    bump(zone)
    return envelope.ok(serialize.build_zone(zone))


def _allocate_make_ready(zone):
    recipients = [
        p for p in calc.zone_preorders(zone["id"]) if p["preorder_status"] == "QUALIFIED"
    ]
    if not recipients:
        return
    def sort_key(preorder):
        address = db.service_addresses.get(preorder["service_address_id"])
        street = address["street_address"] if address else ""
        return (preorder["created_at"], street, preorder["_seq"])

    recipients.sort(key=sort_key)
    shares = calc.allocate(calc.make_ready_cost(zone), len(recipients))
    for preorder, share in zip(recipients, shares):
        preorder["make_ready_share_cents"] = share
        bump(preorder)


@bp.post("/build-zones/<zone_id>/construction-complete")
def construction_complete(zone_id):
    auth.gate(("ProgramManager",))
    zone = must_find("build_zones", zone_id)
    if zone["construction_status"] != "IN_CONSTRUCTION":
        raise ApiError(
            "ERR_BUILD_ZONE_STATE_INVALID",
            "only a zone under construction can be declared service-ready",
        )
    if calc.outstanding_restoration_count(zone) != 0:
        raise ApiError("ERR_RESTORATION_OUTSTANDING", "restoration work is still outstanding")
    zone["construction_status"] = "SERVICE_READY"
    bump(zone)
    return envelope.ok(serialize.build_zone(zone))


@bp.post("/build-zones/<zone_id>/suspension")
def suspension(zone_id):
    auth.gate(("ProgramManager",))
    zone = must_find("build_zones", zone_id)
    data = shape.body()
    action = shape.req_enum(data, "action", calc.SUSPEND_ACTIONS)
    reason = shape.opt_enum(data, "suspension_reason", calc.SUSPENSION_REASONS)
    if action == "SUSPEND":
        if zone["construction_status"] != "IN_CONSTRUCTION":
            raise ApiError(
                "ERR_BUILD_ZONE_STATE_INVALID",
                "only a zone under construction can be suspended",
            )
        cascades.suspend_zone(zone, reason or "MANUAL")
    else:
        if zone["construction_status"] != "SUSPENDED":
            raise ApiError(
                "ERR_BUILD_ZONE_STATE_INVALID", "only a suspended zone can be resumed"
            )
        poles = calc.zone_poles(zone["id"])
        denied = any(pole["status"] == "DENIED" for pole in poles)
        attached = any(pole["status"] == "ATTACHED" for pole in poles)
        if denied and not attached:
            raise ApiError(
                "ERR_BUILD_ZONE_STATE_INVALID",
                "a denied pole attachment blocks resumption",
            )
        zone["construction_status"] = "IN_CONSTRUCTION"
        zone["suspension_reason"] = None
        bump(zone)
    return envelope.ok(serialize.build_zone(zone))
