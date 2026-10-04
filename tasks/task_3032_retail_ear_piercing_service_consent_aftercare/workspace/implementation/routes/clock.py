"""The evaluator-controlled logical clock (PRD 3.10)."""

from flask import Blueprint

import db
import response as R
from middleware import authenticated
from services import common

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@authenticated("ComplianceOfficer")
def set_current_utc():
    data = common.body()
    current_utc = common.require_instant(data, "current_utc")
    db.DB.clock = current_utc
    common.sweep_clock_driven_transitions()
    return R.success({}, "object", 200)