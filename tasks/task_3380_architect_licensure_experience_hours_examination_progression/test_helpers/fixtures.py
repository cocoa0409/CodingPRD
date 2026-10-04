"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD §4 endpoints
(each test starts against an empty database). Setup calls use the lenient
get_success_data validator so failures surface as clear setup errors.

Clock discipline (PRD §2.4): the logical clock starts at
2026-09-01T00:00:00Z and helpers only ever move it forward.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import AREA_MIN_HOURS, DIVISION_CODES_ASC
from .factories import (
    create_candidate_payload, create_jurisdiction_payload,
    create_supervisor_payload, create_education_evaluation_payload,
    create_experience_report_payload, create_ce_entry_payload,
    create_disciplinary_report_payload,
)
from .test_users import (
    TEST_USERS, make_board_admin_headers, make_candidate_headers,
    make_supervisor_headers,
)

NCARB = TEST_USERS["ncarb_admin_headers"]
BOARD = TEST_USERS["board_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Standard non-overlapping work periods for the six practice areas, all with
# work_period_end inside the full-credit window at the default clock
# 2026-09-01 (PRD §3.3: end + 8 months >= 2026-09-01 for every row).
SIX_AREA_PERIODS = {
    "PRACTICE_MANAGEMENT": ("2026-01-05", "2026-01-30"),
    "PROJECT_MANAGEMENT": ("2026-02-02", "2026-03-31"),
    "PROGRAMMING_ANALYSIS": ("2026-04-01", "2026-04-30"),
    "PROJECT_PLANNING_DESIGN": ("2026-05-01", "2026-06-30"),
    "PROJECT_DEVELOPMENT_DOCUMENTATION": ("2026-07-01", "2026-07-31"),
    "CONSTRUCTION_EVALUATION": ("2026-08-03", "2026-08-14"),
}

# Six division sittings on six distinct calendar days (PRD §3.4 exam-day
# conflict rule), all after the default clock date.
SIX_DIVISION_SITTINGS = {
    "CE": "2026-10-01",
    "PA": "2026-10-02",
    "PCM": "2026-10-03",
    "PDD": "2026-10-04",
    "PJM": "2026-10-05",
    "PPD": "2026-10-06",
}


def set_clock(iso8601: str) -> dict:
    """Move the logical clock (PRD §2.4). NcarbAdministrator-only."""
    return get_success_data(api_client.set_clock(iso8601, NCARB))


def run_expiry_sweep() -> dict:
    """Ops checkpoint (PRD §2.4): expires passed divisions, lapses active
    certificates; returns the counts payload."""
    return get_success_data(api_client.run_expiry_sweep(NCARB))


def create_jurisdiction(code: str = "J1", **overrides) -> dict:
    payload = create_jurisdiction_payload(code=code, **overrides)
    return get_success_data(api_client.create_jurisdiction(payload, NCARB))


def create_candidate(home_jurisdiction_code: str = "J1", **overrides) -> dict:
    payload = create_candidate_payload(
        home_jurisdiction_code=home_jurisdiction_code, **overrides
    )
    return get_success_data(api_client.create_candidate(payload, ANON))


def create_active_supervisor(jurisdiction_code: str = "J1", **overrides) -> dict:
    payload = create_supervisor_payload(jurisdiction_code=jurisdiction_code, **overrides)
    return get_success_data(api_client.create_supervisor(payload, NCARB))


def setup_registry(jurisdiction_code: str = "J1", **jurisdiction_overrides) -> dict:
    """Jurisdiction + candidate homed to it + ACTIVE supervisor."""
    jurisdiction = create_jurisdiction(code=jurisdiction_code, **jurisdiction_overrides)
    candidate = create_candidate(home_jurisdiction_code=jurisdiction_code)
    supervisor = create_active_supervisor(jurisdiction_code=jurisdiction_code)
    return {
        "jurisdiction": jurisdiction,
        "candidate": candidate,
        "supervisor": supervisor,
    }


def satisfy_education(candidate: dict, **eval_overrides) -> dict:
    """Submit an evaluation and review it SATISFIED (PRD §3.2); flips the
    candidate's education_status to SATISFIED."""
    ch = make_candidate_headers(candidate["id"])
    evaluation = get_success_data(api_client.create_education_evaluation(
        candidate["id"], create_education_evaluation_payload(**eval_overrides), ch,
    ))
    return get_success_data(api_client.review_education_evaluation(
        evaluation["id"], {"decision": "SATISFIED"}, NCARB,
    ))


def create_draft_report(candidate: dict, supervisor: dict, practice_area: str,
                        hours, work_period_start: str, work_period_end: str,
                        **overrides) -> dict:
    """Create a DRAFT experience report (PRD §3.3)."""
    ch = make_candidate_headers(candidate["id"])
    payload = create_experience_report_payload(
        candidate_id=candidate["id"], supervisor_id=supervisor["id"],
        practice_area=practice_area, hours=hours,
        work_period_start=work_period_start, work_period_end=work_period_end,
        **overrides,
    )
    return get_success_data(api_client.create_experience_report(payload, ch))


def submit_report(candidate: dict, report_id: str) -> dict:
    ch = make_candidate_headers(candidate["id"])
    return get_success_data(api_client.submit_experience_report(report_id, ch))


def verify_report(supervisor: dict, report_id: str) -> dict:
    sh = make_supervisor_headers(supervisor["id"])
    return get_success_data(api_client.verify_experience_report(report_id, sh))


def create_submitted_report(candidate: dict, supervisor: dict, practice_area: str,
                            hours, work_period_start: str, work_period_end: str,
                            **overrides) -> dict:
    report = create_draft_report(
        candidate, supervisor, practice_area, hours,
        work_period_start, work_period_end, **overrides,
    )
    return submit_report(candidate, report["id"])


def create_verified_report(candidate: dict, supervisor: dict, practice_area: str,
                           hours, work_period_start: str, work_period_end: str,
                           **overrides) -> dict:
    report = create_submitted_report(
        candidate, supervisor, practice_area, hours,
        work_period_start, work_period_end, **overrides,
    )
    return verify_report(supervisor, report["id"])


def verify_six_area_minima(candidate: dict, supervisor: dict) -> dict:
    """Create + submit + verify one report per practice area at exactly its
    area minimum (PRD §3.3); at the default clock every report locks 100%
    credit, so the completion gate closes at exactly 3740 total hours."""
    reports = {}
    for area, minimum in AREA_MIN_HOURS.items():
        start, end = SIX_AREA_PERIODS[area]
        reports[area] = create_verified_report(
            candidate, supervisor, area, minimum, start, end,
        )
    return reports


def authorize_exams(candidate: dict, jurisdiction_code: str = "J1") -> dict:
    """Board grants the examination authorization (PRD §3.4); returns the
    authorization plus the six division rows keyed by division_code."""
    authorization = get_success_data(api_client.create_exam_authorization(
        candidate["id"], {"jurisdiction_code": jurisdiction_code}, BOARD,
    ))
    ch = make_candidate_headers(candidate["id"])
    rows, _meta = validate_paginated(
        api_client.list_exam_progress(candidate["id"], ch)
    )
    divisions = {row["division_code"]: row for row in rows}
    return {"authorization": authorization, "divisions": divisions}


def schedule_division(candidate: dict, division_id: str, sitting_date: str) -> dict:
    ch = make_candidate_headers(candidate["id"])
    return get_success_data(api_client.schedule_exam_division(
        division_id, {"scheduled_date": sitting_date}, ch,
    ))


def report_score(division_id: str, result: str, scaled_score: int = 75) -> dict:
    return get_success_data(api_client.report_exam_score(
        division_id, {"result": result, "scaled_score": scaled_score}, NCARB,
    ))


def pass_division(candidate: dict, division_id: str, sitting_date: str,
                  scaled_score: int = 75) -> dict:
    """Schedule a sitting, advance the clock to its day, report PASS
    (PRD §3.4)."""
    schedule_division(candidate, division_id, sitting_date)
    set_clock(f"{sitting_date}T00:00:00Z")
    return report_score(division_id, "PASS", scaled_score)


def fail_division(candidate: dict, division_id: str, sitting_date: str,
                  scaled_score: int = 55) -> dict:
    """Schedule a sitting, advance the clock to its day, report FAIL."""
    schedule_division(candidate, division_id, sitting_date)
    set_clock(f"{sitting_date}T00:00:00Z")
    return report_score(division_id, "FAIL", scaled_score)


def pass_all_six_divisions(candidate: dict, divisions: dict) -> dict:
    """Schedule all six divisions on distinct days, advance the clock to the
    last sitting, then report PASS on every row (PRD §3.4)."""
    ch = make_candidate_headers(candidate["id"])
    for code in DIVISION_CODES_ASC:
        get_success_data(api_client.schedule_exam_division(
            divisions[code]["id"],
            {"scheduled_date": SIX_DIVISION_SITTINGS[code]}, ch,
        ))
    set_clock("2026-10-06T00:00:00Z")
    passed = {}
    for code in DIVISION_CODES_ASC:
        passed[code] = report_score(divisions[code]["id"], "PASS", 75)
    return passed


def setup_eligible_candidate(jurisdiction_code: str = "J1",
                             **jurisdiction_overrides) -> dict:
    """Full progression short of issuance: education SATISFIED, all six areas
    verified at minima (experience COMPLETE at the national floor), all six
    divisions PASSED (exam ALL_PASSED) — so certificate_eligible holds for a
    home jurisdiction that requires no supplemental exam (PRD §3.6)."""
    reg = setup_registry(jurisdiction_code=jurisdiction_code, **jurisdiction_overrides)
    candidate = reg["candidate"]
    satisfy_education(candidate)
    reports = verify_six_area_minima(candidate, reg["supervisor"])
    auth = authorize_exams(candidate, jurisdiction_code=jurisdiction_code)
    passed = pass_all_six_divisions(candidate, auth["divisions"])
    return {
        **reg,
        "reports": reports,
        "authorization": auth["authorization"],
        "divisions": auth["divisions"],
        "passed_divisions": passed,
    }


def setup_certificate_holder(jurisdiction_code: str = "J1",
                             **jurisdiction_overrides) -> dict:
    """Eligible candidate + issued ACTIVE certificate (PRD §3.6). The clock
    sits at 2026-10-06, so period_start is 2026-10-06 and period_end is
    2028-10-06 (twenty-four calendar months later)."""
    ctx = setup_eligible_candidate(
        jurisdiction_code=jurisdiction_code, **jurisdiction_overrides
    )
    certificate = get_success_data(api_client.issue_certificate(
        ctx["candidate"]["id"], NCARB,
    ))
    ctx["certificate"] = certificate
    return ctx


def log_ce_entry(candidate: dict, certificate_id: str, hours: int, hsw: bool,
                 completed_date: str, provider: str = "AIA") -> dict:
    ch = make_candidate_headers(candidate["id"])
    return get_success_data(api_client.create_ce_entry(
        certificate_id,
        create_ce_entry_payload(hours=hours, hsw=hsw,
                                completed_date=completed_date, provider=provider),
        ch,
    ))


def file_disciplinary_report(candidate: dict, jurisdiction_code: str,
                             allegation: str = "stamping unsupervised work",
                             filed_by: str = "board-admin-1") -> dict:
    return get_success_data(api_client.create_disciplinary_report(
        create_disciplinary_report_payload(
            candidate_id=candidate["id"],
            jurisdiction_code=jurisdiction_code,
            allegation=allegation,
        ),
        make_board_admin_headers(filed_by),
    ))
