"""Council review outcomes, payline publication (budget walk, ESI bonus,
OCC), and select-pay discretion (state gate, band on the raw percentile,
payline precondition)."""
import pytest

from test_helpers import (
    api_client,
    fixtures,
    factories,
    TEST_USERS,
    make_applicant_headers,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
)

_PO = TEST_USERS["program_officer_headers"]
_CM = TEST_USERS["council_member_headers"]
_GO = TEST_USERS["grants_officer_headers"]


def test_payline_budget_walk_stops_at_committable_boundary():
    """PRD §3.7: "The walk then proceeds in order, funding a candidate while the running total of projected costs plus the candidate's own projected cost stays within committable authority, and it stops at the first candidate that would exceed that authority — later, cheaper candidates are never skipped ahead, and the published percentile is never re-derived from the walk's outcome."
    PRD §3.7: "The institute's `current_payline_percentile` records exactly the requested `base_payline_percentile`, superseding any previously published payline, and the institute's `version` increments by one."
    Setup derivation: each candidate projects 20,000,000 + rhup(20,000,000 x
    0.55) = 31,000,000 cents; committable = 98,000,000 - 0 - 0 - 5,000,000 =
    93,000,000, so the third candidate lands exactly on the boundary (funded
    by <=) and the walk stops at the fourth.

    Design: Difficulty/combinatorial_formula/payline_budget_walk_stops_at_committable_boundary
    """
    ctx = fixtures.make_review_context(
        appropriation_cents=98_000_000, reserve_cents=5_000_000, indirect_cost_rate=0.55)
    section = fixtures.make_study_section(name="Section W")
    entries = [fixtures.add_reviewed_application(ctx, section, convene=False, title=f"W{i}")
               for i in range(1, 5)]
    fixtures.score_section(section, entries, [
        [{"overall_impact_score": 2}, {"overall_impact_score": 2}],   # impact 20
        [{"overall_impact_score": 3}, {"overall_impact_score": 3}],   # impact 30
        [{"overall_impact_score": 4}, {"overall_impact_score": 4}],   # impact 40
        [{"overall_impact_score": 5}, {"overall_impact_score": 5}],   # impact 50
    ])
    for entry in entries:
        fixtures.record_council_review(entry["application"]["id"], "FUND",
                                       priority_alignment_score=4)

    institute = fixtures.publish_payline(
        ctx["institute"]["id"], 100.0,
        expected_institute_version=ctx["institute"]["version"])

    statuses = [fixtures.refresh_application(e["application"]["id"])["status"]
                for e in entries]
    # Single-section pool: normalized percentiles are 12.5, 37.5, 62.5, 87.5,
    # all <= 100.0, so the walk order is W1..W4; the boundary stops it at W4.
    assert statuses == ["JIT_PENDING", "JIT_PENDING", "JIT_PENDING", "COUNCIL_REVIEWED"]
    assert institute["current_payline_percentile"] == 100.0
    assert institute["version"] == ctx["institute"]["version"] + 1


def test_payline_percentile_exact_boundary():
    """PRD §3.7: "Each candidate's effective percentile is its `percentile_normalized` reduced by an early-stage bonus — five percentile points when the applicant's `career_stage` is `EARLY_STAGE_INVESTIGATOR`, zero otherwise — but never below one-tenth of a percentile point."
    PRD §3.7: "Candidates whose effective percentile does not exceed the requested `base_payline_percentile` are eligible; they are ordered by effective percentile lowest first, with ties broken by `percentile_raw` lowest first, then `impact_score` lowest first, then `created_at` earliest first."
    A candidate whose effective percentile equals the base payline is funded
    (the comparison is <=).

    Design: Difficulty/boundary_precision_check/payline_percentile_exact_boundary
    """
    ctx = fixtures.make_review_context(appropriation_cents=200_000_000)
    section = fixtures.make_study_section(name="Section PB")
    e1 = fixtures.add_reviewed_application(ctx, section, convene=False, title="PB1")
    e2 = fixtures.add_reviewed_application(ctx, section, convene=False, title="PB2")
    fixtures.score_section(section, [e1, e2], [
        [{"overall_impact_score": 2}, {"overall_impact_score": 2}],   # impact 20
        [{"overall_impact_score": 3}, {"overall_impact_score": 3}],   # impact 30
    ])
    for entry in (e1, e2):
        fixtures.record_council_review(entry["application"]["id"], "FUND",
                                       priority_alignment_score=4)
    # Two-application pool: normalized percentiles are 25.0 and 75.0.
    assert fixtures.refresh_application(e1["application"]["id"])["percentile_normalized"] == 25.0
    assert fixtures.refresh_application(e2["application"]["id"])["percentile_normalized"] == 75.0

    institute = fixtures.publish_payline(ctx["institute"]["id"], 25.0)
    pb1 = fixtures.refresh_application(e1["application"]["id"])
    pb2 = fixtures.refresh_application(e2["application"]["id"])
    assert pb1["status"] == "JIT_PENDING", "25.0 <= 25.0 boundary is funded"
    assert pb2["status"] == "COUNCIL_REVIEWED", "75.0 > 25.0 is not funded"
    assert institute["current_payline_percentile"] == 25.0


def test_select_pay_state_gate_beats_fiscal_cap():
    """PRD §3.7: "Select pay is the discretionary sibling path, exercised by a `GrantsOfficer` on an application in `COUNCIL_REVIEWED` status — from any other status the attempt is rejected with `ERR_APPLICATION_NOT_FUNDABLE`"
    PRD §2.7: "Every request is validated against a fixed, priority-ordered pipeline. When several checks could reject the same request, the earliest stage in this ordering wins, so the error a caller observes is always the highest-priority failure:"
    The application is SCORED (never council-funded), so the state gate (stage
    6) fires before the select-pay fiscal gates (stage 20), even though the
    projected cost (30,000,000) also exceeds the select-pay cap
    (0.10 x 40,000,000 = 4,000,000).

    Design: Difficulty/priority_pair_validation_conflict/select_pay_state_gate_beats_fiscal_cap
    """
    scenario = fixtures.setup_scored_application(
        overall_impact_score=3,
        context_kwargs={"appropriation_cents": 40_000_000, "reserve_cents": 0,
                        "indirect_cost_rate": 0.5, "select_pay_cap_pct": 0.10})
    app_id = scenario["application"]["id"]
    assert scenario["application"]["status"] == "SCORED"

    resp = api_client.select_pay_application(
        app_id, factories.select_pay_payload(rationale="discretionary"), _GO)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FUNDABLE)

    assert fixtures.refresh_application(app_id)["status"] == "SCORED"
    institute = fixtures.refresh_institute(scenario["context"]["institute"]["id"])
    assert institute["select_pay_spent_cents"] == 0, "a rejected selection moves no money"


def test_council_not_fund_terminates_and_locks():
    """PRD §3.6: "`NOT_FUND` moves a `SCORED` or `DEFERRED` application to the terminal `NOT_FUNDED` state."
    PRD §3.6: "Second-level review is performed by a `CouncilMember`, who records a **CouncilReview** for an application in `SCORED` or `DEFERRED` status — recording against any other status is rejected with `ERR_APPLICATION_NOT_SCORED`."

    Design: Corner/state_machines/council_not_fund_terminates_and_locks
    """
    scenario = fixtures.setup_scored_application(overall_impact_score=3)
    app_id = scenario["application"]["id"]
    resp = api_client.create_council_review(
        factories.council_review_payload(app_id, "NOT_FUND"), _CM)
    review = validate_success(resp, 201)
    assert review["recommendation"] == "NOT_FUND"
    assert fixtures.refresh_application(app_id)["status"] == "NOT_FUNDED"

    resp2 = api_client.create_council_review(
        factories.council_review_payload(app_id, "FUND", priority_alignment_score=4), _CM)
    validate_error(resp2, ApiErrorId.ERR_APPLICATION_NOT_SCORED)


def test_defer_then_fund_reviews_application():
    """PRD §3.6: "`DEFER` moves a `SCORED` application to `DEFERRED`, and recording another `DEFER` on an already-`DEFERRED` application is a legitimate re-deferral that leaves it `DEFERRED`."
    PRD §3.6: "`FUND` moves a `SCORED` or `DEFERRED` application to `COUNCIL_REVIEWED`."
    PRD §3.6: "All of an application's council reviews can be listed under the application."

    Design: Corner/state_machines/defer_then_fund_reviews_application
    """
    scenario = fixtures.setup_scored_application(overall_impact_score=3)
    app_id = scenario["application"]["id"]
    fixtures.record_council_review(app_id, "DEFER")
    assert fixtures.refresh_application(app_id)["status"] == "DEFERRED"
    fixtures.record_council_review(app_id, "FUND", priority_alignment_score=4)
    assert fixtures.refresh_application(app_id)["status"] == "COUNCIL_REVIEWED"

    data, meta = validate_paginated(api_client.list_council_reviews(app_id, _CM))
    assert meta["total_count"] == 2 and len(data) == 2, (
        "both council reviews must persist under the application"
    )


def test_esi_payline_bonus_shifts_eligibility():
    """PRD §3.7: "Each candidate's effective percentile is its `percentile_normalized` reduced by an early-stage bonus — five percentile points when the applicant's `career_stage` is `EARLY_STAGE_INVESTIGATOR`, zero otherwise — but never below one-tenth of a percentile point."
    PRD §3.7: "Candidates whose effective percentile does not exceed the requested `base_payline_percentile` are eligible; they are ordered by effective percentile lowest first, with ties broken by `percentile_raw` lowest first, then `impact_score` lowest first, then `created_at` earliest first."

    Design: Corner/calculations/esi_payline_bonus_shifts_eligibility
    """
    ctx = fixtures.make_review_context(appropriation_cents=500_000_000)
    section = fixtures.make_study_section(name="Section ESI")
    e1 = fixtures.add_reviewed_application(ctx, section, convene=False,
                                           career_stage="ESTABLISHED_INVESTIGATOR", title="E1")
    e2 = fixtures.add_reviewed_application(ctx, section, convene=False,
                                           career_stage="EARLY_STAGE_INVESTIGATOR", title="E2")
    e3 = fixtures.add_reviewed_application(ctx, section, convene=False,
                                           career_stage="ESTABLISHED_INVESTIGATOR", title="E3")
    fixtures.score_section(section, [e1, e2, e3], [
        [{"overall_impact_score": 2}, {"overall_impact_score": 2}],   # impact 20
        [{"overall_impact_score": 3}, {"overall_impact_score": 3}],   # impact 30
        [{"overall_impact_score": 4}, {"overall_impact_score": 4}],   # impact 40
    ])
    for entry in (e1, e2, e3):
        fixtures.record_council_review(entry["application"]["id"], "FUND",
                                       priority_alignment_score=4)
    # Single-section pool of three: normalized percentiles 16.7 / 50.0 / 83.3.
    institute = fixtures.publish_payline(ctx["institute"]["id"], 45.0)

    a1 = fixtures.refresh_application(e1["application"]["id"])
    a2 = fixtures.refresh_application(e2["application"]["id"])
    a3 = fixtures.refresh_application(e3["application"]["id"])
    assert a1["percentile_normalized"] == pytest.approx(16.7, abs=1e-9)
    assert a2["percentile_normalized"] == 50.0
    assert a3["percentile_normalized"] == pytest.approx(83.3, abs=1e-9)
    assert a1["status"] == "JIT_PENDING"       # 16.7 <= 45.0 without any bonus
    assert a2["status"] == "JIT_PENDING", (
        "ESI bonus: effective percentile 50.0 - 5.0 == 45.0 <= 45.0"
    )
    assert a3["status"] == "COUNCIL_REVIEWED"  # 83.3 > 45.0, no bonus for ESTABLISHED
    assert institute["current_payline_percentile"] == 45.0


def test_select_pay_band_uses_raw_not_normalized():
    """PRD §3.7: "The band check then uses the *raw* percentile, not the normalized one: the application's `percentile_raw` must not exceed the institute's `current_payline_percentile` plus its `select_pay_extension_percentile`, or the selection is rejected with `ERR_SELECT_PAY_BAND_EXCEEDED`."
    PRD §3.7: "On success the application moves from `COUNCIL_REVIEWED` to `JIT_PENDING` with the same automatically created `ISSUED` just-in-time request due thirty days out, the institute's `select_pay_spent_cents` grows by the projected cost, and the application's `version` increments."
    Derivation: projected cost per application = 20,000,000 + rhup(20,000,000
    x 0.5) = 30,000,000; two selections drive select_pay_spent_cents to
    60,000,000.

    Design: Corner/validations/select_pay_band_uses_raw_not_normalized
    """
    ctx = fixtures.make_review_context(
        appropriation_cents=1_000_000_000, select_pay_extension_percentile=70.0)
    sec_a = fixtures.make_study_section(name="Section SA", meeting_date="2027-03-01T00:00:00Z")
    sec_b = fixtures.make_study_section(name="Section SB", meeting_date="2027-04-15T00:00:00Z")
    e_a1 = fixtures.add_reviewed_application(ctx, sec_a, convene=False, title="SA1")
    e_a2 = fixtures.add_reviewed_application(ctx, sec_a, convene=False, title="SA2")
    e_b1 = fixtures.add_reviewed_application(ctx, sec_b, convene=False, title="SB1")
    fixtures.score_section(sec_a, [e_a1, e_a2], [
        [{"overall_impact_score": 2}, {"overall_impact_score": 2}],   # impact 20
        [{"overall_impact_score": 4}, {"overall_impact_score": 4}],   # impact 40
    ])
    fixtures.score_section(sec_b, [e_b1], [
        [{"overall_impact_score": 5}, {"overall_impact_score": 5}],   # impact 50
    ])
    for entry, score in ((e_a2, 5), (e_b1, 4)):
        fixtures.record_council_review(entry["application"]["id"], "FUND",
                                       priority_alignment_score=score)
    # Base payline 10.0 funds nobody (normalized 83.3 and 50.0 both exceed it).
    fixtures.publish_payline(ctx["institute"]["id"], 10.0)

    a2_pre = fixtures.refresh_application(e_a2["application"]["id"])
    assert a2_pre["percentile_raw"] == 75.0
    assert a2_pre["percentile_normalized"] == pytest.approx(83.3, abs=1e-9)

    # Band on the RAW percentile: 75.0 <= 10.0 + 70.0 passes even though the
    # normalized 83.3 lies beyond the band.
    a2 = fixtures.select_pay(e_a2["application"]["id"], rationale="high program priority")
    assert a2["status"] == "JIT_PENDING"
    b1 = fixtures.select_pay(e_b1["application"]["id"], rationale="portfolio balance")
    assert b1["status"] == "JIT_PENDING"

    a1 = fixtures.refresh_application(e_a1["application"]["id"])
    assert a1["status"] == "SCORED", "a1 was never council-reviewed and stays untouched"
    institute = fixtures.refresh_institute(ctx["institute"]["id"])
    assert institute["select_pay_spent_cents"] == 60_000_000


def test_select_pay_no_payline_then_band_exceeded():
    """PRD §3.7: "The institute must have a published payline: when `current_payline_percentile` is still null, selection is rejected with `ERR_NO_PAYLINE_PUBLISHED`."
    PRD §3.7: "The band check then uses the *raw* percentile, not the normalized one: the application's `percentile_raw` must not exceed the institute's `current_payline_percentile` plus its `select_pay_extension_percentile`, or the selection is rejected with `ERR_SELECT_PAY_BAND_EXCEEDED`."

    Design: Corner/validations/select_pay_no_payline_then_band_exceeded
    """
    scenario = fixtures.setup_council_reviewed_application(recommendation="FUND")
    app_id = scenario["application"]["id"]
    institute_id = scenario["context"]["institute"]["id"]

    early = api_client.select_pay_application(
        app_id, factories.select_pay_payload(rationale="too early"), _GO)
    validate_error(early, ApiErrorId.ERR_NO_PAYLINE_PUBLISHED)

    # Single-application pool: raw == normalized == 50.0, so publishing base
    # 10.0 funds nobody (50.0 > 10.0) but establishes a payline.
    institute = fixtures.publish_payline(institute_id, 10.0)
    assert institute["current_payline_percentile"] == 10.0
    assert institute["version"] == scenario["context"]["institute"]["version"] + 1

    # Band: raw 50.0 > 10.0 + 5.0 (the default select_pay_extension_percentile).
    late = api_client.select_pay_application(
        app_id, factories.select_pay_payload(rationale="too far out"), _GO)
    validate_error(late, ApiErrorId.ERR_SELECT_PAY_BAND_EXCEEDED)
    assert fixtures.refresh_application(app_id)["status"] == "COUNCIL_REVIEWED"


def test_stale_institute_version_on_second_payline():
    """PRD §2.6: "Publishing a payline decision requires the request to carry `expected_institute_version`, the caller's last observed `version` of the institute. A payline decision supersedes the institute's previously published payline, so a request whose `expected_institute_version` no longer matches the institute's current `version` is rejected as stale with `ERR_STALE_INSTITUTE_VERSION` (HTTP 412)."
    PRD §3.7: "The institute's `current_payline_percentile` records exactly the requested `base_payline_percentile`, superseding any previously published payline, and the institute's `version` increments by one."

    Design: Corner/cross_cutting_layers/stale_institute_version_on_second_payline
    """
    institute = fixtures.make_institute()
    v0 = institute["version"]

    first = api_client.publish_payline_decision(
        institute["id"], factories.payline_decision_payload(50.0, v0), _PO)
    d1 = validate_success(first, 200)
    assert d1["current_payline_percentile"] == 50.0
    assert d1["version"] == v0 + 1

    stale = api_client.publish_payline_decision(
        institute["id"], factories.payline_decision_payload(60.0, v0), _PO)
    validate_error(stale, ApiErrorId.ERR_STALE_INSTITUTE_VERSION)

    current = api_client.publish_payline_decision(
        institute["id"], factories.payline_decision_payload(60.0, v0 + 1), _PO)
    d3 = validate_success(current, 200)
    assert d3["current_payline_percentile"] == 60.0
    assert d3["version"] == v0 + 2


def test_applicant_cannot_publish_payline():
    """PRD §2.1: "**ProgramOfficer** — program official; configures funding opportunities, institutes, institutions, and applicant registrations; publishes paylines; operates the logical clock."
    PRD §2.7: "2. **Role authorization.** The supplied role must be listed among the endpoint's authorized roles (`ERR_UNAUTHORIZED_ROLE`, HTTP 403)."
    PRD §2.8: "The `current_payline_percentile` records the most recently published base payline and is null until the first payline decision."

    Design: Corner/rbac/applicant_cannot_publish_payline
    """
    institute = fixtures.make_institute()
    pi_a = fixtures.make_applicant()
    resp = api_client.publish_payline_decision(
        institute["id"],
        factories.payline_decision_payload(50.0, institute["version"]),
        make_applicant_headers(pi_a["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert fixtures.refresh_institute(institute["id"])["current_payline_percentile"] is None
