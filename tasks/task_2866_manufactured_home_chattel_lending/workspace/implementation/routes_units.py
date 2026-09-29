"""Collateral registration, land documents and the classification conversion
cycle (PRD 3.2, 3.8)."""

from flask import Blueprint, request

import constants as K
import core
import domain
import envelope
import security
import shape
import store
from errors import ApiError

bp = Blueprint("units", __name__)

UNIT_ROLES = security.STAFF + (security.COMMUNITY_OPERATOR, security.BORROWER)


def query_enum(name, members):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in members:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a declared enum member." % name)
    return value


def non_terminal_loans_of_unit(unit_id):
    out = []
    for loan in store.loans_of_unit(unit_id):
        if loan["servicing_state"] in K.TERMINAL_SERVICING_STATES:
            continue
        if loan["underwriting_state"] == "DECLINED":
            continue
        out.append(loan)
    return out


def recovery_hold_active(unit):
    """PRD 3.2/3.8: hold flag, or any loan on the unit in RECOVERY/CHARGED_OFF."""
    if unit["recovery_hold"]:
        return True
    for loan in store.loans_of_unit(unit["id"]):
        if loan["servicing_state"] in ("RECOVERY", "CHARGED_OFF"):
            return True
    return False


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------

def _check_placement(data, placement_type, community_id, land_owner_borrower_id):
    lot_number = shape.opt_string(data, "lot_number")
    land_parcel_apn = shape.opt_string(data, "land_parcel_apn")
    land_county = shape.opt_string(data, "land_county")
    if placement_type == "COMMUNITY":
        if (community_id is None or lot_number is None
                or not shape.present(data, "placement_start_date")
                or land_owner_borrower_id is not None):
            raise ApiError("ERR_PLACEMENT_FIELDS_INCONSISTENT")
    else:
        if (land_owner_borrower_id is None or land_parcel_apn is None
                or land_county is None or community_id is not None):
            raise ApiError("ERR_PLACEMENT_FIELDS_INCONSISTENT")
    return lot_number, land_parcel_apn, land_county


def _check_lot_occupancy(community_id, lot_number, start):
    for other in store.ordered(list(store.units.values())):
        if other.get("community_id") != community_id or other.get("lot_number") != lot_number:
            continue
        incumbent_start = other.get("placement_start_date")
        if incumbent_start is None:
            continue
        incumbent_end = other.get("placement_end_date")
        if incumbent_end is None:
            if start >= incumbent_start:
                raise ApiError("ERR_LOT_OCCUPANCY_CONFLICT")
            continue
        buffered_end = core.add_days(incumbent_end, K.LOT_TURNOVER_BUFFER_DAYS)
        if incumbent_start <= start < buffered_end:
            raise ApiError("ERR_LOT_OCCUPANCY_CONFLICT")


@bp.post("/units")
def create_unit():
    security.require(security.PLATFORM_ADMIN, security.CLOSING_AGENT)
    data = shape.body()

    # rung 5: body foreign keys, in declaration order
    community_id = shape.opt_id(data, "community_id")
    if community_id is not None:
        store.get_community(community_id)
    land_owner_borrower_id = shape.opt_id(data, "land_owner_borrower_id")
    if land_owner_borrower_id is not None:
        store.get_borrower(land_owner_borrower_id)

    # rung 6: shape
    record = {
        "id": core.new_id(),
        "hud_label_number": shape.req_string(data, "hud_label_number"),
        "manufacturer": shape.req_string(data, "manufacturer"),
        "model_year": shape.req_int(data, "model_year"),
        "width_class": shape.req_enum(data, "width_class", K.WIDTH_CLASSES),
        "square_feet": shape.req_int(data, "square_feet", minimum=1),
        "condition_grade": shape.req_enum(data, "condition_grade", K.CONDITION_GRADES),
        "installation_type": shape.req_enum(data, "installation_type", K.INSTALLATION_TYPES),
        "wind_zone": shape.req_int(data, "wind_zone", minimum=1, maximum=3),
        "placement_type": shape.req_enum(data, "placement_type", K.PLACEMENT_TYPES),
    }
    placement_start = shape.opt_instant(data, "placement_start_date")
    placement_end = shape.opt_instant(data, "placement_end_date")
    land_value_cents = shape.opt_int(data, "land_value_cents", default=0, minimum=0)

    # rung 12: duplicate HUD label
    for other in store.units.values():
        if other["hud_label_number"] == record["hud_label_number"]:
            raise ApiError("ERR_DUPLICATE_HUD_LABEL")

    # rung 13: placement-field consistency
    lot_number, land_parcel_apn, land_county = _check_placement(
        data, record["placement_type"], community_id, land_owner_borrower_id)

    # rung 14: lot occupancy exclusivity with the turnover buffer
    if record["placement_type"] == "COMMUNITY":
        _check_lot_occupancy(community_id, lot_number, placement_start)

    record.update({
        "community_id": community_id,
        "lot_number": lot_number,
        "placement_start_date": placement_start,
        "placement_end_date": placement_end,
        "land_owner_borrower_id": land_owner_borrower_id,
        "land_parcel_apn": land_parcel_apn,
        "land_county": land_county,
        "land_value_cents": land_value_cents,
        "deed_recorded": False,
        "affixation_affidavit_recorded": False,
        "classification": "PERSONAL_PROPERTY",
        "title_status": "ACTIVE_TITLE",
        "recovery_hold": False,
    })
    store.stamp_new(record)
    store.units[record["id"]] = record
    return envelope.created(store.serialize(record))


@bp.get("/units/<unit_id>")
def read_unit(unit_id):
    actor = security.require(*UNIT_ROLES)
    unit = store.get_unit(unit_id)
    security.check_unit_scope(actor, unit)
    return envelope.ok(store.serialize(unit))


@bp.get("/units")
def list_units():
    actor = security.require(*UNIT_ROLES)
    community_id = request.args.get("community_id")
    land_owner_borrower_id = request.args.get("land_owner_borrower_id")
    classification = query_enum("classification", K.CLASSIFICATIONS)
    placement_type = query_enum("placement_type", K.PLACEMENT_TYPES)

    rows = store.ordered(list(store.units.values()))
    if community_id:
        rows = [u for u in rows if u.get("community_id") == community_id]
    if land_owner_borrower_id:
        rows = [u for u in rows if u.get("land_owner_borrower_id") == land_owner_borrower_id]
    if classification:
        rows = [u for u in rows if u["classification"] == classification]
    if placement_type:
        rows = [u for u in rows if u["placement_type"] == placement_type]
    rows = security.narrow_units(actor, rows)
    return envelope.paginate(rows, store.serialize)


# --------------------------------------------------------------------------
# land documents
# --------------------------------------------------------------------------

@bp.post("/units/<unit_id>/land-documents")
def record_land_document(unit_id):
    security.require(security.CLOSING_AGENT)
    unit = store.get_unit(unit_id)
    data = shape.body()
    document_type = shape.req_enum(data, "document_type", K.LAND_DOCUMENT_TYPES)
    if recovery_hold_active(unit):
        raise ApiError("ERR_RECOVERY_HOLD_ACTIVE")
    if document_type == "DEED":
        unit["deed_recorded"] = True
    else:
        unit["affixation_affidavit_recorded"] = True
    store.touch(unit)
    return envelope.ok(store.serialize(unit))


# --------------------------------------------------------------------------
# classification conversion
# --------------------------------------------------------------------------

def _complete_conversion(unit):
    unit["classification"] = "REAL_PROPERTY"
    unit["title_status"] = "TITLE_SURRENDERED"
    for filing in store.filings_of_unit(unit["id"]):
        if filing["status"] == "RECORDED" and filing["filing_type"] == "TITLE_LIEN":
            filing["status"] = "RELEASED"
            filing["released_at"] = core.now()
            filing["_release_cause"] = K.RELEASE_CAUSE_CONVERSION
            store.touch(filing)
    for loan in non_terminal_loans_of_unit(unit["id"]):
        loan["collateral_classification"] = "REAL_PROPERTY"
        if loan["perfection_state"] == "PERFECTED":
            loan["perfection_state"] = "RE_PERFECTION_REQUIRED"
        domain.rescore_active_policies(loan, unit)
        domain.recompute_insurance_compliance(loan)
        store.touch(loan)


def _rescind_conversion(unit):
    unit["classification"] = "PERSONAL_PROPERTY"
    unit["title_status"] = "ACTIVE_TITLE"
    for filing in store.filings_of_unit(unit["id"]):
        if (filing["status"] == "RELEASED" and filing["filing_type"] == "TITLE_LIEN"
                and filing.get("_release_cause") == K.RELEASE_CAUSE_CONVERSION):
            filing["status"] = "RECORDED"
            filing["released_at"] = None
            filing["_release_cause"] = None
            store.touch(filing)
    for loan in non_terminal_loans_of_unit(unit["id"]):
        loan["collateral_classification"] = "PERSONAL_PROPERTY"
        if loan["perfection_state"] == "RE_PERFECTION_REQUIRED":
            loan["perfection_state"] = "PERFECTED"
        domain.rescore_active_policies(loan, unit)
        domain.recompute_insurance_compliance(loan)
        store.touch(loan)


@bp.post("/units/<unit_id>/convert-classification")
def convert_classification(unit_id):
    security.require(security.CLOSING_AGENT)
    unit = store.get_unit(unit_id)
    data = shape.body()
    action = shape.req_enum(data, "action", K.CONVERSION_ACTIONS)

    required_from = {"INITIATE": "PERSONAL_PROPERTY",
                     "COMPLETE": "CONVERSION_PENDING",
                     "RESCIND": "REAL_PROPERTY"}[action]
    if unit["classification"] != required_from:
        raise ApiError("ERR_UNIT_CLASSIFICATION_INVALID_STATE")
    if recovery_hold_active(unit):
        raise ApiError("ERR_RECOVERY_HOLD_ACTIVE")

    if action == "INITIATE":
        if (unit["placement_type"] != "PRIVATE_LAND"
                or not unit["deed_recorded"]
                or not unit["affixation_affidavit_recorded"]):
            raise ApiError("ERR_LAND_DOCUMENTS_INCOMPLETE")
        unit["classification"] = "CONVERSION_PENDING"
    elif action == "COMPLETE":
        for filing in store.filings_of_unit(unit["id"]):
            if filing["status"] == "SUBMITTED":
                raise ApiError("ERR_FILING_INVALID_STATE")
        _complete_conversion(unit)
    else:
        _rescind_conversion(unit)

    store.touch(unit)
    return envelope.ok(store.serialize(unit))
