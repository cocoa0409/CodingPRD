"""Measurement & verification: GEN exclusion, verified-UCAP formula, window
overlap, and the revision loop (PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_owner,
    create_resource,
    create_measurement_report_payload,
    get_success_data,
    make_resource_owner_headers,
    reject_report,
    setup_delivery_year_with_forecast,
    setup_dr_resource_measured,
    start_review,
    submit_measurement_report,
    validate_error,
    verify_report,
)

ADMIN = TEST_USERS["market_admin_headers"]


class TestMeasurementApplicability:
    def test_gen_resource_report_rejected(self, api):
        """PRD §3.7: "Demand-response and energy-efficiency resources prove
        their capability through **MeasurementReport** submissions by their
        owner; generation resources may not submit, and an attempt yields
        `ERR_MEASUREMENT_NOT_APPLICABLE`."

        Design: Corner/validations/err_measurement_not_applicable_for_gen_resource
        """
        dy, zone, forecast = setup_delivery_year_with_forecast()
        owner = create_owner()
        resource = create_resource(owner["id"], zone["id"], resource_type="GEN",
                                   nameplate_mw=100.0)
        headers = make_resource_owner_headers(owner["id"])
        payload = create_measurement_report_payload(
            resource["id"], dy["id"],
            reporting_period_start="2029-06-01T00:00:00Z",
            reporting_period_end="2029-08-01T00:00:00Z",
            metered_mwh=100.0, baseline_mwh=200.0,
        )
        resp = api.create_measurement_report(payload, headers)
        validate_error(resp, ApiErrorId.ERR_MEASUREMENT_NOT_APPLICABLE,
                       expected_status=422)


class TestVerifiedUcap:
    def test_min_baseline_then_derate(self, api):
        """PRD §3.7: "Verification computes `verified_ucap_mw`: the delivered
        energy is the lesser of `metered_mwh` and `baseline_mwh`; divided by
        the window length in hours it yields an average megawatt figure, which
        is then scaled by the resource's `EFFECTIVE` accreditation factor for
        the report's delivery year"

        Design: Corner/calculations/mv_verified_ucap_min_baseline_then_derate
        """
        ctx = setup_dr_resource_measured(metered_mwh=1464.0, baseline_mwh=1000.0)
        start_review(ctx["report"]["id"])
        verified = verify_report(ctx["report"]["id"])
        assert verified["status"] == "VERIFIED"
        # delivered = min(1464, 1000) = 1000; window = 1464 h;
        # avg = 0.683060...; * 0.8 = 0.546448... -> 0.546
        assert verified["verified_ucap_mw"] == pytest.approx(0.546, abs=1e-9)


class TestMeasurementWindowOverlap:
    def test_overlapping_window_blocked_at_verify(self, api):
        """PRD §3.7: "a `VERIFIED` report's half-open window blocks any later
        report for the same resource with an overlapping window from entering
        `VERIFIED`, rejected with `ERR_MEASUREMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/measurement_window_overlap_blocks_verify
        """
        ctx = setup_dr_resource_measured(metered_mwh=1464.0, baseline_mwh=2000.0)
        start_review(ctx["report"]["id"])
        verify_report(ctx["report"]["id"])

        mr2 = submit_measurement_report(
            ctx["resource"]["id"], ctx["owner"]["id"], ctx["dy"]["id"],
            reporting_period_start="2029-07-01T00:00:00Z",
            reporting_period_end="2029-09-01T00:00:00Z",
            metered_mwh=1000.0, baseline_mwh=2000.0,
        )
        start_review(mr2["id"])
        resp = api.verify_measurement_report(mr2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEASUREMENT_WINDOW_OVERLAP,
                       expected_status=409)
        mr2_after = get_success_data(api.get_measurement_report(mr2["id"], ADMIN))
        assert mr2_after["status"] == "UNDER_REVIEW"

    def test_non_overlapping_window_verifies(self, api):
        """PRD §3.7: "a `VERIFIED` report's half-open window blocks any later
        report for the same resource with an overlapping window from entering
        `VERIFIED`" — a window that starts exactly where the VERIFIED window
        ends does not overlap the half-open [start, end) interval and may
        verify.

        Design: Difficulty/resource_temporal_overlap/measurement_window_overlap_blocks_verify
        """
        ctx = setup_dr_resource_measured(metered_mwh=1464.0, baseline_mwh=2000.0)
        start_review(ctx["report"]["id"])
        verify_report(ctx["report"]["id"])

        mr2 = submit_measurement_report(
            ctx["resource"]["id"], ctx["owner"]["id"], ctx["dy"]["id"],
            reporting_period_start="2029-08-01T00:00:00Z",
            reporting_period_end="2029-10-01T00:00:00Z",
            metered_mwh=1000.0, baseline_mwh=2000.0,
        )
        start_review(mr2["id"])
        verified = verify_report(mr2["id"])
        assert verified["status"] == "VERIFIED"


class TestRevisionLoop:
    def _setup_rejected_then_revised(self, api):
        ctx = setup_dr_resource_measured(metered_mwh=1464.0, baseline_mwh=2000.0)
        start_review(ctx["report"]["id"])
        reject_report(ctx["report"]["id"])
        mr2 = submit_measurement_report(
            ctx["resource"]["id"], ctx["owner"]["id"], ctx["dy"]["id"],
            reporting_period_start="2029-06-01T00:00:00Z",
            reporting_period_end="2029-08-01T00:00:00Z",
            metered_mwh=1500.0, baseline_mwh=2000.0,
            revision_of_id=ctx["report"]["id"],
        )
        start_review(mr2["id"])
        return ctx, mr2

    def test_revision_reenters_submitted_and_verifies(self, api):
        """PRD §3.7: "the owner submits a revision whose `revision_of_id`
        points at the `REJECTED` report, the new report enters `SUBMITTED`
        provided its window overlaps no `VERIFIED` report for the resource,
        and the prior report remains untouched — an append-only revision
        history."

        Design: Difficulty/non_linear_state_machine/measurement_report_revision_loop_after_rejection
        """
        ctx, mr2 = self._setup_rejected_then_revised(api)
        verified = verify_report(mr2["id"])
        assert verified["status"] == "VERIFIED"
        assert verified["revision_of_id"] == ctx["report"]["id"]
        mr1_after = get_success_data(
            api.get_measurement_report(ctx["report"]["id"], ADMIN)
        )
        assert mr1_after["status"] == "REJECTED"

    def test_revision_verified_ucap_uses_revision_metered_values(self, api):
        """PRD §3.7: "Verification computes `verified_ucap_mw`: the delivered
        energy is the lesser of `metered_mwh` and `baseline_mwh`; divided by
        the window length in hours it yields an average megawatt figure, which
        is then scaled by the resource's `EFFECTIVE` accreditation factor for
        the report's delivery year — or by 1.0 when no effective accreditation
        exists, so unaccredited DR and EE resources are still measured at face
        value — and rounded to 3 decimal places round half up."

        Design: Difficulty/non_linear_state_machine/measurement_report_revision_loop_after_rejection
        """
        ctx, mr2 = self._setup_rejected_then_revised(api)
        verified = verify_report(mr2["id"])
        # delivered = min(1500, 2000) = 1500; window = 1464 h;
        # avg = 1.024590...; * 0.8 = 0.819672... -> 0.820
        assert verified["verified_ucap_mw"] == pytest.approx(0.820, abs=1e-9)
