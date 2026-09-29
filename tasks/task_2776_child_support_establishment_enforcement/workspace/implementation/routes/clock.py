"""Logical clock control (PRD 2.4)."""
import db
import middleware
import response
import util
import validate
from common import PREFIX


def register(app):
    @app.post(PREFIX + "/_clock/set_current_utc")
    def set_clock():
        middleware.authenticate(["ProgramAdmin"])
        payload = validate.body()
        instant = validate.req_instant(payload, "to_iso8601")
        db.set_clock(instant)
        _establish_ripe_acknowledgments(instant)
        return response.ok({})


def _establish_ripe_acknowledgments(new_clock):
    """A deadline strictly before the new clock establishes; equality does not."""
    for action in db.ordered(list(db.paternity_actions.values())):
        if action["status"] != "AOP_SIGNED":
            continue
        deadline = action["rescission_deadline_at"]
        if deadline is None or not (deadline < new_clock):
            continue
        action["status"] = "ESTABLISHED"
        action["established_method"] = "VOLUNTARY_ACKNOWLEDGMENT"
        action["established_at"] = new_clock
        db.touch(action)
        case = db.cases.get(action["case_id"])
        if case is not None and case["case_status"] != "CLOSED":
            case["case_status"] = "ORDER_ESTABLISHMENT"
            db.touch(case)
