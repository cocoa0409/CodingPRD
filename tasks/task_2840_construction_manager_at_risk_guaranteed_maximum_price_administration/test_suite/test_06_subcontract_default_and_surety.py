"""Subcontract default: the cure loop, the surety axis, and the five-level cascade.

The contract-performance axis and the surety axis move independently of one another,
and the one operation that terminates a subcontract reaches from the subcontract's own
exposure all the way down to the project's open cost reports.
"""

from decimal import Decimal
from typing import Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CM_HEADERS,
    OWNER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_equals,
    assert_fields,
    assert_gmp_identity,
    assert_money,
    assert_money_fields,
    assert_project_axes,
    factories,
    fixtures,
    single_row,
)
from test_helpers.types import JsonObject

NORTHGATE_TRANSIT_CENTER = {
    "cm_fee_pct": Decimal("0.04"),
    "insurance_rate": Decimal("0.01"),
    "cost_of_work_total": Decimal("3000000.00"),
    "general_conditions_total": Decimal("200000.00"),
    "owner_contingency_amount": Decimal("100000.00"),
    "construction_contingency_amount": Decimal("240000.00"),
    "project_kwargs": {
        "name": "Northgate Transit Center",
        "owner_org": "Northgate Transit Authority",
        "precon_fee_amount": Decimal("60000.00"),
    },
}


def _status_action(
    api: ApiClient, subcontract_id: str, action: str, **notes: str
) -> JsonObject:
    """Drive the contract-performance axis of a subcontract."""
    return validate_success(
        api.subcontract_status_action(
            subcontract_id, factories.status_action_payload(action, **notes), CM_HEADERS
        )
    )


def _earthwork_default_noticed(api: ApiClient) -> Tuple[str, JsonObject]:
    """A bonded 1,900,000.00 earthwork subcontract, 400,000.00 paid, at default notice.

    The exposure a default would have to replace is therefore 1,500,000.00 rather than
    the whole contract amount.
    """
    priced = fixtures.executed_project(api, **NORTHGATE_TRANSIT_CENTER)
    setup = fixtures.active_subcontract(
        api,
        priced.id,
        budget_amount=Decimal("2000000.00"),
        base_bid_amount=Decimal("1900000.00"),
        contract_amount=Decimal("1900000.00"),
        bond_required=True,
        bond_amount=Decimal("1900000.00"),
        performance_start="2026-09-01T00:00:00Z",
        performance_end="2026-12-01T00:00:00Z",
    )
    fixtures.pay_subcontract(api, setup.id, Decimal("400000.00"))
    noticed = fixtures.notice_default(api, setup.id, "abandonment of the work")
    assert_fields(noticed, {"contract_status": "DEFAULT_NOTICED"})
    return priced.id, setup.subcontract


def _steel_package_with_a_winter_window(
    api: ApiClient,
) -> Tuple[str, fixtures.SubcontractSetup]:
    """A 500,000.00 steel subcontract holding the closed window 09-01 through 12-01."""
    priced = fixtures.executed_project(api, **NORTHGATE_TRANSIT_CENTER)
    setup = fixtures.active_subcontract(
        api,
        priced.id,
        budget_amount=Decimal("900000.00"),
        base_bid_amount=Decimal("500000.00"),
        contract_amount=Decimal("500000.00"),
        performance_start="2026-09-01T00:00:00Z",
        performance_end="2026-12-01T00:00:00Z",
    )
    return priced.id, setup


def _candidate_window(
    api: ApiClient,
    package: JsonObject,
    bid_id: str,
    package_version: int,
    performance_start: str,
    performance_end: str,
    contract_amount: Decimal = Decimal("100000.00"),
    subcontractor_name: str = "Keystone Steel Erection Phase 2",
) -> object:
    """Attempt a second subcontract on the same package over the named window."""
    return api.create_subcontract(
        factories.subcontract_payload(
            package["id"],
            bid_id,
            package_version,
            contract_amount=contract_amount,
            performance_start=performance_start,
            performance_end=performance_end,
            subcontractor_name=subcontractor_name,
            bond_required=False,
        ),
        CM_HEADERS,
    )


def test_the_cure_loop_returns_the_contract_to_active_and_counts_itself(
    api: ApiClient,
) -> None:
    """A cured default leaves the contract where it started, but with a memory of it.

    PRD: "Noticing a default advances `ACTIVE → DEFAULT_NOTICED` and stamps `default_notice_at` from the logical clock."

    PRD: "Curing advances `DEFAULT_NOTICED → ACTIVE`, increments `cure_count` by 1 and clears `default_notice_at` back to null; that loop may repeat without bound and `cure_count` records how many times it did."

    PRD: "Its **surety axis branches on the creation payload**: when `bond_required` is true the `bond_claim_status` is initialised to `NONE`, meaning a claim is possible but has not been filed; when `bond_required` is false it is initialised to `NOT_APPLICABLE`, a terminal dead axis on which no bond-claim action will ever be accepted."

    Design: Difficulty/non_linear_state_machine/subcontract_two_independent_axes_with_default_cure_cycle
    """
    _project_id, subcontract = _earthwork_default_noticed(api)

    cured = _status_action(
        api,
        subcontract["id"],
        "CURE",
        cure_note="crew remobilized within the cure period",
    )
    assert_fields(
        cured,
        {
            "contract_status": "ACTIVE",
            "cure_count": 1,
            "default_notice_at": None,
            "bond_claim_status": "NONE",
        },
    )
    assert_money_fields(
        cured,
        {
            "paid_to_date": Decimal("400000.00"),
            "unpaid_committed_amount": Decimal("1500000.00"),
            "bond_claim_amount": Decimal("0.00"),
            "replacement_cost_amount": Decimal("0.00"),
        },
    )

    noticed_again = _status_action(
        api, subcontract["id"], "NOTICE_DEFAULT", default_reason="second demobilization"
    )
    assert_fields(
        noticed_again,
        {"contract_status": "DEFAULT_NOTICED", "cure_count": 1, "bond_claim_status": "NONE"},
    )
    assert noticed_again["default_notice_at"] is not None, (
        "the second default notice did not stamp default_notice_at"
    )


def test_the_surety_axis_runs_its_own_course_without_moving_the_contract_axis(
    api: ApiClient,
) -> None:
    """Filing, acknowledging and denying the bond all leave the contract terminated.

    PRD: "If `bond_required` is true, the `bond_claim_status` stays exactly where it was at `NONE` — termination does not file a claim, and the claim must still be filed explicitly."

    PRD: "A `ConstructionManager` files the claim with an `action` of `FILE` and a `claim_amount`, which must not exceed the subcontract's `bond_amount`; filing requires `bond_required` to be true — so the axis is at `NONE` rather than `NOT_APPLICABLE` — and requires the `contract_status` to be `TERMINATED_FOR_DEFAULT`."

    PRD: "`DENY` advances `ACKNOWLEDGED → DENIED`, and is also permitted directly from `FILED`, advancing `FILED → DENIED`; an optional `denial_reason` may be recorded, `bond_recovered_amount` stays at 0.00, and no contingency credit occurs — the construction contingency simply stays depleted."

    PRD: "This endpoint never touches `contract_status`: a denied claim leaves the contract `TERMINATED_FOR_DEFAULT`, and a settled claim does not resurrect it."

    Design: Difficulty/non_linear_state_machine/subcontract_two_independent_axes_with_default_cure_cycle
    """
    project_id, subcontract = _earthwork_default_noticed(api)
    _status_action(
        api,
        subcontract["id"],
        "CURE",
        cure_note="crew remobilized within the cure period",
    )
    _status_action(
        api, subcontract["id"], "NOTICE_DEFAULT", default_reason="second demobilization"
    )

    validate_error(
        api.bond_claim(
            subcontract["id"],
            factories.bond_claim_payload("FILE", claim_amount=Decimal("1500000.00")),
            CM_HEADERS,
        ),
        ApiErrorId.BOND_CLAIM_STATE_INVALID,
        409,
    )

    terminated = _status_action(
        api,
        subcontract["id"],
        "TERMINATE_FOR_DEFAULT",
        default_reason="failure to cure the second default",
    )
    assert_fields(
        terminated,
        {
            "contract_status": "TERMINATED_FOR_DEFAULT",
            "bond_claim_status": "NONE",
            "cure_count": 1,
        },
    )
    assert_money_fields(
        terminated,
        {
            "unpaid_committed_amount": Decimal("1500000.00"),
            "replacement_cost_amount": Decimal("1725000.00"),
        },
    )

    filed = validate_success(
        api.bond_claim(
            subcontract["id"],
            factories.bond_claim_payload("FILE", claim_amount=Decimal("1500000.00")),
            CM_HEADERS,
        )
    )
    assert_fields(
        filed,
        {"bond_claim_status": "FILED", "contract_status": "TERMINATED_FOR_DEFAULT"},
    )
    assert_money(filed["bond_claim_amount"], Decimal("1500000.00"), "bond_claim_amount")

    acknowledged = validate_success(
        api.bond_claim(
            subcontract["id"], factories.bond_claim_payload("ACKNOWLEDGE"), OWNER_HEADERS
        )
    )
    assert_fields(
        acknowledged,
        {
            "bond_claim_status": "ACKNOWLEDGED",
            "contract_status": "TERMINATED_FOR_DEFAULT",
        },
    )

    denied = validate_success(
        api.bond_claim(
            subcontract["id"],
            factories.bond_claim_payload(
                "DENY", denial_reason="surety asserts the notice was untimely"
            ),
            OWNER_HEADERS,
        )
    )
    assert_fields(
        denied,
        {
            "bond_claim_status": "DENIED",
            "contract_status": "TERMINATED_FOR_DEFAULT",
            "cure_count": 1,
        },
    )
    assert_money_fields(
        denied,
        {
            "bond_claim_amount": Decimal("1500000.00"),
            "bond_recovered_amount": Decimal("0.00"),
            "unpaid_committed_amount": Decimal("1500000.00"),
            "replacement_cost_amount": Decimal("1725000.00"),
        },
    )

    project = fixtures.read_project(api, project_id)
    assert_money_fields(
        project,
        {
            "construction_contingency_remaining": Decimal("15000.00"),
            "gmp_amount": Decimal("3702611.20"),
        },
    )


def test_termination_reprices_the_package_and_posts_the_premium_out_of_contingency(
    api: ApiClient,
) -> None:
    """Levels one through four: exposure, reprocurement, a posted draw, a constrained pot.

    PRD: "On the subcontract itself, `unpaid_committed_amount` is frozen at `contract_amount` less `paid_to_date`, and `replacement_cost_amount` is written as that frozen unpaid amount multiplied by 1.15 — a fifteen-percent replacement premium — rounded half-up to 2 decimal places."

    PRD: "Its `replacement_reserve_amount` is set to the subcontract's `replacement_cost_amount`; its `committed_amount` drops by the terminated subcontract's `unpaid_committed_amount`, which is exactly what the recount rule above yields once the terminated row contributes only its `paid_to_date`; and its `awarded_amount` increases by the replacement premium."

    PRD: "Because `awarded_amount` moved, a contingency draw is minted for the premium: `contingency_type` `CONSTRUCTION`, `origin` `SUBCONTRACTOR_DEFAULT_PREMIUM`, `amount` equal to the replacement premium, `requires_owner_approval` true, `source_subcontract_id` naming the terminated subcontract and `change_event_id` null — and, uniquely among draws, it is minted **already at** `POSTED` with `posted_at` stamped from the logical clock."

    PRD: "Posting it moves `construction_contingency_remaining` down by the premium and `contingency_drawn_to_cost_total` up by the premium, leaving `gmp_amount` untouched exactly as §2.6 requires."

    Design: Difficulty/transitive_cascade/subcontractor_default_five_level_cascade_to_held_cost_reports
    """
    project_id, subcontract = _earthwork_default_noticed(api)

    terminated = _status_action(
        api,
        subcontract["id"],
        "TERMINATE_FOR_DEFAULT",
        default_reason="failure to cure within the notice period",
    )
    assert_fields(terminated, {"contract_status": "TERMINATED_FOR_DEFAULT"})
    assert_money_fields(
        terminated,
        {
            "unpaid_committed_amount": Decimal("1500000.00"),
            "replacement_cost_amount": Decimal("1725000.00"),
        },
    )

    package = fixtures.read_work_package(api, subcontract["work_package_id"])
    assert_fields(package, {"procurement_status": "REPROCUREMENT"})
    assert_money_fields(
        package,
        {
            "replacement_reserve_amount": Decimal("1725000.00"),
            "awarded_amount": Decimal("2125000.00"),
            "committed_amount": Decimal("400000.00"),
        },
    )

    draws, meta = validate_paginated(
        api.list_draws(
            CM_HEADERS,
            {"project_id": project_id, "origin": "SUBCONTRACTOR_DEFAULT_PREMIUM"},
        )
    )
    assert meta["total_count"] == 1, (
        "the termination did not mint exactly one replacement-premium draw"
    )
    premium_draw = single_row(draws, "source_subcontract_id", subcontract["id"])
    assert_fields(
        premium_draw,
        {
            "contingency_type": "CONSTRUCTION",
            "status": "POSTED",
            "requires_owner_approval": True,
            "change_event_id": None,
        },
    )
    assert_money(premium_draw["amount"], Decimal("225000.00"), "premium draw amount")
    assert premium_draw["posted_at"] is not None, (
        "the cascade-minted draw was not stamped with posted_at"
    )

    project = fixtures.read_project(api, project_id)
    assert_project_axes(project, contingency_posture="CONSTRAINED", gmp_status="EXECUTED")
    assert_money_fields(
        project,
        {
            "construction_contingency_remaining": Decimal("15000.00"),
            "contingency_drawn_to_cost_total": Decimal("225000.00"),
            "owner_contingency_remaining": Decimal("100000.00"),
            "gmp_amount": Decimal("3702611.20"),
            "buyout_savings_trade_level": Decimal("0.00"),
            "buyout_savings_project_net": Decimal("-125000.00"),
        },
    )
    assert_gmp_identity(project)


def test_the_fifth_cascade_level_holds_only_the_reports_still_open(
    api: ApiClient,
) -> None:
    """The report already reconciled is provably left alone by the hold.

    PRD: "Because the contingency ledger moved, `contingency_posture` is re-derived, and if it lands on `CONSTRAINED` every cost report of the project whose status is `OPEN` is held at `RECONCILIATION_HELD` with the reason `CONSTRUCTION_CONTINGENCY_CONSTRAINED`."

    PRD: "A single termination therefore increments the subcontract's `version`, the work package's `version` and the project's `version`, plus a `version` on each held cost report."

    PRD: "A report sitting at `RECONCILIATION_HELD` accepts neither new lines nor a reconcile decision, and any action attempted from a status that does not permit it is rejected with `ERR_COST_REPORT_STATE_INVALID` (HTTP 409)."

    Design: Difficulty/transitive_cascade/subcontractor_default_five_level_cascade_to_held_cost_reports
    """
    project_id, subcontract = _earthwork_default_noticed(api)
    reconciled = fixtures.reconciled_cost_report(
        api,
        project_id,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        quantity=Decimal("1.0000"),
        unit_rate=Decimal("400000.0000"),
    )
    still_open = fixtures.cost_report(
        api,
        project_id,
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-10-01T00:00:00Z",
    )
    fixtures.append_line(
        api,
        still_open["id"],
        quantity=Decimal("1.0000"),
        unit_rate=Decimal("50000.0000"),
    )

    _status_action(
        api,
        subcontract["id"],
        "TERMINATE_FOR_DEFAULT",
        default_reason="failure to cure within the notice period",
    )

    held = fixtures.read_cost_report(api, still_open["id"])
    assert_fields(
        held,
        {
            "status": "RECONCILIATION_HELD",
            "held_reason": "CONSTRUCTION_CONTINGENCY_CONSTRAINED",
        },
    )
    assert held["version"] > still_open["version"], (
        "the held report's version did not increment with the hold"
    )

    untouched = fixtures.read_cost_report(api, reconciled["id"])
    assert_fields(untouched, {"status": "RECONCILED", "held_reason": None})

    validate_error(
        api.reconcile_cost_report(
            still_open["id"],
            factories.cost_report_reconcile_payload("RECONCILE"),
            OWNER_HEADERS,
        ),
        ApiErrorId.COST_REPORT_STATE_INVALID,
        409,
    )
    assert_project_axes(
        fixtures.read_project(api, project_id), contingency_posture="CONSTRAINED"
    )


def test_the_mobilization_buffer_wants_seventy_two_clear_hours_on_an_inclusive_edge(
    api: ApiClient,
) -> None:
    """Touching the sibling's end instant is zero clear hours; 72 hours exactly is enough.

    PRD: "A new subcontract's closed performance window must be separated from every *blocking* sibling window on the same work package by at least 72 hours — three full days — of clear time on whichever side it falls."

    PRD: "Any window that overlaps a blocking sibling, or that clears it by less than 72 hours, is rejected with `ERR_PERFORMANCE_WINDOW_BUFFER_VIOLATION` (HTTP 409)."

    PRD: "the on-site performance window as `performance_start` and `performance_end` (ISO 8601 UTC instants bounding a **closed**, inclusive interval, with the end strictly after the start)"

    PRD: "Creating a subcontract requires `expected_work_package_version` to equal the target work package's current `version`, and a mismatch is rejected with `ERR_STALE_WORK_PACKAGE_VERSION` (HTTP 412)."

    Design: Difficulty/resource_temporal_overlap/subcontract_windows_need_seventy_two_clear_hours_from_blocking_siblings_only
    """
    _project_id, setup = _steel_package_with_a_winter_window(api)
    held_version = fixtures.work_package_version(api, setup.package["id"])

    validate_error(
        _candidate_window(
            api,
            setup.package,
            setup.bid["id"],
            held_version,
            "2026-12-01T00:00:00Z",
            "2027-02-01T00:00:00Z",
        ),
        ApiErrorId.PERFORMANCE_WINDOW_BUFFER_VIOLATION,
        409,
    )
    validate_error(
        _candidate_window(
            api,
            setup.package,
            setup.bid["id"],
            held_version,
            "2026-12-03T23:59:59Z",
            "2027-02-01T00:00:00Z",
        ),
        ApiErrorId.PERFORMANCE_WINDOW_BUFFER_VIOLATION,
        409,
    )

    accepted = validate_success(
        _candidate_window(
            api,
            setup.package,
            setup.bid["id"],
            held_version,
            "2026-12-04T00:00:00Z",
            "2027-02-01T00:00:00Z",
        ),
        201,
    )
    assert_fields(
        accepted,
        {"contract_status": "ACTIVE", "bond_claim_status": "NOT_APPLICABLE", "cure_count": 0},
    )
    assert_money(accepted["bond_amount"], Decimal("0.00"), "bond_amount")


def test_a_terminated_sibling_stops_blocking_the_window_it_vacated(
    api: ApiClient,
) -> None:
    """The replacement crew may take the very interval that was refused an hour earlier.

    PRD: "Blocking siblings are those whose `contract_status` is `ACTIVE`, `DEFAULT_NOTICED` or `COMPLETED`."

    PRD: "Siblings at `TERMINATED_FOR_DEFAULT` are deliberately non-blocking, so that a reprocurement can reuse the window the defaulted trade vacated."

    PRD: "Because the contingency ledger moved, `contingency_posture` is re-derived, and if it lands on `CONSTRAINED` every cost report of the project whose status is `OPEN` is held at `RECONCILIATION_HELD` with the reason `CONSTRUCTION_CONTINGENCY_CONSTRAINED`."

    Design: Difficulty/resource_temporal_overlap/subcontract_windows_need_seventy_two_clear_hours_from_blocking_siblings_only
    """
    project_id, setup = _steel_package_with_a_winter_window(api)
    phase_two = validate_success(
        _candidate_window(
            api,
            setup.package,
            setup.bid["id"],
            fixtures.work_package_version(api, setup.package["id"]),
            "2026-12-04T00:00:00Z",
            "2027-02-01T00:00:00Z",
        ),
        201,
    )

    validate_error(
        _candidate_window(
            api,
            setup.package,
            setup.bid["id"],
            fixtures.work_package_version(api, setup.package["id"]),
            "2026-09-15T00:00:00Z",
            "2026-10-15T00:00:00Z",
            contract_amount=Decimal("575000.00"),
            subcontractor_name="Ridgeline Steel replacement crew",
        ),
        ApiErrorId.PERFORMANCE_WINDOW_BUFFER_VIOLATION,
        409,
    )

    fixtures.notice_default(api, setup.id, "erection crew never mobilised")
    terminated = fixtures.terminate_for_default(api, setup.id)
    assert_fields(terminated, {"contract_status": "TERMINATED_FOR_DEFAULT"})
    assert_money_fields(
        terminated,
        {
            "unpaid_committed_amount": Decimal("500000.00"),
            "replacement_cost_amount": Decimal("575000.00"),
        },
    )

    replacement = validate_success(
        _candidate_window(
            api,
            setup.package,
            setup.bid["id"],
            fixtures.work_package_version(api, setup.package["id"]),
            "2026-09-15T00:00:00Z",
            "2026-10-15T00:00:00Z",
            contract_amount=Decimal("575000.00"),
            subcontractor_name="Ridgeline Steel replacement crew",
        ),
        201,
    )
    assert_fields(replacement, {"contract_status": "ACTIVE"})

    rows, meta = validate_paginated(
        api.list_subcontracts(CM_HEADERS, {"work_package_id": setup.package["id"]})
    )
    assert meta["total_count"] == 3, "the package does not carry exactly three subcontracts"
    active_rows, active_meta = validate_paginated(
        api.list_subcontracts(
            CM_HEADERS,
            {"work_package_id": setup.package["id"], "contract_status": "ACTIVE"},
        )
    )
    assert active_meta["total_count"] == 2, (
        "the terminated subcontract is still being listed as ACTIVE"
    )
    assert {row["id"] for row in active_rows} == {phase_two["id"], replacement["id"]}
    assert setup.id in {row["id"] for row in rows}

    project = fixtures.read_project(api, project_id)
    assert_project_axes(project, contingency_posture="OPEN")
    assert_money_fields(
        project,
        {
            "construction_contingency_remaining": Decimal("165000.00"),
            "contingency_drawn_to_cost_total": Decimal("75000.00"),
        },
    )
    assert_equals(project, "gmp_status", "EXECUTED")
