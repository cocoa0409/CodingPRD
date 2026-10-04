"""Boundary precision: adulterant action level and blend residual tolerance."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_supplier, create_received_lot, create_accepted_lot,
    create_active_formula, create_blend_run, create_committed_blend_run,
    post_test, get_lot, get_blend_run,
)


class TestAdulterantActionLevel:
    def test_below_action_level_passes(self, api):
        """PRD §3.2: "An `ADULTERANT_SCREEN` test — measured in parts per
        million against the lead action level — fails when `measured_value` is
        greater than or equal to 2.00". PRD §3.2: "Anything not reaching its
        action level is a `PASS`."

        1.99 ppm is below the action level: PASS, and the first test simply
        moves the lot RECEIVED -> IN_TEST with no quarantine.

        Design: Difficulty/boundary_precision_check/adulterant_at_action_level_fails
        """
        supplier = create_supplier(name="Ceylon Spice Board",
                                   origin_country="LK")
        lot = create_received_lot(supplier["id"], spice_code="CINNAMON",
                                  origin_region="Galle", quantity_kg=80,
                                  flavor_intensity_units=65.0,
                                  moisture_pct=9.0, cost_per_kg_cents=400,
                                  organic_certified=True)
        t = post_test(lot["id"], "ADULTERANT_SCREEN", 1.99)
        assert t["result"] == "PASS"
        assert get_lot(lot["id"])["status"] == "IN_TEST"

    def test_at_action_level_fails_and_auto_quarantines(self, api):
        """PRD §3.2: "a reading of exactly 2.00 is a `FAIL`." PRD §3.2: "the
        moment an `ADULTERANT_SCREEN` test computes `FAIL`, the lot is
        auto-quarantined: a lot in `IN_TEST` or even in `ACCEPTED` moves
        immediately to `QUARANTINED`".

        Exactly 2.00 ppm meets the >= action level: FAIL, auto-quarantine.

        Design: Difficulty/boundary_precision_check/adulterant_at_action_level_fails
        """
        supplier = create_supplier(name="Ceylon Spice Board",
                                   origin_country="LK")
        lot = create_received_lot(supplier["id"], spice_code="CINNAMON",
                                  origin_region="Galle", quantity_kg=80,
                                  flavor_intensity_units=65.0,
                                  moisture_pct=9.0, cost_per_kg_cents=400,
                                  organic_certified=True)
        t = post_test(lot["id"], "ADULTERANT_SCREEN", 2.00)
        assert t["result"] == "FAIL"
        assert get_lot(lot["id"])["status"] == "QUARANTINED"


def _setup_tolerance_probe():
    """A lots (flavor 102.0, cost 200) committed first at exactly +2.000%
    residual; cheaper B lots (flavor 102.01, cost 100) accepted afterwards so
    the second COST_MIN run lands at +2.010%."""
    supplier = create_supplier()
    for _ in range(3):
        create_accepted_lot(supplier["id"], flavor_intensity_units=102.0,
                            cost_per_kg_cents=200)
    formula = create_active_formula("TOL-1")
    br1 = create_committed_blend_run(formula["id"], "COST_MIN", 100)
    b_lots = [create_accepted_lot(supplier["id"],
                                  flavor_intensity_units=102.01,
                                  cost_per_kg_cents=100)
              for _ in range(3)]
    br2 = create_blend_run(formula["id"], "COST_MIN", 100)
    return {"formula": formula, "br1": br1, "br2": br2, "b_lots": b_lots}


class TestResidualToleranceBoundary:
    def test_residual_exactly_at_tolerance_commits(self, api):
        """PRD §3.4: "The run's `spec_status` is `WITHIN_SPEC` when the
        absolute value of `residual_flavor_pct` is less than or equal to the
        formula's `flavor_tolerance_pct`".

        Blended 102.0 vs target 100.0 -> residual exactly +2.000 with
        tolerance 2.0: inclusive boundary passes, the run commits.

        Design: Difficulty/boundary_precision_check/blend_residual_at_tolerance_passes
        """
        supplier = create_supplier()
        for _ in range(3):
            create_accepted_lot(supplier["id"], flavor_intensity_units=102.0,
                                cost_per_kg_cents=200)
        formula = create_active_formula("TOL-1")
        br = create_committed_blend_run(formula["id"], "COST_MIN", 100)
        assert br["status"] == "COMMITTED"
        assert br["residual_flavor_pct"] == pytest.approx(2.0, abs=1e-6)
        assert br["spec_status"] == "WITHIN_SPEC"

    def test_residual_over_tolerance_rejected_but_fields_persist(self, api):
        """PRD §3.4: "anything else is `OUT_OF_SPEC`, and an out-of-spec
        commit is rejected with `ERR_BLEND_OUT_OF_SPEC` (HTTP 422) — the
        computed fields persist, the status stays `DRAFT`, and no lot
        quantities change."

        Cheapest lots are the 102.01-flavor B lots: residual +2.010 exceeds
        tolerance 2.0; the failed commit persists its computed fields and
        leaves every lot untouched.

        Design: Difficulty/boundary_precision_check/blend_residual_at_tolerance_passes
        """
        s = _setup_tolerance_probe()
        resp = api_client.commit_blend_run(
            s["br2"]["id"], TEST_USERS["flavor_scientist_headers"])
        validate_error(resp, ApiErrorId.ERR_BLEND_OUT_OF_SPEC)
        br2 = get_blend_run(s["br2"]["id"])
        assert br2["status"] == "DRAFT"
        assert br2["residual_flavor_pct"] == pytest.approx(2.01, abs=1e-6)
        assert br2["spec_status"] == "OUT_OF_SPEC"
        for b in s["b_lots"]:
            assert get_lot(b["id"])["quantity_remaining_kg"] == \
                pytest.approx(100.0)
