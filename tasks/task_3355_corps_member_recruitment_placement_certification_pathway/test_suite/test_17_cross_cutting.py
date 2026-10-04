"""Cross-cutting layers: version discipline, reconciliation and immediacy."""
import pytest

from test_helpers import validate_success

from test_helpers.fixtures import (
    COMPLETER,
    PLACEMENT_COORDINATOR,
    complete_institute,
    complete_milestone,
    create_matched_placement,
    get_district,
    get_member,
    milestones_by_type,
    record_practice_hours,
    setup_member_scenario,
    start_milestone,
)


class TestVersionDiscipline:
    def test_every_declared_mutation_advances_the_member_version_by_one(self, api):
        """PRD §2.5: "The `version` is an integer that starts at 1 and increments by exactly 1 on each mutation of the resource."
        PRD §2.8: "a single acceptance advances the member's `version` once per milestone it creates"
        PRD §2.7: "Creating a Placement through `POST /corps/placements` requires a non-optional `expected_corps_member_version` field carrying the client's last observed `version` of the CorpsMember being placed."

        Design: Corner/cross_cutting_layers/occ_version_increments_on_every_declared_mutation
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        assert scenario["member"]["version"] == 5, (
            "1 at synthesis plus one advance per synthesized milestone"
        )

        after_practice = record_practice_hours(member_id, 240)
        assert after_practice["version"] == 6

        after_institute = complete_institute(member_id)
        assert after_institute["version"] == 7

        observed = get_member(member_id)["version"]
        assert observed == 7
        placement = create_matched_placement(member_id, scenario["school"]["id"])
        assert placement["corps_member_id"] == member_id
        assert get_member(member_id)["version"] == 8, (
            "the placement create consumed the observed 7 and advanced the version once"
        )


class TestDerivedFieldReconciliation:
    def test_completing_coursework_reconciles_two_derived_fields(self, api):
        """PRD §3.5: "Both completion edges stamp `completed_at` with the current logical clock and record the officer in `completed_by_user_id`, and both recompute the member's `readiness_score` and `coursework_hours_completed`."
        PRD §2.8: "A conforming implementation must treat every one of these as live state that is refreshed by the transitions listed in §3, not as a value written once."

        Before the completion readiness is 30.00 with no coursework hours;
        the 60-hour COURSEWORK milestone moves the coursework ratio to 1.0,
        lifting the subtotal to 50.00 and the QUALIFIED credit to 1.5.

        Design: Corner/cross_cutting_layers/derived_field_reconciled_when_milestone_completes
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 240)

        before = get_member(member_id)
        assert before["coursework_hours_completed"] == 0
        assert before["readiness_score"] == pytest.approx(30.00, abs=0.01)

        milestone_id = milestones_by_type(member_id)["COURSEWORK"]["id"]
        start_milestone(milestone_id)
        validate_success(api.complete_certification_milestone(milestone_id, COMPLETER))

        after = get_member(member_id)
        assert after["coursework_hours_completed"] == 60
        assert after["readiness_score"] == pytest.approx(51.50, abs=0.01), (
            "subtotal 50.00 plus the QUALIFIED credit of 1.5"
        )


class TestImmediateConsistency:
    def test_confirmation_response_already_carries_reconciled_values(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.7: "It then runs its cascade: the district's `committed_placement_count` rises by 1, which drives a recompute of the district's `invoice_amount_cents` and of the placement's own `placement_fee_cents`"

        Design: Corner/consistency_model/immediate_visibility_inside_the_mutating_request
        """
        scenario = setup_member_scenario()
        placement = create_matched_placement(scenario["member_id"], scenario["school"]["id"])

        confirmed = validate_success(
            api.confirm_placement(placement["id"], PLACEMENT_COORDINATOR)
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["placement_fee_cents"] == 402500, (
            "the mutating response itself carries the recomputed fee"
        )

        district = get_district(scenario["district"]["id"])
        assert district["committed_placement_count"] == 1
        assert district["invoice_amount_cents"] == 710000, (
            "no wait or re-read is needed; the cascade is already visible"
        )
