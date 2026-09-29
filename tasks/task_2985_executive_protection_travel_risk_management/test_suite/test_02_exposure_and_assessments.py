"""Exposure scoring, the two readings of the exposure formula and the review cycle."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _exposure_world(api):
    """A TIER_2 protectee with a 20.00 survey figure and three in-window signals."""
    dep = fx.bootstrap_department(api)
    exec_row = fx.register_executive(api, dep, tier=c.TIER_2)
    fx.complete_residential_survey(api, dep, exec_row["id"], c.SURVEY_COMPLETE, 20.0)
    fx.add_exposure_signal(
        api, dep, exec_row["id"], c.SIGNAL_MEDIA_MENTION, 4, "2026-08-01T00:00:00Z"
    )
    fx.add_exposure_signal(
        api, dep, exec_row["id"], c.SIGNAL_SOCIAL_GEOTAG, 3, "2026-07-02T00:00:00Z"
    )
    fx.add_exposure_signal(
        api, dep, exec_row["id"], c.SIGNAL_PROTEST_MENTION, 2, "2026-06-02T00:00:00Z"
    )
    assessment = fx.draft_assessment(api, dep, exec_row["id"], 40.0)
    return dep, exec_row["id"], assessment["id"]


def test_decay_weighted_score_and_rolling_window_component_diverge(api):
    """One signal set scores 36.25 with decay weighting and 62.50 at full weight.

    PRD §3.2: "`public_exposure_component` is recomputed using the **rolling-window** reading of the exposure formula: the same 90-day half-open window, the same channel multipliers, the same accumulation order, the same scale factor of 5, the same single half-up rounding to two decimals and the same cap of 100.00, but with every in-window signal counted at full weight regardless of age."

    Design: Difficulty/dual_variant_calc/exposure_decay_weighted_vs_rolling_window_diverge_on_one_signal_set
    """
    dep, exec_id, ra_id = _exposure_world(api)

    submitted = validate_success(api.submit_risk_assessment(ra_id, dep.analyst))
    a.assert_decimal_value(
        submitted["public_exposure_component"], 62.50, "public_exposure_component"
    )

    executive = fx.read_executive(api, dep, exec_id, dep.analyst)
    a.assert_decimal_value(
        executive["public_exposure_score"], 36.25, "public_exposure_score"
    )
    assert (
        a.round_half_up(submitted["public_exposure_component"], 2)
        - a.round_half_up(executive["public_exposure_score"], 2)
        == 26.25
    ), "the rolling-window reading exceeds the decay-weighted one on aged signals"


def test_submit_snapshots_the_survey_figure_and_applies_the_tier_uplift(api):
    """The composite pins the snapshot, weights three inputs and uplifts for TIER_2.

    PRD §3.2: "That base is then multiplied by the protectee's tier uplift: 1.20 for `TIER_1`, 1.10 for `TIER_2`, and 1.00 for `TIER_3`."

    Design: Difficulty/dual_variant_calc/exposure_decay_weighted_vs_rolling_window_diverge_on_one_signal_set
    """
    dep, exec_id, ra_id = _exposure_world(api)

    submitted = validate_success(api.submit_risk_assessment(ra_id, dep.analyst))
    a.assert_decimal_value(
        submitted["residential_component_snapshot"],
        20.00,
        "residential_component_snapshot",
    )
    a.assert_decimal_value(
        submitted["composite_risk_score"], 48.26, "composite_risk_score"
    )
    assert submitted["status"] == c.ASSESSMENT_SUBMITTED
    assert submitted["revision_round"] == 0, "a submit never moves the revision round"


def _protest_world(api):
    """A TIER_3 protectee whose single signal is a severity-4 protest mention."""
    dep = fx.bootstrap_department(api)
    exec_row = fx.register_executive(api, dep, tier=c.TIER_3)
    fx.complete_residential_survey(api, dep, exec_row["id"], c.SURVEY_COMPLETE, 10.0)
    fx.add_exposure_signal(
        api, dep, exec_row["id"], c.SIGNAL_PROTEST_MENTION, 4, "2026-08-01T00:00:00Z"
    )
    assessment = fx.draft_assessment(api, dep, exec_row["id"], 30.0)
    return dep, exec_row["id"], assessment["id"]


def test_protest_floor_replaces_the_weighted_composite(api):
    """A severity-4 protest mention floors the composite at 60.00, not 29.50.

    PRD §3.2: "Next comes the protest floor: if the same in-window signal set that produced `public_exposure_component` contains at least one signal whose `signal_type` is `PROTEST_MENTION` and whose `severity` is 4 or greater, the uplifted value is replaced by the larger of itself and 60.00; otherwise it passes through unchanged."

    Design: Difficulty/combinatorial_formula/composite_risk_protest_floor_overrides_three_input_weighting
    """
    dep, exec_id, ra_id = _protest_world(api)

    submitted = validate_success(api.submit_risk_assessment(ra_id, dep.analyst))
    a.assert_decimal_value(
        submitted["public_exposure_component"], 40.00, "public_exposure_component"
    )
    a.assert_decimal_value(
        submitted["composite_risk_score"], 60.00, "composite_risk_score"
    )


def test_protest_floored_composite_bands_the_protectee_as_high(api):
    """The floored 60.00 bands the protectee HIGH where the unfloored value was LOW.

    PRD §3.2: "The banding is: `LOW` when the composite is below 30.00, `ELEVATED` when it is at least 30.00 and below 55.00, `HIGH` when it is at least 55.00 and below 80.00, and `SEVERE` when it is 80.00 or above; the comparisons run against the stored two-decimal value, with every lower bound inclusive and every upper bound exclusive."

    Design: Difficulty/combinatorial_formula/composite_risk_protest_floor_overrides_three_input_weighting
    """
    dep, exec_id, ra_id = _protest_world(api)
    fx.submit_assessment(api, dep, ra_id)

    approved = validate_success(
        api.review_risk_assessment(
            ra_id,
            f.assessment_review_payload(
                c.REVIEW_APPROVE, review_notes="floored by protest exposure"
            ),
            dep.dir,
        )
    )
    assert approved["status"] == c.ASSESSMENT_APPROVED
    a.assert_decimal_value(
        approved["composite_risk_score"], 60.00, "composite_risk_score"
    )

    executive = fx.read_executive(api, dep, exec_id, dep.dir)
    assert executive["threat_level"] == c.THREAT_HIGH
    a.assert_decimal_value(
        executive["public_exposure_score"], 40.00, "public_exposure_score"
    )


def _revision_world(api):
    """A TIER_3 protectee with a complete survey and one draft assessment."""
    dep = fx.bootstrap_department(api)
    exec_row = fx.register_executive(api, dep, tier=c.TIER_3)
    fx.complete_residential_survey(api, dep, exec_row["id"], c.SURVEY_COMPLETE, 10.0)
    assessment = fx.draft_assessment(api, dep, exec_row["id"], 20.0)
    return dep, exec_row["id"], assessment["id"]


def _return_once(api, dep, ra_id, note):
    return validate_success(
        api.review_risk_assessment(
            ra_id,
            f.assessment_review_payload(c.REVIEW_RETURN, review_notes=note),
            dep.dir,
        )
    )


def test_three_returns_keep_the_cycle_open_and_the_fourth_voids_it(api):
    """The return/resubmit loop is bounded by the three-round allowance, not the graph.

    PRD §3.2: "The maximum revision allowance is three rounds, so the first, second and third `RETURN` leave `revision_round` at 1, 2 and 3 respectively with the assessment `RETURNED`, while the fourth leaves `revision_round` at 4 with the assessment `VOIDED`."

    Design: Difficulty/non_linear_state_machine/assessment_revision_cycle_voids_on_fourth_return
    """
    dep, exec_id, ra_id = _revision_world(api)

    fx.submit_assessment(api, dep, ra_id)
    first = _return_once(api, dep, ra_id, "round 1 rework")
    assert (first["status"], first["revision_round"]) == (c.ASSESSMENT_RETURNED, 1)

    resubmitted = fx.submit_assessment(api, dep, ra_id)
    assert resubmitted["status"] == c.ASSESSMENT_SUBMITTED
    assert resubmitted["revision_round"] == 1, "a submit never moves the revision round"

    second = _return_once(api, dep, ra_id, "round 2 rework")
    assert (second["status"], second["revision_round"]) == (c.ASSESSMENT_RETURNED, 2)

    fx.submit_assessment(api, dep, ra_id)
    third = _return_once(api, dep, ra_id, "round 3 rework")
    assert (third["status"], third["revision_round"]) == (c.ASSESSMENT_RETURNED, 3)

    fx.submit_assessment(api, dep, ra_id)
    fourth = _return_once(api, dep, ra_id, "round 4 rework")
    assert (fourth["status"], fourth["revision_round"]) == (c.ASSESSMENT_VOIDED, 4)


def test_each_resubmit_rescores_the_assessment_and_voiding_is_terminal(api):
    """A signal added mid-cycle lifts the composite, and the voided row is closed.

    PRD §3.2: "`VOIDED` is terminal: such an assessment can never be submitted again and never approved."

    Design: Difficulty/non_linear_state_machine/assessment_revision_cycle_voids_on_fourth_return
    """
    dep, exec_id, ra_id = _revision_world(api)

    first_submit = fx.submit_assessment(api, dep, ra_id)
    a.assert_decimal_value(
        first_submit["composite_risk_score"], 11.00, "composite_risk_score"
    )
    _return_once(api, dep, ra_id, "round 1 rework")
    fx.submit_assessment(api, dep, ra_id)
    _return_once(api, dep, ra_id, "round 2 rework")

    fx.add_exposure_signal(
        api, dep, exec_id, c.SIGNAL_MEDIA_MENTION, 4, "2026-08-01T00:00:00Z"
    )
    third_submit = fx.submit_assessment(api, dep, ra_id)
    a.assert_decimal_value(
        third_submit["composite_risk_score"], 18.00, "composite_risk_score"
    )

    _return_once(api, dep, ra_id, "round 3 rework")
    fx.submit_assessment(api, dep, ra_id)
    _return_once(api, dep, ra_id, "round 4 rework")

    blocked = api.submit_risk_assessment(ra_id, dep.analyst)
    validate_error(blocked, e.ERR_ASSESSMENT_INVALID_STATE, 409)

    row = validate_success(api.get_risk_assessment(ra_id, dep.analyst))
    assert row["status"] == c.ASSESSMENT_VOIDED
    assert row["revision_round"] == 4


def test_assessment_and_policy_start_in_their_declared_initial_states(api, dep):
    """A new assessment is a draft at round zero and a new policy is unverified.

    PRD §3.2: "The new row's `status` is `DRAFT` and its `revision_round` is 0; its `approved_by_staff_id`, `supersedes_assessment_id`, `review_notes`, `submitted_at` and `approved_at` are all null, and its three derived components are 0."

    Design: Corner/state_machines/newly_created_assessment_and_policy_start_in_their_declared_initial_states
    """
    exec_row = fx.register_executive(api, dep)

    assessment = validate_success(
        api.create_risk_assessment(
            f.risk_assessment_payload(exec_row["id"], dep.analyst_id, 20.0),
            dep.analyst,
        ),
        201,
    )
    assert assessment["status"] == c.ASSESSMENT_DRAFT
    assert assessment["revision_round"] == 0
    for field in (
        "approved_by_staff_id",
        "supersedes_assessment_id",
        "review_notes",
        "submitted_at",
        "approved_at",
    ):
        assert assessment[field] is None, f"{field} must start null"
    a.assert_decimal_value(
        assessment["public_exposure_component"], 0, "public_exposure_component"
    )
    a.assert_decimal_value(
        assessment["residential_component_snapshot"],
        0,
        "residential_component_snapshot",
    )
    a.assert_decimal_value(
        assessment["composite_risk_score"], 0, "composite_risk_score"
    )
    a.assert_common_fields(assessment, expected_version=1)

    policy = validate_success(
        api.create_insurance_policy(
            f.insurance_policy_payload(exec_row["id"]), dep.officer
        ),
        201,
    )
    assert policy["status"] == c.POLICY_UNVERIFIED
    assert policy["verified_at"] is None
    assert policy["verification_note"] is None
    assert policy["excluded_country_codes"] == []
    a.assert_common_fields(policy, expected_version=1)


def test_submit_before_the_residential_survey_is_blocked_then_deficient_passes(api, dep):
    """Only PENDING blocks a submit; a DEFICIENT survey is a performed survey.

    PRD §3.2: "`residential_survey_status` must be anything other than `PENDING`, so both `COMPLETE` and `DEFICIENT` pass and only `PENDING` blocks with `ERR_RESIDENTIAL_SURVEY_INCOMPLETE`."

    Design: Corner/state_machines/submit_assessment_before_the_residential_survey_returns_survey_incomplete
    """
    exec_row = fx.register_executive(api, dep)
    assessment = fx.draft_assessment(api, dep, exec_row["id"], 20.0)

    blocked = api.submit_risk_assessment(assessment["id"], dep.analyst)
    validate_error(blocked, e.ERR_RESIDENTIAL_SURVEY_INCOMPLETE, 409)

    still_draft = validate_success(
        api.get_risk_assessment(assessment["id"], dep.analyst)
    )
    assert still_draft["status"] == c.ASSESSMENT_DRAFT
    assert still_draft["version"] == 1, "a rejected submit is not a mutation"

    fx.complete_residential_survey(
        api, dep, exec_row["id"], c.SURVEY_DEFICIENT, 40.0
    )
    submitted = validate_success(api.submit_risk_assessment(assessment["id"], dep.analyst))
    assert submitted["status"] == c.ASSESSMENT_SUBMITTED
    a.assert_decimal_value(
        submitted["residential_component_snapshot"],
        40.00,
        "residential_component_snapshot",
    )
    a.assert_decimal_value(
        submitted["composite_risk_score"], 17.00, "composite_risk_score"
    )


def test_exposure_score_rounds_once_and_drops_aged_out_signals(api, dep):
    """The score is scaled then rounded once, and a signal past 90 days is excluded.

    PRD §3.2: "A signal is inside the window when its age in days is at least 0 and strictly less than 90 days — the window is a rolling quarter, half-open at its far edge, and a signal that has aged out is excluded outright rather than down-weighted to a small contribution."

    Design: Corner/calculations/exposure_score_rounds_once_after_scaling_and_drops_signals_past_the_window
    """
    exec_row = fx.register_executive(api, dep)

    after_first = fx.add_exposure_signal(
        api, dep, exec_row["id"], c.SIGNAL_SOCIAL_GEOTAG, 3, "2026-07-02T00:00:00Z"
    )
    assert after_first is not None
    a.assert_decimal_value(
        fx.read_executive(api, dep, exec_row["id"])["public_exposure_score"],
        11.25,
        "public_exposure_score",
    )

    fx.add_exposure_signal(
        api, dep, exec_row["id"], c.SIGNAL_MEDIA_MENTION, 5, "2026-08-01T00:00:00Z"
    )
    a.assert_decimal_value(
        fx.read_executive(api, dep, exec_row["id"])["public_exposure_score"],
        36.25,
        "public_exposure_score",
    )

    fx.add_exposure_signal(
        api, dep, exec_row["id"], c.SIGNAL_PUBLIC_FILING, 4, "2026-05-01T00:00:00Z"
    )
    a.assert_decimal_value(
        fx.read_executive(api, dep, exec_row["id"])["public_exposure_score"],
        36.25,
        "public_exposure_score",
    )

    signals, meta = validate_paginated(
        api.list_exposure_signals(exec_row["id"], dep.analyst)
    )
    assert meta["total_count"] == 3, "the aged-out signal is stored, only unscored"


def test_approving_a_second_assessment_supersedes_the_first_and_relevels_the_trip(api):
    """Approving higher-scoring intelligence re-points the live trip and re-bands its leg.

    PRD §3.2: "Hop three re-points every trip that referenced the superseded assessment and whose `readiness_state` is not `CLOSED`, rewriting each one's `risk_assessment_id` to the newly approved assessment."

    Design: Corner/state_machines/approving_a_second_assessment_supersedes_the_first_and_relevels_the_live_trip
    """
    w = fx.bootstrap_world(
        api,
        rating={
            "crime_index": 30.0,
            "political_instability_index": 30.0,
            "medical_infrastructure_index": 100.0,
            "natural_hazard_index": 34.95,
        },
        coverage_cents=50_000_000,
    )
    dep = w.dep
    a.assert_decimal_value(
        w.rating["composite_destination_score"], 24.99, "composite_destination_score"
    )
    assert w.rating["rating_band"] == c.BAND_LOW

    trip = fx.create_trip(
        api, dep, w.exec_id, w.ra_id, insurance_policy_id=w.policy_id
    )
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        arrive_at=c.TRIP_DEPART_AT,
        depart_at=c.TRIP_RETURN_AT,
    )
    assert leg["leg_risk_band"] == c.BAND_LOW
    fx.assign_detail(
        api,
        dep,
        leg["id"],
        dep.lead_id,
        c.DETAIL_LEAD_AGENT,
        "2026-09-10T08:00:00Z",
        "2026-09-10T18:00:00Z",
    )
    fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY)
    submitted_trip = fx.submit_trip(api, dep, trip["id"])
    assert submitted_trip["max_leg_risk_band"] == c.BAND_LOW
    assert submitted_trip["required_approval_level"] == c.LEVEL_MANAGER
    fx.ack_briefing(api, w.exec_id, trip["id"])
    fx.decide_trip(api, dep, trip["id"], c.DECISION_APPROVE)
    w.trip_id = trip["id"]
    w.leg_id = leg["id"]

    second = fx.draft_assessment(api, dep, w.exec_id, 90.0)
    submitted = fx.submit_assessment(api, dep, second["id"])
    a.assert_decimal_value(
        submitted["composite_risk_score"], 42.50, "composite_risk_score"
    )

    approved = fx.review_assessment(
        api, dep, second["id"], c.REVIEW_APPROVE, "new intelligence"
    )
    assert approved["status"] == c.ASSESSMENT_APPROVED
    assert approved["approved_by_staff_id"] == dep.dir_id
    assert approved["approved_at"] == "2026-08-01T00:00:00.000Z"
    assert approved["supersedes_assessment_id"] == w.ra_id

    superseded = validate_success(api.get_risk_assessment(w.ra_id, dep.analyst))
    assert superseded["status"] == c.ASSESSMENT_SUPERSEDED

    executive = fx.read_executive(api, dep, w.exec_id)
    assert executive["threat_level"] == c.THREAT_ELEVATED

    trip = fx.read_trip(api, dep, w.trip_id)
    assert trip["risk_assessment_id"] == second["id"]
    assert trip["max_leg_risk_band"] == c.BAND_MODERATE
    assert trip["required_approval_level"] == c.LEVEL_DIRECTOR
    a.assert_trip_states(
        trip, c.APPROVAL_PENDING_REVIEW, c.READINESS_ADVANCE_IN_PROGRESS
    )
    assert trip["briefing_ack_at"] is None

    leg = fx.read_leg(api, dep, w.leg_id)
    assert leg["leg_risk_band"] == c.BAND_MODERATE
    assert leg["required_advance_items"] == [c.ITEM_ROUTE_SURVEY, c.ITEM_HOTEL_SURVEY]
    assert leg["completed_advance_items"] == [c.ITEM_ROUTE_SURVEY]
    assert leg["advance_complete"] is False

    a.assert_budget_ledger(
        executive, committed=112_500, spent=0, remaining=99_887_500
    )
    a.assert_cents(
        trip["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )
