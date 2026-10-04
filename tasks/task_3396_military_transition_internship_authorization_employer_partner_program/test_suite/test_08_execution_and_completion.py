"""Internship execution: supervision reports, the auto-start sweep, completion
gates (timing, objectives, coverage, mastery), and terminal lockdown."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiErrorId,
    assert_instant,
    assert_two_dp,
    factories,
    fixtures,
    make_employer_rep_headers,
)

DIVERGING_PLAN = [
    {"objective_code": "O1", "description": "Safety basics", "weight_hours": 10},
    {"objective_code": "O2", "description": "Forklift operation", "weight_hours": 10},
    {"objective_code": "O3", "description": "Inventory systems", "weight_hours": 20},
]
DIVERGING_MARKS = {0: {"achieved": ["O1"]}, 1: {"achieved": ["O2"]}, 2: {"excused": ["O3"]}}


def test_supervision_report_is_immutable_event(api):
    """PRD §2.5: "Three ledger-style resources — SupervisionReport, WageRecord, and
    ConversionRecord — are immutable once filed. They carry only `id` and
    `created_at`; both `updated_at` and `version` are absent on these resources."

    Design: Corner/entities/event_entities_immutable_no_version
    """
    ns = fixtures.setup_match(api, advance_to="active")  # clock at 2026-10-01
    report = get_success_data(
        api.create_supervision_report(
            factories.supervision_report_payload(ns.match["id"], "2026-10-01"),
            make_employer_rep_headers(ns.employer["id"]),
        ),
        201,
    )
    assert report["id"]
    assert_instant(report["created_at"], "2026-10-01T00:00:00Z", "report created_at")
    assert "version" not in report, "ledger resources must not carry version"
    assert "updated_at" not in report, "ledger resources must not carry updated_at"


def test_match_lifecycle_state_gates(api):
    """PRD §3.6: "The filing `EmployerRep` must own the match's employer
    (`ERR_FORBIDDEN_OWNERSHIP`) and the match must be `ACTIVE`
    (`ERR_MATCH_NOT_ACTIVE`)."
    PRD §3.6: "Wage records are accepted only while the match is `ACTIVE`; posting
    against a match in any other status is rejected with the dedicated
    `ERR_WAGE_RECORD_NOT_ALLOWED`."
    PRD §3.7: "Completion requires the match to be `ACTIVE` (`ERR_MATCH_NOT_ACTIVE`)
    and the logical clock date to have reached or passed the match's `end_date`
    (`ERR_COMPLETION_DATE_NOT_REACHED`)."

    Design: Corner/validations/match_lifecycle_state_gates
    """
    ns = fixtures.setup_match(api, advance_to="proposed")

    report = api.create_supervision_report(
        factories.supervision_report_payload(ns.match["id"], "2026-10-01"),
        make_employer_rep_headers(ns.employer["id"]),
    )
    validate_error(report, ApiErrorId.ERR_MATCH_NOT_ACTIVE)

    wage = api.create_wage_record(
        factories.wage_record_payload(ns.match["id"], "2026-10-05", "2026-10-11", 0),
        make_employer_rep_headers(ns.employer["id"]),
    )
    validate_error(wage, ApiErrorId.ERR_WAGE_RECORD_NOT_ALLOWED)

    complete = api.complete_match(ns.match["id"], fixtures.make_installation_authority_headers("auth-1"))
    validate_error(complete, ApiErrorId.ERR_MATCH_NOT_ACTIVE)


def test_complete_before_end_date_rejected(api):
    """PRD §3.7: "Completion requires the match to be `ACTIVE`
    (`ERR_MATCH_NOT_ACTIVE`) and the logical clock date to have reached or passed
    the match's `end_date` (`ERR_COMPLETION_DATE_NOT_REACHED`)."

    Clock sits on the start date 2026-10-01, before end_date 2026-10-31.

    Design: Corner/state_machines/complete_before_end_date_rejected
    """
    ns = fixtures.setup_match(api, advance_to="active")
    resp = api.complete_match(ns.match["id"], fixtures.make_installation_authority_headers("auth-1"))
    validate_error(resp, ApiErrorId.ERR_COMPLETION_DATE_NOT_REACHED)
    assert fixtures.get_match(api, ns.match["id"])["match_status"] == "ACTIVE"


def test_match_auto_start_on_clock(api):
    """PRD §3.5: "Activation is then automatic: the match auto-start sweep of §2.4
    moves an `INSTALLATION_APPROVED` match to `ACTIVE` once the logical clock date
    has reached or passed its `start_date`, provided the member is still
    `ACTIVE_DUTY`."

    Design: Corner/state_machines/match_auto_start_on_clock
    """
    ns = fixtures.setup_match(api, advance_to="installation_approved")

    early = fixtures.set_clock(api, "2026-09-30T00:00:00Z")
    assert early["matches_activated"] == 0
    assert fixtures.get_match(api, ns.match["id"])["match_status"] == "INSTALLATION_APPROVED"

    on_start = fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    assert on_start["matches_activated"] == 1
    assert fixtures.get_match(api, ns.match["id"])["match_status"] == "ACTIVE"


def test_supervision_report_content_rules(api):
    """PRD §3.6: "The `week_start_date` must lie within the match's
    `start_date`-to-`end_date` window, every objective code referenced must exist
    in the match's approved plan, and the two objective lists must be disjoint;
    violations are `ERR_VALIDATION`. One report is allowed per match per week: a
    second report for the same `week_start_date` on the same match is rejected
    with `ERR_DUPLICATE_WEEK_REPORT`."

    Design: Corner/validations/supervision_report_content_rules
    """
    ns = fixtures.setup_match(api, advance_to="active")
    match_id, employer_id = ns.match["id"], ns.employer["id"]

    unknown_code = api.create_supervision_report(
        factories.supervision_report_payload(match_id, "2026-10-05", objectives_achieved=["ZZZ"]),
        make_employer_rep_headers(employer_id),
    )
    validate_error(unknown_code, ApiErrorId.ERR_VALIDATION)

    clean = fixtures.file_report(api, match_id, employer_id, "2026-10-05")
    assert clean["id"]

    duplicate = api.create_supervision_report(
        factories.supervision_report_payload(match_id, "2026-10-05", hours_supervised=4),
        make_employer_rep_headers(employer_id),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_WEEK_REPORT)


def test_objectives_incomplete_blocks_completion(api):
    """PRD §3.7: "Three content gates then run in pinned order. First, every
    learning objective must be resolved — status `ACHIEVED` or `EXCUSED`,
    equivalently a `resolution_ratio` of exactly 1.00 — else
    `ERR_OBJECTIVES_INCOMPLETE`."

    O3 stays PENDING (resolution 2/3), so the first content gate reports even
    though mastery (20 of 40 weight-hours) would also fail the third gate.

    Design: Corner/validations/objectives_incomplete_blocks_completion
    """
    ns = fixtures.setup_ready_to_complete(
        api, objectives=DIVERGING_PLAN, marks={0: {"achieved": ["O1"]}, 1: {"achieved": ["O2"]}}
    )
    resp = api.complete_match(ns.match["id"], fixtures.make_installation_authority_headers("auth-1"))
    validate_error(resp, ApiErrorId.ERR_OBJECTIVES_INCOMPLETE)
    assert fixtures.get_match(api, ns.match["id"])["match_status"] == "ACTIVE"


def test_supervision_coverage_floor_boundary(api):
    """PRD §3.7: "Second, supervision coverage must be met: the number of
    SupervisionReports filed for the match must be at least the duration in whole
    days divided by the 7-day supervision cadence (`SUPERVISION_CADENCE_DAYS`),
    rounded down to an integer — a 34-day internship requires 4 reports, a 35-day
    internship requires 5 — and one report too few is `ERR_INSUFFICIENT_SUPERVISION`."

    Design: Corner/calculations/supervision_coverage_floor_boundary
    """
    w = fixtures.setup_members_with_approved_applications(api, 2)
    eo = fixtures.setup_employer_with_opening(api, capacity=2)
    employer_id = eo.employer["id"]

    def build(end_date):
        match = fixtures.propose_match(api, w.applications[0 if end_date == "2026-12-05" else 1]["id"],
                                       eo.opening["id"], "2026-11-01", end_date)
        fixtures.submit_plan(api, match["id"], employer_id)
        fixtures.review_plan(api, match["id"], "APPROVE")
        fixtures.installation_decision(api, match["id"], "APPROVE")
        return match

    mt34 = build("2026-12-05")
    mt35 = build("2026-12-06")
    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    for mt in (mt34, mt35):
        fixtures.file_weekly_reports(api, mt["id"], employer_id, "2026-11-01", count=4,
                                     marks={0: {"achieved": ["O1"]}})
    fixtures.set_clock(api, "2026-12-06T00:00:00Z")

    done = fixtures.complete_match(api, mt34["id"])
    assert done["match_status"] == "COMPLETED", "4 reports satisfy floor(34/7) == 4"

    short = api.complete_match(mt35["id"], fixtures.make_installation_authority_headers("auth-1"))
    validate_error(short, ApiErrorId.ERR_INSUFFICIENT_SUPERVISION)
    assert fixtures.get_match(api, mt35["id"])["match_status"] == "ACTIVE"


def test_mastery_exact_threshold_passes(api):
    """PRD §3.7: "Third, `mastery_ratio` must be at least the `MIN_MASTERY_RATIO`
    floor of 0.75, else `ERR_MASTERY_BELOW_THRESHOLD`."
    PRD §3.6: "The `mastery_ratio` is the sum of `weight_hours` over `ACHIEVED`
    objectives only, divided by the sum of `weight_hours` over all objectives — a
    weighted quality floor."

    30 of 40 weight-hours ACHIEVED lands mastery exactly on the inclusive floor.

    Design: Corner/calculations/mastery_exact_threshold_passes
    """
    plan = [
        {"objective_code": "O1", "description": "Core rotations", "weight_hours": 30},
        {"objective_code": "O2", "description": "Elective shadowing", "weight_hours": 10},
    ]
    ns = fixtures.setup_ready_to_complete(
        api, objectives=plan, marks={0: {"achieved": ["O1"]}, 1: {"excused": ["O2"]}}
    )
    done = fixtures.complete_match(api, ns.match["id"])
    assert done["match_status"] == "COMPLETED"
    assert_two_dp(done["mastery_ratio"], 0.75, "mastery_ratio")
    assert_two_dp(done["resolution_ratio"], 1.00, "resolution_ratio")
    assert_instant(done["completed_at"], "2026-10-31T00:00:00Z", "completed_at")


def test_complete_rejected_when_mastery_below_floor(api):
    """PRD §3.7: "Third, `mastery_ratio` must be at least the `MIN_MASTERY_RATIO`
    floor of 0.75, else `ERR_MASTERY_BELOW_THRESHOLD`."

    The plan is fully resolved (2 ACHIEVED + 1 EXCUSED) yet mastery is 0.50, so
    completion fails the third gate while the first two pass.

    Design: Difficulty/dual_variant_calc/training_progress_resolution_vs_mastery_diverge
    """
    ns = fixtures.setup_ready_to_complete(api, objectives=DIVERGING_PLAN, marks=DIVERGING_MARKS)
    resp = api.complete_match(ns.match["id"], fixtures.make_installation_authority_headers("auth-1"))
    validate_error(resp, ApiErrorId.ERR_MASTERY_BELOW_THRESHOLD)
    assert fixtures.get_match(api, ns.match["id"])["match_status"] == "ACTIVE", (
        "a rejected completion leaves the match untouched"
    )


def test_resolution_and_mastery_ratios_diverge(api):
    """PRD §3.6: "The `resolution_ratio` is the count of objectives whose status is
    `ACHIEVED` or `EXCUSED` divided by the total number of objectives — an
    unweighted structural-completeness measure. The `mastery_ratio` is the sum of
    `weight_hours` over `ACHIEVED` objectives only, divided by the sum of
    `weight_hours` over all objectives — a weighted quality floor."
    PRD §3.6: "The two measures legitimately diverge: an excused objective resolves
    the plan but contributes no mastery hours, so a heavily-excused plan can be
    fully resolved yet below the mastery floor."

    Design: Difficulty/dual_variant_calc/training_progress_resolution_vs_mastery_diverge
    """
    ns = fixtures.setup_ready_to_complete(api, objectives=DIVERGING_PLAN, marks=DIVERGING_MARKS)
    current = fixtures.get_match(api, ns.match["id"])
    assert_two_dp(current["resolution_ratio"], 1.00, "resolution_ratio")
    assert_two_dp(current["mastery_ratio"], 0.50, "mastery_ratio")
    assert current["match_status"] == "ACTIVE"


def test_terminate_completed_match_rejected(api):
    """PRD §3.6: "The match must be `PROPOSED`, `INSTALLATION_APPROVED`, or
    `ACTIVE`; terminating an already-terminal match — `INSTALLATION_DENIED`,
    `COMPLETED`, `TERMINATED_EARLY`, or `MATCH_VOIDED` — is rejected with
    `ERR_MATCH_NOT_TERMINABLE`."

    Design: Corner/state_machines/terminate_terminal_lockdown
    """
    ns = fixtures.setup_completed_match(api)
    resp = api.terminate_match(
        ns.match["id"], factories.terminate_payload("VOLUNTARY"),
        make_employer_rep_headers(ns.employer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MATCH_NOT_TERMINABLE)
    after = fixtures.get_match(api, ns.match["id"])
    assert after["match_status"] == "COMPLETED"
    assert_instant(after["completed_at"], "2026-10-31T00:00:00Z", "completed_at")
