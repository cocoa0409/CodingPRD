"""Entity creation, declared defaults, system fields, retrieval and listing."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_common_fields,
    assert_notification_shape,
    assert_same_instant,
    ids_of,
)
from test_helpers.constants import CLOCK_START_ISO
from test_helpers.fixtures import (
    add_rota_entry,
    create_bib_item,
    create_partner,
    create_rota,
    intake_request,
    read_rota,
    run_rota_round,
    set_clock,
)
from test_helpers.test_users import (
    make_accountant_headers,
    make_admin_headers,
    make_ill_staff_headers,
    make_partner_agent_headers,
    make_patron_headers,
)
from test_helpers.types import (
    ItemType,
    LicensedAccessStatus,
    LocalHoldingStatus,
    MaterialType,
    NotificationChannel,
    NotificationKind,
    PartnerStatus,
    PatronStatus,
    PatronType,
    SelectionPolicy,
)

UNKNOWN_UUID = "11111111-2222-3333-4444-555555555555"
OTHER_UNKNOWN_UUID = "99999999-8888-7777-6666-555555555555"


def test_patron_create_returns_201_and_echoes_every_declared_input(client):
    """Registering a patron answers 201 and echoes the submitted inputs inside the
    standard success envelope.

    PRD: "Registering one is open to `LibraryAdmin` and `IllBorrowingStaff` and
    requires an `external_id` — the campus-unique identifier, between 1 and 32
    characters long and unique across all patron rows — together with a
    `full_name`, an `email` that notices are sent to, a `patron_type` of
    `FACULTY`, `GRAD`, `UNDERGRAD` or `STAFF` (recorded for reporting only and
    never used as a gate), and the owning academic `department` code."

    Design: Corner/entities/create_patron_with_all_required_fields_returns_201_and_echoes_inputs
    """
    response = client.create_patron(
        {
            "external_id": "P-9001",
            "full_name": "Ada Reader",
            "email": "ada@u.edu",
            "patron_type": PatronType.FACULTY,
            "department": "CSCI",
            "max_open_requests": 7,
            "max_concurrent_loans": 4,
            "unpaid_balance_cap_cents": 12000,
        },
        headers=make_ill_staff_headers(),
    )
    patron = validate_success(response, expected_status=201)

    assert patron["external_id"] == "P-9001"
    assert patron["full_name"] == "Ada Reader"
    assert patron["email"] == "ada@u.edu"
    assert patron["patron_type"] == PatronType.FACULTY
    assert patron["department"] == "CSCI"
    assert patron["max_open_requests"] == 7
    assert patron["max_concurrent_loans"] == 4
    assert patron["unpaid_balance_cap_cents"] == 12000
    assert patron["status"] == PatronStatus.ACTIVE

    assert_common_fields(patron, expected_version=1)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_patron_create_omitting_the_three_ceilings_applies_the_declared_defaults(client):
    """With all three ceilings omitted the new account carries 5, 3 and 5000.

    PRD: "Three ceilings may be supplied at registration and default when they
    are not: `max_open_requests` defaults to 5 and must be at least 1,
    `max_concurrent_loans` defaults to 3 and must be at least 1, and
    `unpaid_balance_cap_cents` defaults to 5000 cents — fifty dollars — and must
    be at least 0."

    Design: Corner/entities/omitting_patron_optional_caps_applies_the_declared_defaults
    """
    patron = validate_success(
        client.create_patron(
            {
                "external_id": "P-9002",
                "full_name": "Ben Reader",
                "email": "ben@u.edu",
                "patron_type": PatronType.UNDERGRAD,
                "department": "ENGL",
            },
            headers=make_ill_staff_headers(),
        ),
        expected_status=201,
    )

    assert patron["max_open_requests"] == 5
    assert patron["max_concurrent_loans"] == 3
    assert patron["unpaid_balance_cap_cents"] == 5000

    assert patron["status"] == PatronStatus.ACTIVE
    assert patron["provisional_risk_score"] == 0
    assert patron["final_risk_score"] == 0
    assert patron["unpaid_balance_cents"] == 0
    assert patron["open_request_count"] == 0
    assert patron["pending_charge_cents"] == 0


def test_patron_create_missing_patron_type_is_rejected_and_writes_nothing(client):
    """Omitting the required `patron_type` input is a malformed body.

    PRD: "**35 —** the body is well formed: required fields present, enum values
    within their declared sets, integers non-negative where this document says
    so, `period_month` matching a four-digit year, a hyphen and a two-digit
    month between `01` and `12`, `effective_to` strictly later than
    `effective_from`, `issn` present when `item_type` is `ARTICLE`,
    `pages_requested` present when a `COPY` is requested for an `ARTICLE`,
    `delivery_mode` equal to `ELECTRONIC` whenever `service_type` is `COPY`,
    pagination `limit` between 1 and 100 and `offset` at least 0. Any violation
    is `ERR_INVALID_REQUEST` (400), on every endpoint."

    Design: Corner/entities/patron_create_missing_patron_type_is_rejected_invalid_request
    """
    error = validate_error(
        client.create_patron(
            {
                "external_id": "P-9003",
                "full_name": "Cara Reader",
                "email": "cara@u.edu",
                "department": "MUSI",
            },
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.INVALID_REQUEST,
        expected_status=400,
    )
    assert set(error.keys()) == {"error_id", "message"}
    assert isinstance(error["message"], str) and error["message"]

    rows, meta = validate_paginated(
        client.list_patrons(
            headers=make_ill_staff_headers(), params={"external_id": "P-9003"}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_patron_create_with_an_unknown_patron_type_enum_is_rejected(client):
    """`ALUMNI` lies outside the declared `patron_type` set and is refused, not coerced.

    PRD: "a `patron_type` of `FACULTY`, `GRAD`, `UNDERGRAD` or `STAFF` (recorded
    for reporting only and never used as a gate)"

    Design: Corner/entities/patron_create_with_unknown_patron_type_enum_is_rejected_invalid_request
    """
    validate_error(
        client.create_patron(
            {
                "external_id": "P-9004",
                "full_name": "Dov Reader",
                "email": "dov@u.edu",
                "patron_type": "ALUMNI",
                "department": "HIST",
            },
            headers=make_ill_staff_headers(),
        ),
        ApiErrorId.INVALID_REQUEST,
        expected_status=400,
    )

    _rows, meta = validate_paginated(
        client.list_patrons(
            headers=make_ill_staff_headers(), params={"external_id": "P-9004"}
        )
    )
    assert meta["total_count"] == 0


def test_bib_item_create_mints_its_own_id_and_created_at(client):
    """A client-supplied `id` and `created_at` are ignored; the server mints both.

    PRD: "carries a server-minted `id` formatted as a UUID with no type prefix,
    and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three
    fractional digits (for example `2026-08-01T00:00:00.000Z`)"

    Design: Corner/entities/bib_item_create_extra_field_id_and_created_at_input_ignored
    """
    submitted_id = "00000000-0000-0000-0000-000000000001"
    bib_item = validate_success(
        client.create_bib_item(
            {
                "title": "Systems of Cataloguing",
                "item_type": ItemType.BOOK,
                "publication_year": 2011,
                "isbn": "978-0-000-00020-2",
                "local_holding_status": LocalHoldingStatus.NONE,
                "licensed_access_status": LicensedAccessStatus.NONE,
                "list_price_cents": 9000,
                "id": submitted_id,
                "created_at": "1999-01-01T00:00:00Z",
            },
            headers=make_admin_headers(),
        ),
        expected_status=201,
    )

    assert bib_item["id"] != submitted_id
    assert is_valid_uuid(bib_item["id"])
    assert_same_instant(bib_item["created_at"], CLOCK_START_ISO, "created_at")
    assert bib_item["version"] == 1


def test_intake_charge_fields_are_computed_from_the_committed_lender_quote(client):
    """A 2000-cent commitment with no rush and no royalty prices out at gross 2000,
    subsidy 1600 and net 400.

    PRD: "**Sixth**, `subsidy_cents` is the gross multiplied by that rate,
    rounded half up to whole cents, and then capped at 4000 cents — the cap is
    applied to the rounded product, never before the tier lookup."

    Design: Corner/entities/request_intake_computes_its_charge_fields_from_the_committed_lender_quote
    """
    set_clock(client, CLOCK_START_ISO)
    patron = validate_success(
        client.create_patron(
            {
                "external_id": "P-9005",
                "full_name": "Eve Reader",
                "email": "eve@u.edu",
                "patron_type": PatronType.GRAD,
                "department": "MATH",
            },
            headers=make_admin_headers(),
        ),
        expected_status=201,
    )
    partner = create_partner(
        client,
        code="NORTHU",
        base_lending_fee_cents=2000,
        avg_turnaround_days=4,
        loan_period_days=28,
        max_renewals=2,
    )
    rota = create_rota(client, material_type=MaterialType.LOAN)
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(client, list_price_cents=9000)

    request = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00Z",
        max_supply_fee_cents=5000,
    )
    offer = run_rota_round(client, request["id"])
    validate_success(
        client.accept_offer(
            offer["id"], headers=make_partner_agent_headers(partner["id"])
        )
    )

    priced = validate_success(
        client.get_request(request["id"], headers=make_ill_staff_headers())
    )
    assert priced["committed_fee_cents"] == 2000
    assert priced["rush_surcharge_cents"] == 0
    assert priced["royalty_cents"] == 0
    assert priced["gross_charge_cents"] == 2000
    assert priced["subsidy_cents"] == 1600
    assert priced["net_patron_charge_cents"] == 400

    refreshed_patron = validate_success(
        client.get_patron(patron["id"], headers=make_ill_staff_headers())
    )
    assert refreshed_patron["pending_charge_cents"] == 400


def test_get_partner_returns_every_stored_input_and_the_derived_balances_at_zero(client):
    """A freshly registered partner reads back its submitted terms plus five
    balance figures initialised to 0.

    PRD: "Five balance figures hang off each partner and are maintained by the
    server. `borrowed_from_count` is the number of requests committed to that
    partner whose `status` is neither `CANCELLED` nor `UNFILLED`. `lent_to_count`
    is the number of lending charges recorded against that partner.
    `net_borrow_imbalance_items` is `borrowed_from_count` minus `lent_to_count`
    and may legitimately be negative."

    Design: Corner/entities/get_partner_by_id_returns_every_stored_and_derived_field
    """
    set_clock(client, CLOCK_START_ISO)
    created = create_partner(
        client,
        code="EASTV",
        name="East Valley College Library",
        consortium_code="EASTERN",
        base_lending_fee_cents=1750,
        avg_turnaround_days=6,
        ships_physical=True,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )

    partner = validate_success(
        client.get_partner(created["id"], headers=make_accountant_headers())
    )
    assert partner["code"] == "EASTV"
    assert partner["name"] == "East Valley College Library"
    assert partner["consortium_code"] == "EASTERN"
    assert partner["base_lending_fee_cents"] == 1750
    assert partner["avg_turnaround_days"] == 6
    assert partner["ships_physical"] is True
    assert partner["supplies_electronic"] is False
    assert partner["allows_renewals"] is False
    assert partner["loan_period_days"] == 21
    assert partner["max_renewals"] == 1
    assert partner["status"] == PartnerStatus.ACTIVE

    assert partner["borrowed_from_count"] == 0
    assert partner["lent_to_count"] == 0
    assert partner["net_borrow_imbalance_items"] == 0
    assert partner["borrow_payable_cents"] == 0
    assert partner["lend_receivable_cents"] == 0


def test_bib_item_listing_combines_a_filter_with_offset_and_limit(client):
    """`total_count` counts the filtered set before the page window is applied.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object, where `total_count` is the number of rows matching
    the filters before pagination is applied and `has_more` states whether any
    matching row remains beyond the current page."

    Design: Corner/entities/list_bib_items_combines_filter_offset_and_limit_with_total_count_and_has_more
    """
    set_clock(client, CLOCK_START_ISO)
    article_one = create_bib_item(
        client,
        title="Article Alpha",
        item_type=ItemType.ARTICLE,
        issn="1111-0001",
        journal_title="Journal A",
        publication_year=2023,
        list_price_cents=4000,
    )
    create_bib_item(
        client,
        title="Article Beta",
        item_type=ItemType.ARTICLE,
        issn="1111-0002",
        journal_title="Journal B",
        publication_year=2023,
        list_price_cents=4000,
    )
    article_three = create_bib_item(
        client,
        title="Article Gamma",
        item_type=ItemType.ARTICLE,
        issn="1111-0003",
        journal_title="Journal C",
        publication_year=2023,
        list_price_cents=4000,
    )
    create_bib_item(
        client,
        title="Book Delta",
        item_type=ItemType.BOOK,
        publication_year=2014,
        isbn="978-0-000-00022-6",
        list_price_cents=9000,
    )
    create_bib_item(
        client,
        title="Book Epsilon",
        item_type=ItemType.BOOK,
        publication_year=2015,
        isbn="978-0-000-00023-3",
        local_holding_status=LocalHoldingStatus.HELD_AVAILABLE,
        list_price_cents=9000,
    )

    page_one, meta_one = validate_paginated(
        client.list_bib_items(
            headers=make_ill_staff_headers(),
            params={"item_type": ItemType.ARTICLE, "limit": 2, "offset": 0},
        )
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert page_one[0]["id"] == article_one["id"]

    page_two, meta_two = validate_paginated(
        client.list_bib_items(
            headers=make_ill_staff_headers(),
            params={"item_type": ItemType.ARTICLE, "limit": 2, "offset": 2},
        )
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert page_two[0]["id"] == article_three["id"]

    held, meta_held = validate_paginated(
        client.list_bib_items(
            headers=make_ill_staff_headers(),
            params={"local_holding_status": LocalHoldingStatus.HELD_AVAILABLE},
        )
    )
    assert len(held) == 1
    assert meta_held["total_count"] == 1
    assert meta_held["has_more"] is False

    everything, meta_all = validate_paginated(
        client.list_bib_items(headers=make_ill_staff_headers())
    )
    assert meta_all["total_count"] == 5
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0
    assert len(everything) == 5


def test_get_supply_offer_with_an_unknown_uuid_is_a_404_not_found(client):
    """A well-formed but unknown offer id resolves to its own 404 code.

    PRD: "**30 —** every identifier in the URL path names an existing row,
    resolved left to right: 404 with the code for the first missing row —
    `ERR_PATRON_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`, `ERR_BIB_ITEM_NOT_FOUND`,
    `ERR_ROTA_NOT_FOUND`, `ERR_ROTA_ENTRY_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_REQUEST_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_POD_ORDER_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND` or `ERR_LENDING_CHARGE_NOT_FOUND`."

    Design: Corner/entities/get_supply_offer_with_unknown_uuid_returns_offer_not_found
    """
    error = validate_error(
        client.get_supply_offer(UNKNOWN_UUID, headers=make_ill_staff_headers()),
        ApiErrorId.OFFER_NOT_FOUND,
        expected_status=404,
    )
    assert set(error.keys()) == {"error_id", "message"}

    _rows, meta = validate_paginated(
        client.list_supply_offers(headers=make_ill_staff_headers())
    )
    assert meta["total_count"] == 0


def test_patron_notification_carries_no_updated_at_and_no_version(client):
    """The notice emitted at intake is an append-only record with neither
    `updated_at` nor `version`, and there is no endpoint that writes one.

    PRD: "The single exception is `PatronNotification`. Notices are append-only
    records of something that already happened; a notification row carries only
    `id` and `created_at`, and both `updated_at` and `version` are absent from
    it. There is no endpoint that updates or deletes a notification."

    Design: Corner/entities/patron_notification_is_immutable_with_no_version_and_no_write_endpoint
    """
    set_clock(client, CLOCK_START_ISO)
    patron = validate_success(
        client.create_patron(
            {
                "external_id": "P-9006",
                "full_name": "Finn Reader",
                "email": "finn@u.edu",
                "patron_type": PatronType.STAFF,
                "department": "ARTS",
            },
            headers=make_admin_headers(),
        ),
        expected_status=201,
    )
    partner = create_partner(client, code="NORTHU", loan_period_days=28)
    rota = create_rota(client, material_type=MaterialType.LOAN)
    add_rota_entry(
        client,
        rota["id"],
        partner["id"],
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    bib_item = create_bib_item(client, title="Baroque Ornament", publication_year=2008)
    request = intake_request(
        client,
        patron["id"],
        bib_item["id"],
        rota["id"],
        needed_by="2026-08-09T00:00:00Z",
        max_supply_fee_cents=5000,
    )

    notices, meta = validate_paginated(
        client.list_notifications(
            request["id"], headers=make_patron_headers(patron["id"])
        )
    )
    assert meta["total_count"] == 1
    notice = notices[0]
    assert notice["kind"] == NotificationKind.REQUEST_SUBMITTED
    assert notice["channel"] == NotificationChannel.EMAIL
    assert notice["request_id"] == request["id"]
    assert isinstance(notice["subject"], str) and notice["subject"]
    assert_same_instant(notice["sent_at"], CLOCK_START_ISO, "sent_at")

    assert "updated_at" not in notice
    assert "version" not in notice
    assert_notification_shape(notice)


def test_rota_entry_create_with_an_unknown_partner_id_is_a_404(client):
    """A body foreign key naming nothing is a 404, and the refused create leaves
    the parent rota's version alone.

    PRD: "**32 —** every foreign key supplied in the request body names an
    existing row, checked in the order the fields are listed for that endpoint in
    §3: 404 with `ERR_PATRON_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`,
    `ERR_BIB_ITEM_NOT_FOUND`, `ERR_ROTA_NOT_FOUND` or `ERR_AGREEMENT_NOT_FOUND`
    as appropriate."

    Design: Corner/entities/rota_entry_create_with_unknown_partner_id_returns_partner_not_found
    """
    set_clock(client, CLOCK_START_ISO)
    rota = create_rota(client, material_type=MaterialType.LOAN)
    version_before = rota["version"]

    validate_error(
        client.create_rota_entry(
            {
                "rota_id": rota["id"],
                "expected_rota_version": version_before,
                "partner_id": OTHER_UNKNOWN_UUID,
                "manual_rank": 1,
                "quoted_fee_cents": 2000,
                "quoted_turnaround_days": 4,
                "is_enabled": True,
            },
            headers=make_admin_headers(),
        ),
        ApiErrorId.PARTNER_NOT_FOUND,
        expected_status=404,
    )

    assert read_rota(client, rota["id"])["version"] == version_before

    _entries, meta = validate_paginated(
        client.list_rota_entries(rota["id"], headers=make_ill_staff_headers())
    )
    assert meta["total_count"] == 0


def test_rota_entry_is_reachable_from_both_the_rota_and_the_partner_side(client):
    """The same junction row is discoverable under its rota and under the partner
    it quotes, and carries its own quote rather than the partner's published fee.

    PRD: "Each partner's place on a rota is a rota entry naming its `rota_id` and
    `partner_id` and carrying a `manual_rank` of at least 1, a
    `quoted_fee_cents` of at least 0, a `quoted_turnaround_days` figure of at
    least 0 in whole days, and an `is_enabled` flag that defaults to true."

    Design: Corner/entities/rota_entry_is_the_junction_row_reachable_from_both_the_rota_and_the_partner_side
    """
    set_clock(client, CLOCK_START_ISO)
    northu = create_partner(
        client, code="NORTHU", base_lending_fee_cents=2000, loan_period_days=28
    )
    southc = create_partner(
        client,
        code="SOUTHC",
        name="South Coast Library",
        base_lending_fee_cents=1200,
        avg_turnaround_days=9,
        supplies_electronic=False,
        allows_renewals=False,
        loan_period_days=21,
        max_renewals=1,
    )
    fast = create_rota(
        client,
        name="FAST rota",
        material_type=MaterialType.LOAN,
        selection_policy=SelectionPolicy.LANDED_COST,
    )
    entry_fast_northu = add_rota_entry(
        client,
        fast["id"],
        northu["id"],
        manual_rank=1,
        quoted_fee_cents=2000,
        quoted_turnaround_days=4,
    )
    cheap = create_rota(
        client,
        name="CHEAP rota",
        material_type=MaterialType.LOAN,
        selection_policy=SelectionPolicy.MANUAL_RANK,
    )
    entry_cheap_northu = add_rota_entry(
        client,
        cheap["id"],
        northu["id"],
        manual_rank=2,
        quoted_fee_cents=2400,
        quoted_turnaround_days=9,
    )
    entry_cheap_southc = add_rota_entry(
        client,
        cheap["id"],
        southc["id"],
        manual_rank=1,
        quoted_fee_cents=1200,
        quoted_turnaround_days=9,
    )

    cheap_entries, cheap_meta = validate_paginated(
        client.list_rota_entries(cheap["id"], headers=make_ill_staff_headers())
    )
    assert cheap_meta["total_count"] == 2
    assert set(ids_of(cheap_entries)) == {
        entry_cheap_northu["id"],
        entry_cheap_southc["id"],
    }

    northu_entries, northu_meta = validate_paginated(
        client.list_partner_rota_entries(
            northu["id"], headers=make_ill_staff_headers()
        )
    )
    assert northu_meta["total_count"] == 2
    assert set(ids_of(northu_entries)) == {
        entry_fast_northu["id"],
        entry_cheap_northu["id"],
    }

    via_id = validate_success(
        client.get_rota_entry(
            entry_cheap_northu["id"], headers=make_ill_staff_headers()
        )
    )
    assert via_id["quoted_fee_cents"] == 2400
    assert via_id["quoted_turnaround_days"] == 9

    _southc_entries, southc_meta = validate_paginated(
        client.list_partner_rota_entries(
            southc["id"], headers=make_ill_staff_headers()
        )
    )
    assert southc_meta["total_count"] == 1

    from_rota_side = next(
        row for row in cheap_entries if row["id"] == entry_cheap_northu["id"]
    )
    from_partner_side = next(
        row for row in northu_entries if row["id"] == entry_cheap_northu["id"]
    )
    for view in (from_rota_side, from_partner_side, via_id):
        assert view["rota_id"] == cheap["id"]
        assert view["partner_id"] == northu["id"]
        assert view["quoted_fee_cents"] == 2400
        assert view["quoted_turnaround_days"] == 9
