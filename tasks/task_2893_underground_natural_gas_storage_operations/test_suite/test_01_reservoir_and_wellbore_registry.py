"""Reservoir and wellbore registration, reads, listings and input discipline."""

import pytest

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_CONTRACT_NOT_FOUND,
    ERR_FIELD_FROZEN,
    ERR_INVALID_REQUEST,
    ERR_STORAGE_FIELD_NOT_FOUND,
    ERR_WELL_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_created,
    assert_created_at_ascending,
    assert_error_envelope,
    assert_field_derived_block,
    assert_instant_equals,
    assert_ledger_entry,
    assert_money,
    assert_number,
    assert_ok,
    assert_pct,
    assert_volume,
)
from test_helpers.constants import (
    CLOCK_EPOCH,
    CONTRACT_DRAFT,
    CREDIT_GOOD,
    DELIVERABILITY_CURVE_INTERPOLATED,
    INTEGRITY_MIT_CURRENT,
    LEDGER_DAILY_IMBALANCE,
    NOMINATION_SUBMITTED,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    SEASON_INJECTION,
    SHUT_IN_REASON_OPERATOR_REQUEST,
    TICKET_PENDING,
    TICKET_REVERSED,
    TIER_1,
    TIER_3,
    UNIT_AVAILABLE,
    WELL_IN_SERVICE,
    WELL_SHUT_IN,
    WELL_TYPE_INJECTION_WITHDRAWAL,
)
from test_helpers.fixtures import (
    build_mini_world,
    confirm_nomination,
    confirm_ticket,
    create_field,
    create_shipper,
    create_well,
    file_and_submit_nomination,
    ledger_entries,
    open_ticket,
    read_contract,
    read_field,
    read_nomination,
    reverse_ticket,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    FIELD_OPERATOR,
    INTEGRITY_ENGINEER,
    SCHEDULING_COORDINATOR,
)

ABSENT_ID = "00000000-0000-4000-8000-000000000000"


class TestReservoirRegistration:
    """Registering a reservoir and the derived block it publishes at once."""

    def test_field_with_no_wellbores_is_frozen_with_zero_rates(self, api):
        """A reservoir opened at half its working-gas ceiling still publishes both
        deliverability rates as 0 and a FROZEN posture, while its inventory-derived
        tier and pressure are fully populated on the same row.

        PRD §2.7 clause 7: "With no in-service injection/withdrawal wellbore at
        all, the mechanical capacity is zero, so both rates are exactly 0 — and
        clause 1 of §2.6 has already forced the posture to `FROZEN`."

        Design: Corner/entities/storage_field_creation_with_no_wells_is_frozen_with_zero_rates
        """
        response = api.create_storage_field(F.storage_field_payload(), FIELD_OPERATOR)
        field = assert_created(response)

        assert_volume(field["max_working_gas_dth"], 500000, "max_working_gas_dth")
        assert_field_derived_block(
            field,
            working_gas=250000,
            inventory_pct=50.00,
            pressure=1500,
            tier=TIER_3,
            injection_rate=0,
            withdrawal_rate=0,
            wells_in_service=0,
            posture=POSTURE_FROZEN,
        )
        assert_money(field["fuel_gas_used_dth"], 0, "fuel_gas_used_dth")
        assert_volume(field["retained_fuel_pool_dth"], 0, "retained_fuel_pool_dth")
        assert field["season"] == SEASON_INJECTION
        assert field["deliverability_method"] == DELIVERABILITY_CURVE_INTERPOLATED

    def test_client_supplied_derived_reservoir_figures_are_discarded(self, api):
        """A create that ships its own values for the server-derived block is
        accepted, and every one of those values is thrown away.

        PRD §2.6: "Every storage field carries a derived gate called
        `field_posture`, whose value is one of `OPEN`, `RESTRICTED` or `FROZEN`.
        Clients never set it."

        Design: Corner/entities/storage_field_computed_field_extra_field_input_ignored
        """
        payload = F.storage_field_payload(
            inventory_pct=99.99,
            max_working_gas_dth=12345,
            current_pressure_psig=2999,
            deliverability_tier=TIER_1,
            field_posture=POSTURE_OPEN,
            max_withdrawal_rate_dth_per_day=999999,
            wells_in_service_count=7,
        )
        field = assert_created(api.create_storage_field(payload, FIELD_OPERATOR))

        assert_pct(field["inventory_pct"], 50.00)
        assert_volume(field["max_working_gas_dth"], 500000, "max_working_gas_dth")
        assert_field_derived_block(
            field,
            pressure=1500,
            tier=TIER_3,
            withdrawal_rate=0,
            wells_in_service=0,
            posture=POSTURE_FROZEN,
        )

    def test_omitted_optional_inputs_fall_back_to_declared_defaults(self, api):
        """A create that supplies only the required inputs materialises every
        declared default in one pass, across four different record types.

        PRD §2.7: "`deliverability_method` selects between two published
        evaluation methods and defaults to `CURVE_INTERPOLATED` when it is not
        supplied at registration."

        Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
        """
        field = assert_created(
            api.create_storage_field(
                F.storage_field_payload(
                    name="Default Dome",
                    field_code="F-DFLT",
                    season=None,
                    opening_working_gas_dth=None,
                    deliverability_method=None,
                ),
                FIELD_OPERATOR,
            )
        )
        well = assert_created(
            api.create_well(
                F.well_payload(field["id"], well_name="DFLT-1"), FIELD_OPERATOR
            )
        )
        unit = assert_created(
            api.create_compressor_unit(
                F.compressor_unit_payload(field["id"], derate_factor=None), FIELD_OPERATOR
            )
        )
        shipper = create_shipper(api)
        contract = assert_created(
            api.create_contract(
                F.contract_payload(shipper["id"], field["id"], contract_code="CN-DFLT"),
                SCHEDULING_COORDINATOR,
            )
        )

        field = read_field(api, field["id"])
        assert field["season"] == SEASON_INJECTION
        assert field["deliverability_method"] == DELIVERABILITY_CURVE_INTERPOLATED
        assert_field_derived_block(
            field,
            working_gas=0,
            inventory_pct=0.00,
            pressure=800,
            tier=TIER_1,
            withdrawal_rate=0,
            injection_rate=300000,
            wells_in_service=1,
            posture=POSTURE_OPEN,
        )

        assert well["casing_pressure_psig"] == 0
        assert well["operational_state"] == WELL_IN_SERVICE
        assert well["integrity_state"] == INTEGRITY_MIT_CURRENT
        assert well["service_change_count"] == 0

        assert assert_number(unit["derate_factor"], "derate_factor") == pytest.approx(0.0)
        assert unit["status"] == UNIT_AVAILABLE
        assert_money(unit["lifetime_fuel_dth"], 0, "lifetime_fuel_dth")
        assert unit["scheduled_run_count"] == 0

        assert contract["status"] == CONTRACT_DRAFT
        assert contract["activated_at"] is None
        assert_volume(contract["inventory_balance_dth"], 0, "inventory_balance_dth")
        assert_volume(contract["imbalance_dth"], 0, "imbalance_dth")
        assert contract["scheduled_injection_dth"] == 0
        assert contract["scheduled_withdrawal_dth"] == 0
        assert_money(contract["cash_out_amount_usd"], 0, "cash_out_amount_usd")
        assert contract["cash_out_through_date"] is None

        assert_money(shipper["outstanding_penalty_usd"], 0, "outstanding_penalty_usd")
        assert shipper["credit_status"] == CREDIT_GOOD


class TestWellboreRegistry:
    """Wellbore registration, reads and listings."""

    def test_first_wellbore_opens_the_field_and_stamps_the_mit_due_date(self, api, bare_field):
        """Registering the first in-service injection/withdrawal wellbore stamps
        the wellbore's own 365-day deadline and re-derives the parent reservoir in
        the same request, lifting it out of FROZEN and raising both rates from 0 to
        the curve values.

        PRD §3.1: "At registration, `service_change_count` starts at 0, and
        `mit_due_at` is computed as `last_mit_passed_at` plus 365 days."

        Design: Corner/entities/well_creation_opens_the_field_and_stamps_mit_due_at_from_the_interval
        """
        response = api.create_well(F.well_payload(bare_field["id"]), FIELD_OPERATOR)
        well = assert_created(response)

        assert_instant_equals(well["mit_due_at"], "2027-06-01T00:00:00Z")
        assert well["integrity_state"] == INTEGRITY_MIT_CURRENT
        assert well["operational_state"] == WELL_IN_SERVICE
        assert well["shut_in_reason"] is None
        assert well["service_change_count"] == 0
        assert well["casing_pressure_psig"] == 0

        field = read_field(api, bare_field["id"])
        assert_field_derived_block(
            field,
            wells_in_service=1,
            posture=POSTURE_OPEN,
            withdrawal_rate=150000,
            injection_rate=150000,
            inventory_pct=50.00,
            pressure=1500,
        )

    def test_client_supplied_identity_fields_on_a_wellbore_are_discarded(self, api, bare_field):
        """id, created_at, updated_at and version are server-owned: a create that
        ships all four keeps none of them, and the derived deadline is still
        computed from the declared input rather than lifted from the body.

        PRD §2.4: "Every business record in the system carries an `id`, which is a
        server-minted UUID string with no type prefix, and a `created_at`, which is
        an ISO 8601 UTC timestamp rendered with three fractional digits (for example
        `2026-08-05T13:00:00.000Z`). Clients never supply either value."

        Design: Corner/entities/well_system_field_extra_field_input_ignored
        """
        forged_id = "11111111-1111-4111-8111-111111111111"
        payload = F.well_payload(
            bare_field["id"],
            id=forged_id,
            created_at="1999-01-01T00:00:00Z",
            updated_at="1999-01-01T00:00:00Z",
            version=42,
            mit_due_at="2099-01-01T00:00:00Z",
            service_change_count=9,
        )
        well = assert_created(api.create_well(payload, FIELD_OPERATOR))

        assert well["id"] != forged_id
        assert_instant_equals(well["created_at"], CLOCK_EPOCH)
        assert_instant_equals(well["updated_at"], CLOCK_EPOCH)
        assert well["version"] != 42
        assert_instant_equals(well["mit_due_at"], "2027-06-01T00:00:00Z")
        assert well["service_change_count"] == 0

        assert_error_envelope(api.get_well(forged_id, FIELD_OPERATOR), ERR_WELL_NOT_FOUND)

    def test_wellbore_read_returns_both_state_dimensions_to_every_reader(self, api, bare_field):
        """The single-wellbore read is shared across reader roles and hands back
        both orthogonal state dimensions plus the derived deadline, identically to
        an integrity engineer and to a compliance officer.

        PRD §3.1: "Wellbores are registered against a field by supplying its
        `storage_field_id`, along with an API `well_name`, a `well_type` of either
        `INJECTION_WITHDRAWAL` for a wellbore that moves gas or `OBSERVATION` for
        one that only monitors, a `rated_rate_dth_per_day` that may be zero or
        greater, and `last_mit_passed_at`, the instant of the last passed
        mechanical integrity test."

        Design: Corner/entities/well_retrieval_returns_both_state_dimensions_for_every_reader_role
        """
        created = create_well(api, bare_field["id"], casing_pressure_psig=1200)

        engineer_view = assert_ok(api.get_well(created["id"], INTEGRITY_ENGINEER))
        officer_view = assert_ok(api.get_well(created["id"], COMPLIANCE_OFFICER))

        for view in (engineer_view, officer_view):
            assert view["storage_field_id"] == bare_field["id"]
            assert view["well_name"] == "MINI-1"
            assert view["well_type"] == WELL_TYPE_INJECTION_WITHDRAWAL
            assert view["rated_rate_dth_per_day"] == 600000
            assert view["casing_pressure_psig"] == 1200
            assert view["operational_state"] == WELL_IN_SERVICE
            assert view["integrity_state"] == INTEGRITY_MIT_CURRENT
            assert_instant_equals(view["mit_due_at"], "2027-06-01T00:00:00Z")

        assert engineer_view == officer_view

    def test_wellbore_listing_pages_in_created_at_order(self, api, bare_field):
        """Three wellbores come back in registration order across two pages, with
        total_count measured before the window is applied.

        PRD §2.3: "All list responses are ordered by `created_at` ascending, and
        `limit` and `offset` are applied only after that ordering has been
        established. The `id` value is never used as a sort key."

        Design: Corner/entities/wells_listing_pages_by_created_at_with_total_count_and_has_more
        """
        first = create_well(api, bare_field["id"], well_name="MINI-1")
        second = create_well(api, bare_field["id"], well_name="MINI-2")
        third = create_well(api, bare_field["id"], well_name="MINI-3")

        page_one = api.list_wells(
            SCHEDULING_COORDINATOR,
            {"storage_field_id": bare_field["id"], "limit": 2, "offset": 0},
        )
        rows, meta = validate_paginated(page_one)
        assert page_one.json()["response_type"] == "array"
        assert len(rows) == 2
        assert (meta["limit"], meta["offset"], meta["total_count"], meta["has_more"]) == (
            2,
            0,
            3,
            True,
        )
        assert [r["id"] for r in rows] == [first["id"], second["id"]]
        assert [r["well_name"] for r in rows] == ["MINI-1", "MINI-2"]
        assert_created_at_ascending(rows)

        page_two = api.list_wells(
            SCHEDULING_COORDINATOR,
            {"storage_field_id": bare_field["id"], "limit": 2, "offset": 2},
        )
        rows, meta = validate_paginated(page_two)
        assert len(rows) == 1
        assert (meta["limit"], meta["offset"], meta["total_count"], meta["has_more"]) == (
            2,
            2,
            3,
            False,
        )
        assert rows[0]["id"] == third["id"]
        assert rows[0]["well_name"] == "MINI-3"


class TestInputDiscipline:
    """Rung 3 and rung 4 refusals on the registry endpoints."""

    def test_unknown_path_id_answers_the_per_type_not_found_code(self, api):
        """The same well-formed but unknown UUID resolves per resource type, and a
        sub-resource listing under an unknown parent is a 404 rather than an empty
        page.

        PRD §2.11 rung 4: "Every identifier in the request path resolves to an
        existing record, validated strictly left to right, so the leftmost
        unresolvable identifier decides the answer."

        Design: Corner/entities/storage_field_and_contract_get_by_unknown_id_return_not_found
        """
        assert_error_envelope(
            api.get_storage_field(ABSENT_ID, FIELD_OPERATOR), ERR_STORAGE_FIELD_NOT_FOUND
        )
        assert_error_envelope(
            api.get_contract(ABSENT_ID, SCHEDULING_COORDINATOR), ERR_CONTRACT_NOT_FOUND
        )
        assert_error_envelope(
            api.list_field_regulatory_reports(ABSENT_ID, COMPLIANCE_OFFICER),
            ERR_STORAGE_FIELD_NOT_FOUND,
        )

    def test_creates_missing_a_required_input_are_malformed_requests(self, api, mini_world):
        """A create that omits a required input is refused as malformed before any
        foreign key in the same body is resolved, so the bogus nomination id in the
        third call is never reported.

        PRD §2.11 rung 3: "The body conforms to the endpoint's input contract:
        required fields present, JSON types correct, enum values drawn from the
        declared sets, and numeric ranges honoured"

        Design: Corner/entities/creates_omitting_a_required_field_return_invalid_request
        """
        assert_error_envelope(
            api.create_storage_field(
                F.storage_field_payload(
                    name="No Cushion", field_code="F-NOCU", cushion_gas_dth=None
                ),
                FIELD_OPERATOR,
            ),
            ERR_INVALID_REQUEST,
        )
        assert_error_envelope(
            api.create_contract(
                F.contract_payload(
                    mini_world.shipper_id,
                    mini_world.field_id,
                    contract_code="CN-NOCM",
                    cash_out_method=None,
                ),
                SCHEDULING_COORDINATOR,
            ),
            ERR_INVALID_REQUEST,
        )
        assert_error_envelope(
            api.raw(
                "POST",
                "/gas-movement-tickets",
                {"nomination_id": ABSENT_ID, "actual_volume_dth": 1000},
                FIELD_OPERATOR,
            ),
            ERR_INVALID_REQUEST,
        )

        rows, meta = validate_paginated(
            api.list_contracts(SCHEDULING_COORDINATOR, {"limit": 100})
        )
        assert meta["total_count"] == 1, "Only the fixture contract may exist"
        assert rows[0]["id"] == mini_world.contract_id

    @pytest.mark.parametrize(
        "case",
        [
            "well_type_off_enum",
            "negative_well_rate",
            "derate_above_ceiling",
            "cushion_equals_capacity",
            "max_pressure_below_base_plus_span",
            "curve_does_not_end_at_100",
            "term_end_before_term_start",
            "limit_above_maximum",
        ],
    )
    def test_off_enum_and_out_of_range_inputs_are_malformed_requests(self, api, mini_world, case):
        """Every declared range and enum constraint is enforced at the schema rung
        and answers the malformed-request code rather than a domain-specific 422.

        PRD §2.11 rung 3: "volumes and horsepower strictly positive,
        `derate_factor` between 0.00 and 0.50 inclusive, the deliverability curve
        ascending with endpoints at 0 and 100, `scheduled_end_at` strictly after
        `scheduled_start_at`, `window_end_at` strictly after `window_start_at`,
        `term_end_date` on or after `term_start_date`"

        Design: Corner/entities/well_type_invalid_enum_and_out_of_range_numerics_are_rejected
        """
        field_id = mini_world.field_id
        if case == "well_type_off_enum":
            response = api.create_well(
                F.well_payload(field_id, well_name="BAD-TYPE", well_type="MONITORING"),
                FIELD_OPERATOR,
            )
        elif case == "negative_well_rate":
            response = api.create_well(
                F.well_payload(field_id, well_name="BAD-RATE", rated_rate_dth_per_day=-1),
                FIELD_OPERATOR,
            )
        elif case == "derate_above_ceiling":
            response = api.create_compressor_unit(
                F.compressor_unit_payload(field_id, unit_code="U-BAD", derate_factor=0.75),
                FIELD_OPERATOR,
            )
        elif case == "cushion_equals_capacity":
            response = api.create_storage_field(
                F.storage_field_payload(
                    name="All Cushion", field_code="F-CUSH", cushion_gas_dth=1000000
                ),
                FIELD_OPERATOR,
            )
        elif case == "max_pressure_below_base_plus_span":
            response = api.create_storage_field(
                F.storage_field_payload(
                    name="Low Ceiling", field_code="F-LOWP", max_pressure_psig=2000
                ),
                FIELD_OPERATOR,
            )
        elif case == "curve_does_not_end_at_100":
            response = api.create_storage_field(
                F.storage_field_payload(
                    name="Short Curve",
                    field_code="F-CURV",
                    deliverability_curve=[
                        F.curve_point(0, 0, 300000),
                        F.curve_point(80, 300000, 0),
                    ],
                ),
                FIELD_OPERATOR,
            )
        elif case == "term_end_before_term_start":
            response = api.create_contract(
                F.contract_payload(
                    mini_world.shipper_id,
                    field_id,
                    contract_code="CN-BADTERM",
                    term_start_date="2026-12-31",
                    term_end_date="2026-08-01",
                ),
                SCHEDULING_COORDINATOR,
            )
        else:
            response = api.list_wells(FIELD_OPERATOR, {"storage_field_id": field_id, "limit": 101})

        assert_error_envelope(response, ERR_INVALID_REQUEST)

    def test_wellbore_on_another_reservoir_is_reported_as_absent(self, api):
        """A wellbore that exists but sits on a different reservoir than the
        nomination's contract is reported exactly as an unknown id would be, and the
        same scoping governs the wellbore named on an emergency event.

        PRD §2.11 rung 5: "when opening a gas movement ticket, `well_id` must
        resolve to a wellbore whose `storage_field_id` equals the field behind the
        nomination's contract, and when opening an emergency event, a supplied
        `well_id` must resolve to a wellbore on the supplied `storage_field_id`.
        Both scope failures answer `ERR_WELL_NOT_FOUND`."

        Design: Corner/entities/gas_movement_ticket_well_on_another_field_is_reported_as_not_found
        """
        world = build_mini_world(api)
        other_field = create_field(
            api, F.storage_field_payload(name="Cavern Mini B", field_code="F-MINI-B")
        )
        other_well = create_well(api, other_field["id"], well_name="B-1")

        nomination = confirm_nomination(
            api,
            file_and_submit_nomination(
                api,
                world.contract_id,
                world.shipper_id,
                gas_day="2026-08-20",
                nominated_volume_dth=80000,
            )["id"],
        )

        assert_error_envelope(
            api.create_ticket(
                F.ticket_payload(nomination["id"], other_well["id"], 76000), FIELD_OPERATOR
            ),
            ERR_WELL_NOT_FOUND,
        )
        assert_error_envelope(
            api.create_emergency_event(
                F.emergency_event_payload(world.field_id, well_id=other_well["id"]),
                FIELD_OPERATOR,
            ),
            ERR_WELL_NOT_FOUND,
        )
        assert_error_envelope(
            api.create_well(F.well_payload(ABSENT_ID, well_name="ORPHAN"), FIELD_OPERATOR),
            ERR_STORAGE_FIELD_NOT_FOUND,
        )

        ticket = assert_created(
            api.create_ticket(
                F.ticket_payload(nomination["id"], world.well_id, 76000), FIELD_OPERATOR
            )
        )
        assert ticket["well_id"] == world.well_id
        assert ticket["status"] == TICKET_PENDING

        _, ticket_meta = validate_paginated(api.list_tickets(FIELD_OPERATOR, {"limit": 100}))
        assert ticket_meta["total_count"] == 1
        _, event_meta = validate_paginated(
            api.list_emergency_events(FIELD_OPERATOR, {"limit": 100})
        )
        assert event_meta["total_count"] == 0


class TestLedgerImmutability:
    """The one record type that carries neither updated_at nor version."""

    def test_ledger_rows_are_immutable_and_carry_no_version(self, api, mini_world):
        """Reversing a movement that under-delivered 4,000 Dth leaves the original
        row untouched and appends an offsetting one, so the ledger holds two rows
        while the contract's imbalance nets back to zero.

        PRD §3.6: "A `DAILY_IMBALANCE` ledger entry carrying the negated
        `volume_dth` is appended rather than the original entry being edited, since
        the ledger is append-only."

        Design: Corner/entities/imbalance_ledger_entries_are_immutable_rows_with_no_version_field
        """
        nomination = confirm_nomination(
            api,
            file_and_submit_nomination(
                api,
                mini_world.contract_id,
                mini_world.shipper_id,
                gas_day="2026-08-20",
                nominated_volume_dth=80000,
            )["id"],
        )
        ticket = open_ticket(api, nomination["id"], mini_world.well_id, 76000)
        confirm_ticket(api, ticket["id"], mini_world.field_id)

        appended_by_confirm = ledger_entries(api, mini_world.contract_id)
        assert len(appended_by_confirm) == 1
        original_row = dict(appended_by_confirm[0])

        reversed_ticket = reverse_ticket(
            api, ticket["id"], "meter re-read after chart correction"
        )
        assert reversed_ticket["status"] == TICKET_REVERSED
        assert reversed_ticket["reversal_reason"] == "meter re-read after chart correction"

        response = api.list_ledger_entries(
            mini_world.contract_id, SCHEDULING_COORDINATOR, {"limit": 100}
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

        assert_ledger_entry(
            rows[0],
            entry_type=LEDGER_DAILY_IMBALANCE,
            volume_dth=-4000.000,
            amount_usd=0.00,
            gas_day="2026-08-20",
        )
        assert_ledger_entry(
            rows[1],
            entry_type=LEDGER_DAILY_IMBALANCE,
            volume_dth=4000.000,
            amount_usd=0.00,
            gas_day="2026-08-20",
        )
        assert rows[0] == original_row, "The reversal must not edit the original row"

        contract = read_contract(api, mini_world.contract_id)
        assert_volume(contract["imbalance_dth"], 0.000, "imbalance_dth")
        assert_volume(contract["inventory_balance_dth"], 0.000, "inventory_balance_dth")

        field = read_field(api, mini_world.field_id)
        assert_volume(field["working_gas_inventory_dth"], 250000, "working_gas_inventory_dth")
        assert_volume(field["retained_fuel_pool_dth"], 0.000, "retained_fuel_pool_dth")


class TestImmediateRecomputation:
    """The reservoir's denormalised block is correct on the very next read."""

    def test_service_change_publishes_the_recomputed_reservoir_immediately(self, api):
        """Two wellbores rated 60,000 each cap both rates below the curve, so
        shutting one in drops both rates to exactly 60,000 on the next read with no
        retry, and shutting the second in freezes the reservoir and makes that gate
        enforceable in the very next call.

        PRD §2.6: "The server recomputes it immediately after any mutation that
        touches the field's wellbores, its emergency events, its working gas
        inventory or its pressure, and it is recomputed immediately after the
        deliverability recomputation described in §2.7 so that both numbers are
        consistent within one request."

        Design: Corner/consistency_model/well_service_change_publishes_the_recomputed_field_in_the_same_request
        """
        world = build_mini_world(
            api, well_names=["MINI-1", "MINI-2"], well_rate_dth_per_day=60000
        )
        nomination = file_and_submit_nomination(
            api,
            world.contract_id,
            world.shipper_id,
            gas_day="2026-08-02",
            nominated_volume_dth=50000,
        )

        before = read_field(api, world.field_id)
        assert_field_derived_block(
            before, wells_in_service=2, withdrawal_rate=120000, injection_rate=120000
        )
        version_before = before["version"]

        first_change = assert_ok(
            api.change_well_service(
                world.wells[0]["id"],
                F.service_change_payload(WELL_SHUT_IN, "Tubing inspection"),
                FIELD_OPERATOR,
            )
        )
        assert first_change["operational_state"] == WELL_SHUT_IN
        assert first_change["shut_in_reason"] == SHUT_IN_REASON_OPERATOR_REQUEST

        after_first = read_field(api, world.field_id)
        assert_field_derived_block(
            after_first,
            wells_in_service=1,
            withdrawal_rate=60000,
            injection_rate=60000,
            posture=POSTURE_OPEN,
            inventory_pct=50.00,
            pressure=1500,
            tier=TIER_3,
        )
        assert after_first["version"] == version_before + 1

        assert_ok(
            api.change_well_service(
                world.wells[1]["id"],
                F.service_change_payload(WELL_SHUT_IN, "Tubing inspection"),
                FIELD_OPERATOR,
            )
        )
        after_second = read_field(api, world.field_id)
        assert_field_derived_block(
            after_second,
            wells_in_service=0,
            withdrawal_rate=0,
            injection_rate=0,
            posture=POSTURE_FROZEN,
        )
        assert after_second["version"] == version_before + 2

        assert_error_envelope(
            api.confirm_nomination(nomination["id"], SCHEDULING_COORDINATOR),
            ERR_FIELD_FROZEN,
        )
        assert read_field(api, world.field_id)["version"] == version_before + 2

        _, meta = validate_paginated(
            api.list_wells(
                SCHEDULING_COORDINATOR,
                {
                    "storage_field_id": world.field_id,
                    "operational_state": WELL_IN_SERVICE,
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 0

        still_submitted = read_nomination(api, nomination["id"])
        assert still_submitted["status"] == NOMINATION_SUBMITTED
        assert still_submitted["confirmed_volume_dth"] == 0
