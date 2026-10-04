"""Accreditation: dual-variant UCAP calculation, approval cascade,
uniqueness, and state legality (PRD §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_accreditation,
    create_accreditation,
    create_owner,
    create_resource,
    get_success_data,
    setup_delivery_year_with_forecast,
    validate_error,
)

ADMIN = TEST_USERS["market_admin_headers"]


def _setup_two_resources():
    dy, zone, forecast = setup_delivery_year_with_forecast()
    owner = create_owner()
    r1 = create_resource(owner["id"], zone["id"], nameplate_mw=100.0)
    r2 = create_resource(owner["id"], zone["id"], nameplate_mw=100.0)
    return dy, zone, owner, r1, r2


class TestDualVariantAccreditation:
    def test_class_avg_variant_pins_factor_flat(self, api):
        """PRD §3.2: "Under the class-average variant, the factor is simply
        the `class_avg_factor`; the outage rate and sample size play no role."
        PRD §3.2: "Either way, the factor is capped at 1.0 and rounded to 4
        decimal places round half up, and the accredited `ucap_mw` is the
        nameplate megawatts times the factor, rounded to 3 decimal places round
        half up."

        Design: Difficulty/dual_variant_calc/accreditation_class_avg_vs_unit_specific_same_nameplate
        """
        dy, zone, owner, r1, r2 = _setup_two_resources()
        acc1 = create_accreditation(
            r1["id"], owner["id"], dy["id"], method="CLASS_AVG",
            class_avg_factor=0.85, forced_outage_rate=0.10,
            scarcity_hours_sampled=50,
        )
        approved = approve_accreditation(acc1["id"])
        assert approved["status"] == "EFFECTIVE"
        assert approved["accreditation_factor"] == pytest.approx(0.85, abs=1e-9)
        assert approved["ucap_mw"] == pytest.approx(85.0, abs=1e-9)
        resource = get_success_data(api.get_resource(r1["id"], ADMIN))
        assert resource["accredited_ucap_mw"] == pytest.approx(85.0, abs=1e-9)

    def test_unit_specific_variant_derates_by_outage_and_sample(self, api):
        """PRD §3.2: "Under the unit-specific variant, the unit's marginal ELCC
        is derated twice: the `unit_elcc_factor` is multiplied by an outage
        derate equal to one minus the unit's `forced_outage_rate`, divided by
        one minus the pool-wide average forced outage rate from the `LOCKED`
        forecast of that delivery year (or, while the year is still `DRAFT`,
        from its highest-revision `DRAFT` forecast), and then multiplied by a
        sample confidence equal to the lesser of 1.0 and the scarcity hours
        sampled divided by 100 — a full sample being 100 hours."

        Design: Difficulty/dual_variant_calc/accreditation_class_avg_vs_unit_specific_same_nameplate
        """
        # Forecast here uses pool_wide_avg_eford 0.05 (fixture default is 0.04,
        # so this test builds its own delivery year).
        dy, zone, forecast = setup_delivery_year_with_forecast(
            pool_wide_avg_eford=0.05,
        )
        owner = create_owner()
        r1 = create_resource(owner["id"], zone["id"], nameplate_mw=100.0)
        r2 = create_resource(owner["id"], zone["id"], nameplate_mw=100.0)
        acc_avg = create_accreditation(
            r1["id"], owner["id"], dy["id"], method="CLASS_AVG",
            class_avg_factor=0.85, forced_outage_rate=0.10,
            scarcity_hours_sampled=50,
        )
        acc_unit = create_accreditation(
            r2["id"], owner["id"], dy["id"], method="UNIT_SPECIFIC",
            unit_elcc_factor=0.85, forced_outage_rate=0.10,
            scarcity_hours_sampled=50,
        )
        approved_avg = approve_accreditation(acc_avg["id"])
        approved_unit = approve_accreditation(acc_unit["id"])

        # UNIT_SPECIFIC: 0.85 * (0.9 / 0.95) * 0.5 = 0.402631... -> 0.4026
        assert approved_unit["accreditation_factor"] == pytest.approx(0.4026, abs=1e-9)
        assert approved_unit["ucap_mw"] == pytest.approx(40.26, abs=1e-9)
        resource = get_success_data(api.get_resource(r2["id"], ADMIN))
        assert resource["accredited_ucap_mw"] == pytest.approx(40.26, abs=1e-9)
        # Same nameplate and same 0.85 input factor, different variant ->
        # different UCAP.
        assert approved_avg["ucap_mw"] == pytest.approx(85.0, abs=1e-9)
        assert approved_unit["ucap_mw"] != approved_avg["ucap_mw"]


class TestClassAvgIgnoresOutageInputs:
    def test_identical_factor_yields_identical_ucap(self, api):
        """PRD §3.2: "Under the class-average variant, the factor is simply the
        `class_avg_factor`; the outage rate and sample size play no role."

        Design: Corner/calculations/accreditation_class_avg_ignores_outage_inputs
        """
        dy, zone, owner, r1, r2 = _setup_two_resources()
        acc1 = create_accreditation(
            r1["id"], owner["id"], dy["id"], method="CLASS_AVG",
            class_avg_factor=0.9, forced_outage_rate=0.02,
            scarcity_hours_sampled=200,
        )
        acc2 = create_accreditation(
            r2["id"], owner["id"], dy["id"], method="CLASS_AVG",
            class_avg_factor=0.9, forced_outage_rate=0.40,
            scarcity_hours_sampled=3,
        )
        a1 = approve_accreditation(acc1["id"])
        a2 = approve_accreditation(acc2["id"])
        assert a1["ucap_mw"] == pytest.approx(90.0, abs=1e-9)
        assert a2["ucap_mw"] == pytest.approx(90.0, abs=1e-9)
        assert a1["accreditation_factor"] == a2["accreditation_factor"]


class TestApprovalCascade:
    def test_approval_promotes_resource_to_accredited(self, api):
        """PRD §3.2: "Approval cascades: the resource moves `REGISTERED` →
        `ACCREDITED`, its `accredited_ucap_mw` takes the computed `ucap_mw`"

        Design: Difficulty/transitive_cascade/accreditation_approval_two_hop_resource_promotion
        """
        dy, zone, forecast = setup_delivery_year_with_forecast()
        owner = create_owner()
        resource = create_resource(owner["id"], zone["id"], nameplate_mw=100.0)
        acc = create_accreditation(resource["id"], owner["id"], dy["id"],
                                   class_avg_factor=0.85)
        approve_accreditation(acc["id"])
        resource_after = get_success_data(api.get_resource(resource["id"], ADMIN))
        assert resource_after["status"] == "ACCREDITED"

    def test_approval_writes_accredited_ucap_on_resource(self, api):
        """PRD §3.2: "Approval cascades: the resource moves `REGISTERED` →
        `ACCREDITED`, its `accredited_ucap_mw` takes the computed `ucap_mw`"

        Design: Difficulty/transitive_cascade/accreditation_approval_two_hop_resource_promotion
        """
        dy, zone, forecast = setup_delivery_year_with_forecast()
        owner = create_owner()
        resource = create_resource(owner["id"], zone["id"], nameplate_mw=100.0)
        acc = create_accreditation(resource["id"], owner["id"], dy["id"],
                                   class_avg_factor=0.85)
        approved = approve_accreditation(acc["id"])
        assert approved["status"] == "EFFECTIVE"
        assert approved["ucap_mw"] == pytest.approx(85.0, abs=1e-9)
        resource_after = get_success_data(api.get_resource(resource["id"], ADMIN))
        assert resource_after["accredited_ucap_mw"] == pytest.approx(85.0, abs=1e-9)


class TestAccreditationStateLegality:
    def test_approve_of_rejected_accreditation_rejected(self, api):
        """PRD §2.6: "State legality — the requested transition must exist from
        the target resource's current state; failure yields
        `ERR_INVALID_STATE`." PRD §3.2: "Rejection instead moves the
        accreditation `PENDING_REVIEW` → `REJECTED` with no further effect."

        Design: Corner/state_machines/accreditation_approve_initial_state_pending_review
        """
        dy, zone, forecast = setup_delivery_year_with_forecast()
        owner = create_owner()
        resource = create_resource(owner["id"], zone["id"], nameplate_mw=100.0)
        acc = create_accreditation(resource["id"], owner["id"], dy["id"],
                                   class_avg_factor=0.85)
        get_success_data(api.reject_accreditation(acc["id"], ADMIN))
        resp = api.approve_accreditation(acc["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        acc_after = get_success_data(api.get_accreditation(acc["id"], ADMIN))
        assert acc_after["status"] == "REJECTED"
        resource_after = get_success_data(api.get_resource(resource["id"], ADMIN))
        assert resource_after["status"] == "REGISTERED"

    def test_second_effective_accreditation_conflicts(self, api):
        """PRD §3.2: "no other `EFFECTIVE` accreditation exists for the same
        resource-and-delivery-year pair — a second effective accreditation is
        refused with `ERR_ACCREDITATION_CONFLICT`."

        Design: Corner/validations/err_accreditation_conflict_second_effective
        """
        dy, zone, forecast = setup_delivery_year_with_forecast()
        owner = create_owner()
        resource = create_resource(owner["id"], zone["id"], nameplate_mw=100.0)
        acc1 = create_accreditation(resource["id"], owner["id"], dy["id"],
                                    class_avg_factor=0.85)
        approve_accreditation(acc1["id"])
        acc2 = create_accreditation(resource["id"], owner["id"], dy["id"],
                                    class_avg_factor=0.80)
        resp = api.approve_accreditation(acc2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCREDITATION_CONFLICT, expected_status=409)
        acc2_after = get_success_data(api.get_accreditation(acc2["id"], ADMIN))
        assert acc2_after["status"] == "PENDING_REVIEW"
