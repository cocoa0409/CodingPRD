"""Payroll periods: overlap/close-order guards, accrual splits, clawbacks, and
the append-only entry resource (PRD Sections 2.5, 2.6, 3.7)."""
from test_helpers import (
    ApiErrorId,
    activate_fall_term,
    assert_payroll_entry,
    create_payroll_period,
    create_section,
    get_faculty,
    get_success_data,
    issue_contract,
    issue_contract_in,
    lock_and_close_period,
    lock_period,
    set_clock,
    setup_accrued_pch_scenario,
    setup_active_contract_scenario,
    setup_fall_payroll_periods,
    standard_fall_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["hr_admin_headers"]
CHAIR = TEST_USERS["chair_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


class TestPayrollEntryResource:
    def test_payroll_entry_immutable_no_update_endpoint(self, api, payroll_headers):
        """PRD Section 2.5: "Payroll entries and evaluation records carry only `id`
        and `created_at`; both `updated_at` and `version` are absent from those two
        resources."
        PRD Section 3.7: "No endpoint creates payroll entries directly; they exist
        only as the output of close runs and cancellation clawbacks."
        PRD Section 3.7: "Under `EQUAL_SPLIT`, the contract's `payable_cents` is
        divided by the number of overlapping periods using integer division that
        discards any fractional cent, giving every period the same base amount"

        With exactly one overlapping period, P1's EQUAL_SPLIT slice is the whole
        450,000-cent payable.

        Design: Corner/entities/payroll_entry_immutable_no_update_endpoint
        """
        scn = setup_active_contract_scenario(dept_code="IMMU", load_cap_units=9.00)
        p1 = create_payroll_period("2026FA-P1", "2026-08-24", "2026-09-20")
        lock_and_close_period(p1["id"])

        entries, meta = validate_paginated(
            api.list_contract_payroll_entries(scn["contract"]["id"], payroll_headers))
        assert meta["total_count"] == 1
        entry = entries[0]
        assert_payroll_entry(entry)
        assert entry["entry_kind"] == "ACCRUAL"
        assert entry["split_variant"] == "EQUAL_SPLIT", (
            "PER_COURSE contracts accrue under EQUAL_SPLIT"
        )
        assert entry["amount_cents"] == 450000
        assert entry["payroll_period_id"] == p1["id"]


class TestPeriodOverlap:
    def test_payroll_period_touching_endpoints_overlap(self, api):
        """PRD Section 3.7: "Creation is refused with `ERR_PAYROLL_PERIOD_OVERLAP`
        when the new period's closed window intersects any existing period not yet
        `CLOSED` — and because payroll intervals are closed, a new period whose
        start date equals an existing open period's end date already counts as
        overlapping."

        Design: Difficulty/resource_temporal_overlap/payroll_period_closed_interval_touching_endpoints_overlap
        """
        create_payroll_period("2026FA-P1", "2026-08-24", "2026-09-20")
        touching = api.create_payroll_period(
            {"period_code": "2026FA-P2", "start_date": "2026-09-20", "end_date": "2026-10-18"},
            PAYROLL,
        )
        validate_error(touching, ApiErrorId.ERR_PAYROLL_PERIOD_OVERLAP)

    def test_payroll_period_one_day_gap_allowed(self, api):
        """PRD Section 2.9: "Payroll periods use closed intervals: a new period
        whose `start_date`-to-`end_date` span merely touches an existing
        non-`CLOSED` period's span — one's end date equal to the other's start date
        — counts as an overlap and is rejected."

        A one-day gap (2026-09-21 > 2026-09-20) creates no closed-interval
        intersection, so creation succeeds.

        Design: Difficulty/resource_temporal_overlap/payroll_period_closed_interval_touching_endpoints_overlap
        """
        create_payroll_period("2026FA-P1", "2026-08-24", "2026-09-20")
        ok = api.create_payroll_period(
            {"period_code": "2026FA-P2B", "start_date": "2026-09-21", "end_date": "2026-10-18"},
            PAYROLL,
        )
        period = validate_success(ok, 201)
        assert period["period_status"] == "OPEN"


class TestCloseOrder:
    def test_payroll_period_double_close_and_lock_ordering(self, api, payroll_headers):
        """PRD Section 3.7: "A period begins `OPEN`, moves to `LOCKED` at the
        officer's lock action, and moves from `LOCKED` to `CLOSED` at the close
        action." — closing an `OPEN` period has no transition and fails the state
        gate with `ERR_INVALID_STATE` (Section 2.8).
        PRD Section 3.7: "Closing is the checkpoint that materializes payroll
        entries, and it is chronologically disciplined: a period may close only
        after every period with an earlier `start_date` is already `CLOSED`, and an
        already-`CLOSED` period rejects any further close; violations of either
        rule surface as `ERR_PAYROLL_CLOSE_ORDER`."

        Design: Corner/state_machines/payroll_period_double_close_and_lock_ordering
        """
        p1 = create_payroll_period("2026FA-P1", "2026-08-24", "2026-09-20")
        p2 = create_payroll_period("2026FA-P2", "2026-09-21", "2026-10-18")
        lock_period(p2["id"])

        from_open = api.close_payroll_period(p1["id"], PAYROLL)
        validate_error(from_open, ApiErrorId.ERR_INVALID_STATE)

        out_of_order = api.close_payroll_period(p2["id"], PAYROLL)
        validate_error(out_of_order, ApiErrorId.ERR_PAYROLL_CLOSE_ORDER)

        p1_after = get_success_data(api.get_payroll_period(p1["id"], payroll_headers))
        p2_after = get_success_data(api.get_payroll_period(p2["id"], payroll_headers))
        assert p1_after["period_status"] == "OPEN"
        assert p2_after["period_status"] == "LOCKED"


class TestDaysWeightedSplit:
    def test_days_weighted_split_remainder_sweep_makes_total_exact(self, api, payroll_headers):
        """PRD Section 3.7: "Under `DAYS_WEIGHTED`, each period's overlap days are
        counted as the calendar dates falling inside both the period's inclusive
        window and the term's inclusive window; walking the overlapping periods in
        chronological order — `start_date` ascending, ties by `created_at`
        ascending — every period except the last receives the payable multiplied by
        the ratio of its overlap days to the total overlap days, rounded half up to
        whole cents, and the chronologically last period receives whatever remains
        of `payable_cents` after the earlier slices, so rounding residue is swept
        into the final period and the per-contract total is always exact."

        Overlap days 28/35/47 (sum 110) over payable 9,000,000:
        [rhu(9000000*28/110), rhu(9000000*35/110), remainder] = [2290909, 2863636,
        3845455].

        Design: Corner/calculations/days_weighted_split_remainder_sweep_makes_total_exact
        """
        scn = setup_active_contract_scenario(
            dept_code="SWEP", load_cap_units=9.00,
            rate_basis="PER_CONTACT_HOUR", base_rate_cents=200000,
            longevity_step_cents=0, longevity_step_cap=0,
            weekly_contact_hours=3.0,
        )
        q1 = create_payroll_period("2026FA-Q1", "2026-08-24", "2026-09-20")
        q2 = create_payroll_period("2026FA-Q2", "2026-09-21", "2026-10-25")
        q3 = create_payroll_period("2026FA-Q3", "2026-10-26", "2026-12-13")
        expected = {q1["id"]: 2290909, q2["id"]: 2863636, q3["id"]: 3845455}
        for period in (q1, q2, q3):
            lock_and_close_period(period["id"])

        total = 0
        for period in (q1, q2, q3):
            entries, meta = validate_paginated(api.list_period_payroll_entries(
                period["id"], payroll_headers,
                params={"contract_id": scn["contract"]["id"], "entry_kind": "ACCRUAL"},
            ))
            assert meta["total_count"] == 1, "each close posts exactly this period's slice"
            entry = entries[0]
            assert entry["split_variant"] == "DAYS_WEIGHTED"
            assert entry["amount_cents"] == expected[period["id"]], (
                f"slice for {period['period_code']}"
            )
            total += entry["amount_cents"]
        assert total == 9000000, (
            "the remainder sweep keeps the per-contract total exact"
        )


class TestCancelClawbackCascade:
    def test_section_cancel_depth3_cascade_to_payroll_clawback(self, api, payroll_headers):
        """PRD Section 3.7: "When a cancellation reduces a contract's payable after
        earlier periods have closed, the excess of prior accruals over the new
        `payable_cents` is reversed through `CLAWBACK` entries posted into the
        earliest period still `OPEN` — earliest `start_date`, ties by earliest
        `created_at` — or, when no `OPEN` period exists, into the period currently
        being closed."
        PRD Section 3.7: "Every entry records its `contract_id`, its
        `payroll_period_id`, its `entry_kind` (`ACCRUAL`, `CANCELLATION_PAYOUT`, or
        `CLAWBACK`), a signed `amount_cents`, the `split_variant` that produced it,
        a `posted_at` timestamp from the close run, and — on clawbacks — a
        `reversal_of_entry_id` naming the accrual it reverses."

        Accrued 2,290,909 in P1; late-tier cancellation at the early-census
        boundary reprices payable to 2,250,000; the 40,909 excess is clawed back
        into P2.

        Design: Difficulty/transitive_cascade/section_cancel_depth3_cascade_to_payroll_clawback
        """
        scn, sec_small, con_small, periods = _two_contract_accrued_fixture("PHYS")
        set_clock("2026-09-14T09:00:00Z")
        get_success_data(api.cancel_section(
            scn["section"]["id"], {"cancellation_reason": "PROGRAM_CUT"}, CHAIR))

        contract = get_success_data(api.get_contract(scn["contract"]["id"], ADMIN))
        assert contract["contract_status"] == "CANCELLED_LATE"
        assert contract["payable_cents"] == 2250000, (
            "earned rhu(9000000*22/110)=1800000 loses to the 2250000 floor"
        )

        clawbacks, meta = validate_paginated(api.list_period_payroll_entries(
            periods[1]["id"], payroll_headers, params={"entry_kind": "CLAWBACK"}))
        assert meta["total_count"] == 1
        clawback = clawbacks[0]
        assert_payroll_entry(clawback)
        assert clawback["amount_cents"] == -40909, (
            "accrued 2290909 minus payable 2250000 reversed (negative on clawbacks)"
        )
        assert clawback["contract_id"] == scn["contract"]["id"]

        accruals, _ = validate_paginated(api.list_period_payroll_entries(
            periods[0]["id"], payroll_headers,
            params={"contract_id": scn["contract"]["id"], "entry_kind": "ACCRUAL"}))
        assert clawback["reversal_of_entry_id"] == accruals[0]["id"], (
            "the clawback names the P1 accrual it reverses"
        )

    def test_section_cancel_cascade_recomputes_load_and_spares_sibling(self, api):
        """PRD Section 3.6: "Both paths recompute every affected faculty member's
        load aggregates, bump the section's `version`, and reprice each cancelled
        contract"
        PRD Section 3.4: "The authoritative actual variant sums `load_units` over
        contracts in `ACTIVE` status only"

        After the big section's cancellation the faculty keeps only the sibling's
        1.50 ACTIVE load and drops below the 4.50 cap.

        Design: Difficulty/transitive_cascade/section_cancel_depth3_cascade_to_payroll_clawback
        """
        scn, sec_small, con_small, periods = _two_contract_accrued_fixture("PHY2")
        set_clock("2026-09-14T09:00:00Z")
        get_success_data(api.cancel_section(
            scn["section"]["id"], {"cancellation_reason": "PROGRAM_CUT"}, CHAIR))

        faculty = get_faculty(scn["faculty"]["id"])
        assert faculty["current_term_load_units"] == 1.50, (
            "only the sibling ACTIVE contract still counts"
        )
        assert faculty["benefits_eligible"] is False, "1.50 < 4.50 flips the flag"
        sibling = get_success_data(api.get_contract(con_small["id"], ADMIN))
        assert sibling["contract_status"] == "ACTIVE", (
            "the sibling section's contract is untouched by the cascade"
        )


class TestAccrualClawbackInvariant:
    def test_payroll_accrual_plus_clawback_conserves_payable(self, api, payroll_headers):
        """PRD Section 2.6: "All money in the system is integer cents." and payroll
        entries "carry a signed `amount_cents` that is negative on clawbacks."
        PRD Section 3.7: "the excess of prior accruals over the new `payable_cents`
        is reversed through `CLAWBACK` entries"

        Invariant: the signed sum of a contract's payroll entries equals its
        payable after the compensating pair: 2,290,909 + (-40,909) == 2,250,000.

        Design: Difficulty/compensating_invariant/payroll_accrual_plus_clawback_conserves_payable
        """
        scn, periods = setup_accrued_pch_scenario(dept_code="STAT")
        set_clock("2026-09-14T09:00:00Z")
        get_success_data(api.cancel_section(
            scn["section"]["id"], {"cancellation_reason": "ADMINISTRATIVE"}, CHAIR))

        entries, _ = validate_paginated(
            api.list_contract_payroll_entries(scn["contract"]["id"], payroll_headers))
        signed_total = sum(e["amount_cents"] for e in entries)
        contract = get_success_data(api.get_contract(scn["contract"]["id"], ADMIN))
        assert contract["payable_cents"] == 2250000
        assert signed_total == contract["payable_cents"], (
            "accrual + compensating clawback conserves payable with zero drift"
        )

    def test_exactly_one_clawback_reversing_the_p1_accrual(self, api, payroll_headers):
        """PRD Section 3.7: "on clawbacks — a `reversal_of_entry_id` naming the
        accrual it reverses"
        PRD Section 3.7: "the excess of prior accruals over the new `payable_cents`
        is reversed through `CLAWBACK` entries posted into the earliest period
        still `OPEN`"

        Design: Difficulty/compensating_invariant/payroll_accrual_plus_clawback_conserves_payable
        """
        scn, periods = setup_accrued_pch_scenario(dept_code="STA2")
        set_clock("2026-09-14T09:00:00Z")
        get_success_data(api.cancel_section(
            scn["section"]["id"], {"cancellation_reason": "ADMINISTRATIVE"}, CHAIR))

        clawbacks, meta = validate_paginated(api.list_contract_payroll_entries(
            scn["contract"]["id"], payroll_headers, params={"entry_kind": "CLAWBACK"}))
        assert meta["total_count"] == 1, "exactly one compensating clawback"
        clawback = clawbacks[0]
        assert clawback["payroll_period_id"] == periods[1]["id"], (
            "posted into the earliest still-OPEN period (P2)"
        )
        accruals, _ = validate_paginated(api.list_contract_payroll_entries(
            scn["contract"]["id"], payroll_headers, params={"entry_kind": "ACCRUAL"}))
        assert len(accruals) == 1
        assert clawback["reversal_of_entry_id"] == accruals[0]["id"]


def _two_contract_accrued_fixture(dept_code):
    """Faculty with two ACTIVE contracts (3.00 + 1.50 load) and P1 CLOSED.

    Both contracts are issued before the clock reaches the term start so both
    activate together; all four canonical periods exist before P1 closes.
    P1 accruals: 2,290,909 (gross 9,000,000) and 1,145,455 (gross 4,500,000).
    """
    scn = standard_fall_scenario(
        dept_code=dept_code, load_cap_units=4.50,
        rate_basis="PER_CONTACT_HOUR", base_rate_cents=200000,
        longevity_step_cents=5000, longevity_step_cap=5,
        weekly_contact_hours=3.0, course_code="PHY-101",
    )
    sec_small = create_section(scn["dept"]["id"], term_code="2026FA",
                               course_code="PHY-110", weekly_contact_hours=1.5,
                               credit_hours=1, enrollment=20)
    con_big = issue_contract_in(scn)
    con_small = issue_contract(
        scn["faculty"]["id"], sec_small["id"], scn["schedule"]["id"])
    periods = setup_fall_payroll_periods()
    activate_fall_term()
    lock_and_close_period(periods[0]["id"])
    scn["contract"] = con_big
    return scn, sec_small, con_small, periods
