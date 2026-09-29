"""Two thresholds probed on both sides: the fifth and sixth free article fill of a journal
year, and a renewal that just reaches the twelve-week ceiling."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    create_article_bib_item,
    create_bib_item,
    create_partner,
    create_patron,
    create_rota,
    intake_copy_request,
    intake_request,
    list_clearances,
    list_notifications,
    pickup_loan,
    read_loan,
    read_patron,
    read_request,
    receive_shipment,
    run_rota_round,
    set_clock,
    ship_item,
)
from test_helpers.test_users import make_ill_staff_headers
from test_helpers.types import (
    ClearanceMethod,
    ClearanceStatus,
    CustodyStatus,
    ItemType,
    MaterialType,
    NotificationKind,
    RecallStatus,
    RequestStatus,
)

ARTICLE_ISSN = "1234-5678"


def _journal_year_with_four_free_fills_spent(client):
    """One journal inside the recency window whose 2026 allowance has four of its five free
    fills already taken."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8010",
        full_name="Jo Faculty",
        email="jo@u.edu",
        patron_type="FACULTY",
        department="OPTI",
        max_open_requests=10,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=5000,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=1500,
        avg_turnaround_days=2,
        supplies_electronic=True,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        name="Article supply rota",
        material_type=MaterialType.COPY,
        max_attempts=3,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=1500,
        quoted_turnaround_days=2,
    )
    bib_item = create_article_bib_item(
        client,
        issn=ARTICLE_ISSN,
        title="Adaptive optics for large apertures",
        journal_title="Journal of Applied Optics",
        publication_year=2024,
        list_price_cents=4000,
    )

    def file_copy():
        return intake_copy_request(
            client,
            patron["id"],
            bib_item["id"],
            rota["id"],
            pages_requested=12,
            needed_by="2026-08-20T00:00:00.000Z",
            max_supply_fee_cents=5000,
        )

    earlier = [file_copy() for _ in range(4)]
    return {"patron": patron, "file_copy": file_copy, "earlier": earlier}


def _usage(client, calendar_year=2026):
    return validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": ARTICLE_ISSN, "calendar_year": calendar_year},
        )
    )


def test_the_fifth_free_fill_of_the_journal_year_still_clears_and_is_numbered_five(client):
    """With four fills spent the counter is still strictly below the allowance, so the fifth
    request clears on the free method and takes the last sequence number in a dense run.

    PRD: "If the work does count and the counter for its journal-year pair is still below
    five, a clearance is created with `method` `CONTU_FREE` and `sequence_in_year` set to the
    counter's new value — one for the first such fill of the year, two for the second, and so
    on up to five — and the request again proceeds to `SOURCING`." And: "The free-fill
    allowance per journal-year pair is five."

    Design: Difficulty/boundary_precision_check/fifth_contu_free_fill_clears_while_the_sixth_parks_in_copyright_hold
    """
    world = _journal_year_with_four_free_fills_spent(client)
    before = _usage(client)
    assert before["counted_fill_count"] == 4
    assert before["free_fills_remaining"] == 1

    fourth_rows = list_clearances(client, world["earlier"][3]["id"])
    assert len(fourth_rows) == 1
    assert fourth_rows[0]["sequence_in_year"] == 4

    fifth = world["file_copy"]()
    assert fifth["status"] == RequestStatus.SOURCING
    assert fifth["copyright_required"] is True

    rows = list_clearances(client, fifth["id"])
    assert len(rows) == 1
    assert rows[0]["method"] == ClearanceMethod.CONTU_FREE
    assert rows[0]["sequence_in_year"] == 5
    assert rows[0]["status"] == ClearanceStatus.ACTIVE
    assert rows[0]["calendar_year"] == 2026
    assert rows[0]["issn"] == ARTICLE_ISSN
    assert rows[0]["pages_covered"] == 12
    assert rows[0]["royalty_cents"] == 0
    assert rows[0]["approved_by_user_id"] is None

    after = _usage(client)
    assert after["counted_fill_count"] == 5
    assert after["free_fills_remaining"] == 0


def test_the_sixth_fill_writes_no_clearance_at_all_and_parks_the_request_on_hold(client):
    """One request past the boundary the same journal year is not an error but a routing
    decision, and it leaves the pool figures exactly where the fifth fill left them.

    PRD: "Otherwise the allowance is spent: **no clearance row is created at all**, and the
    request parks at `COPYRIGHT_HOLD`." And: "On the sourcing branch a notice of kind
    `REQUEST_SUBMITTED` is emitted; on the hold branch the notice is of kind
    `COPYRIGHT_HOLD`." And: "Staff can see the state of the pool before they take a request
    in: the copyright-usage report answers, for one `issn` and one `calendar_year`, the
    `counted_fill_count` consumed so far, the `free_fills_remaining` out of five, and for
    context the `royalty_paid_count` and `pre_window_exempt_count` recorded under the other
    two methods."

    Design: Difficulty/boundary_precision_check/fifth_contu_free_fill_clears_while_the_sixth_parks_in_copyright_hold
    """
    world = _journal_year_with_four_free_fills_spent(client)
    fifth = world["file_copy"]()
    assert fifth["status"] == RequestStatus.SOURCING

    sixth = world["file_copy"]()
    assert sixth["status"] == RequestStatus.COPYRIGHT_HOLD
    assert sixth["copyright_required"] is True

    rows, meta = validate_paginated(
        client.list_copyright_clearances(sixth["id"], headers=make_ill_staff_headers())
    )
    assert rows == []
    assert meta["total_count"] == 0

    notices = list_notifications(
        client, sixth["id"], params={"kind": NotificationKind.COPYRIGHT_HOLD}
    )
    assert len(notices) == 1

    unchanged = _usage(client)
    assert unchanged["counted_fill_count"] == 5
    assert unchanged["free_fills_remaining"] == 0
    assert unchanged["royalty_paid_count"] == 0
    assert unchanged["pre_window_exempt_count"] == 0

    holder = read_patron(client, world["patron"]["id"])
    assert holder["open_request_count"] == 6


def _eighty_day_loan_in_the_hands_of_its_patron(client):
    """A loan whose committed period of 80 days leaves only four days of headroom under the
    twelve-week ceiling."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8011",
        full_name="Kim Grad",
        email="kim@u.edu",
        patron_type="GRAD",
        department="HIST",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=5000,
    )
    partner = create_partner(
        client,
        code="LONGL",
        name="Long Loan Regional Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        supplies_electronic=False,
        allows_renewals=True,
        loan_period_days=80,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        name="Long loan rota",
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
        title="Prairie Settlement Records 1860-1900",
        item_type=ItemType.BOOK,
        publication_year=1998,
        isbn="978-0-000-00005-9",
        list_price_cents=12000,
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
        client, offer["id"], partner["id"], carrier="FEDEX", insured_value_cents=12000
    )
    loan = receive_shipment(client, shipment["id"])
    loan = pickup_loan(client, loan["id"])
    return {"patron": patron, "request": request, "loan": loan}


def test_the_first_renewal_is_truncated_by_the_twelve_week_ceiling_to_four_days(client):
    """A full fortnight would run past the hard ceiling, so the projection is the ceiling
    itself, which is still strictly later than the current due date and so is granted.

    PRD: "The projected new due date is the earlier of the current `due_at` plus 14 days — a
    fortnight per renewal — and the hard ceiling of `received_at` plus 84 days, twelve weeks
    from receipt." And: "On success `due_at` becomes the projection, `renewal_count` is
    incremented by 1, and `original_due_at` stays exactly where it was."

    Design: Difficulty/boundary_precision_check/renewal_at_the_total_loan_ceiling_extends_once_then_stalls_on_exact_equality
    """
    world = _eighty_day_loan_in_the_hands_of_its_patron(client)
    loan = world["loan"]
    assert loan["max_renewals"] == 2
    assert loan["renewal_count"] == 0
    assert_same_instant(loan["due_at"], "2026-10-20T00:00:00.000Z")
    assert_same_instant(loan["original_due_at"], "2026-10-20T00:00:00.000Z")

    committed = read_request(client, world["request"]["id"])
    assert committed["committed_loan_period_days"] == 80
    assert committed["rush_surcharge_cents"] == 0

    renewed = validate_success(
        client.renew_loan(loan["id"], headers=make_ill_staff_headers())
    )
    assert_same_instant(renewed["due_at"], "2026-10-24T00:00:00.000Z")
    assert renewed["renewal_count"] == 1
    assert_same_instant(renewed["original_due_at"], "2026-10-20T00:00:00.000Z")


def test_the_second_renewal_stalls_on_exact_equality_with_the_ceiling_not_on_the_count(
    client,
):
    """The second projection lands on the ceiling the first renewal already reached, so it is
    not strictly later and buys nothing, while the count and policy gates both still allow it.

    PRD: "If that projection is not strictly later than the current `due_at`, the renewal
    buys nothing and is likewise refused with `ERR_RENEWAL_CAP_REACHED`." And: "the renewal
    budget and the total-loan ceiling both leave room: `ERR_RENEWAL_CAP_REACHED` (409), on
    renewal."

    Design: Difficulty/boundary_precision_check/renewal_at_the_total_loan_ceiling_extends_once_then_stalls_on_exact_equality
    """
    world = _eighty_day_loan_in_the_hands_of_its_patron(client)
    loan_id = world["loan"]["id"]
    validate_success(client.renew_loan(loan_id, headers=make_ill_staff_headers()))

    validate_error(
        client.renew_loan(loan_id, headers=make_ill_staff_headers()),
        ApiErrorId.RENEWAL_CAP_REACHED,
        expected_status=409,
    )

    stalled = read_loan(client, loan_id)
    assert stalled["renewal_count"] == 1
    assert stalled["renewal_count"] < stalled["max_renewals"]
    assert_same_instant(stalled["due_at"], "2026-10-24T00:00:00.000Z")
    assert_same_instant(stalled["original_due_at"], "2026-10-20T00:00:00.000Z")
    assert stalled["renewals_allowed"] is True
    assert stalled["recall_status"] == RecallStatus.NONE
    assert stalled["custody_status"] == CustodyStatus.WITH_PATRON
