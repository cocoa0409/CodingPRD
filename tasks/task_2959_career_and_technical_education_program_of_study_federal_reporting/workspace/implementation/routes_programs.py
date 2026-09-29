"""Program-of-study routes: authoring, the CLNA axis and the approval axis."""
from flask import Blueprint

import calc
import resolve
import serialize
import services
import shape
from auth import actor, endpoint
from envelope import listing, ok, created, page
from errors import ApiError
from store import (ALIGNMENT_APPROVAL_FLOOR, APPROVAL_STATUSES, CLNA_PHASES,
                   CLNA_SUCCESSOR, CLNA_VALIDITY_DAYS, CLUSTERS, COURSE_STATUSES,
                   CONCENTRATOR_STATUSES, CREDENTIAL_TIERS, EXPENDITURE_CATEGORIES,
                   EXPENDITURE_STATUSES, EDUCATOR_STATUSES, CERTIFICATION_ROUTES,
                   COMMITTEE_STATUSES, INDICATOR_STATUSES, LABOR_MARKET_DATA_MAX_AGE_DAYS,
                   ROLES, SEGMENTS, add_days, clock_date, db, dec, fmt_date,
                   parse_date, stamp_new, touch)

bp = Blueprint("programs", __name__)

DIRECTOR = ("CteDirector",)
REVIEWER = ("StateComplianceReviewer",)
DIRECTOR_REVIEWER = ("CteDirector", "StateComplianceReviewer")
DIRECTOR_REVIEWER_FISCAL = ("CteDirector", "StateComplianceReviewer",
                            "GrantFiscalOfficer")
DIRECTOR_REVIEWER_REGISTRAR = ("CteDirector", "StateComplianceReviewer",
                               "SchoolRegistrar")
NO_REGISTRAR = ("CteDirector", "StateComplianceReviewer", "GrantFiscalOfficer",
                "CommitteeChair")
CIP_PATTERN = r"\d{2}\.\d{4}"


# ------------------------------------------------------------------ reads
@bp.get("/cte/programs-of-study")
@endpoint(ROLES)
def list_programs():
    limit, offset = shape.pagination()
    approval_status = shape.filter_enum("approval_status", APPROVAL_STATUSES)
    cluster = shape.filter_enum("cluster", CLUSTERS)
    clna_phase = shape.filter_enum("clna_phase", CLNA_PHASES)
    rows = list(db.programs.values())
    if approval_status is not None:
        rows = [r for r in rows if r["approval_status"] == approval_status]
    if cluster is not None:
        rows = [r for r in rows if r["cluster"] == cluster]
    if clna_phase is not None:
        rows = [r for r in rows if r["clna_phase"] == clna_phase]
    rows.sort(key=lambda r: r["_seq"], reverse=True)
    window, total = page(rows, limit, offset)
    return listing([serialize.program(r) for r in window], limit, offset, total)


@bp.get("/cte/programs-of-study/<pos_id>")
@endpoint(ROLES)
def get_program(pos_id):
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    return ok(serialize.program(program))


@bp.get("/cte/programs-of-study/<pos_id>/sequence-courses")
@endpoint(ROLES)
def list_program_courses(pos_id):
    limit, offset = shape.pagination()
    segment = shape.filter_enum("segment", SEGMENTS)
    status = shape.filter_enum("status", COURSE_STATUSES)
    resolve.program(pos_id)
    rows = [c for c in db.courses.values() if c["pos_id"] == pos_id]
    if segment is not None:
        rows = [r for r in rows if r["segment"] == segment]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (int(r["position"]), r["_seq"]))
    window, total = page(rows, limit, offset)
    return listing([serialize.course(r) for r in window], limit, offset, total)


@bp.get("/cte/programs-of-study/<pos_id>/credentials")
@endpoint(ROLES)
def list_program_credentials(pos_id):
    limit, offset = shape.pagination()
    tier = shape.filter_enum("tier", CREDENTIAL_TIERS)
    resolve.program(pos_id)
    rows = [c for c in db.credentials.values() if c["pos_id"] == pos_id]
    if tier is not None:
        rows = [r for r in rows if r["tier"] == tier]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.credential(r) for r in window], limit, offset, total)


@bp.get("/cte/programs-of-study/<pos_id>/students")
@endpoint(DIRECTOR_REVIEWER_REGISTRAR)
def list_program_students(pos_id):
    limit, offset = shape.pagination()
    cohort_year = shape.filter_int("cohort_year")
    concentrator = shape.filter_enum("concentrator_status", CONCENTRATOR_STATUSES)
    resolve.program(pos_id)
    rows = [s for s in db.students.values() if s["pos_id"] == pos_id]
    if cohort_year is not None:
        rows = [r for r in rows if int(r["cohort_year"]) == cohort_year]
    if concentrator is not None:
        rows = [r for r in rows if r["concentrator_status"] == concentrator]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.student(r) for r in window], limit, offset, total)


@bp.get("/cte/programs-of-study/<pos_id>/advisory-committees")
@endpoint(NO_REGISTRAR)
def list_program_committees(pos_id):
    limit, offset = shape.pagination()
    status = shape.filter_enum("status", COMMITTEE_STATUSES)
    resolve.program(pos_id)
    rows = [c for c in db.committees.values() if c["pos_id"] == pos_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.committee(r) for r in window], limit, offset, total)


@bp.get("/cte/programs-of-study/<pos_id>/expenditures")
@endpoint(DIRECTOR_REVIEWER_FISCAL)
def list_program_expenditures(pos_id):
    limit, offset = shape.pagination()
    status = shape.filter_enum("status", EXPENDITURE_STATUSES)
    category = shape.filter_enum("category", EXPENDITURE_CATEGORIES)
    asset_tag = shape.filter_str("asset_tag")
    resolve.program(pos_id)
    rows = [e for e in db.expenditures.values() if e["pos_id"] == pos_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if asset_tag is not None:
        rows = [r for r in rows if r["asset_tag"] == asset_tag]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.expenditure(r) for r in window], limit, offset, total)


@bp.get("/cte/programs-of-study/<pos_id>/performance-indicators")
@endpoint(DIRECTOR_REVIEWER_FISCAL)
def list_program_indicators(pos_id):
    limit, offset = shape.pagination()
    status = shape.filter_enum("status", INDICATOR_STATUSES)
    reporting_year = shape.filter_int("reporting_year")
    resolve.program(pos_id)
    rows = [i for i in db.indicators.values() if i["pos_id"] == pos_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reporting_year is not None:
        rows = [r for r in rows if int(r["reporting_year"]) == reporting_year]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.indicator(r) for r in window], limit, offset, total)


@bp.get("/cte/programs-of-study/<pos_id>/educators")
@endpoint(DIRECTOR_REVIEWER)
def list_program_educators(pos_id):
    limit, offset = shape.pagination()
    status = shape.filter_enum("status", EDUCATOR_STATUSES)
    route = shape.filter_enum("certification_route", CERTIFICATION_ROUTES)
    resolve.program(pos_id)
    services.refresh_program_educators(pos_id)
    rows = [e for e in db.educators.values() if e["pos_id"] == pos_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if route is not None:
        rows = [r for r in rows if r["certification_route"] == route]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.educator(r) for r in window], limit, offset, total)


# ------------------------------------------------------------------ authoring
@bp.post("/cte/programs-of-study")
@endpoint(DIRECTOR)
def create_program():
    data = shape.body()
    cip_code = shape.req_string(data, "cip_code", min_len=7, max_len=7,
                                pattern=CIP_PATTERN)
    title = shape.req_string(data, "title", min_len=1, max_len=120)
    cluster = shape.req_enum(data, "cluster", CLUSTERS)
    asof = shape.req_date(data, "labor_market_data_asof")
    for existing in db.programs.values():
        if existing["cip_code"] == cip_code:
            raise ApiError("ERR_CIP_CODE_DUPLICATE",
                           "A program of study already carries cip_code '%s'."
                           % cip_code)
    program = stamp_new({
        "cip_code": cip_code,
        "title": title,
        "cluster": cluster,
        "approval_status": "DRAFT",
        "clna_phase": "NOT_STARTED",
        "approval_round": 0,
        "authored_by_user_id": actor(),
        "clna_certified_by_user_id": None,
        "labor_market_data_asof": fmt_date(asof),
        "clna_certified_on": None,
        "clna_expires_on": None,
        "alignment_index": None,
        "alignment_index_variant": None,
        "secondary_credit_total": dec(0),
        "postsecondary_credit_total": dec(0),
        "articulated_credit_total": dec(0),
        "open_finding_codes": [],
        "narrative_url": None,
    })
    db.programs[program["id"]] = program
    return created(serialize.program(program))


@bp.patch("/cte/programs-of-study/<pos_id>")
@endpoint(DIRECTOR)
def amend_program(pos_id):
    data = shape.body()
    title = shape.opt_string(data, "title", min_len=1, max_len=120)
    cluster = shape.opt_enum(data, "cluster", CLUSTERS)
    asof = shape.opt_date(data, "labor_market_data_asof")
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    if program["approval_status"] == "STATE_APPROVED":
        raise ApiError("ERR_INVALID_APPROVAL_TRANSITION",
                       "A state-approved program of study may not be amended.")
    if title is not None:
        program["title"] = title
    if cluster is not None:
        program["cluster"] = cluster
    if asof is not None:
        program["labor_market_data_asof"] = fmt_date(asof)
    touch(program)
    return ok(serialize.program(program))


# ------------------------------------------------------------------ CLNA axis
@bp.post("/cte/programs-of-study/<pos_id>/clna-advance")
@endpoint(DIRECTOR_REVIEWER)
def clna_advance(pos_id):
    data = shape.body()
    to_phase = shape.req_enum(data, "to_phase", CLNA_PHASES)
    evidence_url = shape.opt_string(data, "evidence_url")
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    current = program["clna_phase"]

    if to_phase == "CERTIFIED" and actor() == program["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The author of a program may not certify its needs assessment.")
    if CLNA_SUCCESSOR.get(current) != to_phase:
        raise ApiError("ERR_INVALID_CLNA_PHASE_TRANSITION",
                       "clna_phase %s does not declare a transition to %s."
                       % (current, to_phase))

    if current == "DATA_COLLECTION" and to_phase == "STAKEHOLDER_CONSULTATION":
        asof = parse_date(program["labor_market_data_asof"])
        if asof is None or (clock_date() - asof).days > LABOR_MARKET_DATA_MAX_AGE_DAYS:
            raise ApiError("ERR_LABOR_MARKET_DATA_STALE",
                           "The labor-market dataset behind this assessment is "
                           "more than 730 days old.")
    if current == "STAKEHOLDER_CONSULTATION" and to_phase == "GAP_ANALYSIS":
        if not services.clna_stakeholder_evidence(pos_id):
            raise ApiError("ERR_CLNA_STAKEHOLDER_EVIDENCE_MISSING",
                           "At least two quorate CLNA_STAKEHOLDER meetings with "
                           "filed minutes are required.")

    program["clna_phase"] = to_phase
    if to_phase == "CERTIFIED":
        today = clock_date()
        program["clna_certified_by_user_id"] = actor()
        program["clna_certified_on"] = fmt_date(today)
        program["clna_expires_on"] = fmt_date(add_days(today, CLNA_VALIDITY_DAYS))
    elif to_phase == "DATA_COLLECTION" and current in ("CERTIFIED", "EXPIRED"):
        program["clna_certified_by_user_id"] = None
        program["clna_certified_on"] = None
        program["clna_expires_on"] = None
    if evidence_url is not None:
        program["clna_evidence_url"] = evidence_url
    touch(program)
    return ok(serialize.program(program))


# ------------------------------------------------------------------ approval axis
def _require_live_clna(program):
    """Priority 11 then 12: never certified, then certified but lapsed."""
    if program["clna_phase"] not in ("CERTIFIED", "EXPIRED"):
        raise ApiError("ERR_CLNA_NOT_CERTIFIED",
                       "This program's needs assessment has never been certified.")
    expires = parse_date(program["clna_expires_on"])
    if program["clna_phase"] == "EXPIRED" or (
            expires is not None and clock_date() > expires):
        raise ApiError("ERR_CLNA_EXPIRED",
                       "This program's certified needs assessment has lapsed.")


@bp.post("/cte/programs-of-study/<pos_id>/submit")
@endpoint(DIRECTOR)
def submit_program(pos_id):
    data = shape.body()
    narrative_url = shape.req_string(data, "narrative_url")
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    services.refresh_program_educators(pos_id)

    if program["approval_status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_APPROVAL_TRANSITION",
                       "approval_status %s does not declare a transition to SUBMITTED."
                       % program["approval_status"])
    _require_live_clna(program)

    courses = calc.program_courses(pos_id)
    has_secondary = any(c["status"] == "ACTIVE" and c["segment"] == "SECONDARY"
                        for c in courses)
    has_postsecondary = any(c["status"] == "ACTIVE" and c["segment"] == "POSTSECONDARY"
                            for c in courses)
    if not (has_secondary and has_postsecondary):
        raise ApiError("ERR_SEQUENCE_INCOMPLETE",
                       "An ACTIVE SECONDARY course and an ACTIVE POSTSECONDARY "
                       "course are both required before submission.")
    if not any(c["pos_id"] == pos_id for c in db.credentials.values()):
        raise ApiError("ERR_CREDENTIAL_LIST_EMPTY",
                       "The approved credential list is empty.")
    if not services.eligible_instructor_exists(pos_id):
        raise ApiError("ERR_NO_ELIGIBLE_INSTRUCTOR",
                       "No educator on this program is in status ELIGIBLE.")

    program["approval_status"] = "SUBMITTED"
    program["approval_round"] = int(program["approval_round"]) + 1
    program["narrative_url"] = narrative_url
    program["open_finding_codes"] = []
    calc.apply_variant(program, "PROVISIONAL_LOCAL")
    touch(program)
    return ok(serialize.program(program))


@bp.post("/cte/programs-of-study/<pos_id>/request-changes")
@endpoint(REVIEWER)
def request_changes(pos_id):
    data = shape.body()
    finding_codes = shape.req_str_list(data, "finding_codes")
    shape.opt_string(data, "note")
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    if program["approval_status"] != "COMMITTEE_REVIEW":
        raise ApiError("ERR_INVALID_APPROVAL_TRANSITION",
                       "approval_status %s does not declare a transition to "
                       "CHANGES_REQUESTED." % program["approval_status"])
    program["approval_status"] = "CHANGES_REQUESTED"
    program["open_finding_codes"] = list(finding_codes)
    touch(program)
    return ok(serialize.program(program))


@bp.post("/cte/programs-of-study/<pos_id>/state-approve")
@endpoint(REVIEWER)
def state_approve(pos_id):
    data = shape.body()
    shape.opt_string(data, "approval_note")
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    if program["approval_status"] != "COMMITTEE_REVIEW":
        raise ApiError("ERR_INVALID_APPROVAL_TRANSITION",
                       "approval_status %s does not declare a transition to "
                       "STATE_APPROVED." % program["approval_status"])
    _require_live_clna(program)
    if not services.endorsement_on_file(pos_id):
        raise ApiError("ERR_COMMITTEE_ENDORSEMENT_MISSING",
                       "No passed POS_ENDORSEMENT meeting is on file for this "
                       "program's active advisory committee.")
    secondary, postsecondary, articulated = calc.credit_subtotals(
        pos_id, "FEDERAL_CERTIFIED")
    index = calc.alignment_index(secondary, postsecondary, articulated)
    if index < ALIGNMENT_APPROVAL_FLOOR:
        raise ApiError("ERR_ALIGNMENT_INDEX_BELOW_FLOOR",
                       "The FEDERAL_CERTIFIED alignment index %s is below the "
                       "federal floor of 0.7500." % index)
    calc.apply_variant(program, "FEDERAL_CERTIFIED")
    program["approval_status"] = "STATE_APPROVED"
    program["open_finding_codes"] = []
    touch(program)
    return ok(serialize.program(program))
