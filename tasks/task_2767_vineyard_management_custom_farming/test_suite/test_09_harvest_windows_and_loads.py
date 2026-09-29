"""Winery receiving slots, load booking and the weigh-tag outcomes."""
from test_helpers import (
    ApiErrorId,
    assert_block_harvest_ledger,
    assert_delivery_window,
    assert_harvest_load,
    assert_instant,
    assert_money,
    assert_version,
    assert_window_tonnage_invariant,
    make_crew_supervisor_headers,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestOpeningAReceivingSlot:
    """PRD §2.6 and §3.8 — the slot has both a clock and a scale."""

    def test_a_slot_that_ends_before_it_starts_is_refused(self, api):
        """A `VineyardManager` opens a receiving slot by naming the `winery_name` that will receive the fruit (non-blank, 1 to 120 characters), the `window_start` and `window_end` instants that bound it — the end strictly later than the start — and the `capacity_tons` the winery will take in that slot, which must be strictly greater than zero.

        Design: Corner/entities/delivery_window_with_end_before_start_rejected
        """
        validate_error(
            api.create_delivery_window(
                f.delivery_window_payload(
                    window_start="2026-09-14T18:00:00Z",
                    window_end="2026-09-14T06:00:00Z",
                    capacity_tons=40.00,
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

        window = validate_success(
            api.create_delivery_window(f.delivery_window_payload(), fx.VM), 201
        )
        assert_delivery_window(window)
        assert_money(window["capacity_tons"], 40.00, "capacity_tons")
        assert_money(window["committed_tons"], 0.00, "committed_tons")
        assert_money(window["remaining_tons"], 40.00, "remaining_tons")
        assert window["window_posture"] == "OPEN"
        assert_version(window, 1, "delivery window")


class TestWeighTagStatePreconditions:
    """PRD §3.8 — each winery outcome demands the load already be in flight."""

    def test_receiving_a_load_that_never_left_the_block_is_refused(self, api):
        """Both require the load to be `IN_TRANSIT`, otherwise `ERR_LOAD_NOT_IN_TRANSIT`, and both are the `VineyardManager`'s to record.

        Design: Corner/state_machines/harvest_receive_from_planned_rejected
        """
        s = fx.setup_harvest_ready(api)
        s = fx.setup_booked_load(api, s, estimated_tons=12.40,
                                 delivery_eta="2026-09-14T09:00:00Z")
        assert s.load["load_status"] == "PLANNED"

        validate_error(
            api.receive_harvest_load(
                s.load["id"], f.receive_load_payload(13.1, 0.7, 0.0, 25.1), fx.VM
            ),
            ApiErrorId.ERR_LOAD_NOT_IN_TRANSIT,
        )

        load = fx.read_harvest_load(api, s.load["id"])
        assert load["load_status"] == "PLANNED"
        assert load["net_tons"] is None
        assert load["quality_incentive_amount"] is None
        assert load["dispatched_at"] is None
        assert load["received_at"] is None
        assert_version(load, 1, "harvest load")

        assert_block_harvest_ledger(fx.read_block(api, s.block["id"]),
                                    91.47, 12.40, 0.00, 79.07, "OPEN")
        assert_money(
            fx.read_contract(api, s.contract["id"])["accrued_quality_incentive"],
            0.00, "accrued_quality_incentive",
        )

    def test_dispatching_a_load_a_second_time_is_refused(self, api):
        """The load must be `PLANNED`, otherwise `ERR_LOAD_NOT_PLANNED`, and the crew must be `ACTIVE`.

        Design: Corner/state_machines/harvest_dispatch_twice_rejected
        """
        s = fx.setup_harvest_ready(api)
        s = fx.setup_dispatched_load(api, s)
        assert s.load["load_status"] == "IN_TRANSIT"

        validate_error(
            api.dispatch_harvest_load(
                s.load["id"], f.dispatch_load_payload(14.9),
                make_crew_supervisor_headers(s.crew["id"]),
            ),
            ApiErrorId.ERR_LOAD_NOT_PLANNED,
        )

        load = fx.read_harvest_load(api, s.load["id"])
        assert load["load_status"] == "IN_TRANSIT"
        assert_money(load["gross_tons_at_dispatch"], 13.10,
                     "gross_tons_at_dispatch")
        assert_instant(load["dispatched_at"], "2026-09-14T07:00:00Z",
                       "dispatched_at")
        assert_version(load, 2, "harvest load")

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 12.40, "committed_tons")
        assert_money(window["remaining_tons"], 27.60, "remaining_tons")
        assert window["window_posture"] == "OPEN"
        assert_version(window, 2, "delivery window")
        assert_window_tonnage_invariant(window)


class TestWeighTagArithmetic:
    """PRD §3.8 — the payable tonnage and the sugar incentive."""

    def test_the_material_deduction_applies_after_the_tare(self, api):
        """The payable tonnage is then `gross_tons` less `tare_tons`, multiplied by one minus `mog_deduct_pct`, rounded to two decimal places, and stored as `net_tons` — a 13.10-ton gross against a 0.70-ton tare with no deduction gives 12.40 net tons, and the same weigh tag with a two-percent deduction gives 12.15.

        Design: Corner/calculations/harvest_net_tons_applies_mog_deduction_after_tare
        """
        s = fx.setup_harvest_ready(api)
        s = fx.setup_dispatched_load(api, s)

        load = validate_success(
            api.receive_harvest_load(
                s.load["id"], f.receive_load_payload(13.1, 0.7, 0.02, 25.1), fx.VM
            )
        )

        assert_harvest_load(load)
        assert load["load_status"] == "RECEIVED"
        assert_money(load["net_tons"], 12.15, "net_tons")
        assert_money(load["quality_incentive_amount"], 546.75,
                     "quality_incentive_amount")

        assert_block_harvest_ledger(fx.read_block(api, s.block["id"]),
                                    91.47, 0.00, 12.15, 79.32, "OPEN")

        contract = fx.read_contract(api, s.contract["id"])
        assert_money(contract["accrued_quality_incentive"], 546.75,
                     "accrued_quality_incentive")
        assert_money(contract["projected_total_billable"], 12421.75,
                     "projected_total_billable")


class TestBookingGauntlet:
    """PRD §2.6 and §3.8 — the longest ladder in the specification."""

    def test_fruit_from_an_unenrolled_block_cannot_be_booked(self, api):
        """The block must be enrolled under an agreement, so a null `contract_id` is refused with `ERR_BLOCK_NOT_ENROLLED`, and unenrolled fruit therefore cannot be sold through this system at all.

        Design: Corner/validations/harvest_load_for_unenrolled_block_rejected
        """
        s = fx.setup_harvest_ready(api)
        outside = fx.create_block_b14(api, s.vineyard["id"])
        assert outside["contract_id"] is None

        validate_error(
            api.create_harvest_load(
                f.harvest_load_payload(
                    outside["id"], s.crew["id"], s.window["id"],
                    fx.window_version(api, s.window["id"]),
                    estimated_tons=5.0,
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_BLOCK_NOT_ENROLLED,
        )

        assert_money(fx.read_block(api, outside["id"])["committed_harvest_tons"],
                     0.00, "committed_harvest_tons")

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 0.00, "committed_tons")
        assert_money(window["remaining_tons"], 40.00, "remaining_tons")
        assert_version(window, 1, "delivery window")

    def test_the_harvest_tolerance_permits_ten_percent_over_the_estimate(self, api):
        """The block's harvest ceiling then requires that the block's `committed_harvest_tons` plus its `received_tons` plus the new `estimated_tons`, rounded to two decimal places, not exceed the block's `governing_estimate_tons` multiplied by a harvest tolerance of 1.10, that product likewise rounded to two decimal places.

        Design: Corner/validations/harvest_load_exceeding_yield_tolerance_rejected
        """
        s = fx.setup_harvest_ready(api, capacity_tons=120.00)
        assert_money(s.block["governing_estimate_tons"], 91.47,
                     "governing_estimate_tons")

        validate_error(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"],
                    fx.window_version(api, s.window["id"]),
                    estimated_tons=100.63,
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_HARVEST_EXCEEDS_ESTIMATE,
        )
        assert_money(fx.read_block(api, s.block["id"])["committed_harvest_tons"],
                     0.00, "committed_harvest_tons")

        load = validate_success(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"],
                    fx.window_version(api, s.window["id"]),
                    estimated_tons=100.62,
                ),
                fx.VM,
            ),
            201,
        )
        assert_harvest_load(load)
        assert load["load_status"] == "PLANNED"

        assert_block_harvest_ledger(fx.read_block(api, s.block["id"]),
                                    91.47, 100.62, 0.00, -9.15, "COMPLETE")

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 100.62, "committed_tons")
        assert_money(window["remaining_tons"], 19.38, "remaining_tons")
        assert window["window_posture"] == "OPEN"

    def test_an_arrival_one_second_early_falls_outside_the_slot(self, api):
        """The `delivery_eta` must also fall inside the window's closed interval, at or after `window_start` and at or before `window_end`; both ends are inclusive, and an arrival outside them is refused with `ERR_DELIVERY_ETA_OUTSIDE_WINDOW`.

        Design: Corner/validations/harvest_load_eta_one_second_before_window_start_rejected
        """
        s = fx.setup_harvest_ready(api)
        opening_version = fx.window_version(api, s.window["id"])

        validate_error(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"], opening_version,
                    estimated_tons=12.40,
                    delivery_eta="2026-09-14T05:59:59Z",
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_DELIVERY_ETA_OUTSIDE_WINDOW,
        )
        assert_version(fx.read_delivery_window(api, s.window["id"]),
                       opening_version, "delivery window")

        load = validate_success(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"], opening_version,
                    estimated_tons=12.40,
                    delivery_eta="2026-09-14T06:00:00Z",
                ),
                fx.VM,
            ),
            201,
        )
        assert_harvest_load(load)
        assert load["load_status"] == "PLANNED"

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 12.40, "committed_tons")
        assert_money(window["remaining_tons"], 27.60, "remaining_tons")
        assert window["window_posture"] == "OPEN"
        assert_window_tonnage_invariant(window)

    def test_a_weigh_tag_whose_tare_exceeds_its_gross_is_refused(self, api):
        """As §2.6 requires, `tare_tons` must be strictly less than `gross_tons` and `mog_deduct_pct` must lie between 0 and 1 inclusive.

        Design: Corner/validations/harvest_receive_with_tare_above_gross_rejected
        """
        s = fx.setup_harvest_ready(api)
        s = fx.setup_dispatched_load(api, s)

        validate_error(
            api.receive_harvest_load(
                s.load["id"], f.receive_load_payload(13.1, 13.5, 0.0, 25.1), fx.VM
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        validate_error(
            api.receive_harvest_load(
                s.load["id"], f.receive_load_payload(13.1, 0.7, 1.5, 25.1), fx.VM
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

        held = fx.read_harvest_load(api, s.load["id"])
        assert held["load_status"] == "IN_TRANSIT"
        assert held["net_tons"] is None
        assert held["quality_incentive_amount"] is None

        received = fx.receive_harvest_load(api, s.load["id"], gross_tons=13.1,
                                           tare_tons=0.7, mog_deduct_pct=0.0)
        assert received["load_status"] == "RECEIVED"
        assert_money(received["net_tons"], 12.40, "net_tons")

        assert_block_harvest_ledger(fx.read_block(api, s.block["id"]),
                                    91.47, 0.00, 12.40, 79.07, "OPEN")

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 0.00, "committed_tons")
        assert_money(window["remaining_tons"], 40.00, "remaining_tons")


class TestBookingConcurrencyGuard:
    """PRD §2.8 — the booking quotes the window version it last observed."""

    def test_a_booking_quoting_a_superseded_window_version_is_refused(self, api):
        """If the window's `version` has advanced since that read, the booking is rejected with `ERR_STALE_DELIVERY_WINDOW_VERSION` (HTTP 412).

        Design: Corner/complexity layers/stale_delivery_window_version_on_harvest_load_returns_conflict
        """
        s = fx.setup_harvest_ready(api)
        s = fx.setup_booked_load(api, s, estimated_tons=12.40,
                                 delivery_eta="2026-09-14T09:00:00Z")

        window = fx.read_delivery_window(api, s.window["id"])
        assert_version(window, 2, "delivery window")
        assert_money(window["committed_tons"], 12.40, "committed_tons")

        validate_error(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"],
                    window["version"] - 1,
                    estimated_tons=12.40,
                    delivery_eta="2026-09-14T12:00:00Z",
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_STALE_DELIVERY_WINDOW_VERSION,
        )
        refused = fx.read_delivery_window(api, s.window["id"])
        assert_money(refused["committed_tons"], 12.40, "committed_tons")
        assert_version(refused, 2, "delivery window")

        retry = validate_success(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"], window["version"],
                    estimated_tons=12.40,
                    delivery_eta="2026-09-14T12:00:00Z",
                ),
                fx.VM,
            ),
            201,
        )
        assert retry["load_status"] == "PLANNED"

        booked = fx.read_delivery_window(api, s.window["id"])
        assert_money(booked["committed_tons"], 24.80, "committed_tons")
        assert_money(booked["remaining_tons"], 15.20, "remaining_tons")
        assert booked["window_posture"] == "OPEN"
        assert_version(booked, 3, "delivery window")
        assert_money(fx.read_block(api, s.block["id"])["committed_harvest_tons"],
                     24.80, "committed_harvest_tons")


class TestWindowPostureBoundary:
    """PRD §2.7 and §3.8 — the utilisation ratio is judged unrounded."""

    def test_a_slot_at_exactly_eighty_five_percent_reads_nearly_full(self, api):
        """`window_posture` is derived from the unrounded ratio of `committed_tons` to `capacity_tons`: it is `FULL` when that ratio is at least 1.00, `NEARLY_FULL` when the ratio is at least 0.85 but below 1.00, and `OPEN` otherwise.

        Design: Corner/complexity layers/window_posture_crosses_into_nearly_full_at_eighty_five_percent
        """
        s = fx.setup_harvest_ready(api, capacity_tons=20.00)

        validate_success(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"],
                    fx.window_version(api, s.window["id"]),
                    estimated_tons=16.99,
                    delivery_eta="2026-09-14T09:00:00Z",
                ),
                fx.VM,
            ),
            201,
        )

        under = fx.read_delivery_window(api, s.window["id"])
        assert_money(under["committed_tons"], 16.99, "committed_tons")
        assert_money(under["remaining_tons"], 3.01, "remaining_tons")
        assert under["window_posture"] == "OPEN"

        validate_success(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"], under["version"],
                    estimated_tons=0.01,
                    delivery_eta="2026-09-14T15:00:00Z",
                ),
                fx.VM,
            ),
            201,
        )

        crossed = fx.read_delivery_window(api, s.window["id"])
        assert_money(crossed["committed_tons"], 17.00, "committed_tons")
        assert_money(crossed["remaining_tons"], 3.00, "remaining_tons")
        assert crossed["window_posture"] == "NEARLY_FULL"
        assert_window_tonnage_invariant(crossed)

        assert_money(fx.read_block(api, s.block["id"])["committed_harvest_tons"],
                     17.00, "committed_harvest_tons")


class TestReceiptCascade:
    """PRD §3.8 — one receipt moves the load, the block, the agreement and the slot."""

    def test_the_receipt_credits_the_load_and_the_block_ledger(self, api):
        """Receipt then cascades four levels: the load moves `IN_TRANSIT → RECEIVED` with `received_at` stamped; the block's `committed_harvest_tons`, `received_tons`, `remaining_estimated_tons` and `harvest_posture` are recomputed and the block's `version` incremented by 1; the agreement's `accrued_quality_incentive` — the sum of `quality_incentive_amount` over all `RECEIVED` loads from blocks enrolled under it, rounded to two decimal places — and its `projected_total_billable` are recomputed and the agreement's `version` incremented by 1; and the window's `committed_tons`, `remaining_tons` and `window_posture` are recomputed with the window's `version` incremented by 1.

        Design: Difficulty/transitive_cascade/harvest_receive_cascades_four_levels_to_projected_billable
        """
        s = fx.setup_harvest_ready(api)
        s = fx.setup_dispatched_load(api, s, estimated_tons=12.40,
                                     delivery_eta="2026-09-14T09:00:00Z")

        load = validate_success(
            api.receive_harvest_load(
                s.load["id"], f.receive_load_payload(13.1, 0.7, 0.0, 25.1), fx.VM
            )
        )

        assert_harvest_load(load)
        assert load["load_status"] == "RECEIVED"
        assert_money(load["net_tons"], 12.40, "net_tons")
        assert_money(load["quality_incentive_amount"], 558.00,
                     "quality_incentive_amount")
        assert_instant(load["received_at"], "2026-09-14T07:00:00Z", "received_at")

        assert_block_harvest_ledger(fx.read_block(api, s.block["id"]),
                                    91.47, 0.00, 12.40, 79.07, "OPEN")

    def test_the_receipt_reaches_the_agreement_and_releases_the_slot(self, api):
        """`projected_total_billable` is that base plus the agreement's `accrued_quality_incentive`, rounded to two decimal places — pass-through and volume discount are excluded from the projection by design, and only a settlement run computes them.

        Design: Difficulty/transitive_cascade/harvest_receive_cascades_four_levels_to_projected_billable
        """
        s = fx.setup_harvest_ready(api)
        contract_before = fx.read_contract(api, s.contract["id"])
        assert_money(contract_before["accrued_quality_incentive"], 0.00,
                     "accrued_quality_incentive")
        assert_money(contract_before["projected_total_billable"], 11875.00,
                     "projected_total_billable")

        s = fx.setup_dispatched_load(api, s, estimated_tons=12.40,
                                     delivery_eta="2026-09-14T09:00:00Z")
        fx.receive_harvest_load(api, s.load["id"], gross_tons=13.1, tare_tons=0.7,
                                mog_deduct_pct=0.0, brix_at_receipt=25.1)

        contract = fx.read_contract(api, s.contract["id"])
        assert_money(contract["accrued_quality_incentive"], 558.00,
                     "accrued_quality_incentive")
        assert_money(contract["projected_total_billable"], 12433.00,
                     "projected_total_billable")
        assert_version(contract, contract_before["version"] + 1, "agreement")

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 0.00, "committed_tons")
        assert_money(window["remaining_tons"], 40.00, "remaining_tons")
        assert window["window_posture"] == "OPEN"
        assert_window_tonnage_invariant(window)


class TestSlotIsAnAggregateResource:
    """PRD §3.8 — the slot is rationed by tonnage, not by arrival time."""

    def test_two_loads_may_share_one_arrival_instant(self, api):
        """Note that this is a containment test on a single instant and nothing more — any number of loads may share the same `delivery_eta`, because the slot is rationed by tonnage rather than by arrival time.

        Design: Difficulty/resource_temporal_overlap/delivery_window_permits_overlapping_etas_until_aggregate_capacity
        """
        s = fx.setup_harvest_ready(
            api, capacity_tons=18.00,
            window_overrides={"window_start": "2026-09-15T06:00:00Z",
                              "window_end": "2026-09-15T18:00:00Z"},
        )

        first = validate_success(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"],
                    fx.window_version(api, s.window["id"]),
                    estimated_tons=8.0,
                    delivery_eta="2026-09-15T09:00:00Z",
                ),
                fx.VM,
            ),
            201,
        )
        second = validate_success(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"],
                    fx.window_version(api, s.window["id"]),
                    estimated_tons=8.0,
                    delivery_eta="2026-09-15T09:00:00Z",
                ),
                fx.VM,
            ),
            201,
        )

        assert first["load_status"] == "PLANNED"
        assert second["load_status"] == "PLANNED"
        assert_instant(first["delivery_eta"], "2026-09-15T09:00:00Z", "delivery_eta")
        assert_instant(second["delivery_eta"], "2026-09-15T09:00:00Z", "delivery_eta")

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 16.00, "committed_tons")
        assert_money(window["remaining_tons"], 2.00, "remaining_tons")
        assert window["window_posture"] == "NEARLY_FULL"
        assert_window_tonnage_invariant(window)

    def test_the_slot_fills_to_capacity_and_then_refuses_more_tonnage(self, api):
        """The window's tonnage ceiling requires that the window's current `committed_tons` plus the new `estimated_tons`, rounded to two decimal places, not exceed its `capacity_tons`; equality is permitted, and anything above is refused with `ERR_WINDOW_CAPACITY_EXCEEDED`.

        Design: Difficulty/resource_temporal_overlap/delivery_window_permits_overlapping_etas_until_aggregate_capacity
        """
        s = fx.setup_harvest_ready(
            api, capacity_tons=18.00,
            window_overrides={"window_start": "2026-09-15T06:00:00Z",
                              "window_end": "2026-09-15T18:00:00Z"},
        )
        for _ in range(2):
            validate_success(
                api.create_harvest_load(
                    f.harvest_load_payload(
                        s.block["id"], s.crew["id"], s.window["id"],
                        fx.window_version(api, s.window["id"]),
                        estimated_tons=8.0,
                        delivery_eta="2026-09-15T09:00:00Z",
                    ),
                    fx.VM,
                ),
                201,
            )
        booked_version = fx.window_version(api, s.window["id"])

        validate_error(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"], booked_version,
                    estimated_tons=4.0,
                    delivery_eta="2026-09-15T09:00:00Z",
                ),
                fx.VM,
            ),
            ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED,
        )

        exact = validate_success(
            api.create_harvest_load(
                f.harvest_load_payload(
                    s.block["id"], s.crew["id"], s.window["id"], booked_version,
                    estimated_tons=2.0,
                    delivery_eta="2026-09-15T17:00:00Z",
                ),
                fx.VM,
            ),
            201,
        )
        assert exact["load_status"] == "PLANNED"

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 18.00, "committed_tons")
        assert_money(window["remaining_tons"], 0.00, "remaining_tons")
        assert window["window_posture"] == "FULL"
        assert_window_tonnage_invariant(window)

        assert_block_harvest_ledger(fx.read_block(api, s.block["id"]),
                                    91.47, 18.00, 0.00, 73.47, "OPEN")


class TestSlotTonnageIsConserved:
    """PRD §3.8 — the booking is consumed once and returned once."""

    def test_dispatch_consumes_no_further_slot_capacity(self, api):
        """Dispatching a load does not move `committed_tons` at all — the tonnage is still booked and still on its way — while receiving or rejecting it releases the booking, which is why both winery outcomes free window capacity even though only one of them credits the block.

        Design: Difficulty/compensating_invariant/window_tonnage_invariant_holds_across_book_dispatch_reject
        """
        s = fx.setup_harvest_ready(api)
        s = fx.setup_booked_load(api, s, estimated_tons=12.40,
                                 delivery_eta="2026-09-14T09:00:00Z")
        assert s.load["load_status"] == "PLANNED"

        booked = fx.read_delivery_window(api, s.window["id"])
        assert_money(booked["committed_tons"], 12.40, "committed_tons")
        assert_money(booked["remaining_tons"], 27.60, "remaining_tons")
        assert_window_tonnage_invariant(booked)

        fx.set_clock(api, "2026-09-14T07:00:00Z")
        dispatched = fx.dispatch_harvest_load(api, s.load["id"], s.crew["id"], 13.10)
        assert dispatched["load_status"] == "IN_TRANSIT"
        assert_instant(dispatched["dispatched_at"], "2026-09-14T07:00:00Z",
                       "dispatched_at")

        in_transit = fx.read_delivery_window(api, s.window["id"])
        assert_money(in_transit["committed_tons"], 12.40, "committed_tons")
        assert_money(in_transit["remaining_tons"], 27.60, "remaining_tons")
        assert in_transit["window_posture"] == "OPEN"
        assert_window_tonnage_invariant(in_transit)

    def test_a_rejection_returns_the_whole_booking_to_the_slot(self, api):
        """`remaining_tons` is `capacity_tons` less `committed_tons`, rounded to two decimal places, and the invariant that `committed_tons` plus `remaining_tons` equals `capacity_tons` holds at every observable instant.

        Design: Difficulty/compensating_invariant/window_tonnage_invariant_holds_across_book_dispatch_reject
        """
        s = fx.setup_harvest_ready(api)
        s = fx.setup_dispatched_load(api, s, estimated_tons=12.40,
                                     delivery_eta="2026-09-14T09:00:00Z")

        rejected = fx.reject_harvest_load(api, s.load["id"], "MOG_EXCESS")
        assert_harvest_load(rejected)
        assert rejected["load_status"] == "REJECTED"
        assert rejected["rejection_reason"] == "MOG_EXCESS"
        assert_money(rejected["net_tons"], 0.00, "net_tons")
        assert_money(rejected["quality_incentive_amount"], 0.00,
                     "quality_incentive_amount")

        window = fx.read_delivery_window(api, s.window["id"])
        assert_money(window["committed_tons"], 0.00, "committed_tons")
        assert_money(window["remaining_tons"], 40.00, "remaining_tons")
        assert window["window_posture"] == "OPEN"
        assert_window_tonnage_invariant(window)

        assert_block_harvest_ledger(fx.read_block(api, s.block["id"]),
                                    91.47, 0.00, 0.00, 91.47, "OPEN")

        contract = fx.read_contract(api, s.contract["id"])
        assert_money(contract["accrued_quality_incentive"], 0.00,
                     "accrued_quality_incentive")
        assert_money(contract["projected_total_billable"], 11875.00,
                     "projected_total_billable")
