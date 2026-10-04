"""Household and property routes (PRD 3.1)."""

from flask import Blueprint

from constants import (
    CREDIT_SCORE_MAX,
    CREDIT_SCORE_MIN,
    DEFAULT_MAX_DTI_BPS,
    ROLES,
)
from errors import ERR_INVALID_REQUEST, ApiError
from routes import endpoint, json_body, query_params
from services import create, touch
from services.lookup import get_homeowner, get_property
from services.property import create_property, record_site_visit
from store import db
from validation import body_of, get_int, get_str

bp = Blueprint("households", __name__)

COORDINATOR = ROLES[0]
HOMEOWNER = ROLES[2]


@bp.post("/knock/homeowners")
@endpoint([COORDINATOR], status=201)
def register_homeowner(actor):
    data = body_of(json_body())

    full_name = get_str(data, "full_name", required=True)
    email = get_str(data, "email", required=True)
    credit_score = get_int(
        data, "credit_score", required=True, minimum=CREDIT_SCORE_MIN, maximum=CREDIT_SCORE_MAX
    )
    household_income_cents = get_int(data, "household_income_cents", required=True, minimum=0)
    max_dti_bps = get_int(data, "max_dti_bps", required=False, default=DEFAULT_MAX_DTI_BPS, minimum=0)

    for existing in db.all("homeowners"):
        if existing.get("email") == email:
            raise ApiError(ERR_INVALID_REQUEST, "email must be unique across homeowners.")

    record = {
        "full_name": full_name,
        "email": email,
        "credit_score": credit_score,
        "household_income_cents": household_income_cents,
        "max_dti_bps": max_dti_bps,
        "departing_equity_cents": 0,
        "program_status": "NONE",
        "sealed_flag": False,
    }
    return create("homeowners", record)


@bp.get("/knock/homeowners/<homeowner_id>")
@endpoint([COORDINATOR, HOMEOWNER])
def read_homeowner(actor, homeowner_id):
    return get_homeowner(homeowner_id)


@bp.post("/knock/properties")
@endpoint([COORDINATOR], status=201)
def register_property(actor):
    return create_property(json_body())


@bp.get("/knock/properties")
@endpoint([COORDINATOR])
def list_properties(actor):
    params = query_params()
    homeowner_id = params.get("homeowner_id")
    if homeowner_id:
        # A filter that names a household resolves it, so a bad id is a 404.
        get_homeowner(homeowner_id)

    records = db.all("properties")
    if homeowner_id:
        records = [r for r in records if r.get("homeowner_id") == homeowner_id]
    return db.sorted_by_created(records), params


@bp.get("/knock/properties/<property_id>")
@endpoint([COORDINATOR, HOMEOWNER])
def read_property(actor, property_id):
    return get_property(property_id)


@bp.post("/knock/properties/<property_id>/site-visits")
@endpoint([COORDINATOR])
def create_site_visit(actor, property_id):
    return record_site_visit(property_id)