"""Cross-cutting layers: concurrency guards, cumulative allowances, derived balances,
filtered paging, and the immediate visibility of every write."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers.api_errors import ApiErrorId
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
    draft_invoice,
    intake_copy_request,
    intake_request,
    issue_invoice,
    list_clearances,
    partner_version,
    read_partner,
    read_patron,
    read_request,
    read_rota,
    run_rota_round,
    set_clock,
)
from test_helpers.test_users import (
    make_accountant_headers,
    make_admin_headers,
    make_ill_staff_headers,
)
from test_helpers.types import (
    AgreementStatus,
    ClearanceMethod,
    FeeWaiverMode,
    InvoiceStatus,
    ItemType,
    LendingChargeStatus,
    MaterialType,
    OfferStatus,
    RequestStatus,
    ServiceType,
    SettlementMode,
)


def test_all_three_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one(
    client,
):
    """The two partner-guarded writes and the rota-guarded write each refuse a version the
    caller has already spent, and each accepts the refreshed one.

    PRD: "Both agreement creation and invoice generation increment the parent `Partner`'s
    `version` by 1 as part of their own success, and rota-entry creation increments the
    parent `Rota`'s `version` by 1, which is what makes a second write with the same
    declared version fail."

    Design: Corner/cross_cutting_complexity_layers/all_three_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
    """
    set_clock(client, CLOCK_START_ISO)
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
    partner_two = create_partner(
        client,
        code="WESTA",
        name="Western State Library",
        consortium_code="MIDWEST",
        base_lending_fee_cents=2500,
        avg_turnaround_days=2,
        supplies_electronic=False,
        loan_period_days=21,
        max_renewals=1,
    )
    rota = create_rota(
        client,
        name="Monograph rota",
        material_type=MaterialType.LOAN,
        max_attempts=3,
        auto_escalate_pod=False,
        offer_response_hours=48,
    )
    partner_v0 = partner["version"]
    rota_v0 = rota["version"]
    assert partner_v0 == 1
    assert rota_v0 == 1

    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        expected_rota_version=rota_v0,
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    rota_v1 = read_rota(client, rota["id"])["version"]
    assert rota_v1 == 2

    stale_entry_payload = F.rota_entry_payload(
        rota_id=rota["id"],
        partner_id=partner_two["id"],
        expected_rota_version=rota_v0,
        manual_rank=2,
        quoted_fee_cents=2500,
        quoted_turnaround_days=2,
    )
    validate_error(
        client.create_rota_entry(stale_entry_payload, headers=make_admin_headers()),
        ApiErrorId.STALE_ROTA_VERSION,
        expected_status=412,
    )
    rows, meta = validate_paginated(
        client.list_rota_entries(rota["id"], headers=make_ill_staff_headers())
    )
    assert meta["total_count"] == 1
    assert [row["partner_id"] for row in rows] == [partner["id"]]

    second_entry = add_rota_entry(
        client,
        rota["id"],
        partner_two["id"],
        expected_rota_version=rota_v1,
        manual_rank=2,
        quoted_fee_cents=2500,
        quoted_turnaround_days=2,
    )
    assert read_rota(client, rota["id"])["version"] == 3
    rows, meta = validate_paginated(
        client.list_rota_entries(rota["id"], headers=make_ill_staff_headers())
    )
    assert meta["total_count"] == 2
    assert second_entry["id"] in {row["id"] for row in rows}
    assert {row["partner_id"] for row in rows} == {partner["id"], partner_two["id"]}

    agreement = create_agreement(
        client,
        partner["id"],
        expected_partner_version=partner_v0,
        fee_waiver_mode=FeeWaiverMode.CAPPED,
        capped_waiver_cents=1000,
        settlement_mode=SettlementMode.NET,
        turnaround_guarantee_days=5,
        effective_from="2026-08-01T00:00:00.000Z",
        effective_to="2027-08-01T00:00:00.000Z",
        balance_tolerance_items=3,
    )
    assert agreement["status"] == AgreementStatus.ACTIVE

    stale_agreement_payload = F.agreement_payload(
        partner_id=partner["id"],
        expected_partner_version=partner_v0,
        fee_waiver_mode=FeeWaiverMode.FULL,
        settlement_mode=SettlementMode.GROSS,
        turnaround_guarantee_days=4,
        effective_from="2026-10-01T00:00:00.000Z",
        effective_to="2027-10-01T00:00:00.000Z",
    )
    validate_error(
        client.create_agreement(stale_agreement_payload, headers=make_admin_headers()),
        ApiErrorId.STALE_PARTNER_VERSION,
        expected_status=412,
    )
    rows, meta = validate_paginated(
        client.list_agreements(
            headers=make_admin_headers(), params={"partner_id": partner["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == agreement["id"]
    assert rows[0]["status"] == AgreementStatus.ACTIVE

    partner_v1 = partner_version(client, partner["id"])
    assert partner_v1 == 2

    set_clock(client, "2026-09-01T00:00:00.000Z")
    validate_error(
        client.create_invoice(
            partner["id"],
            F.invoice_payload("2026-08", partner_v0),
            headers=make_accountant_headers(),
        ),
        ApiErrorId.STALE_PARTNER_VERSION,
        expected_status=412,
    )

    invoice = draft_invoice(
        client, partner["id"], "2026-08", expected_partner_version=partner_v1
    )
    assert invoice["settlement_variant"] == SettlementMode.NET
    assert invoice["gross_amount_cents"] == 0
    assert partner_version(client, partner["id"]) == 3

    rows, meta = validate_paginated(
        client.list_partner_invoices(
            partner["id"],
            headers=make_accountant_headers(),
            params={"period_month": "2026-08"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == invoice["id"]


def test_the_cumulative_copyright_allowance_resets_when_the_calendar_year_rolls_over(
    client,
):
    """The five-fill allowance is exhausted for one journal in one year and is available
    again one instant into the next year, with no write having reset anything.

    PRD: "This system tracks that allowance with a counter keyed on the pair of `issn`
    and `calendar_year` — and on nothing else." And: "Otherwise the allowance is spent:
    **no clearance row is created at all**, and the request parks at `COPYRIGHT_HOLD`."

    Design: Corner/cross_cutting_complexity_layers/the_cumulative_copyright_allowance_resets_when_the_calendar_year_rolls_over
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9062",
        full_name="Ada Reader",
        email="ada@u.edu",
        patron_type="FACULTY",
        department="PHYS",
        max_open_requests=20,
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
        name="Article rota",
        material_type=MaterialType.COPY,
        max_attempts=3,
    )
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    article = create_article_bib_item(
        client,
        issn="2211-0007",
        title="Muon flux at altitude",
        journal_title="Journal of Cosmic Rays",
        publication_year=2024,
    )

    def file_copy(needed_by):
        return intake_copy_request(
            client,
            patron["id"],
            article["id"],
            rota["id"],
            pages_requested=10,
            needed_by=needed_by,
            max_supply_fee_cents=5000,
        )

    for _ in range(5):
        assert file_copy("2026-08-25T00:00:00.000Z")["status"] == RequestStatus.SOURCING

    spent = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "2211-0007", "calendar_year": 2026},
        )
    )
    assert spent["counted_fill_count"] == 5
    assert spent["free_fills_remaining"] == 0

    parked = file_copy("2026-08-25T00:00:00.000Z")
    assert parked["status"] == RequestStatus.COPYRIGHT_HOLD
    rows, meta = validate_paginated(
        client.list_copyright_clearances(
            parked["id"], headers=make_ill_staff_headers()
        )
    )
    assert rows == []
    assert meta["total_count"] == 0

    unchanged = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "2211-0007", "calendar_year": 2026},
        )
    )
    assert unchanged["counted_fill_count"] == 5
    assert unchanged["free_fills_remaining"] == 0

    set_clock(client, "2027-01-01T00:00:00.000Z")
    new_year = file_copy("2027-01-20T00:00:00.000Z")
    assert new_year["status"] == RequestStatus.SOURCING

    fresh = list_clearances(client, new_year["id"])
    assert len(fresh) == 1
    assert fresh[0]["method"] == ClearanceMethod.CONTU_FREE
    assert fresh[0]["calendar_year"] == 2027
    assert fresh[0]["sequence_in_year"] == 1

    usage_2027 = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "2211-0007", "calendar_year": 2027},
        )
    )
    assert usage_2027["counted_fill_count"] == 1
    assert usage_2027["free_fills_remaining"] == 4

    usage_2026 = validate_success(
        client.get_copyright_usage(
            headers=make_ill_staff_headers(),
            params={"issn": "2211-0007", "calendar_year": 2026},
        )
    )
    assert usage_2026["counted_fill_count"] == 5
    assert usage_2026["free_fills_remaining"] == 0
    assert read_request(client, parked["id"])["status"] == RequestStatus.COPYRIGHT_HOLD


def test_partner_balance_fields_are_recomputed_on_every_write_that_moves_their_source_rows(
    client,
):
    """Two derived partner figures with different source predicates are tracked across
    three writes, and issuing the invoice moves one of them without touching the other.

    PRD: "`lent_to_count` is the number of lending charges recorded against that
    partner." And: "`lend_receivable_cents` is the sum of `charge_cents` over that
    partner's lending charges whose `status` is still `OPEN`."

    Design: Corner/cross_cutting_complexity_layers/partner_balance_fields_are_recomputed_on_every_write_that_moves_their_source_rows
    """
    set_clock(client, CLOCK_START_ISO)
    partner = create_partner(
        client,
        code="NORTHU",
        name="North University Library",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    assert partner["lend_receivable_cents"] == 0
    assert partner["lent_to_count"] == 0
    assert partner["net_borrow_imbalance_items"] == 0

    first = create_lending_charge(
        client,
        partner["id"],
        item_title="Outbound lend, volume 1",
        service_type=ServiceType.LOAN,
        charge_cents=1200,
        incurred_at="2026-08-03T00:00:00.000Z",
    )
    assert first["status"] == LendingChargeStatus.OPEN
    after_first = read_partner(client, partner["id"])
    assert after_first["lend_receivable_cents"] == 1200
    assert after_first["lent_to_count"] == 1
    assert after_first["net_borrow_imbalance_items"] == -1

    second = create_lending_charge(
        client,
        partner["id"],
        item_title="Outbound lend, volume 2",
        service_type=ServiceType.COPY,
        charge_cents=2000,
        incurred_at="2026-08-07T00:00:00.000Z",
    )
    after_second = read_partner(client, partner["id"])
    assert after_second["lend_receivable_cents"] == 3200
    assert after_second["lent_to_count"] == 2
    assert after_second["net_borrow_imbalance_items"] == -2

    set_clock(client, "2026-09-01T00:00:00.000Z")
    invoice = draft_invoice(
        client,
        partner["id"],
        "2026-08",
        expected_partner_version=after_second["version"],
    )
    assert invoice["receivable_total_cents"] == 3440
    assert invoice["lend_line_count"] == 2

    after_draft = read_partner(client, partner["id"])
    assert after_draft["lend_receivable_cents"] == 3200
    assert after_draft["lent_to_count"] == 2

    issued = issue_invoice(client, invoice["id"])
    assert issued["status"] == InvoiceStatus.ISSUED

    after_issue = read_partner(client, partner["id"])
    assert after_issue["lend_receivable_cents"] == 0
    assert after_issue["lent_to_count"] == 2
    assert after_issue["net_borrow_imbalance_items"] == -2

    invoiced, invoiced_meta = validate_paginated(
        client.list_partner_lending_charges(
            partner["id"],
            headers=make_accountant_headers(),
            params={"status": LendingChargeStatus.INVOICED},
        )
    )
    assert invoiced_meta["total_count"] == 2
    assert {row["status"] for row in invoiced} == {LendingChargeStatus.INVOICED}

    still_open, open_meta = validate_paginated(
        client.list_partner_lending_charges(
            partner["id"],
            headers=make_accountant_headers(),
            params={"status": LendingChargeStatus.OPEN},
        )
    )
    assert still_open == []
    assert open_meta["total_count"] == 0

    for charge_id in (first["id"], second["id"]):
        row = validate_success(
            client.get_lending_charge(charge_id, headers=make_accountant_headers())
        )
        assert row["status"] == LendingChargeStatus.INVOICED


def test_filters_narrow_the_total_count_before_the_page_window_is_applied(client):
    """A twelve-row collection is paged unfiltered, then filtered, and the reported total
    follows the predicate rather than the page, including after a row is added.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the
    `meta` object, where `total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` states whether any matching row remains beyond
    the current page." And: "Filters combine conjunctively, and a filter naming a value
    outside its enum is a malformed request." And: "A `limit` outside the range 1 to 100
    inclusive, or an `offset` below 0, is a malformed request and is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/cross_cutting_complexity_layers/filters_narrow_the_total_count_before_the_page_window_is_applied
    """
    set_clock(client, CLOCK_START_ISO)
    article_ids = []
    for index in range(7):
        article = create_article_bib_item(
            client,
            issn="3300-0001",
            title="Sediment cores, part %d" % (index + 1),
            journal_title="Journal of Quaternary Studies",
            publication_year=2024,
        )
        article_ids.append(article["id"])
    book_ids = []
    for index in range(5):
        book = create_bib_item(
            client,
            title="Field notes, volume %d" % (index + 1),
            item_type=ItemType.BOOK,
            publication_year=2010 + index,
            isbn="978-0-000-0008%d-3" % index,
            list_price_cents=9000,
        )
        book_ids.append(book["id"])
    assert len(set(article_ids + book_ids)) == 12

    first_page, first_meta = validate_paginated(
        client.list_bib_items(headers=make_ill_staff_headers())
    )
    assert len(first_page) == 10
    assert first_meta["total_count"] == 12
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 10
    assert first_meta["offset"] == 0

    last_page, last_meta = validate_paginated(
        client.list_bib_items(headers=make_ill_staff_headers(), params={"offset": 10})
    )
    assert len(last_page) == 2
    assert last_meta["total_count"] == 12
    assert last_meta["has_more"] is False
    seen = [row["id"] for row in first_page] + [row["id"] for row in last_page]
    assert len(set(seen)) == 12

    filtered, filtered_meta = validate_paginated(
        client.list_bib_items(
            headers=make_ill_staff_headers(),
            params={"item_type": ItemType.ARTICLE, "limit": 5, "offset": 0},
        )
    )
    assert len(filtered) == 5
    assert filtered_meta["total_count"] == 7
    assert filtered_meta["has_more"] is True

    filtered_tail, tail_meta = validate_paginated(
        client.list_bib_items(
            headers=make_ill_staff_headers(),
            params={"item_type": ItemType.ARTICLE, "limit": 5, "offset": 5},
        )
    )
    assert len(filtered_tail) == 2
    assert tail_meta["total_count"] == 7
    assert tail_meta["has_more"] is False
    assert set(row["id"] for row in filtered_tail) <= set(article_ids)

    conjunctive, conjunctive_meta = validate_paginated(
        client.list_bib_items(
            headers=make_ill_staff_headers(),
            params={"issn": "3300-0001", "item_type": ItemType.BOOK},
        )
    )
    assert conjunctive == []
    assert conjunctive_meta["total_count"] == 0

    eighth = create_article_bib_item(
        client,
        issn="3300-0001",
        title="Sediment cores, part 8",
        journal_title="Journal of Quaternary Studies",
        publication_year=2025,
    )
    grown, grown_meta = validate_paginated(
        client.list_bib_items(
            headers=make_ill_staff_headers(),
            params={"item_type": ItemType.ARTICLE, "limit": 5, "offset": 5},
        )
    )
    assert grown_meta["total_count"] == 8
    assert grown_meta["has_more"] is False
    assert len(grown) == 3
    assert eighth["id"] in {row["id"] for row in grown}

    beyond, beyond_meta = validate_paginated(
        client.list_bib_items(
            headers=make_ill_staff_headers(),
            params={"item_type": ItemType.ARTICLE, "limit": 100, "offset": 8},
        )
    )
    assert beyond == []
    assert beyond_meta["total_count"] == 8
    assert beyond_meta["has_more"] is False

    for bad_limit in (0, 101):
        validate_error(
            client.list_bib_items(
                headers=make_ill_staff_headers(), params={"limit": bad_limit}
            ),
            ApiErrorId.INVALID_REQUEST,
            expected_status=400,
        )


def test_every_write_is_fully_visible_to_the_first_read_that_follows_it(client):
    """Intake, sourcing and acceptance each move derived fields on three entities, and the
    very next read of each entity — including a filtered collection read on a field the
    acceptance had just set — already shows the settled values.

    PRD: "Then the partner's `borrowed_from_count`, `net_borrow_imbalance_items` and
    `borrow_payable_cents` are re-derived, and the request is priced." And: "The patron's
    `pending_charge_cents` is re-derived once the request's money fields have settled."

    Design: Corner/consistency_model/every_write_is_fully_visible_to_the_first_read_that_follows_it
    """
    set_clock(client, CLOCK_START_ISO)
    patron = create_patron(
        client,
        external_id="P-9063",
        full_name="Ira Reader",
        email="ira@u.edu",
        patron_type="FACULTY",
        department="HIST",
        max_open_requests=5,
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
        expected_rota_version=rota["version"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(
        client,
        title="Cartularies of Cluny",
        item_type=ItemType.BOOK,
        publication_year=2011,
        isbn="978-0-000-00086-8",
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
    assert request["status"] == RequestStatus.SOURCING
    assert request["attempt_count"] == 0
    assert request["net_patron_charge_cents"] == 0

    after_intake = read_patron(client, patron["id"])
    assert after_intake["open_request_count"] == 1
    assert after_intake["pending_charge_cents"] == 0

    offer = run_rota_round(client, request["id"])
    assert offer["status"] == OfferStatus.OFFERED
    assert offer["attempt_seq"] == 1
    assert offer["effective_fee_cents"] == 2000
    assert offer["landed_cost_cents"] == 2000

    sourced = read_request(client, request["id"])
    assert sourced["status"] == RequestStatus.OFFER_PENDING
    assert sourced["attempt_count"] == 1
    assert sourced["days_available_at_source"] == 8

    accepted = accept_offer(client, offer["id"], partner["id"])
    assert accepted["status"] == OfferStatus.ACCEPTED

    committed = read_request(client, request["id"])
    assert committed["status"] == RequestStatus.SUPPLY_COMMITTED
    assert committed["committed_partner_id"] == partner["id"]
    assert committed["committed_fee_cents"] == 2000
    assert committed["committed_loan_period_days"] == 28
    assert committed["rush_surcharge_cents"] == 0
    assert committed["gross_charge_cents"] == 2000
    assert committed["subsidy_cents"] == 1600
    assert committed["net_patron_charge_cents"] == 400

    after_commit = read_patron(client, patron["id"])
    assert after_commit["open_request_count"] == 1
    assert after_commit["pending_charge_cents"] == 400

    partner_now = read_partner(client, partner["id"])
    assert partner_now["borrowed_from_count"] == 1
    assert partner_now["borrow_payable_cents"] == 2000
    assert partner_now["net_borrow_imbalance_items"] == 1

    rows, meta = validate_paginated(
        client.list_requests(
            headers=make_ill_staff_headers(),
            params={
                "committed_partner_id": partner["id"],
                "status": RequestStatus.SUPPLY_COMMITTED,
            },
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [request["id"]]
