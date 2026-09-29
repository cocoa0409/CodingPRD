"""Trade buyout: the two savings figures, bid opening and writing the subcontract.

Buyout savings are published two different ways from identical data, bid opening is
guarded by four independent conditions, and a subcontract may only be written from
the bid that actually won.
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
    PO_HEADERS,
    PO_INDEPENDENT_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_fields,
    assert_instant,
    assert_money,
    assert_money_fields,
    factories,
    fixtures,
    single_row,
    to_decimal,
    user_id_of,
)
from test_helpers.types import JsonObject

RIVERSIDE_DATA_HALL = {
    "cm_fee_pct": Decimal("0.0375"),
    "insurance_rate": Decimal("0.0125"),
    "cost_of_work_total": Decimal("40000000.00"),
    "general_conditions_total": Decimal("2500000.00"),
    "owner_contingency_amount": Decimal("1200000.00"),
    "construction_contingency_amount": Decimal("240000.00"),
    "project_kwargs": {
        "name": "Riverside Data Hall",
        "owner_org": "Riverside Metro Owner Authority",
        "precon_fee_amount": Decimal("250000.00"),
    },
}


def _southgate_awarded_with_a_losing_bid(
    api: ApiClient,
) -> Tuple[JsonObject, JsonObject, JsonObject]:
    """A concrete package awarded to the low bidder, with the high bidder not awarded."""
    priced = fixtures.executed_project(
        api, project_kwargs={"name": "Southgate Parking Structure"}
    )
    package = fixtures.soliciting_package(
        api,
        priced.id,
        budget_amount=Decimal("1000000.00"),
        trade_division="03-CONCRETE",
        solicitation_opens_at="2026-08-01T00:00:00Z",
        solicitation_closes_at="2026-08-10T00:00:00Z",
    )
    winner = fixtures.third_party_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("950000.00"),
        bidder_name="Alpha Concrete Contractors",
    )
    loser = fixtures.third_party_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("980000.00"),
        bidder_name="Beta Structural Concrete",
    )
    fixtures.set_clock(api, "2026-08-10T00:00:00Z")
    validate_success(api.open_bid(winner["id"], PO_INDEPENDENT_HEADERS))
    validate_success(api.open_bid(loser["id"], PO_INDEPENDENT_HEADERS))
    awarded = validate_success(
        api.award_work_package(
            package["id"], factories.award_payload(winner["id"]), PO_HEADERS
        )
    )
    return awarded, winner, loser


def _self_perform_bid_awaiting_disclosure(
    api: ApiClient,
) -> Tuple[JsonObject, JsonObject]:
    """A sealed self-perform drywall bid on a package still at SEALED disclosure."""
    priced = fixtures.executed_project(api)
    package = fixtures.soliciting_package(
        api,
        priced.id,
        budget_amount=Decimal("180000.00"),
        trade_division="09-DRYWALL",
        self_perform_intent=True,
        solicitation_opens_at="2026-08-01T00:00:00Z",
        solicitation_closes_at="2026-08-20T00:00:00Z",
    )
    bid = fixtures.self_perform_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("170000.00"),
        bidder_name="CM Self-Perform Drywall Division",
        open_book_cost_breakdown=factories.open_book_breakdown(
            Decimal("90000.00"),
            Decimal("55000.00"),
            Decimal("8000.00"),
            Decimal("12000.00"),
            Decimal("5000.00"),
        ),
    )
    # Re-read the package: submitting the bid bumped its bid_count and version
    # behind the snapshot taken at solicitation time.
    return fixtures.read_work_package(api, package["id"]), bid


def test_awarding_an_over_budget_package_diverges_the_two_savings_figures(
    api: ApiClient,
) -> None:
    """One underrun then one overrun: the floored figure holds while the signed one falls.

    PRD: "For each work package of the project, the per-package delta is its `budget_amount` minus its `awarded_amount`, so a positive delta is an underrun."

    PRD: "The **trade-level** figure (the `TRADE_LEVEL` variant) floors each package at zero before summing — it is the sum of the greater of the package delta and 0.00 across the included packages — and is written to the project's `buyout_savings_trade_level`."

    PRD: "The **project-net** figure (the `PROJECT_NET` variant) sums every included package delta signed, so overruns offset underruns and the result may be negative; it is written to the project's `buyout_savings_project_net`."

    Design: Difficulty/dual_variant_calc/buyout_savings_trade_level_vs_project_net_divergence
    """
    priced = fixtures.executed_project(api, **RIVERSIDE_DATA_HALL)

    fixtures.awarded_package(
        api,
        priced.id,
        budget_amount=Decimal("5000000.00"),
        base_bid_amount=Decimal("4600000.00"),
        trade_division="03-CONCRETE",
        solicitation_opens_at="2026-08-01T00:00:00Z",
        solicitation_closes_at="2026-08-15T00:00:00Z",
    )
    after_underrun = fixtures.read_project(api, priced.id)
    assert_money_fields(
        after_underrun,
        {
            "buyout_savings_trade_level": Decimal("400000.00"),
            "buyout_savings_project_net": Decimal("400000.00"),
        },
    )

    fixtures.awarded_package(
        api,
        priced.id,
        budget_amount=Decimal("3000000.00"),
        base_bid_amount=Decimal("3250000.00"),
        trade_division="09-FINISHES",
        solicitation_opens_at="2026-08-15T00:00:00Z",
        solicitation_closes_at="2026-08-20T00:00:00Z",
    )
    after_overrun = fixtures.read_project(api, priced.id)
    assert_money_fields(
        after_overrun,
        {
            "buyout_savings_trade_level": Decimal("400000.00"),
            "buyout_savings_project_net": Decimal("150000.00"),
            "gmp_amount": Decimal("46105590.83"),
        },
    )
    assert to_decimal(after_overrun["buyout_savings_trade_level"]) != to_decimal(
        after_overrun["buyout_savings_project_net"]
    ), "the overrun package was not floored out of the trade-level figure"


def test_the_award_writes_the_winning_amount_and_leaves_unbought_packages_out(
    api: ApiClient,
) -> None:
    """Each award copies its bid's lump sum onto the package it bought out.

    PRD: "The award advances the package `SOLICITING → AWARDED`, writes `awarded_bid_id` from the supplied `bid_id` and `awarded_amount` from that bid's `base_bid_amount`, advances the winning bid `OPENED → AWARDED`, and moves **every other** bid on that package that is currently `OPENED` to `NOT_AWARDED`."

    PRD: "Only packages whose `procurement_status` is `AWARDED`, `REPROCUREMENT` or `CLOSED` are included; packages still at `BUDGETED` or `SOLICITING` are excluded outright, because nothing has been bought out yet."

    PRD: "This is the number reported to the owner trade by trade: a package that came in over budget is treated as a separate problem, not as a reduction of the savings already banked on packages that came in under."

    Design: Difficulty/dual_variant_calc/buyout_savings_trade_level_vs_project_net_divergence
    """
    priced = fixtures.executed_project(api, **RIVERSIDE_DATA_HALL)

    concrete = fixtures.awarded_package(
        api,
        priced.id,
        budget_amount=Decimal("5000000.00"),
        base_bid_amount=Decimal("4600000.00"),
        trade_division="03-CONCRETE",
        solicitation_opens_at="2026-08-01T00:00:00Z",
        solicitation_closes_at="2026-08-15T00:00:00Z",
    )
    finishes = fixtures.awarded_package(
        api,
        priced.id,
        budget_amount=Decimal("3000000.00"),
        base_bid_amount=Decimal("3250000.00"),
        trade_division="09-FINISHES",
        solicitation_opens_at="2026-08-15T00:00:00Z",
        solicitation_closes_at="2026-08-20T00:00:00Z",
    )

    assert_fields(
        concrete.package,
        {"procurement_status": "AWARDED", "awarded_bid_id": concrete.bid["id"]},
    )
    assert_money(
        concrete.package["awarded_amount"], Decimal("4600000.00"), "awarded_amount"
    )
    assert_fields(
        finishes.package,
        {"procurement_status": "AWARDED", "awarded_bid_id": finishes.bid["id"]},
    )
    assert_money(
        finishes.package["awarded_amount"], Decimal("3250000.00"), "awarded_amount"
    )
    assert_fields(concrete.bid, {"status": "AWARDED"})
    assert_fields(finishes.bid, {"status": "AWARDED"})

    unbought = fixtures.work_package(
        api,
        priced.id,
        budget_amount=Decimal("900000.00"),
        trade_division="05-STEEL",
    )
    assert_fields(unbought, {"procurement_status": "BUDGETED"})
    after_budgeting = fixtures.read_project(api, priced.id)
    assert_money_fields(
        after_budgeting,
        {
            "buyout_savings_trade_level": Decimal("400000.00"),
            "buyout_savings_project_net": Decimal("150000.00"),
        },
    )


def test_a_subcontract_named_against_a_losing_bid_is_refused(api: ApiClient) -> None:
    """The high bidder sits on the right package but in the wrong bid status.

    PRD: "The named `awarded_bid_id` must reference a bid whose status is already `AWARDED` — a losing `NOT_AWARDED` bid on the same package is rejected with `ERR_BID_STATE_INVALID` (HTTP 409) — and that bid's own `work_package_id` must equal the subcontract's, a mismatch drawing `ERR_WORK_PACKAGE_PROJECT_MISMATCH` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/subcontract_creation_requires_the_named_bid_to_be_the_awarded_one
    """
    package, winner, loser = _southgate_awarded_with_a_losing_bid(api)

    assert_fields(fixtures.read_bid(api, loser["id"]), {"status": "NOT_AWARDED"})
    assert_fields(fixtures.read_bid(api, winner["id"]), {"status": "AWARDED"})

    validate_error(
        api.create_subcontract(
            factories.subcontract_payload(
                package["id"],
                loser["id"],
                package["version"],
                contract_amount=Decimal("980000.00"),
                subcontractor_name="Beta Structural Concrete",
                bond_required=True,
                bond_amount=Decimal("980000.00"),
            ),
            CM_HEADERS,
        ),
        ApiErrorId.BID_STATE_INVALID,
        409,
    )

    rows, meta = validate_paginated(
        api.list_subcontracts(CM_HEADERS, {"work_package_id": package["id"]})
    )
    assert rows == [], "the refused write left a subcontract behind"
    assert meta["total_count"] == 0, "the refused write left a subcontract behind"
    untouched = fixtures.read_work_package(api, package["id"])
    assert untouched["version"] == package["version"], (
        "the refused write moved the work package's version counter"
    )
    assert_money(untouched["committed_amount"], Decimal("0.00"), "committed_amount")


def test_the_retry_with_the_awarded_bid_reuses_the_same_package_version(
    api: ApiClient,
) -> None:
    """Because the refusal wrote nothing, the version the client already held still fits.

    PRD: "Creating a subcontract requires `expected_work_package_version` to equal the target work package's current `version`, and a mismatch is rejected with `ERR_STALE_WORK_PACKAGE_VERSION` (HTTP 412)."

    PRD: "A new subcontract begins with `contract_status` at `ACTIVE`, `paid_to_date` at 0.00, `unpaid_committed_amount` equal to its `contract_amount`, `replacement_cost_amount` at 0.00, `bond_claim_amount` at 0.00, `bond_recovered_amount` at 0.00, `default_notice_at` null and `cure_count` at 0."

    PRD: "Its **surety axis branches on the creation payload**: when `bond_required` is true the `bond_claim_status` is initialised to `NONE`, meaning a claim is possible but has not been filed; when `bond_required` is false it is initialised to `NOT_APPLICABLE`, a terminal dead axis on which no bond-claim action will ever be accepted."

    PRD: "That recount is defined once and used everywhere: a package's `committed_amount` is the sum of `contract_amount` over its subcontracts whose `contract_status` is `ACTIVE`, `DEFAULT_NOTICED` or `COMPLETED`, plus the sum of `paid_to_date` over its subcontracts whose `contract_status` is `TERMINATED_FOR_DEFAULT`."

    Design: Difficulty/cross_entity_state_dependency/subcontract_creation_requires_the_named_bid_to_be_the_awarded_one
    """
    package, winner, loser = _southgate_awarded_with_a_losing_bid(api)
    held_version = package["version"]

    validate_error(
        api.create_subcontract(
            factories.subcontract_payload(
                package["id"],
                loser["id"],
                held_version,
                contract_amount=Decimal("980000.00"),
                bond_required=True,
                bond_amount=Decimal("980000.00"),
            ),
            CM_HEADERS,
        ),
        ApiErrorId.BID_STATE_INVALID,
        409,
    )

    created = validate_success(
        api.create_subcontract(
            factories.subcontract_payload(
                package["id"],
                winner["id"],
                held_version,
                contract_amount=Decimal("950000.00"),
                subcontractor_name="Alpha Concrete Contractors",
                bond_required=True,
                bond_amount=Decimal("950000.00"),
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_fields(
        created,
        {
            "contract_status": "ACTIVE",
            "awarded_bid_id": winner["id"],
            "bond_claim_status": "NONE",
            "cure_count": 0,
            "default_notice_at": None,
        },
    )
    assert_money_fields(
        created,
        {
            "paid_to_date": Decimal("0.00"),
            "unpaid_committed_amount": Decimal("950000.00"),
            "replacement_cost_amount": Decimal("0.00"),
            "bond_claim_amount": Decimal("0.00"),
            "bond_recovered_amount": Decimal("0.00"),
        },
    )

    package_after = fixtures.read_work_package(api, package["id"])
    assert_money_fields(
        package_after,
        {
            "awarded_amount": Decimal("950000.00"),
            "committed_amount": Decimal("950000.00"),
        },
    )
    rows, meta = validate_paginated(
        api.list_subcontracts(CM_HEADERS, {"work_package_id": package["id"]})
    )
    assert meta["total_count"] == 1, "the package carries more than one subcontract"
    single_row(rows, "id", created["id"])


def test_opening_a_self_perform_bid_reports_the_disclosure_gate_first(
    api: ApiClient,
) -> None:
    """Two conditions fail at once and the open-book gate is the earlier of the two.

    PRD: "A bid whose `bidder_type` is `CM_SELF_PERFORM` may only be opened once the package's `transparency_status` has reached `DISCLOSED` or `AUDITED`, and opening one while the package is still `SEALED` is rejected with `ERR_OPEN_BOOK_DISCLOSURE_REQUIRED` (HTTP 422); third-party bids are exempt, because the gate exists specifically for the case where the construction manager is bidding against the trades it also administers."

    PRD: "10. Open-book compliance — the disclosure gate `ERR_OPEN_BOOK_DISCLOSURE_REQUIRED`, then the breakdown-arithmetic check `ERR_OPEN_BOOK_BREAKDOWN_MISMATCH`."

    PRD: "A sealed bid's breakdown is suppressed on read: `open_book_cost_breakdown` is populated in responses only for bids whose status is `OPENED`, `AWARDED` or `NOT_AWARDED`, and reads as null while the bid is still `SEALED`."

    Design: Difficulty/priority_pair_validation_conflict/open_book_disclosure_priority_81_outranks_solicitation_still_open_priority_100
    """
    package, bid = _self_perform_bid_awaiting_disclosure(api)
    assert_fields(package, {"transparency_status": "SEALED", "bid_count": 1})

    validate_error(
        api.open_bid(bid["id"], PO_HEADERS),
        ApiErrorId.OPEN_BOOK_DISCLOSURE_REQUIRED,
        422,
    )

    rows, _ = validate_paginated(
        api.list_bids(PO_HEADERS, {"work_package_id": package["id"]})
    )
    still_sealed = single_row(rows, "id", bid["id"])
    assert_fields(
        still_sealed,
        {
            "status": "SEALED",
            "open_book_cost_breakdown": None,
            "opened_by_user_id": None,
            "opened_at": None,
        },
    )


def test_disclosing_the_package_unmasks_the_solicitation_window_refusal(
    api: ApiClient,
) -> None:
    """With the open-book gate satisfied, the clock is what still stands in the way.

    PRD: "A `ProcurementOfficer` publishes the cost breakdowns to the owner by naming `target_status` `DISCLOSED`, advancing the package `SEALED → DISCLOSED`; this requires the package to have attracted at least one bid, that is `bid_count` of 1 or more."

    PRD: "The logical clock must have reached the package's `solicitation_closes_at`, with an inclusive boundary — a clock reading exactly equal to the close instant is permitted — and an earlier reading is rejected with `ERR_SOLICITATION_STILL_OPEN` (HTTP 409)."

    PRD: "Neither axis constrains the other's position: a package may be `DISCLOSED` while still `BUDGETED`, or while already `CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/open_book_disclosure_priority_81_outranks_solicitation_still_open_priority_100
    """
    package, bid = _self_perform_bid_awaiting_disclosure(api)

    disclosed = validate_success(
        api.set_transparency(
            package["id"], factories.transparency_payload("DISCLOSED"), PO_HEADERS
        )
    )
    assert_fields(
        disclosed,
        {"transparency_status": "DISCLOSED", "procurement_status": "SOLICITING"},
    )

    validate_error(
        api.open_bid(bid["id"], PO_HEADERS),
        ApiErrorId.SOLICITATION_STILL_OPEN,
        409,
    )
    assert_fields(fixtures.read_bid(api, bid["id"]), {"status": "SEALED"})


def test_at_the_inclusive_close_instant_the_disclosed_self_perform_bid_opens(
    api: ApiClient,
) -> None:
    """A clock reading exactly equal to the close instant is permitted.

    PRD: "A successful open advances the bid `SEALED → OPENED`, records `opened_by_user_id` from the acting `X-User-ID` and `opened_at` from the logical clock, and increments the bid's `version`."

    PRD: "**The five components must sum exactly to `base_bid_amount`**; any discrepancy is rejected with `ERR_OPEN_BOOK_BREAKDOWN_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/open_book_disclosure_priority_81_outranks_solicitation_still_open_priority_100
    """
    package, bid = _self_perform_bid_awaiting_disclosure(api)
    validate_success(
        api.set_transparency(
            package["id"], factories.transparency_payload("DISCLOSED"), PO_HEADERS
        )
    )
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")

    opened = validate_success(api.open_bid(bid["id"], PO_HEADERS))
    assert_fields(
        opened,
        {
            "status": "OPENED",
            "opened_by_user_id": user_id_of("procurement_officer"),
            "bidder_type": "CM_SELF_PERFORM",
        },
    )
    assert_instant(opened["opened_at"], "2026-08-20T00:00:00Z", "opened_at")

    breakdown = opened["open_book_cost_breakdown"]
    assert breakdown is not None, "an opened bid must publish its open-book breakdown"
    components = sum(
        to_decimal(breakdown[part], part)
        for part in ("labor", "material", "equipment", "overhead", "profit")
    )
    assert_money(components, Decimal("170000.00"), "open-book component total")
    assert_money(opened["base_bid_amount"], Decimal("170000.00"), "base_bid_amount")
