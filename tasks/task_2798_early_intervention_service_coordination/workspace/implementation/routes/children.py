"""Child registration and retrieval."""
from flask import Blueprint

import domain as D
from auth import STAFF_READ, endpoint
from envelope import single
from errors import fail
from helpers import get_child, ser_child
from services import compute
from store import clock_date, db, flush, iso_date, new_row, pd
from validate import Field, parse_body, v_date, v_str, v_token

bp = Blueprint("children", __name__)


@bp.route("/ei/children", methods=["POST"])
@endpoint(["IntakeSpecialist"])
def create_child():
    payload = parse_body([
        Field("first_name", v_str()),
        Field("last_name", v_str()),
        Field("date_of_birth", v_date()),
        Field("county_code", v_token()),
        Field("primary_language", v_token()),
    ])
    dob = pd(payload["date_of_birth"])
    if dob > clock_date():
        fail("ERR_INVALID_REQUEST",
             "Field 'date_of_birth' must not be later than the current logical date.")
    child = new_row({
        "first_name": payload["first_name"],
        "last_name": payload["last_name"],
        "date_of_birth": payload["date_of_birth"],
        "county_code": payload["county_code"],
        "primary_language": payload["primary_language"],
        "third_birthday_date": iso_date(compute.third_birthday_date(dob)),
        "active_referral_count": 0,
    })
    db.children[child["id"]] = child
    flush()
    return single(ser_child(child), 201)


@bp.route("/ei/children/<child_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_child(child_id):
    return single(ser_child(get_child(child_id)))
