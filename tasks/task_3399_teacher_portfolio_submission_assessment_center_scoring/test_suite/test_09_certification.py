"""Certification decisions: auto-creation, the provisional/final weighted-total
variants, the pinned rounding order, the threshold boundary, the read-driven
decision cascade, denial/reopen on retake, and clock-driven expiry."""
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    BOARD,
    INCENTIVE_ADMIN,
    STANDARD_COMPLETION_CLOCK,
    VALIDITY_DAYS,
    AssignmentStatus,
    CertificationStatus,
    ProgramStatus,
    StipendStatus,
    SubmissionStatus,
    assert_certification,
    assert_certification_validity_window,
    create_active_assessors,
    create_assessment_center,
    create_certified_scenario,
    create_default_benchmark,
    create_eligible_candidate,
    create_fully_scored_scenario,
    create_incentive_program_payload,
    create_live_assignment,
    create_open_cycle,
    create_portfolio_submission_in_state,
    create_submission,
    cycle_component,
    expected_weighted_total,
    get_certification_for,
    get_success_data,
    retake_submission,
    score_assessment_component,
    score_portfolio_with_agreeing_reads,
    set_logical_clock,
    submit_assignment_score,
    submit_submission,
    tech_review,
    upload_minimal_portfolio_artifacts,
    validate_created,
    validate_success,
)

EARLY_BIRD_DEADLINE = "2027-12-31T00:00:00Z"


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_certification_record_auto_created_pending_on_first_submission(api):
    """PRD §3.3: "The candidate's very first attempt in a cycle also auto-creates
    their certification record for that cycle in `PENDING` status with
    `weighted_total_provisional` at 0.0 — exactly one certification record ever
    exists per candidate-and-cycle pair."
    PRD §3.7: "`weighted_total_final` uses each component's `counted_score` — the
    best across `SCORED` attempts — so a worse retake cannot lower it; it is
    computed only once every component of the cycle has at least one `SCORED`
    attempt, it drives the certification decision, and it is stored on the
    certification when decided, staying null until then."

    Design: Corner/calculations/certification_record_auto_created_pending_on_first_submission
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    create_submission(cycle["id"], candidate, "P1")

    certification = get_certification_for(candidate["id"], cycle["id"])

    assert_certification(certification)
    assert certification["status"] == CertificationStatus.PENDING.value
    assert certification["weighted_total_provisional"] == 0.0
    assert certification["weighted_total_final"] is None


def test_certification_expires_after_valid_until(api):
    """PRD §3.7: "A `weighted_total_final` at or above the cycle's
    `certification_threshold` moves the certification from `PENDING` to
    `CERTIFIED` — equality certifies — stamping `certified_at` from the logical
    clock and computing `valid_until` as `certified_at` plus 1825 days, the fixed
    validity period."
    PRD §3.7: "When the logical clock advances past `valid_until` for a
    certification in `CERTIFIED` or `RENEWED`, the sweep of §2.4 flips it to
    `EXPIRED`, the certification's terminal state."

    Re-derived literals: the design recipe hardcodes valid_until
    2032-05-30T00:00:00Z and a 2032-05-31 sweep, but certified_at +
    1825 days from 2027-01-20T15:00:00Z is 2032-01-19T15:00:00Z. This test asserts
    the window through the frozen validity helper (which applies the PRD rule) and
    sweeps one day past the certification's own computed valid_until.

    Design: Corner/state_machines/certification_expires_after_valid_until
    """
    scenario = create_certified_scenario()
    certification = scenario["certification"]
    assert certification["status"] == CertificationStatus.CERTIFIED.value
    assert _parse_iso(certification["certified_at"]) == _parse_iso(STANDARD_COMPLETION_CLOCK)
    assert_certification_validity_window(
        certification, certification["certified_at"], VALIDITY_DAYS
    )

    sweep_clock = _format_iso(_parse_iso(certification["valid_until"]) + timedelta(days=1))
    set_logical_clock(sweep_clock)

    expired = validate_success(api.get_certification(certification["id"], BOARD))
    assert expired["status"] == CertificationStatus.EXPIRED.value
    assert expired["valid_until"] == certification["valid_until"]


def test_certification_denied_below_threshold_reopens_on_retake(api):
    """PRD §3.7: "A total below the threshold moves the certification to `DENIED`
    instead."
    PRD §3.7: "A certification stays `PENDING` while any component remains
    unscored, and a retake after a denial reopens the decision exactly as §3.3
    describes: back to `PENDING`, with `weighted_total_final` cleared to null."

    Substituted literal: the design recipe completes the CKA booking with
    earned_score 2.85, which is off the 0.25 grid and would be rejected with
    ERR_SCORE_INVALID at booking completion per PRD §2.6 ("a valid score is at
    least 0.00, at most 4.00, and an exact multiple of 0.25"). This test uses the
    grid-legal CKA 2.75 instead; with P1 1.50 / P2 1.00 / P3 0.50 the weighted
    total is 1.70 < 1.75 — still the below-threshold DENIED branch the recipe
    targets.

    Design: Corner/state_machines/certification_denied_at_1_74_reopens_on_retake
    """
    scenario = create_fully_scored_scenario(
        scores={"CKA": 2.75, "P1": 1.50, "P2": 1.00, "P3": 0.50}
    )
    certification = scenario["certification"]
    assert certification["status"] == CertificationStatus.DENIED.value
    expected = expected_weighted_total(
        [(2.75, 0.40), (1.50, 0.20), (1.00, 0.20), (0.50, 0.20)]
    )
    assert expected == 1.70
    assert certification["weighted_total_final"] == pytest.approx(expected)

    p1_attempt1 = scenario["submissions"]["P1"]
    attempt2 = retake_submission(p1_attempt1["id"], scenario["candidate"])
    assert attempt2["attempt_number"] == 2
    assert attempt2["prior_submission_id"] == p1_attempt1["id"]

    reopened = validate_success(api.get_certification(certification["id"], BOARD))
    assert reopened["status"] == CertificationStatus.PENDING.value
    assert reopened["weighted_total_final"] is None


def _certified_then_worse_p2_retake(api) -> dict:
    """Certify on the standard 2.40 pipeline, then retake P2 and score it worse
    (1.25 agreeing pair). Returns the scenario augmented with the P2 retake."""
    scenario = create_certified_scenario()
    candidate = scenario["candidate"]
    assessors = scenario["assessors"]
    attempt2 = retake_submission(scenario["submissions"]["P2"]["id"], candidate)
    upload_minimal_portfolio_artifacts(attempt2["id"], candidate)
    submit_submission(attempt2["id"], candidate)
    tech_review(attempt2["id"], "ACCEPT")
    score_portfolio_with_agreeing_reads(
        attempt2["id"], assessors[0], assessors[1], 1.25
    )
    scenario["p2_attempt2"] = attempt2
    return scenario


def test_provisional_variant_tracks_latest_attempt(api):
    """PRD §3.7: "`weighted_total_provisional` lives on the certification at all
    times, starts at 0.0, is recomputed on every score event and every retake
    creation, and uses each component's **latest-attempt** `final_score`, treating
    a component whose latest attempt is unscored as 0 — so a worse retake drags the
    provisional total down."

    With the P2 retake scored 1.25 (latest attempt), the provisional reads
    1.20 + 0.50 + 0.25 + 0.40 == 2.35.

    Design: Difficulty/dual_variant_calc/certification_weighted_total_provisional_latest_vs_final_max
    """
    scenario = _certified_then_worse_p2_retake(api)

    certification = validate_success(
        api.get_certification(scenario["certification"]["id"], BOARD)
    )
    expected_provisional = expected_weighted_total(
        [(3.00, 0.40), (2.50, 0.20), (1.25, 0.20), (2.00, 0.20)]
    )
    assert expected_provisional == 2.35
    assert certification["weighted_total_provisional"] == pytest.approx(
        expected_provisional
    )

    attempt1 = validate_success(
        api.get_submission(scenario["submissions"]["P2"]["id"], BOARD)
    )
    attempt2 = validate_success(
        api.get_submission(scenario["p2_attempt2"]["id"], BOARD)
    )
    assert attempt1["final_score"] == 1.50
    assert attempt2["final_score"] == 1.25
    assert attempt2["attempt_number"] == 2
    assert attempt2["prior_submission_id"] == attempt1["id"]


def test_final_variant_uses_max_across_attempts(api):
    """PRD §3.7: "`weighted_total_final` uses each component's `counted_score` —
    the best across `SCORED` attempts — so a worse retake cannot lower it".
    PRD §3.3: "`counted_score` stays null until at least one attempt is `SCORED`,
    and it — not the latest attempt — is what final certification aggregation
    reads, so a worse retake never lowers a candidate's certified record."

    The decided certification keeps weighted_total_final 2.40 (max variant) and
    stays CERTIFIED after the worse 1.25 retake; both P2 attempt rows carry the
    max counted_score 1.50, and superseded flags follow the highest attempt.

    Design: Difficulty/dual_variant_calc/certification_weighted_total_provisional_latest_vs_final_max
    """
    scenario = _certified_then_worse_p2_retake(api)

    certification = validate_success(
        api.get_certification(scenario["certification"]["id"], BOARD)
    )
    expected_final = expected_weighted_total(
        [(3.00, 0.40), (2.50, 0.20), (1.50, 0.20), (2.00, 0.20)]
    )
    assert expected_final == 2.40
    assert certification["weighted_total_final"] == pytest.approx(expected_final)
    assert certification["status"] == CertificationStatus.CERTIFIED.value

    attempt1 = validate_success(
        api.get_submission(scenario["submissions"]["P2"]["id"], BOARD)
    )
    attempt2 = validate_success(
        api.get_submission(scenario["p2_attempt2"]["id"], BOARD)
    )
    assert attempt1["counted_score"] == 1.50
    assert attempt2["counted_score"] == 1.50
    assert attempt1["superseded"] is True
    assert attempt2["superseded"] is False


def test_weighted_score_pinned_rounding_order_certifies(api):
    """PRD §2.6: "The rounding order of the weighted certification total is pinned
    and non-negotiable: each component's weighted contribution is rounded half up
    to 3 decimal places **before** summing, the rounded contributions are summed,
    and the resulting sum is then rounded half up to 2 decimal places. Summing the
    raw products and rounding only once at the end is a different, non-conformant
    algorithm — with component weights 0.325, 0.275, 0.225, and 0.175 against
    scores 0.00, 0.25, 0.50, and 1.50, the pinned round-then-sum order yields 0.45
    while sum-then-round yields 0.44."
    PRD §3.7: "A `weighted_total_final` at or above the cycle's
    `certification_threshold` moves the certification from `PENDING` to
    `CERTIFIED` — equality certifies".

    The PRD's own worked example is replayed end to end: the pinned order reaches
    0.45, which certifies at a 0.45 threshold.

    Design: Difficulty/combinatorial_formula/weighted_score_per_component_rounding_order
    """
    components = [
        cycle_component("RK", "ASSESSMENT", 0.325),
        cycle_component("RA", "PORTFOLIO", 0.275),
        cycle_component("RB", "PORTFOLIO", 0.225),
        cycle_component("RC", "PORTFOLIO", 0.175),
    ]
    scenario = create_fully_scored_scenario(
        scores={"RK": 0.00, "RA": 0.25, "RB": 0.50, "RC": 1.50},
        cycle_overrides={"components": components, "certification_threshold": 0.45},
    )

    certification = scenario["certification"]
    expected = expected_weighted_total(
        [(0.00, 0.325), (0.25, 0.275), (0.50, 0.225), (1.50, 0.175)]
    )
    assert expected == 0.45
    assert certification["weighted_total_final"] == pytest.approx(0.45)
    assert certification["weighted_total_final"] != 0.44, (
        "the non-conformant sum-then-round order would compute 0.44"
    )
    assert certification["status"] == CertificationStatus.CERTIFIED.value


def test_weighted_score_pinned_rounding_order_provisional_and_inputs(api):
    """PRD §2.6: "The rounding order of the weighted certification total is pinned
    and non-negotiable: each component's weighted contribution is rounded half up
    to 3 decimal places **before** summing, the rounded contributions are summed,
    and the resulting sum is then rounded half up to 2 decimal places."
    PRD §3.7: "`weighted_total_provisional` lives on the certification at all
    times, starts at 0.0, is recomputed on every score event and every retake
    creation, and uses each component's **latest-attempt** `final_score`, treating
    a component whose latest attempt is unscored as 0".

    Single attempts per component make the provisional variant read the same
    score inputs; it must show the same pinned-order 0.45.

    Design: Difficulty/combinatorial_formula/weighted_score_per_component_rounding_order
    """
    components = [
        cycle_component("RK", "ASSESSMENT", 0.325),
        cycle_component("RA", "PORTFOLIO", 0.275),
        cycle_component("RB", "PORTFOLIO", 0.225),
        cycle_component("RC", "PORTFOLIO", 0.175),
    ]
    scenario = create_fully_scored_scenario(
        scores={"RK": 0.00, "RA": 0.25, "RB": 0.50, "RC": 1.50},
        cycle_overrides={"components": components, "certification_threshold": 0.45},
    )

    submissions = scenario["submissions"]
    assert submissions["RK"]["final_score"] == 0.00
    assert submissions["RA"]["final_score"] == 0.25
    assert submissions["RB"]["final_score"] == 0.50
    assert submissions["RC"]["final_score"] == 1.50

    certification = scenario["certification"]
    assert certification["weighted_total_provisional"] == pytest.approx(0.45)


def test_threshold_exact_equality_certifies(api):
    """PRD §3.1: "The cycle's `certification_threshold` is the weighted total at
    or above which certification is granted — a total exactly equal to the
    threshold certifies."
    PRD §3.7: "A `weighted_total_final` at or above the cycle's
    `certification_threshold` moves the certification from `PENDING` to
    `CERTIFIED` — equality certifies".

    CKA 3.00 / P1 1.75 / P2 1.00 / P3 0.00 sums to exactly the 1.75 threshold.

    Design: Difficulty/boundary_precision_check/certification_threshold_exact_equality_certifies
    """
    scenario = create_fully_scored_scenario(
        scores={"CKA": 3.00, "P1": 1.75, "P2": 1.00, "P3": 0.00}
    )

    certification = scenario["certification"]
    expected = expected_weighted_total(
        [(3.00, 0.40), (1.75, 0.20), (1.00, 0.20), (0.00, 0.20)]
    )
    assert expected == 1.75
    assert certification["weighted_total_final"] == pytest.approx(1.75)
    assert certification["status"] == CertificationStatus.CERTIFIED.value


def test_decision_fires_when_last_component_scores(api):
    """PRD §3.7: "The decision fires automatically the moment every cycle
    component holds a `counted_score`."
    PRD §3.7: "A certification stays `PENDING` while any component remains
    unscored".

    With P3's read pair incomplete the certification is PENDING with a null
    final; the landing of P3's second read decides it on the spot at exactly the
    1.75 threshold.

    Design: Difficulty/boundary_precision_check/certification_threshold_exact_equality_certifies
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    assessors = create_active_assessors(benchmark["id"], count=2)
    center = create_assessment_center()

    score_assessment_component(cycle["id"], candidate, center["id"], earned_score=3.00)
    p1 = create_portfolio_submission_in_state(cycle["id"], candidate, "P1", state="SCORING")
    score_portfolio_with_agreeing_reads(p1["id"], assessors[0], assessors[1], 1.75)
    p2 = create_portfolio_submission_in_state(cycle["id"], candidate, "P2", state="SCORING")
    score_portfolio_with_agreeing_reads(p2["id"], assessors[0], assessors[1], 1.00)
    p3 = create_portfolio_submission_in_state(cycle["id"], candidate, "P3", state="SCORING")

    first = create_live_assignment(p3["id"], assessors[0])
    submit_assignment_score(first["id"], assessors[0], 0.00)

    pending = get_certification_for(candidate["id"], cycle["id"])
    assert pending["status"] == CertificationStatus.PENDING.value
    assert pending["weighted_total_final"] is None

    second = create_live_assignment(p3["id"], assessors[1])
    submit_assignment_score(second["id"], assessors[1], 0.00)

    decided = validate_success(api.get_certification(pending["id"], BOARD))
    assert decided["status"] == CertificationStatus.CERTIFIED.value
    assert decided["weighted_total_final"] == pytest.approx(1.75)


def _cascade_stage(api) -> dict:
    """All components except P3 fully scored; P3 in SCORING with read 1 (2.00)
    submitted; one OPEN statewide program in place. The cascade origin is P3's
    second read."""
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    assessors = create_active_assessors(benchmark["id"], count=2)
    center = create_assessment_center()

    score_assessment_component(cycle["id"], candidate, center["id"], earned_score=3.00)
    p1 = create_portfolio_submission_in_state(cycle["id"], candidate, "P1", state="SCORING")
    score_portfolio_with_agreeing_reads(p1["id"], assessors[0], assessors[1], 2.50)
    p2 = create_portfolio_submission_in_state(cycle["id"], candidate, "P2", state="SCORING")
    score_portfolio_with_agreeing_reads(p2["id"], assessors[0], assessors[1], 1.50)
    p3 = create_portfolio_submission_in_state(cycle["id"], candidate, "P3", state="SCORING")
    first_read = create_live_assignment(p3["id"], assessors[0])
    submit_assignment_score(first_read["id"], assessors[0], 2.00)

    program = validate_created(
        api.create_incentive_program(
            create_incentive_program_payload(
                budget_total_cents=500000,
                base_stipend_cents=300000,
                early_bird_multiplier=1.10,
                early_bird_deadline=EARLY_BIRD_DEADLINE,
            ),
            INCENTIVE_ADMIN,
        )
    )
    return {
        "cycle": cycle,
        "candidate": candidate,
        "assessors": assessors,
        "p3": p3,
        "first_read": first_read,
        "program": program,
    }


def test_read_finalization_cascades_to_certified(api):
    """PRD §3.6: "If the reads sit within 0.50 of each other — the boundary is
    inclusive — the attempt's `final_score` is the mean of the two reads rounded
    half up to 2 decimal places, both read assignments transition to `FINALIZED`,
    and the attempt becomes `SCORED`."
    PRD §3.7: "The decision fires automatically the moment every cycle component
    holds a `counted_score`. A `weighted_total_final` at or above the cycle's
    `certification_threshold` moves the certification from `PENDING` to
    `CERTIFIED` — equality certifies — stamping `certified_at` from the logical
    clock and computing `valid_until` as `certified_at` plus 1825 days, the fixed
    validity period."

    Hop chain from the second read's submission: read FINALIZED -> submission
    SCORED (2.00) -> certification CERTIFIED at 2.40, stamped from the logical
    clock with the validity window derived per the PRD rule.

    Design: Difficulty/transitive_cascade/read_finalization_cascades_to_certification_and_stipend
    """
    stage = _cascade_stage(api)

    second_read = create_live_assignment(stage["p3"]["id"], stage["assessors"][1])
    submit_assignment_score(second_read["id"], stage["assessors"][1], 2.00)

    finalized = validate_success(api.get_assignment(second_read["id"], BOARD))
    assert finalized["status"] == AssignmentStatus.FINALIZED.value

    scored = validate_success(api.get_submission(stage["p3"]["id"], BOARD))
    assert scored["status"] == SubmissionStatus.SCORED.value
    assert scored["final_score"] == 2.00

    certification = get_certification_for(stage["candidate"]["id"], stage["cycle"]["id"])
    assert_certification(certification)
    assert certification["status"] == CertificationStatus.CERTIFIED.value
    expected = expected_weighted_total(
        [(3.00, 0.40), (2.50, 0.20), (1.50, 0.20), (2.00, 0.20)]
    )
    assert expected == 2.40
    assert certification["weighted_total_final"] == pytest.approx(expected)
    assert _parse_iso(certification["certified_at"]) == _parse_iso(
        STANDARD_COMPLETION_CLOCK
    )
    assert_certification_validity_window(
        certification, certification["certified_at"], VALIDITY_DAYS
    )


def test_certification_cascade_auto_proposes_stipend(api):
    """PRD §3.8: "The moment a certification becomes `CERTIFIED`, stipend
    auto-proposal runs: for every `OPEN` program whose eligibility geography
    matches the candidate and whose `budget_remaining_cents` is above 0, the
    system creates a stipend in `PROPOSED` keyed by `program_id` and
    `certification_id`."
    PRD §3.8: "No money moves at proposal time — the debit happens only at
    approval."

    Hop 4 of the same cascade: the statewide NM program (candidate license_state
    NM, fte 1.0, early multiplier 1.10 before the deadline) receives a PROPOSED
    stipend of round_half_up(300000 x 1.0 x 1.10) == 330000 cents, and the
    program's remaining budget is untouched.

    Design: Difficulty/transitive_cascade/read_finalization_cascades_to_certification_and_stipend
    """
    stage = _cascade_stage(api)

    second_read = create_live_assignment(stage["p3"]["id"], stage["assessors"][1])
    submit_assignment_score(second_read["id"], stage["assessors"][1], 2.00)

    certification = get_certification_for(stage["candidate"]["id"], stage["cycle"]["id"])
    assert certification["status"] == CertificationStatus.CERTIFIED.value

    stipends = get_success_data(
        api.list_certification_stipends(certification["id"], INCENTIVE_ADMIN)
    )
    assert len(stipends) == 1
    stipend = stipends[0]
    assert stipend["program_id"] == stage["program"]["id"]
    assert stipend["certification_id"] == certification["id"]
    assert stipend["amount_cents"] == 330000
    assert stipend["status"] == StipendStatus.PROPOSED.value

    program = validate_success(
        api.get_incentive_program(stage["program"]["id"], INCENTIVE_ADMIN)
    )
    assert program["budget_remaining_cents"] == 500000
    assert program["status"] == ProgramStatus.OPEN.value
