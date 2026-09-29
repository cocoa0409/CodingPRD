"""Destination advisories, the coverage floors and insurance verification."""

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

PL_RATING = {
    "crime_index": 30.0,
    "political_instability_index": 25.0,
    "medical_infrastructure_index": 70.0,
    "natural_hazard_index": 20.0,
}
PL_EMERGENCY = {
    "crime_index": 95.0,
    "political_instability_index": 95.0,
    "medical_infrastructure_index": 20.0,
    "natural_hazard_index": 80.0,
    "advisory_note": "State of emergency declared",
}


def _cascade_world(api):
    """A MODERATE PL trip carried to APPROVED and READY on a covered leg."""
    w = fx.bootstrap_world(api, country_code=c.COUNTRY_PL, rating=PL_RATING)
    dep = w.dep
    trip = fx.create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        insurance_policy_id=w.policy_id,
        primary_destination_country_code=c.COUNTRY_PL,
        cost_allocation_method=c.ALLOCATION_PRORATA,
    )
    leg = fx.add_leg(api, dep, trip["id"], destination_country_code=c.COUNTRY_PL)
    w.assignment = fx.assign_detail(api, dep, leg["id"], dep.lead_id)
    fx.complete_required_advance_work(api, dep, leg["id"])
    fx.submit_trip(api, dep, trip["id"])
    fx.ack_briefing(api, w.exec_id, trip["id"])
    w.trip = fx.decide_trip(api, dep, trip["id"], c.DECISION_APPROVE)
    w.trip_id = trip["id"]
    w.leg_id = leg["id"]
    return w


def test_advisory_revision_rescores_the_country_and_expands_the_advance_set(api):
    """Hops one and two: the rating is recomputed and every matching leg re-banded.

    PRD §3.3: "Hop two recomputes `leg_risk_band` and `required_advance_items` on every trip leg whose `destination_country_code` matches this country and whose owning trip's `readiness_state` is not `CLOSED`."

    Design: Difficulty/transitive_cascade/destination_rating_revision_cascades_four_hops_and_reopens_approval
    """
    w = _cascade_world(api)
    dep = w.dep

    a.assert_decimal_value(
        w.rating["composite_destination_score"], 26.50, "composite_destination_score"
    )
    assert w.rating["rating_band"] == c.BAND_MODERATE
    a.assert_cents(
        w.rating["insurance_required_coverage_cents"],
        50_000_000,
        "insurance_required_coverage_cents",
    )

    before_leg = fx.read_leg(api, dep, w.leg_id)
    assert before_leg["leg_risk_band"] == c.BAND_MODERATE
    assert before_leg["required_advance_items"] == [
        c.ITEM_ROUTE_SURVEY,
        c.ITEM_HOTEL_SURVEY,
    ]
    assert before_leg["advance_complete"] is True
    assert w.trip["required_approval_level"] == c.LEVEL_DIRECTOR
    a.assert_trip_states(w.trip, c.APPROVAL_APPROVED, c.READINESS_READY)
    assert w.trip["check_in_interval_hours"] == 12
    assert w.trip["briefing_ack_at"] == "2026-08-01T00:00:00.000Z"
    a.assert_cents(
        w.trip["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )

    revised = validate_success(
        api.update_destination_rating(
            c.COUNTRY_PL,
            f.destination_rating_patch_payload(**PL_EMERGENCY),
            dep.analyst,
        )
    )
    a.assert_decimal_value(
        revised["composite_destination_score"], 89.00, "composite_destination_score"
    )
    assert revised["rating_band"] == c.BAND_EXTREME
    a.assert_cents(
        revised["insurance_required_coverage_cents"],
        500_000_000,
        "insurance_required_coverage_cents",
    )

    after_leg = fx.read_leg(api, dep, w.leg_id)
    assert after_leg["leg_risk_band"] == c.BAND_EXTREME
    assert after_leg["required_advance_items"] == [
        c.ITEM_ROUTE_SURVEY,
        c.ITEM_HOTEL_SURVEY,
        c.ITEM_HOSPITAL_SURVEY,
        c.ITEM_COMMS_TEST,
        c.ITEM_LOCAL_LIAISON,
    ]
    assert after_leg["completed_advance_items"] == [
        c.ITEM_ROUTE_SURVEY,
        c.ITEM_HOTEL_SURVEY,
    ]
    assert after_leg["advance_complete"] is False


def test_advisory_revision_degrades_readiness_and_reopens_the_approval(api):
    """Hops three and four: the raised level reverts approval and voids the briefing.

    PRD §3.3: "Hop four handles the approval consequence: any affected trip whose `approval_state` was `APPROVED` and whose `required_approval_level` has risen reverts `APPROVED → PENDING_REVIEW` and has `briefing_ack_at` cleared to null."

    Design: Difficulty/transitive_cascade/destination_rating_revision_cascades_four_hops_and_reopens_approval
    """
    w = _cascade_world(api)
    dep = w.dep

    validate_success(
        api.update_destination_rating(
            c.COUNTRY_PL,
            f.destination_rating_patch_payload(**PL_EMERGENCY),
            dep.analyst,
        )
    )

    trip = fx.read_trip(api, dep, w.trip_id)
    assert trip["max_leg_risk_band"] == c.BAND_EXTREME
    assert trip["required_approval_level"] == c.LEVEL_DIRECTOR_AND_COMPLIANCE
    a.assert_trip_states(trip, c.APPROVAL_PENDING_REVIEW, c.READINESS_DEGRADED)
    assert trip["check_in_interval_hours"] == 2
    assert trip["briefing_ack_at"] is None

    executive = fx.read_executive(api, dep, w.exec_id)
    assert executive["open_degraded_trip_count"] == 1
    a.assert_budget_ledger(executive, committed=112_500, spent=0)
    a.assert_cents(
        trip["provisional_security_cost_cents"],
        112_500,
        "provisional_security_cost_cents",
    )

    assignment = validate_success(
        api.get_detail_assignment(w.assignment["id"], dep.mgr)
    )
    assert assignment["status"] == c.ASSIGNMENT_CONFIRMED
    assert fx.read_leg(api, dep, w.leg_id)["lead_agent_covered"] is True


def test_composite_lands_exactly_on_the_moderate_band_edge(api, dep):
    """The band cut is lower-bound inclusive, so equality already moves the band.

    PRD §3.3: "`rating_band` is the threshold band of that composite: `LOW` when the composite is below 25.00, `MODERATE` when it is at least 25.00 and below 50.00, `HIGH` when it is at least 50.00 and below 75.00, and `EXTREME` when it is 75.00 or above."

    Design: Corner/calculations/destination_composite_lands_exactly_on_the_moderate_band_edge
    """
    below = validate_success(
        api.create_destination_rating(
            f.destination_rating_payload(
                country_code=c.COUNTRY_PT,
                crime_index=30.0,
                political_instability_index=30.0,
                medical_infrastructure_index=100.0,
                natural_hazard_index=34.95,
            ),
            dep.analyst,
        ),
        201,
    )
    a.assert_decimal_value(
        below["composite_destination_score"], 24.99, "composite_destination_score"
    )
    assert below["rating_band"] == c.BAND_LOW
    a.assert_cents(
        below["insurance_required_coverage_cents"],
        25_000_000,
        "insurance_required_coverage_cents",
    )

    on_edge = validate_success(
        api.update_destination_rating(
            c.COUNTRY_PT,
            f.destination_rating_patch_payload(natural_hazard_index=35.0),
            dep.analyst,
        )
    )
    a.assert_decimal_value(
        on_edge["composite_destination_score"], 25.00, "composite_destination_score"
    )
    assert on_edge["rating_band"] == c.BAND_MODERATE
    a.assert_cents(
        on_edge["insurance_required_coverage_cents"],
        50_000_000,
        "insurance_required_coverage_cents",
    )

    above = validate_success(
        api.update_destination_rating(
            c.COUNTRY_PT,
            f.destination_rating_patch_payload(natural_hazard_index=35.05),
            dep.analyst,
        )
    )
    a.assert_decimal_value(
        above["composite_destination_score"], 25.01, "composite_destination_score"
    )
    assert above["rating_band"] == c.BAND_MODERATE
    a.assert_cents(
        above["insurance_required_coverage_cents"],
        50_000_000,
        "insurance_required_coverage_cents",
    )
    assert above["country_code"] == c.COUNTRY_PT
    a.assert_decimal_value(above["crime_index"], 30.00, "crime_index")
    a.assert_decimal_value(
        above["political_instability_index"], 30.00, "political_instability_index"
    )
    assert above["version"] == 3, "each accepted PATCH increments the same row once"


def test_verifying_an_already_verified_policy_is_rejected_from_both_outcomes(api, dep):
    """VERIFIED is terminal, so neither a repeat VERIFY nor a late REJECT lands.

    PRD §3.3: "Verification requires `status` to be `UNVERIFIED`; a second attempt on an already-decided policy yields `ERR_POLICY_INVALID_STATE`."

    Design: Corner/state_machines/verify_an_already_verified_policy_returns_policy_invalid_state
    """
    exec_row = fx.register_executive(api, dep)
    policy = fx.create_policy(
        api,
        dep,
        exec_row["id"],
        coverage_cents=50_000_000,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )
    first = fx.verify_policy(api, dep, policy["id"], "first pass")
    assert first["status"] == c.POLICY_VERIFIED
    assert first["version"] == 2

    fx.set_clock(api, "2026-08-02T00:00:00Z")

    repeat = api.verify_insurance_policy(
        policy["id"],
        f.policy_verify_payload(c.VERIFY_OUTCOME_VERIFY, "second pass"),
        dep.officer,
    )
    validate_error(repeat, e.ERR_POLICY_INVALID_STATE, 409)

    late_reject = api.verify_insurance_policy(
        policy["id"],
        f.policy_verify_payload(c.VERIFY_OUTCOME_REJECT, "late objection"),
        dep.officer,
    )
    validate_error(late_reject, e.ERR_POLICY_INVALID_STATE, 409)

    rows, _meta = validate_paginated(
        api.list_executive_insurance_policies(exec_row["id"], dep.officer)
    )
    stored = [row for row in rows if row["id"] == policy["id"]][0]
    assert stored["status"] == c.POLICY_VERIFIED
    assert stored["verified_at"] == "2026-08-01T00:00:00.000Z"
    assert stored["verification_note"] == "first pass"
    assert stored["version"] == 2, "a rejected transition performs no write"


def test_coverage_exactly_equal_to_the_requirement_lets_the_submission_through(api):
    """The coverage comparison is inclusive, so the exact floor is adequate cover.

    PRD §3.6: "Sixth, coverage adequacy: the policy's `coverage_cents` must be greater than or equal to the largest `insurance_required_coverage_cents` demanded by the destination ratings of any of the trip's legs, or the submission is rejected with `ERR_INSURANCE_COVERAGE_INSUFFICIENT`."

    Design: Corner/validations/coverage_exactly_equal_to_the_requirement_satisfies_the_insurance_rule
    """
    w = fx.bootstrap_world(api, coverage_cents=25_000_000)
    dep = w.dep
    a.assert_cents(
        w.rating["insurance_required_coverage_cents"],
        25_000_000,
        "insurance_required_coverage_cents",
    )
    a.assert_cents(w.policy["coverage_cents"], 25_000_000, "coverage_cents")

    trip = fx.create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        insurance_policy_id=w.policy_id,
        cost_allocation_method=c.ALLOCATION_PRORATA,
    )
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        arrive_at=c.TRIP_DEPART_AT,
        depart_at=c.TRIP_RETURN_AT,
    )
    fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY)

    submitted = validate_success(api.submit_trip_for_approval(trip["id"], dep.mgr))
    a.assert_trip_states(
        submitted, c.APPROVAL_PENDING_REVIEW, c.READINESS_ADVANCE_IN_PROGRESS
    )
    a.assert_cents(
        submitted["provisional_security_cost_cents"],
        0,
        "provisional_security_cost_cents",
    )
    assert submitted["check_in_interval_hours"] == 24
    assert submitted["next_check_in_due_at"] == "2026-09-11T00:00:00.000Z"

    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(
        executive, committed=0, spent=0, remaining=c.DEFAULT_ANNUAL_BUDGET_CENTS
    )


def test_the_null_policy_is_caught_before_the_coverage_comparison_runs(api):
    """A trip with no policy fails on verification; one cent short fails on coverage.

    PRD §3.6: "Fourth, insurance existence: `insurance_policy_id` must be non-null and the named policy's `status` must be `VERIFIED`, or the submission is rejected with `ERR_INSURANCE_NOT_VERIFIED` — this is the check that guarantees the two insurance rules below never have to reason about a null policy."

    Design: Corner/validations/insurance_coverage_rule_runs_only_after_the_verification_rule_established_a_policy
    """
    w = fx.bootstrap_world(api, coverage_cents=24_999_999)
    dep = w.dep
    assert w.policy["status"] == c.POLICY_VERIFIED

    trip_a = fx.create_trip(api, dep, w.exec_id, w.ra_id)
    leg_a = fx.add_leg(
        api, dep, trip_a["id"], arrive_at=c.TRIP_DEPART_AT, depart_at=c.TRIP_RETURN_AT
    )
    fx.record_advance(api, dep, leg_a["id"], c.ITEM_ROUTE_SURVEY)

    trip_b = fx.create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        insurance_policy_id=w.policy_id,
        depart_at="2026-09-20T00:00:00Z",
        return_at="2026-09-22T00:00:00Z",
    )
    leg_b = fx.add_leg(
        api,
        dep,
        trip_b["id"],
        arrive_at="2026-09-20T00:00:00Z",
        depart_at="2026-09-22T00:00:00Z",
    )
    fx.record_advance(api, dep, leg_b["id"], c.ITEM_ROUTE_SURVEY)

    validate_error(
        api.submit_trip_for_approval(trip_a["id"], dep.mgr),
        e.ERR_INSURANCE_NOT_VERIFIED,
        409,
    )
    validate_error(
        api.submit_trip_for_approval(trip_b["id"], dep.mgr),
        e.ERR_INSURANCE_COVERAGE_INSUFFICIENT,
        409,
    )

    for trip_id in (trip_a["id"], trip_b["id"]):
        row = fx.read_trip(api, dep, trip_id)
        a.assert_trip_states(row, c.APPROVAL_DRAFT)
    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(executive, committed=0, spent=0)


def test_an_excluded_destination_and_a_lapsing_window_share_one_error_id(api):
    """Both scope defects report the same id, and a window ending at return_at passes.

    PRD §3.6: "Fifth, insurance scope: no leg's `destination_country_code` may appear in the policy's `excluded_country_codes`, and the policy window must span the trip window, meaning `effective_from` at or before the trip's `depart_at` and `effective_to` at or after the trip's `return_at`; a failure of either is `ERR_INSURANCE_COUNTRY_EXCLUDED`."

    Design: Corner/errors/policy_excluding_the_destination_or_lapsing_before_the_return_is_rejected
    """
    dep = fx.bootstrap_department(api)
    exec_row = fx.register_executive(api, dep)
    fx.complete_residential_survey(api, dep, exec_row["id"])
    fx.publish_rating(api, dep)
    assessment = fx.approved_assessment(api, dep, exec_row["id"])

    excluding = fx.create_verified_policy(
        api,
        dep,
        exec_row["id"],
        coverage_cents=50_000_000,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
        excluded_country_codes=[c.COUNTRY_PT],
    )
    lapsing = fx.create_verified_policy(
        api,
        dep,
        exec_row["id"],
        coverage_cents=50_000_000,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-11T00:00:00Z",
    )
    to_the_instant = fx.create_verified_policy(
        api,
        dep,
        exec_row["id"],
        coverage_cents=50_000_000,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-12T00:00:00Z",
    )

    trips = {}
    for label, policy in (
        ("excluding", excluding),
        ("lapsing", lapsing),
        ("edge", to_the_instant),
    ):
        trip = fx.create_trip(
            api,
            dep,
            exec_row["id"],
            assessment["id"],
            insurance_policy_id=policy["id"],
        )
        leg = fx.add_leg(
            api,
            dep,
            trip["id"],
            arrive_at=c.TRIP_DEPART_AT,
            depart_at=c.TRIP_RETURN_AT,
        )
        fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY)
        trips[label] = trip["id"]

    validate_error(
        api.submit_trip_for_approval(trips["excluding"], dep.mgr),
        e.ERR_INSURANCE_COUNTRY_EXCLUDED,
        409,
    )
    validate_error(
        api.submit_trip_for_approval(trips["lapsing"], dep.mgr),
        e.ERR_INSURANCE_COUNTRY_EXCLUDED,
        409,
    )
    accepted = validate_success(
        api.submit_trip_for_approval(trips["edge"], dep.mgr)
    )
    a.assert_trip_states(accepted, c.APPROVAL_PENDING_REVIEW)

    for label in ("excluding", "lapsing"):
        row = fx.read_trip(api, dep, trips[label])
        a.assert_trip_states(row, c.APPROVAL_DRAFT, c.READINESS_ADVANCE_IN_PROGRESS)
    executive = fx.read_executive(api, dep, exec_row["id"])
    a.assert_budget_ledger(executive, committed=0, spent=0)


def test_leg_sequence_is_unique_per_trip_and_a_country_is_rated_once(api):
    """Two uniqueness keys the API never exposes as a path segment.

    PRD §3.4: "It carries `destination_country_code`, two uppercase letters that must resolve to a published destination rating, `arrive_at`, the inclusive UTC start of on-ground presence, and `depart_at`, its exclusive end, which must be strictly later than `arrive_at`."

    Design: Corner/errors/duplicate_leg_sequence_and_duplicate_country_rating_are_rejected
    """
    dep = fx.bootstrap_department(api)
    exec_row = fx.register_executive(api, dep)
    fx.complete_residential_survey(api, dep, exec_row["id"])
    fx.publish_rating(api, dep)
    assessment = fx.approved_assessment(api, dep, exec_row["id"])
    trip = fx.create_trip(api, dep, exec_row["id"], assessment["id"])
    first_leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        sequence_no=1,
        arrive_at=c.TRIP_DEPART_AT,
        depart_at="2026-09-11T00:00:00Z",
    )

    validate_error(
        api.create_trip_leg(
            trip["id"],
            f.trip_leg_payload(
                sequence_no=1,
                arrive_at="2026-09-11T00:00:00Z",
                depart_at=c.TRIP_RETURN_AT,
            ),
            dep.mgr,
        ),
        e.ERR_DUPLICATE_LEG_SEQUENCE,
        409,
    )
    validate_error(
        api.create_destination_rating(
            f.destination_rating_payload(
                country_code=c.COUNTRY_PT,
                crime_index=20.0,
                political_instability_index=18.0,
                medical_infrastructure_index=80.0,
                natural_hazard_index=22.0,
                advisory_effective_at="2026-07-15T00:00:00Z",
            ),
            dep.analyst,
        ),
        e.ERR_DESTINATION_RATING_EXISTS,
        409,
    )

    second_leg = validate_success(
        api.create_trip_leg(
            trip["id"],
            f.trip_leg_payload(
                sequence_no=2,
                arrive_at="2026-09-11T00:00:00Z",
                depart_at=c.TRIP_RETURN_AT,
            ),
            dep.mgr,
        ),
        201,
    )

    rating = validate_success(
        api.create_destination_rating(
            f.destination_rating_payload(country_code=c.COUNTRY_ES), dep.analyst
        ),
        201,
    )
    assert rating["country_code"] == c.COUNTRY_ES

    legs, meta = validate_paginated(api.list_trip_legs(trip["id"], dep.mgr))
    assert meta["total_count"] == 2
    assert [row["id"] for row in legs] == [first_leg["id"], second_leg["id"]]
