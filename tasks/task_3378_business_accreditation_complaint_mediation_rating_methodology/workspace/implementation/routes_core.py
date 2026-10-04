"""Bureaus, daily close, consumers, businesses, and the logical clock."""
from flask import Blueprint, request

import db
import domain
import web
from constants import ALL_ROLES, ROLE_BUREAU_ADMIN
from errors import ApiError

bp = Blueprint("core", __name__)

READ_ROLES = ALL_ROLES


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize_bureau(bureau):
    domain.refresh_derived("bureau", bureau)
    return db.serialize(bureau)


def serialize_consumer(consumer):
    domain.refresh_derived("consumer", consumer)
    return db.serialize(consumer)


def serialize_business(business):
    domain.refresh_derived("business", business)
    return db.serialize(business)


def get_bureau_or_404(bureau_id):
    bureau = db.STORE.bureaus.get(bureau_id)
    if bureau is None:
        raise ApiError("ERR_BUREAU_NOT_FOUND")
    return bureau


def get_business_or_404(business_id):
    business = db.STORE.businesses.get(business_id)
    if business is None:
        raise ApiError("ERR_BUSINESS_NOT_FOUND")
    return business


# ---------------------------------------------------------------------------
# POST /bureaus
# ---------------------------------------------------------------------------
@bp.route("/bureaus", methods=["POST"])
def create_bureau():
    web.authz({ROLE_BUREAU_ADMIN})
    data = web.body()
    # priority 5: schema
    name = web.require_string(data, "name")
    state_codes = web.require_string_list(data, "territory_state_codes")
    local_fee = web.optional_int(data, "local_dues_fee_cents", minimum=0)
    if local_fee is None:
        local_fee = 0
    # priority 9: state codes are exclusive across bureaus
    claimed = set()
    for bureau in db.STORE.bureaus.values():
        claimed.update(bureau["territory_state_codes"])
    if any(code in claimed for code in state_codes):
        raise ApiError(
            "ERR_STATE_ALREADY_ASSIGNED",
            "one or more state codes are already assigned to another bureau",
        )
    bureau = db.new_entity(
        "bureaus",
        {
            "name": name,
            "territory_state_codes": list(state_codes),
            "local_dues_fee_cents": local_fee,
            "dues_collected_cents": 0,
            "ops_day_index": 0,
        },
    )
    return web.success_object(serialize_bureau(bureau), status=201)


# ---------------------------------------------------------------------------
# POST /bureaus/{id}/run_daily_close
# ---------------------------------------------------------------------------
@bp.route("/bureaus/<bureau_id>/run_daily_close", methods=["POST"])
def run_daily_close(bureau_id):
    web.authz({ROLE_BUREAU_ADMIN})
    bureau = get_bureau_or_404(bureau_id)
    domain.run_daily_close(bureau)
    return web.success_object(serialize_bureau(bureau), status=200)


# ---------------------------------------------------------------------------
# POST /consumers
# ---------------------------------------------------------------------------
@bp.route("/consumers", methods=["POST"])
def create_consumer():
    web.authz({ROLE_BUREAU_ADMIN})
    data = web.body()
    full_name = web.require_string(data, "full_name")
    email = web.require_string(data, "email")
    home_state_code = web.require_string(data, "home_state_code")
    # email is unique across consumers (priority 5 schema rule)
    if any(c["email"] == email for c in db.STORE.consumers.values()):
        raise ApiError("ERR_INVALID_REQUEST", "email is already registered")
    consumer = db.new_entity(
        "consumers",
        {
            "full_name": full_name,
            "email": email,
            "home_state_code": home_state_code,
            "complaints_filed_count": 0,
        },
    )
    return web.success_object(serialize_consumer(consumer), status=201)


# ---------------------------------------------------------------------------
# POST /businesses
# ---------------------------------------------------------------------------
@bp.route("/businesses", methods=["POST"])
def create_business():
    web.authz({ROLE_BUREAU_ADMIN})
    data = web.body()
    # priority 5: schema
    legal_name = web.require_string(data, "legal_name")
    home_state_code = web.require_string(data, "home_state_code")
    employee_count = web.require_int(data, "employee_count", minimum=1)
    founded_on = web.require_datetime(data, "founded_on")
    # priority 9: territory assignment (state codes are unique across bureaus,
    # so at most one candidate; no tie-break needed)
    bureau = next(
        (
            b
            for b in db.STORE.bureaus.values()
            if home_state_code in b["territory_state_codes"]
        ),
        None,
    )
    if bureau is None:
        raise ApiError("ERR_TERRITORY_UNCOVERED")
    business = db.new_entity(
        "businesses",
        {
            "legal_name": legal_name,
            "home_state_code": home_state_code,
            "employee_count": employee_count,
            "founded_on": founded_on,
            "bureau_id": bureau["id"],
            "size_tier": domain.size_tier_of(employee_count),
            "accreditation_status": "NOT_ACCREDITED",
            "advertising_compliance_status": "CLEAR",
            "suspension_count_24m": 0,
            "last_suspension_at": None,
            "complaints_received_36m": 0,
            "complaints_unanswered_36m": 0,
            "complaints_unresolved_36m": 0,
            "complaints_open_count": 0,
            "complaints_closed_count": 0,
            "published_scam_count_12m": 0,
            "current_published_score": None,
            "current_published_grade": None,
            "current_provisional_score": None,
            "current_provisional_grade": None,
        },
    )
    return web.success_object(serialize_business(business), status=201)


# ---------------------------------------------------------------------------
# GET /businesses/{id}
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>", methods=["GET"])
def get_business(business_id):
    web.authz(READ_ROLES)
    business = get_business_or_404(business_id)
    return web.success_object(serialize_business(business), status=200)


# ---------------------------------------------------------------------------
# GET /businesses
# ---------------------------------------------------------------------------
@bp.route("/businesses", methods=["GET"])
def list_businesses():
    web.authz(READ_ROLES)
    bureau_id = request.args.get("bureau_id")
    accreditation_status = request.args.get("accreditation_status")
    home_state_code = request.args.get("home_state_code")
    items = list(db.STORE.businesses.values())
    if bureau_id is not None:
        items = [b for b in items if b["bureau_id"] == bureau_id]
    if accreditation_status is not None:
        items = [b for b in items if b["accreditation_status"] == accreditation_status]
    if home_state_code is not None:
        items = [b for b in items if b["home_state_code"] == home_state_code]
    return web.paginated_entities(items, serialize_business)


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    web.authz({ROLE_BUREAU_ADMIN})
    data = web.body()
    instant = web.require_datetime(data, "to_iso8601")
    db.set_clock(instant)
    return web.success_object(
        {"current_utc": db.iso_clock_value(instant)}, status=200
    )
