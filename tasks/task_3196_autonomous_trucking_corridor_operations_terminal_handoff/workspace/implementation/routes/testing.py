"""Declared test-driving endpoints — PRD §3.13, endpoints 171-173.

"None of the three persists a business field — they apply their effect and return
without mutating any entity."
"""

from core import ApiError
from response import ok_empty
from http_util import body
from routes._common import route


def register(app):

    @route(app, "/_testing/simulate-vehicle-routing/I2", ["POST"], ["ComplianceOfficer"])
    def simulate_terminal_routing():
        raw = body()
        allowed = {"terminal_id", "plan_code", "lift_minutes"}
        _validate(raw, allowed, required=("terminal_id", "plan_code", "lift_minutes"))
        return ok_empty(200)

    @route(app, "/_testing/simulate-vehicle-routing/I5", ["POST"], ["IncidentReviewer"])
    def simulate_corridor_routing():
        raw = body()
        allowed = {"corridor_id", "plan_code", "lift_minutes"}
        _validate(raw, allowed, required=("corridor_id", "plan_code", "lift_minutes"))
        return ok_empty(200)

    @route(app, "/_testing/simulate-ring-maintenance/I5", ["POST"], ["IncidentReviewer"])
    def simulate_ring_maintenance():
        """The ring-maintenance driver takes no lift figure at all."""
        raw = body()
        allowed = {"unit_id", "ring_code"}
        _validate(raw, allowed, required=("unit_id", "ring_code"))
        return ok_empty(200)


def _validate(raw, allowed, required):
    for key in raw:
        if key not in allowed:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
    for key in required:
        if key not in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Required field '%s' is missing." % key)