"""Dual-variant calculations: quantities that the same input can resolve two ways."""
import pytest

from test_helpers import (
    validate_success, ApiErrorId,
    assert_credited_approval, assert_code_value_invariants,
    assert_release_cycle_pool_invariants,
    CHAIR, STAFF, LICENSING,
    api_client, set_clock, create_society, create_applicant, create_meeting,
    create_cycle, create_change, submit_into_cycle, post_change, docket,
    open_meeting, setup_panel_ready_change, setup_gpci_code_value,
    setup_release_cycle_only,
    GPCI_WORK, GPCI_PE, GPCI_MP, CONVERSION_FACTOR,
)


@pytest.fixture
def cea_panel_ready():
    """Sponsored TIER_I single-organ-system high-volume addition at PANEL_REVIEW."""
    return setup_panel_ready_change(
        change_code="00001", society_name="Alpha Society", society_code="ALP",
        tier="TIER_I", volume=8000, organ_systems=1,
    )


class TestChangeCreditDualScopes:
    def test_approved_tier_one_single_organ_high_volume_awards_full_credit(
        self, api, cea_panel_ready,
    ):
        """PRD §3.5: "A change whose determination is APPROVED begins from a base
        award of 2.0 credits, and then: if the code applies to a single organ system
        — that is, if organ_system_count is 1 — 0.5 credits are added; if the
        change's procedure_volume_threshold is greater than 0 and no greater than
        10000, 0.5 credits are added; and if the change's clinical_evidence_tier is
        TIER_I, 1.0 credit is added. The resulting total is rounded half up to 2
        decimal places and stored in cea_credits."

        Design: Difficulty/dual_variant_calc/change_cea_credit_dual_credit_scopes
        """
        change = cea_panel_ready["change"]
        response = api.determine_code_change(
            change["id"],
            {"determination": "APPROVED", "determination_basis": "Evidence supports the addition"},
            CHAIR,
        )
        data = validate_success(response)
        # 2.0 base + 0.5 single organ system + 0.5 volume within the low band + 1.0 TIER_I
        assert_credited_approval(data, 4.0)

    def test_approved_change_credits_flow_into_sponsoring_society_balance(
        self, api, cea_panel_ready,
    ):
        """PRD §3.5: "The society's cea_credit_balance is then the sum of cea_credits
        across every change naming it whose determination is APPROVED".

        Design: Difficulty/dual_variant_calc/change_cea_credit_dual_credit_scopes
        """
        change = cea_panel_ready["change"]
        society = cea_panel_ready["society"]
        validate_success(api.determine_code_change(
            change["id"],
            {"determination": "APPROVED", "determination_basis": "Evidence supports the addition"},
            CHAIR,
        ))
        refreshed = validate_success(api.get_specialty_society(society["id"], STAFF))
        change_row = validate_success(api.get_code_change(change["id"], STAFF))
        assert refreshed["cea_credit_balance"] == change_row["cea_credits"] == 4.0


class TestCodeValueRoundingDualVariant:
    def test_value_record_publishes_both_rounding_orders_for_identical_inputs(self, api):
        """PRD §2.9: "Under AGGREGATE_ROUNDING the facility payment is produced by
        summing the adjusted RVU components first and rounding the resulting dollar
        product once. Under COMPONENT_ROUNDING each adjusted component's dollar
        product is rounded individually and the three rounded figures are then
        summed."

        Design: Difficulty/dual_variant_calc/value_record_component_rounding_dual_variant
        """
        bundle = setup_gpci_code_value(code="00002", rounding_variant="AGGREGATE_ROUNDING",
                                       society_code="BET")
        value = validate_success(api.get_code_value(bundle["value"]["id"], LICENSING))
        assert value["aggregate_round_total_cents"] == 18173
        assert value["component_round_total_cents"] == 18174

    def test_rounding_variant_decides_which_total_publishes_as_facility_payment(self, api):
        """PRD §2.9: "The facility payment stored on the row is the component-rounded
        total when rounding_variant is COMPONENT_ROUNDING and the aggregate-rounded
        total when it is AGGREGATE_ROUNDING".

        Design: Difficulty/dual_variant_calc/value_record_component_rounding_dual_variant
        """
        aggregate_bundle = setup_gpci_code_value(code="00002",
                                                 rounding_variant="AGGREGATE_ROUNDING",
                                                 society_code="BET")
        component_bundle = setup_gpci_code_value(code="00003",
                                                 rounding_variant="COMPONENT_ROUNDING",
                                                 society_code="DEL")
        aggregate_value = validate_success(
            api.get_code_value(aggregate_bundle["value"]["id"], LICENSING))
        component_value = validate_success(
            api.get_code_value(component_bundle["value"]["id"], LICENSING))
        assert_code_value_invariants(aggregate_value)
        assert_code_value_invariants(component_value)
        assert aggregate_value["facility_payment_cents"] == 18173
        assert component_value["facility_payment_cents"] == 18174


class TestReleaseCyclePoolDualDerivation:
    def test_default_per_bucket_floors_leave_forty_discretionary_and_clear_gate(self, api):
        """PRD §2.11: "By default each bucket is floored to a whole descriptor before
        it is subtracted, and under that default a capacity of 200 yields a
        discretionary pool of 40."
        PRD §3.6: "The return requires submission_count to be exactly 0, and it
        recomputes discretionary_codes before moving cycle_status back to PLANNING."

        Design: Difficulty/dual_variant_calc/release_cycle_pool_dual_derivation
        """
        bundle = setup_release_cycle_only(capacity=192, open_cycle=True)
        cycle = validate_success(api.return_release_cycle(
            bundle["cycle"]["id"], {"reason": "Recompute the descriptor pools"}, STAFF))
        assert cycle["editorial_reserved_codes"] == 76
        assert cycle["additions_pool_codes"] == 67
        assert cycle["catiii_pool_codes"] == 9
        assert cycle["discretionary_codes"] == 40
        assert cycle["budget_gate_status"] == "OPEN"

    def test_single_floor_variant_yields_one_fewer_code_and_trips_the_gate(self, api):
        """PRD §2.11: "When a cycle instead sets single_floor_budgeting, the three
        unbounded percentages are summed first and the sum is floored once; that
        variant can yield a discretionary pool one descriptor lower than the default
        for the same capacity, and can therefore trip a gate the default would clear."
        PRD §3.6: "under single_floor_budgeting the same capacity yields only 39 and
        trips the gate."

        Design: Difficulty/dual_variant_calc/release_cycle_pool_dual_derivation
        """
        default_bundle = setup_release_cycle_only(capacity=192, year=2027,
                                                  meeting_code="APR2027",
                                                  meeting_month="APRIL",
                                                  open_cycle=True)
        single_floor_bundle = setup_release_cycle_only(
            capacity=192, year=2028, single_floor_budgeting=True,
            meeting_code="AUG2028", meeting_month="AUGUST",
            starts_at="2028-08-14T14:00:00Z", ends_at="2028-08-14T23:00:00Z",
            open_cycle=True,
        )
        default_cycle = validate_success(api.return_release_cycle(
            default_bundle["cycle"]["id"], {"reason": "Recompute"}, STAFF))
        single_floor_cycle = validate_success(api.return_release_cycle(
            single_floor_bundle["cycle"]["id"], {"reason": "Recompute"}, STAFF))
        assert_release_cycle_pool_invariants(default_cycle)
        assert default_cycle["discretionary_codes"] == 40
        assert single_floor_cycle["discretionary_codes"] == 39
        assert single_floor_cycle["discretionary_codes"] == \
            default_cycle["discretionary_codes"] - 1
        assert single_floor_cycle["budget_gate_status"] == "EXHAUSTED"
        assert default_cycle["budget_gate_status"] == "OPEN"