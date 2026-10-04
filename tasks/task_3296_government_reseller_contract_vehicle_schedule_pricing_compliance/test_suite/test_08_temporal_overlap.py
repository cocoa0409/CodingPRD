"""Temporal semantics: exclusive vehicle window end; period uniqueness."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_agreement,
    create_active_price_list,
    create_manufacturer,
    create_order,
    create_sales_report,
    create_vehicle_payload,
    set_clock,
    validate_error,
    validate_success,
)

CM = TEST_USERS["contracts_manager_headers"]
FIN = TEST_USERS["finance_ops_headers"]
OPS = TEST_USERS["reseller_ops_headers"]


class TestVehicleWindowExclusiveEnd:
    def _vehicle_at_window_end(self, api):
        """Vehicle with window [2026-01-01, 2026-10-01); authorized while the
        clock is inside the window, then the clock advances to exactly
        effective_to. Returns (agreement, vehicle, price_list, order)."""
        set_clock("2026-06-01T00:00:00Z")
        manufacturer = create_manufacturer(legal_name="O Corp 2")
        _, agreement = create_active_agreement(manufacturer_id=manufacturer["id"])
        resp = api.create_vehicle(
            create_vehicle_payload(
                agreement["id"],
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            CM,
        )
        vehicle = validate_success(resp, expected_status=201)
        validate_success(api.authorize_vehicle(vehicle["id"], CM))
        price_list = create_active_price_list(
            vehicle["id"],
            period_from="2026-01-01T00:00:00Z",
            period_to="2026-10-01T00:00:00Z",
        )
        # Order is created while the clock is still inside the window; the
        # clock then advances to exactly effective_to before submission.
        order = create_order(vehicle["id"], price_list["id"])
        set_clock("2026-10-01T00:00:00Z")
        return agreement, vehicle, price_list, order

    def test_submit_at_effective_to_rejected_outside_window(self, api):
        """PRD §3.6: "Submission also enforces the vehicle-window check — the
        logical clock must fall within the vehicle's effective window,
        otherwise ERR_OUTSIDE_VEHICLE_WINDOW — and, for teaming-routed orders,
        repeats the teaming-eligibility check from creation."
        PRD §3.2: "the logical clock currently falls within the half-open
        window from effective_from up to but not including effective_to
        (otherwise ERR_OUTSIDE_VEHICLE_WINDOW)."

        Design: Difficulty/resource_temporal_overlap/vehicle_window_exclusive_end_vs_teaming_window_inclusive
        """
        _, vehicle, _, order = self._vehicle_at_window_end(api)
        resp = api.submit_order(order["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_VEHICLE_WINDOW)

    def test_vehicle_lazily_expires_on_read_after_effective_to(self, api):
        """PRD §3.2: "A vehicle expires when the logical clock reaches or
        passes effective_to. The transition from AUTHORIZED to EXPIRED is
        evaluated lazily on the next touch (order intake, price-list
        submission, or vehicle read), and a ComplianceOfficer may also force
        expiry."

        Design: Difficulty/resource_temporal_overlap/vehicle_window_exclusive_end_vs_teaming_window_inclusive
        """
        _, vehicle, _, order = self._vehicle_at_window_end(api)
        validate_error(api.submit_order(order["id"], OPS), ApiErrorId.ERR_OUTSIDE_VEHICLE_WINDOW)
        vehicle = validate_success(api.get_vehicle(vehicle["id"], CM))
        assert vehicle["status"] == "EXPIRED"

    def test_submit_before_window_end_accepted(self, api):
        """PRD §3.2: "the logical clock currently falls within the half-open
        window from effective_from up to but not including effective_to
        (otherwise ERR_OUTSIDE_VEHICLE_WINDOW)."

        Design: Difficulty/resource_temporal_overlap/vehicle_window_exclusive_end_vs_teaming_window_inclusive
        """
        set_clock("2026-06-01T00:00:00Z")
        manufacturer = create_manufacturer(legal_name="O Corp 3")
        _, agreement = create_active_agreement(manufacturer_id=manufacturer["id"])
        resp = api.create_vehicle(
            create_vehicle_payload(
                agreement["id"],
                effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-10-01T00:00:00Z",
            ),
            CM,
        )
        vehicle = validate_success(resp, expected_status=201)
        validate_success(api.authorize_vehicle(vehicle["id"], CM))
        price_list = create_active_price_list(
            vehicle["id"],
            period_from="2026-01-01T00:00:00Z",
            period_to="2026-10-01T00:00:00Z",
        )
        # 2026-09-30 is strictly inside the half-open window.
        set_clock("2026-09-30T23:59:59Z")
        order = create_order(vehicle["id"], price_list["id"])
        resp = api.submit_order(order["id"], OPS)
        order = validate_success(resp)
        assert order["compliance_status"] == "CLEARED"


class TestSalesReportPeriodUniqueness:
    def test_duplicate_period_report_rejected(self, api):
        """PRD §3.8: "A FinanceOps operator may also open a sales report
        directly for an (agreement_id, period_label) pair when none was
        auto-created; the pair must be unique, with a duplicate rejected as
        ERR_UNIQUENESS_VIOLATION."

        Design: Difficulty/resource_temporal_overlap/sales_report_period_overlap_uniqueness
        """
        set_clock("2026-10-01T00:00:00Z")
        _, agreement = create_active_agreement()
        create_sales_report(agreement["id"], period_label="2026-09")
        resp = api.create_sales_report(
            {"agreement_id": agreement["id"], "period_label": "2026-09"}, FIN,
        )
        validate_error(resp, ApiErrorId.ERR_UNIQUENESS_VIOLATION)

    def test_distinct_period_reports_admitted(self, api):
        """PRD §3.8: "A FinanceOps operator may also open a sales report
        directly for an (agreement_id, period_label) pair when none was
        auto-created; the pair must be unique, with a duplicate rejected as
        ERR_UNIQUENESS_VIOLATION."

        Design: Difficulty/resource_temporal_overlap/sales_report_period_overlap_uniqueness
        """
        set_clock("2026-10-01T00:00:00Z")
        _, agreement = create_active_agreement()
        create_sales_report(agreement["id"], period_label="2026-09")
        resp = api.create_sales_report(
            {"agreement_id": agreement["id"], "period_label": "2026-08"}, FIN,
        )
        report = validate_success(resp, expected_status=201)
        assert report["period_label"] == "2026-08"
        assert report["status"] == "DRAFT"
