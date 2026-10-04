"""In-use compliance results (PRD §3.4): append-only, latest stamp wins."""
from flask import Blueprint

import calculations
import clock
import store
from errors import ApiError
from rbac import auth
from validators import (
    body, f_str, f_int, get_or_404,
    envelope_ok, new_append, touch, ser,
)

bp = Blueprint("in_use_compliance", __name__)

MIN_IN_USE_SAMPLE_SIZE = 5


@bp.post("/emissions/engine-families/<familyId>/in-use-results")
def create_in_use_result(familyId):
    auth(("RegulatoryOfficer",))
    b = body()
    label = f_str(b, "test_period_label")
    sample_size = f_int(b, "sample_size", min_v=1)
    passing = f_int(b, "passing_units", min_v=0)
    if passing > sample_size:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "passing_units must not exceed sample_size")
    fam = get_or_404(store.families, familyId, "EngineFamily")
    # state gate (priority 7)
    if fam["certification_status"] != "IN_PRODUCTION":
        raise ApiError("ERR_FAMILY_NOT_IN_PRODUCTION", 409,
                       "In-use results require the family IN_PRODUCTION")
    # structural minimum sample (priority 11)
    if sample_size < MIN_IN_USE_SAMPLE_SIZE:
        raise ApiError("ERR_SAMPLE_SIZE_TOO_SMALL", 422,
                       "sample_size must be at least %d" % MIN_IN_USE_SAMPLE_SIZE)
    ratio, outcome = calculations.conformity(passing, sample_size)
    rec = new_append()
    rec.update({
        "engine_family_id": fam["id"],
        "test_period_label": label,
        "sample_size": sample_size,
        "passing_units": passing,
        "conformity_ratio": ratio,
        "outcome": outcome,
        "recorded_at": clock.now_dt(),
    })
    store.in_use_results[rec["id"]] = rec
    # latest recorded result stamps the family (recording order decides)
    fam["in_use_compliance_status"] = outcome
    touch(fam)
    return envelope_ok(ser(rec), 201)
