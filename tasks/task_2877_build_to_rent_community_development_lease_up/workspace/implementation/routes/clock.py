"""The logical clock (PRD section 2.9). Any role may drive it, and it moves forward only."""
from __future__ import annotations

from flask import Blueprint

from calc import iso
from db import set_field, store
from errors import ApiError
from middleware import ALL_OPERATOR_ROLES, endpoint
from response import ok_data
from services import community as community_service
from validation import body, req_instant

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(*ALL_OPERATOR_ROLES)
def set_current_utc():
    payload = body()
    current_utc = req_instant(payload, "current_utc")
    if current_utc <= store.clock:
        raise ApiError("ERR_CLOCK_REWIND")
    store.clock = current_utc
    # The one business side effect of advancing the clock.
    for community in list(store.communities.values()):
        if (community["management_mode"] == "PM_TRANSITION_PENDING"
                and community["_pm_effective_from"] is not None
                and community["_pm_effective_from"] <= current_utc):
            set_field(community, "management_mode", "PM_MANAGED")
    return ok_data({"current_utc": iso(current_utc)})
