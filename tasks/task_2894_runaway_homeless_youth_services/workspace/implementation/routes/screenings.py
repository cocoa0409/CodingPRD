"""Safety-screening disposition and the specialized anti-trafficking response."""

from flask import Blueprint

import authz
import cascade
import envelope
import find
import serial
import shape
import store
from errors import fail

bp = Blueprint("screenings", __name__)

DISPOSITIONS = ("CLEARED", "ESCALATED")
RESPONSE_CODES = ("NONE", "ADVOCATE_ASSIGNED", "LAW_ENFORCEMENT_LIAISON", "EMERGENCY_RELOCATION")

# PRD 2.10 rule 13 / 3.2: the declared transitions of the screening machine.
DECLARED_TRANSITIONS = {
    ("SUBMITTED", "CLEARED"),
    ("SUBMITTED", "ESCALATED"),
    ("ESCALATED", "CLEARED"),
    ("CLEARED", "ESCALATED"),
}


@bp.post("/ryhs/safety-screenings/<screening_id>/disposition")
def disposition(screening_id):
    user_id, _role = authz.require(authz.PROGRAM_ADMIN)
    screening = find.screening(screening_id)
    body = shape.body()
    decision = shape.need_enum(body, "disposition", DISPOSITIONS)
    # PRD 3.2: the response code "defaults to NONE when omitted".
    response_code = shape.opt_enum(body, "specialized_response_code", RESPONSE_CODES, "NONE")
    if decision == "ESCALATED" and response_code == "NONE":
        # "Escalating in either direction requires a specialized_response_code other
        # than NONE, because an escalation without a specialized response is
        # meaningless" - a constraint on the supplied field, so a request-shape failure.
        fail(
            "ERR_INVALID_REQUEST",
            "specialized_response_code must not be NONE when escalating a screening",
        )

    # Ladder 13: the requested disposition is a declared transition.
    if (screening["status"], decision) not in DECLARED_TRANSITIONS:
        fail("ERR_SCREENING_INVALID_TRANSITION")
    if (
        screening["status"] == "ESCALATED"
        and decision == "CLEARED"
        and screening["specialized_response_code"] == "NONE"
    ):
        # "re-clearing an escalated screening requires that the escalated row already
        # carries a response code other than NONE, evidencing that a specialized
        # response actually ran."
        fail(
            "ERR_SCREENING_INVALID_TRANSITION",
            "an escalated screening may only be cleared once a specialized response has run",
        )

    # Ladder 18: a screening in the CRITICAL tier may not be cleared.
    if decision == "CLEARED" and screening["tier"] == "CRITICAL":
        fail("ERR_SCREENING_CRITICAL_TIER")

    # Ladder 24: whoever dispositions the screening must not be the submitter.
    if user_id == screening["screener_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    screening["status"] = decision
    screening["specialized_response_code"] = response_code
    screening["disposition_user_id"] = user_id
    store.touch(screening)

    youth = store.youths[screening["youth_id"]]
    posture_changed = cascade.apply_youth_derived(youth)

    activated = None
    if decision == "CLEARED":
        # PRD 3.2: the youth's oldest admission still waiting on screening advances to
        # its active stay. "Exactly one admission is activated per clearance."
        pending = store.ordered(
            [
                a
                for a in store.admissions.values()
                if a["youth_id"] == youth["id"] and a["status"] == "PENDING_SCREENING"
            ]
        )
        if pending:
            candidate = pending[0]
            program = store.programs.get(candidate["program_id"])
            # "Activation also requires that the program's posture is not FROZEN at
            # disposition time."
            if program is not None and program["posture"] != "FROZEN":
                cascade.activate_admission(candidate, store.now())
                store.touch(candidate)
                activated = candidate

    if activated is None and posture_changed:
        store.touch(youth)

    return envelope.ok(serial.screening(screening))
