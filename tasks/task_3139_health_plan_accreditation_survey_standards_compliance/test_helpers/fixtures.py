"""Composite setup helpers for the accreditation domain.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server (empty database) before each
test. All ownership-gated calls thread the real entity id through the
per-instance header builders from test_users.py.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import (
    make_accreditation_officer_headers,
    make_plan_coordinator_headers,
    make_platform_admin_headers,
    make_public_viewer_headers,
    make_surveyor_headers,
)


def _admin():
    return make_platform_admin_headers()


def _officer():
    return make_accreditation_officer_headers()


def _coord(plan_id):
    return make_plan_coordinator_headers(plan_id)


def _surveyor(surveyor_id):
    return make_surveyor_headers(surveyor_id)


def _public():
    return make_public_viewer_headers()


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = TEST_DEFAULTS["CLOCK_DEFAULT"]):
    """Pin the logical clock (PRD §2.7)."""
    r = api_client.set_clock({"to_iso8601": to_iso8601}, _admin())
    return get_success_data(r)


# ---------------------------------------------------------------------------
# Tier 1: reference data (editions, elements, plans, scopes, surveyors)
# ---------------------------------------------------------------------------

CANONICAL_ELEMENTS = [
    {"element_code": "UM-1", "category": "UM", "max_points": 4, "is_must_pass": True, "evidence_required_count": 2},
    {"element_code": "UM-2", "category": "UM", "max_points": 2, "is_must_pass": False, "evidence_required_count": 0},
    {"element_code": "CR-1", "category": "CR", "max_points": 4, "is_must_pass": True, "evidence_required_count": 1},
    {"element_code": "MRR-1", "category": "MRR", "max_points": 2, "is_must_pass": False, "evidence_required_count": 0},
    {"element_code": "QI-1", "category": "QI", "max_points": 4, "is_must_pass": False, "evidence_required_count": 1},
]


def create_edition(*, publish: bool = False, elements=CANONICAL_ELEMENTS, **overrides):
    """Create a StandardsEdition with the given elements. Returns
    (edition_dict, {element_code: element_id})."""
    payload = {
        "edition_year": TEST_DEFAULTS["EDITION_YEAR"],
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "effective_until": TEST_DEFAULTS["EFFECTIVE_UNTIL"],
        "min_file_sample_per_category": TEST_DEFAULTS["MIN_FILE_SAMPLE_PER_CATEGORY"],
        "timeliness_threshold": TEST_DEFAULTS["TIMELINESS_THRESHOLD"],
    }
    payload.update(overrides)
    edition = get_success_data(api_client.create_standards_edition(payload, _admin()))
    ids = {}
    for el in elements:
        body = dict(el)
        created = get_success_data(api_client.create_standard_element(edition["id"], body, _admin()))
        ids[body["element_code"]] = created["id"]
    if publish:
        edition = get_success_data(api_client.publish_standards_edition(edition["id"], _admin()))
    return edition, ids


def create_plan(**overrides):
    payload = {
        "name": TEST_DEFAULTS["PLAN_NAME"],
        "plan_code": f"{TEST_DEFAULTS['PLAN_CODE']}-{overrides.pop('code_suffix', '001')}",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_health_plan(payload, _admin()))


def create_scope(plan_id, **overrides):
    payload = {"product_line": "COMMERCIAL", "state_codes": ["OR", "WA"], "member_count": 120000}
    payload.update(overrides)
    return get_success_data(api_client.create_product_line_scope(plan_id, payload, _coord(plan_id)))


def create_surveyor(**overrides):
    payload = {"name": "Dana Lead", "credential_level": "LEAD"}
    payload.update(overrides)
    return get_success_data(api_client.create_surveyor(payload, _admin()))


# ---------------------------------------------------------------------------
# Tier 2: application lifecycle progression
# ---------------------------------------------------------------------------

def create_application(plan_id, scope_id, edition_id, **overrides):
    payload = {
        "product_line_scope_id": scope_id,
        "standards_edition_id": edition_id,
        "review_period_start": TEST_DEFAULTS["REVIEW_PERIOD_START"],
        "review_period_end": TEST_DEFAULTS["REVIEW_PERIOD_END"],
    }
    payload.update(overrides)
    return get_success_data(api_client.create_application(plan_id, payload, _coord(plan_id)))


def get_app(application_id):
    return get_success_data(api_client.get_application(application_id, _officer()))


def submit_application(application_id, plan_id):
    app = get_app(application_id)
    return get_success_data(
        api_client.submit_application(
            application_id, {"expected_application_version": app["version"]}, _coord(plan_id)
        )
    )


def begin_evidence_review(application_id):
    return get_success_data(api_client.begin_evidence_review(application_id, _officer()))


def advance_to_survey_scheduling(application_id):
    return get_success_data(api_client.advance_to_survey_scheduling(application_id, _officer()))


# ---------------------------------------------------------------------------
# Tier 3: evidence
# ---------------------------------------------------------------------------

def add_evidence(application_id, plan_id, element_id, title):
    """Create an evidence item, threading the current application version (OCC)."""
    app = get_app(application_id)
    return get_success_data(
        api_client.create_evidence_item(
            application_id,
            {"standard_element_id": element_id, "title": title,
             "expected_application_version": app["version"]},
            _coord(plan_id),
        )
    )


def accept_evidence(evidence_id):
    return get_success_data(api_client.accept_evidence_item(evidence_id, {}, _officer()))


def satisfy_evidence_completeness(ctx):
    """Create and ACCEPT exactly evidence_required_count items for every element
    of the edition that requires evidence (PRD §3.3). Element requirements are
    read back from the server so custom element sets work."""
    for code, el_id in ctx["elements"].items():
        el = get_success_data(api_client.get_standard_element(el_id, _admin()))
        count = el["evidence_required_count"]
        if count <= 0:
            continue
        for i in range(count):
            ev = add_evidence(ctx["app"]["id"], ctx["plan"]["id"], el_id,
                              f"{code} evidence {i + 1}")
            accept_evidence(ev["id"])


# ---------------------------------------------------------------------------
# Tier 4: file review samples & cases
# ---------------------------------------------------------------------------

# Canonical 5-case DENIAL set, all timely on a DECISION_DATE basis with a
# 30-day turnaround (PRD §3.4).
BASE_TIMELY_CASES = [
    {"service_date": "2025-02-01T00:00:00Z", "decision_date": "2025-02-10T00:00:00Z"},
    {"service_date": "2025-03-01T00:00:00Z", "decision_date": "2025-03-05T00:00:00Z"},
    {"service_date": "2025-04-01T00:00:00Z", "decision_date": "2025-04-20T00:00:00Z"},
    {"service_date": "2025-05-01T00:00:00Z", "decision_date": "2025-05-30T00:00:00Z"},
    {"service_date": "2025-06-01T00:00:00Z", "decision_date": "2025-06-01T00:00:00Z"},
]

# Extra 5 cases used to reach a 10-case sample; the last one is 73 days late.
BASE_EXTRA_CASES = [
    {"service_date": "2025-07-01T00:00:00Z", "decision_date": "2025-07-15T00:00:00Z"},
    {"service_date": "2025-08-01T00:00:00Z", "decision_date": "2025-08-10T00:00:00Z"},
    {"service_date": "2025-09-01T00:00:00Z", "decision_date": "2025-09-20T00:00:00Z"},
    {"service_date": "2025-10-01T00:00:00Z", "decision_date": "2025-10-05T00:00:00Z"},
    {"service_date": "2025-01-01T00:00:00Z", "decision_date": "2025-03-15T00:00:00Z"},
]

LATE_CASE = {"service_date": "2025-01-05T00:00:00Z", "decision_date": "2025-04-20T00:00:00Z"}
LATE_CASE_2 = {"service_date": "2025-02-05T00:00:00Z", "decision_date": "2025-05-20T00:00:00Z"}


def create_sample(application_id, *, sample_type="DENIAL", required_size=5,
                  timeliness_basis="DECISION_DATE"):
    payload = {
        "sample_type": sample_type,
        "required_size": required_size,
        "timeliness_basis": timeliness_basis,
    }
    return get_success_data(api_client.create_file_review_sample(application_id, payload, _officer()))


def add_case(sample_id, plan_id, *, case_reference=None, service_date, decision_date,
             resolution_date=None, required_turnaround_days=30):
    payload = {
        "case_reference": case_reference or f"CASE-{service_date[:10]}",
        "service_date": service_date,
        "decision_date": decision_date,
        "resolution_date": resolution_date or decision_date,
        "required_turnaround_days": required_turnaround_days,
    }
    return get_success_data(api_client.create_file_review_case(sample_id, payload, _coord(plan_id)))


def fill_sample_with_cases(sample_id, plan_id, case_specs, prefix="C"):
    ids = []
    for i, spec in enumerate(case_specs, 1):
        c = add_case(sample_id, plan_id, case_reference=f"{prefix}{i:02d}", **spec)
        ids.append(c["id"])
    return ids


def submit_sample(sample_id, plan_id):
    return get_success_data(api_client.submit_file_review_sample(sample_id, _coord(plan_id)))


def score_sample(sample_id):
    return get_success_data(api_client.score_file_review_sample(sample_id, _officer()))


def create_scored_sample(application_id, plan_id, case_specs, *,
                         sample_type="DENIAL", required_size=None, prefix="C",
                         timeliness_basis="DECISION_DATE"):
    """Create an OPEN sample, fill it, submit, score. Returns the SCORED sample."""
    sample = create_sample(
        application_id, sample_type=sample_type,
        required_size=required_size or len(case_specs),
        timeliness_basis=timeliness_basis,
    )
    fill_sample_with_cases(sample["id"], plan_id, case_specs, prefix=prefix)
    submit_sample(sample["id"], plan_id)
    return score_sample(sample["id"])


# ---------------------------------------------------------------------------
# Tier 5: surveys, sessions, questions
# ---------------------------------------------------------------------------

def create_survey_on_app(application_id, *, survey_type="FULL", mode="VIRTUAL",
                         start_date="2026-10-05", end_date="2026-10-09",
                         budgeted_surveyor_hours=8):
    """Create a survey, threading the current application version (OCC)."""
    app = get_app(application_id)
    payload = {
        "survey_type": survey_type,
        "mode": mode,
        "start_date": start_date,
        "end_date": end_date,
        "budgeted_surveyor_hours": budgeted_surveyor_hours,
        "expected_application_version": app["version"],
    }
    return get_success_data(api_client.create_survey(application_id, payload, _officer()))


def add_session(survey_id, surveyor_id, *, session_date="2026-10-05",
                start_minute=540, end_minute=660, is_onsite=False):
    payload = {
        "surveyor_id": surveyor_id,
        "session_date": session_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "is_onsite": is_onsite,
    }
    return get_success_data(api_client.create_survey_session(survey_id, payload, _officer()))


def confirm_survey(survey_id):
    return get_success_data(api_client.confirm_survey(survey_id, _officer()))


def complete_session(session_id, surveyor_id):
    return get_success_data(api_client.complete_survey_session(session_id, _surveyor(surveyor_id)))


def cancel_survey(survey_id):
    return get_success_data(api_client.cancel_survey(survey_id, _officer()))


def cancel_session(session_id):
    return get_success_data(api_client.cancel_survey_session(session_id, _officer()))


def complete_survey(survey_id):
    return get_success_data(api_client.complete_survey(survey_id, _officer()))


def log_question(session_id, surveyor_id, element_id, question_text, raises_gap=True):
    payload = {
        "standard_element_id": element_id,
        "question_text": question_text,
        "raises_gap": raises_gap,
    }
    return get_success_data(
        api_client.create_surveyor_question(session_id, payload, _surveyor(surveyor_id))
    )


def adjudicate_question(question_id, gap_confirmed):
    return get_success_data(
        api_client.adjudicate_surveyor_question(question_id, {"gap_confirmed": gap_confirmed}, _officer())
    )


# ---------------------------------------------------------------------------
# Tier 6: element scores and outcomes
# ---------------------------------------------------------------------------

def create_score(application_id, element_id):
    return get_success_data(
        api_client.create_element_score(application_id, {"standard_element_id": element_id}, _officer())
    )


def finalize_score(score_id):
    return get_success_data(api_client.finalize_element_score(score_id, _officer()))


def void_score(score_id):
    return get_success_data(api_client.void_element_score(score_id, _officer()))


def decide_outcome(application_id):
    return get_success_data(api_client.create_outcome(application_id, _officer()))


def revise_outcome(outcome_id):
    return get_success_data(api_client.revise_outcome(outcome_id, _officer()))


def publish_outcome(outcome_id):
    return get_success_data(api_client.publish_outcome(outcome_id, _officer()))


def list_caps(application_id):
    data, _meta = validate_paginated(
        api_client.list_corrective_action_plans_of_application(application_id, _officer())
    )
    return data


def cap_for_element(application_id, element_id):
    for cap in list_caps(application_id):
        if cap["standard_element_id"] == element_id:
            return cap
    raise AssertionError(f"No corrective action plan found for element {element_id}")


def submit_cap_evidence(cap_id, plan_id, evidence_summary="Remediation evidence package"):
    return get_success_data(
        api_client.submit_cap_evidence(cap_id, {"evidence_summary": evidence_summary}, _coord(plan_id))
    )


def verify_cap(cap_id, approved: bool):
    return get_success_data(
        api_client.verify_corrective_action_plan(cap_id, {"approved": approved}, _officer())
    )


# ---------------------------------------------------------------------------
# Tier 7: measures
# ---------------------------------------------------------------------------

def add_measure(scope_id, plan_id, *, measure_code, measurement_year=2025,
                percentile=100, is_reportable=True):
    payload = {
        "measure_code": measure_code,
        "measurement_year": measurement_year,
        "percentile": percentile,
        "is_reportable": is_reportable,
    }
    return get_success_data(
        api_client.create_quality_measure_result(scope_id, payload, _coord(plan_id))
    )


def add_consumer_score(scope_id, plan_id, *, survey_year=2025, composite_score=100.00,
                       response_count=900):
    payload = {
        "survey_year": survey_year,
        "composite_score": composite_score,
        "response_count": response_count,
    }
    return get_success_data(
        api_client.create_consumer_survey_score(scope_id, payload, _coord(plan_id))
    )


# ---------------------------------------------------------------------------
# Composite fixtures (shared preambles)
# ---------------------------------------------------------------------------

def setup_base(elements=CANONICAL_ELEMENTS):
    """Canonical base chain: clock pinned -> edition + elements -> publish ->
    plan -> scope -> DRAFT application. Returns a context dict."""
    set_clock()
    edition, el_ids = create_edition(publish=True, elements=elements)
    plan = create_plan()
    scope = create_scope(plan["id"])
    app = create_application(plan["id"], scope["id"], edition["id"])
    return {
        "edition": edition,
        "elements": el_ids,
        "plan": plan,
        "scope": scope,
        "app": app,
    }


def setup_evidence_review(elements=CANONICAL_ELEMENTS):
    """Base chain driven to EVIDENCE_REVIEW."""
    ctx = setup_base(elements=elements)
    ctx["app"] = submit_application(ctx["app"]["id"], ctx["plan"]["id"])
    ctx["app"] = begin_evidence_review(ctx["app"]["id"])
    return ctx


def setup_survey_scheduling(elements=CANONICAL_ELEMENTS, with_evidence=True):
    """Base chain driven to SURVEY_SCHEDULING (evidence completeness satisfied)."""
    ctx = setup_evidence_review(elements=elements)
    if with_evidence:
        satisfy_evidence_completeness(ctx)
    ctx["app"] = advance_to_survey_scheduling(ctx["app"]["id"])
    return ctx


def setup_planned_full_survey(elements=CANONICAL_ELEMENTS, surveyor=None):
    """SURVEY_SCHEDULING + a PLANNED FULL survey + a surveyor. Returns ctx with
    'survey' and 'surveyor'."""
    ctx = setup_survey_scheduling(elements=elements)
    ctx["survey"] = create_survey_on_app(ctx["app"]["id"], survey_type="FULL")
    ctx["surveyor"] = surveyor or create_surveyor()
    return ctx


def setup_confirmed_full_survey(elements=CANONICAL_ELEMENTS, surveyor=None,
                                session_kwargs=None):
    """CONFIRMED FULL survey with one SCHEDULED session; application is
    SURVEY_IN_PROGRESS."""
    ctx = setup_planned_full_survey(elements=elements, surveyor=surveyor)
    kwargs = {"session_date": "2026-10-05", "start_minute": 540, "end_minute": 660,
              "is_onsite": False}
    if session_kwargs:
        kwargs.update(session_kwargs)
    ctx["session"] = add_session(ctx["survey"]["id"], ctx["surveyor"]["id"], **kwargs)
    ctx["survey"] = confirm_survey(ctx["survey"]["id"])
    ctx["app"] = get_app(ctx["app"]["id"])
    return ctx


def setup_scoring(elements=CANONICAL_ELEMENTS, surveyor=None,
                  gap_elements=None):
    """Full survey completed; application is SCORING. Optionally log + confirm
    `gap_elements` (list of element_codes) during the confirmed survey."""
    ctx = setup_confirmed_full_survey(elements=elements, surveyor=surveyor)
    if gap_elements:
        for code in gap_elements:
            q = log_question(ctx["session"]["id"], ctx["surveyor"]["id"],
                             ctx["elements"][code], f"{code} gap probe")
            adjudicate_question(q["id"], True)
    complete_session(ctx["session"]["id"], ctx["surveyor"]["id"])
    ctx["survey"] = complete_survey(ctx["survey"]["id"])
    ctx["app"] = get_app(ctx["app"]["id"])
    return ctx


def finalize_all_scores(ctx, exclude=()):
    """Create + finalize a score for every edition element. Returns
    {element_code: score_dict}."""
    scores = {}
    for code, el_id in ctx["elements"].items():
        if code in exclude:
            continue
        s = create_score(ctx["app"]["id"], el_id)
        scores[code] = finalize_score(s["id"])
    return scores


def setup_closed_application(surveyor=None):
    """Clean full lifecycle: all elements fully awarded (no CAPs) -> decide ->
    application CLOSED. Returns ctx with 'scores' and 'outcome'."""
    ctx = setup_scoring(surveyor=surveyor)
    ctx["scores"] = finalize_all_scores(ctx)
    ctx["outcome"] = decide_outcome(ctx["app"]["id"])
    ctx["app"] = get_app(ctx["app"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Specialized composites used by the deep scenarios
# ---------------------------------------------------------------------------

def setup_decided_with_um1_gap_failure():
    """Base chain decided with UM-1 at 1.60 (6 confirmed gap questions during
    the survey), every other element fully awarded. No measure/consumer data.
    Outcome: composite 92.00, 1 must-pass failure -> ACCREDITED_WITH_CAP; one
    AUTO corrective action plan for UM-1; application CORRECTIVE_ACTION."""
    ctx = setup_survey_scheduling()
    ctx["sample"] = create_scored_sample(
        ctx["app"]["id"], ctx["plan"]["id"], BASE_TIMELY_CASES, prefix="DN"
    )
    ctx["survey"] = create_survey_on_app(ctx["app"]["id"], survey_type="FULL")
    ctx["surveyor"] = create_surveyor()
    ctx["session"] = add_session(ctx["survey"]["id"], ctx["surveyor"]["id"])
    ctx["survey"] = confirm_survey(ctx["survey"]["id"])
    ctx["gap_questions"] = []
    for i in range(6):
        q = log_question(ctx["session"]["id"], ctx["surveyor"]["id"],
                         ctx["elements"]["UM-1"], f"UM turnaround controls q{i + 1}")
        adjudicate_question(q["id"], True)
        ctx["gap_questions"].append(q)
    complete_session(ctx["session"]["id"], ctx["surveyor"]["id"])
    ctx["survey"] = complete_survey(ctx["survey"]["id"])
    ctx["app"] = get_app(ctx["app"]["id"])
    ctx["scores"] = finalize_all_scores(ctx)
    ctx["outcome"] = decide_outcome(ctx["app"]["id"])
    ctx["app"] = get_app(ctx["app"]["id"])
    return ctx


def setup_resurvey_survey(ctx, *, start_date="2026-11-02", end_date="2026-11-06",
                          session_date="2026-11-02"):
    """From CORRECTIVE_ACTION: create + session + confirm a RESURVEY survey.
    Returns the CONFIRMED survey (with frozen_cap_closure_rate set)."""
    resurvey = create_survey_on_app(
        ctx["app"]["id"], survey_type="RESURVEY", start_date=start_date,
        end_date=end_date, budgeted_surveyor_hours=4,
    )
    ctx["resurvey"] = resurvey
    ctx["resession"] = add_session(resurvey["id"], ctx["surveyor"]["id"],
                                   session_date=session_date)
    ctx["resurvey"] = confirm_survey(resurvey["id"])
    ctx["app"] = get_app(ctx["app"]["id"])
    return ctx["resurvey"]


def finish_resurvey(ctx):
    """Complete the resurvey session + survey. Application returns to SCORING."""
    complete_session(ctx["resession"]["id"], ctx["surveyor"]["id"])
    ctx["resurvey"] = complete_survey(ctx["resurvey"]["id"])
    ctx["app"] = get_app(ctx["app"]["id"])
    return ctx["resurvey"]
