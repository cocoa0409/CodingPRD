"""Incentive boundary, staffing allocation, and suspend/resume conservation (PRD §3.2, §3.6)."""
from test_helpers import (
    get_success_data,
    open_statement,
    post_ledger_entry,
    set_clock,
    setup_managed_property,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["pm_headers"]
ACCT = TEST_USERS["acct_headers"]


class TestIncentiveThresholdBoundary:
    def _close_with_egi(self, api, egi_cents, name):
        fx = setup_managed_property(legal_name="Bound Owner LP",
                                    property_name=name, unit_count=100)
        post_ledger_entry(fx["prop"], "RENT", egi_cents, "2026-09",
                          collected_month="2026-09",
                          resident_id=fx["resident"]["id"])
        st = open_statement(fx["prop"], period_month="2026-09", basis="CASH")
        set_clock("2026-10-01T00:00:00Z")
        return validate_success(api.close_statement(st["id"], ACCT))

    def test_incentive_threshold_strictly_greater_boundary(self, api):
        """PRD §3.6: "Using the same basis revenue as effective gross income,
        when EGI is strictly greater than the agreement's
        `incentive_threshold_egi_cents`, `incentive_fee_cents` is the
        agreement's `incentive_tier1_rate` multiplied by the excess of EGI
        over the threshold, rounded half-up to whole cents; otherwise the
        incentive is zero. The boundary is exact: EGI equal to the threshold
        yields zero — strictly greater triggers the tier, greater-than-or-equal
        does not."

        Design: Difficulty/boundary_precision_check/incentive_threshold_strictly_greater_boundary
        """
        at = self._close_with_egi(api, 12000000, "Bound A")
        above = self._close_with_egi(api, 12000010, "Bound B")

        assert at["incentive_fee_cents"] == 0, (
            "EGI == threshold must not trigger the incentive tier"
        )
        # round_half_up(0.10 * 10) == 1
        assert above["incentive_fee_cents"] == 1, (
            f"EGI == threshold + 10 must yield incentive 1, got {above['incentive_fee_cents']}"
        )
        assert at["base_fee_cents"] == 480000
        assert above["base_fee_cents"] == 480000

    def test_incentive_zero_below_threshold_and_scales_above(self, api):
        """PRD §3.6: "when EGI is strictly greater than the agreement's
        `incentive_threshold_egi_cents`, `incentive_fee_cents` is the
        agreement's `incentive_tier1_rate` multiplied by the excess of EGI
        over the threshold, rounded half-up to whole cents; otherwise the
        incentive is zero."

        Design: Difficulty/boundary_precision_check/incentive_threshold_strictly_greater_boundary
        """
        below = self._close_with_egi(api, 11999999, "Bound C")
        well_above = self._close_with_egi(api, 12200000, "Bound D")

        assert below["incentive_fee_cents"] == 0
        # round(0.10 * (12200000 - 12000000)) == 20000
        assert well_above["incentive_fee_cents"] == 20000
        assert well_above["base_fee_cents"] == 488000  # round(0.04 * 12200000)


def _staff_pair(api, region, legal_name, name_a, name_b):
    """Two managed properties in the same region, each with one ACTIVE
    PROPERTY_MANAGER position (3000 cents/hr x 30 hr/wk)."""
    fx_a = setup_managed_property(legal_name=legal_name, property_name=name_a,
                                  unit_count=100)
    fx_b = setup_managed_property(legal_name=legal_name, property_name=name_b,
                                  unit_count=100)
    sp_a = get_success_data(
        api.create_staff(
            fx_a["prop"]["id"],
            {"role_title": "PROPERTY_MANAGER", "hourly_cost_cents": 3000,
             "scheduled_hours_per_week": 30, "shared_region_code": region},
            PM,
        )
    )
    sp_b = get_success_data(
        api.create_staff(
            fx_b["prop"]["id"],
            {"role_title": "PROPERTY_MANAGER", "hourly_cost_cents": 3000,
             "scheduled_hours_per_week": 30, "shared_region_code": region},
            PM,
        )
    )
    return fx_a, fx_b, sp_a, sp_b


class TestStaffingAllocation:
    def test_staffing_allocation_mode_a_nested_conditionals(self, api, acct_headers):
        """PRD §3.6: "the direct cost is its scheduled weekly hours multiplied
        by 4 weeks per month multiplied by its hourly cost. ... the pool is
        charged a regional overhead of 20 percent, and the property's share of
        that overhead is the pool times 0.20 times the ratio of the property's
        direct total to the region's direct total, rounded half-up to whole
        cents — this regional allocation is rounded first, and that rounding
        point is normative. A load of 32 percent is then applied to the sum of
        the property's direct total and its regional share, and that loaded
        amount is rounded half-up to whole cents as a second, separately
        pinned rounding. The statement's `payroll_charge_cents` is the
        property's direct total plus its regional share plus the loaded
        amount."

        Design: Difficulty/combinatorial_formula/staffing_allocation_mode_a_nested_conditionals
        """
        fx_a, _fx_b, _a, _b = _staff_pair(api, "R1", "Staff Owner LP",
                                          "Staff Prop A", "Staff Prop B")
        st = open_statement(fx_a["prop"], period_month="2026-09", basis="CASH")
        set_clock("2026-10-01T00:00:00Z")
        closed = validate_success(api.close_statement(st["id"], acct_headers))

        # direct = 30*4*3000 == 360000; pool = 720000; share = round(720000*0.20*0.5) == 72000
        # loaded = round((360000+72000)*0.32) == 138240; payroll = 360000+72000+138240 == 570240
        assert closed["payroll_charge_cents"] == 570240, (
            f"payroll must be 570240, got {closed['payroll_charge_cents']}"
        )
        assert closed["base_fee_cents"] == 250000  # floor binds at zero revenue
        assert closed["management_fee_total_cents"] == 250000

    def test_staffing_allocation_excludes_inactive_positions_from_pool(self, api, acct_headers):
        """PRD §3.6: "`INACTIVE` positions are excluded from both the direct
        and the regional pool."

        Design: Difficulty/combinatorial_formula/staffing_allocation_mode_a_nested_conditionals
        """
        # Only ONE active position in its region: position 2000 cents/hr x
        # 40 hr/wk -> direct 320000; pool 320000 (only this position);
        # share round(320000*0.20*1.0) == 64000; loaded round(384000*0.32) == 122880;
        # payroll == 320000 + 64000 + 122880 == 506880.
        fx = setup_managed_property(legal_name="Solo Staff LP",
                                    property_name="Solo Staff Prop", unit_count=100)
        get_success_data(
            api.create_staff(
                fx["prop"]["id"],
                {"role_title": "LEASING_AGENT", "hourly_cost_cents": 2000,
                 "scheduled_hours_per_week": 40, "shared_region_code": "RSOLO"},
                PM,
            )
        )
        st = open_statement(fx["prop"], period_month="2026-09", basis="CASH")
        set_clock("2026-10-01T00:00:00Z")
        closed = validate_success(api.close_statement(st["id"], acct_headers))
        assert closed["payroll_charge_cents"] == 506880, (
            f"solo-region payroll must be 506880, got {closed['payroll_charge_cents']}"
        )


class TestSuspendResumeConservation:
    def test_suspend_resume_cycle_conserves_staffing_payroll_charge(self, api, pm_headers, acct_headers):
        """PRD §3.2: "Suspension moves the agreement to `SUSPENDED`, increments
        its `version`, and cascades down to staffing: every `StaffPosition`
        row for the property flips to `INACTIVE`. Resuming a `SUSPENDED`
        agreement returns it to `ACTIVE`, increments `version` again, and
        performs the compensation cascade — the positions that suspension
        pushed to `INACTIVE` return to `ACTIVE`."

        Design: Difficulty/compensating_invariant/suspend_resume_cycle_conserves_staffing_payroll_charge
        """
        fx_a, _fx_b, _a, _b = _staff_pair(api, "R9", "Suspend Owner LP",
                                          "Suspend A", "Suspend B")
        prop_a, ag_a = fx_a["prop"], fx_a["agreement"]
        sm_pre = open_statement(prop_a, period_month="2026-09", basis="CASH")
        sm_during = open_statement(prop_a, period_month="2026-10", basis="CASH")
        sm_post = open_statement(prop_a, period_month="2026-11", basis="CASH")

        set_clock("2026-10-01T00:00:00Z")
        pre = validate_success(api.close_statement(sm_pre["id"], acct_headers))

        get_success_data(api.suspend_agreement(ag_a["id"], pm_headers))
        set_clock("2026-11-01T00:00:00Z")
        during = validate_success(api.close_statement(sm_during["id"], acct_headers))

        get_success_data(api.resume_agreement(ag_a["id"], pm_headers))
        set_clock("2026-12-01T00:00:00Z")
        post = validate_success(api.close_statement(sm_post["id"], acct_headers))

        assert pre["payroll_charge_cents"] == 570240
        assert during["payroll_charge_cents"] == 0, (
            "all P18a positions INACTIVE during suspension -> zero payroll charge"
        )
        assert post["payroll_charge_cents"] == 570240, (
            f"compensation must restore the pre-suspension charge, got {post['payroll_charge_cents']}"
        )

    def test_suspend_resume_payroll_conservation_single_property_region(self, api, pm_headers, acct_headers):
        """PRD §3.2: "Resuming a `SUSPENDED` agreement returns it to `ACTIVE`,
        increments `version` again, and performs the compensation cascade —
        the positions that suspension pushed to `INACTIVE` return to
        `ACTIVE`."

        Design: Difficulty/compensating_invariant/suspend_resume_cycle_conserves_staffing_payroll_charge
        """
        fx = setup_managed_property(legal_name="Conserve Staff LP",
                                    property_name="Conserve Staff Prop", unit_count=100)
        get_success_data(
            api.create_staff(
                fx["prop"]["id"],
                {"role_title": "PROPERTY_MANAGER", "hourly_cost_cents": 2000,
                 "scheduled_hours_per_week": 40, "shared_region_code": "RC1"},
                PM,
            )
        )
        sm_pre = open_statement(fx["prop"], period_month="2026-09", basis="CASH")
        sm_post = open_statement(fx["prop"], period_month="2026-10", basis="CASH")

        set_clock("2026-10-01T00:00:00Z")
        pre = validate_success(api.close_statement(sm_pre["id"], acct_headers))
        get_success_data(api.suspend_agreement(fx["agreement"]["id"], pm_headers))
        get_success_data(api.resume_agreement(fx["agreement"]["id"], pm_headers))
        set_clock("2026-11-01T00:00:00Z")
        post = validate_success(api.close_statement(sm_post["id"], acct_headers))

        # direct 40*4*2000 == 320000; share round(320000*0.2*1.0) == 64000;
        # loaded round(384000*0.32) == 122880; payroll == 506880 pre and post.
        assert pre["payroll_charge_cents"] == 506880
        assert post["payroll_charge_cents"] == pre["payroll_charge_cents"], (
            "payroll charge pre-suspension must equal post-resume (conserved)"
        )
