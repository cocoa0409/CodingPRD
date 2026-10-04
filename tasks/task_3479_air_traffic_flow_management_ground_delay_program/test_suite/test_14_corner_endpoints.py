"""Corner queue: listing behaviour — pagination, filters, log ordering, and
the two parents a ledger is reachable from."""

from test_helpers import (
    FLOW_MANAGER_HEADERS,
    ApiErrorId,
    assert_instant,
    assert_slot_transaction,
    at,
    create_airport,
    create_carrier,
    file_flights,
    ledger_for,
    list_flights,
    list_operator_ledgers,
    list_slot_transactions,
    list_tmi_ledgers,
    set_clock,
    setup_active_gdp,
    substitution_payload,
    transactions_of_type,
    validate_error,
    validate_success,
)


class TestPaginationDefaultsAndBounds:
    def test_default_limit_offset_pages_and_limit_cap(self, api):
        """PRD §2.3: "List endpoints accept two query parameters, `limit` and
        `offset`. `limit` defaults to 10, must be at least 1, and must not
        exceed 100; a `limit` outside that range is a malformed request
        rejected with `ERR_INVALID_REQUEST` (HTTP 400). `offset` defaults to 0.
        Every list response carries the pagination fields `limit`, `offset`,
        `total_count`, and `has_more` inside its `meta` object."

        Design: Corner/endpoints/pagination_defaults_and_bounds
        """
        set_clock(api)
        facility = create_airport(api)
        operator, _ = create_carrier(api)
        times = [f"13:{minute:02d}" for minute in range(1, 13)]
        file_flights(api, operator, facility["id"], times)

        rows, meta = list_flights(api)
        assert len(rows) == 10, "default limit is 10"
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True

        rows, meta = list_flights(api, {"limit": 10, "offset": 10})
        assert len(rows) == 2
        assert meta["total_count"] == 12
        assert meta["has_more"] is False

        resp = api.list_flights(FLOW_MANAGER_HEADERS, params={"limit": 101})
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestFlightsFilterCombination:
    def test_filters_compose(self, api):
        """PRD §3.5: "Flights are listed with optional `operator_id`,
        `arrival_facility_id`, `ops_status`, and `control_status` filters plus
        pagination."

        Design: Corner/endpoints/flights_filter_combination
        """
        world = setup_active_gdp(
            api,
            flight_specs=(
                (0, "AAL1", "13:05"), (0, "AAL2", "13:10"), (1, "BAL1", "13:15"),
            ),
        )
        op_a = world["operators"][0]
        facility = world["facility"]

        rows, meta = list_flights(
            api, {"operator_id": op_a["id"], "control_status": "SLOTTED"}
        )
        assert meta["total_count"] == 2
        assert all(r["operator_id"] == op_a["id"] for r in rows)
        assert all(r["control_status"] == "SLOTTED" for r in rows)

        rows, meta = list_flights(api, {"arrival_facility_id": facility["id"]})
        assert meta["total_count"] == 3


class TestSlotTransactionsChronological:
    def test_log_orders_initial_assignments_before_swaps(self, api):
        """PRD §3.4: "A program's transaction log is listed in chronological
        `created_at` order, filterable by `transaction_type`"
        PRD §3.5: "A legal swap exchanges the two flights' controlled arrival
        times, writes two `SUBSTITUTION_SWAP` transactions with opposite
        `delay_delta_minutes` values — the created response returns the
        transaction recorded for `flight_id_1` — recomputes both flights'
        `provisional_delay_minutes`, reconciles the operator's ledger, and
        recomputes fair shares, all while conserving the program's
        assigned-slot multiset exactly."

        Design: Corner/endpoints/slot_transactions_chronological
        """
        world = setup_active_gdp(
            api, carrier_names=("Alpha Air",),
            flight_specs=((0, "AAL1", "13:05"), (0, "AAL2", "13:20")),
        )
        f1, f2 = world["flights"]
        tmi_id = world["tmi"]["id"]

        # move the clock so the swap group is strictly later than activation's
        set_clock(api, at("12:30"))
        resp = api.create_substitution(
            tmi_id, substitution_payload(f1["id"], f2["id"]),
            world["operator_headers"][0],
        )
        transaction = validate_success(resp, 201)
        assert transaction["transaction_type"] == "SUBSTITUTION_SWAP"
        assert transaction["flight_id"] == f1["id"]
        assert_instant(transaction["from_slot_time"], at("13:00"), "swap from")
        assert_instant(transaction["to_slot_time"], at("13:10"), "swap to")
        assert transaction["delay_delta_minutes"] == 5

        rows, meta = list_slot_transactions(api, tmi_id)
        assert meta["total_count"] == 4
        for row in rows:
            assert_slot_transaction(row)
        type_sequence = [t["transaction_type"] for t in rows]
        assert type_sequence == [
            "INITIAL_ASSIGNMENT", "INITIAL_ASSIGNMENT",
            "SUBSTITUTION_SWAP", "SUBSTITUTION_SWAP",
        ], "created_at ascending places activation's writes before the swap's"
        initial_by_flight = {
            t["flight_id"]: t
            for t in transactions_of_type(rows, "INITIAL_ASSIGNMENT")
        }
        assert initial_by_flight[f1["id"]]["from_slot_time"] is None
        assert_instant(initial_by_flight[f1["id"]]["to_slot_time"], at("13:00"), "f1 initial")
        assert_instant(initial_by_flight[f2["id"]]["to_slot_time"], at("13:10"), "f2 initial")

        filtered, meta = list_slot_transactions(
            api, tmi_id, {"transaction_type": "SUBSTITUTION_SWAP"}
        )
        assert meta["total_count"] == 2
        assert {t["flight_id"] for t in filtered} == {f1["id"], f2["id"]}


class TestDelayLedgersDualReachable:
    def test_same_ledger_from_operator_and_program(self, api):
        """PRD §3.9: "Ledgers are listed per operator and per program, giving
        both the operator-centric and the program-centric view of the same
        numbers."

        Design: Corner/endpoints/delay_ledgers_dual_reachable
        """
        world = setup_active_gdp(
            api,
            flight_specs=((0, "AAL1", "13:05"), (1, "BAL1", "13:15")),
        )
        tmi_id = world["tmi"]["id"]
        op_a, op_b = world["operators"]

        operator_side = list_operator_ledgers(api, op_a["id"])
        assert len(operator_side) == 1, "one program touched this operator"
        assert operator_side[0]["tmi_id"] == tmi_id
        assert operator_side[0]["attributed_delay_minutes"] == 0, (
            "A1 scheduled 13:05 took slot 13:00: no attributable delay"
        )

        program_side = list_tmi_ledgers(api, tmi_id)
        assert len(program_side) == 2
        same_rows = {
            (row["operator_id"], row["attributed_delay_minutes"]) for row in program_side
        }
        assert same_rows == {(op_a["id"], 0), (op_b["id"], 0)}, (
            "both parents resolve the same ledger set with the same numbers"
        )
        ledger_a = ledger_for(program_side, op_a["id"])
        assert ledger_a["id"] == operator_side[0]["id"]
