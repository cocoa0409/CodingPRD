"""The ordered rejection chain of PRD 2.11.

Band 1 (auth) -> band 2 (request shape) -> band 3 (existence) -> bands 4..9,
which the route handlers contribute as numbered checks run in ascending
priority order by :func:`run_checks`.
"""

import re

from flask import g, request

from errors import ApiError
from store import (
    d, db, now_date, parse_date, parse_instant,
)

ROLE_NAMES = (
    "SystemAdmin", "IntakeClerk", "CountyOfficer", "StateAuditor", "VeteranClient",
)

# --------------------------------------------------------------------------
# field vocabularies
# --------------------------------------------------------------------------

ENUMS = {
    "accreditation_type": ("COUNTY_CVSO", "VSO_ORG", "ATTORNEY", "CLAIMS_AGENT"),
    "document_type": ("DD214", "NGB22", "DD215", "STATEMENT_OF_SERVICE"),
    "source": ("VETERAN_PROVIDED", "NPRC_RESPONSE", "STATE_ARCHIVE"),
    "claimed_character_of_service": (
        "HONORABLE", "GENERAL", "OTHER_THAN_HONORABLE", "BAD_CONDUCT",
        "DISHONORABLE", "UNCHARACTERIZED",
    ),
    "homeless_status": ("NOT_HOMELESS", "AT_RISK", "SHELTERED", "UNSHELTERED"),
    "referral_source": (
        "WALK_IN", "OUTREACH_EVENT", "JAIL_INREACH", "SHELTER_REFERRAL",
        "STATE_HOTLINE",
    ),
    "form_type": ("VA_21_22", "VA_21_22A"),
    "scope": ("ALL_BENEFITS", "SPECIFIC_CLAIM"),
    "claim_type": (
        "DISABILITY_COMPENSATION", "PENSION", "DEPENDENCY_INDEMNITY",
        "SURVIVOR_PENSION",
    ),
    "evidence_type": (
        "SERVICE_TREATMENT_RECORD", "PRIVATE_MEDICAL", "VA_MEDICAL",
        "LAY_STATEMENT", "NEXUS_LETTER", "DBQ",
    ),
    "nexus_opinion_strength": (
        "NONE", "POSSIBLE", "AT_LEAST_AS_LIKELY_AS_NOT", "HIGHLY_PROBABLE",
    ),
    "review_lane": (
        "HIGHER_LEVEL_REVIEW", "SUPPLEMENTAL_CLAIM", "BOARD_APPEAL_DIRECT",
        "BOARD_APPEAL_EVIDENCE", "BOARD_APPEAL_HEARING",
    ),
    "program_type": ("PROPERTY_TAX_EXEMPTION", "TUITION_WAIVER", "BURIAL_BENEFIT"),
    "event_type": (
        "HOMELESS_STANDDOWN", "RURAL_CLINIC", "TRIBAL_OUTREACH", "JAIL_INREACH",
    ),
    "decision_outcome": ("GRANTED", "PARTIAL_GRANT", "DENIED"),
    "weighting_basis": ("CLAIM_WEIGHTED", "VETERAN_WEIGHTED"),
}

DATE_FIELDS = (
    "accreditation_expires_on", "date_of_birth", "service_start_date",
    "service_end_date", "claimed_service_start", "claimed_service_end",
    "executed_on", "intent_to_file_date", "filed_on", "decided_on",
    "date_of_death", "completed_on", "elected_on", "issued_on",
)

INSTANT_FIELDS = ("current_utc", "starts_at", "ends_at")

# (minimum, maximum, multiple-of) -- None where unconstrained. PRD 2.11 (14).
INT_RULES = {
    "household_income_cents": (0, None, None),
    "net_worth_cents": (0, None, None),
    "annual_pool_cents": (0, None, None),
    "max_award_cents": (0, None, None),
    "assessed_property_value_cents": (0, None, None),
    "dependent_count": (0, 12, None),
    "tuition_credits_requested": (0, 30, None),
    "concurrent_capacity": (1, None, None),
    "buffer_minutes": (0, 120, None),
    "fiscal_year": (2020, 2100, None),
    "min_rating_pct": (0, 100, 10),
    "awarded_rating_pct": (0, 100, 10),
    "ce_credits": (0, None, None),
    "veterans_contacted": (0, None, None),
    "veterans_enrolled": (0, None, None),
}

STRING_RULES = {
    "full_name": (1, 120),
    "accreditation_number": (1, 40),
    "county_code": (2, 5),
    "name": (1, 120),
    "location_name": (1, 160),
    "program_code": (1, 40),
    "program_name": (1, 160),
    "provider_name": (1, 160),
}

BOOL_FIELDS = ("requires_wartime", "underserved_flag")

# Every field whose value the server computes or assigns (PRD 1.1 sources
# `system` and `computed`) plus the four identity/audit fields.  A body key in
# this set that the addressed endpoint does not itself declare as an input is
# ERR_READONLY_FIELD (PRD 2.5 / 2.11 rule 21).
SERVER_OWNED = frozenset([
    "id", "created_at", "updated_at", "version",
    "accreditation_status", "ce_credits_earned", "revocation_reason",
    "active_poa_count", "caseload_weight",
    "county_case_number", "character_of_service", "discharge_doc_status",
    "intake_status", "wartime_service_days", "combined_rating_pct",
    "priority_group", "assigned_representative_id", "date_of_death",
    "verification_status", "discrepancy_reason", "resubmission_count",
    "verified_at", "verified_by_representative_id",
    "screen_sequence", "basic_eligibility", "income_limit_applied_cents",
    "wartime_service_days_at_screen", "priority_group_assigned",
    "category_results", "eligible_category_count",
    "status", "accepted_at", "revoked_reason",
    "prepared_by_representative_id", "peer_reviewed_by_representative_id",
    "evidence_completeness_pct", "rework_count", "reopen_count", "filed_on",
    "effective_date", "effective_date_basis", "decided_on", "decision_outcome",
    "awarded_rating_pct", "retro_award_cents", "withdrawal_reason",
    "requested_on", "received_on", "weight_points", "status_reason",
    "auto_generated",
    "booked_slot_count",
    "prep_session_completed", "completed_on", "cancellation_reason",
    "counseled_by_representative_id", "decision_notice_date", "deadline_on",
    "days_remaining", "elected_on", "closure_reason",
    "allocated_cents",
    "determination_status", "disbursement_status", "gross_award_cents",
    "admin_fee_cents", "benefit_amount_cents", "rating_at_approval_pct",
    "determination_reason", "issued_on",
    "veterans_contacted", "veterans_enrolled",
    "weighting_basis", "filed_claim_count", "favorable_claim_count",
    "performance_score", "retro_dollars_cents", "veterans_contacted_total",
    "certified_by_representative_id", "submitted_at", "return_reason",
])

FISCAL_QUARTER_RE = re.compile(r"^[0-9]{4}Q[1-4]$")
INT_TOKEN_RE = re.compile(r"^[+-]?[0-9]+$")


# --------------------------------------------------------------------------
# band 1 -- authentication and authorization
# --------------------------------------------------------------------------

def authorize(roles, owner_resolver=None):
    """Rules 1..5.  `owner_resolver()` returns the owning veteran id, or None
    when the addressed row does not exist (band 3 reports that later)."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or role.strip() == "" or uid is None or uid.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS",
                       "X-User-ID and X-User-Role are required")
    if role not in ROLE_NAMES:
        raise ApiError("ERR_INVALID_ROLE", "unknown role %r" % (role,))
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "role %s may not call this endpoint" % (role,))
    g.role = role
    g.user_id = uid
    g.actor_rep = None
    g.actor_vet = None
    if role == "CountyOfficer":
        rep = db.representatives.get(uid)
        if rep is None:
            raise ApiError("ERR_UNKNOWN_ACTOR",
                           "X-User-ID is not a representative id")
        g.actor_rep = rep
    elif role == "VeteranClient":
        vet = db.veterans.get(uid)
        if vet is None:
            raise ApiError("ERR_UNKNOWN_ACTOR", "X-User-ID is not a veteran id")
        g.actor_vet = vet
    if role == "VeteranClient" and owner_resolver is not None:
        owner = owner_resolver()
        if owner is not None and owner != uid:
            raise ApiError("ERR_ACTOR_NOT_OWNER",
                           "this row does not belong to the acting veteran")
    return role, uid


# --------------------------------------------------------------------------
# band 2 -- request shape
# --------------------------------------------------------------------------

def body_json():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        value = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", "request body is not valid JSON")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check_shape(spec):
    """Run rules 10..22 in the order PRD 2.11 lists them.

    Recognised spec keys: required, optional, actions, action_required,
    action_enums, claimed_conditions, interval, service_dates,
    fiscal_quarter, enrolled, occ, extra.
    """
    body = body_json()
    g.body = body
    required = list(spec.get("required", ()))
    optional = list(spec.get("optional", ()))
    declared = set(required) | set(optional)
    if spec.get("actions"):
        declared.add("action")

    # (10) declared-without-default fields present and non-null
    for field in required:
        if field not in body or body[field] is None:
            raise ApiError("ERR_VALIDATION", "%s is required" % (field,))

    # (11) enum-typed fields carry a declared value
    for field in declared:
        if field == "action":
            continue
        if field in ENUMS and field in body and body[field] is not None:
            if body[field] not in ENUMS[field]:
                raise ApiError("ERR_VALIDATION",
                               "%s has an undeclared value" % (field,))

    # (12) the action field carries a declared value
    action = None
    if spec.get("actions"):
        action = body.get("action")
        if action not in spec["actions"]:
            raise ApiError("ERR_UNKNOWN_ACTION",
                           "unknown action %r" % (action,))
        g.action = action
        for role_gate in spec.get("action_roles", ()) or ():
            allowed_action, allowed_roles = role_gate
            if action == allowed_action and g.role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED",
                               "role %s may not perform %s"
                               % (g.role, action))
        for field in spec.get("action_required", {}).get(action, ()):
            if field not in body or body[field] is None:
                raise ApiError("ERR_VALIDATION",
                               "%s is required for %s" % (field, action))

    # (13) date and datetime shapes
    for field in declared:
        if field in body and body[field] is not None:
            if field in DATE_FIELDS:
                parse_date(body[field])
            elif field in INSTANT_FIELDS:
                parse_instant(body[field])

    # (14) integer ranges, plus declared string and boolean shapes
    for field in declared:
        if field not in body or body[field] is None:
            continue
        value = body[field]
        if field in INT_RULES:
            low, high, mult = INT_RULES[field]
            if not _is_int(value):
                raise ApiError("ERR_VALIDATION",
                               "%s must be an integer" % (field,))
            if low is not None and value < low:
                raise ApiError("ERR_VALIDATION", "%s is below %d" % (field, low))
            if high is not None and value > high:
                raise ApiError("ERR_VALIDATION", "%s is above %d" % (field, high))
            if mult is not None and value % mult != 0:
                raise ApiError("ERR_VALIDATION",
                               "%s must be a multiple of %d" % (field, mult))
        elif field in BOOL_FIELDS:
            if not isinstance(value, bool):
                raise ApiError("ERR_VALIDATION",
                               "%s must be a boolean" % (field,))
        elif field in STRING_RULES:
            low, high = STRING_RULES[field]
            if not isinstance(value, str) or len(value.strip()) < low \
                    or len(value) > high:
                raise ApiError("ERR_VALIDATION",
                               "%s has an unacceptable length" % (field,))
        elif field in ENUMS or field in DATE_FIELDS or field in INSTANT_FIELDS:
            pass
        elif field.endswith("_id") or field in (
                "reason", "rework_note", "fiscal_quarter"):
            if not isinstance(value, str) or value.strip() == "":
                raise ApiError("ERR_VALIDATION",
                               "%s must be a non-blank string" % (field,))
        elif field in ("expected_veteran_version", "expected_program_version"):
            pass

    # (16) claimed_conditions
    if spec.get("claimed_conditions") and "claimed_conditions" in body \
            and body["claimed_conditions"] is not None:
        _check_claimed_conditions(body["claimed_conditions"])

    # (17) ends_at strictly after starts_at
    if spec.get("interval"):
        starts = parse_instant(body["starts_at"])
        ends = parse_instant(body["ends_at"])
        if not ends > starts:
            raise ApiError("ERR_INVALID_INTERVAL",
                           "ends_at must be strictly after starts_at")

    # (18) service spans
    pair = spec.get("service_dates")
    if pair:
        start_field, end_field = pair
        if body.get(start_field) is not None and body.get(end_field) is not None:
            if parse_date(body[end_field]) < parse_date(body[start_field]):
                raise ApiError("ERR_INVALID_SERVICE_DATES",
                               "%s is earlier than %s" % (end_field, start_field))

    # (19) fiscal quarter label
    if spec.get("fiscal_quarter"):
        label = body.get("fiscal_quarter")
        if not isinstance(label, str) or not FISCAL_QUARTER_RE.match(label):
            raise ApiError("ERR_INVALID_FISCAL_QUARTER",
                           "fiscal_quarter must look like 2026Q1")

    # (20) veterans_enrolled <= veterans_contacted
    if spec.get("enrolled") and action == "HOLD":
        if body.get("veterans_enrolled") > body.get("veterans_contacted"):
            raise ApiError("ERR_ENROLLED_EXCEEDS_CONTACTED",
                           "veterans_enrolled exceeds veterans_contacted")

    # (21) no server-owned field in a write body
    for key in body.keys():
        if key in SERVER_OWNED and key not in declared:
            raise ApiError("ERR_READONLY_FIELD",
                           "%s is owned by the server" % (key,))

    # (22) the optimistic-concurrency field
    occ = spec.get("occ")
    if occ:
        value = body.get(occ)
        if value is None or not _is_int(value) or value < 1:
            raise ApiError("ERR_VALIDATION",
                           "%s must be an integer of at least 1" % (occ,))

    extra = spec.get("extra")
    if extra is not None:
        extra(body)
    return body


def _check_claimed_conditions(value):
    if not isinstance(value, list) or len(value) < 1 or len(value) > 8:
        raise ApiError("ERR_VALIDATION",
                       "claimed_conditions must hold 1 to 8 entries")
    for entry in value:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION",
                           "each claimed condition must be an object")
        code = entry.get("condition_code")
        pct = entry.get("claimed_rating_pct")
        if not isinstance(code, str) or code.strip() == "":
            raise ApiError("ERR_VALIDATION",
                           "condition_code must be a non-blank string")
        if not _is_int(pct) or pct < 0 or pct > 100 or pct % 10 != 0:
            raise ApiError("ERR_VALIDATION",
                           "claimed_rating_pct must be a multiple of 10 in 0..100")


def require_date_not_after_clock(body, field):
    """A body date bounded above by the logical-clock date (PRD 3.x)."""
    if body.get(field) is None:
        return None
    value = parse_date(body[field])
    if value > now_date():
        raise ApiError("ERR_VALIDATION",
                       "%s may not be later than the logical-clock date" % (field,))
    return value


# --------------------------------------------------------------------------
# band 2 rule 15 -- pagination
# --------------------------------------------------------------------------

def read_pagination():
    limit = 10
    offset = 0
    raw = request.args.get("limit")
    if raw is not None:
        if not INT_TOKEN_RE.match(raw.strip()):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "limit must be from 1 through 100")
    raw = request.args.get("offset")
    if raw is not None:
        if not INT_TOKEN_RE.match(raw.strip()):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer")
        offset = int(raw.strip())
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "offset must be at least 0")
    return limit, offset


def page_of(rows):
    """Apply rule 15 and window `rows` (already ordered and filtered)."""
    limit, offset = read_pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }


def filter_rows(rows, filters):
    """`filters` maps a query-parameter name to the row key it narrows."""
    out = rows
    for param, key in filters.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        if param in ("underserved_flag", "prep_session_completed",
                     "auto_generated"):
            token = raw.strip().lower()
            if token in ("true", "1"):
                wanted = True
            elif token in ("false", "0"):
                wanted = False
            else:
                return []
            out = [r for r in out if r.get(key) is wanted]
        elif param == "fiscal_year":
            if not INT_TOKEN_RE.match(raw.strip()):
                return []
            wanted = int(raw.strip())
            out = [r for r in out if r.get(key) == wanted]
        else:
            out = [r for r in out if r.get(key) == raw]
    return out


# --------------------------------------------------------------------------
# band 3 -- existence
# --------------------------------------------------------------------------

def lookup(table, row_id, error_id):
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id, "%s is not a known id" % (row_id,))
    return row


def need_representative(row_id):
    return lookup(db.representatives, row_id, "ERR_REPRESENTATIVE_NOT_FOUND")


def need_veteran(row_id):
    return lookup(db.veterans, row_id, "ERR_VETERAN_NOT_FOUND")


def need_document(row_id):
    return lookup(db.discharge_documents, row_id,
                  "ERR_DISCHARGE_DOCUMENT_NOT_FOUND")


def need_poa(row_id):
    return lookup(db.powers_of_attorney, row_id, "ERR_POA_NOT_FOUND")


def need_claim(row_id):
    return lookup(db.claims, row_id, "ERR_CLAIM_NOT_FOUND")


def need_evidence(row_id):
    return lookup(db.evidence_items, row_id, "ERR_EVIDENCE_ITEM_NOT_FOUND")


def need_site(row_id):
    return lookup(db.exam_sites, row_id, "ERR_EXAM_SITE_NOT_FOUND")


def need_appointment(row_id):
    return lookup(db.exam_appointments, row_id, "ERR_EXAM_APPOINTMENT_NOT_FOUND")


def need_review(row_id):
    return lookup(db.decision_reviews, row_id, "ERR_DECISION_REVIEW_NOT_FOUND")


def need_program(row_id):
    return lookup(db.state_programs, row_id, "ERR_STATE_PROGRAM_NOT_FOUND")


def need_application(row_id):
    return lookup(db.state_benefit_applications, row_id,
                  "ERR_BENEFIT_APPLICATION_NOT_FOUND")


def need_event(row_id):
    return lookup(db.outreach_events, row_id, "ERR_OUTREACH_EVENT_NOT_FOUND")


def need_report(row_id):
    return lookup(db.outcome_reports, row_id, "ERR_OUTCOME_REPORT_NOT_FOUND")


# --------------------------------------------------------------------------
# bands 4..9 -- numbered state / safety / temporal / fiscal checks
# --------------------------------------------------------------------------

def _accreditation_active():
    rep = g.actor_rep
    if rep is not None and rep.get("accreditation_status") != "ACTIVE":
        raise ApiError("ERR_REPRESENTATIVE_NOT_ACCREDITED",
                       "the acting representative is not ACTIVE")


def _accreditation_unexpired():
    rep = g.actor_rep
    if rep is not None and rep.get("accreditation_expires_on") is not None:
        if d(rep["accreditation_expires_on"]) < now_date():
            raise ApiError("ERR_ACCREDITATION_EXPIRED",
                           "the acting accreditation has expired")


def run_checks(checks=()):
    """Run numbered checks in ascending priority order.

    The two 2.6 accreditation gates (42 and 54) are injected automatically
    whenever the caller is acting as a CountyOfficer.
    """
    items = list(checks)
    if request.method == "GET":
        # rule 15 is band 2, so it must beat the band 4/5 accreditation gates.
        items.append((15, lambda: read_pagination()))
    if getattr(g, "role", None) == "CountyOfficer":
        items.append((42, _accreditation_active))
        items.append((54, _accreditation_unexpired))
    items.sort(key=lambda item: item[0])
    for _, fn in items:
        fn()


def invalid_transition(message="the requested action is not available from this state"):
    raise ApiError("ERR_INVALID_STATE_TRANSITION", message)
