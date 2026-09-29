"""Two quantities a cancellation has to hand back exactly: the money a lender is owed, and
a journal's regulatory allowance."""

from prd_bench_local_runner.testing import validate_success

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
    read_partner,
    read_patron,
    read_request,
    run_rota_round,
    set_clock,
)
from test_helpers.test_users import make_ill_staff_headers
from test_helpers.types import (
    ClearanceMethod,
    ClearanceStatus,
    ItemType,
    MaterialType,
    OfferStatus,
    RequestStatus,
)

POOL_ISSN = "4321-8765"


def _partner_owed_one_committed_fee_and_a_second_commitment_ready(client):
    """A lender carrying exactly one live commitment worth 1200 cents, plus a second request
    ready to be committed at a different price."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8016",
        full_name="Pia Grad",
        email="pia@u.edu",
        patron_type="GRAD",
        department="PHIL",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=20000,
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
    assert partner["borrow_payable_cents"] == 0
    assert partner["borrowed_from_count"] == 0

    rotas = {}
    for name, fee, days in (("CHEAP rota", 1200, 9), ("FAST rota", 2000, 4)):
        rota = create_rota(
            client,
            name=name,
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
            quoted_fee_cents=fee,
            quoted_turnaround_days=days,
        )
        rotas[name] = rota

    def commit(rota, title, isbn, publication_year, needed_by):
        bib_item = create_bib_item(
            client,
            title=title,
            item_type=ItemType.BOOK,
            publication_year=publication_year,
            isbn=isbn,
            list_price_cents=9000,
        )
        request = intake_request(
            client,
            patron["id"],
            bib_item["id"],
            rota["id"],
            needed_by=needed_by,
            max_supply_fee_cents=5000,
        )
        offer = run_rota_round(client, request["id"])
        accepted = accept_offer(client, offer["id"], partner["id"])
        return request, offer, accepted

    request_x, _, _ = commit(
        rotas["CHEAP rota"],
        "Phenomenology of Perception",
        "978-0-000-00012-7",
        2009,
        "2026-08-20T00:00:00.000Z",
    )
    baseline = read_partner(client, partner["id"])
    assert baseline["borrow_payable_cents"] == 1200
    assert baseline["borrowed_from_count"] == 1
    assert baseline["net_borrow_imbalance_items"] == 1

    return {
        "patron": patron,
        "partner": partner,
        "baseline": baseline,
        "request_x": request_x,
        "commit_second": lambda: commit(
            rotas["FAST rota"],
            "Being and Nothingness",
            "978-0-000-00013-4",
            2010,
            "2026-08-09T00:00:00.000Z",
        ),
    }


def test_cancelling_the_second_commitment_returns_the_payable_to_its_exact_baseline(client):
    """The payable rises by the newly committed fee and then comes back to the byte-identical
    figure it held before, with the item counters unwinding in step rather than lagging.

    PRD: "Committing a request adds that request's committed fee; cancelling the same request
    must return `borrow_payable_cents` to exactly the value it held before the commitment, with
    no drift in either direction." And: "The same conservation applies to
    `borrowed_from_count` and, through it, to `net_borrow_imbalance_items`."

    Design: Difficulty/compensating_invariant/cancelling_a_committed_request_restores_partner_borrow_payable_without_drift
    """
    world = _partner_owed_one_committed_fee_and_a_second_commitment_ready(client)
    partner_id = world["partner"]["id"]
    request_y, _, accepted = world["commit_second"]()
    assert accepted["status"] == OfferStatus.ACCEPTED

    peak = read_partner(client, partner_id)
    assert peak["borrow_payable_cents"] == 3200
    assert peak["borrowed_from_count"] == 2
    assert peak["net_borrow_imbalance_items"] == 2

    validate_success(
        client.cancel_request(request_y["id"], headers=make_ill_staff_headers())
    )

    after = read_partner(client, partner_id)
    assert after["borrow_payable_cents"] == world["baseline"]["borrow_payable_cents"]
    assert after["borrow_payable_cents"] == 1200
    assert after["borrow_payable_cents"] != 3200
    assert after["borrow_payable_cents"] != 2000
    assert after["borrowed_from_count"] == 1
    assert after["net_borrow_imbalance_items"] == 1


def test_the_cancelled_request_is_stripped_of_its_money_while_its_neighbour_is_untouched(
    client,
):
    """Every priced figure on the abandoned request is zeroed and its lender link cleared, so
    the patron's pending total falls back to the surviving commitment alone.

    PRD: "The request's `committed_partner_id` is cleared to null and its
    `committed_fee_cents`, `rush_surcharge_cents`, `royalty_cents`, `gross_charge_cents`,
    `subsidy_cents` and `net_patron_charge_cents` are all zeroed, so a cancelled request
    contributes nothing to the patron's `pending_charge_cents` and nothing to any invoice
    period." And: "Every `OFFERED` offer moves to `CANCELLED` and every `PROPOSED` purchase
    order moves to `CANCELLED`."

    Design: Difficulty/compensating_invariant/cancelling_a_committed_request_restores_partner_borrow_payable_without_drift
    """
    world = _partner_owed_one_committed_fee_and_a_second_commitment_ready(client)
    request_y, offer_y, _ = world["commit_second"]()

    cancelled = validate_success(
        client.cancel_request(request_y["id"], headers=make_ill_staff_headers())
    )
    assert cancelled["status"] == RequestStatus.CANCELLED
    assert cancelled["committed_partner_id"] is None
    assert cancelled["committed_fee_cents"] == 0
    assert cancelled["rush_surcharge_cents"] == 0
    assert cancelled["royalty_cents"] == 0
    assert cancelled["gross_charge_cents"] == 0
    assert cancelled["subsidy_cents"] == 0
    assert cancelled["net_patron_charge_cents"] == 0

    kept = validate_success(
        client.get_supply_offer(offer_y["id"], headers=make_ill_staff_headers())
    )
    assert kept["status"] == OfferStatus.ACCEPTED

    survivor = read_request(client, world["request_x"]["id"])
    assert survivor["committed_fee_cents"] == 1200
    assert survivor["status"] == RequestStatus.SUPPLY_COMMITTED
    assert survivor["net_patron_charge_cents"] == 240

    patron = read_patron(client, world["patron"]["id"])
    assert patron["open_request_count"] == 1
    assert patron["pending_charge_cents"] == 240


def _journal_pool_exhausted_with_a_sixth_request_parked(client):
    """One journal year with all five free fills issued, a sixth request parked on hold, and a
    way to file further requests against the same article."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8017",
        full_name="Quinn Faculty",
        email="quinn@u.edu",
        patron_type="FACULTY",
        department="PHYS",
        max_open_requests=10,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=20000,
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
        issn=POOL_ISSN,
        title="Superfluid helium transport",
        journal_title="Low Temperature Physics Letters",
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

    free_fills = [file_copy() for _ in range(5)]
    parked = file_copy()
    assert parked["status"] == RequestStatus.COPYRIGHT_HOLD
    return {
        "patron": patron,
        "file_copy": file_copy,
        "fifth": free_fills[4],
        "parked": parked,
    }


def _pool(client):
    return validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": POOL_ISSN, "calendar_year": 2026},
        )
    )


def test_cancelling_an_article_request_voids_its_clearance_and_hands_the_fill_back(client):
    """The exhausted pool has one fill returned to it by the cancellation, and the returned
    clearance row survives as an audit trace rather than disappearing.

    PRD: "Cancelling a request voids every `ACTIVE` clearance it holds, moving each `status` to
    `VOIDED`, and because the counter only counts `ACTIVE` rows, the freed slot becomes
    available to the next article request for that journal and year." And: "The counter itself
    is the number of clearance rows sharing the given `issn` and `calendar_year` whose `method`
    is `CONTU_FREE` and whose `status` is `ACTIVE`; voided rows do not count, and rows recorded
    under the other two methods do not count either."

    Design: Difficulty/compensating_invariant/cancelling_an_article_request_returns_its_contu_free_fill_to_the_journal_pool
    """
    world = _journal_pool_exhausted_with_a_sixth_request_parked(client)
    full = _pool(client)
    assert full["counted_fill_count"] == 5
    assert full["free_fills_remaining"] == 0

    cancelled = validate_success(
        client.cancel_request(world["fifth"]["id"], headers=make_ill_staff_headers())
    )
    assert cancelled["status"] == RequestStatus.CANCELLED

    traces = list_clearances(client, world["fifth"]["id"])
    assert len(traces) == 1
    assert traces[0]["status"] == ClearanceStatus.VOIDED
    assert traces[0]["sequence_in_year"] == 5
    assert traces[0]["method"] == ClearanceMethod.CONTU_FREE

    returned = _pool(client)
    assert returned["counted_fill_count"] == 4
    assert returned["free_fills_remaining"] == 1


def test_the_returned_fill_is_reissued_once_and_the_pool_lands_exactly_back_on_five(client):
    """The freed slot is taken by the next request at the same sequence number, the pool is
    exactly full again with no drift, and the request already parked stays parked.

    PRD: "If the work does count and the counter for its journal-year pair is still below
    five, a clearance is created with `method` `CONTU_FREE` and `sequence_in_year` set to the
    counter's new value — one for the first such fill of the year, two for the second, and so
    on up to five — and the request again proceeds to `SOURCING`." And: "A request sitting at
    `COPYRIGHT_HOLD` moves forward only when an `IllBorrowingStaff` member records a
    paid-royalty clearance, which drives the transition `COPYRIGHT_HOLD → SOURCING`."

    Design: Difficulty/compensating_invariant/cancelling_an_article_request_returns_its_contu_free_fill_to_the_journal_pool
    """
    world = _journal_pool_exhausted_with_a_sixth_request_parked(client)
    validate_success(
        client.cancel_request(world["fifth"]["id"], headers=make_ill_staff_headers())
    )

    reissued = world["file_copy"]()
    assert reissued["status"] == RequestStatus.SOURCING

    rows = list_clearances(client, reissued["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == ClearanceStatus.ACTIVE
    assert rows[0]["method"] == ClearanceMethod.CONTU_FREE
    assert rows[0]["sequence_in_year"] == 5

    refilled = _pool(client)
    assert refilled["counted_fill_count"] == 5
    assert refilled["free_fills_remaining"] == 0

    still_parked = read_request(client, world["parked"]["id"])
    assert still_parked["status"] == RequestStatus.COPYRIGHT_HOLD
    assert list_clearances(client, world["parked"]["id"]) == []

    patron = read_patron(client, world["patron"]["id"])
    assert patron["open_request_count"] == 6
