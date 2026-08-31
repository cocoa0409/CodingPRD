"""Rung 9 helpers: state legality, terminal states and path resolution."""

from core.errors import ApiError, NOT_FOUND
from core.store import store

TERMINAL = {
    "Referral": {"ACCEPTED", "DECLINED"},
    "Participant": {"WITHDRAWN"},
    "Cohort": {"COMPLETED", "CANCELLED"},
    "Enrollment": {"COMPLETED", "WITHDRAWN", "EXPIRED"},
    "Counselor": {"INACTIVE"},
    "CounselingReferral": {"CLOSED", "CANCELLED"},
    "VolunteerCompanion": set(),
    "CompanionMatch": {"DECLINED", "ENDED"},
    "RemembranceEvent": {"HELD", "CANCELLED"},
    "Invitation": {"ACCEPTED", "DECLINED", "EXPIRED", "VOID"},
    "FundingAllocation": {"SETTLED", "RELEASED"},
    "GrantReport": {"ACCEPTED"},
    "GrantAward": {"CLOSED"},
    "AnniversaryOutreach": {"ACKNOWLEDGED", "NO_RESPONSE", "CANCELLED"},
    "MeetingSpace": set(),
}


def must_exist(kind, rid):
    """Path / body existence with the entity's own not-found code."""
    rec = store.get(kind, rid)
    if rec is None:
        raise ApiError(NOT_FOUND[kind], "No %s with id %s." % (kind, rid))
    return rec


def status_of(rec):
    if "status" in rec:
        return rec["status"]
    return rec.get("service_status")


def transition(rec, allowed, error_id=None):
    """The addressed resource must sit in a state the transition is declared from."""
    current = status_of(rec)
    if current in allowed:
        return
    kind = rec.get("_kind")
    if current in TERMINAL.get(kind, set()):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "%s is already in terminal state %s." % (kind, current))
    raise ApiError(error_id or "ERR_INVALID_STATE",
                   "%s in state %s does not allow this transition." % (kind, current))


def require_participant_active(participant):
    """Any participant-scoped write is refused once the participant withdrew."""
    if participant["service_status"] == "WITHDRAWN":
        raise ApiError("ERR_PARTICIPANT_WITHDRAWN", "The participant has withdrawn.")
