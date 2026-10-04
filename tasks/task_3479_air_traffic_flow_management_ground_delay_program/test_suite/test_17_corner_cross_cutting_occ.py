"""Corner queue: optimistic concurrency, version discipline, and derived-field
reconciliation after compression."""

from test_helpers import (
    FLOW_MANAGER_HEADERS,
    ApiErrorId,
    apply_revision,
    assert_delay_ledger,
    assert_instant,
    at,
    create_airport,
    create_carrier,
    create_revision,
    file_flight,
    flight_update_payload,
    get_flight,
    get_tmi,
    ledger_for,
    list_tmi_ledgers,
    run_compression,
    setup_active_gdp,
    setup_compression_scenario,
    tmi_revision_payload,
    update_flight,
    validate_error,
    validate_success,
)


class TestOccTmiRevisionStaleRejected:
    def test_revision_on_moved_baseline_rejected(self, api):
        """PRD §2.7: "Creating a revision requires the request to carry
        `expected_tmi_version`, holding the client's last observed `version` of
        the TrafficManagementInitiative. If the TMI's current `version` has
        advanced past the supplied value — because another writer has mutated
        the initiative since the client last read it — the create is rejected
        with `ERR_STALE_VERSION` (HTTP 412), so the client re-reads the moved
        baseline instead of chaining a revision onto a state it never
        observed."

        Design: Corner/cross_cutting_complexity_layers/occ_tmi_revision_stale_rejected
        """
        world = setup_active_gdp(api, flight_specs=())
        tmi_id = world["tmi"]["id"]
        stale_version = get_tmi(api, tmi_id)["version"]

        # a legitimate revision cycle advances the version twice
        create_revision(api, tmi_id, new_controlled_rate=10, reason="first")
        apply_revision(api, tmi_id)
        assert get_tmi(api, tmi_id)["status"] == "ACTIVE"

        # the TMI is ACTIVE again — only the version check can reject this
        resp = api.create_tmi_revision(
            tmi_id,
            tmi_revision_payload(
                expected_tmi_version=stale_version,
                new_controlled_rate=12, reason="stale baseline",
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        tmi_after = get_tmi(api, tmi_id)
        assert tmi_after["status"] == "ACTIVE"
        assert tmi_after["revision_count"] == 1


class TestOccFlightUpdateStaleRejected:
    def test_replayed_eta_update_rejected(self, api):
        """PRD §2.7: "Submitting a flight data-exchange update requires
        `expected_flight_version`, holding the client's last observed `version`
        of the Flight. A mismatch with the flight's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412). ETA and ops updates are
        otherwise always legal on non-terminal flights and never change a state
        field that would reject a later update, so the stale-version check is
        the only correct rejection for a moved baseline — note that a cascaded
        slot mutation may itself have advanced the flight's `version` between
        the client's read and its write."

        Design: Corner/cross_cutting_complexity_layers/occ_flight_update_stale_rejected
        """
        facility = create_airport(api)
        operator, operator_headers = create_carrier(api)
        flight = file_flight(api, operator, facility["id"], scheduled_arrival=at("13:05"))
        observed_version = flight["version"]

        first = update_flight(api, flight, new_eta=at("13:20"))
        assert first["version"] == observed_version + 1

        resp = api.update_flight(
            flight["id"],
            flight_update_payload(
                expected_flight_version=observed_version, new_eta=at("13:25")
            ),
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert_instant(
            get_flight(api, flight["id"])["estimated_arrival"], at("13:20"),
            "the rejected replay left the first update's ETA in place",
        )


class TestVersionIncrementsOnMutation:
    def test_exactly_one_increment_per_mutation(self, api):
        """PRD §2.4: "`version` is an integer that increments by exactly one on
        every mutation; clients read it and echo it back on the
        optimistic-concurrency-guarded writes described in §2.7."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_mutation
        """
        facility = create_airport(api)
        operator, _ = create_carrier(api)
        flight = file_flight(api, operator, facility["id"], scheduled_arrival=at("13:05"))
        assert flight["version"] == 1
        updated = update_flight(api, flight, new_eta=at("13:20"))
        assert updated["version"] == 2, "one accepted update, one increment"


class TestDerivedFieldReconciliationAfterCompression:
    def test_ledgers_track_source_mutations_exactly(self, api):
        """PRD §3.9: "One ledger exists per operator per program, created at
        activation for every operator with at least one eligible flight,
        recording a `flight_count` — the operator's flights holding slots or
        virtual CTAs in the program, set at activation and decremented on
        cancellation removal — and a running `attributed_delay_minutes`,
        reconciled on every slot mutation, alongside the
        `reversed_delay_minutes` that compensation returns."
        PRD §3.9: "On activation and after every delay-affecting mutation —
        substitution, compression, revision application, cancellation removal —
        the system recomputes each operator's fair share of the program's total
        delay."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_after_compression
        """
        world = setup_compression_scenario(api)  # A1 cancelled before the run
        run_compression(api, world["tmi"]["id"])

        ledgers = list_tmi_ledgers(api, world["tmi"]["id"])
        for ledger in ledgers:
            assert_delay_ledger(ledger)
        op_a, op_b = world["operators"]
        ledger_a = ledger_for(ledgers, op_a["id"])
        ledger_b = ledger_for(ledgers, op_b["id"])
        # A2/A3 moved up to 13:00/13:05, at or before their schedules
        assert ledger_a["flight_count"] == 2, "the cancelled A1 was removed"
        assert ledger_a["attributed_delay_minutes"] == 0
        assert ledger_b["flight_count"] == 2
        assert ledger_b["attributed_delay_minutes"] == 0
        assert ledger_a["fair_share_minutes"] == 0
        assert ledger_b["fair_share_minutes"] == 0, (
            "total delay 0 reconciles exactly: floors 0, leftover 0"
        )
        assert ledger_a["deviation_minutes"] == 0
        assert ledger_b["deviation_minutes"] == 0
