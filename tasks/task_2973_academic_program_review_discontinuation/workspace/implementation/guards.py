"""Checks 1-8 of the refusal waterfall (PRD 2.10) plus small shared gates."""

from flask import request

from errors import ApiError
from store import db

ROLES = (
    "ProgramChair",
    "ExternalReviewer",
    "ReviewCoordinator",
    "Provost",
    "Registrar",
    "HRPartner",
)

CHAIR = "ProgramChair"
REVIEWER = "ExternalReviewer"
COORD = "ReviewCoordinator"
PROVOST = "Provost"
REGISTRAR = "Registrar"
HR = "HRPartner"

# Closed action vocabularies (PRD 2.1). A value outside the set for the
# endpoint it was sent to is an enum-range failure at check 9.
ACTIONS_SELF_STUDY = ("SUBMIT", "RETURN", "ACCEPT")
ACTIONS_PLAN = ("SUBMIT", "RETURN", "APPROVE", "ACTIVATE")
ACTIONS_DECISION = ("RATIFY", "EFFECTUATE", "RESCIND", "EVALUATE_IMPROVEMENT")
ACTIONS_NOTIFICATION = ("SEND", "ACKNOWLEDGE")
ACTIONS_APPOINTMENT = (
    "RETAIN",
    "PROPOSE_REASSIGNMENT",
    "WITHDRAW_REASSIGNMENT",
    "CONFIRM_REASSIGNMENT",
    "ISSUE_NOTICE",
    "SEPARATE",
)
ACTIONS_SEAT = ("COMMIT", "RELEASE", "SUBSTITUTE", "WAIVE")
ACTIONS_PROGRESS = ("COMPLETE", "WITHDRAW")

# Per-(endpoint, action) grants for the three shared endpoints (PRD 2.1).
OWNERS_SELF_STUDY = {"SUBMIT": (CHAIR,), "RETURN": (COORD,), "ACCEPT": (COORD,)}
OWNERS_PLAN = {
    "SUBMIT": (CHAIR,),
    "RETURN": (PROVOST,),
    "APPROVE": (PROVOST,),
    "ACTIVATE": (COORD,),
}
OWNERS_DECISION = {
    "RATIFY": (PROVOST,),
    "RESCIND": (PROVOST,),
    "EFFECTUATE": (COORD,),
    "EVALUATE_IMPROVEMENT": (COORD,),
}

TERMINAL_LIFECYCLE = ("DISCONTINUED", "CONSOLIDATED")


class Ctx(object):
    """Carries the authenticated identity and the parsed request body."""

    def __init__(self, role, user_id, body):
        self.role = role
        self.user_id = user_id
        self.body = body if isinstance(body, dict) else None
        self.action = None
        if isinstance(body, dict):
            candidate = body.get("action")
            if isinstance(candidate, str):
                self.action = candidate

    # ---- check 4 -------------------------------------------------------
    def chair_owner(self, program):
        if self.role == CHAIR and program is not None:
            if program["id"] != self.user_id:
                raise ApiError("ERR_NOT_PROGRAM_OWNER")

    # ---- check 5 -------------------------------------------------------
    def reviewer_owner(self, visit):
        if self.role == REVIEWER and visit is not None:
            if visit["reviewer_id"] != self.user_id:
                raise ApiError("ERR_NOT_ASSIGNED_REVIEWER")

    # ---- check 6 -------------------------------------------------------
    def segregation(self, decision):
        if decision is None:
            return
        if self.action == "RATIFY" and self.user_id == decision.get("proposed_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # ---- check 7 / 8 ---------------------------------------------------
    @staticmethod
    def require(row, error_id):
        if row is None:
            raise ApiError(error_id)
        return row

    # ---- check 9 helper ------------------------------------------------
    def require_object_body(self):
        if self.body is None:
            raise ApiError("ERR_VALIDATION", "A JSON object body is required.")
        return self.body

    # ---- check 11 ------------------------------------------------------
    @staticmethod
    def not_terminal(program):
        if program is not None and program["lifecycle_state"] in TERMINAL_LIFECYCLE:
            raise ApiError("ERR_PROGRAM_ALREADY_TERMINAL")


def begin(roles, action_owners=None):
    """Checks 1, 2 and 3 for every endpoint."""
    role_hdr = request.headers.get("X-User-Role")
    user_hdr = request.headers.get("X-User-ID")
    if role_hdr is None or user_hdr is None:
        raise ApiError("ERR_MISSING_AUTH_HEADER")
    if role_hdr.strip() == "" or user_hdr.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADER")
    if role_hdr not in ROLES:
        raise ApiError("ERR_INVALID_ROLE")

    body = request.get_json(silent=True)
    ctx = Ctx(role_hdr, user_hdr, body)

    if role_hdr not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if action_owners and ctx.action in action_owners:
        if role_hdr not in action_owners[ctx.action]:
            raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return ctx


# --------------------------------------------------------------------------
# transitive resolution helpers used by checks 4 and 11
# --------------------------------------------------------------------------

def program_of_cycle(cycle):
    if cycle is None:
        return None
    return db.programs.get(cycle["program_id"])


def program_of_self_study(self_study):
    if self_study is None:
        return None
    return program_of_cycle(db.cycles.get(self_study["cycle_id"]))


def program_of_visit(visit):
    if visit is None:
        return None
    return program_of_cycle(db.cycles.get(visit["cycle_id"]))


def program_of_decision(decision):
    if decision is None:
        return None
    return program_of_cycle(db.cycles.get(decision["cycle_id"]))


def program_of_notification(notification):
    if notification is None:
        return None
    return program_of_decision(db.decisions.get(notification["decision_id"]))


def program_of_plan(plan):
    if plan is None:
        return None
    return db.programs.get(plan["program_id"])


def program_of_guarantee(guarantee):
    if guarantee is None:
        return None
    return program_of_plan(db.plans.get(guarantee["teach_out_plan_id"]))


def program_of_student(student):
    if student is None:
        return None
    return program_of_plan(db.plans.get(student["teach_out_plan_id"]))


def program_of_appointment(appointment):
    if appointment is None:
        return None
    return db.programs.get(appointment["program_id"])
