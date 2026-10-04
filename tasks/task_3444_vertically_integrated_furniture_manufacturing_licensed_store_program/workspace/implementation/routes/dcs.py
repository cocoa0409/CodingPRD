"""Distribution centers (PRD §3.6)."""
from flask import Blueprint

from constants import (
    DEFAULT_DAILY_CREW_UNITS, MAX_DAILY_CREW_UNITS, MIN_DAILY_CREW_UNITS,
)
from db import store
from errors import err
from middleware import auth, require_role
from util import (
    get_body, new_record, ok_object, opt_int, req_bool, req_list, req_str, serialize,
)

bp = Blueprint("dcs", __name__)


def get_dc(did):
    d = store.dcs.get(did)
    if d is None:
        err("ERR_DC_NOT_FOUND", "unknown distribution center id")
    return d


@bp.route("/api/distribution-centers", methods=["POST"])
def create_dc():
    _uid, role = auth()
    data = get_body()
    code = req_str(data, "code")
    supports = req_bool(data, "supports_home_delivery")
    crew = opt_int(
        data, "daily_crew_units", DEFAULT_DAILY_CREW_UNITS,
        minimum=MIN_DAILY_CREW_UNITS, maximum=MAX_DAILY_CREW_UNITS,
    )
    regions = req_list(data, "region_codes")
    if any(not isinstance(x, str) for x in regions):
        err("ERR_VALIDATION", "region_codes must be an array of strings")
    require_role(role, ["PlatformAdmin"])
    if any(d["code"] == code for d in store.dcs.values()):
        err("ERR_VALIDATION", "DC code must be unique")
    rec = new_record()
    rec.update({
        "code": code,
        "supports_home_delivery": supports,
        "daily_crew_units": crew,
        "region_codes": list(regions),
    })
    store.dcs[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/api/distribution-centers/<did>", methods=["GET"])
def fetch_dc(did):
    auth()
    return ok_object(serialize(get_dc(did)), 200)
