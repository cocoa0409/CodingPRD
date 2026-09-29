"""Engineers of record, dealerships and erection crews."""
from flask import Blueprint, request

import calc
import serializers
import services
import store
from authz import ALL_ROLES, authorize
from envelope import created, ok, paginated
from errors import ApiError
from routes_config import find_config
from shape import body, req_bool, req_dt, req_enum, req_int, req_str, req_str_array
from store import insert, touch

bp = Blueprint("parties", __name__)


def find_engineer(row_id):
    row = store.engineers.get(row_id)
    if row is None:
        raise ApiError("ERR_ENGINEER_NOT_FOUND")
    return row


def find_dealer(row_id):
    row = store.dealers.get(row_id)
    if row is None:
        raise ApiError("ERR_DEALER_NOT_FOUND")
    return row


def find_crew(row_id):
    row = store.installation_crews.get(row_id)
    if row is None:
        raise ApiError("ERR_INSTALLATION_CREW_NOT_FOUND")
    return row


# ---------------------------------------------------------------------------
# Engineers
# ---------------------------------------------------------------------------
@bp.post("/engineers")
def create_engineer():
    authorize(("PlantAdmin",))
    payload = body()
    row = {
        "name": req_str(payload, "name"),
        "license_number": req_str(payload, "license_number"),
        "licensed_jurisdiction_codes": req_str_array(payload, "licensed_jurisdiction_codes"),
        "status": "ACTIVE",
    }
    insert(store.engineers, row)
    return created(serializers.engineer(row))


@bp.get("/engineers")
def list_engineers():
    authorize(ALL_ROLES)
    rows = store.ordered(store.engineers)
    status = request.args.get("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    return paginated(rows, serializers.engineer)


@bp.get("/engineers/<row_id>")
def read_engineer(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.engineer(find_engineer(row_id)))


@bp.post("/engineers/<row_id>/lapse")
def lapse_engineer(row_id):
    authorize(("PlantAdmin",))
    engineer = find_engineer(row_id)
    engineer["status"] = "LAPSED"
    touch(engineer)
    return ok(serializers.engineer(engineer))


# ---------------------------------------------------------------------------
# Dealerships
# ---------------------------------------------------------------------------
@bp.post("/dealers")
def create_dealer():
    authorize(("PlantAdmin",))
    payload = body()
    name = req_str(payload, "name")
    region_code = req_str(payload, "region_code")
    jurisdiction_id = req_str(payload, "jurisdiction_id")
    credit_limit_cents = req_int(payload, "credit_limit_cents", minimum=0, maximum=100000000000)
    program_tier = req_enum(payload, "program_tier", ("BASE", "PREFERRED", "ELITE"))
    staging_slots = req_int(payload, "staging_slots", minimum=1, maximum=20)
    high_cube_access = req_bool(payload, "high_cube_access")

    find_config(store.jurisdictions, jurisdiction_id)

    row = {
        "name": name,
        "region_code": region_code,
        "jurisdiction_id": jurisdiction_id,
        "credit_limit_cents": credit_limit_cents,
        "program_tier": program_tier,
        "staging_slots": staging_slots,
        "high_cube_access": high_cube_access,
        "credit_committed_cents": 0,
        "credit_available_cents": credit_limit_cents,
        "staged_kit_count": 0,
        "status": "ACTIVE",
    }
    insert(store.dealers, row)
    return created(serializers.dealer(row))


@bp.get("/dealers")
def list_dealers():
    authorize(ALL_ROLES)
    rows = store.ordered(store.dealers)
    jurisdiction_id = request.args.get("jurisdiction_id")
    if jurisdiction_id:
        rows = [row for row in rows if row["jurisdiction_id"] == jurisdiction_id]
    return paginated(rows, serializers.dealer)


@bp.get("/dealers/<row_id>")
def read_dealer(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.dealer(find_dealer(row_id)))


@bp.post("/dealers/<row_id>/credit-limit")
def reset_credit_limit(row_id):
    authorize(("PlantAdmin",))
    payload = body()
    limit = req_int(payload, "credit_limit_cents", minimum=0, maximum=100000000000)
    dealer = find_dealer(row_id)
    dealer["credit_limit_cents"] = limit
    services.recompute_dealer_ledger(dealer)
    return ok(serializers.dealer(dealer))


@bp.get("/dealers/<row_id>/installation-crews")
def list_dealer_crews(row_id):
    authorize(ALL_ROLES)
    dealer = find_dealer(row_id)
    return paginated(store.crews_of_dealer(dealer["id"]), serializers.installation_crew)


# ---------------------------------------------------------------------------
# Erection crews
# ---------------------------------------------------------------------------
@bp.post("/installation-crews")
def create_crew():
    authorize(("PlantAdmin",))
    payload = body()
    dealer_id = req_str(payload, "dealer_id")
    crew_name = req_str(payload, "crew_name")
    tier = req_enum(payload, "certification_tier", ("T1", "T2", "T3"))
    certified_until = req_dt(payload, "certified_until")

    find_dealer(dealer_id)

    row = {
        "dealer_id": dealer_id,
        "crew_name": crew_name,
        "certification_tier": tier,
        "max_diameter_m": calc.CREW_TIER_MAX_DIAMETER_M[tier],
        "certified_until": certified_until,
        "status": "CERTIFIED",
    }
    insert(store.installation_crews, row)
    return created(serializers.installation_crew(row))


@bp.get("/installation-crews")
def list_crews():
    authorize(ALL_ROLES)
    rows = store.ordered(store.installation_crews)
    dealer_id = request.args.get("dealer_id")
    if dealer_id:
        rows = [row for row in rows if row["dealer_id"] == dealer_id]
    return paginated(rows, serializers.installation_crew)


@bp.get("/installation-crews/<row_id>")
def read_crew(row_id):
    authorize(ALL_ROLES)
    return ok(serializers.installation_crew(find_crew(row_id)))
