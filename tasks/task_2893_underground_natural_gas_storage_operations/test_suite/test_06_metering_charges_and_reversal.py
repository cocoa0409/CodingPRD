"""Metering the physical movement: the six-step charge breakdown, the discount
tiers, the creation and confirmation gates on a ticket, the two priority pairs
that a ticket confirm can trigger, and the compensating reversal."""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_CONTRACT_INVENTORY_INSUFFICIENT,
    ERR_CUSHION_GAS_BREACH,
    ERR_FIELD_PRESSURE_LIMIT,
    ERR_INVALID_CONTRACT_STATE,
    ERR_INVALID_NOMINATION_STATE,
    ERR_INVALID_TICKET_STATE,
    ERR_TICKET_ALREADY_EXISTS,
    ERR_TICKET_OVERRUN_EXCEEDED,
    ERR_WELL_INTEGRITY_FAILED,
    ERR_WELL_NOT_IN_SERVICE,
    ERR_WORKING_GAS_CAPACITY_EXCEEDED,
)
from test_helpers.assertions import (
    assert_created,
    assert_error_envelope,
    assert_field_derived_block,
    assert_ledger_entry,
    assert_money,
    assert_ok,
    assert_ticket_charges,
    assert_ticket_charges_unpriced,
    assert_volume,
)
from test_helpers.constants import (
    DIRECTION_INJECTION,
    DIRECTION_WITHDRAWAL,
    INTEGRITY_MIT_FAILED,
    LEDGER_DAILY_IMBALANCE,
    NOMINATION_CONFIRMED,
    POSTURE_RESTRICTED,
    SEASON_WITHDRAWAL,
    TICKET_CONFIRMED,
    TICKET_PENDING,
    TICKET_REVERSED,
    TIER_2,
    TIER_3,
    TIER_4,
    WELL_SHUT_IN,
    WELL_TYPE_OBSERVATION,
)
from test_helpers.fixtures import (
    confirm_ticket,
    confirmed_nomination,
    create_active_contract,
    create_bound_field,
    create_field,
    create_shipper,
    create_std_field,
    create_well,
    fail_mit_on_well,
    field_version,
    file_nomination,
    ledger_entries,
    open_ticket,
    read_contract,
    read_field,
    read_nomination,
    read_ticket,
    read_well,
    reverse_ticket,
)
from test_helpers.test_users import (
    FIELD_OPERATOR,
    SCHEDULING_COORDINATOR,
    make_shipper_headers,
)


def _charge_world(api, **contract_overrides):
    """The standard reservoir, one wellbore and one active firm contract."""
    field = create_std_field(api)
    well = create_well(api, field["id"], well_name="AUR-1")
    shipper = create_shipper(api)
    contract = create_active_contract(
        api, shipper["id"], field["id"], contract_code="CT-CHARGE", **contract_overrides
    )
    return field, well, shipper, contract


class TestTicketChargeBreakdown:
    """One confirm composes five dependent figures in a pinned order."""

    def test_the_discount_tier_is_keyed_on_the_commodity_charge_alone(self, api):
        """A 92,000 Dth movement priced at 0.0450 earns no discount because its
        commodity charge of 4,140.00 is below the first threshold, even though adding
        the fuel charge would carry the ticket over it.

        PRD §3.6: "The volume discount tier is selected from `commodity_charge_usd`
        **alone** and from no other figure: no discount when that charge is below
        5,000 US dollars, 2 percent when it is at least 5,000 but below 20,000, and 5
        percent at 20,000 or above."

        Design: Difficulty/combinatorial_formula/ticket_charge_six_step_order_with_discount_tier_keyed_on_commodity_only
        """
        field, well, shipper, contract = _charge_world(api)
        nomination = confirmed_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-02", direction=DIRECTION_INJECTION,
            nominated_volume_dth=90000,
        )
        ticket = open_ticket(api, nomination["id"], well["id"], 92000)
        assert ticket["status"] == TICKET_PENDING
        assert_ticket_charges_unpriced(ticket)

        confirmed = confirm_ticket(api, ticket["id"], field["id"])
        assert confirmed["status"] == TICKET_CONFIRMED
        assert_ticket_charges(
            confirmed,
            fuel_retention=1104.000, net_volume=90896.000,
            commodity=4140.00, discount=0.00, fuel_charge=3808.80, total=7948.80,
        )
        assert confirmed["total_charge_usd"] != 7866.00, (
            "7866.00 is the total a tier keyed on commodity plus fuel would publish"
        )

    def test_the_same_confirm_moves_gas_fuel_and_the_contract_book_apart(self, api):
        """The single confirm moves the reservoir by the metered volume, the retained
        fuel pool by the retention and the contract's book by the net, and writes the
        overrun to the balancing ledger.

        PRD §3.6: "On the reservoir, `working_gas_inventory_dth` moves by the full
        `actual_volume_dth`, signed by the nomination's `direction` — upward for an
        injection, downward for a withdrawal — and `retained_fuel_pool_dth` increases
        by `fuel_retention_dth`, which is how the retention stays inside the field
        while leaving the shipper's book."

        Design: Difficulty/combinatorial_formula/ticket_charge_six_step_order_with_discount_tier_keyed_on_commodity_only
        """
        field, well, shipper, contract = _charge_world(api)
        nomination = confirmed_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-02", direction=DIRECTION_INJECTION,
            nominated_volume_dth=90000,
        )
        ticket = open_ticket(api, nomination["id"], well["id"], 92000)
        confirm_ticket(api, ticket["id"], field["id"])

        after_field = read_field(api, field["id"])
        assert_volume(
            after_field["working_gas_inventory_dth"], 3092000.000, "working_gas_inventory_dth"
        )
        assert_volume(after_field["retained_fuel_pool_dth"], 1104.000, "retained_fuel_pool_dth")

        after_contract = read_contract(api, contract["id"])
        assert_volume(after_contract["inventory_balance_dth"], 90896.000, "inventory_balance_dth")
        assert_volume(after_contract["imbalance_dth"], 2000.000, "imbalance_dth")

        rows = ledger_entries(api, contract["id"], limit=100)
        assert len(rows) == 1
        assert_ledger_entry(
            rows[0], entry_type=LEDGER_DAILY_IMBALANCE,
            volume_dth=2000.000, amount_usd=0.00, gas_day="2026-08-02",
        )


class TestDiscountTierBoundaries:
    """Both discount thresholds are inclusive at the bottom, which prices a
    marginally smaller haul above a marginally larger one."""

    def test_one_dekatherm_less_makes_two_hauls_more_expensive(self, api):
        """Four movements on one contract straddle both thresholds by a single
        dekatherm, and the two just below each threshold total more than the two at
        it.

        PRD §3.6: "`volume_discount_usd` is `commodity_charge_usd` multiplied by that
        percentage and divided by 100, rounded half up to 2 decimal places."

        Design: Corner/calculations/ticket_discount_tier_boundaries_make_a_bigger_haul_cheaper
        """
        field = create_std_field(api)
        well = create_well(api, field["id"], well_name="STD-1")
        shipper = create_shipper(api)
        contract = create_active_contract(
            api, shipper["id"], field["id"], contract_code="CS-1",
            commodity_rate_usd_per_dth=0.1000, max_daily_injection_dth=200000,
            max_storage_quantity_dth=10000000,
        )

        volumes = [200000, 199999, 50000, 49999]
        gas_days = ["2026-08-20", "2026-08-21", "2026-08-22", "2026-08-23"]
        nominations = [
            confirmed_nomination(
                api, contract["id"], shipper["id"],
                gas_day=gas_day, direction=DIRECTION_INJECTION, nominated_volume_dth=volume,
            )
            for volume, gas_day in zip(volumes, gas_days)
        ]
        for nomination, volume in zip(nominations, volumes):
            assert nomination["confirmed_volume_dth"] == volume

        tickets = []
        for nomination, volume in zip(nominations, volumes):
            opened = open_ticket(api, nomination["id"], well["id"], volume)
            tickets.append(confirm_ticket(api, opened["id"], field["id"]))

        assert_ticket_charges(
            tickets[0],
            fuel_retention=2400.000, net_volume=197600.000,
            commodity=20000.00, discount=1000.00, fuel_charge=8280.00, total=27280.00,
        )
        assert_ticket_charges(
            tickets[1],
            fuel_retention=2399.988, net_volume=197599.012,
            commodity=19999.90, discount=400.00, fuel_charge=8279.96, total=27879.86,
        )
        assert_ticket_charges(
            tickets[2],
            fuel_retention=600.000, net_volume=49400.000,
            commodity=5000.00, discount=100.00, fuel_charge=2070.00, total=6970.00,
        )
        assert_ticket_charges(
            tickets[3],
            fuel_retention=599.988, net_volume=49399.012,
            commodity=4999.90, discount=0.00, fuel_charge=2069.96, total=7069.86,
        )
        assert tickets[1]["total_charge_usd"] > tickets[0]["total_charge_usd"], (
            "199999 Dth costs more than 200000 Dth once the 5% tier is lost"
        )
        assert tickets[3]["total_charge_usd"] > tickets[2]["total_charge_usd"], (
            "49999 Dth costs more than 50000 Dth once the 2% tier is lost"
        )

        after_contract = read_contract(api, contract["id"])
        assert_volume(
            after_contract["inventory_balance_dth"], 493998.024, "inventory_balance_dth"
        )
        assert_volume(after_contract["imbalance_dth"], 0.000, "imbalance_dth")

        after_field = read_field(api, field["id"])
        assert_volume(after_field["retained_fuel_pool_dth"], 5999.976, "retained_fuel_pool_dth")
        assert_field_derived_block(
            after_field,
            working_gas=3499998.000, inventory_pct=43.75, pressure=1412, tier=TIER_2,
            withdrawal_rate=262500, injection_rate=275000,
        )


class TestActionReplay:
    """No action endpoint is idempotent, and a refused replay applies nothing."""

    def test_replaying_activate_submit_confirm_and_ticket_confirm_all_refuse(self, api):
        """Each of the four action endpoints answers its own entity's state code on a
        second call, and the duplicate ticket confirm — re-issued with a freshly read
        reservoir version so that the state gate rather than the concurrency gate is
        under test — leaves every quantity exactly where the first confirm left it.

        PRD §2.11 rung 7: "The target record is in a state from which the requested
        transition is declared. Per-entity codes, all HTTP 409: a nomination gives
        `ERR_INVALID_NOMINATION_STATE`, a ticket `ERR_INVALID_TICKET_STATE`, a contract
        `ERR_INVALID_CONTRACT_STATE`."

        Design: Corner/state_machines/repeated_action_calls_are_refused_rather_than_replayed
        """
        field = create_field(api)
        well = create_well(api, field["id"], well_name="MINI-1")
        shipper = create_shipper(api)
        contract = create_active_contract(api, shipper["id"], field["id"])
        nomination = confirmed_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-20", direction=DIRECTION_INJECTION,
            nominated_volume_dth=80000,
        )
        ticket = open_ticket(api, nomination["id"], well["id"], 76000)
        confirm_ticket(api, ticket["id"], field["id"])

        assert_error_envelope(
            api.activate_contract(contract["id"], SCHEDULING_COORDINATOR),
            ERR_INVALID_CONTRACT_STATE,
        )
        assert read_contract(api, contract["id"])["status"] == "ACTIVE"

        shipper_headers = make_shipper_headers(shipper["id"])
        assert_error_envelope(
            api.submit_nomination(nomination["id"], shipper_headers, {}),
            ERR_INVALID_NOMINATION_STATE,
        )
        assert_error_envelope(
            api.confirm_nomination(nomination["id"], SCHEDULING_COORDINATOR),
            ERR_INVALID_NOMINATION_STATE,
        )

        assert_error_envelope(
            api.confirm_ticket(
                ticket["id"],
                F.ticket_confirm_payload(field_version(api, field["id"])),
                FIELD_OPERATOR,
            ),
            ERR_INVALID_TICKET_STATE,
        )

        settled_ticket = read_ticket(api, ticket["id"])
        assert settled_ticket["status"] == TICKET_CONFIRMED
        assert_volume(settled_ticket["net_volume_dth"], 75088.000, "net_volume_dth")
        assert_volume(settled_ticket["fuel_retention_dth"], 912.000, "fuel_retention_dth")

        after_field = read_field(api, field["id"])
        assert_field_derived_block(
            after_field,
            working_gas=326000.000, inventory_pct=65.20, pressure=1713, tier=TIER_3,
            withdrawal_rate=195600, injection_rate=104400,
        )
        assert_volume(after_field["retained_fuel_pool_dth"], 912.000, "retained_fuel_pool_dth")

        after_contract = read_contract(api, contract["id"])
        assert_volume(after_contract["inventory_balance_dth"], 75088.000, "inventory_balance_dth")
        assert_volume(after_contract["imbalance_dth"], -4000.000, "imbalance_dth")
        assert len(ledger_entries(api, contract["id"], limit=100)) == 1, (
            "the refused replay appended no second DAILY_IMBALANCE row"
        )


class TestTicketCreationGates:
    """Opening a ticket is guarded by the overrun ceiling, the nomination's state
    and a uniqueness scope that ignores reversed rows."""

    def test_the_overrun_ceiling_the_draft_nomination_and_the_live_duplicate(self, api):
        """One dekatherm past the five-percent ceiling is refused, a draft nomination
        is not ticketable, a second live ticket on the same nomination is a duplicate —
        and once the first ticket is reversed the identical create succeeds.

        PRD §3.6: "Metering tolerance is five percent: `actual_volume_dth` may exceed
        the nomination's `confirmed_volume_dth` by at most five percent, that ceiling
        rounded half up to a whole dekatherm, and anything beyond it is refused with
        `ERR_TICKET_OVERRUN_EXCEEDED`."

        Design: Corner/validations/ticket_creation_gates_run_nomination_state_then_overrun_then_duplication
        """
        field = create_field(api)
        well = create_well(api, field["id"], well_name="MINI-1")
        shipper = create_shipper(api)
        contract = create_active_contract(api, shipper["id"], field["id"])
        live = confirmed_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-20", direction=DIRECTION_INJECTION,
            nominated_volume_dth=80000,
        )
        draft = file_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-21", direction=DIRECTION_INJECTION,
            nominated_volume_dth=80000,
        )

        assert_error_envelope(
            api.create_ticket(
                F.ticket_payload(live["id"], well["id"], 84001), FIELD_OPERATOR
            ),
            ERR_TICKET_OVERRUN_EXCEEDED,
        )
        assert_error_envelope(
            api.create_ticket(
                F.ticket_payload(draft["id"], well["id"], 1000), FIELD_OPERATOR
            ),
            ERR_INVALID_NOMINATION_STATE,
        )

        first = assert_created(
            api.create_ticket(
                F.ticket_payload(live["id"], well["id"], 84000), FIELD_OPERATOR
            )
        )
        assert first["actual_volume_dth"] == 84000, "the ceiling is exactly 84000"
        assert first["status"] == TICKET_PENDING

        assert_error_envelope(
            api.create_ticket(
                F.ticket_payload(live["id"], well["id"], 1000), FIELD_OPERATOR
            ),
            ERR_TICKET_ALREADY_EXISTS,
        )

        confirmed = confirm_ticket(api, first["id"], field["id"])
        assert_volume(confirmed["fuel_retention_dth"], 1008.000, "fuel_retention_dth")
        assert_volume(confirmed["net_volume_dth"], 82992.000, "net_volume_dth")

        reversed_ticket = reverse_ticket(api, first["id"])
        assert reversed_ticket["status"] == TICKET_REVERSED

        replacement = assert_created(
            api.create_ticket(
                F.ticket_payload(live["id"], well["id"], 84000), FIELD_OPERATOR
            )
        )
        assert replacement["status"] == TICKET_PENDING, (
            "the uniqueness scope counts only non-REVERSED tickets"
        )

        after_field = read_field(api, field["id"])
        assert_field_derived_block(
            after_field,
            working_gas=250000.000, inventory_pct=50.00, pressure=1500, tier=TIER_3,
            withdrawal_rate=150000, injection_rate=150000,
        )
        assert_volume(after_field["retained_fuel_pool_dth"], 0.000, "retained_fuel_pool_dth")

        _, meta = validate_paginated(
            api.list_tickets(FIELD_OPERATOR, {"nomination_id": live["id"], "limit": 100})
        )
        assert meta["total_count"] == 2, "one REVERSED row beside one PENDING row"

        after_contract = read_contract(api, contract["id"])
        assert_volume(after_contract["inventory_balance_dth"], 0.000, "inventory_balance_dth")
        assert_volume(after_contract["imbalance_dth"], 0.000, "imbalance_dth")

    def test_integrity_is_reported_ahead_of_availability(self, api):
        """A healthy observation wellbore fails only the availability rung, while a
        wellbore that is both shut in and integrity-failed reports the integrity rung
        even though both are breached.

        PRD §2.11 rung 11: "Integrity is deliberately checked *before* availability at
        rung 12, because a failed test always shuts its wellbore in as a side effect:
        the two conditions are co-violated on every failed wellbore, and only this
        order leaves both errors observable."

        Design: Corner/validations/ticket_creation_reports_well_integrity_ahead_of_well_availability
        """
        field = create_field(api)
        healthy = create_well(api, field["id"], well_name="MINI-1")
        observation = create_well(
            api, field["id"], well_name="MINI-OBS", well_type=WELL_TYPE_OBSERVATION
        )
        failing = create_well(api, field["id"], well_name="MINI-2")
        shipper = create_shipper(api)
        contract = create_active_contract(api, shipper["id"], field["id"])
        nominations = [
            confirmed_nomination(
                api, contract["id"], shipper["id"],
                gas_day=gas_day, direction=DIRECTION_INJECTION, nominated_volume_dth=10000,
            )
            for gas_day in ("2026-08-20", "2026-08-21", "2026-08-22")
        ]

        fail_mit_on_well(api, failing["id"], result_pressure_psig=2900)
        broken = read_well(api, failing["id"])
        assert broken["operational_state"] == WELL_SHUT_IN
        assert broken["integrity_state"] == INTEGRITY_MIT_FAILED

        assert_error_envelope(
            api.create_ticket(
                F.ticket_payload(nominations[0]["id"], observation["id"], 10000),
                FIELD_OPERATOR,
            ),
            ERR_WELL_NOT_IN_SERVICE,
        )
        assert_error_envelope(
            api.create_ticket(
                F.ticket_payload(nominations[1]["id"], failing["id"], 10000), FIELD_OPERATOR
            ),
            ERR_WELL_INTEGRITY_FAILED,
        )

        opened = assert_created(
            api.create_ticket(
                F.ticket_payload(nominations[2]["id"], healthy["id"], 10000), FIELD_OPERATOR
            )
        )
        confirmed = confirm_ticket(api, opened["id"], field["id"])
        assert_ticket_charges(
            confirmed,
            fuel_retention=120.000, net_volume=9880.000,
            commodity=450.00, discount=0.00, fuel_charge=414.00, total=864.00,
        )

        assert_field_derived_block(
            read_field(api, field["id"]),
            working_gas=260000.000, inventory_pct=52.00, pressure=1528, tier=TIER_3,
            withdrawal_rate=156000, injection_rate=144000,
            posture=POSTURE_RESTRICTED, wells_in_service=1,
        )
        for nomination in nominations[:2]:
            survivor = read_nomination(api, nomination["id"])
            assert survivor["status"] == NOMINATION_CONFIRMED, (
                "the firm schedule survived the RESTRICTED sweep"
            )
            assert survivor["confirmed_volume_dth"] == 10000

        after_contract = read_contract(api, contract["id"])
        assert_volume(after_contract["inventory_balance_dth"], 9880.000, "inventory_balance_dth")
        assert_volume(after_contract["imbalance_dth"], 0.000, "imbalance_dth")


class TestInjectionCeilingGates:
    """The two injection gates are prospective: both are evaluated on the position
    the confirm would produce, not on the one the reservoir reports."""

    def test_the_working_gas_ceiling_is_measured_against_the_net_volume(self, api):
        """On a nearly full reservoir a 10,500 Dth movement is refused because its net
        of 10,374.000 would breach the working gas ceiling, the refusal touches
        nothing, and a 5,000 Dth movement then lands.

        PRD §2.11 rung 14: "On confirming an injection ticket, the field's
        `working_gas_inventory_dth` plus the ticket's `net_volume_dth` is no greater
        than `max_working_gas_dth` — otherwise `ERR_WORKING_GAS_CAPACITY_EXCEEDED`
        (422)."

        Design: Corner/validations/injection_capacity_gate_measures_the_net_volume_against_the_working_gas_ceiling
        """
        field = create_field(
            api,
            name="Tight Sands",
            field_code="F-TGHT",
            total_capacity_dth=300000,
            cushion_gas_dth=100000,
            opening_working_gas_dth=190000,
        )
        well = create_well(api, field["id"], well_name="TIGHT-1")
        shipper = create_shipper(api)
        contract = create_active_contract(
            api, shipper["id"], field["id"], contract_code="CT-1",
            max_daily_injection_dth=20000,
        )
        first = confirmed_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=10500,
        )
        second = confirmed_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-21", direction=DIRECTION_INJECTION, nominated_volume_dth=5000,
        )
        oversized = open_ticket(api, first["id"], well["id"], 10500)
        admitted = open_ticket(api, second["id"], well["id"], 5000)
        version_before = field_version(api, field["id"])

        assert_error_envelope(
            api.confirm_ticket(
                oversized["id"], F.ticket_confirm_payload(version_before), FIELD_OPERATOR
            ),
            ERR_WORKING_GAS_CAPACITY_EXCEEDED,
        )
        refused = read_ticket(api, oversized["id"])
        assert refused["status"] == TICKET_PENDING
        assert_ticket_charges_unpriced(refused)
        assert field_version(api, field["id"]) == version_before, (
            "the refused confirm did not touch the reservoir"
        )

        confirmed = confirm_ticket(api, admitted["id"], field["id"])
        assert_volume(confirmed["fuel_retention_dth"], 60.000, "fuel_retention_dth")
        assert_volume(confirmed["net_volume_dth"], 4940.000, "net_volume_dth")
        assert_money(confirmed["total_charge_usd"], 432.00, "total_charge_usd")

        after_field = read_field(api, field["id"])
        assert_volume(after_field["max_working_gas_dth"], 200000.000, "max_working_gas_dth")
        assert_volume(after_field["retained_fuel_pool_dth"], 60.000, "retained_fuel_pool_dth")
        assert_field_derived_block(
            after_field,
            working_gas=195000.000, inventory_pct=97.50, pressure=2165, tier=TIER_4,
            withdrawal_rate=292500, injection_rate=7500,
        )
        after_contract = read_contract(api, contract["id"])
        assert_volume(after_contract["inventory_balance_dth"], 4940.000, "inventory_balance_dth")
        assert_volume(after_contract["imbalance_dth"], 0.000, "imbalance_dth")

    def test_the_pressure_limit_admits_the_confirm_that_lands_two_psi_under_it(self, api):
        """A 45,000 Dth movement is refused because it would drive the wellhead to
        3,001 psig, one psi over the reservoir's 3,000 psig limit, while a 5,000 Dth
        movement landing on 2,889 psig is admitted — and the reservoir is
        `RESTRICTED` throughout, which never blocks firm service.

        The geometry is pinned by PRD §3.1, which requires that
        "`max_pressure_psig` is the regulatory maximum operating pressure and must
        be at least the base pressure plus the span". With `max_pressure_psig`
        exactly equal to `base_pressure_psig` plus `pressure_span_psig`, the
        pressure ceiling can only be crossed above a full working-gas book — which
        rung 14 still admits, because it measures `net_volume_dth` (the metered
        volume less the 1.20 percent fuel retention) while the pressure of rung 15
        is derived from the full `actual_volume_dth` that moves the inventory. The
        45,000 Dth ticket lands 499,960 of net volume under the 500,000 ceiling and
        yet books 500,500 of working gas, so rung 15 is the first rung it violates.

        PRD §2.11 rung 15: "The `current_pressure_psig` that would result from
        confirming an injection ticket is no greater than the field's
        `max_pressure_psig`, and a recorded test's `result_pressure_psig` is likewise
        no greater than that limit — otherwise `ERR_FIELD_PRESSURE_LIMIT` (422)."

        Design: Corner/validations/pressure_ceiling_admits_the_confirm_that_lands_just_under_the_limit
        """
        field = create_field(
            api,
            name="Pressure Limit Dome",
            field_code="F-PLIM",
            base_pressure_psig=1600,
            pressure_span_psig=1400,
            max_pressure_psig=3000,
            opening_working_gas_dth=455500,
            # Injection capability held flat across the curve so that a reservoir
            # sitting at 91.10 percent still carries the day's nomination; the
            # rung under test is the pressure ceiling, not the deliverability one.
            deliverability_curve=[
                F.curve_point(0, 0, 300000),
                F.curve_point(100, 300000, 300000),
            ],
        )
        well = create_well(api, field["id"], well_name="PLIM-1")
        shipper = create_shipper(api)
        contract = create_active_contract(
            api, shipper["id"], field["id"], contract_code="CP-1",
            max_daily_injection_dth=50000,
        )
        assert_field_derived_block(
            read_field(api, field["id"]),
            working_gas=455500.000, inventory_pct=91.10, pressure=2875,
            posture=POSTURE_RESTRICTED,
        )

        first = confirmed_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=45000,
        )
        second = confirmed_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-21", direction=DIRECTION_INJECTION, nominated_volume_dth=5000,
        )
        oversized = open_ticket(api, first["id"], well["id"], 45000)
        admitted = open_ticket(api, second["id"], well["id"], 5000)
        version_before = field_version(api, field["id"])

        assert_error_envelope(
            api.confirm_ticket(
                oversized["id"], F.ticket_confirm_payload(version_before), FIELD_OPERATOR
            ),
            ERR_FIELD_PRESSURE_LIMIT,
        )
        assert read_ticket(api, oversized["id"])["status"] == TICKET_PENDING

        confirmed = assert_ok(
            api.confirm_ticket(
                admitted["id"], F.ticket_confirm_payload(version_before), FIELD_OPERATOR
            )
        )
        assert_volume(confirmed["fuel_retention_dth"], 60.000, "fuel_retention_dth")
        assert_volume(confirmed["net_volume_dth"], 4940.000, "net_volume_dth")

        after_field = read_field(api, field["id"])
        assert after_field["max_pressure_psig"] == 3000
        assert_field_derived_block(
            after_field,
            working_gas=460500.000, inventory_pct=92.10, pressure=2889, tier=TIER_4,
            withdrawal_rate=276300, injection_rate=300000, posture=POSTURE_RESTRICTED,
        )


def _state_versus_safety_world(api):
    """One confirmed ticket and one pending ticket on the wellbore that a failed
    integrity test has just shut in."""
    field = create_std_field(api)
    strong = create_well(api, field["id"], well_name="AUR-1")
    create_well(api, field["id"], well_name="AUR-2", rated_rate_dth_per_day=60000)
    shipper = create_shipper(api)
    contract = create_active_contract(
        api, shipper["id"], field["id"], contract_code="CT-STATE"
    )
    settled_nomination = confirmed_nomination(
        api, contract["id"], shipper["id"],
        gas_day="2026-08-02", direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
    )
    settled = open_ticket(api, settled_nomination["id"], strong["id"], 80000)
    confirm_ticket(api, settled["id"], field["id"])

    pending_nomination = confirmed_nomination(
        api, contract["id"], shipper["id"],
        gas_day="2026-08-11", direction=DIRECTION_INJECTION, nominated_volume_dth=50000,
    )
    pending = open_ticket(api, pending_nomination["id"], strong["id"], 50000)

    fail_mit_on_well(
        api, strong["id"],
        scheduled_start_at="2026-08-10T00:00:00Z",
        scheduled_end_at="2026-08-10T06:00:00Z",
        record_at="2026-08-10T12:00:00Z",
        result_pressure_psig=1200,
    )
    return SimpleNamespace(
        field=field, well=strong, contract=contract,
        settled_ticket=settled, pending_ticket=pending,
    )


class TestTicketStateBeatsWellSafety:
    """A ticket that is already confirmed reports its own state, not the safety
    failures its wellbore has since acquired."""

    def test_the_state_gate_answers_first_and_the_integrity_gate_answers_next(self, api):
        """Re-confirming the settled ticket on a shut-in, integrity-failed wellbore
        answers the ticket state, while confirming the still-pending ticket on that
        very same wellbore answers the integrity failure.

        PRD §2.11 rung 7: "The target record is in a state from which the requested
        transition is declared. Per-entity codes, all HTTP 409: ... a ticket
        `ERR_INVALID_TICKET_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/ticket_state_priority_7_wins_over_well_safety_priority_11_and_12
        """
        world = _state_versus_safety_world(api)
        token = F.ticket_confirm_payload(field_version(api, world.field["id"]))

        assert_error_envelope(
            api.confirm_ticket(world.settled_ticket["id"], token, FIELD_OPERATOR),
            ERR_INVALID_TICKET_STATE,
        )
        assert_error_envelope(
            api.confirm_ticket(world.pending_ticket["id"], token, FIELD_OPERATOR),
            ERR_WELL_INTEGRITY_FAILED,
        )

        broken = read_well(api, world.well["id"])
        assert broken["operational_state"] == WELL_SHUT_IN
        assert broken["integrity_state"] == INTEGRITY_MIT_FAILED

    def test_neither_refusal_moves_the_reservoir_or_the_tickets(self, api):
        """Both refused confirms are pure no-ops: the reservoir keeps the position the
        first confirm left, its version does not move, and the two tickets keep their
        statuses on a reservoir that is `RESTRICTED` rather than `FROZEN`.

        PRD §2.11 rung 9: "The field's posture is not `FROZEN` for any operation that
        schedules or moves gas on it — otherwise `ERR_FIELD_FROZEN` (422)."

        Design: Difficulty/priority_pair_validation_conflict/ticket_state_priority_7_wins_over_well_safety_priority_11_and_12
        """
        world = _state_versus_safety_world(api)
        version_before = field_version(api, world.field["id"])
        token = F.ticket_confirm_payload(version_before)

        api.confirm_ticket(world.settled_ticket["id"], token, FIELD_OPERATOR)
        api.confirm_ticket(world.pending_ticket["id"], token, FIELD_OPERATOR)

        assert read_ticket(api, world.settled_ticket["id"])["status"] == TICKET_CONFIRMED
        assert read_ticket(api, world.pending_ticket["id"])["status"] == TICKET_PENDING

        after_field = read_field(api, world.field["id"])
        assert after_field["version"] == version_before
        assert_field_derived_block(
            after_field,
            working_gas=3080000.000, posture=POSTURE_RESTRICTED, wells_in_service=1,
        )


def _bound_world_at_the_two_floors(api):
    """The tight reservoir loaded to 92,500 Dth of working gas against a contract
    book of 91,390.000, with two withdrawal tickets waiting between the physical
    cushion floor and the contractual inventory floor."""
    field = create_bound_field(api)
    well = create_well(api, field["id"], well_name="BND-1", rated_rate_dth_per_day=120000)
    shipper = create_shipper(api)
    contract = create_active_contract(
        api, shipper["id"], field["id"], contract_code="CT-BOUND",
        max_storage_quantity_dth=200000,
    )
    loading = confirmed_nomination(
        api, contract["id"], shipper["id"],
        gas_day="2026-08-02", direction=DIRECTION_INJECTION, nominated_volume_dth=92500,
    )
    loaded = open_ticket(api, loading["id"], well["id"], 92500)
    confirm_ticket(api, loaded["id"], field["id"])

    assert_ok(api.set_season(field["id"], F.season_payload(SEASON_WITHDRAWAL), FIELD_OPERATOR))

    first = confirmed_nomination(
        api, contract["id"], shipper["id"],
        gas_day="2026-08-03", direction=DIRECTION_WITHDRAWAL, nominated_volume_dth=91390,
    )
    second = confirmed_nomination(
        api, contract["id"], shipper["id"],
        gas_day="2026-08-04", direction=DIRECTION_WITHDRAWAL, nominated_volume_dth=91390,
    )
    return SimpleNamespace(
        field=field, contract=contract,
        breaches_cushion=open_ticket(api, first["id"], well["id"], 92600),
        breaches_book=open_ticket(api, second["id"], well["id"], 92000),
        nominations=[first, second],
    )


class TestCushionFloorBeatsContractFloor:
    """The physical floor and the fiscal floor sit 1,110 Dth apart because only the
    fiscal one adds the fuel retention."""

    def test_the_cushion_breach_is_reported_before_the_contract_shortfall(self, api):
        """A 92,600 Dth withdrawal breaks the reservoir's cushion floor and the
        contract's book at once and reports the cushion, while a 92,000 Dth withdrawal
        clears the cushion yet still overdraws the book once its retention is added.

        PRD §2.11 rung 13: "On confirming a withdrawal ticket, `actual_volume_dth` is
        no greater than the field's `working_gas_inventory_dth` — otherwise
        `ERR_CUSHION_GAS_BREACH` (422)."

        Design: Difficulty/priority_pair_validation_conflict/cushion_gas_safety_priority_13_wins_over_contract_inventory_fiscal_priority_34
        """
        world = _bound_world_at_the_two_floors(api)
        token = F.ticket_confirm_payload(field_version(api, world.field["id"]))

        assert_error_envelope(
            api.confirm_ticket(world.breaches_cushion["id"], token, FIELD_OPERATOR),
            ERR_CUSHION_GAS_BREACH,
        )
        assert_error_envelope(
            api.confirm_ticket(world.breaches_book["id"], token, FIELD_OPERATOR),
            ERR_CONTRACT_INVENTORY_INSUFFICIENT,
        )

    def test_the_fiscal_floor_adds_the_retention_the_safety_floor_ignores(self, api):
        """The 92,000 Dth withdrawal sits below the 92,500 Dth of working gas yet its
        92,000 plus 1,104.000 of retention exceeds the 91,390.000 the contract holds,
        and neither refusal moves the reservoir or the two schedules.

        PRD §2.11 rung 34: "On confirming a withdrawal ticket, `actual_volume_dth` plus
        `fuel_retention_dth` is no greater than the contract's `inventory_balance_dth`
        — otherwise `ERR_CONTRACT_INVENTORY_INSUFFICIENT` (422)."

        Design: Difficulty/priority_pair_validation_conflict/cushion_gas_safety_priority_13_wins_over_contract_inventory_fiscal_priority_34
        """
        world = _bound_world_at_the_two_floors(api)
        token = F.ticket_confirm_payload(field_version(api, world.field["id"]))

        api.confirm_ticket(world.breaches_cushion["id"], token, FIELD_OPERATOR)
        api.confirm_ticket(world.breaches_book["id"], token, FIELD_OPERATOR)

        after_field = read_field(api, world.field["id"])
        assert_volume(after_field["retained_fuel_pool_dth"], 1110.000, "retained_fuel_pool_dth")
        assert_field_derived_block(
            after_field,
            working_gas=92500.000, inventory_pct=92.50, pressure=2095, tier=TIER_4,
            withdrawal_rate=111000,
        )
        assert_volume(
            read_contract(api, world.contract["id"])["inventory_balance_dth"],
            91390.000, "inventory_balance_dth",
        )
        assert read_ticket(api, world.breaches_cushion["id"])["status"] == TICKET_PENDING
        assert read_ticket(api, world.breaches_book["id"])["status"] == TICKET_PENDING
        for nomination in world.nominations:
            still_scheduled = read_nomination(api, nomination["id"])
            assert still_scheduled["status"] == NOMINATION_CONFIRMED
            assert still_scheduled["confirmed_volume_dth"] == 91390


def _reversible_world(api):
    """One 82,000 Dth movement confirmed against an 80,000 Dth schedule."""
    field = create_std_field(api)
    well = create_well(api, field["id"], well_name="AUR-1")
    shipper = create_shipper(api)
    contract = create_active_contract(
        api, shipper["id"], field["id"], contract_code="CT-REV"
    )
    nomination = confirmed_nomination(
        api, contract["id"], shipper["id"],
        gas_day="2026-08-02", direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
    )
    ticket = open_ticket(api, nomination["id"], well["id"], 82000)
    confirm_ticket(api, ticket["id"], field["id"])
    return SimpleNamespace(
        field=field, contract=contract, nomination=nomination, ticket=ticket
    )


class TestReversalRestoresTheOpeningPosition:
    """The reversal unwinds four quantities that moved by four different amounts."""

    def test_every_quantity_returns_to_the_position_before_the_ticket_existed(self, api):
        """The confirm moved working gas by 82,000, the fuel pool by 984.000, the
        contract's book by 81,016.000 and its imbalance by 2,000.000, and the reversal
        puts all four back exactly.

        PRD §3.6: "A permitted reversal moves every reservoir and contract quantity the
        confirmation moved back by the identical magnitude — inventory, retained fuel,
        contract balance and contract imbalance alike — so that the conservation
        identity of §2.9 holds exactly as it did before the ticket existed."

        Design: Difficulty/compensating_invariant/ticket_reversal_restores_field_and_contract_quantities_to_the_exact_opening_position
        """
        world = _reversible_world(api)
        loaded_field = read_field(api, world.field["id"])
        assert_volume(
            loaded_field["working_gas_inventory_dth"], 3082000.000, "working_gas_inventory_dth"
        )
        assert_volume(loaded_field["retained_fuel_pool_dth"], 984.000, "retained_fuel_pool_dth")
        loaded_contract = read_contract(api, world.contract["id"])
        assert_volume(
            loaded_contract["inventory_balance_dth"], 81016.000, "inventory_balance_dth"
        )
        assert_volume(loaded_contract["imbalance_dth"], 2000.000, "imbalance_dth")

        reversed_ticket = reverse_ticket(
            api, world.ticket["id"], "Chart integration error at the meter run."
        )
        assert reversed_ticket["status"] == TICKET_REVERSED
        assert reversed_ticket["reversal_reason"] == "Chart integration error at the meter run."

        restored_field = read_field(api, world.field["id"])
        assert_volume(restored_field["retained_fuel_pool_dth"], 0.000, "retained_fuel_pool_dth")
        assert_field_derived_block(
            restored_field,
            working_gas=3000000.000, inventory_pct=37.50, pressure=1325, tier=TIER_2,
            withdrawal_rate=225000, injection_rate=300000,
        )
        restored_contract = read_contract(api, world.contract["id"])
        assert_volume(
            restored_contract["inventory_balance_dth"], 0.000, "inventory_balance_dth"
        )
        assert_volume(restored_contract["imbalance_dth"], 0.000, "imbalance_dth")

    def test_the_compensation_is_additive_rather_than_a_deletion(self, api):
        """A second ledger row carrying the negated volume is appended beside the
        original, the ticket keeps the money it was stamped with, the reservoir's
        version climbs by one more and the schedule that authorised the movement is
        untouched.

        PRD §3.6: "A `DAILY_IMBALANCE` ledger entry carrying the negated `volume_dth`
        is appended rather than the original entry being edited, since the ledger is
        append-only."

        Design: Difficulty/compensating_invariant/ticket_reversal_restores_field_and_contract_quantities_to_the_exact_opening_position
        """
        world = _reversible_world(api)
        version_before = field_version(api, world.field["id"])

        reverse_ticket(api, world.ticket["id"], "Chart integration error at the meter run.")

        rows = ledger_entries(
            api, world.contract["id"], entry_type=LEDGER_DAILY_IMBALANCE, limit=100
        )
        assert len(rows) == 2
        assert_ledger_entry(
            rows[0], entry_type=LEDGER_DAILY_IMBALANCE,
            volume_dth=2000.000, amount_usd=0.00, gas_day="2026-08-02",
        )
        assert_ledger_entry(
            rows[1], entry_type=LEDGER_DAILY_IMBALANCE,
            volume_dth=-2000.000, amount_usd=0.00, gas_day="2026-08-02",
        )

        settled = read_ticket(api, world.ticket["id"])
        assert_money(settled["total_charge_usd"], 7084.80, "total_charge_usd")
        assert_money(settled["commodity_charge_usd"], 3690.00, "commodity_charge_usd")
        assert_money(settled["fuel_charge_usd"], 3394.80, "fuel_charge_usd")

        assert field_version(api, world.field["id"]) == version_before + 1

        untouched = read_nomination(api, world.nomination["id"])
        assert untouched["status"] == NOMINATION_CONFIRMED
        assert untouched["confirmed_volume_dth"] == 80000
