"""Pumping fees, the tiered overdraft penalty, and the verify-triggered cascade
(PRD §3.3, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_penalty_assessment,
    create_account,
    create_penalty_assessment_payload,
    get_account,
    make_enforcement_officer_headers,
    setup_account_with_active_production_well,
    setup_account_with_verified_extraction,
    submit_and_verify_report,
    submit_extraction_report,
    validate_error,
    validate_paginated,
    validate_success,
    verify_report,
)


class TestTieredOverdraftPenalty:
    def test_overdraft_penalty_tiered_marginal_calculation(self, api, water_master_headers):
        """PRD §3.6: "The first tier covers the portion of the overdraft up to ten percent of the account's `base_allocation_af` (the tier-1 limit itself rounded half-up to 3 decimals) and is priced at 10000 cents per acre-foot; any overdraft above that limit falls into the second tier at 25000 cents per acre-foot."
        PRD §3.3: "If the overdraft was zero or negative before this verification and is strictly positive after it, the system auto-creates a `PenaltyAssessment` with `reason` `OVERDRAFT`, the report's `water_year`, an `overdraft_af` equal to the computed overdraft, and `assessed_by` set to the literal string `system`, and the new penalty's `amount_cents` is debited into the account's `penalty_balance_cents`."

        Design: Difficulty/combinatorial_formula/overdraft_penalty_tiered_marginal_calculation
        """
        # Allocation 200.000, verified extraction 250.000, condition NORMAL:
        # overdraft 50.000, tier-1 limit round3(0.10*200)=20.000,
        # amount = (20*10000 + 30*25000) * 1.00 = 950000 cents.
        account, well, _report = setup_account_with_verified_extraction(
            200.000, 250.000, holder_name="Pumper C"
        )

        data, meta = validate_paginated(
            api.list_penalty_assessments(water_master_headers,
                                         params={"account_id": account["id"]})
        )
        assert meta["total_count"] == 1, f"exactly one auto assessment expected, got {meta['total_count']}"
        auto = data[0]
        assert_penalty_assessment(auto)
        assert auto["reason"] == "OVERDRAFT"
        assert auto["overdraft_af"] == pytest.approx(50.000, abs=1e-9), (
            f"overdraft_af must equal the computed overdraft 50.000, got {auto['overdraft_af']}"
        )
        assert auto["amount_cents"] == 950000, (
            f"tiered schedule: min(50,20)*10000 + max(0,50-20)*25000 = 950000, got "
            f"{auto['amount_cents']}"
        )
        assert auto["assessed_by"] == "system", (
            f"the cascade assessment must be stamped assessed_by 'system', got {auto['assessed_by']!r}"
        )
        assert auto["water_year"] == 2026

        account_after = get_account(account["id"])
        assert account_after["penalty_balance_cents"] == 950000

    def test_manual_overdraft_amount_must_match_computed(self, api):
        """PRD §3.6: "The conditional field is required if and only if `reason` is `OVERDRAFT`, must be absent otherwise (`ERR_INVALID_REQUEST`), and when present must equal the computed overdraft volume at 3-decimal comparison or the filing is rejected with `ERR_OVERDRAFT_AMOUNT_MISMATCH`."

        Design: Difficulty/combinatorial_formula/overdraft_penalty_tiered_marginal_calculation
        """
        account, _well, _report = setup_account_with_verified_extraction(
            200.000, 250.000, holder_name="Pumper C2"
        )

        mismatch = api.create_penalty_assessment(
            create_penalty_assessment_payload(account["id"], reason="OVERDRAFT",
                                              water_year=2026, overdraft_af=49.999),
            make_enforcement_officer_headers("eo-1"),
        )
        validate_error(mismatch, ApiErrorId.ERR_OVERDRAFT_AMOUNT_MISMATCH)

        exact = api.create_penalty_assessment(
            create_penalty_assessment_payload(account["id"], reason="OVERDRAFT",
                                              water_year=2026, overdraft_af=50.000),
            make_enforcement_officer_headers("eo-1"),
        )
        manual = validate_success(exact, 201)
        assert manual["amount_cents"] == 950000, (
            f"a manual assessment matching the computed 50.000 overdraft must price at "
            f"950000 cents, got {manual['amount_cents']}"
        )
        assert manual["assessed_by"] == "eo-1"


class TestVerifyOverdraftCascade:
    def test_verify_triggers_overdraft_penalty_chain(self, api, water_master_headers):
        """PRD §3.3: "If the overdraft was zero or negative before this verification and is strictly positive after it, the system auto-creates a `PenaltyAssessment` with `reason` `OVERDRAFT`, the report's `water_year`, an `overdraft_af` equal to the computed overdraft, and `assessed_by` set to the literal string `system`, and the new penalty's `amount_cents` is debited into the account's `penalty_balance_cents`."

        Design: Difficulty/transitive_cascade/verify_triggers_overdraft_penalty_chain
        """
        # Allocation 50.000; verify 60.000 -> overdraft 10.000, tier-1 limit 5.000,
        # amount = 5*10000 + 5*25000 = 175000; a second verify while already
        # overdrawn is not a new crossing and creates nothing.
        account, well = setup_account_with_active_production_well(
            holder_name="Pumper G", base_allocation_af=50.000
        )
        report_1 = submit_extraction_report(well["id"], account["id"], month=6,
                                            reported_af=60.000)
        report_2 = submit_extraction_report(well["id"], account["id"], month=7,
                                            reported_af=5.000)

        verify_report(report_1["id"])
        data, meta = validate_paginated(
            api.list_penalty_assessments(water_master_headers,
                                         params={"account_id": account["id"]})
        )
        assert meta["total_count"] == 1
        auto = data[0]
        assert auto["reason"] == "OVERDRAFT" and auto["assessed_by"] == "system"
        assert auto["amount_cents"] == 175000, (
            f"5*10000 + 5*25000 at NORMAL multiplier 1.00 = 175000, got {auto['amount_cents']}"
        )

        account_mid = get_account(account["id"])
        assert account_mid["extracted_af_ytd"] == pytest.approx(60.000, abs=1e-9)
        assert account_mid["penalty_balance_cents"] == 175000, (
            "the cascade's assessment creation itself must debit the penalty ledger"
        )

        verify_report(report_2["id"])
        data2, meta2 = validate_paginated(
            api.list_penalty_assessments(water_master_headers,
                                         params={"account_id": account["id"]})
        )
        assert meta2["total_count"] == 1, (
            "the second verify crosses nothing (overdraft was already positive), so no "
            "new assessment may be created"
        )
        assert data2[0]["amount_cents"] == 175000

    def test_no_overdraft_penalty_at_exactly_zero_crossing(self, api, water_master_headers):
        """PRD §3.3: "If the overdraft was zero or negative before this verification and is strictly positive after it, the system auto-creates a `PenaltyAssessment` with `reason` `OVERDRAFT`, the report's `water_year`, an `overdraft_af` equal to the computed overdraft, and `assessed_by` set to the literal string `system`, and the new penalty's `amount_cents` is debited into the account's `penalty_balance_cents`."
        PRD §3.6: "The overdraft volume itself is the settled-basis figure: the greater of zero and `extracted_af_ytd` minus the effective allocation minus `credit_balance_af` plus `transfer_out_af_ytd`, rounded half-up to 3 decimals."

        Design: Difficulty/transitive_cascade/verify_triggers_overdraft_penalty_chain
        """
        # Allocation 50.000: verify exactly 50.000 -> overdraft 0 (not strictly
        # positive) -> no assessment; then verify 0.001 -> overdraft 0.001 > 0, a
        # genuine crossing -> one assessment of round_half_up(0.001*10000) = 10 cents.
        account, well = setup_account_with_active_production_well(
            holder_name="Pumper G2", base_allocation_af=50.000
        )
        r_full = submit_extraction_report(well["id"], account["id"], month=6,
                                          reported_af=50.000)
        verify_report(r_full["id"])
        data, meta = validate_paginated(
            api.list_penalty_assessments(water_master_headers,
                                         params={"account_id": account["id"]})
        )
        assert meta["total_count"] == 0, (
            "an overdraft of exactly zero is not strictly positive, so nothing is created"
        )

        r_over = submit_extraction_report(well["id"], account["id"], month=7,
                                          reported_af=0.001)
        verify_report(r_over["id"])
        data2, meta2 = validate_paginated(
            api.list_penalty_assessments(water_master_headers,
                                         params={"account_id": account["id"]})
        )
        assert meta2["total_count"] == 1
        auto = data2[0]
        assert auto["reason"] == "OVERDRAFT" and auto["assessed_by"] == "system"
        assert auto["overdraft_af"] == pytest.approx(0.001, abs=1e-9)
        assert auto["amount_cents"] == 10, (
            f"0.001 af within tier 1 at 10000 cents/af rounds to 10 cents, got "
            f"{auto['amount_cents']}"
        )
        account_after = get_account(account["id"])
        assert account_after["penalty_balance_cents"] == 10


class TestPenaltyCreation:
    def test_penalty_creation_records_assessor_and_debits_balance(self, api):
        """PRD §3.6: "For `LATE_REPORT` the fee is a flat 10000 cents; for `UNMETERED_PUMPING` it is a flat 50000 cents; flat fees are never multiplied by the basin-condition multiplier."
        PRD §3.6: "A new assessment starts in `ASSESSED` status, `assessed_by` is stamped from the caller's `X-User-ID` (or the literal `system` for the auto-created cascade), and the account's `penalty_balance_cents` increases by `amount_cents`."

        Design: Corner/state_machines/penalty_creation_records_assessor_and_debits_balance
        """
        account = create_account(holder_name="Pumper PA-1")

        resp = api.create_penalty_assessment(
            create_penalty_assessment_payload(account["id"], reason="LATE_REPORT",
                                              water_year=2026),
            make_enforcement_officer_headers("eo-1"),
        )
        assessment = validate_success(resp, 201)
        assert_penalty_assessment(assessment)
        assert assessment["status"] == "ASSESSED"
        assert assessment["assessed_by"] == "eo-1", (
            f"assessed_by must be stamped from the caller's X-User-ID, got "
            f"{assessment['assessed_by']!r}"
        )
        assert assessment["amount_cents"] == 10000, (
            f"LATE_REPORT carries a flat 10000-cent fee, got {assessment['amount_cents']}"
        )

        account_after = get_account(account["id"])
        assert account_after["penalty_balance_cents"] == 10000, (
            "creation must immediately debit the account ledger"
        )
