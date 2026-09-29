"""Endpoint contracts: partial updates, action endpoints, links and computed reads."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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
    create_article_bib_item,
    create_bib_item,
    create_lending_charge,
    create_partner,
    create_patron,
    create_rota,
    deliver_electronically,
    draft_invoice,
    intake_copy_request,
    list_clearances,
    issue_invoice,
    read_partner,
    read_request,
    run_ops,
    run_rota_round,
    set_clock,
    update_bib_item,
)
from test_helpers.test_users import (
    make_accountant_headers,
    make_ill_staff_headers,
    make_partner_agent_headers,
)
from test_helpers.types import (
    ClearanceMethod,
    DeliveryStatus,
    InvoiceStatus,
    ItemType,
    LendingChargeStatus,
    LicensedAccessStatus,
    LocalHoldingStatus,
    MaterialType,
    OfferStatus,
    RequestStatus,
    SettlementMode,
)


def test_bib_item_patch_updates_only_the_supplied_fields_and_bumps_the_version(client):
    """A partial update rewrites exactly the fields it carries, leaves the omitted
    optional facts as created, and bumps the version on every call.

    PRD: "Holdings facts change, so a `LibraryAdmin` or `AcquisitionsLibrarian` may
    amend a record's `local_holding_status`, `licensed_access_status`, `embargo_months`
    or `list_price_cents`; each amendment increments that record's `version` by 1."

    Design: Corner/endpoints/bib_item_patch_updates_only_the_supplied_fields_and_bumps_the_version
    """
    set_clock(client, CLOCK_START_ISO)
    created = create_bib_item(
        client,
        title="Glacial Landforms",
        item_type=ItemType.BOOK,
        publication_year=2014,
        isbn="978-0-000-00060-8",
        local_holding_status=LocalHoldingStatus.NONE,
        licensed_access_status=LicensedAccessStatus.LICENSED_EMBARGOED,
        embargo_months=24,
        list_price_cents=5000,
    )

    patched = update_bib_item(
        client,
        created["id"],
        local_holding_status=LocalHoldingStatus.ON_ORDER,
        list_price_cents=6400,
    )
    assert patched["local_holding_status"] == LocalHoldingStatus.ON_ORDER
    assert patched["list_price_cents"] == 6400
    assert patched["licensed_access_status"] == LicensedAccessStatus.LICENSED_EMBARGOED
    assert patched["embargo_months"] == 24
    assert patched["version"] == created["version"] + 1

    read_back = validate_success(
        client.get_bib_item(created["id"], headers=make_ill_staff_headers())
    )
    assert read_back["local_holding_status"] == LocalHoldingStatus.ON_ORDER
    assert read_back["list_price_cents"] == 6400
    assert read_back["version"] == patched["version"]
    assert_same_instant(read_back["created_at"], created["created_at"])

    repatched = update_bib_item(client, created["id"], list_price_cents=6400)
    assert repatched["list_price_cents"] == 6400
    assert repatched["version"] == patched["version"] + 1

    validate_error(
        client.update_bib_item(
            created["id"],
            F.bib_item_update_payload(list_price_cents=7000),
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.UNAUTHORIZED,
        expected_status=403,
    )


def test_issuing_an_invoice_flips_its_open_lending_charge_lines_to_invoiced(client):
    """Drafting leaves every line `OPEN`; only issuing claims the in-period line, and
    the partner's receivable drops by the face value rather than the surcharged value.

    PRD: "Issuing stamps `issued_at` from the clock, moves every `OPEN` lending charge
    line inside the period to `INVOICED`, and re-derives the partner's
    `lend_receivable_cents`."

    Design: Corner/endpoints/issuing_an_invoice_flips_its_open_lending_charge_lines_to_invoiced
    """
    set_clock(client, "2026-09-01T00:00:00Z")
    partner = create_partner(
        client,
        code="EASTV",
        name="East Valley College Library",
        consortium_code="EASTERN",
        base_lending_fee_cents=1750,
        avg_turnaround_days=6,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    in_period = create_lending_charge(
        client,
        partner["id"],
        item_title="In period line",
        service_type="LOAN",
        charge_cents=2000,
        incurred_at="2026-08-05T00:00:00.000Z",
    )
    out_of_period = create_lending_charge(
        client,
        partner["id"],
        item_title="Out of period line",
        service_type="COPY",
        charge_cents=3000,
        incurred_at="2026-09-01T00:00:00.000Z",
    )
    assert in_period["status"] == LendingChargeStatus.OPEN
    assert read_partner(client, partner["id"])["lend_receivable_cents"] == 5000

    invoice = draft_invoice(client, partner["id"], "2026-08")
    assert invoice["status"] == InvoiceStatus.DRAFT
    assert invoice["issued_at"] is None
    assert invoice["receivable_total_cents"] == 2150
    assert invoice["settlement_variant"] == SettlementMode.GROSS
    assert (
        validate_success(
            client.get_lending_charge(in_period["id"], headers=make_accountant_headers())
        )["status"]
        == LendingChargeStatus.OPEN
    )

    issued = issue_invoice(client, invoice["id"])
    assert issued["status"] == InvoiceStatus.ISSUED
    assert_same_instant(issued["issued_at"], "2026-09-01T00:00:00.000Z")

    assert (
        validate_success(
            client.get_lending_charge(in_period["id"], headers=make_accountant_headers())
        )["status"]
        == LendingChargeStatus.INVOICED
    )
    assert (
        validate_success(
            client.get_lending_charge(
                out_of_period["id"], headers=make_accountant_headers()
            )
        )["status"]
        == LendingChargeStatus.OPEN
    )
    assert read_partner(client, partner["id"])["lend_receivable_cents"] == 3000

    open_rows, open_meta = validate_paginated(
        client.list_partner_lending_charges(
            partner["id"],
            headers=make_accountant_headers(),
            params={"status": LendingChargeStatus.OPEN},
        )
    )
    assert open_meta["total_count"] == 1
    assert [row["id"] for row in open_rows] == [out_of_period["id"]]

    validate_error(
        client.issue_invoice(invoice["id"], headers=make_accountant_headers()),
        ApiErrorId.INVOICE_INVALID_STATE,
        expected_status=409,
    )
    assert (
        validate_success(
            client.get_lending_charge(in_period["id"], headers=make_accountant_headers())
        )["status"]
        == LendingChargeStatus.INVOICED
    )
    assert (
        validate_success(
            client.get_lending_charge(
                out_of_period["id"], headers=make_accountant_headers()
            )
        )["status"]
        == LendingChargeStatus.OPEN
    )


def test_one_ops_run_sweeps_two_step_families_and_the_rerun_is_a_no_op(client):
    """One sweep crosses both an offer deadline and a delivery window, leaving the other
    seven counters at zero, and the immediate rerun writes nothing at all.

    PRD: "And the sweep is **idempotent**: running it a second time without moving the
    logical clock performs no further writes and returns all-zero counters."

    Design: Corner/endpoints/one_ops_run_sweeps_two_independent_step_families_and_the_rerun_is_a_no_op
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9040",
        full_name="Eli Reader",
        email="eli@u.edu",
        patron_type="FACULTY",
        department="STAT",
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
    rota = create_rota(
        client,
        material_type=MaterialType.COPY,
        max_attempts=3,
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
    article_a = create_article_bib_item(
        client,
        issn="6666-0001",
        title="Bayesian shrinkage",
        journal_title="Statistics Letters",
        publication_year=2023,
        list_price_cents=4000,
    )
    article_b = create_article_bib_item(
        client,
        issn="6666-0002",
        title="Sequential designs",
        journal_title="Statistics Letters",
        publication_year=2023,
        list_price_cents=4000,
    )
    request_a = intake_copy_request(
        client,
        patron["id"],
        article_a["id"],
        rota["id"],
        pages_requested=10,
        needed_by="2026-08-20T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    offer_a = run_rota_round(client, request_a["id"])
    assert_same_instant(offer_a["respond_by"], "2026-08-03T00:00:00.000Z")

    request_b = intake_copy_request(
        client,
        patron["id"],
        article_b["id"],
        rota["id"],
        pages_requested=10,
        needed_by="2026-08-20T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    offer_b = run_rota_round(client, request_b["id"])
    accept_offer(client, offer_b["id"], partner["id"])
    delivery = deliver_electronically(
        client,
        request_b["id"],
        partner["id"],
        file_token="tok-6666-0002",
        pages_delivered=10,
    )
    assert delivery["status"] == DeliveryStatus.AVAILABLE
    assert delivery["max_downloads"] == 3
    assert_same_instant(delivery["expires_at"], "2026-08-31T00:00:00.000Z")

    set_clock(client, "2026-09-05T00:00:00Z")
    first_run = run_ops(client)
    assert_same_instant(first_run["ran_at"], "2026-09-05T00:00:00.000Z")
    assert first_run["offers_expired"] == 1
    assert first_run["deliveries_expired"] == 1
    assert first_run["agreements_expired"] == 0
    assert first_run["recalls_breached"] == 0
    assert first_run["pickups_abandoned"] == 0
    assert first_run["shipments_lost"] == 0
    assert first_run["requests_escalated"] == 0
    assert first_run["requests_unfilled"] == 0
    assert first_run["patrons_blocked"] == 0

    assert (
        validate_success(
            client.get_supply_offer(offer_a["id"], headers=make_ill_staff_headers())
        )["status"]
        == OfferStatus.EXPIRED
    )
    cascaded = read_request(client, request_a["id"])
    assert cascaded["status"] == RequestStatus.SOURCING
    assert cascaded["attempt_count"] == 1

    swept_delivery = validate_success(
        client.get_electronic_delivery(
            delivery["id"], headers=make_ill_staff_headers()
        )
    )
    assert swept_delivery["status"] == DeliveryStatus.EXPIRED
    assert swept_delivery["download_count"] == 0

    second_run = run_ops(client)
    assert_same_instant(second_run["ran_at"], "2026-09-05T00:00:00.000Z")
    assert second_run["offers_expired"] == 0
    assert second_run["deliveries_expired"] == 0
    assert second_run["requests_escalated"] == 0
    assert second_run["requests_unfilled"] == 0
    assert second_run["patrons_blocked"] == 0

    validate_error(
        client.create_download(
            delivery["id"], headers=make_ill_staff_headers()
        ),
        ApiErrorId.DELIVERY_NOT_AVAILABLE,
        expected_status=409,
    )


def test_lending_charge_links_to_an_existing_partner_and_is_reachable_from_it(client):
    """The body foreign key is validated before anything is written, and the created row
    is reachable only from the partner it names.

    PRD: "every foreign key supplied in the request body names an existing row, checked
    in the order the fields are listed for that endpoint in §3: 404 with
    `ERR_PATRON_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`, `ERR_BIB_ITEM_NOT_FOUND`,
    `ERR_ROTA_NOT_FOUND` or `ERR_AGREEMENT_NOT_FOUND` as appropriate." And: "A lending
    charge opens at `status` `OPEN` and moves to `INVOICED` when an invoice containing it
    is issued; creating one re-derives the partner's `lent_to_count`,
    `net_borrow_imbalance_items` and `lend_receivable_cents`."

    Design: Corner/endpoints/lending_charge_links_to_an_existing_partner_and_is_reachable_from_that_partner
    """
    set_clock(client, CLOCK_START_ISO)
    eastv = create_partner(
        client,
        code="EASTV",
        name="East Valley College Library",
        consortium_code="EASTERN",
        base_lending_fee_cents=1750,
        avg_turnaround_days=6,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    westa = create_partner(
        client,
        code="WESTA",
        name="West Annex Library",
        consortium_code="WESTERN",
        base_lending_fee_cents=2500,
        avg_turnaround_days=2,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    assert eastv["lend_receivable_cents"] == 0

    validate_error(
        client.create_lending_charge(
            F.lending_charge_payload(
                NON_EXISTENT_UUID,
                item_title="Ghost loan",
                service_type="LOAN",
                charge_cents=2200,
                incurred_at="2026-08-01T00:00:00.000Z",
            ),
            headers=make_accountant_headers(),
        ),
        ApiErrorId.PARTNER_NOT_FOUND,
        expected_status=404,
    )
    assert read_partner(client, eastv["id"])["lend_receivable_cents"] == 0

    charge = create_lending_charge(
        client,
        eastv["id"],
        item_title="Bound periodical volume 12",
        service_type="LOAN",
        charge_cents=2200,
        incurred_at="2026-08-01T00:00:00.000Z",
    )
    assert charge["partner_id"] == eastv["id"]
    assert charge["status"] == LendingChargeStatus.OPEN

    eastv_rows, eastv_meta = validate_paginated(
        client.list_partner_lending_charges(
            eastv["id"], headers=make_accountant_headers()
        )
    )
    assert eastv_meta["total_count"] == 1
    assert [row["id"] for row in eastv_rows] == [charge["id"]]

    westa_rows, westa_meta = validate_paginated(
        client.list_partner_lending_charges(
            westa["id"], headers=make_accountant_headers()
        )
    )
    assert westa_meta["total_count"] == 0
    assert westa_rows == []

    credited = read_partner(client, eastv["id"])
    assert credited["lend_receivable_cents"] == 2200
    assert credited["lent_to_count"] == 1


def test_copyright_usage_read_splits_counted_fills_from_pre_window_exempt_fills(client):
    """The report is keyed on the journal and the year, not on one record: two articles
    sharing an ISSN aggregate, and the pre-window fill is reported separately.

    PRD: "Staff can see the state of the pool before they take a request in: the
    copyright-usage report answers, for one `issn` and one `calendar_year`, the
    `counted_fill_count` consumed so far, the `free_fills_remaining` out of five, and for
    context the `royalty_paid_count` and `pre_window_exempt_count` recorded under the
    other two methods."

    Design: Corner/endpoints/copyright_usage_read_splits_counted_fills_from_pre_window_exempt_fills
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9041",
        full_name="Fay Reader",
        email="fay@u.edu",
        patron_type="FACULTY",
        department="HIST",
        max_open_requests=10,
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
    old_article = create_article_bib_item(
        client,
        issn="5555-0001",
        title="Guild records of 1650",
        journal_title="Early Modern Review",
        publication_year=2019,
        list_price_cents=4000,
    )
    new_article = create_article_bib_item(
        client,
        issn="5555-0001",
        title="Guild records revisited",
        journal_title="Early Modern Review",
        publication_year=2023,
        list_price_cents=4000,
    )

    old_request = intake_copy_request(
        client,
        patron["id"],
        old_article["id"],
        rota["id"],
        pages_requested=8,
        needed_by="2026-08-20T00:00:00.000Z",
        max_supply_fee_cents=5000,
    )
    assert old_request["status"] == RequestStatus.SOURCING

    new_requests = [
        intake_copy_request(
            client,
            patron["id"],
            new_article["id"],
            rota["id"],
            pages_requested=8,
            needed_by="2026-08-20T00:00:00.000Z",
            max_supply_fee_cents=5000,
        )
        for _ in range(2)
    ]

    usage = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "5555-0001", "calendar_year": 2026},
        )
    )
    assert usage["issn"] == "5555-0001"
    assert usage["calendar_year"] == 2026
    assert usage["counted_fill_count"] == 2
    assert usage["free_fills_remaining"] == 3
    assert usage["royalty_paid_count"] == 0
    assert usage["pre_window_exempt_count"] == 1

    second_free = list_clearances(client, new_requests[1]["id"])
    assert len(second_free) == 1
    assert second_free[0]["method"] == ClearanceMethod.CONTU_FREE
    assert second_free[0]["sequence_in_year"] == 2

    exempt = list_clearances(client, old_request["id"])
    assert len(exempt) == 1
    assert exempt[0]["method"] == ClearanceMethod.PRE_WINDOW_EXEMPT
    assert exempt[0]["sequence_in_year"] == 0

    prior_year = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "5555-0001", "calendar_year": 2025},
        )
    )
    assert prior_year["counted_fill_count"] == 0
    assert prior_year["free_fills_remaining"] == 5
    assert prior_year["royalty_paid_count"] == 0
    assert prior_year["pre_window_exempt_count"] == 0


def test_settle_accepts_dispute_from_the_partner_but_reserves_payment(client):
    """One endpoint carries three actions of differing authority, and the dispute round
    trip leaves the original issue instant intact.

    PRD: "`PartnerAgent` acts for a lending library: accepting or declining offers,
    shipping, confirming what came back, recalling an item, delivering a scan, and
    disputing or reinstating an invoice." And: "Reinstating drives `DISPUTED → ISSUED`,
    clears `dispute_reason` back to null, and pointedly **does not rewrite `issued_at`**
    — the original issue instant survives the round trip, which is what makes the
    `ISSUED → DISPUTED → ISSUED` cycle auditable and repeatable."

    Design: Corner/endpoints/settle_accepts_dispute_from_the_partner_but_reserves_payment_for_the_accountant
    """
    set_clock(client, "2026-09-01T00:00:00Z")
    partner = create_partner(
        client,
        code="EASTV",
        name="East Valley College Library",
        consortium_code="EASTERN",
        base_lending_fee_cents=1750,
        avg_turnaround_days=6,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    create_lending_charge(
        client,
        partner["id"],
        item_title="Bound volume 7",
        service_type="LOAN",
        charge_cents=2000,
        incurred_at="2026-08-05T00:00:00.000Z",
    )
    invoice = draft_invoice(client, partner["id"], "2026-08")
    issued = issue_invoice(client, invoice["id"])
    assert issued["status"] == InvoiceStatus.ISSUED
    assert_same_instant(issued["issued_at"], "2026-09-01T00:00:00.000Z")

    set_clock(client, "2026-09-05T00:00:00Z")

    validate_error(
        client.settle_invoice(
            invoice["id"],
            F.invoice_settle_payload(action="PAY"),
            headers=make_partner_agent_headers(partner["id"]),
        ),
        ApiErrorId.UNAUTHORIZED,
        expected_status=403,
    )
    untouched = validate_success(
        client.get_invoice(invoice["id"], headers=make_accountant_headers())
    )
    assert untouched["status"] == InvoiceStatus.ISSUED
    assert untouched["settled_at"] is None

    disputed = validate_success(
        client.settle_invoice(
            invoice["id"],
            F.invoice_settle_payload(
                action="DISPUTE",
                dispute_reason="Volume 7 was returned undamaged",
            ),
            headers=make_partner_agent_headers(partner["id"]),
        )
    )
    assert disputed["status"] == InvoiceStatus.DISPUTED
    assert disputed["dispute_reason"] == "Volume 7 was returned undamaged"
    assert disputed["settled_at"] is None

    reinstated = validate_success(
        client.settle_invoice(
            invoice["id"],
            F.invoice_settle_payload(action="REINSTATE"),
            headers=make_partner_agent_headers(partner["id"]),
        )
    )
    assert reinstated["status"] == InvoiceStatus.ISSUED
    assert reinstated["dispute_reason"] is None
    assert_same_instant(reinstated["issued_at"], "2026-09-01T00:00:00.000Z")

    paid = validate_success(
        client.settle_invoice(
            invoice["id"],
            F.invoice_settle_payload(action="PAY"),
            headers=make_accountant_headers(),
        )
    )
    assert paid["status"] == InvoiceStatus.PAID
    assert_same_instant(paid["settled_at"], "2026-09-05T00:00:00.000Z")

    validate_error(
        client.settle_invoice(
            invoice["id"],
            F.invoice_settle_payload(
                action="DISPUTE", dispute_reason="Changed our mind"
            ),
            headers=make_accountant_headers(),
        ),
        ApiErrorId.INVOICE_INVALID_STATE,
        expected_status=409,
    )
