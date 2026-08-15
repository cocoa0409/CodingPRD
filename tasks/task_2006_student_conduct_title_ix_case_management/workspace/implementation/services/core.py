"""Core shared services: record lifecycle, audit events, notices, case helpers,
exposure scoring, segregation-of-duties, and list plumbing."""
from datetime import timedelta
from flask import request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_CASE_ALREADY_TERMINAL,
    ERR_SEGREGATION_OF_DUTIES, ERR_OFFICIAL_IS_CASE_PARTY, ERR_NO_ACTIVE_INVESTIGATOR,
)
from util import new_id, now_ts, clock_iso, clock_dt, parse_datetime, next_seq

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

ROLE_TYPES = ["STUDENT", "EMPLOYEE", "FACULTY", "STAFF", "EXTERNAL"]
CATEGORIES = [
    "SEXUAL_HARASSMENT", "SEXUAL_ASSAULT", "DATING_VIOLENCE", "DOMESTIC_VIOLENCE",
    "STALKING", "OTHER_SEX_BASED", "NON_TITLE_IX_MISCONDUCT",
]
TITLE_IX_CATEGORIES = [
    "SEXUAL_HARASSMENT", "SEXUAL_ASSAULT", "DATING_VIOLENCE", "DOMESTIC_VIOLENCE",
    "STALKING", "OTHER_SEX_BASED",
]
RECEIVED_VIA = ["ONLINE_FORM", "IN_PERSON", "EMAIL", "THIRD_PARTY", "ANONYMOUS"]
STANDARDS = ["PREPONDERANCE", "CLEAR_AND_CONVINCING"]
DISMISSAL_REASONS = [
    "MANDATORY_NO_JURISDICTION", "DISCRETIONARY_COMPLAINANT_WITHDRAWN",
    "DISCRETIONARY_RESPONDENT_DEPARTED", "DISCRETIONARY_EVIDENCE_UNAVAILABLE",
]
MEASURE_TYPES = [
    "COUNSELING", "COURSE_ADJUSTMENT", "HOUSING_CHANGE", "SCHEDULE_CHANGE",
    "EXTENSION", "ESCORT", "SAFETY_PLAN", "OTHER",
]
MEASURE_SIDES = ["COMPLAINANT", "RESPONDENT", "BOTH"]
DIRECTIVE_SIDES = ["COMPLAINANT", "RESPONDENT", "MUTUAL"]
RESTRICTIONS = ["IN_PERSON", "ELECTRONIC", "THIRD_PARTY", "PROXIMITY"]
REPORTED_BY_SIDES = ["COMPLAINANT", "RESPONDENT", "STAFF"]
EVIDENCE_SIDES = ["COMPLAINANT", "RESPONDENT", "INVESTIGATOR"]
EVIDENCE_TYPES = ["DOCUMENT", "PHOTO", "VIDEO", "MESSAGE_RECORD", "TESTIMONY_SUMMARY", "OTHER"]
NOTICE_TYPES = [
    "ALLEGATIONS", "INTERVIEW", "EVIDENCE_RELEASE", "HEARING", "DETERMINATION",
    "DISMISSAL", "APPEAL_FILED", "APPEAL_OUTCOME", "INFORMAL_PROPOSAL",
]
NOTICE_SIDES = ["COMPLAINANT", "RESPONDENT", "BOTH"]
APPOINTMENT_SIDES = ["COMPLAINANT", "RESPONDENT"]
MODALITIES = ["IN_PERSON", "VIRTUAL"]
QUESTION_TARGET_SIDES = ["COMPLAINANT", "RESPONDENT"]
QUESTION_RULINGS = ["ALLOWED", "DISALLOWED"]
FINDINGS = ["RESPONSIBLE", "NOT_RESPONSIBLE", "INSUFFICIENT_EVIDENCE"]
SANCTION_TYPES = [
    "WARNING", "PROBATION", "SUSPENSION", "EXPULSION", "EDUCATIONAL_PROGRAM",
    "NO_CONTACT_CONTINUATION", "RESTITUTION",
]
APPEAL_TARGETS = ["DETERMINATION", "DISMISSAL"]
APPEAL_GROUNDS = [
    "PROCEDURAL_IRREGULARITY", "NEW_EVIDENCE", "CONFLICT_OF_INTEREST",
    "DISPROPORTIONATE_SANCTION",
]
APPEAL_OUTCOMES = ["AFFIRMED", "REVERSED", "REMANDED", "SANCTION_MODIFIED", "REINSTATED"]
REMAND_SCOPES = ["INVESTIGATION", "HEARING_PREPARATION"]
FILED_BY_SIDES = ["COMPLAINANT", "RESPONDENT"]

TERMINAL_CASE_STATES = {"CLOSED", "REFERRED_TO_CONDUCT", "RESOLVED_INFORMAL"}

LEAD_DAYS = {"INTERVIEW": 5, "HEARING": 10}
REVIEW_WINDOW_DAYS = 10
APPEAL_WINDOW_DAYS = 5
HEARING_BUFFER_MINUTES = 60
RETENTION_YEARS = 7

CATEGORY_BASE = {
    "SEXUAL_ASSAULT": 40, "DATING_VIOLENCE": 35, "DOMESTIC_VIOLENCE": 35,
    "STALKING": 30, "SEXUAL_HARASSMENT": 25, "OTHER_SEX_BASED": 15,
    "NON_TITLE_IX_MISCONDUCT": 0,
}
STAT_HIERARCHY_PRIORITY = {
    "SEXUAL_ASSAULT": 7, "DATING_VIOLENCE": 6, "DOMESTIC_VIOLENCE": 5,
    "STALKING": 4, "SEXUAL_HARASSMENT": 3, "OTHER_SEX_BASED": 2,
    "NON_TITLE_IX_MISCONDUCT": 1,
}
PRIOR_FINDING_POINTS = 15
NCD_VIOLATION_POINTS = 10
ACTIVE_DIRECTIVE_POINTS = 10
INTERIM_SUSPENSION_THRESHOLD = 70
ROLLING_WINDOW_DAYS = 365

LIVE_PACKET_STATES = {"DRAFT", "RELEASED_FOR_REVIEW", "REVIEW_CLOSED"}
LIVE_HEARING_STATES = {"SCHEDULED", "IN_SESSION", "ADJOURNED", "DELIBERATION"}
LIVE_IR_STATES = {"PROPOSED", "IN_PROGRESS"}
INVESTIGATOR_HELD_STATES = {"PROPOSED", "ACTIVE", "COMPLETED"}


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------

def new_record(collection, fields, with_version=True):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_ts()
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def bump_case(case):
    touch(case)


# ---------------------------------------------------------------------------
# Audit trail and auto-generated notices
# ---------------------------------------------------------------------------

def append_event(case_id, event_type, caller=None, details=None, system=False):
    if system or caller is None:
        actor_role, actor_id = "system", "system"
    else:
        actor_role, actor_id = caller.role, caller.user_id
    new_record("case_events", {
        "case_id": case_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "details": details or {},
        "occurred_at": clock_iso(),
    }, with_version=False)


def auto_notice(case_id, notice_type, recipient_side, body, scheduled_event_at=None):
    """Workflow-emitted notice; bypasses request validation but computes the
    lead-time flag per PRD 2.8 (true for non-event types)."""
    if notice_type in LEAD_DAYS and scheduled_event_at is not None:
        gap = (parse_datetime(scheduled_event_at) - clock_dt()).total_seconds()
        sufficient = gap >= LEAD_DAYS[notice_type] * 86400
    else:
        sufficient = True
    return new_record("notices", {
        "case_id": case_id,
        "notice_type": notice_type,
        "recipient_side": recipient_side,
        "body": body,
        "scheduled_event_at": scheduled_event_at,
        "sent_at": clock_iso(),
        "lead_time_sufficient": sufficient,
    }, with_version=False)


# ---------------------------------------------------------------------------
# Case helpers
# ---------------------------------------------------------------------------

def get_case(case_id):
    case = db["cases"].get(case_id)
    if case is None:
        raise_error(ERR_NOT_FOUND, f"case not found: {case_id}")
    return case


def check_case_not_terminal(case):
    """Tier 4 guard on case-nested child mutations (PRD 2.11)."""
    if case["status"] in TERMINAL_CASE_STATES:
        raise_error(ERR_CASE_ALREADY_TERMINAL,
                    f"case is in terminal state {case['status']}")


def case_events_for(case_id):
    return [e for e in db["case_events"].values() if e["case_id"] == case_id]


# ---------------------------------------------------------------------------
# Exposure scoring (PRD 2.7)
# ---------------------------------------------------------------------------

def category_base(case):
    best = max(case["categories"], key=lambda c: STAT_HIERARCHY_PRIORITY[c])
    return CATEGORY_BASE[best]


def count_respondent_priors(case):
    """Count of OTHER cases of the same respondent carrying a determination in
    ISSUED/FINAL/SUPERSEDED with finding RESPONSIBLE (REVERSED excluded)."""
    qualifying_case_ids = set()
    for det in db["determinations"].values():
        if det["status"] in ("ISSUED", "FINAL", "SUPERSEDED") \
                and det["responsibility_finding"] == "RESPONSIBLE":
            other = db["cases"].get(det["case_id"])
            if other is not None and other["id"] != case["id"] \
                    and other["respondent_id"] == case["respondent_id"]:
                qualifying_case_ids.add(other["id"])
    return len(qualifying_case_ids)


def rolling_substantiated_count(case, now):
    """Substantiated violations on this case's directives within the inclusive
    window [now - 365 days, now]."""
    window_start = now - timedelta(days=ROLLING_WINDOW_DAYS)
    directive_ids = {
        d["id"] for d in db["no_contact_directives"].values() if d["case_id"] == case["id"]
    }
    rows = [
        v for v in db["directive_violations"].values()
        if v["directive_id"] in directive_ids and v["status"] == "SUBSTANTIATED"
        and v.get("substantiated_at") is not None
        and window_start <= parse_datetime(v["substantiated_at"]) <= now
    ]
    rows.sort(key=lambda v: (parse_datetime(v["substantiated_at"]), v["created_at"], v["_seq"]))
    return len(rows)


def recompute_exposure(case):
    now = clock_dt()
    score = category_base(case)
    score += PRIOR_FINDING_POINTS * count_respondent_priors(case)
    score += NCD_VIOLATION_POINTS * rolling_substantiated_count(case, now)
    if any(d["case_id"] == case["id"] and d["status"] == "ACTIVE"
           for d in db["no_contact_directives"].values()):
        score += ACTIVE_DIRECTIVE_POINTS
    case["exposure_score"] = score
    case["interim_suspension_eligible"] = score >= INTERIM_SUSPENSION_THRESHOLD
    return score


def alltime_substantiated_count(case_id):
    directive_ids = {
        d["id"] for d in db["no_contact_directives"].values() if d["case_id"] == case_id
    }
    return sum(
        1 for v in db["directive_violations"].values()
        if v["directive_id"] in directive_ids and v["status"] == "SUBSTANTIATED"
    )


# ---------------------------------------------------------------------------
# Segregation of duties (PRD 2.6)
# ---------------------------------------------------------------------------

def recused_persons(case_id):
    return {
        a["investigator_id"]
        for a in db["investigator_assignments"].values()
        if a["case_id"] == case_id and a["status"] == "RECUSED"
    }


def investigator_function_holders(case_id):
    """Investigator function = any assignment in PROPOSED/ACTIVE/COMPLETED."""
    return {
        a["investigator_id"]
        for a in db["investigator_assignments"].values()
        if a["case_id"] == case_id and a["status"] in INVESTIGATOR_HELD_STATES
    }


def hearing_decision_makers(case_id):
    return {
        h["decision_maker_id"]
        for h in db["hearings"].values()
        if h["case_id"] == case_id
    }


def appeal_officers(case_id):
    return {
        a["appeal_officer_id"]
        for a in db["appeals"].values()
        if a["case_id"] == case_id and a.get("appeal_officer_id") is not None
    }


def facilitators(case_id):
    """Facilitator function = facilitator of a LIVE informal resolution
    (PROPOSED/IN_PROGRESS). A withdrawn/terminated resolution releases the
    function, so the same facilitator may be re-proposed (withdrawal cycle)."""
    return {
        ir["facilitator_id"]
        for ir in db["informal_resolutions"].values()
        if ir["case_id"] == case_id and ir["status"] in LIVE_IR_STATES
    }


def function_holders(case, function, exclude_assignment_id=None):
    """Current holders of one official function on the case."""
    cid = case["id"]
    if function == "coordinator":
        return {case["coordinator_id"]}
    if function == "investigator":
        return {
            a["investigator_id"]
            for a in db["investigator_assignments"].values()
            if a["case_id"] == cid and a["status"] in INVESTIGATOR_HELD_STATES
            and a["id"] != exclude_assignment_id
        }
    if function == "decision_maker":
        return hearing_decision_makers(cid)
    if function == "appeal_officer":
        return appeal_officers(cid)
    if function == "facilitator":
        return facilitators(cid)
    return set()


ALL_FUNCTIONS = ("coordinator", "investigator", "decision_maker", "appeal_officer", "facilitator")


def all_officials(case):
    officials = set()
    for fn in ALL_FUNCTIONS:
        officials |= function_holders(case, fn)
    return officials


def check_not_case_party(case, person_id):
    """Tier 5, more specific than generic segregation."""
    if person_id in (case["complainant_id"], case["respondent_id"]):
        raise_error(ERR_OFFICIAL_IS_CASE_PARTY,
                    "official function assignee is the case complainant or respondent")


def check_segregation(case, person_id, for_function=None, exclude_assignment_id=None):
    """Tier 5 segregation: a person may hold at most one official function per
    case; recusal is a permanent per-case bar on any official function.
    Holding the SAME function being proposed is not itself a violation —
    per-function singleton rules govern that (the accept-time re-check is the
    strict one for investigators)."""
    cid = case["id"]
    if person_id in recused_persons(cid):
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "person was recused on this case and may hold no further official function")
    for fn in ALL_FUNCTIONS:
        if fn == for_function:
            continue
        excl = exclude_assignment_id if fn == "investigator" else None
        if person_id in function_holders(case, fn, exclude_assignment_id=excl):
            raise_error(ERR_SEGREGATION_OF_DUTIES,
                        f"person already holds the {fn} function on this case")


def active_assignment_for(case_id, investigator_id=None):
    for a in db["investigator_assignments"].values():
        if a["case_id"] == case_id and a["status"] == "ACTIVE":
            if investigator_id is None or a["investigator_id"] == investigator_id:
                return a
    return None


def require_active_investigator(case, caller):
    """Tier 7: evidence/packet work requires the actor to hold the case's
    ACTIVE investigator assignment."""
    asg = active_assignment_for(case["id"], caller.user_id)
    if asg is None:
        raise_error(ERR_NO_ACTIVE_INVESTIGATOR,
                    "actor does not hold an ACTIVE investigator assignment on this case")
    return asg


# ---------------------------------------------------------------------------
# List plumbing: pagination, filters, sorting
# ---------------------------------------------------------------------------

def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def sort_items(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def apply_filters(items, filters):
    """Exact-match equality filters; None values are skipped."""
    out = list(items)
    for field, value in filters.items():
        if value is None:
            continue
        out = [r for r in out if r.get(field) == value]
    return out
