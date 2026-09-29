"""Identity, authorization, club scope and path-existence resolution.

Implements steps 1 to 5 of the order of refusal in PRD section 2.8, in that
order: ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, the eleven 404s resolved left to
right, ERR_CLUB_SCOPE_VIOLATION, then the Member ownership rule.
"""

import functools

from flask import g, request

import derive
import store
from errors import fail

ROLES = ("NgbAdmin", "ClubAdministrator", "ScreeningVendor", "SafeSportOfficer",
         "ComplianceAuditor", "Member")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if not role or not role.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role")
    g.user_id = user_id
    g.role = role


def endpoint(*roles):
    """Bind an authenticated, authorized handler and apply the lazily
    evaluated clock transitions before it reads any row."""
    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(**kwargs):
            authenticate()
            if g.role not in roles:
                fail("ERR_UNAUTHORIZED", "%s may not call this endpoint" % g.role)
            derive.sync()
            return handler(**kwargs)
        return wrapper
    return decorator


def payload():
    if not request.get_data():
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        fail("ERR_VALIDATION", "request body must be valid JSON")
    return parsed


# ------------------------------------------------------- path existence (3) --
def _get(table, row_id, error_id, label):
    row = table.get(row_id)
    if row is None:
        fail(error_id, "%s %s does not exist" % (label, row_id))
    return row


def club(club_id):
    return _get(store.CLUBS, club_id, "ERR_CLUB_NOT_FOUND", "club")


def member(member_id):
    return _get(store.MEMBERS, member_id, "ERR_MEMBER_NOT_FOUND", "member")


def screening_order(order_id):
    return _get(store.SCREENING_ORDERS, order_id, "ERR_SCREENING_ORDER_NOT_FOUND",
                "screening order")


def training_assignment(assignment_id):
    return _get(store.TRAINING_ASSIGNMENTS, assignment_id,
                "ERR_TRAINING_ASSIGNMENT_NOT_FOUND", "training assignment")


def coach_assignment(assignment_id):
    return _get(store.COACH_ASSIGNMENTS, assignment_id,
                "ERR_COACH_ASSIGNMENT_NOT_FOUND", "coach assignment")


def investigating_body(body_id):
    return _get(store.INVESTIGATING_BODIES, body_id, "ERR_INVESTIGATING_BODY_NOT_FOUND",
                "investigating body")


def case(case_id):
    return _get(store.CASES, case_id, "ERR_CASE_NOT_FOUND", "case")


def interim_measure(measure_id):
    return _get(store.INTERIM_MEASURES, measure_id, "ERR_INTERIM_MEASURE_NOT_FOUND",
                "interim measure")


def club_audit(audit_id):
    return _get(store.CLUB_AUDITS, audit_id, "ERR_CLUB_AUDIT_NOT_FOUND", "club audit")


def audit_finding(finding_id):
    return _get(store.AUDIT_FINDINGS, finding_id, "ERR_AUDIT_FINDING_NOT_FOUND",
                "audit finding")


def room_stay(stay_id):
    return _get(store.ROOM_STAYS, stay_id, "ERR_ROOM_STAY_NOT_FOUND", "room stay")


# --------------------------------------------------------- club scope (4) --
def scope(club_id):
    """A ClubAdministrator's X-User-ID must equal the owning club."""
    if g.role == "ClubAdministrator" and g.user_id != club_id:
        fail("ERR_CLUB_SCOPE_VIOLATION", "resource belongs to another club")


def scope_member(member_row):
    scope(member_row["club_id"])


def scope_finding(finding):
    audit = store.CLUB_AUDITS.get(finding["audit_id"])
    if audit is not None:
        scope(audit["club_id"])


def scope_measure(measure):
    subject = store.MEMBERS.get(measure["member_id"])
    if subject is not None:
        scope_member(subject)


def is_club_admin():
    return g.role == "ClubAdministrator"


def own_club():
    return g.user_id


# ----------------------------------------------------- member ownership (5) --
def owner(member_id):
    if g.role == "Member" and g.user_id != member_id:
        fail("ERR_UNAUTHORIZED", "a member may act only on their own resources")
