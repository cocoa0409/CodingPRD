"""Two payloads that break two rules at once, where the reported error is fixed by the
ladder rather than by which condition looks more serious."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.factories import request_payload
from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    create_bib_item,
    create_partner,
    create_patron,
    create_rota,
    intake_request,
    load_infraction,
    pickup_loan,
    read_loan,
    read_patron,
    receive_shipment,
    recall_loan,
    run_rota_round,
    set_clock,
    ship_item,
)
from test_helpers.test_users import make_ill_staff_headers
from test_helpers.types import (
    CustodyStatus,
    InfractionKind,
    ItemType,
    LicensedAccessStatus,
    LocalHoldingStatus,
    MaterialType,
    PatronStatus,
    RecallStatus,
)


def _over_cap_patron_with_a_held_and_an_unheld_work(client):
    """A patron 4000 cents over their fiscal cap, plus two works identical except that one
    of them is already on our own shelf."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8008",
        full_name="Hana Staff",
        email="hana@u.edu",
        patron_type="STAFF",
        department="ARCH",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=5000,
    )
    patron = load_infraction(
        client, patron["id"], InfractionKind.UNPAID_CHARGE, unpaid_amount_cents=9000
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        name="Monograph rota",
        material_type=MaterialType.LOAN,
        max_attempts=3,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    held = create_bib_item(
        client,
        title="Concrete Design Handbook",
        item_type=ItemType.BOOK,
        publication_year=2018,
        isbn="978-0-000-00003-5",
        local_holding_status=LocalHoldingStatus.HELD_AVAILABLE,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=9000,
    )
    not_held = create_bib_item(
        client,
        title="Timber Design Handbook",
        item_type=ItemType.BOOK,
        publication_year=2018,
        isbn="978-0-000-00004-2",
        local_holding_status=LocalHoldingStatus.NONE,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=9000,
    )
    return {
        "patron": patron,
        "rota": rota,
        "held": held,
        "not_held": not_held,
    }


def test_the_holdings_gate_answers_first_and_the_fiscal_gate_answers_once_it_is_satisfied(
    client,
):
    """One payload breaks the holdings rule and the money rule together and reports the
    holdings rule; swapping in an unheld work leaves only the money rule, which then fires.

    PRD: "First, the work must not already be sitting on our own shelf: a
    `local_holding_status` of `HELD_AVAILABLE` is refused with `ERR_HELD_LOCALLY`, because
    the patron should borrow it locally instead." And: "Only after all six have passed does
    the fiscal gate run: a patron whose `unpaid_balance_cents` strictly exceeds
    `unpaid_balance_cap_cents` is refused with `ERR_PATRON_BALANCE_EXCEEDED`, carrying HTTP
    402 rather than 403 because the remedy is money rather than permission." And: "Note that
    this fiscal gate is evaluated **after** all six earlier intake gates, so a blocked patron
    whose balance is also over the cap is reported as blocked, not as over-balance."

    Design: Difficulty/priority_pair_validation_conflict/held_locally_constraint_outranks_patron_balance_fiscal_gate_on_intake
    """
    world = _over_cap_patron_with_a_held_and_an_unheld_work(client)
    patron = world["patron"]
    assert patron["unpaid_balance_cents"] == 9000
    assert patron["provisional_risk_score"] == 9
    assert patron["status"] == PatronStatus.ACTIVE

    validate_error(
        client.create_request(
            request_payload(
                patron["id"],
                world["held"]["id"],
                world["rota"]["id"],
                needed_by="2026-08-09T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.HELD_LOCALLY,
        expected_status=422,
    )

    validate_error(
        client.create_request(
            request_payload(
                patron["id"],
                world["not_held"]["id"],
                world["rota"]["id"],
                needed_by="2026-08-09T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.PATRON_BALANCE_EXCEEDED,
        expected_status=402,
    )


def test_neither_refused_intake_left_a_request_row_or_moved_the_patron_counters(client):
    """Both calls are rejections, so the patron's derived figures stand exactly where the
    migrated history put them and the request collection is still empty.

    PRD: "Either way the patron's `open_request_count`, `pending_charge_cents` and
    `provisional_risk_score` are re-derived afterwards." And: "List responses carry `limit`,
    `offset`, `total_count` and `has_more` inside the `meta` object, where `total_count` is
    the number of rows matching the filters before pagination is applied and `has_more`
    states whether any matching row remains beyond the current page."

    Design: Difficulty/priority_pair_validation_conflict/held_locally_constraint_outranks_patron_balance_fiscal_gate_on_intake
    """
    world = _over_cap_patron_with_a_held_and_an_unheld_work(client)
    patron_id = world["patron"]["id"]

    for bib_item_key, error_id in (
        ("held", ApiErrorId.HELD_LOCALLY),
        ("not_held", ApiErrorId.PATRON_BALANCE_EXCEEDED),
    ):
        validate_error(
            client.create_request(
                request_payload(
                    patron_id,
                    world[bib_item_key]["id"],
                    world["rota"]["id"],
                    needed_by="2026-08-09T00:00:00.000Z",
                    max_supply_fee_cents=5000,
                ),
                headers=make_ill_staff_headers(),
            ),
            error_id,
        )

    untouched = read_patron(client, patron_id)
    assert untouched["open_request_count"] == 0
    assert untouched["pending_charge_cents"] == 0
    assert untouched["unpaid_balance_cents"] == 9000
    assert untouched["provisional_risk_score"] == 9
    assert untouched["status"] == PatronStatus.ACTIVE

    rows, meta = validate_paginated(
        client.list_requests(
            headers=make_ill_staff_headers(), params={"patron_id": patron_id}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def _recalled_loan_still_on_the_hold_shelf_past_its_recall_deadline(client):
    """A loan recalled on the day of receipt with two days of grace, never collected, with
    the clock two days past the recall deadline."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8009",
        full_name="Iris Faculty",
        email="iris@u.edu",
        patron_type="FACULTY",
        department="GEOL",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=5000,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        allows_renewals=True,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        name="Monograph rota",
        material_type=MaterialType.LOAN,
        max_attempts=3,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(
        client,
        title="Structural Dynamics",
        item_type=ItemType.BOOK,
        publication_year=2019,
        isbn="978-0-000-00001-1",
        list_price_cents=9000,
    )
    request = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    offer = run_rota_round(client, request["id"])
    accept_offer(client, offer["id"], partner["id"])
    shipment = ship_item(
        client, offer["id"], partner["id"], carrier="UPS", insured_value_cents=9000
    )
    loan = receive_shipment(client, shipment["id"])
    assert loan["custody_status"] == CustodyStatus.AWAITING_PICKUP
    assert loan["renewals_allowed"] is True
    assert loan["max_renewals"] == 2
    assert_same_instant(loan["due_at"], "2026-08-29T00:00:00.000Z")
    assert_same_instant(loan["pickup_expires_at"], "2026-08-08T00:00:00.000Z")

    recalled = recall_loan(client, loan["id"], partner["id"], grace_days=2)
    assert recalled["recall_status"] == RecallStatus.RECALL_ISSUED
    assert_same_instant(recalled["recall_due_at"], "2026-08-03T00:00:00.000Z")
    assert_same_instant(recalled["due_at"], "2026-08-03T00:00:00.000Z")

    set_clock(client, "2026-08-05T00:00:00.000Z")
    return {"patron": patron, "partner": partner, "request": request, "loan": recalled}


def test_the_custody_gate_answers_before_the_recall_deadline_gate_on_a_renewal(client):
    """The uncollected item is both in the wrong custody and past its recall deadline, and
    the earlier rung decides; collecting it changes nothing else, and the later rung fires.

    PRD: "The gates are evaluated in exactly the order §2.8 pins: custody must be
    `WITH_PATRON`; the loan must not be past a recall deadline, meaning `recall_status` must
    not be `RECALL_BREACHED` and, where it is `RECALL_ISSUED`, the clock must be at or before
    `recall_due_at`, otherwise `ERR_RECALL_OVERDUE`; `recall_status` must then be `NONE`
    outright, so a recall that has been issued, honoured or breached locks renewals out with
    `ERR_RENEWAL_BLOCKED_BY_RECALL`; the loan's `renewals_allowed` snapshot must be true,
    otherwise `ERR_RENEWALS_NOT_ALLOWED_BY_LENDER`; and `renewal_count` must be strictly
    below `max_renewals`, otherwise `ERR_RENEWAL_CAP_REACHED`." And: "A renewal attempted on
    a loan that is both breached and beyond its renewal cap reports `ERR_RECALL_OVERDUE`,
    never `ERR_RENEWAL_CAP_REACHED`."

    Design: Difficulty/priority_pair_validation_conflict/loan_custody_state_gate_outranks_recall_temporal_gate_on_renewal
    """
    world = _recalled_loan_still_on_the_hold_shelf_past_its_recall_deadline(client)
    loan_id = world["loan"]["id"]

    validate_error(
        client.renew_loan(loan_id, headers=make_ill_staff_headers()),
        ApiErrorId.LOAN_INVALID_CUSTODY_STATE,
        expected_status=409,
    )

    collected = pickup_loan(client, loan_id)
    assert collected["custody_status"] == CustodyStatus.WITH_PATRON

    validate_error(
        client.renew_loan(loan_id, headers=make_ill_staff_headers()),
        ApiErrorId.RECALL_OVERDUE,
        expected_status=409,
    )


def test_the_two_refused_renewals_leave_the_loan_dates_and_dimensions_exactly_as_found(
    client,
):
    """No renewal was granted, so the recall-shortened due date, the untouched original due
    date and the open recall all survive both refusals, while the pickup in between lands.

    PRD: "On success `due_at` becomes the projection, `renewal_count` is incremented by 1,
    and `original_due_at` stays exactly where it was." And: "the loan's `due_at` is pulled in
    to the earlier of its current value and `recall_due_at`, so a recall never pushes a due
    date outward."

    Design: Difficulty/priority_pair_validation_conflict/loan_custody_state_gate_outranks_recall_temporal_gate_on_renewal
    """
    world = _recalled_loan_still_on_the_hold_shelf_past_its_recall_deadline(client)
    loan_id = world["loan"]["id"]

    client.renew_loan(loan_id, headers=make_ill_staff_headers())
    still_waiting = read_loan(client, loan_id)
    assert still_waiting["renewal_count"] == 0
    assert still_waiting["custody_status"] == CustodyStatus.AWAITING_PICKUP
    assert still_waiting["recall_status"] == RecallStatus.RECALL_ISSUED

    pickup_loan(client, loan_id)
    client.renew_loan(loan_id, headers=make_ill_staff_headers())

    final = read_loan(client, loan_id)
    assert final["renewal_count"] == 0
    assert_same_instant(final["due_at"], "2026-08-03T00:00:00.000Z")
    assert_same_instant(final["original_due_at"], "2026-08-29T00:00:00.000Z")
    assert_same_instant(final["recall_due_at"], "2026-08-03T00:00:00.000Z")
    assert final["recall_status"] == RecallStatus.RECALL_ISSUED
    assert final["custody_status"] == CustodyStatus.WITH_PATRON
    assert_same_instant(final["picked_up_at"], "2026-08-05T00:00:00.000Z")
