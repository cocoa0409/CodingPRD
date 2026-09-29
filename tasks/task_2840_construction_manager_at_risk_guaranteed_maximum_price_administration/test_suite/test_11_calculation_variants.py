"""Which numbers go in, which rate applies, and how wide the intermediate figures are.

Every calculation in this contract narrows an input set, reads a per-row rate, or rounds at
a named step. Each test here moves exactly one of those three dials and shows the published
figure move with it.
"""

from decimal import Decimal
from typing import Tuple

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CM_HEADERS,
    OWNER_HEADERS,
    PO_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_allowance_ledger_invariant,
    assert_equals,
    assert_fields,
    assert_instant,
    assert_money,
    assert_money_fields,
    assert_project_axes,
    assert_ratio,
    factories,
    fixtures,
    to_decimal,
)
from test_helpers.types import JsonObject

HARBORVIEW_CLINIC = {
    "name": "Harborview Clinic",
    "owner_org": "Harborview Health",
}

CLINIC_KWARGS = {"project_kwargs": dict(HARBORVIEW_CLINIC)}

AUGUST = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
SEPTEMBER = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")


def _clinic_allowance(
    api: ApiClient,
    allowance_amount: Decimal,
    allocated_units: Decimal,
    unit_of_measure: str,
    text: str,
) -> JsonObject:
    """Log one allowance against the clinic's base proposal while it is still a draft."""
    priced = fixtures.draft_priced_project(api, **CLINIC_KWARGS)
    return fixtures.allowance_item(
        api,
        priced.proposal["id"],
        allowance_amount=allowance_amount,
        allocated_units=allocated_units,
        unit_of_measure=unit_of_measure,
        text=text,
    )


def _rate_project(
    api: ApiClient, name: str, owner_org: str, insurance_rate: Decimal
) -> Tuple[JsonObject, JsonObject]:
    """Register a project at the named builder's-risk rate and reconcile its SD estimate."""
    project = fixtures.create_project(
        api,
        name=name,
        owner_org=owner_org,
        cm_fee_pct=Decimal("0.04"),
        insurance_rate=insurance_rate,
    )
    return project, fixtures.reconciled_estimate(api, project["id"])


def _price_it(api: ApiClient, project: JsonObject, estimate: JsonObject) -> JsonObject:
    """Send the one byte-identical proposal payload both projects are fed."""
    return validate_success(
        api.create_gmp_proposal(
            factories.gmp_proposal_payload(
                project["id"],
                estimate["id"],
                fixtures.project_version(api, project["id"]),
                cost_of_work_total=Decimal("1000000.00"),
                general_conditions_total=Decimal("100000.00"),
                owner_contingency_amount=Decimal("50000.00"),
                construction_contingency_amount=Decimal("40000.00"),
            ),
            CM_HEADERS,
        ),
        201,
    )


def _settled_project(api: ApiClient, name: str, unit_rate: Decimal) -> JsonObject:
    """An executed project carrying one reconciled August report at the named cost."""
    priced = fixtures.executed_project(
        api, project_kwargs={"name": name, "owner_org": "Harborview Health"}
    )
    fixtures.reconciled_cost_report(
        api,
        priced.id,
        period_start=AUGUST[0],
        period_end=AUGUST[1],
        quantity=Decimal("1.0000"),
        unit_rate=unit_rate,
    )
    return fixtures.read_project(api, priced.id)


def _reconcile(api: ApiClient, report_id: str, note: str) -> JsonObject:
    """Have the owner's representative close out a monthly report with RECONCILE."""
    return validate_success(
        api.reconcile_cost_report(
            report_id,
            factories.cost_report_reconcile_payload("RECONCILE", note),
            OWNER_HEADERS,
        )
    )


def test_the_booking_keeps_the_actual_cost_apart_from_the_expected_cost(
    api: ApiClient,
) -> None:
    """400 cubic yards bought at 62.50 against a 60.00 allowance rate: six figures move.

    PRD: "From those two numbers the server derives `allowance_unit_rate` as `allowance_amount` divided by `allocated_units`, rounded half-up to 4 decimal places, and opens the ledger with `remaining_units` equal to `allocated_units`, `reconciled_units` at 0.00, `reconciled_amount` at 0.00, `variance_amount` at 0.00, `reconciliation_seq` at 0, `last_action` at `NONE` and `status` at `OPEN`."

    PRD: "A successful booking moves four fields together: `reconciled_units` increases by the booked units, `remaining_units` decreases by the same units, `reconciled_amount` increases by the booked dollars — the units multiplied by the `actual_unit_cost`, rounded half-up to 2 decimal places — and `variance_amount` is rewritten as the item's `reconciled_amount` less the expected dollars at the carried rate, where the expected figure is `reconciled_units` multiplied by `allowance_unit_rate`, rounded half-up to 2 decimal places."

    PRD: "A positive `variance_amount` means the allowance is overrunning."

    PRD: "The booking also increments `reconciliation_seq` by 1 and records `last_action` as `RECONCILE`."

    PRD: "**The invariant, asserted after every action of either kind, is that `allocated_units` equals `remaining_units` plus `reconciled_units`.**"

    Design: Corner/calculations/allowance_reconcile_books_actual_cost_and_reports_the_rate_variance
    """
    item = _clinic_allowance(
        api,
        Decimal("90000.00"),
        Decimal("1500.00"),
        "CY",
        "hard rock excavation allowance",
    )
    assert_ratio(item["allowance_unit_rate"], Decimal("60.0000"), "allowance_unit_rate")
    assert_fields(item, {"status": "OPEN", "last_action": "NONE"})
    assert_equals(item, "reconciliation_seq", 0)
    assert_money_fields(
        item,
        {
            "allocated_units": Decimal("1500.00"),
            "remaining_units": Decimal("1500.00"),
            "reconciled_units": Decimal("0.00"),
        },
    )

    booked = validate_success(
        api.reconcile_allowance(
            item["id"],
            factories.allowance_reconcile_payload(
                Decimal("400.00"), Decimal("62.5000"), overrun_authorized=True
            ),
            CM_HEADERS,
        )
    )
    assert_money_fields(
        booked,
        {
            "reconciled_amount": Decimal("25000.00"),
            "variance_amount": Decimal("1000.00"),
            "reconciled_units": Decimal("400.00"),
            "remaining_units": Decimal("1100.00"),
            "allocated_units": Decimal("1500.00"),
        },
    )
    assert_fields(booked, {"status": "PARTIALLY_RECONCILED", "last_action": "RECONCILE"})
    assert_equals(booked, "reconciliation_seq", 1)
    assert_allowance_ledger_invariant(booked)


def test_the_unit_rate_keeps_four_decimals_so_three_units_book_the_whole_allowance(
    api: ApiClient,
) -> None:
    """100,000.00 over 3 units divides without terminating; the cent must still close.

    PRD: "Ratios are held to 4 decimal places, also round-half-up."

    PRD: "Every stored money field carries exactly 2 decimal places, and every rounding step uses the round-half-up convention."

    PRD: "From those two numbers the server derives `allowance_unit_rate` as `allowance_amount` divided by `allocated_units`, rounded half-up to 4 decimal places, and opens the ledger with `remaining_units` equal to `allocated_units`, `reconciled_units` at 0.00, `reconciled_amount` at 0.00, `variance_amount` at 0.00, `reconciliation_seq` at 0, `last_action` at `NONE` and `status` at `OPEN`."

    PRD: "A successful booking moves four fields together: `reconciled_units` increases by the booked units, `remaining_units` decreases by the same units, `reconciled_amount` increases by the booked dollars — the units multiplied by the `actual_unit_cost`, rounded half-up to 2 decimal places — and `variance_amount` is rewritten as the item's `reconciled_amount` less the expected dollars at the carried rate, where the expected figure is `reconciled_units` multiplied by `allowance_unit_rate`, rounded half-up to 2 decimal places."

    PRD: "After either action, the item's `status` is re-derived from the ledger rather than transitioned by hand: it is `OPEN` when `reconciled_units` is 0, `FULLY_RECONCILED` when `reconciled_units` equals `allocated_units`, and `PARTIALLY_RECONCILED` in between."

    PRD: "if the `actual_unit_cost` exceeds the item's `allowance_unit_rate`, the request must carry `overrun_authorized` set to true, acknowledging that the difference will be routed through a change event, and its absence is rejected with `ERR_ALLOWANCE_OVERRUN_UNAUTHORIZED` (HTTP 422)."

    Design: Corner/calculations/allowance_unit_rate_holds_four_decimals_while_money_holds_two
    """
    item = _clinic_allowance(
        api,
        Decimal("100000.00"),
        Decimal("3.00"),
        "EA",
        "signage package allowance",
    )
    assert_ratio(
        item["allowance_unit_rate"], Decimal("33333.3333"), "allowance_unit_rate"
    )

    booked = validate_success(
        api.reconcile_allowance(
            item["id"],
            factories.allowance_reconcile_payload(
                Decimal("3.00"), Decimal("33333.3333")
            ),
            CM_HEADERS,
        )
    )
    assert_money_fields(
        booked,
        {
            "reconciled_amount": Decimal("100000.00"),
            "variance_amount": Decimal("0.00"),
            "reconciled_units": Decimal("3.00"),
            "remaining_units": Decimal("0.00"),
            "allocated_units": Decimal("3.00"),
        },
    )
    assert_fields(booked, {"status": "FULLY_RECONCILED", "last_action": "RECONCILE"})
    assert_equals(booked, "reconciliation_seq", 1)
    assert_allowance_ledger_invariant(booked)


def test_packages_that_have_not_been_bought_out_bank_no_savings(api: ApiClient) -> None:
    """Three packages, one award: the savings figures see 40,000.00, not 540,000.00.

    PRD: "**Buyout savings are published two different ways from identical data.**"

    PRD: "For each work package of the project, the per-package delta is its `budget_amount` minus its `awarded_amount`, so a positive delta is an underrun."

    PRD: "Only packages whose `procurement_status` is `AWARDED`, `REPROCUREMENT` or `CLOSED` are included; packages still at `BUDGETED` or `SOLICITING` are excluded outright, because nothing has been bought out yet."

    PRD: "The **trade-level** figure (the `TRADE_LEVEL` variant) floors each package at zero before summing — it is the sum of the greater of the package delta and 0.00 across the included packages — and is written to the project's `buyout_savings_trade_level`."

    PRD: "The **project-net** figure (the `PROJECT_NET` variant) sums every included package delta signed, so overruns offset underruns and the result may be negative; it is written to the project's `buyout_savings_project_net`."

    PRD: "A new package begins with `procurement_status` at `BUDGETED`, `transparency_status` at `SEALED`, `awarded_bid_id` null, `awarded_amount` at 0.00, `committed_amount` at 0.00, `replacement_reserve_amount` at 0.00, `bid_count` at 0, and both `solicitation_opens_at` and `solicitation_closes_at` null."

    PRD: "The award advances the package `SOLICITING → AWARDED`, writes `awarded_bid_id` from the supplied `bid_id` and `awarded_amount` from that bid's `base_bid_amount`, advances the winning bid `OPENED → AWARDED`, and moves **every other** bid on that package that is currently `OPENED` to `NOT_AWARDED`."

    Design: Corner/calculations/buyout_savings_ignores_packages_that_have_not_been_bought_out
    """
    priced = fixtures.executed_project(api, **CLINIC_KWARGS)
    concrete = fixtures.soliciting_package(
        api,
        priced.id,
        budget_amount=Decimal("500000.00"),
        trade_division="03-CONCRETE",
        self_perform_intent=False,
    )
    finishes = fixtures.soliciting_package(
        api,
        priced.id,
        budget_amount=Decimal("300000.00"),
        trade_division="09-FINISHES",
        self_perform_intent=False,
    )
    electrical = fixtures.work_package(
        api,
        priced.id,
        budget_amount=Decimal("200000.00"),
        trade_division="26-ELECTRICAL",
        self_perform_intent=False,
    )
    assert_fields(
        electrical,
        {
            "procurement_status": "BUDGETED",
            "transparency_status": "SEALED",
            "awarded_bid_id": None,
            "bid_count": 0,
        },
    )

    bid = fixtures.opened_bid(
        api, concrete["id"], base_bid_amount=Decimal("460000.00")
    )
    awarded = validate_success(
        api.award_work_package(
            concrete["id"],
            factories.award_payload(bid["id"], "Cascade Concrete is the low bid"),
            PO_HEADERS,
        )
    )
    assert_fields(awarded, {"procurement_status": "AWARDED"})
    assert_money(awarded["awarded_amount"], Decimal("460000.00"), "awarded_amount")

    still_bidding = fixtures.read_work_package(api, finishes["id"])
    assert_fields(still_bidding, {"procurement_status": "SOLICITING"})
    assert_money(still_bidding["awarded_amount"], Decimal("0.00"), "awarded_amount")

    still_budgeted = fixtures.read_work_package(api, electrical["id"])
    assert_fields(still_budgeted, {"procurement_status": "BUDGETED"})
    assert_money(still_budgeted["awarded_amount"], Decimal("0.00"), "awarded_amount")

    project = fixtures.read_project(api, priced.id)
    assert_money_fields(
        project,
        {
            "buyout_savings_trade_level": Decimal("40000.00"),
            "buyout_savings_project_net": Decimal("40000.00"),
        },
    )


def test_two_projects_price_one_payload_from_their_own_rate_columns(
    api: ApiClient,
) -> None:
    """Byte-identical proposals, two builder's-risk rates, two guaranteed maximum prices.

    PRD: "A `ProgramAdmin` opens the engagement by registering the CMAR project itself, supplying a project `name` and the `owner_org` of the owner organization holding the CMAR contract (each between 1 and 200 characters), together with the two contractual rates that will later price the guaranteed maximum price: `cm_fee_pct`, the construction manager's fee rate, which must be greater than 0 and no greater than 0.1500 at 4 decimal places, and `insurance_rate`, the builder's-risk rate, which must be at least 0 and no greater than 0.0500 at 4 decimal places."

    PRD: "Compute `insurance_amount` as the project's `insurance_rate` multiplied by the sum of the base and `provisional_fee_amount`, rounded half-up to 2 decimal places."

    PRD: "Compute the **binding** `cm_fee_amount` as the project's `cm_fee_pct` multiplied by the sum of the base and `insurance_amount`, rounded half-up to 2 decimal places."

    PRD: "Compute the proposal's `gmp_amount` as the exact sum of five already-rounded terms: the base, `insurance_amount`, `cm_fee_amount`, `owner_contingency_amount` and `construction_contingency_amount`."

    PRD: "Only the proposal's own four money inputs plus `cm_fee_pct` and `insurance_rate` from its project participate."

    PRD: "A base proposal is minted with `proposal_type` recorded as `BASE`, `status` at `DRAFT`, `amount_delta` at 0.00 and `change_event_id` null, and the create increments the project's `version` by 1."

    Design: Corner/calculations/fee_and_insurance_rates_are_read_from_the_project_row_not_a_global_constant
    """
    clinic, clinic_estimate = _rate_project(
        api, "Harborview Clinic", "Harborview Health", Decimal("0.01")
    )
    pavilion, pavilion_estimate = _rate_project(
        api, "Eastgate Pavilion", "Eastgate Civic Trust", Decimal("0.02")
    )

    at_one_percent = _price_it(api, clinic, clinic_estimate)
    at_two_percent = _price_it(api, pavilion, pavilion_estimate)

    assert_money_fields(
        at_one_percent,
        {
            "provisional_fee_amount": Decimal("44000.00"),
            "insurance_amount": Decimal("11440.00"),
            "cm_fee_amount": Decimal("44457.60"),
            "gmp_amount": Decimal("1245897.60"),
            "amount_delta": Decimal("0.00"),
        },
    )
    assert_money_fields(
        at_two_percent,
        {
            "provisional_fee_amount": Decimal("44000.00"),
            "insurance_amount": Decimal("22880.00"),
            "cm_fee_amount": Decimal("44915.20"),
            "gmp_amount": Decimal("1257795.20"),
            "amount_delta": Decimal("0.00"),
        },
    )
    assert_fields(at_one_percent, {"proposal_type": "BASE", "status": "DRAFT"})
    assert_fields(at_two_percent, {"proposal_type": "BASE", "status": "DRAFT"})

    assert to_decimal(at_two_percent["gmp_amount"]) - to_decimal(
        at_one_percent["gmp_amount"]
    ) == Decimal("11897.60"), (
        "identical payloads must diverge by the insurance delta plus the fee it earns, "
        "not by nothing"
    )


def test_one_cent_of_pool_carries_the_split_across_the_first_tier_edge(
    api: ApiClient,
) -> None:
    """Two projects a penny apart in reported cost land on 25% and on 35%.

    PRD: "The **recoverable base** is the project's `gmp_amount` minus its `cm_fee_amount` minus its `insurance_amount`."

    PRD: "Under `PRE_AUDIT_PROVISIONAL`, the settled cost is the sum of `reported_cost_total` over the project's cost reports whose status is `RECONCILED` or `DISPUTED`."

    PRD: "Otherwise the **savings percentage** is the pool divided by the project's `gmp_amount`, rounded to 4 decimal places half-up."

    PRD: "The percentage is **rounded before the tier comparison**, and both tier boundaries are non-strict on their upper edge: a percentage of at most 0.02 selects a 25% construction-manager rate; otherwise a percentage of at most 0.05 selects 35%; anything above 0.05 selects 50%."

    PRD: "The uncapped construction-manager share is the selected rate times the pool, rounded to 2 decimal places half-up."

    PRD: "The **cap** is 25% of the project's `cm_fee_amount`, rounded to 2 decimal places half-up."

    PRD: "The construction manager's share is the lesser of the uncapped share and the cap, and the owner's share is the pool minus the construction manager's share — so the owner absorbs whatever the cap withholds, and the two shares always add back to the pool exactly."

    Design: Corner/calculations/one_cent_of_savings_pool_flips_the_shared_savings_tier
    """
    on_the_edge = _settled_project(api, "Harborview Clinic", Decimal("1165019.7600"))
    over_the_edge = _settled_project(api, "Harborview Annex", Decimal("1165019.7500"))
    for project in (on_the_edge, over_the_edge):
        assert_money_fields(
            project,
            {
                "gmp_amount": Decimal("1245897.60"),
                "cm_fee_amount": Decimal("44457.60"),
                "insurance_amount": Decimal("11440.00"),
            },
        )

    tier_one = validate_success(
        api.shared_savings(
            on_the_edge["id"],
            factories.shared_savings_payload("PRE_AUDIT_PROVISIONAL", False),
            OWNER_HEADERS,
        )
    )
    assert_money_fields(
        tier_one,
        {
            "provisional_savings_pool": Decimal("24980.24"),
            "provisional_cm_savings_share": Decimal("6245.06"),
            "provisional_owner_savings_share": Decimal("18735.18"),
        },
    )

    tier_two = validate_success(
        api.shared_savings(
            over_the_edge["id"],
            factories.shared_savings_payload("PRE_AUDIT_PROVISIONAL", False),
            OWNER_HEADERS,
        )
    )
    assert_money_fields(
        tier_two,
        {
            "provisional_savings_pool": Decimal("24980.25"),
            "provisional_cm_savings_share": Decimal("8743.09"),
            "provisional_owner_savings_share": Decimal("16237.16"),
        },
    )

    assert to_decimal(tier_two["provisional_cm_savings_share"]) - to_decimal(
        tier_one["provisional_cm_savings_share"]
    ) == Decimal("2498.03"), "one cent of pool must move the CM share by a whole tier step"
    for split in (tier_one, tier_two):
        assert to_decimal(split["provisional_cm_savings_share"]) < Decimal(
            "11114.40"
        ), "the fee cap must sit idle on both sides of the tier edge"
        assert to_decimal(split["provisional_cm_savings_share"]) + to_decimal(
            split["provisional_owner_savings_share"]
        ) == to_decimal(split["provisional_savings_pool"]), (
            "the two shares must add back to the pool exactly"
        )


def test_the_declared_basis_picks_the_variant_and_the_fields_it_may_write(
    api: ApiClient,
) -> None:
    """The same project at the same instant accepts one basis and refuses the other.

    PRD: "Shared savings are computed by the `OwnerRepresentative` under a declared `basis` of `PRE_AUDIT_PROVISIONAL` or `POST_AUDIT_FINAL`, together with an `execute` boolean that decides whether the figures are merely stored or the settlement is actually written."

    PRD: "It writes `provisional_savings_pool`, `provisional_cm_savings_share` and `provisional_owner_savings_share`, and moves `closeout_status` `NOT_STARTED → PROVISIONAL_COMPUTED`."

    PRD: "It may be run while the audit is anywhere at all, including `NOT_REQUESTED`, and while cost reports remain `OPEN`, `DISPUTED` or held."

    PRD: "This basis is permitted only when the project's `audit_status` is `CLOSED`, failing which it is rejected with `ERR_AUDIT_NOT_CLOSED` (HTTP 422), and only when no cost report of the project remains at `OPEN`, `DISPUTED` or `RECONCILIATION_HELD`, failing which it is rejected with `ERR_COST_REPORTS_NOT_RECONCILED` (HTTP 422)."

    PRD: "The provisional pass is therefore optional: an owner may go straight to the audited final figure, in which case the three provisional fields are simply never computed and stay at 0.00."

    Design: Corner/calculations/the_basis_field_selects_which_variant_runs_and_which_fields_it_writes
    """
    project = _settled_project(api, "Harborview Clinic", Decimal("1165100.0000"))
    assert_project_axes(
        project, audit_status="NOT_REQUESTED", closeout_status="NOT_STARTED"
    )

    provisional = validate_success(
        api.shared_savings(
            project["id"],
            factories.shared_savings_payload("PRE_AUDIT_PROVISIONAL", False),
            OWNER_HEADERS,
        )
    )
    assert_money_fields(
        provisional,
        {
            "provisional_savings_pool": Decimal("24900.00"),
            "provisional_cm_savings_share": Decimal("6225.00"),
            "provisional_owner_savings_share": Decimal("18675.00"),
            "final_savings_pool": Decimal("0.00"),
            "final_cm_savings_share": Decimal("0.00"),
            "final_owner_savings_share": Decimal("0.00"),
        },
    )
    assert_project_axes(provisional, closeout_status="PROVISIONAL_COMPUTED")

    validate_error(
        api.shared_savings(
            project["id"],
            factories.shared_savings_payload("POST_AUDIT_FINAL", False),
            OWNER_HEADERS,
        ),
        ApiErrorId.AUDIT_NOT_CLOSED,
        422,
    )

    unmoved = fixtures.read_project(api, project["id"])
    assert_money_fields(
        unmoved,
        {
            "provisional_savings_pool": Decimal("24900.00"),
            "provisional_cm_savings_share": Decimal("6225.00"),
            "provisional_owner_savings_share": Decimal("18675.00"),
            "final_savings_pool": Decimal("0.00"),
            "final_cm_savings_share": Decimal("0.00"),
            "final_owner_savings_share": Decimal("0.00"),
        },
    )
    assert_project_axes(
        unmoved, audit_status="NOT_REQUESTED", closeout_status="PROVISIONAL_COMPUTED"
    )


def test_the_reconciled_report_keeps_the_savings_snapshot_it_was_decided_on(
    api: ApiClient,
) -> None:
    """August is decided at 40,000.00 of savings and stays there once September doubles it.

    PRD: "A new report is minted with `status` `OPEN`, an empty `lines` array, `line_count` 0, all three of `reported_cost_total`, `undisputed_cost_total` and `disputed_cost_total` at 0.00, `buyout_savings_to_date` 0.00, and `held_reason`, `reconciled_at` and `reconciliation_note` all null."

    PRD: "The report's `reported_cost_total` is then the sum of `line_amount` over every line, `undisputed_cost_total` is the sum of `line_amount` over lines whose `disputed` is false, `disputed_cost_total` is the sum over lines whose `disputed` is true, and `line_count` is the number of entries in `lines`."

    PRD: "A `RECONCILE` decision is permitted from `OPEN` or from `DISPUTED` — the latter being how a dispute is resolved after the parties settle it — and requires the report's `line_count` to be at least 1; it advances the report to `RECONCILED` and stamps `reconciled_at` from the logical clock."

    PRD: "**Either** decision writes `reconciliation_note` from the payload and snapshots the project's `buyout_savings_trade_level` onto the report's `buyout_savings_to_date`, freezing the savings picture as at the moment the report was decided; a later award that changes the project figure does not retrospectively alter a decided report's snapshot."

    PRD: "Both are recomputed on every award, on every subcontract execution, and on every termination-for-default cascade that rewrites a package's `awarded_amount`."

    PRD: "because the interval is half-open, **adjacency is explicitly allowed** — a period whose `period_start` equals another period's `period_end` abuts it and is not an overlap, so consecutive monthly periods tile without gaps"

    Design: Corner/calculations/cost_report_snapshots_buyout_savings_and_never_restates_it
    """
    priced = fixtures.executed_project(api, **CLINIC_KWARGS)
    fixtures.awarded_package(
        api,
        priced.id,
        budget_amount=Decimal("500000.00"),
        base_bid_amount=Decimal("460000.00"),
        trade_division="03-CONCRETE",
        self_perform_intent=False,
    )

    august = fixtures.cost_report(
        api, priced.id, period_start=AUGUST[0], period_end=AUGUST[1]
    )
    assert_fields(august, {"status": "OPEN", "line_count": 0, "reconciled_at": None})
    assert_money(
        august["buyout_savings_to_date"], Decimal("0.00"), "buyout_savings_to_date"
    )
    fixtures.append_line(
        api,
        august["id"],
        cost_code="03-100",
        quantity=Decimal("1.0000"),
        unit_rate=Decimal("300000.0000"),
    )
    august_decided = _reconcile(api, august["id"], "August reconciled")
    assert_fields(
        august_decided,
        {"status": "RECONCILED", "reconciliation_note": "August reconciled"},
    )
    assert_money_fields(
        august_decided,
        {
            "reported_cost_total": Decimal("300000.00"),
            "buyout_savings_to_date": Decimal("40000.00"),
        },
    )

    fixtures.awarded_package(
        api,
        priced.id,
        budget_amount=Decimal("300000.00"),
        base_bid_amount=Decimal("250000.00"),
        trade_division="09-FINISHES",
        self_perform_intent=False,
        solicitation_opens_at="2026-08-15T00:00:00Z",
        solicitation_closes_at="2026-08-20T00:00:00Z",
    )

    september = fixtures.cost_report(
        api, priced.id, period_start=SEPTEMBER[0], period_end=SEPTEMBER[1]
    )
    fixtures.append_line(
        api,
        september["id"],
        cost_code="09-100",
        quantity=Decimal("1.0000"),
        unit_rate=Decimal("200000.0000"),
    )
    september_decided = _reconcile(api, september["id"], "September reconciled")
    assert_fields(september_decided, {"status": "RECONCILED"})
    assert_money_fields(
        september_decided,
        {
            "reported_cost_total": Decimal("200000.00"),
            "buyout_savings_to_date": Decimal("90000.00"),
        },
    )

    august_again = fixtures.read_cost_report(api, august["id"])
    assert_fields(august_again, {"status": "RECONCILED"})
    assert_money_fields(
        august_again,
        {
            "reported_cost_total": Decimal("300000.00"),
            "buyout_savings_to_date": Decimal("40000.00"),
        },
    )
    assert_instant(august_again["period_end"], SEPTEMBER[0], "period_end")
    assert_instant(september_decided["period_start"], AUGUST[1], "period_start")

    project = fixtures.read_project(api, priced.id)
    assert_money_fields(
        project,
        {
            "buyout_savings_trade_level": Decimal("90000.00"),
            "buyout_savings_project_net": Decimal("90000.00"),
        },
    )
