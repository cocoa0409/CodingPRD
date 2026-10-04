"""Transitive cascades: one request mutating a chain of dependent records."""
import pytest

from test_helpers import (
    validate_success,
    assert_credited_approval,
    CHAIR, STAFF, LICENSING, TEST_USERS,
    api_client, set_clock, create_society, create_applicant, create_meeting,
    create_cycle, create_change, submit_into_cycle, post_change, docket,
    open_meeting, setup_panel_ready_change, create_licence_and_territory,
)


class TestDeterminationToCreditToSocietyBalance:
    def test_determination_sets_the_change_credit_award(self, api):
        """PRD §3.5: "A change whose determination is APPROVED begins from a base
        award of 2.0 credits, and then: if the code applies to a single organ system
        — that is, if organ_system_count is 1 — 0.5 credits are added".

        Design: Difficulty/transitive_cascade/determination_to_cea_to_society_balance
        """
        bundle = setup_panel_ready_change(
            change_code="00006", society_name="Zeta Society", society_code="ZET",
            tier="TIER_II", volume=4000, organ_systems=1,
            meeting_code="FEB2028", meeting_month="FEBRUARY",
        )
        change = validate_success(api.determine_code_change(
            bundle["change"]["id"],
            {"determination": "APPROVED",
             "determination_basis": "Descriptor is distinct and evidence is sufficient"},
            CHAIR,
        ))
        # 2.0 base + 0.5 single organ system + 0.5 volume within the low band
        assert_credited_approval(change, 3.0)

    def test_society_balance_tracks_the_change_credit_award(self, api):
        """PRD §3.5: "recomputes the change's cea_credits, recomputes the sponsoring
        society's cea_credit_balance when a society is named".
        PRD §3.1: "The derived cea_credit_balance on a society is the sum of
        cea_credits across every CodeChange row that names it as sponsoring society
        and whose determination has reached APPROVED".

        Design: Difficulty/transitive_cascade/determination_to_cea_to_society_balance
        """
        bundle = setup_panel_ready_change(
            change_code="00006", society_name="Zeta Society", society_code="ZET",
            tier="TIER_II", volume=4000, organ_systems=1,
            meeting_code="FEB2028", meeting_month="FEBRUARY",
        )
        validate_success(api.determine_code_change(
            bundle["change"]["id"],
            {"determination": "APPROVED",
             "determination_basis": "Descriptor is distinct and evidence is sufficient"},
            CHAIR,
        ))
        society = validate_success(api.get_specialty_society(bundle["society"]["id"], STAFF))
        change = validate_success(api.get_code_change(bundle["change"]["id"], STAFF))
        assert change["cea_credits"] == 3.0
        assert society["cea_credit_balance"] == 3.0


class TestLicenceTerminationCascade:
    @pytest.fixture
    def released_delivery(self, api):
        """An active licence bound to a territory, holding one RELEASED delivery."""
        set_clock("2026-09-01T00:00:00Z")
        licence, territory = create_licence_and_territory(
            territory_code="US-SOUTH", method="SITE", licensee_type="PROVIDER",
            licensee_name="South Clinic", sales_unit_count=10, expected_users=25,
            activate=True,
        )
        licensee_headers = TEST_USERS["licensee_headers"]
        order = validate_success(api.create_content_delivery_order(
            {
                "license_id": licence["id"],
                "distribution_channel": "SITE",
                "format_params": {"electronic_format": "NONE", "media": "NONE",
                                  "version_qualifier": "2026.1",
                                  "payer_identifier_qualifier": "NONE"},
                "payer_identifier": "PLACEHOLDER",
                "expected_license_version": licence["version"],
            },
            TEST_USERS["licensee_headers"],
        ), 201)
        validate_success(api.mark_delivery_ready(order["id"], {"media": "NONE"}, STAFF))
        released = validate_success(api.release_delivery(order["id"], STAFF))
        return {"licence": licence, "territory": territory, "order": released}

    def test_termination_withdraws_the_released_delivery_order(self, api, released_delivery):
        """PRD §3.9: "Termination cascades broadly: every ContentDeliveryOrder carrying
        this licence with delivery_status RELEASED is set to WITHDRAWN".

        Design: Difficulty/transitive_cascade/licence_termination_to_delivery_to_scope
        """
        licence = released_delivery["licence"]
        validate_success(api.terminate_licensing_agreement(
            licence["id"], {"reason": "Licence not renewed"}, LICENSING))
        order = validate_success(api.get_content_delivery_order(
            released_delivery["order"]["id"], STAFF))
        assert order["delivery_status"] == "WITHDRAWN"

    def test_termination_forces_scope_internal_and_withdraws_the_territory(
        self, api, released_delivery,
    ):
        """PRD §3.9: "the licence's distribution_scope is recomputed and fixed at
        INTERNAL_ONLY; and the licensee's territory row has its territory_status set
        to WITHDRAWN and its can_license recomputed to false."

        Design: Difficulty/transitive_cascade/licence_termination_to_delivery_to_scope
        """
        licence = released_delivery["licence"]
        territory = released_delivery["territory"]
        terminated = validate_success(api.terminate_licensing_agreement(
            licence["id"], {"reason": "Licence not renewed"}, LICENSING))
        assert terminated["agreement_status"] == "TERMINATED"
        assert terminated["distribution_scope"] == "INTERNAL_ONLY"
        refreshed_territory = validate_success(
            api.get_distribution_territory(territory["id"], LICENSING))
        assert refreshed_territory["territory_status"] == "WITHDRAWN"
        assert refreshed_territory["can_license"] is False