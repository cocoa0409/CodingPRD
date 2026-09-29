"""Filing, superseding, the five-step allocation waterfall, the bounded revision
cycle and the season sweep over counterflow interruptible schedules."""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_CONTRACT_NOT_FOUND,
    ERR_CONTRACT_NOT_OWNED,
    ERR_CONTRACT_RIGHTS_EXCEEDED,
    ERR_GAS_DAY_OUTSIDE_TERM,
    ERR_INVALID_NOMINATION_STATE,
    ERR_INVALID_REQUEST,
    ERR_NOMINATION_REVISION_LIMIT,
    ERR_NOMINATION_WINDOW_CLOSED,
    ERR_SEASON_DIRECTION_MISMATCH,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_created,
    assert_error_envelope,
    assert_field_derived_block,
    assert_ledger_entry,
    assert_ok,
    assert_volume,
)
from test_helpers.constants import (
    DIRECTION_INJECTION,
    DIRECTION_WITHDRAWAL,
    LEDGER_CURTAILMENT_CREDIT,
    NOMINATION_CONFIRMED,
    NOMINATION_CURTAILED,
    NOMINATION_DRAFT,
    NOMINATION_SUBMITTED,
    NOMINATION_SUPERSEDED,
    POSTURE_OPEN,
    SEASON_WITHDRAWAL,
    SERVICE_CLASS_FIRM,
    SERVICE_CLASS_INTERRUPTIBLE,
    TIER_3,
)
from test_helpers.fixtures import (
    confirm_nomination,
    confirmed_nomination,
    contract_version,
    create_active_contract,
    create_field,
    create_second_shipper,
    create_shipper,
    create_std_field,
    create_well,
    file_nomination,
    ledger_entries,
    moved_gas,
    read_contract,
    read_field,
    read_nomination,
    set_clock,
    submit_nomination,
)
from test_helpers.test_users import (
    FIELD_OPERATOR,
    SCHEDULING_COORDINATOR,
    make_shipper_headers,
)

ABSENT_ID = "00000000-0000-4000-8000-000000000000"


def _mini_field_with_shipper(api, **contract_overrides):
    """One F-MINI reservoir, one wellbore and one active contract for one shipper."""
    field = create_field(api)
    create_well(api, field["id"], well_name="MINI-1")
    shipper = create_shipper(api)
    contract = create_active_contract(
        api, shipper["id"], field["id"], **contract_overrides
    )
    return field, shipper, contract


class TestNominationFiling:
    """A filing is inert until it is submitted, it displaces the slot it lands on,
    and its input rules are peeled off in priority order."""

    def test_a_filed_nomination_is_inert_but_still_bumps_the_contract(self, api):
        """A brand-new nomination holds no volume and reserves no reservoir or
        contract capacity, yet the filing itself moves the contract's concurrency
        token forward by one.

        PRD §3.5: "A filed nomination begins at `status` `DRAFT`, with
        `confirmed_volume_dth` 0, `curtailed_volume_dth` 0, `revision_round` 0, and
        both `submitted_at` and `confirmed_at` null."

        Design: Corner/state_machines/nomination_create_starts_in_draft_and_reserves_no_capacity
        """
        field, shipper, contract = _mini_field_with_shipper(api)
        opening_version = contract["version"]

        nomination = assert_created(
            api.create_nomination(
                F.nomination_payload(
                    contract["id"], opening_version,
                    gas_day="2026-08-20", direction=DIRECTION_INJECTION,
                    nominated_volume_dth=80000,
                ),
                make_shipper_headers(shipper["id"]),
            )
        )
        assert nomination["status"] == NOMINATION_DRAFT
        assert nomination["confirmed_volume_dth"] == 0
        assert nomination["curtailed_volume_dth"] == 0
        assert nomination["revision_round"] == 0
        assert nomination["submitted_at"] is None
        assert nomination["confirmed_at"] is None
        assert nomination["superseded_by_nomination_id"] is None
        assert nomination["gas_day"] == "2026-08-20"
        assert nomination["direction"] == DIRECTION_INJECTION
        assert nomination["nominated_volume_dth"] == 80000

        after = read_contract(api, contract["id"])
        assert after["scheduled_injection_dth"] == 0
        assert after["scheduled_withdrawal_dth"] == 0
        assert_volume(after["inventory_balance_dth"], 0.000, "inventory_balance_dth")
        assert after["version"] == opening_version + 1

        assert_field_derived_block(read_field(api, field["id"]), injection_rate=150000)
        assert ledger_entries(api, contract["id"], limit=100) == []

    def test_refiling_the_same_slot_supersedes_it_and_earns_no_credit(self, api):
        """A second filing for the same contract, gas day and direction terminates the
        confirmed row, releases its volume from the contract's schedule and appends no
        curtailment credit, because the shipper gave the capacity back voluntarily.

        PRD §3.5: "if a non-terminal nomination already exists on the same
        `contract_id`, `gas_day` and `direction`, it moves to the terminal
        `SUPERSEDED` status with its `superseded_by_nomination_id` set to the new
        nomination's `id`, and whatever confirmed volume it was holding is removed
        from the contract's scheduled totals."

        Design: Corner/state_machines/superseding_nomination_releases_the_prior_schedule_without_a_credit_row
        """
        _, shipper, contract = _mini_field_with_shipper(api)
        shipper_headers = make_shipper_headers(shipper["id"])
        first = confirmed_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-20", direction=DIRECTION_INJECTION,
            nominated_volume_dth=80000,
        )
        assert first["confirmed_volume_dth"] == 80000
        assert read_contract(api, contract["id"])["scheduled_injection_dth"] == 80000
        version_before = contract_version(api, contract["id"])

        second = file_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-20", direction=DIRECTION_INJECTION,
            nominated_volume_dth=60000,
        )
        assert second["status"] == NOMINATION_DRAFT
        assert second["nominated_volume_dth"] == 60000

        displaced = read_nomination(api, first["id"], SCHEDULING_COORDINATOR)
        assert displaced["status"] == NOMINATION_SUPERSEDED
        assert displaced["superseded_by_nomination_id"] == second["id"]
        assert displaced["confirmed_volume_dth"] == 80000, (
            "the historical row keeps the volume it held; the contract gives it back"
        )

        after = read_contract(api, contract["id"])
        assert after["scheduled_injection_dth"] == 0
        assert after["version"] == version_before + 1
        assert ledger_entries(api, contract["id"], limit=100) == [], (
            "a voluntary supersede earns no CURTAILMENT_CREDIT"
        )

        _, meta = validate_paginated(
            api.list_nominations(
                SCHEDULING_COORDINATOR,
                {
                    "contract_id": contract["id"],
                    "superseded_by_nomination_id": second["id"],
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 1

        assert_error_envelope(
            api.submit_nomination(first["id"], shipper_headers, {}),
            ERR_INVALID_NOMINATION_STATE,
        )

    def test_the_contract_term_is_inclusive_at_both_ends(self, api):
        """A gas day one day past the term end is refused, a gas day before the term
        start reports the term rather than the cutoff it also violates, and the last
        day of the term is admitted.

        PRD §2.11 rung 17: "A nomination's `gas_day` falls within the contract's
        `term_start_date` and `term_end_date`, both boundaries inclusive — otherwise
        `ERR_GAS_DAY_OUTSIDE_TERM` (422)."

        Design: Corner/validations/nomination_gas_day_must_fall_inside_the_contract_term_inclusively
        """
        _, shipper, contract = _mini_field_with_shipper(api)
        shipper_headers = make_shipper_headers(shipper["id"])
        token = contract["version"]

        for gas_day in ("2027-01-01", "2026-07-31"):
            assert_error_envelope(
                api.create_nomination(
                    F.nomination_payload(
                        contract["id"], token,
                        gas_day=gas_day, nominated_volume_dth=80000,
                    ),
                    shipper_headers,
                ),
                ERR_GAS_DAY_OUTSIDE_TERM,
            )

        accepted = assert_created(
            api.create_nomination(
                F.nomination_payload(
                    contract["id"], token,
                    gas_day="2026-12-31", nominated_volume_dth=80000,
                ),
                shipper_headers,
            )
        )
        assert accepted["gas_day"] == "2026-12-31"
        assert accepted["status"] == NOMINATION_DRAFT
        assert read_contract(api, contract["id"])["version"] == token + 1

        _, meta = validate_paginated(
            api.list_nominations(
                SCHEDULING_COORDINATOR, {"contract_id": contract["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1

    def test_only_interruptible_service_must_nominate_with_the_season(self, api):
        """On an injection-season reservoir the interruptible counterflow filing is
        refused while the firm counterflow filing and the interruptible with-season
        filing both land.

        PRD §3.5: "Interruptible service must nominate with the reservoir's `season`:
        an interruptible nomination whose `direction` contradicts the season is
        refused with `ERR_SEASON_DIRECTION_MISMATCH`, while firm service may nominate
        against the season freely."

        Design: Corner/validations/firm_may_nominate_counterflow_while_interruptible_may_not
        """
        field = create_field(api)
        create_well(api, field["id"], well_name="MINI-1")
        shipper = create_shipper(api)
        shipper_headers = make_shipper_headers(shipper["id"])
        firm = create_active_contract(api, shipper["id"], field["id"], contract_code="CN-1")
        interruptible = create_active_contract(
            api, shipper["id"], field["id"], contract_code="CN-2",
            service_class=SERVICE_CLASS_INTERRUPTIBLE,
        )
        interruptible_token = interruptible["version"]

        assert_error_envelope(
            api.create_nomination(
                F.nomination_payload(
                    interruptible["id"], interruptible_token,
                    gas_day="2026-08-20", direction=DIRECTION_WITHDRAWAL,
                    nominated_volume_dth=40000,
                ),
                shipper_headers,
            ),
            ERR_SEASON_DIRECTION_MISMATCH,
        )

        firm_counterflow = assert_created(
            api.create_nomination(
                F.nomination_payload(
                    firm["id"], firm["version"],
                    gas_day="2026-08-20", direction=DIRECTION_WITHDRAWAL,
                    nominated_volume_dth=40000,
                ),
                shipper_headers,
            )
        )
        assert firm_counterflow["direction"] == DIRECTION_WITHDRAWAL
        assert firm_counterflow["status"] == NOMINATION_DRAFT
        assert firm_counterflow["gas_day"] == "2026-08-20"

        with_season = assert_created(
            api.create_nomination(
                F.nomination_payload(
                    interruptible["id"], interruptible_token,
                    gas_day="2026-08-20", direction=DIRECTION_INJECTION,
                    nominated_volume_dth=40000,
                ),
                shipper_headers,
            )
        )
        assert with_season["direction"] == DIRECTION_INJECTION
        assert with_season["status"] == NOMINATION_DRAFT

        assert read_contract(api, interruptible["id"])["version"] == interruptible_token + 1
        for row in (firm_counterflow, with_season):
            assert row["confirmed_volume_dth"] == 0
            assert row["curtailed_volume_dth"] == 0
            assert row["revision_round"] == 0

    def test_filing_rules_are_peeled_off_term_then_season_then_rights(self, api):
        """One payload violating the term, the season and the daily right reports the
        term first, then the season once the gas day moves inside it, then the right
        once the direction is corrected, and finally lands at exactly the right.

        PRD §2.11 rung 19: "A nomination on an `INTERRUPTIBLE` contract must have a
        `direction` equal to the field's current `season`; firm contracts may nominate
        against the season — otherwise `ERR_SEASON_DIRECTION_MISMATCH` (422)."

        Design: Corner/validations/nomination_create_peels_off_term_then_season_then_rights_in_priority_order
        """
        field = create_field(api)
        create_well(api, field["id"], well_name="MINI-1")
        shipper = create_shipper(api)
        shipper_headers = make_shipper_headers(shipper["id"])
        contract = create_active_contract(
            api, shipper["id"], field["id"], contract_code="CN-2",
            service_class=SERVICE_CLASS_INTERRUPTIBLE,
            term_start_date="2026-08-01", term_end_date="2026-08-31",
        )
        token = contract["version"]

        def _file(gas_day, direction, volume):
            return api.create_nomination(
                F.nomination_payload(
                    contract["id"], token,
                    gas_day=gas_day, direction=direction, nominated_volume_dth=volume,
                ),
                shipper_headers,
            )

        assert_error_envelope(
            _file("2026-09-15", DIRECTION_WITHDRAWAL, 200000), ERR_GAS_DAY_OUTSIDE_TERM
        )
        assert_error_envelope(
            _file("2026-08-20", DIRECTION_WITHDRAWAL, 200000), ERR_SEASON_DIRECTION_MISMATCH
        )
        assert_error_envelope(
            _file("2026-08-20", DIRECTION_INJECTION, 200000), ERR_CONTRACT_RIGHTS_EXCEEDED
        )

        accepted = assert_created(_file("2026-08-20", DIRECTION_INJECTION, 100000))
        assert accepted["nominated_volume_dth"] == 100000, "the daily right is inclusive"
        assert accepted["status"] == NOMINATION_DRAFT
        assert accepted["revision_round"] == 0
        assert read_contract(api, contract["id"])["version"] == token + 1

        _, meta = validate_paginated(
            api.list_nominations(
                SCHEDULING_COORDINATOR, {"contract_id": contract["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1

    def test_role_then_shape_then_lookup_then_ownership_are_reported_in_turn(self, api):
        """A request carrying four defects at once answers the role first, then the
        unparseable direction, then the unresolvable contract, then the foreign
        contract — and the owner's identical request lands.

        PRD §2.11 rung 5: "The acting user is entitled to the resource: a `Shipper`
        acts only on its own contracts, nominations and tickets — otherwise
        `ERR_CONTRACT_NOT_OWNED`, `ERR_NOMINATION_NOT_OWNED` or
        `ERR_TICKET_NOT_OWNED`, all HTTP 403."

        Design: Corner/validations/nomination_create_rejects_role_then_shape_then_lookup_then_ownership_in_turn
        """
        field = create_field(api)
        create_well(api, field["id"], well_name="MINI-1")
        northline = create_shipper(api)
        southline = create_second_shipper(api)
        create_active_contract(api, northline["id"], field["id"], contract_code="CN-1")
        foreign = create_active_contract(
            api, southline["id"], field["id"], contract_code="CS-2"
        )
        token = foreign["version"]
        northline_headers = make_shipper_headers(northline["id"])
        southline_headers = make_shipper_headers(southline["id"])

        malformed = F.nomination_payload(
            ABSENT_ID, token,
            gas_day="2026-08-20", direction="SIDEWAYS", nominated_volume_dth=80000,
        )
        assert_error_envelope(
            api.create_nomination(malformed, FIELD_OPERATOR), ERR_UNAUTHORIZED
        )
        assert_error_envelope(
            api.create_nomination(malformed, northline_headers), ERR_INVALID_REQUEST
        )
        assert_error_envelope(
            api.create_nomination(
                F.nomination_payload(
                    ABSENT_ID, token,
                    gas_day="2026-08-20", direction=DIRECTION_INJECTION,
                    nominated_volume_dth=80000,
                ),
                northline_headers,
            ),
            ERR_CONTRACT_NOT_FOUND,
        )

        owner_payload = F.nomination_payload(
            foreign["id"], token,
            gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
        )
        assert_error_envelope(
            api.create_nomination(owner_payload, northline_headers), ERR_CONTRACT_NOT_OWNED
        )

        accepted = assert_created(api.create_nomination(owner_payload, southline_headers))
        assert accepted["contract_id"] == foreign["id"]
        assert accepted["status"] == NOMINATION_DRAFT

        _, meta = validate_paginated(
            api.list_nominations(southline_headers, {"limit": 100})
        )
        assert meta["total_count"] == 1, "none of the four refusals left a row behind"


class TestAllocationWaterfall:
    """Both buckets are read live, so the same world binds on the reservoir on one
    gas day and on the contract's own balance on the next."""

    def test_the_field_bucket_then_the_contract_bucket_bind_on_live_figures(self, api):
        """After one metered injection the reservoir's injection ceiling has fallen, so
        the second filing for the next gas day is cut to the remaining headroom, and a
        withdrawal two days later is cut to the contract's post-retention balance
        rather than to the volume it metered.

        PRD §3.5: "`confirmed_volume_dth` is the smaller of the contract bucket and
        the headroom, floored at zero so that a negative headroom yields zero rather
        than a negative volume."

        Design: Corner/calculations/nomination_waterfall_binds_on_the_field_bucket_then_the_inventory_bucket
        """
        field = create_field(api)
        well = create_well(api, field["id"], well_name="MINI-1")
        shipper = create_shipper(api)
        first = create_active_contract(
            api, shipper["id"], field["id"], contract_code="CN-1"
        )
        second = create_active_contract(
            api, shipper["id"], field["id"], contract_code="CN-2"
        )
        moved_gas(
            api, first["id"], shipper["id"], field["id"], well["id"], 60000,
            gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=60000,
        )
        assert_volume(
            read_contract(api, first["id"])["inventory_balance_dth"],
            59280.000, "inventory_balance_dth",
        )

        full = confirmed_nomination(
            api, first["id"], shipper["id"],
            gas_day="2026-08-21", direction=DIRECTION_INJECTION,
            nominated_volume_dth=100000,
        )
        assert full["status"] == NOMINATION_CONFIRMED
        assert full["confirmed_volume_dth"] == 100000
        assert full["curtailed_volume_dth"] == 0

        squeezed = confirmed_nomination(
            api, second["id"], shipper["id"],
            gas_day="2026-08-21", direction=DIRECTION_INJECTION,
            nominated_volume_dth=100000,
        )
        assert squeezed["status"] == NOMINATION_CURTAILED
        assert squeezed["confirmed_volume_dth"] == 14000, (
            "the headroom is the live 114000 ceiling less the 100000 already confirmed"
        )
        assert squeezed["curtailed_volume_dth"] == 86000
        credits = ledger_entries(api, second["id"], limit=100)
        assert len(credits) == 1
        assert_ledger_entry(
            credits[0], entry_type=LEDGER_CURTAILMENT_CREDIT,
            volume_dth=-86000.000, amount_usd=0.00, gas_day="2026-08-21",
        )

        withdrawal = confirmed_nomination(
            api, first["id"], shipper["id"],
            gas_day="2026-08-22", direction=DIRECTION_WITHDRAWAL,
            nominated_volume_dth=100000,
        )
        assert withdrawal["status"] == NOMINATION_CURTAILED
        assert withdrawal["confirmed_volume_dth"] == 59280
        assert withdrawal["curtailed_volume_dth"] == 40720

        first_after = read_contract(api, first["id"])
        assert_volume(
            first_after["inventory_balance_dth"], 59280.000, "inventory_balance_dth"
        )
        assert first_after["scheduled_withdrawal_dth"] == 59280
        assert read_contract(api, second["id"])["scheduled_injection_dth"] == 14000

        field_after = read_field(api, field["id"])
        assert_volume(
            field_after["working_gas_inventory_dth"], 310000.000, "working_gas_inventory_dth"
        )
        assert_field_derived_block(
            field_after, inventory_pct=62.00, pressure=1668, tier=TIER_3,
            withdrawal_rate=186000, injection_rate=114000,
        )


class TestSeasonTurnSweep:
    """Turning the reservoir sweeps interruptible counterflow only."""

    def test_a_season_turn_curtails_interruptible_counterflow_and_spares_firm(self, api):
        """With a firm and an interruptible injection nomination confirmed on the same
        gas day, flipping the reservoir to withdrawal service strips the interruptible
        volume and issues its credit while the firm schedule stands, and the reservoir
        itself moves no gas.

        PRD §2.8: "every `CONFIRMED` nomination on an `INTERRUPTIBLE` contract of that
        field whose `direction` no longer matches the new `season`, whose `gas_day` is
        today or later, and which has no confirmed movement ticket, is curtailed in
        full with the same `CURTAILMENT_CREDIT` entry and the same contract
        reconciliation. Firm nominations are never touched by a season turn."

        Design: Corner/state_machines/season_flip_curtails_interruptible_counterflow_and_spares_firm
        """
        field = create_field(api)
        create_well(api, field["id"], well_name="MINI-1")
        shipper = create_shipper(api)
        firm = create_active_contract(
            api, shipper["id"], field["id"],
            contract_code="CN-F", service_class=SERVICE_CLASS_FIRM,
        )
        interruptible = create_active_contract(
            api, shipper["id"], field["id"],
            contract_code="CN-I", service_class=SERVICE_CLASS_INTERRUPTIBLE,
        )
        firm_nomination = confirmed_nomination(
            api, firm["id"], shipper["id"],
            gas_day="2026-08-20", direction=DIRECTION_INJECTION,
            nominated_volume_dth=80000,
        )
        interruptible_nomination = confirmed_nomination(
            api, interruptible["id"], shipper["id"],
            gas_day="2026-08-20", direction=DIRECTION_INJECTION,
            nominated_volume_dth=40000,
        )
        assert firm_nomination["status"] == NOMINATION_CONFIRMED
        assert interruptible_nomination["status"] == NOMINATION_CONFIRMED, (
            "the interruptible share of 45000 leaves room for 40000"
        )

        flipped = assert_ok(
            api.set_season(field["id"], F.season_payload(SEASON_WITHDRAWAL), FIELD_OPERATOR)
        )
        assert flipped["season"] == SEASON_WITHDRAWAL

        swept = read_nomination(api, interruptible_nomination["id"])
        assert swept["status"] == NOMINATION_CURTAILED
        assert swept["confirmed_volume_dth"] == 0
        assert swept["curtailed_volume_dth"] == 40000

        spared = read_nomination(api, firm_nomination["id"])
        assert spared["status"] == NOMINATION_CONFIRMED
        assert spared["confirmed_volume_dth"] == 80000
        assert spared["curtailed_volume_dth"] == 0

        assert read_contract(api, interruptible["id"])["scheduled_injection_dth"] == 0
        assert read_contract(api, firm["id"])["scheduled_injection_dth"] == 80000

        credits = ledger_entries(api, interruptible["id"], limit=100)
        assert len(credits) == 1
        assert_ledger_entry(
            credits[0], entry_type=LEDGER_CURTAILMENT_CREDIT,
            volume_dth=-40000.000, amount_usd=0.00, gas_day="2026-08-20",
        )
        assert ledger_entries(api, firm["id"], limit=100) == []

        assert_field_derived_block(
            read_field(api, field["id"]),
            working_gas=250000.000, inventory_pct=50.00, posture=POSTURE_OPEN,
            injection_rate=150000, withdrawal_rate=150000,
        )


def _interruptible_at_the_revision_limit(api):
    """One interruptible nomination driven around the CURTAILED back edge twice, so
    it rests at `CURTAILED` with `revision_round` already at the permitted two."""
    field = create_std_field(api)
    create_well(api, field["id"], well_name="AUR-1", rated_rate_dth_per_day=300000)
    shipper = create_shipper(api)
    contract = create_active_contract(
        api, shipper["id"], field["id"],
        contract_code="CT-INTR", service_class=SERVICE_CLASS_INTERRUPTIBLE,
        max_daily_injection_dth=120000, max_daily_withdrawal_dth=120000,
    )
    nomination = file_nomination(
        api, contract["id"], shipper["id"],
        gas_day="2026-08-20", direction=DIRECTION_INJECTION,
        nominated_volume_dth=100000,
    )
    for _ in range(3):
        submit_nomination(api, nomination["id"], shipper["id"])
        confirm_nomination(api, nomination["id"])
    return SimpleNamespace(
        field=field, shipper=shipper, contract=contract, nomination=nomination,
        shipper_headers=make_shipper_headers(shipper["id"]),
    )


class TestBoundedRevisionCycle:
    """The curtailed-to-submitted back edge is walked twice and then closed."""

    def test_the_third_resubmission_is_refused_and_leaves_the_nomination_curtailed(self, api):
        """Two revision rounds are honoured, each returning the nomination to
        `SUBMITTED` with both allocated volumes cleared, and the third re-submission
        is refused without making the nomination terminal.

        PRD §3.5: "Two rounds of revision are permitted; a third attempt — that is, a
        re-submission when `revision_round` has already reached 2 — is refused with
        `ERR_NOMINATION_REVISION_LIMIT`."

        Design: Difficulty/non_linear_state_machine/nomination_curtailed_resubmit_cycle_bounded_by_revision_rounds
        """
        field = create_std_field(api)
        create_well(api, field["id"], well_name="AUR-1", rated_rate_dth_per_day=300000)
        shipper = create_shipper(api)
        contract = create_active_contract(
            api, shipper["id"], field["id"],
            contract_code="CT-INTR", service_class=SERVICE_CLASS_INTERRUPTIBLE,
            max_daily_injection_dth=120000, max_daily_withdrawal_dth=120000,
        )
        nomination = file_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-20", direction=DIRECTION_INJECTION,
            nominated_volume_dth=100000,
        )

        submit_nomination(api, nomination["id"], shipper["id"])
        first = confirm_nomination(api, nomination["id"])
        assert first["status"] == NOMINATION_CURTAILED
        assert first["confirmed_volume_dth"] == 90000, (
            "the interruptible share is floor(300000 x 30%) = 90000"
        )
        assert first["curtailed_volume_dth"] == 10000
        assert first["revision_round"] == 0

        second = submit_nomination(api, nomination["id"], shipper["id"])
        assert second["status"] == NOMINATION_SUBMITTED
        assert second["revision_round"] == 1
        assert second["confirmed_volume_dth"] == 0
        assert second["curtailed_volume_dth"] == 0
        confirm_nomination(api, nomination["id"])

        submit_nomination(api, nomination["id"], shipper["id"])
        third = confirm_nomination(api, nomination["id"])
        assert third["revision_round"] == 2
        assert third["status"] == NOMINATION_CURTAILED

        assert_error_envelope(
            api.submit_nomination(nomination["id"], make_shipper_headers(shipper["id"]), {}),
            ERR_NOMINATION_REVISION_LIMIT,
        )

        final = read_nomination(api, nomination["id"])
        assert final["status"] == NOMINATION_CURTAILED, (
            "the refusal does not push the nomination into a terminal state"
        )
        assert final["revision_round"] == 2
        assert final["confirmed_volume_dth"] == 90000
        assert final["curtailed_volume_dth"] == 10000

    def test_each_back_edge_unwinds_the_schedule_before_the_next_allocation(self, api):
        """The contract's scheduled injection returns to zero on every re-submission
        and is recomputed — not accumulated — on every confirmation, so after three
        rounds it stands at one round's worth of volume beside three credit rows.

        PRD §3.5: "`revision_round` increments by one, `submitted_at` is refreshed,
        `confirmed_volume_dth` and `curtailed_volume_dth` are reset to 0, and the
        contract's scheduled total is reduced by the volume the nomination had
        previously been holding."

        Design: Difficulty/non_linear_state_machine/nomination_curtailed_resubmit_cycle_bounded_by_revision_rounds
        """
        field = create_std_field(api)
        create_well(api, field["id"], well_name="AUR-1", rated_rate_dth_per_day=300000)
        shipper = create_shipper(api)
        contract = create_active_contract(
            api, shipper["id"], field["id"],
            contract_code="CT-INTR", service_class=SERVICE_CLASS_INTERRUPTIBLE,
            max_daily_injection_dth=120000, max_daily_withdrawal_dth=120000,
        )
        nomination = file_nomination(
            api, contract["id"], shipper["id"],
            gas_day="2026-08-20", direction=DIRECTION_INJECTION,
            nominated_volume_dth=100000,
        )

        for round_index in range(3):
            submit_nomination(api, nomination["id"], shipper["id"])
            assert read_contract(api, contract["id"])["scheduled_injection_dth"] == 0, (
                f"round {round_index} released the volume it had been holding"
            )
            confirm_nomination(api, nomination["id"])
            assert read_contract(api, contract["id"])["scheduled_injection_dth"] == 90000

        assert read_contract(api, contract["id"])["scheduled_injection_dth"] == 90000, (
            "three rounds of the same 90000 Dth never accumulate to 270000"
        )

        credits = ledger_entries(api, contract["id"], limit=100)
        assert len(credits) == 3
        for credit in credits:
            assert_ledger_entry(
                credit, entry_type=LEDGER_CURTAILMENT_CREDIT,
                volume_dth=-10000.000, amount_usd=0.00, gas_day="2026-08-20",
            )


class TestWindowBeatsRevisionLimit:
    """When the cutoff and the revision limit are breached at once, the clock wins."""

    def test_the_same_submission_reports_the_limit_then_the_closed_window(self, api):
        """A nomination resting at the revision limit answers
        `ERR_NOMINATION_REVISION_LIMIT` while its cutoff is still ahead, and answers
        `ERR_NOMINATION_WINDOW_CLOSED` once the clock has passed the cutoff, with both
        rules still breached.

        PRD §2.11 rung 18: "The logical clock is strictly before the cutoff for the
        nomination's `gas_day`, which is 13:00:00 UTC on the day immediately before
        that gas day — otherwise `ERR_NOMINATION_WINDOW_CLOSED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/nomination_window_temporal_priority_18_wins_over_revision_limit_priority_30
        """
        world = _interruptible_at_the_revision_limit(api)
        resting = read_nomination(api, world.nomination["id"])
        assert resting["status"] == NOMINATION_CURTAILED
        assert resting["revision_round"] == 2

        assert_error_envelope(
            api.submit_nomination(world.nomination["id"], world.shipper_headers, {}),
            ERR_NOMINATION_REVISION_LIMIT,
        )

        set_clock(api, "2026-08-19T14:00:00Z")
        assert_error_envelope(
            api.submit_nomination(world.nomination["id"], world.shipper_headers, {}),
            ERR_NOMINATION_WINDOW_CLOSED,
        )

        after = read_nomination(api, world.nomination["id"])
        assert after["status"] == NOMINATION_CURTAILED
        assert after["revision_round"] == 2
        assert after["confirmed_volume_dth"] == 90000
        assert after["curtailed_volume_dth"] == 10000
        assert read_contract(api, world.contract["id"])["scheduled_injection_dth"] == 90000

    def test_the_cutoff_instant_itself_already_closes_the_window(self, api):
        """At exactly 13:00:00Z on the day before the gas day the window is already
        shut, so the temporal rule displaces the revision limit on the boundary
        instant rather than one hour after it.

        PRD §3.5: "The cutoff applies here too: a submission at or after 13:00Z on the
        day before the gas day is refused with `ERR_NOMINATION_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/nomination_window_temporal_priority_18_wins_over_revision_limit_priority_30
        """
        world = _interruptible_at_the_revision_limit(api)

        set_clock(api, "2026-08-19T12:59:59Z")
        assert_error_envelope(
            api.submit_nomination(world.nomination["id"], world.shipper_headers, {}),
            ERR_NOMINATION_REVISION_LIMIT,
        )

        set_clock(api, "2026-08-19T13:00:00Z")
        assert_error_envelope(
            api.submit_nomination(world.nomination["id"], world.shipper_headers, {}),
            ERR_NOMINATION_WINDOW_CLOSED,
        )

        after = read_nomination(api, world.nomination["id"])
        assert after["status"] == NOMINATION_CURTAILED
        assert after["revision_round"] == 2
        assert after["confirmed_volume_dth"] == 90000
