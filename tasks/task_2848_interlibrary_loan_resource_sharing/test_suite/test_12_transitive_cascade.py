"""Two chains that run several levels down from a single call: a lender's damage report,
and the nightly hold-shelf sweep."""

from test_helpers.assertions import assert_all_counters_zero, assert_same_instant
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    create_bib_item,
    create_partner,
    create_patron,
    create_rota,
    intake_request,
    lender_confirm,
    list_notifications,
    list_request_shipments,
    load_infraction,
    pickup_loan,
    read_loan,
    read_patron,
    read_request,
    receive_shipment,
    return_loan,
    run_ops,
    run_rota_round,
    set_clock,
    ship_item,
)
from test_helpers.types import (
    BillingStatus,
    CustodyStatus,
    InfractionKind,
    ItemType,
    MaterialType,
    NotificationKind,
    PatronStatus,
    RecallStatus,
    RequestStatus,
    ShipmentCondition,
    ShipmentDirection,
    ShipmentStatus,
)


def _loan_returned_early_by_a_patron_with_history(client):
    """A patron already carrying one loss and one damage returns an item nineteen days
    early, so the return parcel is in transit with no fine attached."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8006",
        full_name="Finn Grad",
        email="finn@u.edu",
        patron_type="GRAD",
        department="BIO",
        max_open_requests=5,
        max_concurrent_loans=3,
        unpaid_balance_cap_cents=100000,
    )
    load_infraction(client, patron["id"], InfractionKind.LOST, count=1)
    patron = load_infraction(client, patron["id"], InfractionKind.DAMAGED, count=1)
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
        title="Freshwater Ecology",
        item_type=ItemType.BOOK,
        publication_year=2013,
        isbn="978-0-000-00004-2",
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
    pickup_loan(client, loan["id"])

    set_clock(client, "2026-08-10T00:00:00.000Z")
    returned = return_loan(client, loan["id"])
    assert returned["overdue_fine_cents"] == 0
    assert returned["billing_status"] == BillingStatus.NO_CHARGE
    assert returned["recall_status"] == RecallStatus.NONE
    parcels = list_request_shipments(
        client, request["id"], params={"direction": ShipmentDirection.RETURN}
    )
    return {
        "patron_before": patron,
        "patron": patron,
        "partner": partner,
        "request": request,
        "loan": returned,
        "return_parcel": parcels[0],
    }


def test_the_damage_report_travels_from_the_parcel_through_the_loan_to_the_request(
    client,
):
    """One lender call moves the parcel, then the loan's custody and billing with two new
    charges, then closes the request and files the notice that tells the patron.

    PRD: "On the `DAMAGED` branch the declared `damage_fee_cents` must be at or below the
    loan's `replacement_cost_cents` snapshot, otherwise the confirmation is refused with
    `ERR_DAMAGE_FEE_EXCEEDS_REPLACEMENT` — a library may not bill more for a scratch than
    the book is worth." And: "This single call is the deepest cascade in the system, and on
    the `DAMAGED` branch it runs five levels down: the parcel moves to `CONFIRMED_DAMAGED`
    with `confirmed_at` stamped; the loan's custody moves to `RETURNED_TO_LENDER` and its
    `billing_status` to `DAMAGE_BILLED` with `damage_fee_cents` recorded,
    `lender_processing_fee_cents` set to 2500 cents, and `total_charge_cents` and
    `outstanding_cents` recomputed; the request moves to `CLOSED_WITH_DAMAGE` with
    `closed_at` stamped; a notice of kind `DAMAGE_BILLED` is emitted; and the patron's
    `damaged_count`, `lost_count`, `unpaid_balance_cents`, `open_request_count` and
    `final_risk_score` are all re-derived, with the account driven to `BLOCKED` when that
    recomputed `final_risk_score` reaches 40."

    Design: Difficulty/transitive_cascade/lender_damage_confirmation_cascades_five_levels_from_shipment_to_patron_block
    """
    world = _loan_returned_early_by_a_patron_with_history(client)
    confirmed = lender_confirm(
        client,
        world["return_parcel"]["id"],
        world["partner"]["id"],
        condition=ShipmentCondition.DAMAGED,
        damage_fee_cents=3000,
    )
    assert confirmed["status"] == ShipmentStatus.CONFIRMED_DAMAGED
    assert_same_instant(confirmed["confirmed_at"], "2026-08-10T00:00:00.000Z")

    loan = read_loan(client, world["loan"]["id"])
    assert loan["custody_status"] == CustodyStatus.RETURNED_TO_LENDER
    assert loan["billing_status"] == BillingStatus.DAMAGE_BILLED
    assert loan["overdue_fine_cents"] == 0
    assert loan["damage_fee_cents"] == 3000
    assert loan["lender_processing_fee_cents"] == 2500
    assert loan["lost_replacement_cents"] == 0
    assert loan["total_charge_cents"] == 5500
    assert loan["outstanding_cents"] == 5500

    closed = read_request(client, world["request"]["id"])
    assert closed["status"] == RequestStatus.CLOSED_WITH_DAMAGE
    assert_same_instant(closed["closed_at"], "2026-08-10T00:00:00.000Z")

    notices = list_notifications(
        client,
        world["request"]["id"],
        params={"kind": NotificationKind.DAMAGE_BILLED},
    )
    assert len(notices) == 1
    assert notices[0]["kind"] == NotificationKind.DAMAGE_BILLED


def test_the_damage_report_reaches_the_patron_counters_and_blocks_the_account(client):
    """The fourth level moves two counters at once, and only their combination pushes the
    fifth level over the block threshold, which the pre-damage score was still under.

    PRD: "`damaged_count` is `historical_damaged_count` plus the number of that patron's
    loans whose `billing_status` is `DAMAGE_BILLED`." And: "`unpaid_balance_cents` is
    `historical_unpaid_cents` plus the sum of `outstanding_cents` over that patron's loans
    whose `billing_status` is `FINE_ACCRUED`, `DAMAGE_BILLED` or `LOST_BILLED`." And: "It is
    stored as `final_risk_score`, and a patron whose `final_risk_score` reaches 40 or more
    has their `status` set to `BLOCKED`."

    Design: Difficulty/transitive_cascade/lender_damage_confirmation_cascades_five_levels_from_shipment_to_patron_block
    """
    world = _loan_returned_early_by_a_patron_with_history(client)
    before = read_patron(client, world["patron"]["id"])
    assert before["provisional_risk_score"] == 37
    assert before["status"] == PatronStatus.ACTIVE
    assert before["damaged_count"] == 1
    assert before["unpaid_balance_cents"] == 0

    lender_confirm(
        client,
        world["return_parcel"]["id"],
        world["partner"]["id"],
        condition=ShipmentCondition.DAMAGED,
        damage_fee_cents=3000,
    )

    after = read_patron(client, world["patron"]["id"])
    assert after["damaged_count"] == 2
    assert after["lost_count"] == 1
    assert after["late_return_count"] == 0
    assert after["unclaimed_count"] == 0
    assert after["unpaid_balance_cents"] == 5500
    assert after["open_request_count"] == 0
    assert after["final_risk_score"] == 50
    assert after["status"] == PatronStatus.BLOCKED


def _loan_left_on_the_hold_shelf_until_its_deadline(client):
    """A received parcel whose loan is never collected, with the clock moved to the exact
    hold-shelf deadline."""
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-8007",
        full_name="Gus Undergrad",
        email="gus@u.edu",
        patron_type="UNDERGRAD",
        department="ENGL",
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
        title="Victorian Serial Fiction",
        item_type=ItemType.BOOK,
        publication_year=2009,
        isbn="978-0-000-00005-9",
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
    assert_same_instant(loan["pickup_expires_at"], "2026-08-08T00:00:00.000Z")
    assert read_request(client, request["id"])["status"] == RequestStatus.ON_HOLD_SHELF
    assert len(list_request_shipments(client, request["id"])) == 1

    set_clock(client, "2026-08-08T00:00:00.000Z")
    return {"patron": patron, "request": request, "loan": loan}


def test_the_hold_shelf_sweep_prepares_a_return_parcel_and_closes_the_request(client):
    """The sweep fires at the deadline instant itself and drives three levels: the loan's
    custody, a brand new return parcel, and the closure of the request with its notice.

    PRD: "**Step 4** abandons hold-shelf items: every loan at custody `AWAITING_PICKUP`
    whose `pickup_expires_at` the clock has reached moves to `UNCLAIMED_RETURN_PREPARED`
    with `return_prepared_at` stamped, a return parcel is created, the request is closed as
    `UNCLAIMED` with `closed_at` stamped, a notice of kind `UNCLAIMED` is emitted, and the
    patron's `unclaimed_count`, `open_request_count` and `final_risk_score` are
    re-derived." And: "Its response is not an entity but a summary object carrying `ran_at`,
    the clock instant at which it ran, together with `agreements_expired`, `offers_expired`,
    `recalls_breached`, `pickups_abandoned`, `deliveries_expired`, `shipments_lost`,
    `requests_escalated`, `requests_unfilled` and `patrons_blocked`, each counting the rows
    that step actually changed on this run."

    Design: Difficulty/transitive_cascade/hold_shelf_expiry_sweep_cascades_four_levels_from_loan_to_patron_unclaimed_counter
    """
    world = _loan_left_on_the_hold_shelf_until_its_deadline(client)
    summary = run_ops(client)
    assert_same_instant(summary["ran_at"], "2026-08-08T00:00:00.000Z")
    assert summary["pickups_abandoned"] == 1
    assert summary["patrons_blocked"] == 0

    loan = read_loan(client, world["loan"]["id"])
    assert loan["custody_status"] == CustodyStatus.UNCLAIMED_RETURN_PREPARED
    assert_same_instant(loan["return_prepared_at"], "2026-08-08T00:00:00.000Z")
    assert loan["picked_up_at"] is None
    assert loan["billing_status"] == BillingStatus.NO_CHARGE
    assert loan["outstanding_cents"] == 0

    returns = list_request_shipments(
        client, world["request"]["id"], params={"direction": ShipmentDirection.RETURN}
    )
    assert len(returns) == 1
    assert returns[0]["status"] == ShipmentStatus.IN_TRANSIT
    assert_same_instant(returns[0]["shipped_at"], "2026-08-08T00:00:00.000Z")
    assert len(list_request_shipments(client, world["request"]["id"])) == 2

    closed = read_request(client, world["request"]["id"])
    assert closed["status"] == RequestStatus.UNCLAIMED
    assert_same_instant(closed["closed_at"], "2026-08-08T00:00:00.000Z")
    assert_same_instant(closed["fulfilled_at"], CLOCK_START_ISO)

    notices = list_notifications(
        client, world["request"]["id"], params={"kind": NotificationKind.UNCLAIMED}
    )
    assert len(notices) == 1


def test_the_unclaimed_chain_scores_the_patron_and_a_second_sweep_changes_nothing(client):
    """The fourth level of the same chain moves the patron's own counters without touching
    any money bucket, and re-running the sweep at the same clock adds nothing to the chain.

    PRD: "`unclaimed_count` is `historical_unclaimed_count` plus the number of that patron's
    requests whose `status` is `UNCLAIMED`." And: "And the sweep is **idempotent**: running
    it a second time without moving the logical clock performs no further writes and returns
    all-zero counters."

    Design: Difficulty/transitive_cascade/hold_shelf_expiry_sweep_cascades_four_levels_from_loan_to_patron_unclaimed_counter
    """
    world = _loan_left_on_the_hold_shelf_until_its_deadline(client)
    run_ops(client)

    patron = read_patron(client, world["patron"]["id"])
    assert patron["unclaimed_count"] == 1
    assert patron["open_request_count"] == 0
    assert patron["unpaid_balance_cents"] == 0
    assert patron["final_risk_score"] == 8
    assert patron["status"] == PatronStatus.ACTIVE

    second = run_ops(client)
    assert_all_counters_zero(second)
    assert len(list_request_shipments(client, world["request"]["id"])) == 2

    unchanged = read_patron(client, world["patron"]["id"])
    assert unchanged["unclaimed_count"] == 1
    assert unchanged["final_risk_score"] == 8
    assert read_request(client, world["request"]["id"])["status"] == (
        RequestStatus.UNCLAIMED
    )
