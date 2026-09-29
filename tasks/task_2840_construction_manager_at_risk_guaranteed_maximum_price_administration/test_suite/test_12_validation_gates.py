"""The gates that refuse a request, and the boundaries where they stop refusing it.

Each gate here is a comparison the contract pins one way rather than the other: non-strict on
remaining units, inclusive on the solicitation close, strict on the allowance rate, strict on
milestone rank, and exact on the open-book components. A rejection must also leave nothing
behind, so every refusal is followed by a read that proves the row never moved.
"""

from decimal import Decimal
from typing import Any, Optional, Tuple

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    AUDITOR_HEADERS,
    CM_HEADERS,
    NO_AUTH_HEADERS,
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
    user_id_of,
)
from test_helpers.types import JsonObject

CLINIC_KWARGS = {
    "project_kwargs": {"name": "Harborview Clinic", "owner_org": "Harborview Health"}
}

ABSENT_PROJECT_ID = "00000000-0000-0000-0000-000000000000"
SOLICITATION_OPENS = "2026-08-01T00:00:00Z"
SOLICITATION_CLOSES = "2026-08-15T00:00:00Z"
ONE_SECOND_EARLY = "2026-08-14T23:59:59Z"


def _hard_rock_allowance(api: ApiClient) -> JsonObject:
    """A 90,000.00 allowance over 1500 CY, so the carried rate is exactly 60.0000."""
    priced = fixtures.draft_priced_project(api, **CLINIC_KWARGS)
    return fixtures.allowance_item(
        api,
        priced.proposal["id"],
        allowance_amount=Decimal("90000.00"),
        allocated_units=Decimal("1500.00"),
        unit_of_measure="CY",
        text="hard rock excavation allowance",
    )


def _book(
    api: ApiClient,
    item_id: str,
    units: Decimal,
    actual_unit_cost: Decimal,
    overrun_authorized: Optional[bool] = None,
) -> Any:
    """Post one RECONCILE booking against an allowance, returning the raw response."""
    return api.reconcile_allowance(
        item_id,
        factories.allowance_reconcile_payload(
            units, actual_unit_cost, overrun_authorized=overrun_authorized
        ),
        CM_HEADERS,
    )


def _allowance_with_four_hundred_booked(api: ApiClient) -> JsonObject:
    """The same allowance after 400 CY have been bought at 55.0000, under the rate."""
    item = _hard_rock_allowance(api)
    return validate_success(
        _book(api, item["id"], Decimal("400.00"), Decimal("55.0000"))
    )


def _concrete_market(
    api: ApiClient, self_perform_intent: bool = False
) -> Tuple[str, JsonObject]:
    """An executed clinic whose concrete package is soliciting until 2026-08-15."""
    priced = fixtures.executed_project(api, **CLINIC_KWARGS)
    package = fixtures.soliciting_package(
        api,
        priced.id,
        budget_amount=Decimal("500000.00"),
        trade_division="03-CONCRETE",
        self_perform_intent=self_perform_intent,
        solicitation_opens_at=SOLICITATION_OPENS,
        solicitation_closes_at=SOLICITATION_CLOSES,
    )
    return priced.id, package


def test_a_booking_beyond_the_remaining_units_is_refused_not_clamped(
    api: ApiClient,
) -> None:
    """1200 CY booked against 1100 remaining: the ledger must not be trimmed to fit.

    PRD: "A booking proceeds as follows: the requested `units` must not exceed the item's current `remaining_units`, and a request for more is rejected with `ERR_ALLOWANCE_UNITS_EXCEEDED` (HTTP 422); if the `actual_unit_cost` exceeds the item's `allowance_unit_rate`, the request must carry `overrun_authorized` set to true, acknowledging that the difference will be routed through a change event, and its absence is rejected with `ERR_ALLOWANCE_OVERRUN_UNAUTHORIZED` (HTTP 422)."

    PRD: "**The invariant, asserted after every action of either kind, is that `allocated_units` equals `remaining_units` plus `reconciled_units`.**"

    PRD: "Every action of either kind increments the item's `version` by 1."

    Design: Corner/validations/allowance_reconcile_beyond_remaining_units_is_rejected
    """
    booked = _allowance_with_four_hundred_booked(api)
    assert_money_fields(
        booked,
        {
            "remaining_units": Decimal("1100.00"),
            "reconciled_units": Decimal("400.00"),
            "reconciled_amount": Decimal("22000.00"),
        },
    )
    settled_version = booked["version"]

    validate_error(
        _book(api, booked["id"], Decimal("1200.00"), Decimal("55.0000")),
        ApiErrorId.ALLOWANCE_UNITS_EXCEEDED,
        422,
    )

    unmoved = fixtures.read_qualification_item(api, booked["id"])
    assert_money_fields(
        unmoved,
        {
            "remaining_units": Decimal("1100.00"),
            "reconciled_units": Decimal("400.00"),
            "reconciled_amount": Decimal("22000.00"),
            "allocated_units": Decimal("1500.00"),
        },
    )
    assert_fields(
        unmoved,
        {
            "status": "PARTIALLY_RECONCILED",
            "last_action": "RECONCILE",
            "version": settled_version,
        },
    )
    assert_equals(unmoved, "reconciliation_seq", 1)
    assert_allowance_ledger_invariant(unmoved)


def test_a_booking_of_exactly_the_remaining_units_closes_the_ledger(
    api: ApiClient,
) -> None:
    """The units check is non-strict, so the last 1100 CY are bookable in one call.

    PRD: "A booking proceeds as follows: the requested `units` must not exceed the item's current `remaining_units`, and a request for more is rejected with `ERR_ALLOWANCE_UNITS_EXCEEDED` (HTTP 422); if the `actual_unit_cost` exceeds the item's `allowance_unit_rate`, the request must carry `overrun_authorized` set to true, acknowledging that the difference will be routed through a change event, and its absence is rejected with `ERR_ALLOWANCE_OVERRUN_UNAUTHORIZED` (HTTP 422)."

    PRD: "After either action, the item's `status` is re-derived from the ledger rather than transitioned by hand: it is `OPEN` when `reconciled_units` is 0, `FULLY_RECONCILED` when `reconciled_units` equals `allocated_units`, and `PARTIALLY_RECONCILED` in between."

    PRD: "Bookings therefore drive `OPEN → PARTIALLY_RECONCILED`, `PARTIALLY_RECONCILED → FULLY_RECONCILED`, and — when a single call consumes every allocated unit at once — `OPEN → FULLY_RECONCILED`."

    PRD: "A successful booking moves four fields together: `reconciled_units` increases by the booked units, `remaining_units` decreases by the same units, `reconciled_amount` increases by the booked dollars — the units multiplied by the `actual_unit_cost`, rounded half-up to 2 decimal places — and `variance_amount` is rewritten as the item's `reconciled_amount` less the expected dollars at the carried rate, where the expected figure is `reconciled_units` multiplied by `allowance_unit_rate`, rounded half-up to 2 decimal places."

    PRD: "The booking also increments `reconciliation_seq` by 1 and records `last_action` as `RECONCILE`."

    Design: Corner/validations/allowance_reconcile_of_exactly_the_remaining_units_is_accepted
    """
    booked = _allowance_with_four_hundred_booked(api)

    closed = validate_success(
        _book(api, booked["id"], Decimal("1100.00"), Decimal("60.0000"))
    )
    assert_money_fields(
        closed,
        {
            "remaining_units": Decimal("0.00"),
            "reconciled_units": Decimal("1500.00"),
            "reconciled_amount": Decimal("88000.00"),
            "variance_amount": Decimal("-2000.00"),
            "allocated_units": Decimal("1500.00"),
        },
    )
    assert_fields(closed, {"status": "FULLY_RECONCILED", "last_action": "RECONCILE"})
    assert_equals(closed, "reconciliation_seq", 2)
    assert_allowance_ledger_invariant(closed)


def test_the_overrun_acknowledgement_is_required_only_above_the_carried_rate(
    api: ApiClient,
) -> None:
    """At 60.0000 the flag may be omitted; a ten-thousandth higher it may not.

    PRD: "A booking proceeds as follows: the requested `units` must not exceed the item's current `remaining_units`, and a request for more is rejected with `ERR_ALLOWANCE_UNITS_EXCEEDED` (HTTP 422); if the `actual_unit_cost` exceeds the item's `allowance_unit_rate`, the request must carry `overrun_authorized` set to true, acknowledging that the difference will be routed through a change event, and its absence is rejected with `ERR_ALLOWANCE_OVERRUN_UNAUTHORIZED` (HTTP 422)."

    PRD: "Unit-rate inputs — a cost line's `unit_rate` and an allowance reconciliation's `actual_unit_cost` — are likewise non-negative decimals with at most 4 decimal places."

    PRD: "A positive `variance_amount` means the allowance is overrunning."

    PRD: "The booking also increments `reconciliation_seq` by 1 and records `last_action` as `RECONCILE`."

    Design: Corner/validations/allowance_overrun_requires_explicit_authorization_only_when_the_rate_is_exceeded
    """
    item = _hard_rock_allowance(api)
    assert_ratio(item["allowance_unit_rate"], Decimal("60.0000"), "allowance_unit_rate")

    at_the_rate = validate_success(
        _book(api, item["id"], Decimal("100.00"), Decimal("60.0000"))
    )
    assert_money_fields(
        at_the_rate,
        {
            "reconciled_amount": Decimal("6000.00"),
            "variance_amount": Decimal("0.00"),
            "reconciled_units": Decimal("100.00"),
        },
    )
    assert_equals(at_the_rate, "reconciliation_seq", 1)

    validate_error(
        _book(api, item["id"], Decimal("100.00"), Decimal("60.0001")),
        ApiErrorId.ALLOWANCE_OVERRUN_UNAUTHORIZED,
        422,
    )
    unmoved = fixtures.read_qualification_item(api, item["id"])
    assert_money(
        unmoved["reconciled_units"], Decimal("100.00"), "reconciled_units"
    )
    assert_equals(unmoved, "reconciliation_seq", 1)

    acknowledged = validate_success(
        _book(
            api,
            item["id"],
            Decimal("100.00"),
            Decimal("60.0001"),
            overrun_authorized=True,
        )
    )
    assert_money_fields(
        acknowledged,
        {
            "reconciled_units": Decimal("200.00"),
            "reconciled_amount": Decimal("12000.01"),
            "variance_amount": Decimal("0.01"),
        },
    )
    assert_equals(acknowledged, "reconciliation_seq", 2)
    assert_fields(acknowledged, {"status": "PARTIALLY_RECONCILED"})
    assert_allowance_ledger_invariant(acknowledged)


def test_the_precedence_table_is_walked_before_the_project_is_looked_up(
    api: ApiClient,
) -> None:
    """An absent project reports 401 then 403; a real one reports shape before state.

    PRD: "When a single request could fail several ways, the system reports the failure that comes first in the following order, and stops."

    PRD: "The ordering matters because it decides which error identifier a client sees; a later check must never mask an earlier one."

    PRD: "1. Header presence and role recognition — `ERR_UNAUTHENTICATED`."

    PRD: "2. Endpoint-level role authority — `ERR_UNAUTHORIZED`."

    PRD: "5. Existence of identifiers in the path, resolved left to right, per §2.9."

    PRD: "A request from any status other than `NOT_REQUESTED` is rejected with `ERR_AUDIT_STATE_INVALID` (HTTP 409)."

    PRD: "Either action from a status that does not permit it is rejected with `ERR_AUDIT_STATE_INVALID` (HTTP 409), and each increments the project's `version` by 1."

    Design: Corner/validations/error_precedence_unauthenticated_then_unauthorized_then_invalid_request
    """
    project = fixtures.create_project(
        api, name="Harborview Clinic", owner_org="Harborview Health"
    )

    validate_error(
        api.request_audit(ABSENT_PROJECT_ID, NO_AUTH_HEADERS),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.request_audit(ABSENT_PROJECT_ID, AUDITOR_HEADERS),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.audit_action(
            project["id"],
            factories.audit_action_payload("NOT_AN_ACTION"),
            AUDITOR_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.audit_action(
            project["id"], factories.audit_action_payload("CLOSE"), AUDITOR_HEADERS
        ),
        ApiErrorId.AUDIT_STATE_INVALID,
        409,
    )

    untouched = fixtures.read_project(api, project["id"])
    assert_project_axes(untouched, audit_status="NOT_REQUESTED")
    assert_money(
        untouched["audit_adjustment_total"],
        Decimal("0.00"),
        "audit_adjustment_total",
    )
    assert_equals(untouched, "version", project["version"])


def test_the_solicitation_close_is_an_inclusive_boundary_for_unsealing(
    api: ApiClient,
) -> None:
    """One second early the envelope stays sealed; on the exact instant it opens.

    PRD: "The logical clock must have reached the package's `solicitation_closes_at`, with an inclusive boundary — a clock reading exactly equal to the close instant is permitted — and an earlier reading is rejected with `ERR_SOLICITATION_STILL_OPEN` (HTTP 409)."

    PRD: "The bid must be `SEALED`, and a bid in any other status is rejected with `ERR_BID_STATE_INVALID` (HTTP 409)."

    PRD: "A successful open advances the bid `SEALED → OPENED`, records `opened_by_user_id` from the acting `X-User-ID` and `opened_at` from the logical clock, and increments the bid's `version`."

    PRD: "A bid is minted at `SEALED` with `prepared_by_user_id` taken from the submitting operator's `X-User-ID`, `opened_by_user_id` null and `opened_at` null; the parent package's `bid_count` increases by 1 and its `version` increments."

    PRD: "That breakdown is an object of five components — `labor`, `material`, `equipment`, `overhead` and `profit` — and it is required when `bidder_type` is `CM_SELF_PERFORM` and must be null when `bidder_type` is `THIRD_PARTY`."

    Design: Corner/validations/bid_opening_before_the_solicitation_closes_is_rejected_and_the_boundary_is_inclusive
    """
    _, package = _concrete_market(api)
    bid = fixtures.third_party_bid(
        api,
        package["id"],
        base_bid_amount=Decimal("460000.00"),
        bidder_name="Cascade Concrete",
    )
    assert_fields(
        bid,
        {
            "status": "SEALED",
            "opened_by_user_id": None,
            "opened_at": None,
            "open_book_cost_breakdown": None,
        },
    )

    validate_error(
        api.open_bid(bid["id"], PO_HEADERS),
        ApiErrorId.SOLICITATION_STILL_OPEN,
        409,
    )
    fixtures.set_clock(api, ONE_SECOND_EARLY)
    validate_error(
        api.open_bid(bid["id"], PO_HEADERS),
        ApiErrorId.SOLICITATION_STILL_OPEN,
        409,
    )
    still_sealed = fixtures.read_bid(api, bid["id"])
    assert_fields(still_sealed, {"status": "SEALED", "opened_at": None})

    fixtures.set_clock(api, SOLICITATION_CLOSES)
    opened = validate_success(api.open_bid(bid["id"], PO_HEADERS))
    assert_fields(
        opened,
        {
            "status": "OPENED",
            "opened_by_user_id": user_id_of("procurement_officer"),
            "open_book_cost_breakdown": None,
        },
    )
    assert_instant(opened["opened_at"], SOLICITATION_CLOSES, "opened_at")


def test_the_five_open_book_components_must_sum_to_the_cent(api: ApiClient) -> None:
    """A one-cent shortfall in the breakdown is refused and files nothing.

    PRD: "**The five components must sum exactly to `base_bid_amount`**; any discrepancy is rejected with `ERR_OPEN_BOOK_BREAKDOWN_MISMATCH` (HTTP 422)."

    PRD: "That breakdown is an object of five components — `labor`, `material`, `equipment`, `overhead` and `profit` — and it is required when `bidder_type` is `CM_SELF_PERFORM` and must be null when `bidder_type` is `THIRD_PARTY`."

    PRD: "A bid is minted at `SEALED` with `prepared_by_user_id` taken from the submitting operator's `X-User-ID`, `opened_by_user_id` null and `opened_at` null; the parent package's `bid_count` increases by 1 and its `version` increments."

    PRD: "10. Open-book compliance — the disclosure gate `ERR_OPEN_BOOK_DISCLOSURE_REQUIRED`, then the breakdown-arithmetic check `ERR_OPEN_BOOK_BREAKDOWN_MISMATCH`."

    Design: Corner/validations/open_book_breakdown_must_sum_exactly_to_the_base_bid_amount
    """
    _, package = _concrete_market(api, self_perform_intent=True)
    assert_equals(package, "bid_count", 0)

    validate_error(
        api.create_bid(
            factories.self_perform_bid_payload(
                package["id"],
                base_bid_amount=Decimal("460000.00"),
                bidder_name="CMAR Concrete Division",
                open_book_cost_breakdown=factories.open_book_breakdown(
                    Decimal("200000.00"),
                    Decimal("180000.00"),
                    Decimal("40000.00"),
                    Decimal("25000.00"),
                    Decimal("14999.99"),
                ),
            ),
            CM_HEADERS,
        ),
        ApiErrorId.OPEN_BOOK_BREAKDOWN_MISMATCH,
        422,
    )
    assert_equals(fixtures.read_work_package(api, package["id"]), "bid_count", 0)

    filed = validate_success(
        api.create_bid(
            factories.self_perform_bid_payload(
                package["id"],
                base_bid_amount=Decimal("460000.00"),
                bidder_name="CMAR Concrete Division",
                open_book_cost_breakdown=factories.open_book_breakdown(
                    Decimal("200000.00"),
                    Decimal("180000.00"),
                    Decimal("40000.00"),
                    Decimal("25000.00"),
                    Decimal("15000.00"),
                ),
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_fields(
        filed,
        {
            "status": "SEALED",
            "bidder_type": "CM_SELF_PERFORM",
            "prepared_by_user_id": user_id_of("cm_estimator"),
        },
    )
    assert_equals(fixtures.read_work_package(api, package["id"]), "bid_count", 1)


def test_a_declared_predecessor_must_sit_at_a_strictly_earlier_milestone(
    api: ApiClient,
) -> None:
    """DD may not be priced against DD, nor SD against DD; CD_50 against DD is fine.

    PRD: "A declared `prior_estimate_id` must have a `milestone_rank` strictly lower than the estimate being created."

    PRD: "Declaring a predecessor at the same or a later design milestone is rejected with `ERR_MILESTONE_RANK_REGRESSION` (HTTP 422) — a milestone may not be priced against a later or equal milestone."

    PRD: "The milestone codes, in ascending design maturity, are `SD`, `DD`, `CD_50`, `CD_100` and `GMP_BASIS`; the server stamps a `milestone_rank` on the row from a fixed ranking in which `SD` ranks 1, `DD` ranks 2, `CD_50` ranks 3, `CD_100` ranks 4 and `GMP_BASIS` ranks 5."

    PRD: "If `prior_estimate_id` was supplied, that estimate is the basis and `variance_basis` is recorded as `DECLARED_PRIOR`."

    PRD: "Whenever a basis is selected, `variance_basis_estimate_id` records that basis row's identifier and `variance_pct` is the basis-relative signed ratio: the new estimate's `submitted_cost_of_work` less the basis estimate's `submitted_cost_of_work`, divided by the basis estimate's `submitted_cost_of_work`, rounded half-up to 4 decimal places."

    PRD: "Estimates already at `RECONCILED` are never superseded; they remain the reconciliation basis for everything downstream."

    Design: Corner/validations/declared_prior_estimate_of_an_equal_or_later_milestone_is_rejected
    """
    project = fixtures.create_project(
        api, name="Harborview Clinic", owner_org="Harborview Health"
    )
    design_development = fixtures.reconciled_estimate(
        api,
        project["id"],
        milestone_code="DD",
        submitted_cost_of_work=Decimal("1000000.00"),
    )
    token = fixtures.project_version(api, project["id"])

    validate_error(
        api.create_estimate(
            factories.estimate_payload(
                project["id"],
                token,
                milestone_code="SD",
                submitted_cost_of_work=Decimal("950000.00"),
                prior_estimate_id=design_development["id"],
            ),
            CM_HEADERS,
        ),
        ApiErrorId.MILESTONE_RANK_REGRESSION,
        422,
    )
    validate_error(
        api.create_estimate(
            factories.estimate_payload(
                project["id"],
                token,
                milestone_code="DD",
                submitted_cost_of_work=Decimal("1050000.00"),
                prior_estimate_id=design_development["id"],
            ),
            CM_HEADERS,
        ),
        ApiErrorId.MILESTONE_RANK_REGRESSION,
        422,
    )

    accepted = validate_success(
        api.create_estimate(
            factories.estimate_payload(
                project["id"],
                token,
                milestone_code="CD_50",
                submitted_cost_of_work=Decimal("1050000.00"),
                prior_estimate_id=design_development["id"],
            ),
            CM_HEADERS,
        ),
        201,
    )
    assert_fields(
        accepted,
        {
            "milestone_rank": 3,
            "variance_basis": "DECLARED_PRIOR",
            "variance_basis_estimate_id": design_development["id"],
        },
    )
    assert_ratio(accepted["variance_pct"], Decimal("0.0500"), "variance_pct")

    basis = fixtures.read_estimate(api, design_development["id"])
    assert_fields(
        basis, {"status": "RECONCILED", "superseded_by_estimate_id": None}
    )
