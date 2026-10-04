"""Compensating invariants: quantities a rejected operation must leave intact."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    LICENSING, STAFF,
    api_client, set_clock, create_licence_and_territory,
)


class TestLicenceFeeGateConservesPerUnitHelper:
    @pytest.fixture
    def two_vendor_licences(self):
        """A four-unit licence and a three-unit licence, both on vendor terms."""
        set_clock("2026-09-01T00:00:00Z")
        clearing, clearing_territory = create_licence_and_territory(
            territory_code="US-PLAINS", method="SITE", licensee_type="VENDOR",
            licensee_name="Plains Vendor", sales_unit_count=4, expected_users=5,
            activate=False,
        )
        failing, failing_territory = create_licence_and_territory(
            territory_code="US-ROCKIES", method="SITE", licensee_type="VENDOR",
            licensee_name="Rockies Vendor", sales_unit_count=3, expected_users=5,
            activate=False,
        )
        return {"clearing": clearing, "failing": failing}

    def test_below_minimum_licence_cannot_be_activated(self, api, two_vendor_licences):
        """PRD §3.9: "activating a licence whose gate is BELOW_MINIMUM because its
        sales unit count is under 4 is rejected with ERR_LICENSE_FEE_BELOW_MINIMUM
        at 422."

        Design: Difficulty/compensating_invariant/license_fee_gate_conserves_per_unit_helper
        """
        failing = two_vendor_licences["failing"]
        response = api.activate_licensing_agreement(failing["id"], LICENSING)
        validate_error(response, ApiErrorId.ERR_LICENSE_FEE_BELOW_MINIMUM, expected_status=422)

    def test_rejected_activation_leaves_the_licence_in_draft(self, api, two_vendor_licences):
        """PRD §3.9: "The licence lifecycle begins at DRAFT. Activation moves it to ACTIVE."
        PRD §3.9: "A licence must clear a fee threshold before it can activate."

        Design: Difficulty/compensating_invariant/license_fee_gate_conserves_per_unit_helper
        """
        failing = two_vendor_licences["failing"]
        api.activate_licensing_agreement(failing["id"], LICENSING)
        licence = validate_success(api.get_licensing_agreement(failing["id"], LICENSING))
        assert licence["agreement_status"] == "DRAFT"
        assert licence["fee_threshold_gate_status"] == "BELOW_MINIMUM"

    def test_per_unit_helper_prices_both_licences_from_the_same_rate(
        self, api, two_vendor_licences,
    ):
        """PRD §3.9: "for up to and including 500,000 units the fee is the unit count
        multiplied by 0.90, rounded half up to a whole cent".

        Design: Difficulty/compensating_invariant/license_fee_gate_conserves_per_unit_helper
        """
        clearing = two_vendor_licences["clearing"]
        failing = two_vendor_licences["failing"]
        api.activate_licensing_agreement(failing["id"], LICENSING)
        clearing_row = validate_success(api.get_licensing_agreement(clearing["id"], LICENSING))
        failing_row = validate_success(api.get_licensing_agreement(failing["id"], LICENSING))
        assert clearing_row["royalty_fee_cents"] == 4
        assert failing_row["royalty_fee_cents"] == 3