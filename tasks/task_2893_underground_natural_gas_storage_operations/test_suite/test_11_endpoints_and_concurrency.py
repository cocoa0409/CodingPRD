"""The HTTP surface itself: the contract list channel with its four filters and
its paging window, the season action that answers with the whole repriced
reservoir row, the two sub-resource listings that must scope on the path parent,
the field read that projects a derived block without mutating anything, the five
uniqueness scopes, and the two optimistic-concurrency tokens of §2.10."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_DUPLICATE_CONTRACT_CODE,
    ERR_DUPLICATE_DUNS,
    ERR_DUPLICATE_FIELD_CODE,
    ERR_DUPLICATE_REPORT_PERIOD,
    ERR_DUPLICATE_UNIT_CODE,
    ERR_STALE_CONTRACT_VERSION,
    ERR_STALE_FIELD_VERSION,
)
from test_helpers.assertions import (
    assert_created,
    assert_created_at_ascending,
    assert_error_envelope,
    assert_field_derived_block,
    assert_money,
    assert_ok,
    assert_ticket_charges,
    assert_ticket_charges_unpriced,
    assert_variance_pct,
    assert_version_bumped_by,
    assert_volume,
)
from test_helpers.constants import (
    AGENCY_REJECTED,
    CONTRACT_ACTIVE,
    CONTRACT_DRAFT,
    DEFAULT_LIMIT,
    DIRECTION_INJECTION,
    F_MINI_MAX_WORKING_GAS_DTH,
    F_MINI_OPENING_WORKING_GAS_DTH,
    NOMINATION_DRAFT,
    NOMINATION_SUBMITTED,
    NOMINATION_SUPERSEDED,
    POSTURE_OPEN,
    REPORT_DRAFT,
    REPORT_REJECTED,
    REPORT_SUBMITTED,
    REPORT_TYPE_INVENTORY,
    RUN_COMPLETED,
    RUN_MODE_INJECTION,
    RUN_SCHEDULED,
    SEASON_WITHDRAWAL,
    SERVICE_CLASS_FIRM,
    SERVICE_CLASS_INTERRUPTIBLE,
    TICKET_CONFIRMED,
    TICKET_PENDING,
    TIER_3,
    UNIT_COMMITTED,
    WELL_TYPE_OBSERVATION,
)
from test_helpers.fixtures import (
    activate_contract,
    book_run,
    complete_run,
    confirmed_nomination,
    contract_version,
    create_contract,
    create_field,
    create_report,
    create_second_shipper,
    create_shipper,
    create_unit,
    create_well,
    field_version,
    file_nomination,
    open_ticket,
    read_contract,
    read_field,
    read_nomination,
    read_ticket,
    read_unit,
    set_clock,
    submit_nomination,
    submit_report,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_B,
    FIELD_OPERATOR,
    INTEGRITY_ENGINEER,
    OFFICER_A_ID,
    SCHEDULING_COORDINATOR,
    make_shipper_headers,
)


def _contracts(api, headers=None, **params):
    """The contract list channel; a bare call deliberately sends no parameters so
    the declared defaults are exercised."""
    return validate_paginated(
        api.list_contracts(headers or SCHEDULING_COORDINATOR, params or None)
    )


def _unit_runs(api, unit_id, headers=None, **params):
    query = {"limit": 100}
    query.update(params)
    return validate_paginated(api.list_unit_runs(unit_id, headers or FIELD_OPERATOR, query))


def _field_reports(api, field_id, headers=None, **params):
    query = {"limit": 100}
    query.update(params)
    return validate_paginated(
        api.list_field_regulatory_reports(field_id, headers or COMPLIANCE_OFFICER, query)
    )


class TestTheContractListChannel:
    """Four independent filters, one ordering and one paging window."""

    def test_the_filters_and_the_paging_window_agree_on_one_created_at_ordering(self, api):
        """Five contracts across two customers on one reservoir: an unparameterised list
        returns all five because five is under the default limit of 10, limit 2 / offset 2
        lands on the third and fourth rows while total_count still reports five, combining
        shipper_id with service_class narrows to a single row, and a status filter of ACTIVE
        drops the two DRAFT rows that match every other filter.

        PRD §3.4: "The coordinator can list contracts filtered by `shipper_id`,
        `storage_field_id`, `status` and `service_class`; a `Shipper` sees only its own rows
        on the same channel, as described in §2.1."

        PRD §2.4: "All list responses are ordered by `created_at` ascending, and `limit` and
        `offset` are applied only after that ordering has been established. The `id` value is
        never used as a sort key. The `total_count` reported in `meta` counts every row
        matching the endpoint's filters — including the ownership narrowing applied to a
        `Shipper` — as measured *before* `limit` and `offset` are applied, so a client can
        page to the end of a filtered set."

        PRD §3.4: "A newly written contract is not yet nominatable. It starts at `status`
        `DRAFT` with `activated_at` null, `inventory_balance_dth` 0.000, `imbalance_dth`
        0.000, `cash_out_amount_usd` 0.00, `cash_out_through_date` null, and both
        `scheduled_injection_dth` and `scheduled_withdrawal_dth` at 0."

        Design: Corner/endpoints/contract_create_read_and_filtered_listing_paginate_by_created_at
        """
        field = create_field(api)
        create_well(api, field["id"], well_name="MINI-1")
        northline = create_shipper(api)
        southgate = create_second_shipper(api)

        # The logical clock is advanced between the five creates so that the
        # created_at ordering the list channel promises is strict rather than a tie.
        c1 = activate_contract(
            api,
            create_contract(
                api, northline["id"], field["id"],
                contract_code="CN-1", service_class=SERVICE_CLASS_FIRM,
            )["id"],
        )
        set_clock(api, "2026-08-01T01:00:00Z")
        c2 = activate_contract(
            api,
            create_contract(
                api, northline["id"], field["id"],
                contract_code="CN-2", service_class=SERVICE_CLASS_INTERRUPTIBLE,
            )["id"],
        )
        set_clock(api, "2026-08-01T02:00:00Z")
        c3 = create_contract(
            api, northline["id"], field["id"],
            contract_code="CN-3", service_class=SERVICE_CLASS_FIRM,
        )
        set_clock(api, "2026-08-01T03:00:00Z")
        c4 = activate_contract(
            api,
            create_contract(
                api, southgate["id"], field["id"],
                contract_code="CS-1", service_class=SERVICE_CLASS_FIRM,
            )["id"],
        )
        set_clock(api, "2026-08-01T04:00:00Z")
        c5 = create_contract(
            api, southgate["id"], field["id"],
            contract_code="CS-2", service_class=SERVICE_CLASS_INTERRUPTIBLE,
        )

        drafted = read_contract(api, c3["id"])
        assert drafted["status"] == CONTRACT_DRAFT, (
            f"An un-activated contract stays DRAFT, got {drafted['status']}"
        )
        assert drafted["activated_at"] is None
        assert_volume(drafted["inventory_balance_dth"], 0.000, "inventory_balance_dth")
        assert_volume(drafted["imbalance_dth"], 0.000, "imbalance_dth")
        assert drafted["scheduled_injection_dth"] == 0, (
            f"scheduled_injection_dth: expected 0, got {drafted['scheduled_injection_dth']}"
        )
        assert drafted["cash_out_through_date"] is None
        assert drafted["version"] == 1, (
            f"An untouched create sits at version 1, got {drafted['version']}"
        )

        every_row, meta = _contracts(api)
        assert meta["total_count"] == 5, f"Expected five contracts, got {meta['total_count']}"
        assert meta["has_more"] is False, (
            f"Five rows fit under the default limit of {DEFAULT_LIMIT}, got has_more "
            f"{meta['has_more']}"
        )
        assert meta["limit"] == DEFAULT_LIMIT, (
            f"limit defaults to {DEFAULT_LIMIT}, got {meta['limit']}"
        )
        assert meta["offset"] == 0
        assert [row["id"] for row in every_row] == [
            c1["id"], c2["id"], c3["id"], c4["id"], c5["id"]
        ], "The unparameterised list must arrive in created_at ascending order"
        assert_created_at_ascending(every_row)

        window, window_meta = _contracts(api, limit=2, offset=2)
        assert [row["id"] for row in window] == [c3["id"], c4["id"]], (
            "limit 2 / offset 2 lands on the third and fourth rows of the same ordering"
        )
        assert window_meta["total_count"] == 5, (
            f"total_count is measured before limit/offset, got {window_meta['total_count']}"
        )
        assert window_meta["has_more"] is True, (
            f"Rows remain beyond the window, got has_more {window_meta['has_more']}"
        )

        interruptible, interruptible_meta = _contracts(
            api, shipper_id=northline["id"], service_class=SERVICE_CLASS_INTERRUPTIBLE,
            limit=100,
        )
        assert interruptible_meta["total_count"] == 1, (
            "shipper_id + service_class leaves one row, got "
            f"{interruptible_meta['total_count']}"
        )
        assert [row["id"] for row in interruptible] == [c2["id"]]

        active, active_meta = _contracts(
            api, COMPLIANCE_OFFICER, storage_field_id=field["id"],
            status=CONTRACT_ACTIVE, limit=100,
        )
        assert active_meta["total_count"] == 3, (
            "The status filter excludes the two DRAFT rows that match the field, got "
            f"{active_meta['total_count']}"
        )
        assert [row["id"] for row in active] == [c1["id"], c2["id"], c4["id"]]
        assert {row["status"] for row in active} == {CONTRACT_ACTIVE}


class TestTheSeasonAction:
    """The action answers with the whole reservoir row, not an acknowledgement."""

    def test_the_flip_returns_the_repriced_field_row_and_persists_it(self, api):
        """On an empty book the turn changes `season` and `version` and nothing else: the
        inventory, the pressure, the tier and both deliverability rates come back identical
        because the curve is indexed on inventory rather than on direction, and the follow-up
        read proves the action persisted the row instead of merely projecting it.

        PRD §3.1: "Turning the reservoir between injection and withdrawal service is a
        distinct operator act that carries a new `season` value. Beyond storing it, the turn
        runs the seasonal curtailment described in §2.8: interruptible nominations whose
        `direction` no longer matches the season lose their confirmed volume for every gas
        day from today forward, each producing a `CURTAILMENT_CREDIT` ledger entry and a
        recomputation of the affected contract's scheduled volumes and `version`."

        PRD §2.7 clause 6: "The curve is evaluated at the current `inventory_pct` under the
        field's `deliverability_method`, producing one withdrawal rate and one injection
        rate."

        Design: Corner/endpoints/season_flip_action_returns_the_repriced_field_row
        """
        field = create_field(api)
        create_well(api, field["id"], well_name="MINI-1")
        before = read_field(api, field["id"])

        flipped = assert_ok(
            api.set_season(field["id"], F.season_payload(SEASON_WITHDRAWAL), FIELD_OPERATOR)
        )
        assert flipped["season"] == SEASON_WITHDRAWAL, (
            f"season: expected {SEASON_WITHDRAWAL}, got {flipped['season']}"
        )
        assert_version_bumped_by(flipped["version"], before["version"], 1)
        assert_field_derived_block(
            flipped,
            working_gas=250000.000, inventory_pct=50.00, pressure=1500, tier=TIER_3,
            injection_rate=150000, withdrawal_rate=150000,
            wells_in_service=1, posture=POSTURE_OPEN,
        )
        assert flipped["max_working_gas_dth"] == F_MINI_MAX_WORKING_GAS_DTH, (
            f"max_working_gas_dth: expected {F_MINI_MAX_WORKING_GAS_DTH}, got "
            f"{flipped['max_working_gas_dth']}"
        )

        persisted = read_field(api, field["id"], SCHEDULING_COORDINATOR)
        assert persisted == flipped, (
            "The follow-up read must return the identical row the action published"
        )


class TestTheSubResourceListings:
    """Both nested channels must scope on the path parent, not on a query field."""

    def test_the_runs_and_the_reports_are_scoped_to_the_parent_in_the_path(self, api):
        """Two units on one reservoir hold two runs and one run respectively, and a third
        unit on a sibling reservoir holds none: each unit's run channel answers only for the
        unit named in the path, a status filter narrows the busy one to the row still
        scheduled, and the report channel is scoped the same way so a filing on the sibling
        reservoir never surfaces under the first.

        PRD §2.12: "Three read channels are the exception — the reports filed for a field,
        the runs booked on a unit, and the balancing ledger of a contract are reached through
        the owning record's path. For these, the owning identifier is resolved first and a
        failure to resolve it is answered with that record's own not-found code before any
        filter is considered, exactly as rung 4 of §2.11 requires."

        PRD §3.3: "Runs booked on a unit can be read through that unit's own run channel,
        filtered by `status`."

        PRD §3.9: "Reports filed for a reservoir are read through that reservoir's own report
        channel, which accepts filters on `report_type` and `status`."

        Design: Corner/endpoints/nested_listings_are_scoped_to_the_parent_in_the_path
        """
        first_field = create_field(api)
        create_well(api, first_field["id"], well_name="MINI-1")
        second_field = create_field(api, name="Cavern Two", field_code="F-TWO")
        create_well(api, second_field["id"], well_name="TWO-1")

        busy_unit = create_unit(api, first_field["id"], unit_code="U-1")
        quiet_unit = create_unit(api, first_field["id"], unit_code="U-2")
        sibling_unit = create_unit(api, second_field["id"], unit_code="U-3")

        elapsed_run = book_run(api, busy_unit["id"])
        set_clock(api, "2026-08-01T01:00:00Z")
        neighbour_run = book_run(
            api, quiet_unit["id"],
            window_start_at="2026-08-05T00:00:00Z", window_end_at="2026-08-05T08:00:00Z",
        )
        set_clock(api, "2026-08-02T08:00:00Z")
        completed = complete_run(api, elapsed_run["id"])
        assert completed["status"] == RUN_COMPLETED
        assert_money(completed["fuel_consumed_dth"], 220.80, "fuel_consumed_dth")
        future_run = book_run(
            api, busy_unit["id"],
            window_start_at="2026-08-10T00:00:00Z", window_end_at="2026-08-10T08:00:00Z",
        )

        own_filing = create_report(api, first_field["id"], 249779.200)
        sibling_filing = create_report(api, second_field["id"], 250000.000)

        busy_rows, busy_meta = _unit_runs(api, busy_unit["id"])
        assert busy_meta["total_count"] == 2, (
            "The busy unit's channel carries exactly its own two runs, got "
            f"{busy_meta['total_count']}"
        )
        assert [row["id"] for row in busy_rows] == [elapsed_run["id"], future_run["id"]], (
            "A run on a sibling unit of the same field must never appear here"
        )
        assert_created_at_ascending(busy_rows)
        assert busy_rows[0]["status"] == RUN_COMPLETED
        assert_money(busy_rows[0]["fuel_consumed_dth"], 220.80, "fuel_consumed_dth")

        quiet_rows, quiet_meta = _unit_runs(api, quiet_unit["id"])
        assert quiet_meta["total_count"] == 1, (
            f"The quiet unit holds one run, got {quiet_meta['total_count']}"
        )
        assert [row["id"] for row in quiet_rows] == [neighbour_run["id"]]

        scheduled_rows, scheduled_meta = _unit_runs(
            api, busy_unit["id"], SCHEDULING_COORDINATOR, status=RUN_SCHEDULED
        )
        assert scheduled_meta["total_count"] == 1, (
            "The status filter leaves only the run still scheduled, got "
            f"{scheduled_meta['total_count']}"
        )
        assert [row["id"] for row in scheduled_rows] == [future_run["id"]]

        empty_rows, empty_meta = _unit_runs(api, sibling_unit["id"])
        assert empty_meta["total_count"] == 0, (
            f"The sibling field's unit holds no runs, got {empty_meta['total_count']}"
        )
        assert empty_meta["has_more"] is False
        assert empty_rows == [], f"Expected an empty data array, got {empty_rows}"

        report_rows, report_meta = _field_reports(api, first_field["id"])
        assert report_meta["total_count"] == 1, (
            "The report channel is scoped to the reservoir in the path, got "
            f"{report_meta['total_count']}"
        )
        assert [row["id"] for row in report_rows] == [own_filing["id"]], (
            f"The sibling filing {sibling_filing['id']} belongs to the other reservoir"
        )
        assert_volume(report_rows[0]["book_inventory_dth"], 249779.200, "book_inventory_dth")
        assert_volume(report_rows[0]["variance_dth"], 0.000, "variance_dth")
        assert_variance_pct(report_rows[0]["variance_pct"], 0.0000)


class TestTheFieldRead:
    """One GET projects the whole derived block and mutates nothing."""

    def test_three_roles_read_the_same_derived_block_without_bumping_the_version(self, api):
        """The reservoir carries an observation wellbore alongside its in-service one and
        a unit holding a scheduled run, and three consecutive reads -- by the operator, by
        an integrity engineer, and by a customer holding no contract on the reservoir at
        all -- return identical rows: every derived quantity is projected, the observation wellbore
        is excluded from the in-service count, and no read moves `version`.

        PRD §2.7: "`wells_in_service_count` is the number of wellbores on this field whose
        `well_type` is `INJECTION_WITHDRAWAL` and whose `operational_state` is `IN_SERVICE`.
        Observation wellbores and wellbores that are shut in or plugged are not counted."

        PRD §3.1: "Registration computes the whole derived block at once.
        `max_working_gas_dth` is set, `working_gas_inventory_dth` is initialised from
        `opening_working_gas_dth`, and `retained_fuel_pool_dth` and `fuel_gas_used_dth` both
        start at 0."

        PRD §2.5: "`version`, an integer that begins at 1 on creation and increments by one
        on every mutation of that record."

        Design: Corner/endpoints/field_read_projects_every_derived_quantity_without_mutating_anything
        """
        field = create_field(api)
        create_well(api, field["id"], well_name="MINI-1")
        create_well(
            api, field["id"], well_name="MINI-OBS", well_type=WELL_TYPE_OBSERVATION,
        )
        unit = create_unit(api, field["id"])
        book_run(api, unit["id"])
        customer = create_shipper(api)

        by_operator = read_field(api, field["id"], FIELD_OPERATOR)
        by_engineer = read_field(api, field["id"], INTEGRITY_ENGINEER)
        by_customer = read_field(api, field["id"], make_shipper_headers(customer["id"]))

        for label, row in (
            ("FieldOperator", by_operator),
            ("IntegrityEngineer", by_engineer),
            ("Shipper", by_customer),
        ):
            assert row["max_working_gas_dth"] == F_MINI_MAX_WORKING_GAS_DTH, (
                f"{label}: max_working_gas_dth expected {F_MINI_MAX_WORKING_GAS_DTH}, got "
                f"{row['max_working_gas_dth']}"
            )
            assert_field_derived_block(
                row,
                working_gas=250000.000, inventory_pct=50.00, pressure=1500, tier=TIER_3,
                injection_rate=150000, withdrawal_rate=150000,
                wells_in_service=1, posture=POSTURE_OPEN,
            )
            assert_volume(row["retained_fuel_pool_dth"], 0.000, "retained_fuel_pool_dth")
            assert_volume(row["fuel_gas_used_dth"], 0.000, "fuel_gas_used_dth")
            assert row["opening_working_gas_dth"] == F_MINI_OPENING_WORKING_GAS_DTH, (
                f"{label}: opening_working_gas_dth expected "
                f"{F_MINI_OPENING_WORKING_GAS_DTH}, got {row['opening_working_gas_dth']}"
            )

        assert by_operator["version"] == by_engineer["version"] == by_customer["version"], (
            "Three reads must leave version alone: got "
            f"{by_operator['version']}, {by_engineer['version']}, {by_customer['version']}"
        )
        assert by_operator == by_engineer == by_customer, (
            "The customer read is admitted with no ownership relationship to the reservoir "
            "and must project exactly the same row"
        )

        committed = read_unit(api, unit["id"])
        assert committed["scheduled_run_count"] == 1, (
            f"scheduled_run_count: expected 1, got {committed['scheduled_run_count']}"
        )
        assert committed["status"] == UNIT_COMMITTED, (
            f"status: expected {UNIT_COMMITTED}, got {committed['status']}"
        )
        assert_money(committed["lifetime_fuel_dth"], 0.00, "lifetime_fuel_dth")


class TestTheFiveUniquenessScopes:
    """One priority row hides five scopes and five codes."""

    def test_each_scope_answers_its_own_code_and_the_unit_code_collides_only_within_a_field(
        self, api
    ):
        """`field_code`, `duns_number` and `contract_code` collide globally -- the contract
        code even when the second contract names a different reservoir -- while `unit_code`
        collides only within one reservoir, so U-1 is registered a second time on the sibling
        field. The report period collides on the composite of reservoir, type and period, but
        only while the earlier filing is not REJECTED: after the agency rejects it the very
        same period is filed again.

        PRD §2.11 rung 27: "**Uniqueness.** `field_code` is unique across all storage fields
        (`ERR_DUPLICATE_FIELD_CODE`); `duns_number` is unique across all shippers
        (`ERR_DUPLICATE_DUNS`); `contract_code` is unique across all storage contracts
        (`ERR_DUPLICATE_CONTRACT_CODE`); `unit_code` is unique within a `storage_field_id`
        (`ERR_DUPLICATE_UNIT_CODE`); and at most one non-`REJECTED` regulatory report may
        exist for a given combination of `storage_field_id`, `report_type`,
        `period_start_date` and `period_end_date` (`ERR_DUPLICATE_REPORT_PERIOD`). All are
        HTTP 409."

        PRD §3.9: "A `REJECTED` disposition moves the report from `SUBMITTED` to `REJECTED`,
        stores the agency's narrative, and unlocks the covered gas days so that the
        underlying measurements can be corrected."

        Design: Corner/validations/uniqueness_scopes_differ_per_entity_with_five_distinct_codes
        """
        first_field = create_field(api)
        create_well(api, first_field["id"], well_name="MINI-1")
        second_field = create_field(api, name="Cavern Two", field_code="F-TWO")
        create_well(api, second_field["id"], well_name="TWO-1")
        create_unit(api, first_field["id"], unit_code="U-1")
        shipper = create_shipper(api)
        create_contract(api, shipper["id"], first_field["id"], contract_code="CN-1")
        filing = create_report(api, first_field["id"], 250000.000)
        assert filing["prepared_by_user_id"] == OFFICER_A_ID
        assert filing["status"] == REPORT_DRAFT

        assert_error_envelope(
            api.create_storage_field(
                F.storage_field_payload(name="Copycat Cavern"), FIELD_OPERATOR
            ),
            ERR_DUPLICATE_FIELD_CODE,
        )
        assert_error_envelope(
            api.create_shipper(
                F.second_shipper_payload(
                    legal_name="Southline Gas Marketing", duns_number="123456789"
                ),
                SCHEDULING_COORDINATOR,
            ),
            ERR_DUPLICATE_DUNS,
        )
        assert_error_envelope(
            api.create_contract(
                F.contract_payload(shipper["id"], second_field["id"], contract_code="CN-1"),
                SCHEDULING_COORDINATOR,
            ),
            ERR_DUPLICATE_CONTRACT_CODE,
        )
        assert_error_envelope(
            api.create_compressor_unit(
                F.compressor_unit_payload(
                    first_field["id"], unit_code="U-1", rated_horsepower=4000
                ),
                FIELD_OPERATOR,
            ),
            ERR_DUPLICATE_UNIT_CODE,
        )

        sibling_unit = assert_created(
            api.create_compressor_unit(
                F.compressor_unit_payload(
                    second_field["id"], unit_code="U-1", rated_horsepower=4000
                ),
                FIELD_OPERATOR,
            )
        )
        assert sibling_unit["unit_code"] == "U-1", (
            "The station-local code is free on another reservoir, got "
            f"{sibling_unit['unit_code']}"
        )
        assert sibling_unit["storage_field_id"] == second_field["id"]

        assert_error_envelope(
            api.create_regulatory_report(
                F.regulatory_report_payload(first_field["id"], 250000.000),
                COMPLIANCE_OFFICER,
            ),
            ERR_DUPLICATE_REPORT_PERIOD,
        )
        sibling_filing = assert_created(
            api.create_regulatory_report(
                F.regulatory_report_payload(second_field["id"], 250000.000),
                COMPLIANCE_OFFICER,
            )
        )
        assert sibling_filing["status"] == REPORT_DRAFT, (
            "The same period on another reservoir opens at DRAFT, got "
            f"{sibling_filing['status']}"
        )
        assert sibling_filing["report_type"] == REPORT_TYPE_INVENTORY

        submitted = submit_report(api, filing["id"])
        assert submitted["status"] == REPORT_SUBMITTED
        rejected = assert_ok(
            api.record_agency_response(
                filing["id"],
                F.agency_response_payload(
                    AGENCY_REJECTED, "Resubmit with the corrected meter log"
                ),
                COMPLIANCE_OFFICER_B,
            )
        )
        assert rejected["status"] == REPORT_REJECTED
        assert rejected["agency_outcome"] == AGENCY_REJECTED
        assert_volume(rejected["book_inventory_dth"], 250000.000, "book_inventory_dth")
        assert_volume(rejected["variance_dth"], 0.000, "variance_dth")
        assert_variance_pct(rejected["variance_pct"], 0.0000)

        refiled = assert_created(
            api.create_regulatory_report(
                F.regulatory_report_payload(first_field["id"], 250000.000),
                COMPLIANCE_OFFICER,
            )
        )
        assert refiled["status"] == REPORT_DRAFT, (
            "The identical period is free once the earlier filing is REJECTED, got "
            f"{refiled['status']}"
        )
        assert refiled["period_start_date"] == "2026-08-01"
        assert refiled["period_end_date"] == "2026-08-31"

        rows, meta = _field_reports(api, first_field["id"])
        assert meta["total_count"] == 2, (
            f"Two filings now cover the reservoir, got {meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {filing["id"], refiled["id"]}


class TestTheNominationConcurrencyToken:
    """The create carries the token because the create is what supersedes."""

    def test_a_stale_contract_token_is_refused_on_both_shapes_and_supersedes_nothing(
        self, api, mini_world
    ):
        """The filing of the first nomination bumps the contract, leaving the client's token
        exactly one behind, and the refusal then fires on both shapes -- a create for an
        untouched gas day and a create that would displace the standing SUBMITTED row. Neither
        412 supersedes anything, neither leaves a DRAFT row behind, and neither burns a
        version; the retry with the refreshed token performs the supersede and bumps the
        contract exactly once.

        PRD §2.10: "A `POST /nominations` request must carry `expected_contract_version`,
        holding the client's last observed `version` of the target `StorageContract`. If that
        value does not equal the contract's current `version`, the create is rejected with
        `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

        PRD §3.5: "Filing also displaces any earlier work for the same slot: if a
        non-terminal nomination already exists on the same `contract_id`, `gas_day` and
        `direction`, it moves to the terminal `SUPERSEDED` status with its
        `superseded_by_nomination_id` set to the new nomination's `id`, and whatever confirmed
        volume it was holding is removed from the contract's scheduled totals. [...] Every
        filing increments the contract's `version` by one, which is exactly why the create is
        the endpoint that carries the optimistic-concurrency field."

        Design: Corner/cross_cutting_complexity_layers/nomination_create_rejects_a_stale_contract_version_and_supersedes_nothing
        """
        shipper_headers = make_shipper_headers(mini_world.shipper_id)
        observed_version = contract_version(api, mini_world.contract_id)

        standing = file_nomination(
            api, mini_world.contract_id, mini_world.shipper_id,
            gas_day="2026-08-02", direction=DIRECTION_INJECTION,
            nominated_volume_dth=80000,
        )
        standing = submit_nomination(api, standing["id"], mini_world.shipper_id)
        assert standing["status"] == NOMINATION_SUBMITTED

        current_version = contract_version(api, mini_world.contract_id)
        assert_version_bumped_by(current_version, observed_version, 1)

        assert_error_envelope(
            api.create_nomination(
                F.nomination_payload(
                    mini_world.contract_id, observed_version,
                    gas_day="2026-08-03", nominated_volume_dth=70000,
                ),
                shipper_headers,
            ),
            ERR_STALE_CONTRACT_VERSION,
        )
        assert_error_envelope(
            api.create_nomination(
                F.nomination_payload(
                    mini_world.contract_id, observed_version,
                    gas_day="2026-08-02", nominated_volume_dth=90000,
                ),
                shipper_headers,
            ),
            ERR_STALE_CONTRACT_VERSION,
        )

        untouched = read_nomination(api, standing["id"], shipper_headers)
        assert untouched["status"] == NOMINATION_SUBMITTED, (
            f"The supersede side effect never ran, got {untouched['status']}"
        )
        assert untouched["superseded_by_nomination_id"] is None
        assert untouched["nominated_volume_dth"] == 80000, (
            f"nominated_volume_dth: expected 80000, got {untouched['nominated_volume_dth']}"
        )
        assert contract_version(api, mini_world.contract_id) == current_version, (
            "A refused write must not increment version, or the client can never converge"
        )
        _, meta = validate_paginated(
            api.list_nominations(
                SCHEDULING_COORDINATOR,
                {"contract_id": mini_world.contract_id, "limit": 100},
            )
        )
        assert meta["total_count"] == 1, (
            f"Neither 412 left a DRAFT row behind, got {meta['total_count']}"
        )

        replacement = file_nomination(
            api, mini_world.contract_id, mini_world.shipper_id,
            expected_contract_version=current_version,
            gas_day="2026-08-02", direction=DIRECTION_INJECTION,
            nominated_volume_dth=90000,
        )
        assert replacement["status"] == NOMINATION_DRAFT, (
            f"A filing opens at DRAFT, got {replacement['status']}"
        )
        assert replacement["nominated_volume_dth"] == 90000
        assert replacement["revision_round"] == 0

        superseded = read_nomination(api, standing["id"], shipper_headers)
        assert superseded["status"] == NOMINATION_SUPERSEDED, (
            f"The accepted filing displaces the standing row, got {superseded['status']}"
        )
        assert superseded["superseded_by_nomination_id"] == replacement["id"], (
            "superseded_by_nomination_id must name the displacing nomination, got "
            f"{superseded['superseded_by_nomination_id']}"
        )
        assert_version_bumped_by(
            contract_version(api, mini_world.contract_id), current_version, 1
        )


class TestTheTicketConcurrencyToken:
    """The confirm carries the token because it prices against the field."""

    def test_a_stale_field_token_is_refused_then_the_refreshed_one_prices_the_burn(
        self, api, mini_world
    ):
        """A third party -- a compressor run closing out and burning 220.80 Dth of fuel gas
        out of working gas -- moves the reservoir's version underneath an operator holding an
        older token. The refused confirmation leaves the ticket PENDING with every charge
        field null and the reservoir untouched, and the retry against the refreshed token
        prices and posts from the post-burn inventory rather than from the 250,000 Dth the
        stale token described.

        PRD §2.10: "A `POST /gas-movement-tickets/{id}/confirm` request must carry
        `expected_storage_field_version`, holding the client's last observed `version` of the
        `StorageField` behind the ticket's nomination. If that value does not equal the
        field's current `version`, the confirmation is rejected with
        `ERR_STALE_FIELD_VERSION` (HTTP 412). Confirmation moves working gas against a
        deliverability envelope and a cushion-gas floor read from the field; a confirmation
        computed from a stale inventory view would succeed on its own terms while breaching
        the envelope the field now holds."

        PRD §3.6: "With the charges stamped, the ticket moves from `PENDING` to `CONFIRMED`
        and `confirmed_at` is set from the logical clock. On the reservoir,
        `working_gas_inventory_dth` moves by the full `actual_volume_dth`, signed by the
        nomination's `direction` — upward for an injection, downward for a withdrawal — and
        `retained_fuel_pool_dth` increases by `fuel_retention_dth`."

        Design: Corner/cross_cutting_complexity_layers/ticket_confirm_rejects_a_stale_field_version_then_succeeds_on_the_refreshed_token
        """
        unit = create_unit(api, mini_world.field_id)
        nomination = confirmed_nomination(
            api, mini_world.contract_id, mini_world.shipper_id,
            gas_day="2026-08-02", direction=DIRECTION_INJECTION,
            nominated_volume_dth=80000,
        )
        assert nomination["confirmed_volume_dth"] == 80000
        ticket = open_ticket(api, nomination["id"], mini_world.well_id, 80000)
        assert ticket["status"] == TICKET_PENDING
        assert_ticket_charges_unpriced(ticket)
        run = book_run(
            api, unit["id"],
            window_start_at="2026-08-02T00:00:00Z", window_end_at="2026-08-02T08:00:00Z",
            allocated_horsepower=3000, mode=RUN_MODE_INJECTION,
        )
        observed_version = field_version(api, mini_world.field_id)

        set_clock(api, "2026-08-02T08:00:00Z")
        burned = complete_run(api, run["id"])
        assert_money(burned["fuel_consumed_dth"], 220.80, "fuel_consumed_dth")
        after_burn = read_field(api, mini_world.field_id)
        assert_volume(
            after_burn["working_gas_inventory_dth"], 249779.200, "working_gas_inventory_dth"
        )
        assert_version_bumped_by(after_burn["version"], observed_version, 1)

        assert_error_envelope(
            api.confirm_ticket(
                ticket["id"], F.ticket_confirm_payload(observed_version), FIELD_OPERATOR
            ),
            ERR_STALE_FIELD_VERSION,
        )
        refused = read_ticket(api, ticket["id"])
        assert refused["status"] == TICKET_PENDING, (
            f"A refused confirm leaves the ticket PENDING, got {refused['status']}"
        )
        assert_ticket_charges_unpriced(refused)
        unmoved = read_field(api, mini_world.field_id)
        assert_volume(
            unmoved["working_gas_inventory_dth"], 249779.200, "working_gas_inventory_dth"
        )
        assert unmoved["version"] == after_burn["version"], (
            "A refused confirm moves no gas and burns no version, got "
            f"{unmoved['version']}"
        )

        confirmed = assert_ok(
            api.confirm_ticket(
                ticket["id"],
                F.ticket_confirm_payload(after_burn["version"]),
                FIELD_OPERATOR,
            )
        )
        assert confirmed["status"] == TICKET_CONFIRMED, (
            f"The refreshed token must be accepted, got {confirmed['status']}"
        )
        assert_ticket_charges(
            confirmed,
            fuel_retention=960.000, net_volume=79040.000,
            commodity=3600.00, discount=0.00, fuel_charge=3312.00, total=6912.00,
        )

        posted = read_field(api, mini_world.field_id)
        assert_volume(
            posted["working_gas_inventory_dth"], 329779.200, "working_gas_inventory_dth"
        )
        assert_volume(posted["retained_fuel_pool_dth"], 960.000, "retained_fuel_pool_dth")
        assert_version_bumped_by(posted["version"], after_burn["version"], 1)
