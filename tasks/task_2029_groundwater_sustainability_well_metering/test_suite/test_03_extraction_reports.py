"""Extraction reporting: state gates, revision loop, late flag, and ledger moves
(PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_well,
    create_account,
    create_active_domestic_well,
    create_active_production_well,
    create_extraction_report_payload,
    create_metered_well,
    create_well,
    dispute_report,
    get_account,
    make_well_owner_headers,
    resubmit_report,
    set_clock,
    setup_account_with_active_production_well,
    submit_and_verify_report,
    submit_extraction_report,
    validate_error,
    validate_paginated,
    validate_success,
    verify_report,
)


class TestReportStateMachine:
    def test_verify_already_verified_report_rejected(self, api, water_master_headers):
        """PRD §3.3: "Verification requires `SUBMITTED` status — anything else is `ERR_INVALID_REPORT_STATE` — and triggers the deepest cascade in the system."
        PRD §3.3: "A report may cycle `SUBMITTED` → `DISPUTED` → `SUBMITTED` any number of times until it is finally verified; `VERIFIED` is terminal."

        Design: Corner/state_machines/verify_already_verified_report_rejected
        """
        account, well = setup_account_with_active_production_well(holder_name="Pumper WV")
        report = submit_and_verify_report(well["id"], account["id"], month=6, reported_af=10.000)
        assert report["status"] == "VERIFIED"

        resp = api.verify_report(report["id"], water_master_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REPORT_STATE)

        account_after = get_account(account["id"])
        assert account_after["extracted_af_ytd"] == pytest.approx(10.000, abs=1e-9), (
            f"the rejected second verify must not double-count, got "
            f"{account_after['extracted_af_ytd']}"
        )

    def test_dispute_resubmit_cycle_lands_amended_value(self, api, water_master_headers):
        """PRD §3.3: "Dispute instead moves the report `SUBMITTED` → `DISPUTED` and removes the reported volume from `pending_extraction_af`."
        PRD §3.3: "Resubmission replaces the reported volume, increments `amendment_count` by 1, recomputes `late_flag` against the current logical clock, adds the new volume back into `pending_extraction_af`, and returns the report to `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/extraction_report_dispute_resubmit_cycle
        """
        account, well = setup_account_with_active_production_well(holder_name="Pumper E")
        report = submit_extraction_report(well["id"], account["id"], month=6, reported_af=10.000)

        disputed = dispute_report(report["id"])
        assert disputed["status"] == "DISPUTED"
        mid = get_account(account["id"])
        assert mid["pending_extraction_af"] == pytest.approx(0.0, abs=1e-9), (
            f"dispute must remove the volume from pending, got {mid['pending_extraction_af']}"
        )

        resubmitted = resubmit_report(report["id"], account["id"], 12.000)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["amendment_count"] == 1, (
            f"amendment_count must increment by 1 per resubmission, got "
            f"{resubmitted['amendment_count']}"
        )

        verified = verify_report(report["id"])
        assert verified["status"] == "VERIFIED"
        final = get_account(account["id"])
        assert final["extracted_af_ytd"] == pytest.approx(12.000, abs=1e-9), (
            f"the amended 12.000, not the original 10.000, must land in the ledger, got "
            f"{final['extracted_af_ytd']}"
        )
        assert final["pending_extraction_af"] == pytest.approx(0.0, abs=1e-9)

    def test_dispute_resubmit_cycle_twice_increments_amendment_count(
        self, api, water_master_headers
    ):
        """PRD §3.3: "Resubmission replaces the reported volume, increments `amendment_count` by 1, recomputes `late_flag` against the current logical clock, adds the new volume back into `pending_extraction_af`, and returns the report to `SUBMITTED`."
        PRD §3.3: "A report may cycle `SUBMITTED` → `DISPUTED` → `SUBMITTED` any number of times until it is finally verified; `VERIFIED` is terminal."

        Design: Difficulty/non_linear_state_machine/extraction_report_dispute_resubmit_cycle
        """
        account, well = setup_account_with_active_production_well(holder_name="Pumper E2")
        report = submit_extraction_report(well["id"], account["id"], month=6, reported_af=10.000)

        dispute_report(report["id"])
        first = resubmit_report(report["id"], account["id"], 11.000)
        assert first["amendment_count"] == 1
        dispute_report(report["id"])
        second = resubmit_report(report["id"], account["id"], 8.000)
        assert second["amendment_count"] == 2, (
            f"each resubmission increments amendment_count by 1, got {second['amendment_count']}"
        )
        assert second["reported_af"] == pytest.approx(8.000, abs=1e-9)

        verified = verify_report(report["id"])
        assert verified["status"] == "VERIFIED"
        final = get_account(account["id"])
        assert final["extracted_af_ytd"] == pytest.approx(8.000, abs=1e-9)


class TestReportCreationGates:
    def test_report_on_registered_well_rejected(self, api, water_master_headers):
        """PRD §3.3: "Submitting against a well that is not `ACTIVE` yields `ERR_WELL_NOT_ACTIVE`; submitting against a non-`PRODUCTION` well yields `ERR_INVALID_WELL_TYPE`."

        Design: Difficulty/cross_entity_state_dependency/report_create_requires_well_active
        """
        account = create_account(holder_name="Pumper KS")
        well = create_well(account["id"], "PRODUCTION", "Parcel K")  # stays REGISTERED

        resp = api.create_extraction_report(
            create_extraction_report_payload(well["id"], water_year=2026, month=6,
                                             reported_af=5.000),
            make_well_owner_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WELL_NOT_ACTIVE)

        data, meta = validate_paginated(
            api.list_extraction_reports(water_master_headers, params={"well_id": well["id"]})
        )
        assert meta["total_count"] == 0 and data == [], (
            "no report may be persisted against a non-ACTIVE well"
        )

    def test_report_on_meter_installed_well_rejected(self, api, water_master_headers):
        """PRD §3.3: "Submitting against a well that is not `ACTIVE` yields `ERR_WELL_NOT_ACTIVE`; submitting against a non-`PRODUCTION` well yields `ERR_INVALID_WELL_TYPE`."
        PRD §3.2: "For a `PRODUCTION` well, activation requires the well to be in `METER_INSTALLED` and advances it to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/report_create_requires_well_active
        """
        account = create_account(holder_name="Pumper KS-2")
        well = create_metered_well(account["id"], "Parcel K2")  # METER_INSTALLED, not ACTIVE
        assert well["status"] == "METER_INSTALLED"

        resp = api.create_extraction_report(
            create_extraction_report_payload(well["id"], water_year=2026, month=6,
                                             reported_af=5.000),
            make_well_owner_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WELL_NOT_ACTIVE)

    def test_report_for_wrong_water_year_rejected(self, api):
        """PRD §3.3: "The `water_year` must equal the owning account's `current_water_year` (a mismatch yields `ERR_REPORT_YEAR_MISMATCH`), `month` must be an integer between 1 and 12 inclusive, and `reported_af` must be non-negative at 3-decimal precision."

        Design: Corner/validations/report_for_wrong_water_year_rejected
        """
        account, well = setup_account_with_active_production_well(holder_name="Pumper WZ")

        resp = api.create_extraction_report(
            create_extraction_report_payload(well["id"], water_year=2025, month=6,
                                             reported_af=5.000),
            make_well_owner_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_YEAR_MISMATCH)

    def test_duplicate_report_period_rejected(self, api):
        """PRD §3.3: "At most one report may exist per well, water year, and month across all statuses — duplicates are rejected with `ERR_DUPLICATE_REPORT`."

        Design: Corner/validations/duplicate_report_period_rejected
        """
        account, well = setup_account_with_active_production_well(holder_name="Pumper WD-2")
        submit_extraction_report(well["id"], account["id"], month=6, reported_af=5.000)

        resp = api.create_extraction_report(
            create_extraction_report_payload(well["id"], water_year=2026, month=6,
                                             reported_af=7.000),
            make_well_owner_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT)

    def test_domestic_well_report_rejected_exemption(self, api):
        """PRD §3.3: "Submitting against a well that is not `ACTIVE` yields `ERR_WELL_NOT_ACTIVE`; submitting against a non-`PRODUCTION` well yields `ERR_INVALID_WELL_TYPE`."

        Design: Corner/validations/domestic_well_report_rejected_exemption
        """
        account = create_account(holder_name="Household HD", account_type="DOMESTIC",
                                 base_allocation_af=2.000)
        well = create_active_domestic_well(account["id"])
        assert well["status"] == "ACTIVE"

        resp = api.create_extraction_report(
            create_extraction_report_payload(well["id"], water_year=2026, month=6,
                                             reported_af=0.500),
            make_well_owner_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WELL_TYPE)


class TestLateFlag:
    def test_late_flag_boundary_day_15_vs_day_16(self, api):
        """PRD §3.3: "A new report lands in `SUBMITTED` status, its `late_flag` is computed at submission (true exactly when the logical clock has reached the 16th 00:00:00 UTC of the month following the reported `(water_year, month)` — month 12 wraps to January of the following year — so a submission at any instant on the 15th through 23:59:59 is not late), and the reported volume is added to the account's `pending_extraction_af`."

        Design: Corner/calculations/late_flag_boundary_day_15_vs_day_16
        """
        set_clock("2026-07-10T12:00:00Z")
        account = create_account(holder_name="Pumper WL")
        well_1 = create_active_production_well(account["id"], "WL-1")
        well_2 = create_active_production_well(account["id"], "WL-2")

        early = submit_extraction_report(well_1["id"], account["id"], month=6,
                                         reported_af=5.000)
        assert early["late_flag"] is False, (
            "a June report filed 2026-07-10 is before the 2026-07-16T00:00:00Z boundary"
        )

        set_clock("2026-08-01T00:00:00Z")
        late = submit_extraction_report(well_2["id"], account["id"], month=6,
                                        reported_af=5.000)
        assert late["late_flag"] is True, (
            "a June report filed 2026-08-01 is past the 2026-07-16T00:00:00Z boundary"
        )


class TestImmediateConsistency:
    def test_verified_report_immediately_visible_on_account(self, api, water_master_headers):
        """PRD §3.3: "The reported volume moves from `pending_extraction_af` into `extracted_af_ytd`."
        PRD §3.3: "the fee equals `reported_af` multiplied by the base rate of 3000 cents per acre-foot, then multiplied by the basin-condition multiplier in force at the verification instant — 1.00 under `NORMAL`, 1.10 under `WATCH`, and 1.25 under `CRITICAL` — with the per-report result rounded half-up to integer cents."

        Design: Corner/consistency_model/verified_report_immediately_visible_on_account
        """
        account, well = setup_account_with_active_production_well(holder_name="Pumper IC")
        report = submit_extraction_report(well["id"], account["id"], month=6,
                                          reported_af=10.000)
        before = get_account(account["id"])
        assert before["pending_extraction_af"] == pytest.approx(10.000, abs=1e-9)

        verified = validate_success(api.verify_report(report["id"], water_master_headers))
        assert verified["fee_cents"] == 30000, (
            f"10.000 af * 3000 cents/af * NORMAL 1.00 must stamp 30000, got "
            f"{verified['fee_cents']}"
        )

        after = get_account(account["id"])
        assert after["extracted_af_ytd"] == pytest.approx(10.000, abs=1e-9)
        assert after["pending_extraction_af"] == pytest.approx(0.0, abs=1e-9), (
            "the verify ledger move must be fully visible on the very next read"
        )
