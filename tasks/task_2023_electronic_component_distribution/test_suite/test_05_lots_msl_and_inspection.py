"""Inventory lots: sourcing-channel initial states, authenticity inspection,
segregation of duties, and moisture-sensitivity handling (PRD §2.5, §2.6, §3.5)."""
from test_helpers import (
    ADMIN,
    WAREHOUSE,
    ApiErrorId,
    advance_clock,
    bake,
    get_lot,
    get_part,
    make_quality_inspector_headers,
    make_warehouse_ops_headers,
    open_exposure_interval,
    receive_lot,
    seal_exposure_interval,
    setup_catalog,
    setup_quarantined_lot,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLotInitialState:
    def test_lot_initial_state_by_source_type(self, api):
        """PRD §2.5: "Franchised stock is presumed authentic by chain of
        custody: such lots begin life already `AVAILABLE`, with their
        `authenticity` recorded as `NOT_REQUIRED`."
        PRD §2.5: "An `OPEN_MARKET` lot begins `IN_INSPECTION` with
        `authenticity` set to `PENDING_INSPECTION`, and it contributes nothing
        to available supply until a `QualityInspector` authenticates it."
        PRD §3.1: "`qty_on_hand`, the sum of unreserved units over the part's
        `AVAILABLE` lots".

        Design: Corner/entities/lot_initial_state_by_source_type
        """
        line, part = setup_catalog(line_code="LIN-IS")
        lot_fr = receive_lot(part["id"], qty_received=10, date_code="202601",
                             source_type="FRANCHISED", receiver_id="wh-01")
        lot_om = receive_lot(part["id"], qty_received=20, date_code="202602",
                             source_type="OPEN_MARKET", receiver_id="wh-01")

        assert lot_fr["status"] == "AVAILABLE"
        assert lot_fr["authenticity"] == "NOT_REQUIRED"
        assert lot_fr["qty_on_hand"] == 10

        assert lot_om["status"] == "IN_INSPECTION"
        assert lot_om["authenticity"] == "PENDING_INSPECTION"
        assert lot_om["qty_on_hand"] == 20

        part_after = get_part(part["id"])
        assert part_after["qty_on_hand"] == 10, (
            "Only the AVAILABLE franchised lot contributes to part availability"
        )


class TestInspection:
    def test_inspect_franchised_lot_rejected(self, api):
        """PRD §2.5: "An inspection attempted on a lot that is no longer
        `IN_INSPECTION` is rejected with `ERR_INSPECTION_NOT_PENDING`."

        Design: Corner/errors/inspect_franchised_lot_rejected
        """
        line, part = setup_catalog(line_code="LIN-IF")
        lot = receive_lot(part["id"], qty_received=50, source_type="FRANCHISED",
                          receiver_id="wh-01")
        resp = api.inspect_lot(lot["id"], {"disposition": "AUTHENTICATE"},
                               make_quality_inspector_headers("qi-01"))
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_PENDING)
        after = get_lot(lot["id"])
        assert after["status"] == "AVAILABLE"
        assert after["authenticity"] == "NOT_REQUIRED"

    def test_rejected_lot_terminal_lockdown(self, api):
        """PRD §2.5: "a disposition of `REJECT` moves it to the terminal
        `REJECTED` state with `authenticity` `REJECTED`."
        PRD §2.6: "Opening is permitted only while the lot is `AVAILABLE` —
        otherwise `ERR_LOT_NOT_AVAILABLE`".
        PRD §3.5: "A `WarehouseOps` operator bakes a lot that is `QUARANTINED` —
        any other state draws `ERR_LOT_NOT_QUARANTINED`".

        Design: Corner/state_machines/rejected_lot_terminal_lockdown
        """
        line, part = setup_catalog(line_code="LIN-RJ")
        lot = receive_lot(part["id"], qty_received=10, source_type="OPEN_MARKET",
                          receiver_id="wh-01")
        rejected = validate_success(
            api.inspect_lot(lot["id"],
                            {"disposition": "REJECT", "note": "counterfeit markers"},
                            make_quality_inspector_headers("qi-01")),
            200)
        assert rejected["status"] == "REJECTED"
        assert rejected["authenticity"] == "REJECTED"

        resp_open = api.open_exposure(lot["id"], {"note": "attempt on rejected"},
                                      WAREHOUSE)
        validate_error(resp_open, ApiErrorId.ERR_LOT_NOT_AVAILABLE)

        resp_bake = api.bake_lot(lot["id"], WAREHOUSE)
        validate_error(resp_bake, ApiErrorId.ERR_LOT_NOT_QUARANTINED)

        after = get_lot(lot["id"])
        assert after["status"] == "REJECTED"
        assert after["authenticity"] == "REJECTED"

    def test_segregation_receiver_cannot_inspect_own_lot(self, api):
        """PRD §2.5: "To prevent self-approval, the inspector must be a
        different operator than the receiver: the lot records the receiving
        operator's `X-User-ID` as `received_by_user_id` at receipt, and an
        inspection attempted by that same user is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_receiver_cannot_inspect_own_lot
        """
        line, part = setup_catalog(line_code="LIN-SD1")
        lot = receive_lot(part["id"], qty_received=10, source_type="OPEN_MARKET",
                          receiver_id="u-77")
        assert lot["received_by_user_id"] == "u-77"

        resp = api.inspect_lot(lot["id"], {"disposition": "AUTHENTICATE"},
                               make_quality_inspector_headers("u-77"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        inspected = validate_success(
            api.inspect_lot(lot["id"], {"disposition": "AUTHENTICATE"},
                            make_quality_inspector_headers("qi-99")),
            200)
        assert inspected["status"] == "AVAILABLE"
        assert inspected["authenticity"] == "AUTHENTICATED"

    def test_warehouse_ops_cannot_inspect_lot(self, api):
        """PRD §2.1: "Access to specific operations is restricted by role; an
        attempt to perform an action outside of a user's designated role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4 restricts lot inspection to QualityInspector: "Authenticate or
        reject an open-market lot (segregation of duties)".

        Design: Corner/rbac/warehouse_ops_cannot_inspect_lot
        """
        line, part = setup_catalog(line_code="LIN-RB3")
        lot = receive_lot(part["id"], qty_received=10, source_type="OPEN_MARKET",
                          receiver_id="wh-01")
        resp = api.inspect_lot(lot["id"], {"disposition": "AUTHENTICATE"},
                               make_warehouse_ops_headers("wh-02"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert get_lot(lot["id"])["status"] == "IN_INSPECTION"


class TestMslFloorLifeBoundary:
    def test_msl_floor_life_99_vs_100_hours(self, api):
        """PRD §2.6: "When this cumulative figure reaches or exceeds the part's
        `floor_life_hours` (equality is a breach), the lot is quarantined by the
        sweep."
        PRD §2.4: "any lot in `AVAILABLE` whose recomputed exposure has reached
        or exceeded its part's floor life is moved to `QUARANTINED`, and the
        quarantine cascade described in §3.5 runs on it."

        Design: Corner/calculations/msl_floor_life_99_vs_100_hours
        """
        line, part = setup_catalog(line_code="LIN-99",
                                   part_kw={"floor_life_hours": 100})
        lot = receive_lot(part["id"], qty_received=50)
        open_exposure_interval(lot["id"], note="open")

        advance_clock("2026-08-05T03:00:00Z")  # 99 hours of exposure
        assert get_lot(lot["id"])["status"] == "AVAILABLE", (
            "99 hours is below the 100-hour floor life — no quarantine"
        )

        advance_clock("2026-08-05T04:00:00Z")  # exactly 100 hours
        after = get_lot(lot["id"])
        assert after["status"] == "QUARANTINED", "Equality breaches the floor life"
        assert after["msl_exposure_hours"] == 100


class TestQuarantineBakeCycle:
    def test_lot_quarantine_at_floor_life(self, api):
        """PRD §2.6: "an interval still open contributes the whole-hour
        difference between `now` and its `opened_at`."
        PRD §2.4: "any lot in `AVAILABLE` whose recomputed exposure has reached
        or exceeded its part's floor life is moved to `QUARANTINED`".

        Design: Difficulty/non_linear_state_machine/lot_quarantine_bake_cycle
        """
        sc = setup_quarantined_lot(floor_life_hours=100, lot_qty=50,
                                   line_code="LIN-M")
        lot = sc["lot"]
        assert lot["status"] == "QUARANTINED"
        assert lot["msl_exposure_hours"] == 100

    def test_bake_returns_lot_to_available_and_cycle_repeats(self, api):
        """PRD §3.5: "Baking stamps `last_baked_at` from the logical clock,
        resets `msl_exposure_hours` to zero, returns the lot to `AVAILABLE`,
        and recomputes the part's availability. Earlier intervals, being before
        the new `last_baked_at`, are excluded from future accrual; the
        quarantine-bake cycle can repeat as often as handling requires."

        Design: Difficulty/non_linear_state_machine/lot_quarantine_bake_cycle
        """
        sc = setup_quarantined_lot(floor_life_hours=100, lot_qty=50,
                                   line_code="LIN-M")
        lot_id = sc["lot"]["id"]
        assert sc["lot"]["status"] == "QUARANTINED"

        seal_exposure_interval(lot_id, sc["exposure"]["id"])
        baked = bake(lot_id)
        assert baked["status"] == "AVAILABLE"
        assert baked["msl_exposure_hours"] == 0
        assert baked["last_baked_at"] == "2026-08-05T04:00:00Z"

        second = open_exposure_interval(lot_id, note="second open after bake")
        assert second["opened_at"] == "2026-08-05T04:00:00Z", (
            "The cycle continues: a fresh interval opens at the current clock"
        )


class TestExposureIntervals:
    def test_exposure_nested_open_rejected(self, api):
        """PRD §2.6: "Opening is permitted only while the lot is `AVAILABLE` —
        otherwise `ERR_LOT_NOT_AVAILABLE` — and only when no other interval of
        the same lot is still unsealed, otherwise `ERR_EXPOSURE_ALREADY_OPEN`."

        Design: Difficulty/resource_temporal_overlap/exposure_interval_nesting_rules
        """
        line, part = setup_catalog(line_code="LIN-E",
                                   part_kw={"floor_life_hours": 1000})
        lot = receive_lot(part["id"], qty_received=50)
        open_exposure_interval(lot["id"], note="E1")
        advance_clock("2026-08-02T00:00:00Z")

        resp = api.open_exposure(lot["id"], {"note": "E2 while E1 open"}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_EXPOSURE_ALREADY_OPEN)
        assert get_lot(lot["id"])["status"] == "AVAILABLE"

    def test_exposure_adjacency_at_seal_allowed(self, api):
        """PRD §2.6: "Adjacency at a seal boundary is allowed: a new interval
        may open at the exact instant the prior one sealed; nesting is not."

        Design: Difficulty/resource_temporal_overlap/exposure_interval_nesting_rules
        """
        line, part = setup_catalog(line_code="LIN-E",
                                   part_kw={"floor_life_hours": 1000})
        lot = receive_lot(part["id"], qty_received=50)
        first = open_exposure_interval(lot["id"], note="E1")
        advance_clock("2026-08-02T00:00:00Z")

        # A nested open is rejected while E1 is unsealed.
        resp = api.open_exposure(lot["id"], {"note": "E2 while E1 open"}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_EXPOSURE_ALREADY_OPEN)

        sealed = seal_exposure_interval(lot["id"], first["id"])
        assert sealed["sealed_at"] == "2026-08-02T00:00:00Z"

        third = open_exposure_interval(lot["id"], note="E3 exactly at E1 sealed_at")
        assert third["opened_at"] == "2026-08-02T00:00:00Z", (
            "opened_at equals the prior interval's sealed_at — adjacency allowed"
        )
        assert third["sealed_at"] is None

        exposures, meta = validate_paginated(api.list_exposures(lot["id"], ADMIN))
        assert meta["total_count"] == 2

    def test_seal_without_open_exposure_rejected(self, api):
        """PRD §2.6: "Sealing an interval stamps `sealed_at` from the logical
        clock; sealing an already-sealed interval is rejected with
        `ERR_EXPOSURE_NOT_OPEN`."

        Design: Corner/errors/seal_without_open_exposure_rejected
        """
        line, part = setup_catalog(line_code="LIN-SL")
        lot = receive_lot(part["id"], qty_received=50)
        exposure = open_exposure_interval(lot["id"], note="open")
        sealed = seal_exposure_interval(lot["id"], exposure["id"])
        assert sealed["sealed_at"] == "2026-08-01T00:00:00Z"

        resp = api.seal_exposure(lot["id"], exposure["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_EXPOSURE_NOT_OPEN)

        exposures, _meta = validate_paginated(api.list_exposures(lot["id"], ADMIN))
        assert exposures[0]["sealed_at"] == "2026-08-01T00:00:00Z", (
            "The rejected second seal leaves sealed_at untouched"
        )

    def test_exposure_open_on_quarantined_lot_rejected(self, api):
        """PRD §2.6: "Opening is permitted only while the lot is `AVAILABLE` —
        otherwise `ERR_LOT_NOT_AVAILABLE`".

        Design: Corner/errors/exposure_open_on_quarantined_lot_rejected
        """
        line, part = setup_catalog(line_code="LIN-XQ",
                                   part_kw={"floor_life_hours": 10})
        lot = receive_lot(part["id"], qty_received=50)
        open_exposure_interval(lot["id"], note="breach interval")
        advance_clock("2026-08-01T10:00:00Z")  # 10 hours == floor life
        assert get_lot(lot["id"])["status"] == "QUARANTINED"

        resp = api.open_exposure(lot["id"], {"note": "attempt on quarantined"},
                                 WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE)

    def test_bake_non_quarantined_lot_rejected(self, api):
        """PRD §3.5: "A `WarehouseOps` operator bakes a lot that is
        `QUARANTINED` — any other state draws `ERR_LOT_NOT_QUARANTINED`".

        Design: Corner/errors/bake_non_quarantined_lot_rejected
        """
        line, part = setup_catalog(line_code="LIN-BK")
        lot = receive_lot(part["id"], qty_received=50)
        resp = api.bake_lot(lot["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_QUARANTINED)
        assert get_lot(lot["id"])["status"] == "AVAILABLE"
