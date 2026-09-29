"""Optimistic concurrency guards and the derived-figure reconciliation after execute."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_RMA_INVALID_STATE,
    ERR_STALE_RETURN_LINE_VERSION,
    ERR_STALE_RMA_VERSION,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_money,
    assert_pct_equals,
    expected_recovery_credit,
    sole_entry_of_type,
)
from test_helpers.constants import (
    CHANNEL_TYPE_BULK_LIQUIDATOR,
    DISPOSITION_DONATE,
    DISPOSITION_LIQUIDATE,
    DO_EXECUTED,
    DS_DISPOSITION_ASSIGNED,
    ENTRY_DESTRUCTION_WRITE_OFF,
    ENTRY_RECOVERY_CREDIT,
    GRADE_C,
    GRADE_D,
    REASON_DEFECTIVE,
    RMA_ISSUED,
    RMA_SUPERSEDED,
    STANDARD_EXPIRES_AT,
    STANDARD_ORDER_PLACED_AT,
)
from test_helpers.test_users import ADMIN, SUPERVISOR

LATER_EXPIRES_AT = "2026-10-01T00:00:00Z"
LOT_WINDOW_START = "2026-08-03T08:00:00Z"
LOT_WINDOW_END = "2026-08-03T12:00:00Z"


def _liquidation_channel(api, channel_code, name):
    """A BULK_LIQUIDATOR taking grades C and D at a 12 percent commission."""
    return fx.make_channel(api, **fx.auction_channel_kwargs(
        channel_code=channel_code, name=name,
        channel_type=CHANNEL_TYPE_BULK_LIQUIDATOR,
        accepted_grades=[GRADE_C, GRADE_D], min_lot_value_cents=1000))


def test_the_creation_time_rma_version_is_already_stale_once_issued(api):
    """PRD §2.8: "If that value does not match the source authorization's current
    `version` — because a prior reissue has already legitimately superseded it, or
    because the authorization has since advanced through receiving — the request is
    rejected with `ERR_STALE_RMA_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_stale_expected_rma_version_blocks_the_reissue
    """
    client = fx.make_client(
        api, **fx.liquidation_client_kwargs("CC1", name="Ccl One")
    )
    item = fx.make_catalog_item(api, client["id"], **fx.widget_item_kwargs())
    draft = fx.make_draft_rma(
        api, client["id"], order_reference="ORD-CC1", customer_reference="CUST-CC1"
    )
    version_at_creation = draft["version"]
    fx.add_rma_line(
        api, draft["id"], item["id"], authorized_quantity=1,
        reason_code=REASON_DEFECTIVE,
    )
    issued = fx.issue_rma(api, draft["id"])
    version_when_issued = issued["version"]
    assert version_when_issued > version_at_creation, (
        "issuing the authorization is itself a guarded write"
    )

    validate_error(
        api.reissue_rma(
            draft["id"],
            f.reissue_payload(version_at_creation, expires_at=LATER_EXPIRES_AT),
            ADMIN,
        ),
        ERR_STALE_RMA_VERSION,
        412,
    )

    unchanged = fx.read_rma(api, draft["id"])
    assert unchanged["status"] == RMA_ISSUED
    assert unchanged["version"] == version_when_issued
    assert_instant_equals(
        unchanged["expires_at"], STANDARD_EXPIRES_AT, "expires_at was not replaced"
    )
    assert unchanged["supersedes_rma_id"] is None
    _, meta = validate_paginated(
        api.list_rmas(ADMIN, {"client_id": client["id"], "limit": 10})
    )
    assert meta["total_count"] == 1, "no replacement authorization was minted"

    # The only defect was the quoted token.
    replacement = validate_success(
        api.reissue_rma(
            draft["id"],
            f.reissue_payload(version_when_issued, expires_at=LATER_EXPIRES_AT),
            ADMIN,
        ),
        201,
    )
    assert replacement["supersedes_rma_id"] == draft["id"]


def test_a_current_rma_version_reissues_and_bumps_the_superseded_source(api):
    """PRD §3.2: "A successful reissue moves the source authorization from `ISSUED`
    to `SUPERSEDED`, advances its `version`, and mints a **new** authorization
    already in `ISSUED` whose `supersedes_rma_id` points at the source; the new
    authorization copies the source's `client_id`, `order_reference`,
    `customer_reference` and `order_placed_at`, copies every authorization line with
    its `catalog_item_id`, `authorized_quantity`, `reason_code` and
    `declared_serial`, and takes the `expires_at` supplied on the request."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_current_expected_rma_version_reissues_and_bumps_the_source
    """
    client = fx.make_client(
        api, **fx.liquidation_client_kwargs("CC2", name="Ccl Two")
    )
    item = fx.make_catalog_item(api, client["id"], **fx.widget_item_kwargs())
    draft = fx.make_draft_rma(
        api, client["id"], order_reference="ORD-CC2", customer_reference="CUST-CC2"
    )
    source_line = fx.add_rma_line(
        api, draft["id"], item["id"], authorized_quantity=2,
        reason_code=REASON_DEFECTIVE,
    )
    version_when_issued = fx.issue_rma(api, draft["id"])["version"]

    replacement = validate_success(
        api.reissue_rma(
            draft["id"],
            f.reissue_payload(version_when_issued, expires_at=LATER_EXPIRES_AT),
            ADMIN,
        ),
        201,
    )
    assert replacement["supersedes_rma_id"] == draft["id"]
    assert replacement["status"] == RMA_ISSUED
    assert replacement["version"] == 1, "the replacement is a brand new row"
    assert_instant_equals(replacement["expires_at"], LATER_EXPIRES_AT, "fresh expiry")
    assert replacement["declared_line_count"] == 1
    assert replacement["authorized_unit_total"] == 2
    assert replacement["received_unit_total"] == 0
    assert replacement["client_id"] == client["id"]
    assert replacement["order_reference"] == "ORD-CC2"
    assert replacement["customer_reference"] == "CUST-CC2"
    assert_instant_equals(
        replacement["order_placed_at"], STANDARD_ORDER_PLACED_AT, "order_placed_at"
    )

    copied, copy_meta = validate_paginated(
        api.list_rma_lines(ADMIN, {"rma_id": replacement["id"], "limit": 10})
    )
    assert copy_meta["total_count"] == 1
    assert copied[0]["authorized_quantity"] == 2
    assert copied[0]["reason_code"] == REASON_DEFECTIVE
    assert copied[0]["id"] != source_line["id"], "the line is a copy, not the same row"

    source = fx.read_rma(api, draft["id"])
    assert source["status"] == RMA_SUPERSEDED
    assert source["version"] == version_when_issued + 1, (
        "the guarded write advanced the source exactly once"
    )

    # SUPERSEDED is terminal, and the state check at priority 20 precedes the
    # version check at priority 28.
    validate_error(
        api.reissue_rma(
            draft["id"],
            f.reissue_payload(source["version"], expires_at=LATER_EXPIRES_AT),
            ADMIN,
        ),
        ERR_RMA_INVALID_STATE,
        409,
    )


def test_an_override_between_grading_and_routing_staleness_beats_drift(api):
    """PRD §2.8: "If that value does not match the line's current `version` —
    because a supervisor override or a mandatory-recall cascade has already changed
    the line's disposition — the request is rejected with
    `ERR_STALE_RETURN_LINE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_stale_expected_return_line_version_blocks_the_order_create
    """
    liquidator = _liquidation_channel(api, "BL-CC3", "Bulk Liquidators")
    donations = fx.make_donation_channel(
        api, channel_code="DN-CC3", name="Helping Hands",
        accepted_grades=[GRADE_C, GRADE_D],
    )
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            "CC3", name="Ccl Three", donation_allowed=True
        ),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-CC3",
    )
    line_id = world["line"]["id"]
    version_when_graded = world["line"]["version"]
    assert world["line"]["disposition"] == DISPOSITION_LIQUIDATE, (
        "grade C on a restock floor of A routes to liquidation"
    )

    overridden = validate_success(
        api.override_disposition(
            line_id,
            f.override_payload(
                DISPOSITION_DONATE, override_reason="Client charity programme"
            ),
            SUPERVISOR,
        ),
        200,
    )
    version_after_override = overridden["version"]
    assert version_after_override == version_when_graded + 1, (
        "the override contributes exactly one increment"
    )

    # Priority 29 precedes priority 49, so the stale token is reported and the
    # pre-override disposition named in the same body is never reached.
    validate_error(
        api.create_disposition_order(
            f.disposition_order_payload(
                line_id,
                version_when_graded,
                channel_id=liquidator["id"],
                disposition=DISPOSITION_LIQUIDATE,
                channel_window_start_at=LOT_WINDOW_START,
                channel_window_end_at=LOT_WINDOW_END,
            ),
            SUPERVISOR,
        ),
        ERR_STALE_RETURN_LINE_VERSION,
        412,
    )

    untouched = fx.read_return_line(api, line_id)
    assert untouched["disposition"] == DISPOSITION_DONATE
    assert untouched["version"] == version_after_override
    assert untouched["disposition_state"] == DS_DISPOSITION_ASSIGNED
    _, order_meta = validate_paginated(
        api.list_disposition_orders(SUPERVISOR, {"return_line_id": line_id})
    )
    assert order_meta["total_count"] == 0, "the refused create stored nothing"

    # Both the token and the disposition had to be refreshed.
    admitted = validate_success(
        api.create_disposition_order(
            f.disposition_order_payload(
                line_id,
                version_after_override,
                channel_id=donations["id"],
                disposition=DISPOSITION_DONATE,
                channel_window_start_at=LOT_WINDOW_START,
                channel_window_end_at=LOT_WINDOW_END,
            ),
            SUPERVISOR,
        ),
        201,
    )
    assert admitted["disposition"] == DISPOSITION_DONATE


def test_the_recovery_credit_lands_in_settlement_but_not_in_shrink(api):
    """PRD §3.8: "The narrower `shrink_ledger_cents` sums only the four loss types —
    `RECEIPT_VARIANCE`, `REFURB_COST`, `DONATION_WRITE_OFF` and
    `DESTRUCTION_WRITE_OFF` — and is therefore never positive."

    Design: Corner/cross_cutting_complexity_layers/corner_ccl_shrink_ledger_and_settlement_derivations_reconcile_after_execute
    """
    channel = _liquidation_channel(api, "BL-CC4", "Bulk Liquidators")
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("CC4", name="Ccl Four"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-CC4",
    )
    client_id = world["client"]["id"]
    order = fx.propose_and_approve(
        api,
        world["line"]["id"],
        channel_id=channel["id"],
        window_start_at=LOT_WINDOW_START,
        window_end_at=LOT_WINDOW_END,
    )
    executed = fx.execute_order(api, order["id"])
    assert executed["status"] == DO_EXECUTED
    assert_money(executed["gross_lot_value_cents"], 7200, "gross lot value")
    assert_pct_equals(executed["effective_fee_pct"], 0.18, "12 percent plus surcharge")
    assert_money(executed["channel_fee_cents"], 1296, "channel fee")
    assert_money(executed["refurb_cost_cents"], 0, "nothing was refurbished")
    assert_money(executed["net_recovery_cents"], 5904, "net recovery")

    entries = fx.list_ledger(api, client_id)
    assert len(entries) == 1, "execution appended exactly one entry"
    credit = sole_entry_of_type(entries, ENTRY_RECOVERY_CREDIT)
    assert_money(
        credit["amount_cents"],
        expected_recovery_credit(5904),
        "net recovery less the 7.5 percent handling share",
    )
    assert credit["sequence_no"] == 1
    assert credit["return_line_id"] == world["line"]["id"]

    client = fx.read_client(api, client_id)
    assert_money(client["settlement_balance_cents"], 5461, "booked settlement")
    assert_money(
        client["shrink_ledger_cents"], 0, "a recovery credit is outside the subset"
    )
    assert_money(
        client["projected_settlement_balance_cents"],
        -12539,
        "5461 booked less the 18000 refund still in RELEASE_PENDING",
    )

    filtered, filtered_meta = validate_paginated(
        api.list_shrink_ledger_entries(
            ADMIN, {"client_id": client_id, "entry_type": ENTRY_RECOVERY_CREDIT}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["id"] == credit["id"]
    _, absent_meta = validate_paginated(
        api.list_shrink_ledger_entries(
            ADMIN,
            {"client_id": client_id, "entry_type": ENTRY_DESTRUCTION_WRITE_OFF},
        )
    )
    assert absent_meta["total_count"] == 0

    audit = fx.read_audit(api, client_id)
    assert_money(audit["recovery_credit_cents"], 5461, "audit recovery credit")
    assert_money(audit["settlement_balance_cents"], 5461, "audit settlement")
    assert_money(audit["shrink_ledger_cents"], 0, "audit shrink")
    assert audit["liquidate_count"] == 1
    assert audit["money_conservation_ok"] is True
