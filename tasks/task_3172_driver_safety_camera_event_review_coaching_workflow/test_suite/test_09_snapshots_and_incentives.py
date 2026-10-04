"""Score snapshots, incentive pricing, awards, and the leaderboard."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    compute_snapshot,
    create_confirmed_event,
    create_driver,
    create_terminal,
    get_driver_awards,
    setup_base,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_fleet_payload
from test_helpers.fixtures import create_fleet, review_event, ingest_event, register_clip, upload_clip, set_clock

EXEC = TEST_USERS["fleet_admin_headers"]
MANAGER = TEST_USERS["safety_manager_headers"]

PERIOD = ("2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")


class TestProvisionalVsFinalRepricing:
    def test_incentive_projection_vs_final_repricing(self, api):
        """PRD §3.9: "with `finalize` false the row is `PROVISIONAL` and
        prices off the provisional score variant; with `finalize` true the row
        is created directly in `FINAL` status pricing off the final variant."
        PRD §3.9: "First, the platform upserts the driver's `IncentiveAward`
        for the period: creating one in `PROJECTED` status if none exists, or
        recomputing `amount_cents` and `tier` in place — and if the recomputed
        tier is `NONE`, the award moves `PROJECTED` → `FORFEITED`."
        PRD §3.9: "The award records the pricing `snapshot_id` and copies
        `period_start` and `period_end` from the snapshot; because provisional
        snapshots price off the provisional score, the projected amount can
        differ from the final amount for identical period data."

        Design: Difficulty/dual_variant_calc/incentive_projection_vs_final_repricing
        """
        base = setup_base()
        # HIGH event IN_REVIEW: provisional 85.00, final 100.00.
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="DISTRACTION", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        snap_prov = compute_snapshot(
            base["fleet"]["id"], "DRIVER", *PERIOD,
            scope_id=base["driver"]["id"], finalize=False,
        )
        assert snap_prov["status"] == "PROVISIONAL"
        assert float(snap_prov["score"]) == 85.00
        awards = get_driver_awards(base["driver"]["id"])
        assert len(awards) == 1
        award = awards[0]
        assert award["status"] == "PROJECTED"
        assert award["tier"] == "BRONZE"
        assert award["amount_cents"] == 10000
        # Dismiss the provisional-only event; final variant excludes it.
        review_event(event["id"], "DISMISS", rationale="false positive from reflection")
        snap_final = compute_snapshot(
            base["fleet"]["id"], "DRIVER", *PERIOD,
            scope_id=base["driver"]["id"], finalize=True,
        )
        assert snap_final["status"] == "FINAL"
        assert float(snap_final["score"]) == 100.00
        awards = get_driver_awards(base["driver"]["id"])
        assert len(awards) == 1
        repriced = awards[0]
        assert repriced["id"] == award["id"]
        assert repriced["status"] == "PROJECTED"
        assert repriced["tier"] == "GOLD"
        assert repriced["amount_cents"] == 50000
        assert repriced["snapshot_id"] == snap_final["id"]
        rows, _ = validate_paginated(
            api.list_snapshot_incentive_awards(snap_prov["id"], EXEC)
        )
        assert len(rows) == 0

    def test_provisional_snapshot_prices_off_provisional_score(self, api):
        """PRD §3.9: "with `finalize` false the row is `PROVISIONAL` and
        prices off the provisional score variant; with `finalize` true the row
        is created directly in `FINAL` status pricing off the final variant."

        Design: Difficulty/dual_variant_calc/incentive_projection_vs_final_repricing
        """
        base = setup_base()
        event = ingest_event(
            base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="HIGH",
            occurred_at="2026-08-30T00:00:00Z",
        )
        clip = register_clip(event["id"], captured_at="2026-08-30T00:00:00Z")
        upload_clip(clip["id"])
        snap_prov = compute_snapshot(
            base["fleet"]["id"], "DRIVER", *PERIOD,
            scope_id=base["driver"]["id"], finalize=False,
        )
        # Provisional counts the IN_REVIEW HIGH event: 100 - 15.00 == 85.00.
        assert float(snap_prov["score"]) == 85.00
        snap_final = compute_snapshot(
            base["fleet"]["id"], "DRIVER", *PERIOD,
            scope_id=base["driver"]["id"], finalize=True,
        )
        # Final excludes IN_REVIEW events: 100.00.
        assert float(snap_final["score"]) == 100.00


class TestIncentiveTierBoundary:
    def test_incentive_tier_exact_threshold_gold(self, api):
        """PRD §3.9: "Award pricing reads the snapshot's `score` at exactly
        two decimal places: at least 95.00 earns `GOLD` (50000 cents), at
        least 90.00 earns `SILVER` (25000 cents), at least 80.00 earns
        `BRONZE` (10000 cents), and anything below 80.00 is `NONE` (0 cents);
        thresholds are inclusive, so 95.00 is `GOLD` while 94.99 is `SILVER`."

        Design: Corner/calculations/incentive_tier_exact_threshold_gold
        """
        base = setup_base()
        for occurred in ("2026-08-30T00:00:00Z", "2026-08-31T00:00:00Z"):
            create_confirmed_event(
                base["fleet"]["id"], base["driver"]["id"], base["vehicle"]["id"],
                event_type="SEAT_BELT", severity="LOW", occurred_at=occurred,
            )
        snapshot = compute_snapshot(
            base["fleet"]["id"], "DRIVER",
            "2026-08-01T00:00:00Z", "2026-09-30T23:59:59Z",
            scope_id=base["driver"]["id"], finalize=True,
        )
        # Two fresh LOW confirmations: 100 - 5.00 == 95.00 exactly.
        assert float(snapshot["score"]) == 95.00
        assert snapshot["status"] == "FINAL"
        awards = get_driver_awards(base["driver"]["id"])
        assert len(awards) == 1
        assert awards[0]["tier"] == "GOLD"
        assert awards[0]["amount_cents"] == 50000
        assert awards[0]["status"] == "PROJECTED"


class TestAwardApprovalGating:
    def test_award_approve_requires_final_snapshot(self, api):
        """PRD §3.9: "Approving a `PROJECTED` award requires its pricing
        snapshot to be in `FINAL` status (otherwise `ERR_SNAPSHOT_NOT_FINAL`)
        and its tier to be anything other than `NONE`."

        Design: Corner/validations/award_approve_requires_final_snapshot
        """
        base = setup_base()
        compute_snapshot(
            base["fleet"]["id"], "DRIVER", *PERIOD,
            scope_id=base["driver"]["id"], finalize=False,
        )
        awards = get_driver_awards(base["driver"]["id"])
        award = awards[0]
        resp = api.approve_incentive_award(award["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_NOT_FINAL)
        compute_snapshot(
            base["fleet"]["id"], "DRIVER", *PERIOD,
            scope_id=base["driver"]["id"], finalize=True,
        )
        approved = validate_success(api.approve_incentive_award(award["id"], EXEC), 200)
        assert approved["status"] == "APPROVED"

    def test_award_pay_from_projected_rejected(self, api):
        """PRD §3.9: "Paying an `APPROVED` award enforces the season budget:
        the sum of `amount_cents` over the fleet's awards in `APPROVED` or
        `PAID` status, after counting this payment, must not exceed the
        fleet's `incentive_budget_cents` — a total exactly equal to the budget
        is admitted, and an excess is rejected with
        `ERR_INCENTIVE_BUDGET_EXCEEDED`. `PAID` and `FORFEITED` are terminal."

        Design: Corner/state_machines/award_pay_from_projected_rejected
        """
        base = setup_base()
        compute_snapshot(
            base["fleet"]["id"], "DRIVER", *PERIOD,
            scope_id=base["driver"]["id"], finalize=True,
        )
        awards = get_driver_awards(base["driver"]["id"])
        award = awards[0]
        resp = api.pay_incentive_award(award["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_incentive_award(award["id"], EXEC), 200)
        assert after["status"] == "PROJECTED"


class TestIncentiveBudget:
    def test_incentive_budget_exceeded_on_pay(self, api):
        """PRD §3.9: "Paying an `APPROVED` award enforces the season budget:
        the sum of `amount_cents` over the fleet's awards in `APPROVED` or
        `PAID` status, after counting this payment, must not exceed the
        fleet's `incentive_budget_cents` — a total exactly equal to the budget
        is admitted, and an excess is rejected with
        `ERR_INCENTIVE_BUDGET_EXCEEDED`."

        Design: Corner/validations/incentive_budget_exceeded_on_pay
        """
        set_clock("2026-09-01T00:00:00Z")
        # Fleet A: budget 40000c < GOLD 50000c.
        fleet_a = create_fleet(name="Tight Budget Freight", incentive_budget_cents=40000)
        terminal_a = create_terminal(fleet_a["id"], name="Depot A")
        driver_a = create_driver(
            terminal_a["id"], employee_ref="E-9001", name="Driver A"
        )
        compute_snapshot(fleet_a["id"], "DRIVER", *PERIOD,
                         scope_id=driver_a["id"], finalize=True)
        award_a = get_driver_awards(driver_a["id"])[0]
        validate_success(api.approve_incentive_award(award_a["id"], EXEC), 200)
        # Fleet B: budget exactly 50000c.
        fleet_b = create_fleet(name="Exact Budget Freight", incentive_budget_cents=50000)
        terminal_b = create_terminal(fleet_b["id"], name="Depot B")
        driver_b = create_driver(
            terminal_b["id"], employee_ref="E-9002", name="Driver B"
        )
        compute_snapshot(fleet_b["id"], "DRIVER", *PERIOD,
                         scope_id=driver_b["id"], finalize=True)
        award_b = get_driver_awards(driver_b["id"])[0]
        validate_success(api.approve_incentive_award(award_b["id"], EXEC), 200)

        resp = api.pay_incentive_award(award_a["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_INCENTIVE_BUDGET_EXCEEDED)
        still = validate_success(api.get_incentive_award(award_a["id"], EXEC), 200)
        assert still["status"] == "APPROVED"
        paid = validate_success(api.pay_incentive_award(award_b["id"], EXEC), 200)
        assert paid["status"] == "PAID"


class TestLeaderboard:
    def test_leaderboard_returns_ranked_final_snapshots(self, api):
        """PRD §3.9: "The fleet's leaderboard returns its driver-scope `FINAL`
        snapshots for a requested `period_start` and `period_end`, ordered by
        `rank` ascending."
        PRD §3.9: "a snapshot's rank is 1 plus the number of candidates with a
        strictly higher `score`, or an equal `score` with fewer of their
        driver's confirmed events whose `occurred_at` falls inside the period
        (inclusive at both ends), or an equal score and equal event count
        whose driver was created earlier; a resource's `id` is never a
        tie-break input."

        Design: Corner/endpoints/leaderboard_returns_ranked_final_snapshots
        """
        base = setup_base()
        driver_b = create_driver(
            base["terminal"]["id"], employee_ref="E-3003", name="Sam Okafor"
        )
        create_confirmed_event(
            base["fleet"]["id"], driver_b["id"], base["vehicle"]["id"],
            event_type="HARSH_BRAKE", severity="MEDIUM",
            occurred_at="2026-08-30T00:00:00Z",
        )
        period = ("2026-08-01T00:00:00Z", "2026-09-30T23:59:59Z")
        compute_snapshot(base["fleet"]["id"], "DRIVER", *period,
                         scope_id=base["driver"]["id"], finalize=True)
        compute_snapshot(base["fleet"]["id"], "DRIVER", *period,
                         scope_id=driver_b["id"], finalize=True)
        rows, meta = validate_paginated(
            api.get_leaderboard(
                base["fleet"]["id"], EXEC,
                params={"period_start": period[0], "period_end": period[1]},
            )
        )
        assert len(rows) == 2
        assert rows[0]["rank"] == 1
        assert rows[0]["scope_id"] == base["driver"]["id"]
        assert float(rows[0]["score"]) == 100.00
        assert rows[1]["rank"] == 2
        assert rows[1]["scope_id"] == driver_b["id"]
        assert float(rows[1]["score"]) == 92.50
