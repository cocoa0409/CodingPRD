"""The allowance's own little ledger, and the reversal that undoes all of it but one field.

An allowance carries dollars and a quantity, so booking actuals against it moves four
fields at once. The compensating reversal backs every one of them out — and deliberately
leaves the audit counter where it was.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CM_HEADERS,
    OWNER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_allowance_ledger_invariant,
    assert_equals,
    assert_fields,
    assert_money,
    assert_money_fields,
    assert_ratio,
    factories,
    fixtures,
)
from test_helpers.types import JsonObject

HARBORVIEW_CLINIC = {
    "project_kwargs": {
        "name": "Harborview Clinic",
        "owner_org": "Harborview Health",
        "precon_fee_amount": Decimal("25000.00"),
    }
}

TERRAZZO_TEXT = "decorative terrazzo flooring at the lobby"


def _harborview_terrazzo_allowance(api: ApiClient) -> JsonObject:
    """A 60,000.00 allowance over 1200 SF, logged while the proposal was still editable."""
    priced = fixtures.draft_priced_project(api, **HARBORVIEW_CLINIC)
    item = fixtures.allowance_item(
        api,
        priced.proposal["id"],
        allowance_amount=Decimal("60000.00"),
        allocated_units=Decimal("1200.00"),
        unit_of_measure="SF",
        text=TERRAZZO_TEXT,
    )
    validate_success(api.submit_gmp_proposal(priced.proposal["id"], CM_HEADERS))
    validate_success(
        api.decide_gmp_proposal(
            priced.proposal["id"],
            factories.proposal_decision_payload("EXECUTE"),
            OWNER_HEADERS,
        )
    )
    return item


def test_the_reversal_puts_all_four_ledger_fields_back_exactly(api: ApiClient) -> None:
    """One overrunning booking, then the compensating move that undoes all of it.

    PRD: "From those two numbers the server derives `allowance_unit_rate` as `allowance_amount` divided by `allocated_units`, rounded half-up to 4 decimal places, and opens the ledger with `remaining_units` equal to `allocated_units`, `reconciled_units` at 0.00, `reconciled_amount` at 0.00, `variance_amount` at 0.00, `reconciliation_seq` at 0, `last_action` at `NONE` and `status` at `OPEN`."

    PRD: "A successful booking moves four fields together: `reconciled_units` increases by the booked units, `remaining_units` decreases by the same units, `reconciled_amount` increases by the booked dollars — the units multiplied by the `actual_unit_cost`, rounded half-up to 2 decimal places — and `variance_amount` is rewritten as the item's `reconciled_amount` less the expected dollars at the carried rate, where the expected figure is `reconciled_units` multiplied by `allowance_unit_rate`, rounded half-up to 2 decimal places."

    PRD: "The compensating move supplies an `action` of `REVERSE`, which undoes the most recent booking and only the most recent booking: exactly the four field movements of that last `RECONCILE` are backed out, so `remaining_units` rises by the reversed units, `reconciled_units` falls by them, `reconciled_amount` falls by the reversed booking, and `variance_amount` is recomputed on the restored figures."

    PRD: "**The invariant, asserted after every action of either kind, is that `allocated_units` equals `remaining_units` plus `reconciled_units`.**"

    Design: Difficulty/compensating_invariant/allowance_reconcile_then_reverse_restores_the_unit_ledger_but_not_the_sequence
    """
    item = _harborview_terrazzo_allowance(api)
    assert_ratio(item["allowance_unit_rate"], Decimal("50.0000"), "allowance_unit_rate")
    assert_fields(item, {"status": "OPEN", "last_action": "NONE"})
    assert_equals(item, "reconciliation_seq", 0)
    assert_money_fields(
        item,
        {
            "remaining_units": Decimal("1200.00"),
            "reconciled_units": Decimal("0.00"),
            "reconciled_amount": Decimal("0.00"),
            "variance_amount": Decimal("0.00"),
        },
    )
    assert_allowance_ledger_invariant(item)

    booked = validate_success(
        api.reconcile_allowance(
            item["id"],
            factories.allowance_reconcile_payload(
                Decimal("500.00"), Decimal("58.0000"), overrun_authorized=True
            ),
            CM_HEADERS,
        )
    )
    assert_money_fields(
        booked,
        {
            "reconciled_units": Decimal("500.00"),
            "remaining_units": Decimal("700.00"),
            "reconciled_amount": Decimal("29000.00"),
            "variance_amount": Decimal("4000.00"),
        },
    )
    assert_fields(booked, {"status": "PARTIALLY_RECONCILED", "last_action": "RECONCILE"})
    assert_allowance_ledger_invariant(booked)

    reversed_item = validate_success(
        api.reconcile_allowance(
            item["id"], factories.allowance_reverse_payload(), CM_HEADERS
        )
    )
    assert_money_fields(
        reversed_item,
        {
            "remaining_units": Decimal("1200.00"),
            "reconciled_units": Decimal("0.00"),
            "reconciled_amount": Decimal("0.00"),
            "variance_amount": Decimal("0.00"),
        },
    )
    assert_allowance_ledger_invariant(reversed_item)


def test_the_status_is_rederived_from_the_ledger_on_the_way_back_to_open(
    api: ApiClient,
) -> None:
    """A partially reconciled allowance returns to OPEN because its booked units are 0.

    PRD: "After either action, the item's `status` is re-derived from the ledger rather than transitioned by hand: it is `OPEN` when `reconciled_units` is 0, `FULLY_RECONCILED` when `reconciled_units` equals `allocated_units`, and `PARTIALLY_RECONCILED` in between."

    PRD: "Every action of either kind increments the item's `version` by 1."

    PRD: "if the `actual_unit_cost` exceeds the item's `allowance_unit_rate`, the request must carry `overrun_authorized` set to true, acknowledging that the difference will be routed through a change event, and its absence is rejected with `ERR_ALLOWANCE_OVERRUN_UNAUTHORIZED` (HTTP 422)."

    Design: Difficulty/compensating_invariant/allowance_reconcile_then_reverse_restores_the_unit_ledger_but_not_the_sequence
    """
    item = _harborview_terrazzo_allowance(api)
    opened_version = item["version"]

    validate_error(
        api.reconcile_allowance(
            item["id"],
            factories.allowance_reconcile_payload(
                Decimal("500.00"), Decimal("58.0000")
            ),
            CM_HEADERS,
        ),
        ApiErrorId.ALLOWANCE_OVERRUN_UNAUTHORIZED,
        422,
    )
    assert_fields(
        fixtures.read_qualification_item(api, item["id"]),
        {"status": "OPEN", "last_action": "NONE", "version": opened_version},
    )

    booked = validate_success(
        api.reconcile_allowance(
            item["id"],
            factories.allowance_reconcile_payload(
                Decimal("500.00"), Decimal("58.0000"), overrun_authorized=True
            ),
            CM_HEADERS,
        )
    )
    assert_fields(
        booked,
        {"status": "PARTIALLY_RECONCILED", "version": opened_version + 1},
    )

    reversed_item = validate_success(
        api.reconcile_allowance(
            item["id"], factories.allowance_reverse_payload(), CM_HEADERS
        )
    )
    assert_fields(
        reversed_item, {"status": "OPEN", "version": opened_version + 2}
    )
    assert_money(
        reversed_item["reconciled_units"], Decimal("0.00"), "reconciled_units"
    )


def test_the_sequence_counter_does_not_rewind_and_the_reversal_is_not_repeatable(
    api: ApiClient,
) -> None:
    """The audit counter counts bookings ever posted, so a second reversal has nothing to name.

    PRD: "Crucially, `reconciliation_seq` is **not** decremented by a reversal: it counts every `RECONCILE` ever posted, and it is the sequence number a reversal names as the booking it undoes."

    PRD: "A reversal requires `last_action` to be `RECONCILE` and `reconciliation_seq` to be at least 1; a reversal cannot itself be reversed, an untouched allowance cannot be reversed, and a non-allowance item cannot be reversed — all three are rejected with `ERR_ALLOWANCE_REVERSAL_INVALID` (HTTP 422)."

    PRD: "The booking also increments `reconciliation_seq` by 1 and records `last_action` as `RECONCILE`."

    PRD: "`last_action` becomes `REVERSE`."

    Design: Difficulty/compensating_invariant/allowance_reconcile_then_reverse_restores_the_unit_ledger_but_not_the_sequence
    """
    item = _harborview_terrazzo_allowance(api)

    booked = validate_success(
        api.reconcile_allowance(
            item["id"],
            factories.allowance_reconcile_payload(
                Decimal("500.00"), Decimal("58.0000"), overrun_authorized=True
            ),
            CM_HEADERS,
        )
    )
    assert_equals(booked, "reconciliation_seq", 1)
    assert_fields(booked, {"last_action": "RECONCILE"})

    reversed_item = validate_success(
        api.reconcile_allowance(
            item["id"], factories.allowance_reverse_payload(), CM_HEADERS
        )
    )
    assert_equals(reversed_item, "reconciliation_seq", 1)
    assert_fields(reversed_item, {"last_action": "REVERSE"})

    validate_error(
        api.reconcile_allowance(
            item["id"], factories.allowance_reverse_payload(), CM_HEADERS
        ),
        ApiErrorId.ALLOWANCE_REVERSAL_INVALID,
        422,
    )

    settled = fixtures.read_qualification_item(api, item["id"])
    assert_equals(settled, "reconciliation_seq", 1)
    assert_fields(
        settled,
        {
            "last_action": "REVERSE",
            "status": "OPEN",
            "item_type": "ALLOWANCE",
            "unit_of_measure": "SF",
        },
    )
    assert_money_fields(
        settled,
        {
            "allowance_amount": Decimal("60000.00"),
            "allocated_units": Decimal("1200.00"),
            "remaining_units": Decimal("1200.00"),
            "reconciled_units": Decimal("0.00"),
            "reconciled_amount": Decimal("0.00"),
            "variance_amount": Decimal("0.00"),
        },
    )
    assert_allowance_ledger_invariant(settled)
