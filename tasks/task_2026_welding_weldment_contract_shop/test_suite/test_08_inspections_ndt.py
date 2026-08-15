"""Inspection hold points: VT segregation of duties and the NDT vendor slot
arithmetic (half-open overlap intervals, aggregate hourly capacity,
scheduled-but-not-yet-resulted filtering)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_cwi_headers,
    record_inspection_result,
    schedule_ndt,
    set_clock,
    setup_fab_workspace,
    setup_vt_passed_workspace,
    validate_error,
    validate_success,
    weld_out,
    record_weld_pass,
)

ADMIN = TEST_USERS["shop_admin_headers"]
CWI = TEST_USERS["cwi_headers"]


class TestVisualInspectionSegregation:
    def test_vt_inspector_must_not_be_welder(self, api):
        """PRD §3.6: "Recording a VT inspection with a `PASS` result requires
        the joint's `inspection_status` to be `READY_FOR_VT`, and enforces
        segregation of duties: the inspector's `X-User-ID` must not equal any
        welder who recorded a pass on that joint (`ERR_SEGREGATION_OF_DUTIES`,
        HTTP 403)."

        Design: Corner/validations/vt_inspector_must_not_be_welder
        """
        ws = setup_fab_workspace(shop_name="VT Segregation Shop")
        shop_id = ws["shop"]["id"]
        joint = ws["joints"][0]
        record_weld_pass(shop_id, joint["id"], ws["welder"]["id"],
                         ws["qualification"]["id"], ws["lot"]["id"])
        weld_out(shop_id, joint["id"])

        resp = api.create_inspection(
            shop_id, joint["id"],
            {"method": "VT",
             "scheduled_start_utc": "2026-08-02T09:00:00Z",
             "scheduled_end_utc": "2026-08-02T09:30:00Z",
             "result": "PASS",
             "result_code": "OK"},
            # CWI identity deliberately equals the welder's entity id.
            make_cwi_headers(ws["welder"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestNdtSlotHalfOpenBoundary:
    """Vendor hourly_capacity 1; half-open [start, end) overlap arithmetic."""

    def test_adjacent_ut_bookings_do_not_conflict(self, api):
        """PRD §3.6: "Capacity is enforced on overlapping bookings: the
        system counts the vendor's scheduled-but-not-yet-resulted inspections
        whose time windows overlap the new one — an existing booking overlaps
        when it starts before the new booking ends and ends after the new
        booking starts, on half-open intervals, so a booking that ends
        exactly when the new one begins does not conflict — and the new
        booking is accepted only while that overlap count is below the
        vendor's `hourly_capacity`, otherwise `ERR_NDT_VENDOR_SLOT_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/boundary_precision_check/ndt_slot_half_open_boundary
        """
        ws = setup_vt_passed_workspace(shop_name="Adjacent Slot Shop",
                                       joint_count=2,
                                       vendor_hourly_capacity=1)
        shop_id = ws["shop"]["id"]
        vendor_id = ws["vendor"]["id"]
        j1, j2 = ws["joints"]

        first = schedule_ndt(shop_id, j1["id"], vendor_id, method="UT",
                             start="2026-08-03T09:00:00Z",
                             end="2026-08-03T10:00:00Z")
        assert first["id"]

        # Starts exactly when the first booking ends: no conflict.
        second = schedule_ndt(shop_id, j2["id"], vendor_id, method="UT",
                              start="2026-08-03T10:00:00Z",
                              end="2026-08-03T11:00:00Z")
        assert second["id"], (
            "A booking starting exactly at the predecessor's end must be "
            "accepted (half-open boundary)")

    def test_overlapping_ut_booking_rejected(self, api):
        """PRD §3.6: "Capacity is enforced on overlapping bookings: the
        system counts the vendor's scheduled-but-not-yet-resulted inspections
        whose time windows overlap the new one — an existing booking overlaps
        when it starts before the new booking ends and ends after the new
        booking starts, on half-open intervals, so a booking that ends
        exactly when the new one begins does not conflict — and the new
        booking is accepted only while that overlap count is below the
        vendor's `hourly_capacity`, otherwise `ERR_NDT_VENDOR_SLOT_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/boundary_precision_check/ndt_slot_half_open_boundary
        """
        ws = setup_vt_passed_workspace(shop_name="Overlap Slot Shop",
                                       joint_count=3,
                                       vendor_hourly_capacity=1)
        shop_id = ws["shop"]["id"]
        vendor_id = ws["vendor"]["id"]
        j1, j2, j3 = ws["joints"]

        schedule_ndt(shop_id, j1["id"], vendor_id, method="UT",
                     start="2026-08-03T09:00:00Z", end="2026-08-03T10:00:00Z")
        schedule_ndt(shop_id, j2["id"], vendor_id, method="UT",
                     start="2026-08-03T10:00:00Z", end="2026-08-03T11:00:00Z")

        # [09:30, 10:30) overlaps both unresolved bookings; capacity is 1.
        resp = api.create_inspection(
            shop_id, j3["id"],
            {"method": "UT",
             "scheduled_start_utc": "2026-08-03T09:30:00Z",
             "scheduled_end_utc": "2026-08-03T10:30:00Z",
             "vendor_id": vendor_id},
            CWI)
        validate_error(resp, ApiErrorId.ERR_NDT_VENDOR_SLOT_CONFLICT)


class TestNdtVendorSlotAccounting:
    """Same vendor resource, RT method: adjacency and the
    scheduled-but-not-yet-resulted filter."""

    def test_adjacent_rt_bookings_share_capacity(self, api):
        """PRD §3.6: "Capacity is enforced on overlapping bookings: the
        system counts the vendor's scheduled-but-not-yet-resulted inspections
        whose time windows overlap the new one — an existing booking overlaps
        when it starts before the new booking ends and ends after the new
        booking starts, on half-open intervals, so a booking that ends
        exactly when the new one begins does not conflict — and the new
        booking is accepted only while that overlap count is below the
        vendor's `hourly_capacity`, otherwise `ERR_NDT_VENDOR_SLOT_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/ndt_vendor_slot_half_open
        """
        ws = setup_vt_passed_workspace(shop_name="RT Adjacent Shop",
                                       joint_count=2,
                                       ndt_methods=("VT", "RT"),
                                       vendor_methods=("RT",),
                                       vendor_hourly_capacity=1)
        shop_id = ws["shop"]["id"]
        vendor_id = ws["vendor"]["id"]
        j1, j2 = ws["joints"]

        schedule_ndt(shop_id, j1["id"], vendor_id, method="RT",
                     start="2026-08-03T09:00:00Z", end="2026-08-03T10:00:00Z")
        second = schedule_ndt(shop_id, j2["id"], vendor_id, method="RT",
                              start="2026-08-03T10:00:00Z",
                              end="2026-08-03T11:00:00Z")
        assert second["id"], (
            "Adjacent RT bookings fit one hourly slot (end == start is not "
            "an overlap)")

    def test_resulted_bookings_free_vendor_capacity(self, api):
        """PRD §3.6: "Capacity is enforced on overlapping bookings: the
        system counts the vendor's scheduled-but-not-yet-resulted inspections
        whose time windows overlap the new one — an existing booking overlaps
        when it starts before the new booking ends and ends after the new
        booking starts, on half-open intervals, so a booking that ends
        exactly when the new one begins does not conflict — and the new
        booking is accepted only while that overlap count is below the
        vendor's `hourly_capacity`, otherwise `ERR_NDT_VENDOR_SLOT_CONFLICT`
        (HTTP 409)."
        PRD §3.6: "A `PASS` completes the method: once every method in the
        joint's `required_ndt_methods` has a passing inspection row, the
        joint's `inspection_status` becomes `NDT_PASSED`, and the passing
        inspection's `hold_point_released` is set true, releasing the hold
        point that gates downstream fabrication on the joint."

        Design: Difficulty/resource_temporal_overlap/ndt_vendor_slot_half_open
        """
        ws = setup_vt_passed_workspace(shop_name="Resulted Frees Shop",
                                       joint_count=2,
                                       ndt_methods=("VT", "RT"),
                                       vendor_methods=("RT",),
                                       vendor_hourly_capacity=1)
        shop_id = ws["shop"]["id"]
        vendor_id = ws["vendor"]["id"]
        j1, j2 = ws["joints"]

        first = schedule_ndt(shop_id, j1["id"], vendor_id, method="RT",
                             start="2026-08-03T09:00:00Z",
                             end="2026-08-03T10:00:00Z")
        # Let the slot elapse, then record the result.
        set_clock("2026-08-03T10:00:01Z")
        resulted = record_inspection_result(shop_id, first["id"],
                                            result="PASS", result_code="OK")
        assert resulted["result"] == "PASS"
        assert resulted["hold_point_released"] is True

        j1_now = get_success_data(api.get_joint(shop_id, j1["id"], ADMIN))
        assert j1_now["inspection_status"] == "NDT_PASSED"

        # The resulted booking no longer counts against vendor capacity, so
        # an overlapping window for another joint is accepted.
        second = schedule_ndt(shop_id, j2["id"], vendor_id, method="RT",
                              start="2026-08-03T09:30:00Z",
                              end="2026-08-03T10:30:00Z")
        assert second["id"], (
            "A resulted inspection stops counting against vendor capacity")
