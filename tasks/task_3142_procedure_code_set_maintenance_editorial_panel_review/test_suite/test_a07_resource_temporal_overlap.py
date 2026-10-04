"""Resource-occupancy overlap: half-open slots that a second holder cannot take."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, validate_paginated,
    LICENSING, TEST_USERS,
    api_client, set_clock, create_society, create_applicant, create_meeting,
    create_change, docket, open_meeting, cast_vote,
    create_licence_and_territory, setup_reserved_delivery, setup_active_licence,
)


class TestDuplicateDeliveryReservation:
    def test_second_reservation_while_a_slot_is_held_is_refused(self, api):
        """PRD §3.10: "A licence may hold at most one delivery order in RESERVED or
        READY at a time. A second reservation while such an order exists is rejected
        with ERR_DUPLICATE_DELIVERY_RESERVATION at 409".

        Design: Difficulty/resource_temporal_overlap/duplicate_delivery_reservation_overlaps_license_slot
        """
        bundle = setup_reserved_delivery(territory_code="US-PACIFIC", sales_unit_count=8)
        licence = bundle["licence"]
        response = api.create_content_delivery_order(
            {
                "license_id": licence["id"],
                "distribution_channel": "SITE",
                "format_params": {"electronic_format": "NONE", "media": "NONE",
                                  "version_qualifier": "2026.1",
                                  "payer_identifier_qualifier": "NONE"},
                "payer_identifier": "PLACEHOLDER",
                "expected_license_version": bundle["version_after_reservation"],
            },
            bundle["licensee_headers"],
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_DELIVERY_RESERVATION,
                       expected_status=409)

    def test_refused_reservation_leaves_the_licence_holding_a_single_order(self, api):
        """PRD §3.10: "the licence's reserved delivery slot stays occupied until the
        existing order is released or withdrawn".

        Design: Difficulty/resource_temporal_overlap/duplicate_delivery_reservation_overlaps_license_slot
        """
        bundle = setup_reserved_delivery(territory_code="US-PACIFIC", sales_unit_count=8)
        licence = bundle["licence"]
        api.create_content_delivery_order(
            {
                "license_id": licence["id"],
                "distribution_channel": "SITE",
                "format_params": {"electronic_format": "NONE", "media": "NONE",
                                  "version_qualifier": "2026.1",
                                  "payer_identifier_qualifier": "NONE"},
                "payer_identifier": "PLACEHOLDER",
                "expected_license_version": bundle["version_after_reservation"],
            },
            bundle["licensee_headers"],
        )
        orders, meta = validate_paginated(
            api.list_license_delivery_orders(licence["id"], LICENSING))
        assert meta["total_count"] == 1
        assert len(orders) == 1
        assert orders[0]["delivery_status"] == "RESERVED"


class TestTerritoryDoubleBinding:
    @pytest.fixture
    def occupied_territory(self):
        """A territory already bound to an active licence."""
        bundle = setup_active_licence(territory_code="US-SOUTHWEST", sales_unit_count=6,
                                      licensee_name="First Southwest Clinic",
                                      expected_users=12)
        return bundle

    def test_second_live_licence_on_an_occupied_territory_is_refused(self, api, occupied_territory):
        """PRD §3.9: "A distribution territory may be bound by at most one
        LicensingAgreement whose agreement_status is not TERMINATED, so the territory's
        occupancy interval ends only when that licence terminates; an attempt to bind a
        second live licence to an already-occupied territory is rejected with
        ERR_TERRITORY_OCCUPIED at 409."

        Design: Difficulty/resource_temporal_overlap/territory_double_binding_overlaps_agreement_interval
        """
        territory = occupied_territory["territory"]
        response = api.create_licensing_agreement(
            {
                "licensee_type": "PROVIDER",
                "licensee_name": "Second Southwest Clinic",
                "vendor_worldwide": False,
                "expected_users": 9,
                "sales_unit_count": 5,
                "base_fee_cents": 0,
                "territory_id": territory["id"],
            },
            LICENSING,
        )
        validate_error(response, ApiErrorId.ERR_TERRITORY_OCCUPIED, expected_status=409)

    def test_refused_binding_leaves_one_licence_on_the_territory(self, api, occupied_territory):
        """PRD §3.9: "the territory's occupancy interval ends only when that licence
        terminates".

        Design: Difficulty/resource_temporal_overlap/territory_double_binding_overlaps_agreement_interval
        """
        territory = occupied_territory["territory"]
        api.create_licensing_agreement(
            {
                "licensee_type": "PROVIDER",
                "licensee_name": "Second Southwest Clinic",
                "vendor_worldwide": False,
                "expected_users": 9,
                "sales_unit_count": 5,
                "base_fee_cents": 0,
                "territory_id": territory["id"],
            },
            LICENSING,
        )
        licences, meta = validate_paginated(
            api.list_territory_licensing_agreements(territory["id"], LICENSING))
        assert meta["total_count"] == 1
        assert len(licences) == 1