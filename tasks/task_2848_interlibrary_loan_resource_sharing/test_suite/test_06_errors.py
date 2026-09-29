"""Error-catalogue coverage: each identifier reached from its own trigger."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_same_instant
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.fixtures import (
    accept_offer,
    add_rota_entry,
    create_agreement,
    create_article_bib_item,
    create_bib_item,
    create_lending_charge,
    create_partner,
    create_patron,
    create_rota,
    deliver_electronically,
    download_delivery,
    draft_invoice,
    intake_copy_request,
    intake_request,
    partner_version,
    read_patron,
    read_request,
    receive_shipment,
    run_ops,
    run_rota_round,
    set_clock,
    ship_item,
)
from test_helpers.test_users import (
    ILL_STAFF_ALT_USER_ID,
    ILL_STAFF_USER_ID,
    make_accountant_headers,
    make_admin_headers,
    make_ill_staff_headers,
    make_partner_agent_headers,
    make_patron_headers,
)
from test_helpers.types import (
    AgreementStatus,
    ClearanceMethod,
    CustodyStatus,
    DeliveryStatus,
    InvoiceStatus,
    ItemType,
    LendingChargeStatus,
    MaterialType,
    RequestStatus,
    ShipmentDirection,
    ShipmentStatus,
)

UNUSED_IDS = {
    "patron": "00000000-0000-4000-8000-000000000b01",
    "partner": "00000000-0000-4000-8000-000000000b02",
    "agreement": "00000000-0000-4000-8000-000000000b03",
    "rota": "00000000-0000-4000-8000-000000000b04",
    "rota_entry": "00000000-0000-4000-8000-000000000b05",
    "bib_item": "00000000-0000-4000-8000-000000000b06",
    "request": "00000000-0000-4000-8000-000000000b07",
    "offer": "00000000-0000-4000-8000-000000000b08",
    "shipment": "00000000-0000-4000-8000-000000000b09",
    "loan": "00000000-0000-4000-8000-000000000b0a",
    "delivery": "00000000-0000-4000-8000-000000000b0b",
    "pod_order": "00000000-0000-4000-8000-000000000b0c",
    "invoice": "00000000-0000-4000-8000-000000000b0d",
    "lending_charge": "00000000-0000-4000-8000-000000000b0e",
}


def test_the_auth_rungs_return_unauthenticated_then_non_owner_then_malformed_input(
    client,
):
    """One read is walked down three rungs of the same ladder, and the ownership failure
    is reported as a non-owner rather than as an unauthorized role.

    PRD: "**25 —** entity-backed role owns the addressed resource:
    `ERR_NOT_RESOURCE_OWNER` (403), on every endpoint reachable by `Patron` or
    `PartnerAgent`."

    Design: Corner/errors/the_auth_rungs_return_unauthenticated_then_non_owner_then_malformed_input
    """
    set_clock(client, CLOCK_START_ISO)
    owner = create_patron(
        client,
        external_id="P-OWNER",
        full_name="Owen Owner",
        email="owen@u.edu",
        patron_type="GRAD",
        department="LING",
    )
    stranger = create_patron(
        client,
        external_id="P-STRANGER",
        full_name="Stan Stranger",
        email="stan@u.edu",
        patron_type="GRAD",
        department="LING",
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
        title="Phonology Handbook",
        item_type=ItemType.BOOK,
        publication_year=2015,
        isbn="978-0-000-00061-5",
        list_price_cents=9000,
    )
    request = intake_request(
        client,
        owner["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )

    validate_error(
        client.get_request(request["id"], headers={}),
        ApiErrorId.UNAUTHENTICATED,
        expected_status=401,
    )
    validate_error(
        client.get_request(request["id"], headers=make_patron_headers(stranger["id"])),
        ApiErrorId.NOT_RESOURCE_OWNER,
        expected_status=403,
    )

    own_read = validate_success(
        client.get_request(request["id"], headers=make_patron_headers(owner["id"]))
    )
    assert own_read["patron_id"] == owner["id"]

    over_limit = client.list_requests(
        headers=make_ill_staff_headers(),
        params={"patron_id": owner["id"], "limit": 101},
    )
    validate_error(over_limit, ApiErrorId.INVALID_REQUEST, expected_status=400)
    body = over_limit.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert "patron_id" not in body["data"]

    _rows, meta = validate_paginated(
        client.list_requests(
            headers=make_ill_staff_headers(),
            params={"patron_id": owner["id"], "limit": 100},
        )
    )
    assert meta["total_count"] == 1


def test_segregation_of_duties_outranks_the_clearance_not_required_gate(client):
    """One article request that never needed a clearance answers two different errors
    depending only on which staff identity asks.

    PRD: "In the first case `X-User-ID` is compared against the order's
    `escalated_by_user_id`; in the second against the request's `intake_user_id`. An
    equal comparison in either case is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP
    403)."

    Design: Corner/errors/segregation_of_duties_outranks_the_clearance_not_required_gate
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9050",
        full_name="Gil Reader",
        email="gil@u.edu",
        patron_type="FACULTY",
        department="PHYS",
        max_open_requests=5,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=1500,
        avg_turnaround_days=2,
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
    article = create_article_bib_item(
        client,
        issn="7777-0001",
        title="Muon anomalies",
        journal_title="Physics Letters Now",
        publication_year=2024,
        list_price_cents=4000,
    )
    request = intake_copy_request(
        client,
        patron["id"],
        article["id"],
        rota["id"],
        pages_requested=10,
        needed_by="2026-08-20T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    assert request["status"] == RequestStatus.SOURCING
    assert request["intake_user_id"] == ILL_STAFF_USER_ID

    validate_error(
        client.create_copyright_clearance(
            request["id"],
            F.royalty_clearance_payload(1500),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    validate_error(
        client.create_copyright_clearance(
            request["id"],
            F.royalty_clearance_payload(1500),
            headers=make_ill_staff_headers(ILL_STAFF_ALT_USER_ID),
        ),
        ApiErrorId.COPYRIGHT_CLEARANCE_NOT_REQUIRED,
        expected_status=422,
    )

    rows, meta = validate_paginated(
        client.list_copyright_clearances(
            request["id"], headers=make_ill_staff_headers()
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["method"] == ClearanceMethod.CONTU_FREE
    assert rows[0]["sequence_in_year"] == 1

    usage = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "7777-0001", "calendar_year": 2026},
        )
    )
    assert usage["counted_fill_count"] == 1
    assert usage["royalty_paid_count"] == 0


def test_the_three_electronic_delivery_refusals_are_each_reachable_in_priority_order(
    client,
):
    """Two sibling delivery windows separate the download-cap refusal, the merely-lapsed
    refusal and the already-swept refusal on one endpoint.

    PRD: "Likewise on the download path: an expired-and-exhausted delivery reports
    `ERR_DELIVERY_NOT_AVAILABLE` from rung 44, an available-but-past-`expires_at`
    delivery reports `ERR_DELIVERY_EXPIRED` from rung 66, and only a live delivery with
    no downloads left reaches `ERR_DELIVERY_DOWNLOAD_CAP_REACHED` at rung 73."

    Design: Corner/errors/the_three_electronic_delivery_refusals_are_each_reachable_in_priority_order
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9051",
        full_name="Hal Reader",
        email="hal@u.edu",
        patron_type="FACULTY",
        department="CHEM",
        max_open_requests=5,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=1500,
        avg_turnaround_days=2,
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

    deliveries = []
    for issn, title, token in (
        ("8888-0001", "Reaction pathways I", "tok-8888-0001"),
        ("8888-0002", "Reaction pathways II", "tok-8888-0002"),
    ):
        article = create_article_bib_item(
            client,
            issn=issn,
            title=title,
            journal_title="Chem Notes",
            publication_year=2024,
            list_price_cents=4000,
        )
        request = intake_copy_request(
            client,
            patron["id"],
            article["id"],
            rota["id"],
            pages_requested=10,
            needed_by="2026-08-20T00:00:00.000Z",
            max_supply_fee_cents=5000,
        )
        offer = run_rota_round(client, request["id"])
        accept_offer(client, offer["id"], partner["id"])
        delivery = deliver_electronically(
            client,
            request["id"],
            partner["id"],
            file_token=token,
            pages_delivered=10,
        )
        deliveries.append((request, delivery))

    (_req_1, del_1), (req_2, del_2) = deliveries
    assert del_1["max_downloads"] == 3
    assert_same_instant(del_1["expires_at"], "2026-08-31T00:00:00.000Z")
    assert del_1["status"] == DeliveryStatus.AVAILABLE

    for expected_count, expected_status in (
        (1, DeliveryStatus.AVAILABLE),
        (2, DeliveryStatus.AVAILABLE),
        (3, DeliveryStatus.EXHAUSTED),
    ):
        taken = download_delivery(client, del_1["id"], patron["id"])
        assert taken["download_count"] == expected_count
        assert taken["status"] == expected_status

    validate_error(
        client.create_download(
            del_1["id"], headers=make_patron_headers(patron["id"])
        ),
        ApiErrorId.DELIVERY_DOWNLOAD_CAP_REACHED,
        expected_status=409,
    )
    after_cap = validate_success(
        client.get_electronic_delivery(del_1["id"], headers=make_admin_headers())
    )
    assert after_cap["download_count"] == 3
    assert after_cap["status"] == DeliveryStatus.EXHAUSTED

    set_clock(client, "2026-08-31T00:00:00.000Z")
    validate_error(
        client.create_download(
            del_2["id"], headers=make_patron_headers(patron["id"])
        ),
        ApiErrorId.DELIVERY_EXPIRED,
        expected_status=409,
    )

    summary = run_ops(client)
    assert summary["deliveries_expired"] == 1

    validate_error(
        client.create_download(
            del_2["id"], headers=make_patron_headers(patron["id"])
        ),
        ApiErrorId.DELIVERY_NOT_AVAILABLE,
        expected_status=409,
    )

    swept_1 = validate_success(
        client.get_electronic_delivery(del_1["id"], headers=make_admin_headers())
    )
    assert swept_1["status"] == DeliveryStatus.EXHAUSTED
    swept_2 = validate_success(
        client.get_electronic_delivery(del_2["id"], headers=make_admin_headers())
    )
    assert swept_2["status"] == DeliveryStatus.EXPIRED
    assert read_request(client, req_2["id"])["status"] == RequestStatus.CLOSED


def test_shipment_gates_reject_the_wrong_direction_and_the_second_receipt(client):
    """One parcel yields the same invalid-state refusal from the direction half of the
    gate and then from the status half of it.

    PRD: "**42 —** the parcel is `IN_TRANSIT` and its `direction` matches the operation,
    `INBOUND` for borrower receipt and `RETURN` for lender confirmation:
    `ERR_SHIPMENT_INVALID_STATE` (409), on both parcel operations."

    Design: Corner/errors/shipment_gates_reject_the_wrong_direction_and_the_second_receipt
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9052",
        full_name="Ida Reader",
        email="ida@u.edu",
        patron_type="GRAD",
        department="CLAS",
        max_open_requests=5,
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
        title="Latin Epigraphy",
        item_type=ItemType.BOOK,
        publication_year=2009,
        isbn="978-0-000-00062-2",
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
    parcel = ship_item(
        client,
        offer["id"],
        partner["id"],
        carrier="UPS",
        tracking_code="1Z-DIR-0062",
        insured_value_cents=9000,
    )
    assert parcel["direction"] == ShipmentDirection.INBOUND
    assert parcel["status"] == ShipmentStatus.IN_TRANSIT

    validate_error(
        client.lender_confirm_shipment(
            parcel["id"],
            F.lender_confirm_payload(),
            headers=make_partner_agent_headers(partner["id"]),
        ),
        ApiErrorId.SHIPMENT_INVALID_STATE,
        expected_status=409,
    )
    still_moving = validate_success(
        client.get_shipment(parcel["id"], headers=make_admin_headers())
    )
    assert still_moving["status"] == ShipmentStatus.IN_TRANSIT
    assert still_moving["confirmed_at"] is None
    _rows, meta = validate_paginated(
        client.list_request_loans(request["id"], headers=make_ill_staff_headers())
    )
    assert meta["total_count"] == 0

    loan = receive_shipment(client, parcel["id"])
    assert loan["custody_status"] == CustodyStatus.AWAITING_PICKUP
    received = validate_success(
        client.get_shipment(parcel["id"], headers=make_admin_headers())
    )
    assert received["status"] == ShipmentStatus.RECEIVED
    assert_same_instant(received["received_at"], CLOCK_START_ISO)

    validate_error(
        client.receive_shipment(parcel["id"], headers=make_ill_staff_headers()),
        ApiErrorId.SHIPMENT_INVALID_STATE,
        expected_status=409,
    )
    rows, meta = validate_paginated(
        client.list_request_loans(request["id"], headers=make_ill_staff_headers())
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [loan["id"]]


def test_material_mismatch_open_period_and_inactive_supersede_target_are_each_refused(
    client,
):
    """Three unrelated business gates on one partner: a copy pointed at a loan pool, an
    issue inside a running month, and a supersede aimed at an expired agreement.

    PRD: "It declares a `service_type` of `LOAN`, meaning a physical item will be
    shipped, or `COPY`, meaning an article scan will be delivered electronically, and
    this value must equal the named rota's `material_type` — a mismatch is refused with
    `ERR_ROTA_MATERIAL_MISMATCH`."

    PRD: "An invoice opens at `DRAFT` and is issued by the accountant, which requires
    that the settlement period be closed — the logical clock must have reached
    `period_end`, and an attempt to issue a month that is still running is refused with
    `ERR_INVOICE_PERIOD_NOT_CLOSED`."

    PRD: "The named agreement must still be `ACTIVE`, otherwise the create is refused
    with `ERR_AGREEMENT_NOT_ACTIVE`, and an identifier naming nothing at all is
    `ERR_AGREEMENT_NOT_FOUND`."

    Design: Corner/errors/material_mismatch_open_period_and_inactive_supersede_target_are_each_refused
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9053",
        full_name="Jan Reader",
        email="jan@u.edu",
        patron_type="GRAD",
        department="MUSI",
        max_open_requests=5,
    )
    partner = create_partner(
        client,
        code="EASTV",
        name="East Valley College Library",
        consortium_code="EASTERN",
        base_lending_fee_cents=1750,
        avg_turnaround_days=6,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    old_agreement = create_agreement(
        client,
        partner["id"],
        effective_from="2026-08-01T00:00:00.000Z",
        effective_to="2026-08-10T00:00:00.000Z",
        turnaround_guarantee_days=7,
        balance_tolerance_items=3,
    )
    assert old_agreement["status"] == AgreementStatus.ACTIVE

    loan_rota = create_rota(client, material_type=MaterialType.LOAN, max_attempts=3)
    add_rota_entry(
        client,
        loan_rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=1750,
        quoted_turnaround_days=6,
    )
    article = create_article_bib_item(
        client,
        issn="9999-0001",
        title="Notation in the 14th century",
        journal_title="Musicology Review",
        publication_year=2024,
        list_price_cents=4000,
    )
    charge = create_lending_charge(
        client,
        partner["id"],
        item_title="Bound volume 3",
        charge_cents=2000,
        incurred_at="2026-08-05T00:00:00.000Z",
    )

    validate_error(
        client.create_request(
            F.copy_request_payload(
                patron["id"],
                article["id"],
                loan_rota["id"],
                pages_requested=10,
                needed_by="2026-08-20T00:00:00.000Z",
                max_supply_fee_cents=5000,
            ),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.ROTA_MATERIAL_MISMATCH,
        expected_status=422,
    )
    assert read_patron(client, patron["id"])["open_request_count"] == 0

    set_clock(client, "2026-08-15T00:00:00.000Z")
    invoice = draft_invoice(client, partner["id"], "2026-08")
    assert invoice["status"] == InvoiceStatus.DRAFT

    validate_error(
        client.issue_invoice(invoice["id"], headers=make_accountant_headers()),
        ApiErrorId.INVOICE_PERIOD_NOT_CLOSED,
        expected_status=409,
    )
    unissued = validate_success(
        client.get_invoice(invoice["id"], headers=make_accountant_headers())
    )
    assert unissued["status"] == InvoiceStatus.DRAFT
    assert unissued["issued_at"] is None
    still_open = validate_success(
        client.get_lending_charge(charge["id"], headers=make_accountant_headers())
    )
    assert still_open["status"] == LendingChargeStatus.OPEN

    summary = run_ops(client)
    assert summary["agreements_expired"] == 1
    lapsed = validate_success(
        client.get_agreement(old_agreement["id"], headers=make_admin_headers())
    )
    assert lapsed["status"] == AgreementStatus.EXPIRED

    validate_error(
        client.create_agreement(
            F.agreement_payload(
                partner_id=partner["id"],
                expected_partner_version=partner_version(client, partner["id"]),
                effective_from="2026-08-15T00:00:00.000Z",
                effective_to="2026-10-01T00:00:00.000Z",
                settlement_mode="NET",
                turnaround_guarantee_days=5,
                supersedes_agreement_id=old_agreement["id"],
            ),
            headers=make_admin_headers(),
        ),
        ApiErrorId.AGREEMENT_NOT_ACTIVE,
        expected_status=409,
    )
    rows, meta = validate_paginated(
        client.list_agreements(
            headers=make_admin_headers(), params={"partner_id": partner["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == old_agreement["id"]


def test_every_not_found_error_is_reachable_from_its_own_read_path(client):
    """Fourteen entity families each answer an unused identifier with their own dedicated
    not-found identifier rather than one shared generic code.

    PRD: "**30 —** every identifier in the URL path names an existing row, resolved left
    to right: 404 with the code for the first missing row — `ERR_PATRON_NOT_FOUND`,
    `ERR_PARTNER_NOT_FOUND`, `ERR_BIB_ITEM_NOT_FOUND`, `ERR_ROTA_NOT_FOUND`,
    `ERR_ROTA_ENTRY_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
    `ERR_OFFER_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`,
    `ERR_DELIVERY_NOT_FOUND`, `ERR_POD_ORDER_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` or
    `ERR_LENDING_CHARGE_NOT_FOUND`."

    Design: Corner/errors/every_not_found_error_is_reachable_from_its_own_read_path
    """
    set_clock(client, CLOCK_START_ISO)
    headers = make_admin_headers()

    reads = (
        (client.get_patron, UNUSED_IDS["patron"], ApiErrorId.PATRON_NOT_FOUND),
        (client.get_partner, UNUSED_IDS["partner"], ApiErrorId.PARTNER_NOT_FOUND),
        (client.get_agreement, UNUSED_IDS["agreement"], ApiErrorId.AGREEMENT_NOT_FOUND),
        (client.get_rota, UNUSED_IDS["rota"], ApiErrorId.ROTA_NOT_FOUND),
        (
            client.get_rota_entry,
            UNUSED_IDS["rota_entry"],
            ApiErrorId.ROTA_ENTRY_NOT_FOUND,
        ),
        (client.get_bib_item, UNUSED_IDS["bib_item"], ApiErrorId.BIB_ITEM_NOT_FOUND),
        (client.get_request, UNUSED_IDS["request"], ApiErrorId.REQUEST_NOT_FOUND),
        (client.get_supply_offer, UNUSED_IDS["offer"], ApiErrorId.OFFER_NOT_FOUND),
        (client.get_shipment, UNUSED_IDS["shipment"], ApiErrorId.SHIPMENT_NOT_FOUND),
        (client.get_loan, UNUSED_IDS["loan"], ApiErrorId.LOAN_NOT_FOUND),
        (
            client.get_electronic_delivery,
            UNUSED_IDS["delivery"],
            ApiErrorId.DELIVERY_NOT_FOUND,
        ),
        (client.get_pod_order, UNUSED_IDS["pod_order"], ApiErrorId.POD_ORDER_NOT_FOUND),
        (client.get_invoice, UNUSED_IDS["invoice"], ApiErrorId.INVOICE_NOT_FOUND),
        (
            client.get_lending_charge,
            UNUSED_IDS["lending_charge"],
            ApiErrorId.LENDING_CHARGE_NOT_FOUND,
        ),
    )
    assert len(reads) == 14
    assert len({expected for _read, _rid, expected in reads}) == 14

    seen = []
    for read, resource_id, expected_error in reads:
        body = validate_error(
            read(resource_id, headers=headers), expected_error, expected_status=404
        )
        seen.append(body["error_id"])
    assert len(set(seen)) == 14
