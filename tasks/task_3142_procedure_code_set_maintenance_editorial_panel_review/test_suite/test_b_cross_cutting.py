"""Corner coverage indexed under the cross-cutting surface (version-sensitive writes)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    STAFF, TEST_USERS,
    api_client, set_clock,
    setup_active_licence, setup_reserved_delivery, setup_submitted_change_in_cycle,
)


class TestDeliveryReservationVersionEcho:
    def test_reserving_with_a_stale_licence_version_is_refused(self, api):
        """PRD §2.10: "For a delivery reservation, expected_license_version must equal
        the current version of the LicensingAgreement the reservation names. If the
        licence's version has advanced since the client last read it — for instance
        because an earlier delivery reservation against the same licence legitimately
        advanced it — the reservation is rejected with ERR_STALE_VERSION at 412."

        Design: Corner/cross_cutting/wrong_expected_license_version_returns_stale_version
        """
        bundle = setup_reserved_delivery(territory_code="US-GULF", sales_unit_count=7)
        licence = bundle["licence"]
        stale_version = bundle["version_before_reservation"]
        response = api.create_content_delivery_order(
            {
                "license_id": licence["id"],
                "distribution_channel": "SITE",
                "format_params": {"electronic_format": "NONE", "media": "NONE",
                                  "version_qualifier": "2026.1",
                                  "payer_identifier_qualifier": "NONE"},
                "payer_identifier": "PLACEHOLDER",
                "expected_license_version": stale_version,
            },
            bundle["licensee_headers"],
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_reserving_with_the_current_licence_version_succeeds(self, api):
        """PRD §3.10: "A successful reservation sets delivery_status to RESERVED,
        computes activation_mode — SITE, MEDIA or ELECTRONIC as derived from the
        channel and format parameters — stamps reserved_at, and increments the named
        licence's version by one."

        Design: Corner/cross_cutting/correct_expected_license_version_reserves_delivery
        """
        bundle = setup_active_licence(territory_code="US-APPALACHIA", sales_unit_count=9,
                                      licensee_name="Appalachia Clinic", expected_users=13)
        licence = bundle["licence"]
        version_before = licence["version"]
        headers = {"X-User-ID": licence["id"], "X-User-Role": "Licensee"}
        order = validate_success(api.create_content_delivery_order(
            {
                "license_id": licence["id"],
                "distribution_channel": "SITE",
                "format_params": {"electronic_format": "NONE", "media": "NONE",
                                  "version_qualifier": "2026.1",
                                  "payer_identifier_qualifier": "NONE"},
                "payer_identifier": "PLACEHOLDER",
                "expected_license_version": version_before,
            },
            headers,
        ), 201)
        assert order["delivery_status"] == "RESERVED"
        assert order["activation_mode"] == "SITE"
        refreshed = validate_success(api.get_licensing_agreement(licence["id"], TEST_USERS["licensing_officer_headers"]))
        assert refreshed["version"] == version_before + 1


class TestCycleSubmissionVersionEcho:
    @pytest.fixture
    def enrolled_change(self, api):
        """A change whose version advanced after being carried back to draft."""
        bundle = setup_submitted_change_in_cycle(
            change_code="00103", society_name="Stale Society", society_code="STL",
            meeting_code="AUG2030", meeting_month="AUGUST", year=2031, capacity=500,
            meeting_starts="2030-08-12T14:00:00Z", meeting_ends="2030-08-12T23:00:00Z",
            sponsored=True, submit=False, docket_change=True,
        )
        version_at_creation = bundle["version_at_creation"]
        # PRD SS3.4: the AGENDA_SET -> DRAFT return requires only that the naming
        # meeting be SCHEDULED or PUBLIC_COMMENT_OPEN, and clears the change's
        # meeting_id. The return advances the version, so the creation-time echo
        # is stale by the time the probe submits.
        api.return_code_change(bundle["change"]["id"], {"reason": "Returns the change for rework"}, STAFF)
        return dict(bundle, version_at_creation=version_at_creation)

    def test_submitting_with_a_stale_change_version_is_refused(self, api, enrolled_change):
        """PRD §2.10: "For a cycle submission, expected_change_version must equal the
        current version of each CodeChange being submitted; if any named change's
        version has advanced since the submitter last observed it — for instance because
        a prior submission advanced it — the submission is rejected with
        ERR_STALE_VERSION at 412."

        Design: Corner/cross_cutting/stale_change_version_blocks_cycle_submission
        """
        bundle = enrolled_change
        response = api.submit_release_cycle_changes(
            bundle["cycle"]["id"],
            {"change_ids": [bundle["change"]["id"]],
             "expected_change_version": bundle["version_at_creation"]},
            STAFF,
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_a_refused_submission_leaves_the_change_unenrolled(self, api, enrolled_change):
        """PRD §3.6: "Every named change has its cycle_id set to the cycle and its
        effective_date stamped to January 1 of the cycle's year plus one."

        Design: Corner/cross_cutting/stale_change_version_blocks_cycle_submission
        """
        bundle = enrolled_change
        api.submit_release_cycle_changes(
            bundle["cycle"]["id"],
            {"change_ids": [bundle["change"]["id"]],
             "expected_change_version": bundle["version_at_creation"]},
            STAFF,
        )
        row = validate_success(api.get_code_change(bundle["change"]["id"], STAFF))
        assert row["cycle_id"] is None