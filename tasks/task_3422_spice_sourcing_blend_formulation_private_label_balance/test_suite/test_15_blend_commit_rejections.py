"""Blend commit aborts: empty candidate pool and cap-bound insufficiency."""
import pytest
from test_helpers import (
    api_client, validate_error, ApiErrorId, TEST_USERS, create_supplier,
    create_accepted_lot, create_active_formula, create_blend_run,
    get_blend_run, get_lot,
)


class TestNoQualifyingLots:
    def test_blend_commit_no_qualifying_lots(self, api):
        """PRD §3.4: "If that pool is empty, the commit aborts with
        `ERR_NO_QUALIFYING_LOTS` (HTTP 422) and persists nothing." PRD §3.4:
        candidate lots must carry "`flavor_intensity_units` of at least" the
        line's `min_lot_flavor_units`.

        The line demands flavor 999.0 that no ACCEPTED lot reaches; the run
        keeps every computed field null and the lot is untouched.

        Design: Corner/calculations/blend_commit_no_qualifying_lots
        """
        supplier = create_supplier()
        lot = create_accepted_lot(supplier["id"], flavor_intensity_units=100.0)
        formula = create_active_formula(
            "NQ-1", lines=[dict(spice_code="BLACK_PEPPER",
                                target_proportion_pct=100.0,
                                min_lot_flavor_units=999.0)])
        br = create_blend_run(formula["id"], "COST_MIN", 10)
        resp = api_client.commit_blend_run(
            br["id"], TEST_USERS["flavor_scientist_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_QUALIFYING_LOTS)
        after = get_blend_run(br["id"])
        assert after["status"] == "DRAFT"
        assert after["selected_allocations"] is None
        assert after["spec_status"] is None
        assert after["cost_total_cents"] is None
        assert get_lot(lot["id"])["quantity_remaining_kg"] == \
            pytest.approx(100.0)


class TestInsufficientQuantityUnderCap:
    def test_blend_commit_insufficient_quantity_under_cap(self, api):
        """PRD §3.4: "the per-line single-lot cap: 40.0 percent of the needed
        kilograms, rounded down to three decimal places — no single lot may
        supply more than that cap for the line." PRD §3.4: "If the walk ends
        with need still outstanding, the commit aborts with
        `ERR_INSUFFICIENT_LOT_QUANTITY` (HTTP 409) and persists nothing."

        Two 100 kg lots cap at 40.000 kg each: max-allocatable 80.000 <
        100.000 needed despite 200 kg of stock on hand.

        Design: Corner/calculations/blend_commit_insufficient_quantity_under_cap
        """
        supplier = create_supplier()
        la = create_accepted_lot(supplier["id"], cost_per_kg_cents=100)
        create_accepted_lot(supplier["id"], cost_per_kg_cents=100)
        formula = create_active_formula(
            "IQ-1", lines=[dict(spice_code="BLACK_PEPPER",
                                target_proportion_pct=100.0,
                                min_lot_flavor_units=0.0)])
        br = create_blend_run(formula["id"], "COST_MIN", 100)
        resp = api_client.commit_blend_run(
            br["id"], TEST_USERS["flavor_scientist_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_QUANTITY)
        assert get_blend_run(br["id"])["status"] == "DRAFT"
        assert get_lot(la["id"])["quantity_remaining_kg"] == \
            pytest.approx(100.0)
