"""Compensating invariants: lot mass across commit/void, weekly pool across
schedule/cancel."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_accepted_lots, create_active_formula, create_blend_run,
    create_committed_blend_run, commit_blend_run, create_line, schedule_run,
    cancel_run,
    reservation_payload, get_lot, assert_lot_mass_invariant,
)


class TestLotMassConservation:
    def _setup(self):
        supplier, lots = setup_accepted_lots(costs=(100, 200, 300))
        formula = create_active_formula("MASS-1")
        br = create_blend_run(formula["id"], "COST_MIN", 100)
        return {"lots": lots, "br": br}

    def test_commit_moves_mass_remaining_to_consumed(self, api):
        """PRD §2.11: "for every lot, `quantity_kg` always equals the sum of
        `quantity_remaining_kg`, `quantity_consumed_kg`, and
        `quantity_wasted_kg`." PRD §3.4: "for every allocation, the source
        lot's `quantity_remaining_kg` decreases by `allocated_kg` and its
        `quantity_consumed_kg` increases by the same amount".

        100 kg COST_MIN commit (cap 40.000): LA 100->60 remaining / 40
        consumed, LB likewise, LC 80/20; 100 == 60+40+0 throughout.

        Design: Difficulty/compensating_invariant/lot_mass_conservation_across_commit_and_void
        """
        s = self._setup()
        la, lb, lc = s["lots"]
        assert la["quantity_remaining_kg"] == pytest.approx(100.0)
        assert la["quantity_consumed_kg"] == pytest.approx(0.0)
        assert la["quantity_wasted_kg"] == pytest.approx(0.0)
        commit_blend_run(s["br"]["id"])
        la1, lb1, lc1 = (get_lot(x["id"]) for x in (la, lb, lc))
        assert la1["quantity_remaining_kg"] == pytest.approx(60.0)
        assert la1["quantity_consumed_kg"] == pytest.approx(40.0)
        assert la1["status"] == "ACCEPTED"
        assert lb1["quantity_remaining_kg"] == pytest.approx(60.0)
        assert lc1["quantity_consumed_kg"] == pytest.approx(20.0)
        for lot in (la1, lb1, lc1):
            assert_lot_mass_invariant(lot)

    def test_void_restores_mass_exactly(self, api):
        """PRD §3.4: "Voiding a `COMMITTED` run ... reverses the consumption
        exactly: for every allocation, the lot's `quantity_consumed_kg`
        decreases by `allocated_kg` and its `quantity_remaining_kg` increases
        by the same amount". PRD §2.11: "voiding a committed blend run moves
        kilograms back from consumed to remaining. No operation creates or
        destroys mass."

        After commit-then-void every lot is back to 100 == 100+0+0.

        Design: Difficulty/compensating_invariant/lot_mass_conservation_across_commit_and_void
        """
        s = self._setup()
        commit_blend_run(s["br"]["id"])
        resp = api_client.void_blend_run(s["br"]["id"],
                                         TEST_USERS["flavor_scientist_headers"])
        voided = validate_success(resp, 200)
        assert voided["status"] == "VOIDED"
        for lot in s["lots"]:
            after = get_lot(lot["id"])
            assert after["quantity_remaining_kg"] == pytest.approx(100.0)
            assert after["quantity_consumed_kg"] == pytest.approx(0.0)
            assert after["quantity_wasted_kg"] == pytest.approx(0.0)
            assert_lot_mass_invariant(after)


class TestWeeklyPoolConservation:
    def _setup(self):
        supplier, lots = setup_accepted_lots(costs=(100, 100, 100),
                                             quantity_kg=1000)
        formula = create_active_formula("POOL-1")
        br = create_committed_blend_run(formula["id"], "COST_MIN", 2000)
        line = create_line(name="Line-K")
        return {"formula": formula, "br": br, "line": line}

    def test_reservation_blocked_while_run_holds_pool(self, api):
        """PRD §3.8: "If honoring the reservation would push any intersected
        week's pool below zero, the create is rejected with
        `ERR_RESERVATION_OVER_COMMIT` (HTTP 409)". PRD §2.11: "the week's pool
        kilograms minus the kilograms scheduled or completed against it minus
        the kilograms reserved against it must remain greater than or equal
        to zero".

        Week-37 pool is 5000 kg; with a 2000 kg run scheduled, a 3001 kg
        reservation would drive the pool to -1 and is rejected.

        Design: Difficulty/compensating_invariant/line_weekly_pool_conservation_across_schedule_and_cancel
        """
        s = self._setup()
        schedule_run(s["line"]["id"], s["formula"]["id"], s["br"]["id"], 2000,
                     "2026-09-07T08:00:00Z", "2026-09-07T16:00:00Z")
        resp = api_client.create_reservation(
            reservation_payload(s["line"]["id"], "2026-09-07T00:00:00Z",
                                "2026-09-14T00:00:00Z", 3001),
            TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_RESERVATION_OVER_COMMIT)

    def test_cancel_restores_pool_exactly(self, api):
        """PRD §3.6: "Cancelling a `SCHEDULED` run instead marks it `CANCELLED`
        and releases its weekly-pool consumption, restoring the capacity
        invariant for that week."

        After the cancel, a 3000 kg reservation succeeds; 2001 kg more would
        break the pool (3000+2001 > 5000) and is rejected, while exactly
        2000 kg lands the pool at zero and succeeds — zero drift.

        Design: Difficulty/compensating_invariant/line_weekly_pool_conservation_across_schedule_and_cancel
        """
        s = self._setup()
        run = schedule_run(s["line"]["id"], s["formula"]["id"], s["br"]["id"],
                           2000, "2026-09-07T08:00:00Z", "2026-09-07T16:00:00Z")
        cancelled = cancel_run(run["id"])
        assert cancelled["status"] == "CANCELLED"
        resp = api_client.create_reservation(
            reservation_payload(s["line"]["id"], "2026-09-07T00:00:00Z",
                                "2026-09-14T00:00:00Z", 3000),
            TEST_USERS["production_scheduler_headers"])
        validate_success(resp, 201)
        resp = api_client.create_reservation(
            reservation_payload(s["line"]["id"], "2026-09-07T00:00:00Z",
                                "2026-09-14T00:00:00Z", 2001),
            TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_RESERVATION_OVER_COMMIT)
        resp = api_client.create_reservation(
            reservation_payload(s["line"]["id"], "2026-09-07T00:00:00Z",
                                "2026-09-14T00:00:00Z", 2000),
            TEST_USERS["production_scheduler_headers"])
        validate_success(resp, 201)
