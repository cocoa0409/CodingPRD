"""Declared lifecycle transitions, terminal-state lockouts and transition cascades."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant, kinds_of
from test_helpers.constants import CLOCK_START_INSTANT, CLOCK_START_ISO
from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    create_article_bib_item,
    create_bib_item,
    create_partner,
    create_patron,
    create_rota,
    decide_pod_order,
    decline_offer,
    deliver_electronically,
    escalate_request,
    intake_copy_request,
    intake_request,
    list_clearances,
    list_notifications,
    list_request_shipments,
    pickup_loan,
    read_loan,
    read_partner,
    read_patron,
    read_request,
    receive_pod_order,
    receive_shipment,
    return_loan,
    run_rota_round,
    set_clock,
    settle_loan_charge,
    ship_item,
)
from test_helpers.test_users import (
    ACQ_USER_ID,
    ILL_STAFF_USER_ID,
    make_acquisitions_headers,
    make_ill_staff_headers,
    make_partner_agent_headers,
    make_patron_headers,
)
from test_helpers.types import (
    BillingStatus,
    CustodyStatus,
    DeliveryStatus,
    ItemType,
    LicensedAccessStatus,
    LocalHoldingStatus as Holding,
    MaterialType,
    NotificationKind,
    OfferStatus,
    PodOrderStatus,
    RecallStatus,
    RequestStatus,
    SelectionPolicy,
    ShipmentStatus,
    UnfilledReason,
)
import test_helpers.factories as F


def test_intake_never_exposes_submitted_and_answers_at_sourcing(client):
    """Intake answers 201 with the request already advanced past the transient
    initial value, on the sourcing branch with a fresh rota budget.

    PRD: "Its nominal initial state is `SUBMITTED`, but `SUBMITTED` is a transient
    value that no API response ever exposes: by the time intake answers, the
    request has already moved either `SUBMITTED → SOURCING`, meaning it is ready
    for the rota, or `SUBMITTED → COPYRIGHT_HOLD`, meaning a copyright decision is
    owed first."

    Design: Corner/state_machines/new_ill_request_starts_in_submitted_and_auto_advances_to_sourcing_in_the_same_response
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9010",
        full_name="Gil Reader",
        email="gil@u.edu",
        patron_type="GRAD",
        department="GEOG",
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        material_type=MaterialType.LOAN,
        selection_policy=SelectionPolicy.LANDED_COST,
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
        is_enabled=True,
    )
    bib_item = create_bib_item(
        client,
        title="Rivers of the Interior",
        item_type=ItemType.BOOK,
        publication_year=2013,
        isbn="978-0-000-00030-1",
        local_holding_status=Holding.NONE,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=9000,
    )

    request = validate_success(
        client.create_request(
            F.request_payload(
                patron["id"],
                bib_item["id"],
                rota["id"],
                needed_by="2026-08-09T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_ill_staff_headers(),
        ),
        expected_status=201,
    )

    assert request["status"] == RequestStatus.SOURCING
    assert request["attempt_count"] == 0
    assert request["unfilled_reason"] == UnfilledReason.NONE
    assert request["committed_partner_id"] is None
    assert request["committed_fee_cents"] == 0
    assert request["copyright_required"] is False
    assert request["intake_user_id"] == ILL_STAFF_USER_ID
    assert request["fulfilled_at"] is None
    assert request["closed_at"] is None

    notices = list_notifications(client, request["id"])
    assert kinds_of(notices) == [NotificationKind.REQUEST_SUBMITTED]

    assert read_patron(client, patron["id"])["open_request_count"] == 1


def test_pod_approval_then_receipt_closes_the_request_by_purchase(client):
    """An approved purchase puts the work on order, and receiving it shelves the
    work and closes the original request as filled by purchase.

    PRD: "Receiving an approved purchase requires `status` `APPROVED`, drives
    `APPROVED → RECEIVED` with `received_at` stamped, sets the work's
    `local_holding_status` to `HELD_AVAILABLE`, advances the request
    `ESCALATED_POD → FILLED_BY_PURCHASE` with `closed_at` stamped, emits a notice
    of kind `PURCHASE_RECEIVED`, and re-derives the patron's
    `open_request_count`."

    Design: Corner/state_machines/pod_approval_then_receipt_fills_the_request_by_purchase_and_shelves_the_item
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9011",
        full_name="Hal Reader",
        email="hal@u.edu",
        patron_type="FACULTY",
        department="HIST",
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        material_type=MaterialType.LOAN,
        selection_policy=SelectionPolicy.LANDED_COST,
        max_attempts=1,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    add_rota_entry(client, rota["id"], partner["id"], manual_rank=1)
    bib_item = create_bib_item(
        client,
        title="Cartographies of Empire",
        item_type=ItemType.BOOK,
        publication_year=2011,
        isbn="978-0-000-00031-8",
        local_holding_status=Holding.NONE,
        licensed_access_status=LicensedAccessStatus.NONE,
        list_price_cents=11000,
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
    decline_offer(client, offer["id"], partner["id"], decline_reason="NOT_HELD")

    order = escalate_request(client, request["id"], vendor="AcmeBooks")
    assert order["status"] == PodOrderStatus.PROPOSED
    assert order["vendor"] == "AcmeBooks"
    assert order["list_price_cents"] == 11000
    assert order["escalated_by_user_id"] == ILL_STAFF_USER_ID
    assert order["decided_by_user_id"] is None
    assert order["decided_at"] is None
    assert order["received_at"] is None
    assert read_request(client, request["id"])["status"] == RequestStatus.ESCALATED_POD

    approved = decide_pod_order(
        client, order["id"], headers=make_acquisitions_headers(), decision="APPROVE"
    )
    assert approved["status"] == PodOrderStatus.APPROVED
    assert approved["decided_by_user_id"] == ACQ_USER_ID
    assert_same_instant(approved["decided_at"], CLOCK_START_INSTANT)

    on_order = validate_success(
        client.get_bib_item(bib_item["id"], headers=make_ill_staff_headers())
    )
    assert on_order["local_holding_status"] == Holding.ON_ORDER
    assert read_request(client, request["id"])["status"] == RequestStatus.ESCALATED_POD

    received = receive_pod_order(client, order["id"])
    assert received["status"] == PodOrderStatus.RECEIVED
    assert_same_instant(received["received_at"], CLOCK_START_INSTANT)

    shelved = validate_success(
        client.get_bib_item(bib_item["id"], headers=make_ill_staff_headers())
    )
    assert shelved["local_holding_status"] == Holding.HELD_AVAILABLE

    closed = read_request(client, request["id"])
    assert closed["status"] == RequestStatus.FILLED_BY_PURCHASE
    assert_same_instant(closed["closed_at"], CLOCK_START_INSTANT)

    notices = list_notifications(client, request["id"])
    assert NotificationKind.POD_APPROVED in kinds_of(notices)
    assert NotificationKind.PURCHASE_RECEIVED in kinds_of(notices)
    assert NotificationKind.REQUEST_SUBMITTED in kinds_of(notices)

    assert read_patron(client, patron["id"])["open_request_count"] == 0


def test_pickup_at_exactly_the_hold_shelf_deadline_is_refused(client):
    """A clock that has arrived at `pickup_expires_at` — but has not yet been
    swept — closes the hold shelf to the patron.

    PRD: "It requires the loan to be at custody `AWAITING_PICKUP`, the request's
    inbound parcel to be at `RECEIVED`, and the logical clock to be strictly
    before `pickup_expires_at`; a clock that has reached the hold-shelf deadline
    but has not yet been swept is refused with `ERR_PICKUP_WINDOW_EXPIRED`."

    Design: Corner/state_machines/pickup_at_exactly_the_hold_shelf_expiry_instant_is_refused
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9012",
        full_name="Ivy Reader",
        email="ivy@u.edu",
        patron_type="GRAD",
        department="MATH",
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(client, rota["id"], partner["id"], manual_rank=1)
    bib_item = create_bib_item(
        client,
        title="Measure and Category",
        item_type=ItemType.BOOK,
        publication_year=2016,
        isbn="978-0-000-00032-5",
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
        client, offer["id"], partner["id"], carrier="UPS", tracking_code="1Z-NU-0090"
    )
    loan = receive_shipment(client, shipment["id"])

    assert_same_instant(loan["pickup_expires_at"], "2026-08-08T00:00:00.000Z")
    assert loan["custody_status"] == CustodyStatus.AWAITING_PICKUP

    assert set_clock(client, "2026-08-08T00:00:00Z")

    validate_error(
        client.pickup_loan(loan["id"], headers=make_ill_staff_headers()),
        ApiErrorId.PICKUP_WINDOW_EXPIRED,
        expected_status=409,
    )

    unchanged = read_loan(client, loan["id"])
    assert unchanged["custody_status"] == CustodyStatus.AWAITING_PICKUP
    assert unchanged["picked_up_at"] is None

    assert read_request(client, request["id"])["status"] == RequestStatus.ON_HOLD_SHELF

    parcels = list_request_shipments(client, request["id"])
    assert [parcel["status"] for parcel in parcels] == [ShipmentStatus.RECEIVED]

    notices = list_notifications(client, request["id"])
    assert NotificationKind.UNCLAIMED not in kinds_of(notices)


def test_electronic_delivery_fires_every_declared_side_effect(client):
    """One delivery call writes the delivery window, advances the request and
    emits the readiness notice, without creating any parcel.

    PRD: "The delivery row records `delivered_at` from the logical clock, an
    `expires_at` of `delivered_at` plus 30 days, a `max_downloads` of 3, a
    `download_count` of 0 and a `status` of `AVAILABLE`; the request's
    `fulfilled_at` is set to the clock and a notice of kind
    `ELECTRONIC_DELIVERY_READY` is emitted."

    Design: Corner/state_machines/electronic_delivery_creation_fires_every_declared_side_effect_across_three_entities
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9013",
        full_name="Jun Reader",
        email="jun@u.edu",
        patron_type="FACULTY",
        department="CHEM",
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=1500,
        avg_turnaround_days=2,
        ships_physical=True,
        supplies_electronic=True,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.COPY, max_attempts=3)
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
        issn="2222-0001",
        title="Catalysis in Flow Reactors",
        publication_year=2019,
        journal_title="Journal of Applied Chemistry",
    )
    request = intake_copy_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        pages_requested=20,
        needed_by="2026-08-20T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    offer = run_rota_round(client, request["id"])
    accept_offer(client, offer["id"], partner["id"])

    delivery = deliver_electronically(
        client,
        request["id"],
        partner["id"],
        file_token="scan-2222-0001-a",
        pages_delivered=20,
    )

    assert delivery["status"] == DeliveryStatus.AVAILABLE
    assert delivery["download_count"] == 0
    assert delivery["max_downloads"] == 3
    assert delivery["pages_delivered"] == 20
    assert_same_instant(delivery["delivered_at"], CLOCK_START_INSTANT)
    assert_same_instant(delivery["expires_at"], "2026-08-31T00:00:00.000Z")

    delivered_request = read_request(client, request["id"])
    assert delivered_request["status"] == RequestStatus.DELIVERED_ELECTRONIC
    assert_same_instant(delivered_request["fulfilled_at"], CLOCK_START_INSTANT)
    assert delivered_request["gross_charge_cents"] == 1500
    assert delivered_request["subsidy_cents"] == 1200
    assert delivered_request["net_patron_charge_cents"] == 300

    clearances = list_clearances(client, request["id"])
    assert len(clearances) == 1
    assert clearances[0]["method"] == "PRE_WINDOW_EXEMPT"
    assert clearances[0]["sequence_in_year"] == 0

    usage = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "2222-0001", "calendar_year": 2026},
        )
    )
    assert usage["counted_fill_count"] == 0
    assert usage["pre_window_exempt_count"] == 1

    notices = list_notifications(client, request["id"])
    assert sorted(kinds_of(notices)) == sorted(
        [NotificationKind.REQUEST_SUBMITTED, NotificationKind.ELECTRONIC_DELIVERY_READY]
    )

    _parcels, parcel_meta = validate_paginated(
        client.list_request_shipments(request["id"], headers=make_ill_staff_headers())
    )
    assert parcel_meta["total_count"] == 0


def test_accepting_an_already_accepted_offer_a_second_time_is_refused(client):
    """A repeat of an identical acceptance is refused, so the commitment side
    effects on the partner's balances do not run twice.

    PRD: "The offer opens at `status` `OFFERED`; its other four values are
    `ACCEPTED`, `DECLINED`, `EXPIRED` and `CANCELLED`, and any operation demanding
    an open offer refuses an offer in one of those four with
    `ERR_OFFER_NOT_OPEN`."

    Design: Corner/state_machines/accepting_an_already_accepted_offer_a_second_time_is_refused
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9014",
        full_name="Kai Reader",
        email="kai@u.edu",
        patron_type="FACULTY",
        department="ANTH",
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(client, rota["id"], partner["id"], manual_rank=1)
    bib_item = create_bib_item(
        client,
        title="Kinship and Exchange",
        item_type=ItemType.BOOK,
        publication_year=2010,
        isbn="978-0-000-00033-2",
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
    accepted = accept_offer(client, offer["id"], partner["id"])

    assert accepted["status"] == OfferStatus.ACCEPTED
    committed_partner = read_partner(client, partner["id"])
    assert committed_partner["borrow_payable_cents"] == 2000
    assert committed_partner["borrowed_from_count"] == 1

    validate_error(
        client.accept_offer(
            offer["id"], headers=make_partner_agent_headers(partner["id"])
        ),
        ApiErrorId.OFFER_NOT_OPEN,
        expected_status=409,
    )

    after = read_partner(client, partner["id"])
    assert after["borrow_payable_cents"] == 2000
    assert after["borrowed_from_count"] == 1

    committed_request = read_request(client, request["id"])
    assert committed_request["status"] == RequestStatus.SUPPLY_COMMITTED
    assert committed_request["committed_fee_cents"] == 2000

    assert read_patron(client, patron["id"])["pending_charge_cents"] == 400


def test_declare_lost_from_awaiting_pickup_is_refused(client):
    """Loss may only be declared from the patron's own custody, so a loan still on
    the hold shelf is refused and no charge or infraction is written.

    PRD: "Declaring an item lost is also an `IllBorrowingStaff` action from custody
    `WITH_PATRON`, and it short-circuits the return path entirely."

    Design: Corner/state_machines/declare_lost_from_awaiting_pickup_is_not_a_declared_custody_transition
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9015",
        full_name="Lia Reader",
        email="lia@u.edu",
        patron_type="UNDERGRAD",
        department="PHYS",
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(client, rota["id"], partner["id"], manual_rank=1)
    bib_item = create_bib_item(
        client,
        title="Quantum Optics Notes",
        item_type=ItemType.BOOK,
        publication_year=2018,
        isbn="978-0-000-00034-9",
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
        client, offer["id"], partner["id"], carrier="UPS", tracking_code="1Z-NU-0091"
    )
    loan = receive_shipment(client, shipment["id"])
    assert loan["custody_status"] == CustodyStatus.AWAITING_PICKUP

    validate_error(
        client.declare_loan_lost(loan["id"], headers=make_ill_staff_headers()),
        ApiErrorId.LOAN_INVALID_CUSTODY_STATE,
        expected_status=409,
    )

    unchanged = read_loan(client, loan["id"])
    assert unchanged["custody_status"] == CustodyStatus.AWAITING_PICKUP
    assert unchanged["billing_status"] == BillingStatus.NO_CHARGE
    assert unchanged["lost_replacement_cents"] == 0
    assert unchanged["outstanding_cents"] == 0

    quiet_patron = read_patron(client, patron["id"])
    assert quiet_patron["lost_count"] == 0
    assert quiet_patron["unpaid_balance_cents"] == 0
    assert quiet_patron["status"] == "ACTIVE"

    assert read_request(client, request["id"])["status"] == RequestStatus.ON_HOLD_SHELF


def test_cancelling_an_already_cancelled_request_is_locked_out(client):
    """A second cancellation of a terminal request is refused and emits no second
    cancellation notice.

    PRD: "The last seven of those are terminal: once a request is `CLOSED`,
    `CLOSED_WITH_DAMAGE`, `CLOSED_LOST`, `UNCLAIMED`, `CANCELLED`, `UNFILLED` or
    `FILLED_BY_PURCHASE`, nothing moves it again, and every operation that demands
    a live request refuses with `ERR_REQUEST_INVALID_STATE`."

    Design: Corner/state_machines/cancelling_an_already_cancelled_request_is_locked_out
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9016",
        full_name="Mia Reader",
        email="mia@u.edu",
        patron_type="GRAD",
        department="SOCI",
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(client, rota["id"], partner["id"], manual_rank=1)
    bib_item = create_bib_item(
        client,
        title="Networks of Trust",
        item_type=ItemType.BOOK,
        publication_year=2020,
        isbn="978-0-000-00035-6",
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

    cancelled = validate_success(
        client.cancel_request(
            request["id"], headers=make_patron_headers(patron["id"])
        )
    )
    assert cancelled["status"] == RequestStatus.CANCELLED
    assert_same_instant(cancelled["closed_at"], CLOCK_START_INSTANT)

    validate_error(
        client.cancel_request(
            request["id"], headers=make_patron_headers(patron["id"])
        ),
        ApiErrorId.REQUEST_INVALID_STATE,
        expected_status=409,
    )

    still_cancelled = read_request(client, request["id"])
    assert still_cancelled["status"] == RequestStatus.CANCELLED
    assert_same_instant(still_cancelled["closed_at"], CLOCK_START_INSTANT)

    _notices, notice_meta = validate_paginated(
        client.list_notifications(
            request["id"],
            headers=make_ill_staff_headers(),
            params={"kind": NotificationKind.REQUEST_CANCELLED},
        )
    )
    assert notice_meta["total_count"] == 1

    assert read_patron(client, patron["id"])["open_request_count"] == 0


def test_cancelling_a_request_awaiting_a_lender_reply_cascades_the_open_offer(client):
    """Cancelling while the lender has not answered moves the open offer to
    cancelled and leaves the partner's balances at zero, since nothing was ever
    committed.

    PRD: "Every `ACTIVE` clearance of the request is voided, which releases its slot
    back into the (`issn`, `calendar_year`) allowance as §3.4 describes. Every
    `OFFERED` offer moves to `CANCELLED` and every `PROPOSED` purchase order moves
    to `CANCELLED`."

    Design: Corner/state_machines/cancelling_a_request_awaiting_a_lender_reply_cascades_the_open_offer_to_cancelled
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9017",
        full_name="Ned Reader",
        email="ned@u.edu",
        patron_type="STAFF",
        department="ARCH",
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(
        client,
        material_type=MaterialType.LOAN,
        max_attempts=3,
        offer_response_hours=48,
    )
    add_rota_entry(client, rota["id"], partner["id"], manual_rank=1)
    bib_item = create_bib_item(
        client,
        title="Vernacular Architecture",
        item_type=ItemType.BOOK,
        publication_year=2007,
        isbn="978-0-000-00036-3",
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
    assert offer["status"] == OfferStatus.OFFERED
    assert_same_instant(offer["respond_by"], "2026-08-03T00:00:00.000Z")

    cancelled = validate_success(
        client.cancel_request(request["id"], headers=make_ill_staff_headers())
    )
    assert cancelled["status"] == RequestStatus.CANCELLED

    cascaded_offer = validate_success(
        client.get_supply_offer(offer["id"], headers=make_ill_staff_headers())
    )
    assert cascaded_offer["status"] == OfferStatus.CANCELLED

    untouched_partner = read_partner(client, partner["id"])
    assert untouched_partner["borrow_payable_cents"] == 0
    assert untouched_partner["borrowed_from_count"] == 0

    final_request = read_request(client, request["id"])
    assert final_request["committed_partner_id"] is None
    assert final_request["attempt_count"] == 1

    _offers, offer_meta = validate_paginated(
        client.list_supply_offers(
            headers=make_ill_staff_headers(),
            params={"request_id": request["id"], "status": OfferStatus.CANCELLED},
        )
    )
    assert offer_meta["total_count"] == 1

    final_patron = read_patron(client, patron["id"])
    assert final_patron["open_request_count"] == 0
    assert final_patron["pending_charge_cents"] == 0


def test_waiving_an_overdue_fine_returns_the_patron_ledger_to_zero(client):
    """A waiver clears the loan's outstanding amount and the patron's unpaid
    balance while leaving every paid bucket at zero.

    PRD: "A `WAIVE` is the opposite: it is permitted from `FINE_ACCRUED`,
    `DAMAGE_BILLED` or `LOST_BILLED`, it forces `outstanding_cents` to 0 **without
    touching any paid bucket** — the four paid figures and `total_paid_cents` stay
    exactly as they were, so the audit trail still shows that nothing was
    collected — and it drives `billing_status` to `CHARGE_WAIVED`."

    Design: Corner/state_machines/waiving_an_overdue_fine_syncs_the_patron_unpaid_balance_ledger_to_zero
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9018",
        full_name="Ola Reader",
        email="ola@u.edu",
        patron_type="UNDERGRAD",
        department="STAT",
    )
    partner = create_partner(
        client,
        code="SHORTL",
        name="Short Loan Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        ships_physical=True,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=7,
        max_renewals=1,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(client, rota["id"], partner["id"], manual_rank=1)
    bib_item = create_bib_item(
        client,
        title="Robust Regression",
        item_type=ItemType.BOOK,
        publication_year=2019,
        isbn="978-0-000-00037-0",
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
        client, offer["id"], partner["id"], carrier="UPS", tracking_code="1Z-SL-0092"
    )
    loan = receive_shipment(client, shipment["id"])
    assert_same_instant(loan["due_at"], "2026-08-08T00:00:00.000Z")
    pickup_loan(client, loan["id"])

    set_clock(client, "2026-08-15T00:00:00Z")
    returned = return_loan(client, loan["id"])
    assert returned["billing_status"] == BillingStatus.FINE_ACCRUED
    assert returned["overdue_fine_cents"] == 750
    assert returned["outstanding_cents"] == 750

    fined_patron = read_patron(client, patron["id"])
    assert fined_patron["unpaid_balance_cents"] == 750
    assert fined_patron["late_return_count"] == 1

    waived = settle_loan_charge(client, loan["id"], F.waive_settlement_payload())
    assert waived["billing_status"] == BillingStatus.CHARGE_WAIVED
    assert waived["outstanding_cents"] == 0
    assert waived["paid_overdue_cents"] == 0
    assert waived["total_paid_cents"] == 0
    assert waived["custody_status"] == CustodyStatus.RETURN_PREPARED
    assert waived["recall_status"] == RecallStatus.NONE

    settled_patron = read_patron(client, patron["id"])
    assert settled_patron["unpaid_balance_cents"] == 0
    assert settled_patron["late_return_count"] == 1
    assert settled_patron["final_risk_score"] == 6
