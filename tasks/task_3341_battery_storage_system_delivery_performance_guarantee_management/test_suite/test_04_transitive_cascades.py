"""Transitive cascade tests: LD-cap termination cascade and lazy LTSA expiry
cascade with credit restoration."""
from test_helpers import (
    TEST_USERS,
    create_claim,
    create_milestone,
    create_order,
    create_project,
    get_success_data,
    set_clock,
    setup_active_ltsa,
    setup_executed_project,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
SVC_MGR = TEST_USERS["service_manager_headers"]
SVC_ENG = TEST_USERS["service_engineer_headers"]


class TestMissedMilestoneLdCapTerminationCascade:
    def test_cap_reached_terminates_esa_and_cascades(self, api):
        """PRD §3.3: "The terminal boundary is exact equality: when
        `accrued_ld_cents` reaches `ld_cap_cents` and the cap is greater than
        zero, the agreement automatically transitions from `EXECUTED` to
        `TERMINATED`, and the termination cascades — every still-`SCHEDULED`
        milestone of the agreement becomes `CANCELLED`; every spare-part order
        in `ORDERED` status whose `warranty_claim_id` references a warranty
        claim of this agreement becomes `CANCELLED`, with any credit-covered
        order returning its draw to the service agreement's
        `credit_drawn_cents`; and every warranty claim of the agreement in
        `SUBMITTED` or `UNDER_REVIEW` becomes `REJECTED`."

        Design: Difficulty/transitive_cascade/missed_milestone_ld_cap_terminates_esa_and_cascades
        """
        project, esa = setup_executed_project(
            api=api,
            esa_overrides={"ld_rate_per_day_cents": 40000, "ld_cap_cents": 1200000},
        )
        m1 = create_milestone(esa["id"], "DELIVERY", "2026-10-01T00:00:00Z", api=api)
        m2 = create_milestone(esa["id"], "DELIVERY", "2026-10-05T00:00:00Z", api=api)
        m3 = create_milestone(esa["id"], "COMMISSIONING", "2026-11-01T00:00:00Z", api=api)
        claim = create_claim(
            esa["id"], api=api, defect_type="BMS_FAULT", claimed_capacity_loss_mwh=0.5
        )

        d1 = validate_success(
            api.record_milestone_outcome(
                m1["id"], {"outcome": "MISSED", "actual_date": "2026-10-21T00:00:00Z"}, DEV
            )
        )
        assert d1["days_late"] == 20 and d1["ld_applied_cents"] == 800000, (
            f"20 days * 40000 == 800000, got days_late={d1['days_late']} "
            f"ld={d1['ld_applied_cents']}"
        )
        d2 = validate_success(
            api.record_milestone_outcome(
                m2["id"], {"outcome": "MISSED", "actual_date": "2026-10-20T00:00:00Z"}, DEV
            )
        )
        # headroom 1200000-800000=400000 -> effective days min(15, 10) = 10 -> 400000
        assert d2["days_late"] == 15 and d2["ld_applied_cents"] == 400000, (
            f"headroom-capped: 10 * 40000 == 400000, got days_late={d2['days_late']} "
            f"ld={d2['ld_applied_cents']}"
        )

        esa_after = get_success_data(api.get_esa(esa["id"], DEV))
        assert esa_after["accrued_ld_cents"] == 1200000
        assert esa_after["net_ld_due_cents"] == 1200000
        assert esa_after["status"] == "TERMINATED", (
            f"accrued == cap must auto-terminate, got {esa_after['status']}"
        )

        m3_after = get_success_data(api.get_milestone(m3["id"], DEV))
        assert m3_after["status"] == "CANCELLED", (
            "still-SCHEDULED milestones cascade to CANCELLED"
        )
        claim_after = get_success_data(api.get_warranty_claim(claim["id"], DEV))
        assert claim_after["status"] == "REJECTED", (
            "SUBMITTED claims cascade to REJECTED"
        )

    def test_under_cap_accrual_leaves_esa_executed(self, api):
        """PRD §3.3: "the effective chargeable days are the lesser of
        `days_late` and the whole-day count that fits in the headroom at
        `ld_rate_per_day_cents` per day (zero effective days when the daily
        rate is zero); and `ld_applied_cents` is the effective days multiplied
        by the daily rate."
        PRD §3.3: "when `accrued_ld_cents` reaches `ld_cap_cents` and the cap
        is greater than zero, the agreement automatically transitions from
        `EXECUTED` to `TERMINATED`"

        Design: Difficulty/transitive_cascade/missed_milestone_ld_cap_terminates_esa_and_cascades
        """
        project, esa = setup_executed_project(
            api=api,
            esa_overrides={"ld_rate_per_day_cents": 40000, "ld_cap_cents": 1200000},
        )
        m1 = create_milestone(esa["id"], "DELIVERY", "2026-10-01T00:00:00Z", api=api)
        claim = create_claim(esa["id"], api=api)

        # 10 days late -> 400000 accrued, below the cap of 1200000.
        d1 = validate_success(
            api.record_milestone_outcome(
                m1["id"], {"outcome": "MISSED", "actual_date": "2026-10-11T00:00:00Z"}, DEV
            )
        )
        assert d1["days_late"] == 10 and d1["ld_applied_cents"] == 400000
        esa_after = get_success_data(api.get_esa(esa["id"], DEV))
        assert esa_after["status"] == "EXECUTED", (
            "accrued below cap: no termination"
        )
        assert esa_after["accrued_ld_cents"] == 400000
        claim_after = get_success_data(api.get_warranty_claim(claim["id"], DEV))
        assert claim_after["status"] == "SUBMITTED", (
            "no termination -> claim untouched"
        )


class TestLtsaLazyExpiryCascade:
    def test_expiry_cancels_shipped_order_and_restores_credit(self, api):
        """PRD §3.6: "Expiry is lazy. There is no background sweeper; instead,
        the first read or write that touches an agreement whose `end_date` has
        passed — from either `ACTIVE` or `SUSPENDED` — flips it to `EXPIRED`
        and runs the expiry cascade: every spare-part order of the agreement in
        `ORDERED` or `SHIPPED` status becomes `CANCELLED`, and each
        credit-covered order returns its `part_cost_cents` to
        `credit_drawn_cents`."
        PRD §3.6: "The pool itself is historical and is never rewritten;
        `credit_drawn_cents` is simply recomputed after the cascade."

        Design: Difficulty/transitive_cascade/ltsa_lazy_expiry_cancels_orders_and_restores_credit
        """
        project = create_project(api=api)
        ltsa = setup_active_ltsa(
            project["id"],
            api=api,
            annual_fee_cents=2_000_000,
            covers_software_updates=False,
            start_date="2026-08-01T00:00:00Z",
            end_date="2026-09-20T00:00:00Z",
        )
        assert ltsa["credit_pool_cents"] == 600000

        order = create_order(
            ltsa["id"], api=api, part_description="HVAC module",
            part_cost_cents=400000,
        )
        assert order["covered_by_credit"] is True
        shipped = validate_success(api.ship_order(order["id"], SVC_ENG))
        assert shipped["status"] == "SHIPPED"
        mid = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        assert mid["credit_drawn_cents"] == 400000

        set_clock("2026-09-21T00:00:00Z", api=api)
        expired = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        assert expired["status"] == "EXPIRED", (
            f"read past end_date flips to EXPIRED, got {expired['status']}"
        )
        assert expired["credit_drawn_cents"] == 0, (
            "covered SHIPPED order cancelled by cascade -> draw restored"
        )
        assert expired["credit_pool_cents"] == 600000, (
            "pool is historical, never rewritten"
        )
        order_after = get_success_data(api.get_spare_part_order(order["id"], SVC_MGR))
        assert order_after["status"] == "CANCELLED"

    def test_expiry_from_suspended_also_cascades(self, api):
        """PRD §3.6: "the first read or write that touches an agreement whose
        `end_date` has passed — from either `ACTIVE` or `SUSPENDED` — flips it
        to `EXPIRED` and runs the expiry cascade"

        Design: Difficulty/transitive_cascade/ltsa_lazy_expiry_cancels_orders_and_restores_credit
        """
        project = create_project(api=api)
        ltsa = setup_active_ltsa(
            project["id"],
            api=api,
            start_date="2026-08-01T00:00:00Z",
            end_date="2026-09-20T00:00:00Z",
        )
        order = create_order(
            ltsa["id"], api=api, part_description="Contactor", part_cost_cents=200000
        )
        assert order["covered_by_credit"] is True  # still ORDERED
        validate_success(api.suspend_service_agreement(ltsa["id"], SVC_MGR))

        set_clock("2026-09-21T00:00:00Z", api=api)
        expired = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        assert expired["status"] == "EXPIRED"
        assert expired["credit_drawn_cents"] == 0
        order_after = get_success_data(api.get_spare_part_order(order["id"], SVC_MGR))
        assert order_after["status"] == "CANCELLED"
