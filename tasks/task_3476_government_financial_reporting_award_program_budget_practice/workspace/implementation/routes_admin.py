"""PlatformAdmin-configured resources: clock, governments, members, checklist
versions, award cycles, standards references (+activation cascade).

Check order everywhere follows PRD 2.6: auth -> shape -> role -> existence ->
ownership -> state -> SoD -> referential -> temporal -> structural -> fiscal.
"""

from decimal import Decimal

from clock import clock, parse_iso
from domain import compute_dues_cents, cycle_window_overlaps, REQUIRED_WEIGHT_SUM
from envelope import ok
from errors import api_error
from auth import authenticate, authorize
from listing import list_response
from serialize import (
    award_cycle,
    checklist_version,
    government,
    member,
    standards_reference,
)
from store import store, new_id, touch
from validate import (
    GOV_TYPES,
    POP_BANDS,
    PROGRAM_TYPES,
    get_body,
    opt_bool,
    pagination,
    query_filter,
    req_datetime,
    req_enum,
    req_int,
    req_list,
    req_str,
    to_decimal,
)


def _now():
    return clock.now_iso()


# --- POST /_clock/set_current_utc (UNPREFIXED — outside /gfoa) ----------------
def set_clock():
    uid, role = authenticate()
    body = get_body()
    raw = req_str(body, "to_iso8601")
    try:
        parse_iso(raw)
    except ValueError:
        raise api_error("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 datetime")
    authorize(role, ["PlatformAdmin"])
    clock.set(raw)
    return ok({"current_utc": clock.raw()})


# --- Governments ---------------------------------------------------------------
def create_government():
    uid, role = authenticate()
    body = get_body()
    legal_name = req_str(body, "legal_name")
    gov_type = req_enum(body, "gov_type", GOV_TYPES)
    population_band = req_enum(body, "population_band", POP_BANDS)
    state_code = req_str(body, "state_code")
    authorize(role, ["PlatformAdmin"])
    now = _now()
    g = {
        "id": new_id(),
        "legal_name": legal_name,
        "gov_type": gov_type,
        "population_band": population_band,
        "state_code": state_code,
        "lifetime_award_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.governments[g["id"]] = g
    return ok(government(g), 201)


# --- Members -------------------------------------------------------------------
def create_member():
    uid, role = authenticate()
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    government_size_band = req_enum(body, "government_size_band", POP_BANDS)
    independent = opt_bool(body, "independent_finance_officer", False)
    authorize(role, ["PlatformAdmin"])
    now = _now()
    m = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "government_size_band": government_size_band,
        "independent_finance_officer": independent,
        # computed server-side; any client-supplied value is ignored (PRD 3.2)
        "annual_dues_cents": compute_dues_cents(government_size_band, independent),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.members[m["id"]] = m
    return ok(member(m), 201)


# --- Checklist versions ---------------------------------------------------------
def _validate_criteria(body):
    criteria = req_list(body, "criteria")
    for entry in criteria:
        if not isinstance(entry, dict):
            raise api_error("ERR_VALIDATION", "each criterion must be an object")
        code = entry.get("criterion_code")
        if not isinstance(code, str) or not code:
            raise api_error("ERR_VALIDATION", "criterion_code must be a string")
        entry["_weight_decimal"] = to_decimal(entry.get("weight"), "criterion weight")
    return criteria


def create_checklist():
    uid, role = authenticate()
    body = get_body()
    program_type = req_enum(body, "program_type", PROGRAM_TYPES)
    version_label = req_str(body, "version_label")
    pass_score = to_decimal(body.get("pass_score"), "field 'pass_score'") if body.get("pass_score") is not None else None
    if pass_score is None:
        raise api_error("ERR_VALIDATION", "field 'pass_score' is required")
    criteria = _validate_criteria(body)
    authorize(role, ["PlatformAdmin"])
    # priority 8 (referential) outranks priority 10 (weight sum structural)
    for c in store.checklist_versions.values():
        if c["program_type"] == program_type and c["status"] == "ACTIVE":
            raise api_error(
                "ERR_CHECKLIST_ALREADY_ACTIVE",
                "an ACTIVE checklist already exists for program %s" % program_type,
            )
    total = sum((e["_weight_decimal"] for e in criteria), Decimal("0"))
    if total != REQUIRED_WEIGHT_SUM:
        raise api_error("ERR_WEIGHT_SUM_INVALID", "criteria weights must sum to exactly 1.000")
    for e in criteria:
        e.pop("_weight_decimal", None)
    now = _now()
    c = {
        "id": new_id(),
        "program_type": program_type,
        "version_label": version_label,
        "pass_score": pass_score,
        "criteria": [{"criterion_code": e["criterion_code"], "weight": e["weight"]} for e in criteria],
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.checklist_versions[c["id"]] = c
    return ok(checklist_version(c), 201)


def list_checklists():
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "GovernmentContact", "AwardsDirector"])
    limit, offset = pagination()
    rows = list(store.checklist_versions.values())
    program_type = query_filter("program_type")
    if program_type is not None:
        rows = [c for c in rows if c["program_type"] == program_type]
    status = query_filter("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return list_response(rows, checklist_version, limit, offset)


# --- Award cycles ----------------------------------------------------------------
def create_cycle():
    uid, role = authenticate()
    body = get_body()
    program_type = req_enum(body, "program_type", PROGRAM_TYPES)
    fiscal_year = req_int(body, "fiscal_year")
    opens = req_datetime(body, "submission_opens_at")
    deadline = req_datetime(body, "submission_deadline_at")
    review_close = req_datetime(body, "review_close_at")
    checklist_version_id = req_str(body, "checklist_version_id")
    # window ordering is a request-shape check (priority 2)
    if not (parse_iso(opens) < parse_iso(deadline) < parse_iso(review_close)):
        raise api_error(
            "ERR_VALIDATION",
            "submission_opens_at must precede submission_deadline_at, which must precede review_close_at",
        )
    authorize(role, ["PlatformAdmin"])
    checklist = store.checklist_versions.get(checklist_version_id)
    if checklist is None:
        raise api_error("ERR_CHECKLIST_NOT_FOUND", "checklist version not found")
    if checklist["status"] != "ACTIVE" or checklist["program_type"] != program_type:
        raise api_error(
            "ERR_CYCLE_CHECKLIST_MISMATCH",
            "checklist must be ACTIVE and of the same program_type as the cycle",
        )
    for c in store.award_cycles.values():
        if c["program_type"] != program_type:
            continue
        if cycle_window_overlaps(
            parse_iso(opens),
            parse_iso(deadline),
            parse_iso(c["submission_opens_at"]),
            parse_iso(c["submission_deadline_at"]),
        ):
            raise api_error(
                "ERR_CYCLE_WINDOW_OVERLAP",
                "submission window overlaps another cycle of the same program",
            )
    now = _now()
    c = {
        "id": new_id(),
        "program_type": program_type,
        "fiscal_year": fiscal_year,
        "submission_opens_at": opens,
        "submission_deadline_at": deadline,
        "review_close_at": review_close,
        "checklist_version_id": checklist_version_id,
        "submitted_count": 0,
        "decision_ready_count": 0,
        "conferred_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.award_cycles[c["id"]] = c
    return ok(award_cycle(c), 201)


def get_cycle(cycle_id):
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "GovernmentContact", "AwardsDirector"])
    c = store.award_cycles.get(cycle_id)
    if c is None:
        raise api_error("ERR_CYCLE_NOT_FOUND", "award cycle not found")
    return ok(award_cycle(c))


def list_cycles():
    uid, role = authenticate()
    authorize(role, ["PlatformAdmin", "GovernmentContact", "AwardsDirector"])
    limit, offset = pagination()
    rows = list(store.award_cycles.values())
    checklist_version_id = query_filter("checklist_version_id")
    if checklist_version_id is not None:
        rows = [c for c in rows if c["checklist_version_id"] == checklist_version_id]
    program_type = query_filter("program_type")
    if program_type is not None:
        rows = [c for c in rows if c["program_type"] == program_type]
    fiscal_year = query_filter("fiscal_year")
    if fiscal_year is not None:
        rows = [c for c in rows if str(c["fiscal_year"]) == fiscal_year]
    return list_response(rows, award_cycle, limit, offset)


# --- Standards references ---------------------------------------------------------
def create_standard():
    uid, role = authenticate()
    body = get_body()
    topic_code = req_str(body, "topic_code")
    title = req_str(body, "title")
    program_type = req_enum(body, "program_type", PROGRAM_TYPES)
    effective_date = req_datetime(body, "effective_date")
    authorize(role, ["PlatformAdmin"])
    now = _now()
    s = {
        "id": new_id(),
        "topic_code": topic_code,
        "title": title,
        "program_type": program_type,
        "effective_date": effective_date,
        "status": "ISSUED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.standards_references[s["id"]] = s
    return ok(standards_reference(s), 201)


def activate_standard(standard_id):
    uid, role = authenticate()
    get_body()
    authorize(role, ["PlatformAdmin"])
    s = store.standards_references.get(standard_id)
    if s is None:
        raise api_error("ERR_STANDARD_NOT_FOUND", "standards reference not found")
    # state gate (priority 6) outranks the temporal gate (priority 9)
    if s["status"] != "ISSUED":
        raise api_error("ERR_STANDARD_STATE_INVALID", "standard is not ISSUED")
    if clock.now() < parse_iso(s["effective_date"]):
        raise api_error("ERR_STANDARD_NOT_YET_EFFECTIVE", "standard is not yet effective")
    now = _now()
    # cascade link 1a: same-topic EFFECTIVE standards -> SUPERSEDED
    for other in store.standards_references.values():
        if other["id"] != s["id"] and other["topic_code"] == s["topic_code"] and other["status"] == "EFFECTIVE":
            other["status"] = "SUPERSEDED"
            touch(other, now)
    # cascade link 1b: the ACTIVE checklist of this program_type -> SUPERSEDED,
    # and link 2: DRAFT submissions pinned to it become stale
    for c in store.checklist_versions.values():
        if c["program_type"] == s["program_type"] and c["status"] == "ACTIVE":
            c["status"] = "SUPERSEDED"
            touch(c, now)
            for sub in store.report_submissions.values():
                if sub["pinned_checklist_version_id"] == c["id"] and sub["status"] == "DRAFT":
                    sub["pinned_checklist_stale"] = True
                    touch(sub, now)
    s["status"] = "EFFECTIVE"
    touch(s, now)
    return ok(standards_reference(s))


def register(app):
    app.add_url_rule("/_clock/set_current_utc", "set_clock", set_clock, methods=["POST"])
    app.add_url_rule("/gfoa/governments", "create_government", create_government, methods=["POST"])
    app.add_url_rule("/gfoa/members", "create_member", create_member, methods=["POST"])
    app.add_url_rule("/gfoa/checklist-versions", "create_checklist", create_checklist, methods=["POST"])
    app.add_url_rule("/gfoa/checklist-versions", "list_checklists", list_checklists, methods=["GET"])
    app.add_url_rule("/gfoa/award-cycles", "create_cycle", create_cycle, methods=["POST"])
    app.add_url_rule("/gfoa/award-cycles", "list_cycles", list_cycles, methods=["GET"])
    app.add_url_rule("/gfoa/award-cycles/<cycle_id>", "get_cycle", get_cycle, methods=["GET"])
    app.add_url_rule("/gfoa/standards-references", "create_standard", create_standard, methods=["POST"])
    app.add_url_rule(
        "/gfoa/standards-references/<standard_id>/activate",
        "activate_standard",
        activate_standard,
        methods=["POST"],
    )
