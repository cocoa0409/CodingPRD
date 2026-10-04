"""Carrier registration and revenue adequacy findings (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    FINDING_2025_SINGLE,
    FINDINGS_2021_2025,
    NON_EXISTENT_ID,
    api_client,
    assert_carrier,
    assert_finding,
    create_carrier_payload,
    file_finding,
    file_findings,
    get_carrier_data,
    register_carrier,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_adjudicator_headers"]


class TestCarrierRegistration:
    def test_carrier_create_returns_computed_defaults(self):
        """PRD §3.1: "At registration the derived registers initialize:
        `active_route_miles` equals `base_route_miles`, `abandoned_route_miles`
        and `trail_use_route_miles` are 0, `revenue_adequacy_status` is
        `UNDETERMINED`, `compliance_standing` is `GOOD`, and
        `reparation_exposure_cents` is 0."

        Design: Corner/entities/carrier_create_returns_computed_defaults
        """
        resp = api_client.create_carrier(create_carrier_payload(), ADMIN)
        carrier = validate_success(resp, 201)
        assert_carrier(carrier)
        assert carrier["active_route_miles"] == 1000
        assert carrier["abandoned_route_miles"] == 0
        assert carrier["trail_use_route_miles"] == 0
        assert carrier["revenue_adequacy_status"] == "UNDETERMINED"
        assert carrier["compliance_standing"] == "GOOD"
        assert carrier["reparation_exposure_cents"] == 0
        assert carrier["version"] == 1

    def test_carrier_get_returns_stored_fields(self):
        """PRD §2.9: "A carrier's condition is never edited directly; four
        registers are derived from underlying records and recomputed at the
        moment those records change, and all of them are visible on every
        carrier read" — so GET returns every stored and derived field.

        Design: Corner/entities/carrier_get_returns_stored_fields
        """
        created = register_carrier()
        fetched = get_carrier_data(created["id"])
        assert_carrier(fetched)
        assert fetched["carrier_code"] == "OKTX"
        assert fetched["legal_name"] == "Oklahoma & Texas Railway"
        assert fetched["carrier_class"] == "I"
        assert fetched["base_route_miles"] == 1000
        assert fetched["active_route_miles"] == 1000

    def test_get_carrier_not_found_returns_404(self):
        """PRD §2.6: "A missing carrier id yields `ERR_CARRIER_NOT_FOUND`"
        (HTTP 404, path existence check)."

        Design: Corner/entities/get_carrier_not_found_returns_404
        """
        resp = api_client.get_carrier(NON_EXISTENT_ID, BOARD)
        validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)

    def test_invalid_enum_carrier_class_rejected(self):
        """PRD §3.1: "its `carrier_class` (one of `I`, `II`, or `III`)"; PRD
        §2.6: "every required input field must be present, enum values must be
        in range, numeric bounds must be respected, `service_end_date` must be
        strictly later than `service_start_date`, and the `conditions` array
        must be non-empty where an outcome requires it — any such defect is
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/invalid_enum_carrier_class_rejected
        """
        resp = api_client.create_carrier(
            create_carrier_payload(
                carrier_code="BADX", legal_name="Bad Class Railway",
                carrier_class="IV", base_route_miles=100),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_carrier_code_rejected(self):
        """PRD §3.1: "The `carrier_code` is unique across all carriers: a
        registration repeating an existing code is rejected with
        `ERR_DUPLICATE_CARRIER_CODE` (HTTP 409)."

        Design: Corner/validations/duplicate_carrier_code_rejected
        """
        first = register_carrier()
        resp = api_client.create_carrier(
            create_carrier_payload(
                legal_name="OK Texas Clone Lines", carrier_class="II",
                base_route_miles=50),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CARRIER_CODE)
        after = get_carrier_data(first["id"])
        assert after["legal_name"] == "Oklahoma & Texas Railway"


class TestRevenueAdequacyFindings:
    def test_duplicate_finding_year_rejected(self):
        """PRD §3.1: "There is at most one finding per carrier per fiscal
        year; a second filing for the same carrier and `fiscal_year` is
        rejected with `ERR_DUPLICATE_FINDING` (HTTP 409)."

        Design: Corner/validations/duplicate_finding_year_rejected
        """
        carrier = register_carrier()
        file_finding(carrier["id"], **FINDING_2025_SINGLE)
        resp = api_client.create_finding(
            carrier["id"],
            {
                "fiscal_year": 2025,
                "operating_revenue_cents": 900000000,
                "operating_expense_cents": 700000000,
                "net_investment_cents": 2000000000,
            },
            BOARD,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FINDING)

    def test_current_year_vs_five_year_roi_finding_divergence(self):
        """PRD §3.1: "The **five-year average** `five_year_avg_roi_bps` is the
        mean of the `current_year_roi_bps` values over this carrier's findings
        whose `fiscal_year` falls in the five-year window from `fiscal_year`
        minus 4 through `fiscal_year` inclusive, that mean rounded half up to
        a whole basis point; when fewer than five findings exist in the
        window, only the years that exist are averaged."
        PRD §3.1: "`finding` is `ADEQUATE` when `five_year_avg_roi_bps` is at
        least 1140 basis points — the Board's cost of capital — and
        `INADEQUATE` otherwise."
        PRD §3.1: "the carrier's `revenue_adequacy_status` immediately adopts
        the `finding` of whichever finding now has the greatest `fiscal_year`."

        Design: Difficulty/dual_variant_calc/current_year_vs_five_year_roi_finding_divergence
        """
        carrier = register_carrier()
        findings = file_findings(carrier["id"], FINDINGS_2021_2025)
        assert_finding(findings[0])
        assert findings[0]["fiscal_year"] == 2021
        # Single available year in the 2017-2021 window averages itself.
        assert findings[0]["current_year_roi_bps"] == 1200
        assert findings[0]["five_year_avg_roi_bps"] == 1200
        # 2025 filing: current-year (1000M-800M)*10000/2000M = 1000 bps, but
        # the five-year variant (1200+1250+1300+1150+1000)/5 = 1180 governs.
        f25 = findings[-1]
        assert f25["current_year_roi_bps"] == 1000
        assert f25["five_year_avg_roi_bps"] == 1180
        assert f25["finding"] == "ADEQUATE"
        assert get_carrier_data(carrier["id"])["revenue_adequacy_status"] == "ADEQUATE"
