"""Quarantine issuance: the vessel-level hold interval, seal conservation and priority."""
from test_helpers import (
    ApiErrorId,
    add_watercraft,
    api_client,
    assert_instant_equals,
    assert_seal_inventory_conserved,
    assert_strike_posture,
    dispose_record,
    fetch_quarantine_order,
    fetch_record,
    fetch_station,
    fetch_watercraft,
    make_inspector_headers,
    quarantine_order_payload,
    report_breach,
    set_clock,
    setup_inspection,
    setup_program,
    setup_quarantined_record,
    validate_error,
    validate_paginated,
    validate_success,
)

ISSUED_AT = "2026-08-05T09:00:00Z"
HOLD_UNTIL = "2026-08-10T09:00:00Z"


def _issue_call(record_id, inspector_id, seal_number):
    return api_client.create_quarantine_order(
        quarantine_order_payload(record_id, seal_number),
        make_inspector_headers(inspector_id),
    )


def _held_vessel_with_a_second_eligible_record():
    """One vessel sealed until 2026-08-10T09:00:00Z, plus a second DECON_REQUIRED record.

    The clock is left at exactly the hold's upper endpoint.
    """
    ctx = setup_program(infestation_status="SUSPECT", seal_stock_initial_count=3)
    vessel = add_watercraft(ctx)
    ctx = setup_quarantined_record(
        ctx, watercraft=vessel, seal_number="MT-SEAL-0400",
        arrived_at=ISSUED_AT, screen_at=ISSUED_AT,
    )
    first_order = ctx["quarantine_order"]
    setup_inspection(
        ctx, watercraft=vessel, arrived_at=HOLD_UNTIL, screen_at=HOLD_UNTIL,
        residual_water_present=True, standing_water_ml=550, disposition="DECON",
    )
    return ctx, first_order, ctx["record"]


class TestQuarantineHoldOnAVesselIsClosedAtBothEnds:
    """A vessel carries at most one live hold, and the upper endpoint is closed."""

    def test_a_second_seal_at_exactly_hold_until_is_refused(self):
        """The hold still blocks when the clock equals hold_until.

        PRD: "And the vessel must not already be sitting under an unexpired hold:
        an existing quarantine order for the same vessel whose `status` is
        `SEALED` or `RELEASE_REQUESTED` and whose `hold_until` the current logical
        time has not yet passed blocks a new one with
        `ERR_WATERCRAFT_ALREADY_QUARANTINED`. That upper endpoint is closed, so an
        order whose `hold_until` equals the current logical time exactly still
        blocks a new order."

        Design: Difficulty/resource_temporal_overlap/quarantine_hold_on_a_vessel_is_closed_at_both_ends
        """
        ctx, first_order, second_record = _held_vessel_with_a_second_eligible_record()

        response = _issue_call(
            second_record["id"], ctx["inspector_a"]["id"], "MT-SEAL-0401"
        )

        validate_error(response, ApiErrorId.ERR_WATERCRAFT_ALREADY_QUARANTINED)
        held = fetch_quarantine_order(first_order["id"])
        assert held["status"] == "SEALED"
        assert_instant_equals(held["hold_until"], HOLD_UNTIL, "hold_until")
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 2
        assert station["seals_in_circulation_count"] == 1
        orders, _meta = validate_paginated(
            api_client.list_quarantine_orders(
                make_inspector_headers(ctx["inspector_a"]["id"]),
                params={"seal_number": "MT-SEAL-0401"},
            )
        )
        assert orders == []

    def test_one_second_after_hold_until_the_vessel_may_be_resealed(self):
        """The same request one second later consumes a seal and starts a new hold.

        PRD: "`hold_until` is then `issued_at` advanced by `hold_hours_required`
        hours, forming the inclusive end of the hold, and the same instant is
        written onto the vessel as `quarantine_hold_until`, which is null whenever
        the vessel is under no hold."

        Design: Difficulty/resource_temporal_overlap/quarantine_hold_on_a_vessel_is_closed_at_both_ends
        """
        ctx, _first_order, second_record = _held_vessel_with_a_second_eligible_record()
        set_clock("2026-08-10T09:00:01Z")

        order = validate_success(
            _issue_call(second_record["id"], ctx["inspector_a"]["id"], "MT-SEAL-0401"),
            201,
        )

        assert order["status"] == "SEALED"
        assert_instant_equals(
            order["hold_until"], "2026-08-15T09:00:01Z", "hold_until"
        )
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 1
        assert station["seals_in_circulation_count"] == 2
        assert_instant_equals(
            fetch_watercraft(ctx["watercraft"]["id"])["quarantine_hold_until"],
            "2026-08-15T09:00:01Z", "quarantine_hold_until",
        )

    def test_a_voided_order_holds_nothing_at_the_same_instant(self):
        """Only SEALED and RELEASE_REQUESTED orders occupy the vessel.

        PRD: "an existing quarantine order for the same vessel whose `status` is
        `SEALED` or `RELEASE_REQUESTED` and whose `hold_until` the current logical
        time has not yet passed blocks a new one with
        `ERR_WATERCRAFT_ALREADY_QUARANTINED`."

        Design: Difficulty/resource_temporal_overlap/quarantine_hold_on_a_vessel_is_closed_at_both_ends
        """
        ctx, first_order, second_record = _held_vessel_with_a_second_eligible_record()
        voided = report_breach(first_order["id"])
        assert voided["status"] == "VOIDED_BREACH"

        order = validate_success(
            _issue_call(second_record["id"], ctx["inspector_a"]["id"], "MT-SEAL-0401"),
            201,
        )

        assert order["status"] == "SEALED"
        assert_instant_equals(order["hold_until"], "2026-08-15T09:00:00Z", "hold_until")


def _sealed_with_three_seals_on_the_shelf():
    """A station stocked with three seals, one of which is now in circulation."""
    return setup_quarantined_record(
        seal_number="MT-SEAL-0500", seal_stock_initial_count=3,
        arrived_at=ISSUED_AT, screen_at=ISSUED_AT,
    )


class TestSealInventoryConservedAcrossIssuanceAndBreach:
    """A breached seal moves from circulation to retired, never back to stock."""

    def test_the_breach_moves_the_seal_from_circulation_to_retired(self):
        """The three buckets still sum to seal_stock_initial_count after the void.

        PRD: "The side effects are identical from both origins: the station's
        `seals_in_circulation_count` is decremented by 1 and `seals_retired_count`
        incremented by 1, because a breached seal is forfeited rather than
        returned"

        Design: Difficulty/compensating_invariant/seal_inventory_conserved_across_issuance_and_breach_void
        """
        ctx = _sealed_with_three_seals_on_the_shelf()
        before = fetch_station(ctx["station"]["id"])
        assert before["seal_stock_count"] == 2
        assert before["seals_in_circulation_count"] == 1
        assert before["seals_retired_count"] == 0
        assert_seal_inventory_conserved(before)

        order = report_breach(ctx["quarantine_order"]["id"])

        assert order["status"] == "VOIDED_BREACH"
        after = fetch_station(ctx["station"]["id"])
        assert after["seal_stock_count"] == 2
        assert after["seals_in_circulation_count"] == 0
        assert after["seals_retired_count"] == 1
        assert_seal_inventory_conserved(after)

    def test_the_breach_clears_the_hold_and_refers_the_record_for_tampering(self):
        """Voiding the order releases the vessel and books one strike.

        PRD: "the vessel's `quarantine_hold_until` is cleared, since a voided
        order is no longer in `SEALED` or `RELEASE_REQUESTED` and therefore holds
        nothing; and the parent record's enforcement dimension is driven `NONE →
        REFERRED` with `referral_reason` set to `SEAL_TAMPER`, but only when that
        record's `enforcement_status` is still `NONE`."

        Design: Difficulty/compensating_invariant/seal_inventory_conserved_across_issuance_and_breach_void
        """
        ctx = _sealed_with_three_seals_on_the_shelf()

        report_breach(ctx["quarantine_order"]["id"])

        record = fetch_record(ctx["record"]["id"])
        assert record["enforcement_status"] == "REFERRED"
        assert record["referral_reason"] == "SEAL_TAMPER"
        watercraft = fetch_watercraft(ctx["watercraft"]["id"])
        assert watercraft["quarantine_hold_until"] is None
        assert_strike_posture(watercraft, 1)

    def test_the_retired_seal_number_stays_globally_taken(self):
        """A terminal order still owns its seal number.

        PRD: "The `seal_number` must be unused across every quarantine order ever
        written, terminal ones included, or the issuance fails with
        `ERR_SEAL_NUMBER_DUPLICATE`."

        Design: Difficulty/compensating_invariant/seal_inventory_conserved_across_issuance_and_breach_void
        """
        ctx = _sealed_with_three_seals_on_the_shelf()
        report_breach(ctx["quarantine_order"]["id"])
        setup_inspection(
            ctx, arrived_at="2026-08-05T10:00:00Z", screen_at="2026-08-05T10:00:00Z",
            residual_water_present=True, standing_water_ml=550, disposition="DECON",
        )

        response = _issue_call(
            ctx["record"]["id"], ctx["inspector_a"]["id"], "MT-SEAL-0500"
        )

        validate_error(response, ApiErrorId.ERR_SEAL_NUMBER_DUPLICATE)
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 2
        assert_seal_inventory_conserved(station)


def _exhausted_shelf_with_an_undispositioned_record():
    """The station's only seal is already in circulation, and R2 is still SCREENED."""
    ctx = setup_quarantined_record(
        seal_number="MT-SEAL-0200", seal_stock_initial_count=1,
        arrived_at=ISSUED_AT, screen_at=ISSUED_AT,
    )
    setup_inspection(
        ctx, arrived_at="2026-08-05T09:30:00Z", screen_at="2026-08-05T09:30:00Z",
        residual_water_present=True, standing_water_ml=550,
    )
    return ctx, ctx["record"]


class TestStateCheckBeatsSealStockCheckOnIssuance:
    """Both 409s are live; the record-state check is the one announced."""

    def test_the_undispositioned_record_is_reported_before_the_empty_shelf(self):
        """A SCREENED record yields ERR_RECORD_NOT_AWAITING_DECON, not the stock error.

        PRD: "The record must be awaiting decontamination — a quarantine order
        created against a record whose `inspection_status` is not `DECON_REQUIRED`
        is rejected with `ERR_RECORD_NOT_AWAITING_DECON`."

        Design: Difficulty/priority_pair_validation_conflict/state_check_beats_seal_stock_check_on_quarantine_issuance
        """
        ctx, second_record = _exhausted_shelf_with_an_undispositioned_record()
        assert second_record["inspection_status"] == "SCREENED"
        assert second_record["quarantine_warranted"] is True

        response = _issue_call(
            second_record["id"], ctx["inspector_a"]["id"], "MT-SEAL-0201"
        )

        validate_error(response, ApiErrorId.ERR_RECORD_NOT_AWAITING_DECON)
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 0
        assert station["seals_in_circulation_count"] == 1
        orders, _meta = validate_paginated(
            api_client.list_quarantine_orders(
                make_inspector_headers(ctx["inspector_a"]["id"]),
                params={"seal_number": "MT-SEAL-0201"},
            )
        )
        assert orders == []

    def test_dispositioning_the_record_exposes_the_exhausted_seal_stock(self):
        """With the state gate satisfied the identical call reports the empty shelf.

        PRD: "The issuing station must have at least one seal on the shelf —
        `seal_stock_count` of 1 or more — or the issuance fails with
        `ERR_STATION_SEAL_STOCK_EXHAUSTED`."

        Design: Difficulty/priority_pair_validation_conflict/state_check_beats_seal_stock_check_on_quarantine_issuance
        """
        ctx, second_record = _exhausted_shelf_with_an_undispositioned_record()
        dispose_record(second_record["id"], ctx["inspector_a"]["id"], "DECON")

        response = _issue_call(
            second_record["id"], ctx["inspector_a"]["id"], "MT-SEAL-0201"
        )

        validate_error(response, ApiErrorId.ERR_STATION_SEAL_STOCK_EXHAUSTED)
        assert fetch_record(second_record["id"])["inspection_status"] == "DECON_REQUIRED"
        assert fetch_station(ctx["station"]["id"])["seal_stock_count"] == 0
