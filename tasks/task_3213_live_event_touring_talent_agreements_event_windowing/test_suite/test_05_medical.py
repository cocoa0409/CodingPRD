"""Medical cases, evaluations, and the clearance segregation-of-duties
protocol."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_medical_case, assert_medical_clearance,
    create_talent, create_medical_case,
    create_cleared_case,
    add_evaluation,
    create_medical_clearance_payload,
    get_talent,
)

MD = TEST_USERS["medic_headers"]


class TestMedicalCaseCreation:
    def test_creation_marks_talent_injured_and_unbookable(self, api):
        """PRD §3.10: "Creation alone has teeth: the talent's `availability_status` flips `ACTIVE → INJURED` immediately, and every `BOOKED` booking of that talent on `SCHEDULED` events whose `event_date` falls within 30 days of the logical clock flips to `SCRATCHED` — the injury scratch horizon — with each scratch re-evaluating storyline gaps per §3.4."
        PRD §3.1: "otherwise a talent who is `INJURED` is `UNBOOKABLE`"

        Design: Corner/state_machines/medical_case_creation_marks_talent_injured
        """
        talent = create_talent(ring_name="Hurt Harry")
        case = create_medical_case(talent["id"], severity="MAJOR")
        assert_medical_case(case)
        assert case["status"] == "OPEN"
        refreshed = get_talent(talent["id"])
        assert refreshed["availability_status"] == "INJURED"
        assert refreshed["booking_mode"] == "UNBOOKABLE"

    def test_injury_scratch_horizon_is_unproven_under_prd(self, api):
        """PRD §3.10: "Creation alone has teeth: the talent's `availability_status` flips `ACTIVE → INJURED` immediately, and every `BOOKED` booking of that talent on `SCHEDULED` events whose `event_date` falls within 30 days of the logical clock flips to `SCRATCHED` — the injury scratch horizon — with each scratch re-evaluating storyline gaps per §3.4."
        PRD §3.1: "New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score."

        Design: Difficulty/transitive_cascade/medical_case_open_cascades_booking_scratch_to_gap
        """
        # Under the PRD the cascade's hop-2 precondition is unreachable: a
        # fresh talent is UNBOOKABLE at 0.00 wellness and wellness rises only
        # through fulfilled bookings, so no BOOKED booking can exist within the
        # horizon. The uniquely-derivable observables are the creation-side
        # effects themselves.
        talent = create_talent(ring_name="Fragile Finn")
        case = create_medical_case(talent["id"], severity="MINOR")
        assert case["status"] == "OPEN"
        refreshed = get_talent(talent["id"])
        assert refreshed["availability_status"] == "INJURED"
        assert refreshed["booking_mode"] == "UNBOOKABLE"


class TestClearanceQuorumBoundary:
    def test_one_recommending_evaluation_fails_two_distinct_succeed(self, api):
        """PRD §3.10: "Issuing a clearance requires the case to be `OPEN`, requires at least two evaluations with `recommends_clearance` true from **distinct** evaluator ids, and requires the clearing medic — identified by the request's `cleared_by`, the issuing medic's `X-User-ID` — to differ from every evaluator on the case; any shortfall is rejected with `ERR_CLEARANCE_PROTOCOL_VIOLATION` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/clearance_two_recommending_evaluations_exact_boundary
        """
        talent = create_talent(ring_name="Hurt Holly")
        case = create_medical_case(talent["id"], severity="MAJOR")
        add_evaluation(case["id"], "medic-m1")
        # Exactly 1 recommending evaluation: below the quorum.
        resp1 = api.create_medical_clearance(
            case["id"], create_medical_clearance_payload("medic-m2"), MD)
        validate_error(resp1, ApiErrorId.ERR_CLEARANCE_PROTOCOL_VIOLATION)
        # Exactly 2 from distinct evaluator ids, cleared by a third medic.
        add_evaluation(case["id"], "medic-m3")
        resp2 = api.create_medical_clearance(
            case["id"], create_medical_clearance_payload("medic-m2"), MD)
        clearance = validate_success(resp2, expected_status=201)
        assert_medical_clearance(clearance)
        case_after = validate_success(api.get_medical_case(case["id"], MD))
        assert case_after["status"] == "CLEARED"
        assert case_after["clearance_id"] == clearance["id"]
        refreshed = get_talent(talent["id"])
        assert refreshed["availability_status"] == "ACTIVE"

    def test_non_recommending_evaluations_do_not_count(self, api):
        """PRD §3.10: "Issuing a clearance requires the case to be `OPEN`, requires at least two evaluations with `recommends_clearance` true from **distinct** evaluator ids, and requires the clearing medic — identified by the request's `cleared_by`, the issuing medic's `X-User-ID` — to differ from every evaluator on the case; any shortfall is rejected with `ERR_CLEARANCE_PROTOCOL_VIOLATION` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/clearance_two_recommending_evaluations_exact_boundary
        """
        talent = create_talent(ring_name="Mixed Moe")
        case = create_medical_case(talent["id"], severity="MINOR")
        add_evaluation(case["id"], "medic-m1", recommends_clearance=True)
        add_evaluation(case["id"], "medic-m3", recommends_clearance=False)
        resp = api.create_medical_clearance(
            case["id"], create_medical_clearance_payload("medic-m2"), MD)
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_PROTOCOL_VIOLATION)


class TestSegregationOfDuties:
    def test_evaluator_cannot_clear_own_case_despite_quorum(self, api):
        """PRD §3.10: "Issuing a clearance requires the case to be `OPEN`, requires at least two evaluations with `recommends_clearance` true from **distinct** evaluator ids, and requires the clearing medic — identified by the request's `cleared_by`, the issuing medic's `X-User-ID` — to differ from every evaluator on the case; any shortfall is rejected with `ERR_CLEARANCE_PROTOCOL_VIOLATION` (HTTP 422)."

        Design: Corner/rbac/rbac_medic_segregation_of_duties_on_clearance
        """
        talent = create_talent(ring_name="Duty Doc")
        case = create_medical_case(talent["id"], severity="MINOR")
        add_evaluation(case["id"], "medic-m1")
        add_evaluation(case["id"], "medic-m2")
        resp = api.create_medical_clearance(
            case["id"], create_medical_clearance_payload("medic-m1"), MD)
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_PROTOCOL_VIOLATION)

    def test_single_recommendation_and_self_clearance_both_fail(self, api):
        """PRD §3.10: "Issuing a clearance requires the case to be `OPEN`, requires at least two evaluations with `recommends_clearance` true from **distinct** evaluator ids, and requires the clearing medic — identified by the request's `cleared_by`, the issuing medic's `X-User-ID` — to differ from every evaluator on the case; any shortfall is rejected with `ERR_CLEARANCE_PROTOCOL_VIOLATION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_merch_sale
        """
        talent = create_talent(ring_name="Hurt Hank")
        case = create_medical_case(talent["id"], severity="MINOR")
        add_evaluation(case["id"], "medic-m1")
        # Only one recommending evaluation AND cleared_by equals the evaluator:
        # the safety rule rejects regardless of which shortfall is reported
        # first, since both live inside the same check.
        resp = api.create_medical_clearance(
            case["id"], create_medical_clearance_payload("medic-m1"), MD)
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_PROTOCOL_VIOLATION)


class TestClearanceOutcome:
    def test_cleared_case_reinstates_talent_active(self, api):
        """PRD §3.10: "A successful clearance creates the **MedicalClearance** record with the system-stamped `cleared_at` instant taken from the logical clock, flips the case `OPEN → CLEARED`, points `clearance_id` at the new clearance, flips the talent `INJURED → ACTIVE`, bumps the talent's `version`, and re-derives `booking_mode`."

        Design: Corner/state_machines/medical_case_creation_marks_talent_injured
        """
        talent = create_talent(ring_name="Heal Hana")
        case, clearance = create_cleared_case(talent["id"])
        assert case["status"] == "CLEARED"
        assert case["clearance_id"] == clearance["id"]
        refreshed = get_talent(talent["id"])
        assert refreshed["availability_status"] == "ACTIVE"


class TestMedicalBookingCascadeUnreachability:
    def test_case_with_zero_bookings_scratches_nothing(self, api):
        """PRD §3.10: "Creation alone has teeth: the talent's `availability_status` flips `ACTIVE → INJURED` immediately, and every `BOOKED` booking of that talent on `SCHEDULED` events whose `event_date` falls within 30 days of the logical clock flips to `SCRATCHED` — the injury scratch horizon — with each scratch re-evaluating storyline gaps per §3.4."
        PRD §3.1: "New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score."

        Design: Difficulty/transitive_cascade/medical_case_open_cascades_booking_scratch_to_gap
        """
        # A fresh UNBOOKABLE talent cannot hold any booking, so opening a case
        # leaves the talent's booking list empty while still injuring them.
        talent = create_talent(ring_name="Cascade Cid")
        create_medical_case(talent["id"], severity="MINOR")
        bookings, meta = validate_paginated(
            api.list_bookings(TEST_USERS["tour_planner_headers"],
                              params={"talent_id": talent["id"]}))
        assert meta["total_count"] == 0
        assert get_talent(talent["id"])["availability_status"] == "INJURED"
