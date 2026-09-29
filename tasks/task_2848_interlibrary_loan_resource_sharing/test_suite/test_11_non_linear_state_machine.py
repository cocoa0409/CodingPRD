"""Two machines that are not straight lines: a request that re-enters sourcing three
times, and a loan whose three dimensions advance on different edges."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    create_bib_item,
    create_partner,
    create_patron,
    create_rota,
    decide_pod_order,
    decline_offer,
    escalate_request,
    intake_request,
    lender_confirm,
    list_request_shipments,
    pickup_loan,
    read_loan,
    read_patron,
    read_request,
    receive_shipment,
    recall_loan,
    return_loan,
    run_rota_round,
    set_clock,
    ship_item,
)
from test_helpers.test_users import (
    ACQ_USER_ID,
    make_acquisitions_headers,
    make_ill_staff_headers,
)
from test_helpers.types import (
    BillingStatus,
    CustodyStatus,
    DeclineReason,
    ItemType,
    MaterialType,
    OfferStatus,
    PatronStatus,
    PodDecision,
    PodOrderStatus,
    RecallStatus,
    RequestStatus,
    ShipmentCondition,
    ShipmentStatus,
    UnfilledReason,
)


def _rota_of_three_partners_with_two_declines(client):
    """A two-attempt rota of three lenders, both permitted rounds spent on declines."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8004",
        full_name="Dan Staff",
        email="dan@u.edu",
        patron_type="STAFF",
        department="LIB",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=5000,
    )
    northu = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    westa = create_partner(
        client,
        code="WESTA",
        name="West Agricultural Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2500,
        avg_turnaround_days=2,
        supplies_electronic=False,
        loan_period_days=21,
        max_renewals=1,
    )
    southc = create_partner(
        client,
        code="SOUTHC",
        name="South College Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=1200,
        avg_turnaround_days=9,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    rota = create_rota(
        client,
        name="Monograph rota",
        material_type=MaterialType.LOAN,
        max_attempts=2,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    for rank, (partner, fee, days) in enumerate(
        ((northu, 2000, 4), (westa, 2500, 2), (southc, 1200, 9)), start=1
    ):
        add_rota_entry(
            client,
            rota["id"],
            partner["id"],
            manual_rank=rank,
            quoted_fee_cents=fee,
            quoted_turnaround_days=days,
        )
    bib_item = create_bib_item(
        client,
        title="Field Guide to Prairie Grasses",
        item_type=ItemType.BOOK,
        publication_year=2015,
        isbn="978-0-000-00002-8",
        list_price_cents=9000,
    )
    request = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-04T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )

    first_offer = run_rota_round(client, request["id"])
    decline_offer(
        client, first_offer["id"], northu["id"], decline_reason=DeclineReason.IN_USE
    )
    second_offer = run_rota_round(client, request["id"])
    decline_offer(
        client, second_offer["id"], westa["id"], decline_reason=DeclineReason.NOT_HELD
    )
    return {
        "patron": patron,
        "northu": northu,
        "westa": westa,
        "southc": southc,
        "rota": rota,
        "bib_item": bib_item,
        "request": request,
        "first_offer": first_offer,
        "second_offer": second_offer,
    }


def test_the_request_re_enters_sourcing_after_each_decline_until_the_budget_is_spent(
    client,
):
    """Two rounds are offered to the two cheapest lenders in turn, each decline sends the
    request back to sourcing without refunding the round, and the third round is refused.

    PRD: "A `PartnerAgent` may only answer for its own partner, and declining drives
    `OFFERED → DECLINED` with a `decline_reason` of `NOT_HELD`, `IN_USE`, `POLICY` or
    `COST` recorded from the payload, sending the request back
    `OFFER_PENDING → SOURCING`." And: "The request must be at `SOURCING`; its
    `attempt_count`, the number of rota rounds already spent, must be strictly below the
    rota's `max_attempts`, or the round is refused with `ERR_ROTA_ATTEMPTS_EXHAUSTED`; and,
    for an article copy whose `copyright_required` is true, an `ACTIVE` clearance must
    exist, as §3.4 explains."

    Design: Difficulty/non_linear_state_machine/request_cycles_sourcing_offer_pending_twice_then_pod_rejection_resets_attempt_budget
    """
    world = _rota_of_three_partners_with_two_declines(client)
    first_offer = world["first_offer"]
    second_offer = world["second_offer"]

    assert first_offer["partner_id"] == world["northu"]["id"]
    assert first_offer["landed_cost_cents"] == 2250
    assert first_offer["attempt_seq"] == 1
    assert second_offer["partner_id"] == world["westa"]["id"]
    assert second_offer["landed_cost_cents"] == 2500
    assert second_offer["attempt_seq"] == 2

    spent = read_request(client, world["request"]["id"])
    assert spent["status"] == RequestStatus.SOURCING
    assert spent["attempt_count"] == 2
    assert spent["unfilled_reason"] == UnfilledReason.NONE

    validate_error(
        client.source_request(world["request"]["id"], headers=make_ill_staff_headers()),
        ApiErrorId.ROTA_ATTEMPTS_EXHAUSTED,
        expected_status=409,
    )
    refused = read_request(client, world["request"]["id"])
    assert refused["attempt_count"] == 2
    assert refused["status"] == RequestStatus.SOURCING


def test_a_rejected_purchase_proposal_sends_the_request_back_with_a_fresh_budget(client):
    """The rejection edge is not a plain revert: the exhausted attempt budget is refilled,
    so the rota can be walked again, but the two lenders that already answered stay out.

    PRD: "Rejecting drives `PROPOSED → REJECTED` and is the system's **second cycle**: the
    request returns `ESCALATED_POD → SOURCING`, and it does so with a **fresh budget** —
    `attempt_count` is reset to 0 and `unfilled_reason` is reset to `NONE`, so a request
    that had exhausted its rota rounds may walk the whole rota again." And: "Finally the
    partner must not already have answered on this request: any partner holding an offer on
    this request whose `status` is `DECLINED`, `EXPIRED` or `ACCEPTED` is excluded from
    every later round, which is what stops the rota loop from asking the same library
    twice."

    Design: Difficulty/non_linear_state_machine/request_cycles_sourcing_offer_pending_twice_then_pod_rejection_resets_attempt_budget
    """
    world = _rota_of_three_partners_with_two_declines(client)
    request_id = world["request"]["id"]

    order = escalate_request(client, request_id, vendor="GOBI")
    assert order["status"] == PodOrderStatus.PROPOSED
    assert order["list_price_cents"] == 9000
    assert read_request(client, request_id)["status"] == RequestStatus.ESCALATED_POD

    rejected = decide_pod_order(
        client,
        order["id"],
        headers=make_acquisitions_headers(ACQ_USER_ID),
        decision=PodDecision.REJECT,
        decision_note="Out of print with every vendor",
    )
    assert rejected["status"] == PodOrderStatus.REJECTED
    assert rejected["decided_by_user_id"] == ACQ_USER_ID

    refreshed = read_request(client, request_id)
    assert refreshed["status"] == RequestStatus.SOURCING
    assert refreshed["attempt_count"] == 0
    assert refreshed["unfilled_reason"] == UnfilledReason.NONE

    third_offer = run_rota_round(client, request_id)
    assert third_offer["partner_id"] == world["southc"]["id"]
    assert third_offer["landed_cost_cents"] == 2700
    assert third_offer["attempt_seq"] == 1
    assert third_offer["status"] == OfferStatus.OFFERED

    walked_again = read_request(client, request_id)
    assert walked_again["status"] == RequestStatus.OFFER_PENDING
    assert walked_again["attempt_count"] == 1

    for offer, partner_key, reason in (
        (world["first_offer"], "northu", DeclineReason.IN_USE),
        (world["second_offer"], "westa", DeclineReason.NOT_HELD),
    ):
        stale = validate_success(
            client.get_supply_offer(offer["id"], headers=make_ill_staff_headers())
        )
        assert stale["status"] == OfferStatus.DECLINED
        assert stale["decline_reason"] == reason
        assert third_offer["partner_id"] != world[partner_key]["id"]


def _recalled_loan_returned_two_weeks_late(client):
    """A loan recalled on 2026-08-05 with three days of grace and returned on 2026-08-15."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8005",
        full_name="Eve Faculty",
        email="eve@u.edu",
        patron_type="FACULTY",
        department="MATH",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=100000,
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
    bib_item = create_bib_item(
        client,
        title="Elliptic Curves in Practice",
        item_type=ItemType.BOOK,
        publication_year=2017,
        isbn="978-0-000-00003-5",
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
    loan = pickup_loan(client, loan["id"])
    assert loan["custody_status"] == CustodyStatus.WITH_PATRON
    assert loan["replacement_cost_cents"] == 9000
    assert_same_instant(loan["due_at"], "2026-08-29T00:00:00.000Z")

    set_clock(client, "2026-08-05T00:00:00.000Z")
    recalled = recall_loan(client, loan["id"], partner["id"], grace_days=3)
    assert recalled["recall_status"] == RecallStatus.RECALL_ISSUED

    set_clock(client, "2026-08-15T00:00:00.000Z")
    returned = return_loan(client, loan["id"])
    return {
        "patron": patron,
        "partner": partner,
        "request": request,
        "loan": returned,
    }


def test_the_return_moves_custody_and_billing_while_the_recall_dimension_settles(client):
    """One call resolves the recall to breached, accrues a tripled fine and prepares the
    return parcel, so the three dimensions of the row end up at three unrelated values.

    PRD: "The recall dimension is resolved first: a loan at `recall_status` `RECALL_ISSUED`
    moves to `RECALL_HONORED` when the clock is at or before `recall_due_at` and to
    `RECALL_BREACHED` when it is later." And: "The multiplier is 3 when the recall dimension
    resolves to `RECALL_BREACHED` at this same call and 1 otherwise." And: "`overdue_fine_cents`
    is written exactly once in the loan's lifetime, by whichever of the two paths fires
    first, and `billing_status` moves `NO_CHARGE → FINE_ACCRUED` when the written figure is
    greater than 0."

    Design: Difficulty/non_linear_state_machine/loan_custody_billing_and_recall_dimensions_advance_independently
    """
    world = _recalled_loan_returned_two_weeks_late(client)
    loan = world["loan"]

    assert loan["custody_status"] == CustodyStatus.RETURN_PREPARED
    assert loan["billing_status"] == BillingStatus.FINE_ACCRUED
    assert loan["recall_status"] == RecallStatus.RECALL_BREACHED
    assert loan["overdue_fine_cents"] == 2250
    assert loan["damage_fee_cents"] == 0
    assert loan["lost_replacement_cents"] == 0
    assert_same_instant(loan["return_prepared_at"], "2026-08-15T00:00:00.000Z")
    assert_same_instant(loan["original_due_at"], "2026-08-29T00:00:00.000Z")
    assert_same_instant(loan["recall_due_at"], "2026-08-08T00:00:00.000Z")
    assert_same_instant(loan["due_at"], "2026-08-08T00:00:00.000Z")

    assert (
        read_request(client, world["request"]["id"])["status"]
        == RequestStatus.RETURN_IN_TRANSIT
    )
    parcels = list_request_shipments(
        client, world["request"]["id"], params={"direction": "RETURN"}
    )
    assert len(parcels) == 1
    assert parcels[0]["status"] == ShipmentStatus.IN_TRANSIT


def test_the_lender_confirmation_advances_two_dimensions_and_leaves_the_recall_alone(
    client,
):
    """The damage confirmation moves custody and billing one step each, records the two
    new charges, and does not disturb the recall value the return had already settled.

    PRD: "A loan may perfectly well sit at custody `RETURNED_TO_LENDER` while its billing is
    still `DAMAGE_BILLED`; the dimensions never gate one another except where a rule below
    says so explicitly." And: "This single call is the deepest cascade in the system, and on
    the `DAMAGED` branch it runs five levels down: the parcel moves to `CONFIRMED_DAMAGED`
    with `confirmed_at` stamped; the loan's custody moves to `RETURNED_TO_LENDER` and its
    `billing_status` to `DAMAGE_BILLED` with `damage_fee_cents` recorded,
    `lender_processing_fee_cents` set to 2500 cents, and `total_charge_cents` and
    `outstanding_cents` recomputed; the request moves to `CLOSED_WITH_DAMAGE` with
    `closed_at` stamped; a notice of kind `DAMAGE_BILLED` is emitted; and the patron's
    `damaged_count`, `lost_count`, `unpaid_balance_cents`, `open_request_count` and
    `final_risk_score` are all re-derived, with the account driven to `BLOCKED` when that
    recomputed `final_risk_score` reaches 40."

    Design: Difficulty/non_linear_state_machine/loan_custody_billing_and_recall_dimensions_advance_independently
    """
    world = _recalled_loan_returned_two_weeks_late(client)
    parcels = list_request_shipments(
        client, world["request"]["id"], params={"direction": "RETURN"}
    )
    confirmed = lender_confirm(
        client,
        parcels[0]["id"],
        world["partner"]["id"],
        condition=ShipmentCondition.DAMAGED,
        damage_fee_cents=3000,
    )
    assert confirmed["status"] == ShipmentStatus.CONFIRMED_DAMAGED
    assert confirmed["direction"] == "RETURN"
    assert_same_instant(confirmed["confirmed_at"], "2026-08-15T00:00:00.000Z")

    settled = read_loan(client, world["loan"]["id"])
    assert settled["custody_status"] == CustodyStatus.RETURNED_TO_LENDER
    assert settled["billing_status"] == BillingStatus.DAMAGE_BILLED
    assert settled["recall_status"] == RecallStatus.RECALL_BREACHED
    assert settled["damage_fee_cents"] == 3000
    assert settled["lender_processing_fee_cents"] == 2500
    assert settled["overdue_fine_cents"] == 2250
    assert settled["lost_replacement_cents"] == 0
    assert settled["total_charge_cents"] == 7750
    assert settled["outstanding_cents"] == 7750

    assert (
        read_request(client, world["request"]["id"])["status"]
        == RequestStatus.CLOSED_WITH_DAMAGE
    )

    patron = read_patron(client, world["patron"]["id"])
    assert patron["damaged_count"] == 1
    assert patron["late_return_count"] == 1
    assert patron["lost_count"] == 0
    assert patron["unpaid_balance_cents"] == 7750
    assert patron["final_risk_score"] == 25
    assert patron["status"] == PatronStatus.ACTIVE
    assert patron["open_request_count"] == 0
