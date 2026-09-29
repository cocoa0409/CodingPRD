"""Valid transitions, non-idempotent triggers and wrong from-states.

PRD 3.2 pins the one forward move a board line makes: "On success the card moves
`DRAFT` -> `PUBLISHED` and `published_at` is stamped with the logical clock, after
which the card appears on the branch's board for its currency line for as long as
the clock sits inside the window."  PRD 2.8 rank 5 collects the from-state refusals
of every machine into one rank - "The target row must be in a state the requested
transition leaves from" - and hands each trigger its own error id.
"""

from test_helpers import (
    CLOCK_START,
    OPERATORS,
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

CANONICAL_MIX = [f.denom(2000, 10), f.denom(5000, 10), f.denom(10000, 20)]
THREE_LINE_DEAL = [f.denom(10000, 1), f.denom(5000, 1), f.denom(2000, 2)]


def test_publishing_a_draft_card_puts_it_on_the_board(
    api, treasury_headers, teller_headers, customer_headers
):
    """The board carries no line while the card is DRAFT; publishing stamps
    published_at with the logical clock and the same card appears at once with the
    derived 970600 buy and 878600 sell rates under its board label.

    Design: Corner/state_machines/rate_card_draft_to_published_transition_and_board_effect
    """
    branch = fx.register_branch(api)
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)
    card = fx.draft_rate_card(api, branch["id"], wholesale["id"], branch["version"])

    before = fx.read_board(api, branch["id"], teller_headers)
    a.assert_rate_board(before)
    assert before["line_count"] == 0
    assert before["lines"] == []

    published = validate_success(api.publish_rate_card(card["id"], treasury_headers))

    a.assert_rate_card(published)
    assert published["status"] == "PUBLISHED"
    a.assert_timestamp_equals(published["published_at"], CLOCK_START)
    assert published["superseded_by_rate_card_id"] is None

    board = validate_success(
        api.get_rate_board(branch["id"], customer_headers, {"currency_code": "EUR"})
    )

    a.assert_rate_board(board)
    assert board["line_count"] == 1
    a.assert_timestamp_equals(board["as_of"], CLOCK_START)
    assert board["min_disclosure_text_version"] == 3
    line = board["lines"][0]
    assert line["board_display_label"] == "EUR Euro"
    assert line["buy_rate_micros"] == 970600
    assert line["sell_rate_micros"] == 878600


def test_publish_is_not_idempotent_on_a_published_card(api, treasury_headers):
    """A second publish of the same card is refused with ERR_RATE_CARD_NOT_DRAFT and
    leaves published_at at the first call's instant even though the clock has since
    moved a day forward, with the card's version untouched.

    Design: Corner/state_machines/rate_card_publish_cannot_repeat_on_published_card
    """
    branch = fx.register_branch(api)
    fx.register_currency(api)
    wholesale = fx.record_wholesale_rate(api)
    card = fx.draft_rate_card(api, branch["id"], wholesale["id"], branch["version"])
    published = fx.publish_rate_card(api, card["id"])
    version_at_publish = published["version"]

    fx.set_clock(api, "2026-08-02T00:00:00Z")

    validate_error(
        api.publish_rate_card(card["id"], treasury_headers),
        ApiErrorId.ERR_RATE_CARD_NOT_DRAFT,
        409,
    )

    final = validate_success(api.get_rate_card(card["id"], treasury_headers))
    assert final["status"] == "PUBLISHED"
    a.assert_timestamp_equals(final["published_at"], CLOCK_START)
    assert final["version"] == version_at_publish


def test_each_settlement_trigger_names_its_own_wrong_from_state(
    api, teller_headers, teller2_headers, manager_headers
):
    """Three distinct from-state errors come out of one rank: re-authorising an
    AUTHORIZED deal gives ERR_TRANSACTION_NOT_QUOTED, reversing a QUOTED deal gives
    ERR_TRANSACTION_NOT_SETTLED and voiding a SETTLED deal gives
    ERR_TRANSACTION_NOT_VOIDABLE, with only the one legal settle moving notes.

    Design: Corner/state_machines/transaction_invalid_from_state_family_returns_4XX
    """
    world = fx.trading_world(api, position_mix=CANONICAL_MIX, identified=False)
    first = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", THREE_LINE_DEAL, teller_headers
    )
    second = fx.quote_deal(
        api, world, "SELL_FX_TO_CUSTOMER", [f.denom(10000, 1)], teller_headers
    )
    fx.authorize_deal(api, first["id"], teller_headers)

    validate_error(
        api.authorize_transaction(first["id"], teller2_headers),
        ApiErrorId.ERR_TRANSACTION_NOT_QUOTED,
        409,
    )
    assert fx.read_transaction(api, first["id"])["settlement_status"] == "AUTHORIZED"

    validate_error(
        api.reverse_transaction(
            second["id"], f.reverse_payload("customer changed mind"), manager_headers
        ),
        ApiErrorId.ERR_TRANSACTION_NOT_SETTLED,
        409,
    )
    assert fx.read_transaction(api, second["id"])["settlement_status"] == "QUOTED"

    settled = validate_success(api.settle_transaction(first["id"], teller2_headers))
    assert settled["settlement_status"] == "SETTLED"
    a.assert_settlement_money(settled, 21626, 757, 22383)

    validate_error(
        api.void_transaction(first["id"], f.void_payload("too late"), teller2_headers),
        ApiErrorId.ERR_TRANSACTION_NOT_VOIDABLE,
        409,
    )
    assert fx.read_transaction(api, first["id"])["settlement_status"] == "SETTLED"

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    a.assert_mix_counts(position, 10000, available=19)
    a.assert_mix_counts(position, 5000, available=9)
    a.assert_mix_counts(position, 2000, available=8)


def test_all_three_plan_triggers_share_one_invalid_state_error(
    api, treasury_headers, manager_headers
):
    """Review and activate on a DRAFT plan and a second submit on a SUBMITTED plan
    are all refused with ERR_PLAN_INVALID_STATE, the single legal submit records the
    submitting operator, and none of the refusals touches revision_count or writes a
    reviewer.

    Design: Corner/state_machines/plan_invalid_state_triggers_rejected
    """
    branch = fx.register_branch(api, code="BR-CMN", name="Casablanca", region_code="SOUTH")
    fx.register_currency(
        api, f.restricted_currency_payload(export_limit_minor_units=200000)
    )
    fx.record_wholesale_rate(api, currency_code="MAD", mid_rate_micros=9_600_000)
    corridor = fx.register_corridor(
        api,
        code="LHR-CMN",
        destination_country_code="MA",
        destination_currency_code="MAD",
        season="SUMMER",
        season_start_date="2026-06-01T00:00:00Z",
        season_end_date="2026-09-30T00:00:00Z",
        demand_index_bps=13500,
    )
    plan = fx.draft_plan(
        api,
        branch["id"],
        corridor["id"],
        season_days=92,
        target_lines=[f.target_line("MAD", 5000)],
    )
    assert plan["status"] == "DRAFT"

    validate_error(
        api.review_inventory_plan(
            plan["id"], f.review_plan_payload("APPROVE"), treasury_headers
        ),
        ApiErrorId.ERR_PLAN_INVALID_STATE,
        409,
    )
    assert fx.read_plan(api, plan["id"])["status"] == "DRAFT"

    validate_error(
        api.activate_inventory_plan(plan["id"], manager_headers),
        ApiErrorId.ERR_PLAN_INVALID_STATE,
        409,
    )

    submitted = validate_success(
        api.submit_inventory_plan(plan["id"], {}, manager_headers)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == OPERATORS["MANAGER"]

    validate_error(
        api.submit_inventory_plan(plan["id"], {}, manager_headers),
        ApiErrorId.ERR_PLAN_INVALID_STATE,
        409,
    )

    final = fx.read_plan(api, plan["id"])
    a.assert_inventory_plan(final)
    assert final["status"] == "SUBMITTED"
    assert final["revision_count"] == 0
    assert final["reviewed_by_user_id"] is None


def test_dispatch_separates_its_state_guard_from_its_window_guard(
    api, treasury_headers, manager_headers
):
    """Dispatching an unscheduled shipment is a state failure
    (ERR_SHIPMENT_INVALID_STATE) while dispatching a SCHEDULED one before the clock
    reaches window_start is a temporal failure (ERR_SHIPMENT_WINDOW_NOT_OPEN); moving
    the clock to exactly window_start lets the identical call through without moving
    a single note.

    Design: Corner/state_machines/shipment_invalid_state_and_window_not_open_enforced
    """
    branch = fx.register_branch(api)
    fx.register_currency(api)
    fx.record_wholesale_rate(api)
    route = fx.register_route(
        api,
        code="RT-SOUTH-1",
        carrier_name="SecurCash",
        region_code="SOUTH",
        daily_capacity_usd_cents=200000,
    )
    position = fx.open_position(api, branch["id"], "EUR", [f.denom(10000, 20)])
    shipment = fx.raise_shipment(
        api, branch["id"], "EUR", "REPLENISHMENT", [f.denom(10000, 4)]
    )

    validate_error(
        api.dispatch_cash_shipment(shipment["id"], treasury_headers),
        ApiErrorId.ERR_SHIPMENT_INVALID_STATE,
        409,
    )
    assert fx.read_shipment(api, shipment["id"])["status"] == "REQUESTED"

    fx.schedule_shipment(
        api,
        shipment["id"],
        route["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
    )

    validate_error(
        api.dispatch_cash_shipment(shipment["id"], treasury_headers),
        ApiErrorId.ERR_SHIPMENT_WINDOW_NOT_OPEN,
        409,
    )
    assert fx.read_shipment(api, shipment["id"])["status"] == "SCHEDULED"

    clock = fx.set_clock(api, "2026-08-05T09:00:00Z")
    a.assert_timestamp_equals(clock["current_utc"], "2026-08-05T09:00:00Z")
    assert clock["expired_contract_count"] == 0

    dispatched = validate_success(
        api.dispatch_cash_shipment(shipment["id"], treasury_headers)
    )
    a.assert_cash_shipment(dispatched)
    assert dispatched["status"] == "IN_TRANSIT"

    settled_position = fx.read_position(api, position["id"])
    a.assert_mix_counts(settled_position, 10000, available=20)
    assert settled_position["total_minor_units"] == 200000


def test_cancelled_contract_refuses_both_of_its_exits(
    api, teller_headers, teller2_headers, manager_headers
):
    """A cancelled rate lock is closed on both exits - redeem answers
    ERR_CONTRACT_NOT_REDEEMABLE and a second cancel answers
    ERR_CONTRACT_NOT_CANCELLABLE - and the cancellation has already zeroed the
    notional and the liability and released the origin deal's pointer.

    Design: Corner/state_machines/contract_cannot_be_redeemed_or_cancelled_after_cancellation
    """
    world = fx.trading_world(api, identified=False)
    txn = fx.settled_deal(
        api,
        world,
        "SELL_FX_TO_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    contract = fx.issue_contract(
        api, txn["customer_id"], txn["id"], headers=teller_headers
    )
    fx.cancel_contract(api, contract["id"], "customer withdrew", manager_headers)

    validate_error(
        api.redeem_buyback_contract(
            contract["id"], f.redeem_payload([f.denom(10000, 1)]), teller_headers
        ),
        ApiErrorId.ERR_CONTRACT_NOT_REDEEMABLE,
        409,
    )
    validate_error(
        api.cancel_buyback_contract(
            contract["id"], f.cancel_contract_payload("again"), manager_headers
        ),
        ApiErrorId.ERR_CONTRACT_NOT_CANCELLABLE,
        409,
    )

    final = fx.read_contract(api, contract["id"])
    a.assert_buyback_contract(final)
    assert final["status"] == "CANCELLED"
    assert final["remaining_fx_minor_units"] == 0
    assert final["liability_usd_cents"] == 0
    assert final["redemption_count"] == 0

    assert fx.read_transaction(api, txn["id"])["buyback_contract_id"] is None
    assert fx.read_branch(api, world["branch"]["id"])["buyback_liability_usd_cents"] == 0


def test_repeating_the_assess_and_amend_triggers_fails_on_both_machines(
    api, teller_headers, teller2_headers, manager_headers, compliance_headers
):
    """A second assess on an ASSESSED row answers ERR_ASSESSMENT_ALREADY_ASSESSED and
    amending the DRAFT counterfeit report answers ERR_REPORT_INVALID_STATE, while
    filing that report first makes the very same amend succeed at amendment_count 1 -
    and the refused retry moves no notes.

    Design: Corner/state_machines/assessment_and_report_repeat_triggers_rejected
    """
    world = fx.trading_world(api, identified=False)
    txn = fx.settled_deal(
        api,
        world,
        "BUY_FX_FROM_CUSTOMER",
        [f.denom(10000, 2)],
        teller_headers,
        settle_headers=teller2_headers,
    )
    assessment = fx.detain_notes(
        api,
        world["branch"]["id"],
        world["position"]["id"],
        txn["id"],
        10000,
        1,
        "SUSPECTED_COUNTERFEIT",
        teller_headers,
        serial_reference="X12345",
    )
    fx.assess_notes(api, assessment["id"], "CONFISCATED", "UV mark absent", manager_headers)
    report = fx.only_report(api, {"note_assessment_id": assessment["id"]})

    validate_error(
        api.assess_note_assessment(
            assessment["id"], f.assess_payload("RETURNED"), manager_headers
        ),
        ApiErrorId.ERR_ASSESSMENT_ALREADY_ASSESSED,
        409,
    )
    unchanged = validate_success(
        api.get_note_assessment(assessment["id"], manager_headers)
    )
    a.assert_note_assessment(unchanged)
    assert unchanged["outcome"] == "CONFISCATED"

    validate_error(
        api.amend_compliance_report(
            report["id"], f.amend_report_payload("serial correction"), compliance_headers
        ),
        ApiErrorId.ERR_REPORT_INVALID_STATE,
        409,
    )
    still_draft = validate_success(
        api.get_compliance_report(report["id"], compliance_headers)
    )
    assert still_draft["status"] == "DRAFT"
    assert still_draft["amendment_count"] == 0

    filed = validate_success(
        api.file_compliance_report(
            report["id"], f.file_report_payload("CTR-2026-0001"), compliance_headers
        )
    )
    assert filed["status"] == "FILED"
    assert filed["filing_reference"] == "CTR-2026-0001"
    a.assert_timestamp_equals(filed["filed_at"], CLOCK_START)

    amended = validate_success(
        api.amend_compliance_report(
            report["id"], f.amend_report_payload("serial correction"), compliance_headers
        )
    )
    a.assert_compliance_report(amended)
    assert amended["status"] == "AMENDING"
    assert amended["amendment_count"] == 1

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    a.assert_mix_counts(position, 10000, available=21, quarantined=0, written_off=1)
