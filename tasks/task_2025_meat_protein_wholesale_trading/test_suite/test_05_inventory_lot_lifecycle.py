"""Inventory lot lifecycle: inspection routing, quarantine doors in and out,
clock-driven expiry, and the warehouse occupancy status filter."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_inventory_lot,
    get_lot,
    get_warehouse,
    load_out_shipment,
    set_clock,
    setup_available_lot,
    setup_confirmed_allocation,
    validate_error,
    validate_success,
)


class TestInspectionRouting:
    def test_inspect_requires_in_inspection(self, quality_grader_headers):
        """PRD §3.4: "Inspection requires the lot to be `IN_INSPECTION`, else
        `ERR_LOT_NOT_IN_INSPECTION`."

        Design: Corner/state_machines/inspect_requires_in_inspection
        """
        ctx = setup_available_lot(product_code="RIBEYE-II", weight=100,
                                  measured_fat_pct=10.0)
        lot_id = ctx["lot"]["id"]

        resp = api_client.inspect_lot(lot_id, {"measured_fat_pct": 11.0},
                                      quality_grader_headers)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_IN_INSPECTION)
        lot = get_lot(lot_id)
        assert lot["status"] == "AVAILABLE"
        assert lot["measured_fat_pct"] == 10.0, \
            "a rejected re-inspection must not overwrite the recorded fat pct"

    def test_quarantine_release_cycle_restores_available(
            self, quality_grader_headers):
        """PRD §3.4: "A non-compliant result routes the lot to `QUARANTINED`
        with `quarantine_reason` `SPEC_NONCOMPLIANCE`."
        PRD §3.4: "Release returns a `QUARANTINED` lot to `AVAILABLE`: the lot
        must be `QUARANTINED`, else `ERR_INVALID_STATE`, and its `age_days`
        must not exceed the product's `shelf_life_days`, else
        `ERR_LOT_EXPIRED`. Release clears `quarantine_reason` to null and
        recomputes `unit_value_cents_per_lb`."

        Design: Corner/state_machines/quarantine_release_cycle_restores_available
        """
        # measured 20.0 > max_fat 12.0 routes the lot to QUARANTINED.
        ctx = setup_available_lot(product_code="RIBEYE-QR", weight=100,
                                  max_fat_pct=12.0, measured_fat_pct=20.0)
        quarantined = ctx["lot"]
        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["quarantine_reason"] == "SPEC_NONCOMPLIANCE"
        assert quarantined["spec_compliant"] is False

        released = api_client.release_lot(quarantined["id"],
                                          quality_grader_headers)
        data = validate_success(released)
        assert_inventory_lot(data)
        assert data["status"] == "AVAILABLE"
        assert data["quarantine_reason"] is None


class TestLotExpirySweep:
    def test_auto_expiry_at_shelf_life_boundary(self):
        """PRD §2.4: "In the first sweep, every `AVAILABLE` lot whose
        `age_days` has moved strictly beyond its product's `shelf_life_days`
        transitions to `EXPIRED`, drops out of its warehouse's occupancy
        figure, and is excluded from the physical component of the net exposure
        report."
        PRD §2.4: "the response reports the new `current_utc` together with the
        swept victims as `expired_lot_ids` and `defaulted_contract_ids`."

        Design: Corner/state_machines/auto_expiry_at_shelf_life_boundary
        """
        ctx = setup_available_lot(product_code="RIBEYE-EX", weight=100,
                                  shelf_life_days=21,
                                  production_date="2026-08-01",
                                  clock="2026-08-03T00:00:00Z")
        lot_id = ctx["lot"]["id"]

        sweep1 = set_clock("2026-08-22T00:00:00Z")  # age 21 == shelf life
        assert lot_id not in sweep1["expired_lot_ids"]
        assert get_lot(lot_id)["status"] == "AVAILABLE", \
            "age exactly equal to shelf life is not strictly beyond it"

        sweep2 = set_clock("2026-08-23T00:00:00Z")  # age 22 > shelf life 21
        assert lot_id in sweep2["expired_lot_ids"]
        assert get_lot(lot_id)["status"] == "EXPIRED"


class TestReleaseGuards:
    def test_release_from_available_returns_invalid_state(
            self, quality_grader_headers):
        """PRD §3.4: "Release returns a `QUARANTINED` lot to `AVAILABLE`: the
        lot must be `QUARANTINED`, else `ERR_INVALID_STATE`, and its `age_days`
        must not exceed the product's `shelf_life_days`, else
        `ERR_LOT_EXPIRED`."

        Design: Corner/validations/release_from_available_returns_invalid_state
        """
        ctx = setup_available_lot(product_code="RIBEYE-RA", weight=100)
        resp = api_client.release_lot(ctx["lot"]["id"], quality_grader_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_lot(ctx["lot"]["id"])["status"] == "AVAILABLE"

    def test_release_expired_quarantined_lot_returns_409(
            self, quality_grader_headers):
        """PRD §3.4: "Release returns a `QUARANTINED` lot to `AVAILABLE`: the
        lot must be `QUARANTINED`, else `ERR_INVALID_STATE`, and its `age_days`
        must not exceed the product's `shelf_life_days`, else
        `ERR_LOT_EXPIRED`."
        PRD §2.4: "In the first sweep, every `AVAILABLE` lot whose `age_days`
        has moved strictly beyond its product's `shelf_life_days` transitions
        to `EXPIRED`"

        Design: Corner/validations/release_expired_quarantined_lot_returns_409
        """
        # measured 20.0 > max_fat 12.0 routes the lot to QUARANTINED.
        ctx = setup_available_lot(product_code="RIBEYE-EQ", weight=100,
                                  shelf_life_days=21,
                                  production_date="2026-08-01",
                                  measured_fat_pct=20.0)
        lot = ctx["lot"]

        set_clock("2026-08-23T00:00:00Z")  # age 22 > shelf 21
        # The expiry sweep touches only AVAILABLE lots, so this one stays
        # QUARANTINED and the release hits the temporal guard instead.
        assert get_lot(lot["id"])["status"] == "QUARANTINED"
        resp = api_client.release_lot(lot["id"], quality_grader_headers)
        validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED)
        assert get_lot(lot["id"])["status"] == "QUARANTINED"


class TestOccupancyStatusFiltering:
    def test_warehouse_occupancy_status_filtering(self, quality_grader_headers):
        """PRD §2.11: "A warehouse's `occupied_lbs` is a live aggregate: the
        sum of `current_weight_lbs` over all lots stored at that warehouse
        whose status is `IN_INSPECTION`, `AVAILABLE`, or `QUARANTINED`. Lots
        in `DEPLETED` or `EXPIRED` status are excluded."
        PRD §3.4: "When a lot's `current_weight_lbs` reaches zero — through
        shipment load-out or fabrication consumption — the lot moves from
        `AVAILABLE` to `DEPLETED` and its warehouse's occupancy is recomputed."

        Design: Corner/calculations/warehouse_occupancy_status_filtering
        """
        ctx = setup_confirmed_allocation(requested_lbs=500, lot_weight=500,
                                         production_date="2026-08-01")
        wh_id = ctx["warehouse"]["id"]
        lot_id = ctx["lot"]["id"]

        assert get_warehouse(wh_id)["occupied_lbs"] == 500, \
            "an AVAILABLE lot counts toward occupancy"

        api_client.quarantine_lot(lot_id, quality_grader_headers)
        assert get_warehouse(wh_id)["occupied_lbs"] == 500, \
            "a QUARANTINED lot still counts toward occupancy"

        api_client.release_lot(lot_id, quality_grader_headers)
        load_out_shipment(ctx["allocation"]["id"], 500)
        assert get_lot(lot_id)["status"] == "DEPLETED"
        assert get_warehouse(wh_id)["occupied_lbs"] == 0, \
            "a DEPLETED lot is excluded from occupancy"
