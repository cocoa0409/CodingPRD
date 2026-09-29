"""Landing a harvest lot — the vibrio allowance, the two time-to-temperature
bases and the six settlement steps — plus tagging and voiding (PRD 3.8, 3.9).
"""

from flask import Blueprint

import calc
import serializers as ser
from core import (
    LOT_STATUSES,
    ROLE_AUTHORITY,
    ROLE_DEALER,
    ROLE_OPERATOR,
    apply_changes,
    authenticate,
    check_not_future_instant,
    db,
    envelope_array,
    envelope_object,
    f_date,
    f_instant,
    f_int,
    f_num,
    f_str,
    get_authorization,
    get_lot,
    json_body,
    pagination,
    paginate,
    q_enum,
    q_str,
    require_lease_owner,
    sort_journal,
    stamp_new,
)
from errors import ApiError

bp = Blueprint("lots", __name__)

LOT_READ_ROLES = [ROLE_AUTHORITY, ROLE_OPERATOR, ROLE_DEALER]


@bp.route("/harvest-authorizations/<authorization_id>/harvest-lots", methods=["POST"])
def land_harvest_lot(authorization_id):
    authenticate([ROLE_OPERATOR])
    authorization = get_authorization(authorization_id)
    lease = db.leases.get(authorization["lease_id"])
    if lease is not None:
        require_lease_owner(lease)
    body = json_body()
    lot_code = f_str(body, "lot_code")
    bushels = f_int(body, "bushels", minimum=1)
    first_out = f_instant(body, "first_out_of_water_at")
    last_out = f_instant(body, "last_out_of_water_at")
    placed = f_instant(body, "placed_in_temperature_control_at")
    water_temp_c = f_num(body, "water_temp_c")

    # Rung 7 — only an active authorization lands shellstock.
    if authorization["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_AUTHORIZATION_STATE")
    # Rung 8 — the area must be open, then a plan must exist for the season.
    area = db.growing_areas.get(authorization["growing_area_id"])
    if area is not None and area["harvest_status"] != "OPEN":
        raise ApiError("ERR_AREA_HARVEST_CLOSED")
    plan_month = first_out.month
    plan = calc.active_plan_for_month(plan_month)
    if plan is None:
        raise ApiError("ERR_NO_VIBRIO_PLAN_FOR_SEASON")
    # Rung 10 — future-dating, then the window, then the instant ordering.
    check_not_future_instant(first_out)
    check_not_future_instant(last_out)
    check_not_future_instant(placed)
    if not (
        authorization["window_start"] <= first_out < authorization["window_end"]
    ):
        raise ApiError("ERR_OUTSIDE_AUTHORIZATION_WINDOW")
    if last_out < first_out or placed < last_out:
        raise ApiError("ERR_INVALID_HARVEST_INSTANTS")
    # Rung 12 — the projection, then lot-code uniqueness.
    if (authorization["harvested_bushels"] + bushels) > authorization[
        "projected_bushels"
    ]:
        raise ApiError("ERR_HARVEST_EXCEEDS_PROJECTION")
    for existing in db.harvest_lots.values():
        if existing["lot_code"] == lot_code:
            raise ApiError("ERR_DUPLICATE_LOT_CODE")

    unit = db.growout_units.get(authorization["growout_unit_id"])
    vessel = db.vessels.get(authorization["vessel_id"])
    gear_type = unit["gear_type"] if unit is not None else None
    refrigeration_type = vessel["refrigeration_type"] if vessel is not None else None
    allowed = calc.allowed_ttt_minutes(
        plan, water_temp_c, gear_type, refrigeration_type
    )
    first_basis, last_basis = calc.ttt_bases(first_out, last_out, placed)
    classification = area["classification"] if area is not None else "APPROVED"
    variant = calc.ttt_basis_variant(classification)
    if variant == "FIRST_HARVEST_BASIS":
        governing = first_basis
    else:
        governing = last_basis
    compliance = "COMPLIANT" if governing <= allowed else "NONCOMPLIANT"
    settlement = calc.settle_lot(authorization["lease_id"], bushels, first_out)

    lot = {
        "harvest_authorization_id": authorization["id"],
        "dealer_id": authorization["dealer_id"],
        "shipment_id": None,
        "lot_code": lot_code,
        "bushels": bushels,
        "first_out_of_water_at": first_out,
        "last_out_of_water_at": last_out,
        "placed_in_temperature_control_at": placed,
        "water_temp_c": water_temp_c,
        "ttt_minutes_first_basis": first_basis,
        "ttt_minutes_last_basis": last_basis,
        "ttt_basis_variant": variant,
        "governing_ttt_minutes": governing,
        "allowed_ttt_minutes": allowed,
        "vibrio_control_plan_id": plan["id"],
        "vibrio_plan_month": plan_month,
        "compliance_status": compliance,
        "status": "HARVESTED",
        "tag_harvest_date": None,
        "tag_area_code": None,
        "tag_lease_code": None,
        "tag_dealer_certification_no": None,
        "embargo_reason": None,
        "void_reason": None,
    }
    lot.update(settlement)
    stamp_new(lot)
    db.harvest_lots[lot["id"]] = lot
    calc.recompute_authorization_volume(authorization)
    if lease is not None:
        calc.recompute_lease_royalty(lease)
    return envelope_object(ser.harvest_lot(lot)), 201


@bp.route("/harvest-authorizations/<authorization_id>/harvest-lots", methods=["GET"])
def list_authorization_lots(authorization_id):
    authenticate([ROLE_AUTHORITY, ROLE_OPERATOR])
    authorization = get_authorization(authorization_id)
    limit, offset = pagination()
    status = q_enum("status", LOT_STATUSES)
    rows = []
    for lot in calc.authorization_lots(authorization["id"]):
        if status is not None and lot["status"] != status:
            continue
        rows.append(lot)
    rows = sort_journal(rows, "first_out_of_water_at", False)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array(
        [ser.harvest_lot(r) for r in page], limit, offset, total
    ), 200


@bp.route("/harvest-lots/<lot_id>", methods=["GET"])
def read_harvest_lot(lot_id):
    authenticate(LOT_READ_ROLES)
    lot = get_lot(lot_id)
    return envelope_object(ser.harvest_lot(lot)), 200


@bp.route("/harvest-lots", methods=["GET"])
def list_harvest_lots():
    authenticate(LOT_READ_ROLES)
    limit, offset = pagination()
    harvest_authorization_id = q_str("harvest_authorization_id")
    dealer_id = q_str("dealer_id")
    shipment_id = q_str("shipment_id")
    vibrio_control_plan_id = q_str("vibrio_control_plan_id")
    status = q_enum("status", LOT_STATUSES)
    rows = []
    for lot in db.harvest_lots.values():
        if (
            harvest_authorization_id is not None
            and lot["harvest_authorization_id"] != harvest_authorization_id
        ):
            continue
        if dealer_id is not None and lot["dealer_id"] != dealer_id:
            continue
        if shipment_id is not None and lot["shipment_id"] != shipment_id:
            continue
        if (
            vibrio_control_plan_id is not None
            and lot["vibrio_control_plan_id"] != vibrio_control_plan_id
        ):
            continue
        if status is not None and lot["status"] != status:
            continue
        rows.append(lot)
    rows = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    total = len(rows)
    page = paginate(rows, limit, offset)
    return envelope_array(
        [ser.harvest_lot(r) for r in page], limit, offset, total
    ), 200


# --------------------------------------------------------------------------
# The shellstock tag
# --------------------------------------------------------------------------
@bp.route("/harvest-lots/<lot_id>/tag", methods=["POST"])
def tag_harvest_lot(lot_id):
    authenticate([ROLE_OPERATOR])
    lot = get_lot(lot_id)
    lease = calc.lot_lease(lot)
    if lease is not None:
        require_lease_owner(lease)
    body = json_body()
    harvest_date = f_date(body, "harvest_date")
    dealer_certification_no = f_str(body, "dealer_certification_no")

    # Rung 7 — only a landed lot may be tagged.
    if lot["status"] != "HARVESTED":
        raise ApiError("ERR_INVALID_LOT_STATE")
    # Rung 8 — this is where a time-and-temperature failure actually bites.
    if lot["compliance_status"] != "COMPLIANT":
        raise ApiError("ERR_TIME_TEMPERATURE_EXCEEDED")
    # Rung 13 — tag coherence, then the dealer's standing.
    if harvest_date != lot["first_out_of_water_at"].date():
        raise ApiError("ERR_TAG_HARVEST_DATE_MISMATCH")
    dealer = db.dealers.get(lot["dealer_id"])
    if dealer is None or dealer_certification_no != dealer["certification_no"]:
        raise ApiError("ERR_TAG_DEALER_CERT_MISMATCH")
    if dealer["listing_status"] == "SUSPENDED":
        raise ApiError("ERR_DEALER_SUSPENDED")

    area = calc.lot_area(lot)
    apply_changes(
        lot,
        {
            "status": "TAGGED",
            "tag_harvest_date": harvest_date,
            "tag_area_code": area["code"] if area is not None else None,
            "tag_lease_code": lease["lease_code"] if lease is not None else None,
            "tag_dealer_certification_no": dealer_certification_no,
        },
    )
    return envelope_object(ser.harvest_lot(lot)), 200


@bp.route("/harvest-lots/<lot_id>/void", methods=["POST"])
def void_harvest_lot(lot_id):
    authenticate([ROLE_OPERATOR])
    lot = get_lot(lot_id)
    lease = calc.lot_lease(lot)
    if lease is not None:
        require_lease_owner(lease)
    body = json_body()
    f_str(body, "void_note", required=False, default=None)

    # Rung 7 — only an unshipped lot in HARVESTED or TAGGED may be voided.
    if lot["status"] not in ("HARVESTED", "TAGGED") or lot["shipment_id"] is not None:
        raise ApiError("ERR_INVALID_LOT_STATE")

    # The tag fields are deliberately retained for the audit trail.
    apply_changes(
        lot, {"status": "VOIDED", "void_reason": "OPERATOR_CORRECTION"}
    )
    authorization = db.authorizations.get(lot["harvest_authorization_id"])
    if authorization is not None:
        calc.recompute_authorization_volume(authorization)
    if lease is not None:
        calc.recompute_lease_royalty(lease)
    return envelope_object(ser.harvest_lot(lot)), 200
