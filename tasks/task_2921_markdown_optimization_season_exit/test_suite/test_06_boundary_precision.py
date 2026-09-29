"""Off-by-one boundaries: the day on the fence, the gap exactly equal to the
lead, and the last cent of headroom.
"""

from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import markdown_step_payload, zone_execution_payload


def _plan_with_empty_ladder_before_the_boundary(api):
    sc = fx.base_scenario(api)
    fx.set_clock(api, "2026-09-27T00:00:00Z")
    estimate = fx.create_estimate(api, sc.item["id"])
    sc["estimate"] = fx.certify_estimate(api, estimate["id"])
    sc["plan"] = fx.create_plan(api, sc.season["id"], sc.item["id"], sc.estimate["id"])
    return sc


class TestProtectedBoundaryEquality:
    """The protected date itself is closed; the day after is open."""

    def test_a_rung_landing_exactly_on_the_protected_date_is_refused(
        self, api, analyst
    ):
        """PRD 3.5: "No markdown rung may ever take effect on or before that date."
        PRD 2.7 rule 17: "Protected new-arrival period on ladder-rung creation: the
        rung's `effective_date` must be strictly later than the item's
        `protected_until_date`; a rung falling exactly on that date is a violation,
        reported as `ERR_PROTECTED_PERIOD_ACTIVE` (422)."

        Design: Difficulty/boundary_precision_check/protected_boundary_equality_rejected_next_day_accepted
        """
        sc = _plan_with_empty_ladder_before_the_boundary(api)

        response = api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(1, "2026-10-01", 22.57), analyst
        )

        validate_error(response, ApiErrorId.PROTECTED_PERIOD_ACTIVE, 422)
        assert fx.read_plan(api, sc.plan["id"])["ladder_step_count"] == 0

    def test_the_day_after_the_protected_date_is_accepted(self, api, analyst):
        """PRD 3.5: "Depth is always measured off the original ticket, never off the
        live one, so the rung's `price_cents` is the item's `original_retail_cents`
        less the discount, where the discount is `original_retail_cents` multiplied
        by `depth_pct` divided by 100 and rounded half up to a whole cent before the
        subtraction."

        Design: Difficulty/boundary_precision_check/protected_boundary_equality_rejected_next_day_accepted
        """
        sc = _plan_with_empty_ladder_before_the_boundary(api)
        api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(1, "2026-10-01", 22.57), analyst
        )

        step = validate_success(
            api.create_markdown_step(
                sc.plan["id"], markdown_step_payload(1, "2026-10-02", 22.57), analyst
            ),
            201,
        )

        assert step["effective_date"] == "2026-10-02"
        assert step["step_index"] == 1
        assert step["price_cents"] == 3871
        assert step["status"] == "PLANNED"

    def test_the_only_rung_takes_its_window_from_the_exit_target(self, api, analyst):
        """PRD 3.5: "Each new rung also fixes the ladder's occupancy calendar: a
        rung's `window_end_date_exclusive` is set to the plan's
        `exit_date_target` when it is the last rung, and appending a further rung
        rewrites the previous rung's `window_end_date_exclusive` to the new rung's
        `effective_date`, so the rungs tile the plan's calendar as half-open
        windows."

        Design: Difficulty/boundary_precision_check/protected_boundary_equality_rejected_next_day_accepted
        """
        sc = _plan_with_empty_ladder_before_the_boundary(api)
        api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(1, "2026-10-01", 22.57), analyst
        )
        step = validate_success(
            api.create_markdown_step(
                sc.plan["id"], markdown_step_payload(1, "2026-10-02", 22.57), analyst
            ),
            201,
        )

        assert step["window_end_date_exclusive"] == "2027-01-15"
        assert fx.read_plan(api, sc.plan["id"])["ladder_step_count"] == 1
        assert fx.read_item(api, sc.item["id"])["protected_until_date"] == "2026-10-01"


def _two_lead_zones(api):
    season = fx.create_season(api)
    chain_zone = fx.create_chain_zone(api)
    east_zone = fx.create_region_zone(
        api,
        chain_zone["id"],
        zone_code="REGION-EAST",
        region_code="EAST",
        signage_lead_days=28,
    )
    mtn_zone = fx.create_region_zone(
        api,
        chain_zone["id"],
        zone_code="REGION-MTN",
        region_code="MTN",
        signage_lead_days=29,
    )
    item = fx.create_item(api, season["id"])
    fx.transition_season(api, season["id"], "ACTIVE")
    fx.post_history(api, item["id"])
    fx.set_clock(api, fx.WORKING_CLOCK)
    estimate = fx.certified_estimate(api, item["id"])
    plan = fx.create_plan(api, season["id"], item["id"], estimate["id"])
    step1 = fx.add_rung(api, plan["id"], 1, "2026-11-16", 22.57)
    step2 = fx.add_rung(api, plan["id"], 2, "2026-12-14", 35.00)
    fx.submit_plan(api, plan["id"])
    fx.approve_plan(api, plan["id"])
    exec_e1 = fx.schedule_execution(
        api, plan["id"], step1["id"], east_zone["id"], "ZONE", "2026-11-16", 60
    )
    exec_m1 = fx.schedule_execution(
        api, plan["id"], step1["id"], mtn_zone["id"], "ZONE", "2026-11-16", 60
    )
    return fx.Scenario(
        season=season,
        chain_zone=chain_zone,
        east_zone=east_zone,
        mtn_zone=mtn_zone,
        item=item,
        estimate=estimate,
        plan=plan,
        step1=step1,
        step2=step2,
        exec_e1=exec_e1,
        exec_m1=exec_m1,
    )


class TestZoneSpacingEqualToLead:
    """The spacing comparison is inclusive of the zone's own lead."""

    def test_a_gap_exactly_equal_to_the_zone_lead_is_accepted(self, api, analyst):
        """PRD 3.6: "Executions on one item in one zone must also respect the
        signage rhythm: for any two executions on the same `price_zone_id` and item
        that are `SCHEDULED` or `APPLIED`, the gap between their effective dates,
        measured in whole days and ignoring direction, must be at least the zone's
        `signage_lead_days`; a gap exactly equal to that lead is allowed and one day
        less is refused with `ERR_ZONE_SIGNAGE_WINDOW_CONFLICT`."

        Design: Difficulty/boundary_precision_check/zone_spacing_gap_equal_to_lead_accepted_one_day_short_rejected
        """
        sc = _two_lead_zones(api)

        execution = validate_success(
            api.create_zone_execution(
                zone_execution_payload(
                    sc.plan["id"],
                    sc.step2["id"],
                    sc.east_zone["id"],
                    "ZONE",
                    "2026-12-14",
                    60,
                ),
                analyst,
            ),
            201,
        )

        assert execution["status"] == "SCHEDULED"
        assert execution["signage_due_date"] == "2026-11-16"

    def test_a_gap_one_day_short_of_the_zone_lead_is_refused(self, api, analyst):
        """PRD 3.1: "That same number does double duty: it is both the lead time
        required before an execution's effective date in the zone and the minimum
        spacing between two executions on the same item in the zone."

        Design: Difficulty/boundary_precision_check/zone_spacing_gap_equal_to_lead_accepted_one_day_short_rejected
        """
        sc = _two_lead_zones(api)
        fx.schedule_execution(
            api, sc.plan["id"], sc.step2["id"], sc.east_zone["id"], "ZONE",
            "2026-12-14", 60,
        )

        response = api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"], sc.step2["id"], sc.mtn_zone["id"], "ZONE",
                "2026-12-14", 60,
            ),
            analyst,
        )

        validate_error(response, ApiErrorId.ZONE_SIGNAGE_WINDOW_CONFLICT, 409)

    def test_the_conflict_is_scoped_to_the_zone_that_declared_the_lead(
        self, api, analyst
    ):
        """PRD 2.3: "Price zones filter on `zone_type`, `parent_zone_id` and
        `region_code`; stores filter on `price_zone_id`, `status` and `region_code`."

        Design: Difficulty/boundary_precision_check/zone_spacing_gap_equal_to_lead_accepted_one_day_short_rejected
        """
        sc = _two_lead_zones(api)
        fx.schedule_execution(
            api, sc.plan["id"], sc.step2["id"], sc.east_zone["id"], "ZONE",
            "2026-12-14", 60,
        )
        api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"], sc.step2["id"], sc.mtn_zone["id"], "ZONE",
                "2026-12-14", 60,
            ),
            analyst,
        )

        _, east_meta = validate_paginated(
            api.list_zone_executions(analyst, {"price_zone_id": sc.east_zone["id"]})
        )
        _, mtn_meta = validate_paginated(
            api.list_zone_executions(analyst, {"price_zone_id": sc.mtn_zone["id"]})
        )

        assert east_meta["total_count"] == 2
        assert mtn_meta["total_count"] == 1
        assert fx.read_step(api, sc.step2["id"])["status"] == "SCHEDULED"

    def test_each_zone_derives_its_own_signage_due_date(self, api):
        """PRD 3.6: "The signage window must still be open: the `effective_date`
        less the zone's `signage_lead_days` must not already be in the past relative
        to the logical clock's current date, else the execution could never be posted
        in time and is refused with `ERR_SIGNAGE_LEAD_VIOLATION`."

        Design: Difficulty/boundary_precision_check/zone_spacing_gap_equal_to_lead_accepted_one_day_short_rejected
        """
        sc = _two_lead_zones(api)

        assert sc.exec_e1["signage_due_date"] == "2026-10-19"
        assert sc.exec_m1["signage_due_date"] == "2026-10-18"


class TestAllowanceHeadroomOfOneCent:
    """One cent of headroom is still a recognisable amount."""

    def test_the_first_claim_is_bounded_by_its_own_claimed_amount(self, api):
        """PRD 3.8: "Third, the headroom still unclaimed on this plan is that
        eligible total less the plan's `vendor_funded_cents`."

        Design: Difficulty/boundary_precision_check/allowance_headroom_of_exactly_one_cent_is_recognized
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56399)
        fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 5000)

        recognized = fx.recognize_claim(api, claim1["id"])
        agreement = fx.read_agreement(api, sc.agreement["id"])

        assert recognized["recognized_cents"] == 56399
        assert agreement["remaining_cap_cents"] == 1
        assert agreement["status"] == "AGREED"

    def test_a_headroom_of_exactly_one_cent_is_still_recognised(self, api):
        """PRD 3.8: "Fifth, if that smallest quantity is below one cent there is
        nothing to recognise and the request is refused with
        `ERR_ALLOWANCE_CAP_EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/allowance_headroom_of_exactly_one_cent_is_recognized
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56399)
        claim2 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 5000)
        fx.recognize_claim(api, claim1["id"])

        second = fx.recognize_claim(api, claim2["id"])

        assert second["recognized_cents"] == 1
        assert second["status"] == "RECOGNIZED"
        assert second["rejection_reason"] is None

    def test_the_last_cent_exhausts_the_cap_and_funds_the_agreement(self, api):
        """PRD 2.7 rule 31: "Allowance cap on claim recognition: the recognition
        arithmetic must yield at least 1 cent, else `ERR_ALLOWANCE_CAP_EXHAUSTED`
        (409)."

        Design: Difficulty/boundary_precision_check/allowance_headroom_of_exactly_one_cent_is_recognized
        """
        sc = fx.executing_plan_with_agreement(api, share_pct=25.00, cap_cents=56400)
        claim1 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 56399)
        claim2 = fx.create_claim(api, sc.agreement["id"], sc.plan["id"], 5000)
        fx.recognize_claim(api, claim1["id"])
        fx.recognize_claim(api, claim2["id"])

        agreement = fx.read_agreement(api, sc.agreement["id"])
        plan = fx.read_plan(api, sc.plan["id"])

        assert agreement["recognized_total_cents"] == 56400
        assert agreement["remaining_cap_cents"] == 0
        assert agreement["status"] == "FUNDED"
        assert plan["vendor_funded_cents"] == 56400
        assert plan["net_markdown_cents"] == 169200
