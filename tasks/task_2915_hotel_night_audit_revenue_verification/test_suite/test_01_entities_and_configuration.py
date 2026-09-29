"""Entity shape: creation echoes, declared defaults, reads, listings and refusals.

Covers PRD section 2.7 (the property configuration rulebook), PRD section 3.1
(standing up a property, its capture points and its calendar), PRD section 2.2
(the response envelope), PRD section 2.3 (pagination) and PRD section 2.4 (record
identity, timestamps and versioning).
"""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_append_only_shape,
    assert_common_fields,
    assert_empty,
    assert_fields,
    assert_int,
    assert_is_instant,
    assert_money,
    assert_money_fields,
    assert_number,
    assert_page_meta,
    assert_row_count,
    single,
)
from test_helpers.constants import STANDARD_PROPERTY
from test_helpers.test_users import (
    ADMIN,
    AUDITOR,
    CONTROLLER,
    FRONT_DESK,
    REVENUE_MANAGER,
    make_outlet_manager_headers,
)

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


def test_registering_a_property_echoes_every_configured_figure_at_full_precision(api):
    """201, the four common fields minted, and three-decimal tax rates preserved.

    PRD section 2.2 wraps a successful write in a meta/response_type/data envelope, and
    PRD section 2.4 mints a bare UUID `id` with `created_at`, `updated_at` and `version` 1.
    PRD section 2.7 carries `occupancy_tax_rate_pct` to three decimal places so that 8.875
    is expressible exactly, and every threshold is stored as supplied. A read of the same
    row returns it unchanged.

    Design: Corner/entities/entity_creation_property_echoes_every_configuration_field_and_common_fields
    """
    response = api.create_property(f.build_property_payload(name="Harbor Grand"), ADMIN)
    created = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object", f"response_type: {body['response_type']!r}"
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]["api_request_id"]
    assert_is_instant(body["meta"]["api_request_timestamp"], "meta.api_request_timestamp")

    assert_common_fields(created, expected_version=1)
    assert is_valid_uuid(created["id"]), f"id is not a bare UUID: {created['id']!r}"
    assert_fields(created, {"name": "Harbor Grand"})
    assert_int(created["room_count_total"], 100, "room_count_total")
    assert_money_fields(
        created,
        {
            "standard_room_rate_amount": 200.00,
            "large_ticket_threshold_amount": 472.00,
            "allowance_manager_threshold_amount": 250.00,
            "allowance_controller_threshold_amount": 1000.00,
            "settlement_variance_tolerance_amount": 5.00,
        },
    )
    for field in (
        "occupancy_tax_rate_pct",
        "fb_tax_rate_pct",
        "service_charge_pct",
        "large_party_discount_pct",
        "rate_variance_tolerance_pct",
        "city_ledger_fee_pct",
    ):
        assert_number(created[field], STANDARD_PROPERTY[field], field)

    reread = validate_success(api.get_property(created["id"], CONTROLLER))
    assert reread == created, "the read must return the identical row that was written"


def test_omitted_optional_inputs_land_on_their_declared_defaults(api):
    """Six optional inputs across four entities, each on its declared default.

    PRD section 2.7 defaults `late_checkout_grace_minutes` to 30, `card_authorization_valid_days`
    to 7 and `no_show_charge_policy` to FIRST_NIGHT_PLUS_TAX. PRD section 3.1 defaults an
    outlet's `requires_shift_settlement` to true with `status` ACTIVE, defaults a day's
    `out_of_order_room_count` to 0 and both pace benchmarks to 0.00 — so a hundred-room
    property has all hundred rooms available — and PRD section 3.2 defaults a guest account's
    `credit_limit_amount` to the non-zero 500.00 and `is_comp` to false.

    Design: Corner/entities/entity_defaults_omitted_optional_inputs_take_their_declared_defaults
    """
    bare = f.without(
        f.build_property_payload(),
        "late_checkout_grace_minutes",
        "card_authorization_valid_days",
        "no_show_charge_policy",
    )
    prop = validate_success(api.create_property(bare, ADMIN), 201)
    assert_int(prop["late_checkout_grace_minutes"], 30, "late_checkout_grace_minutes")
    assert_int(prop["card_authorization_valid_days"], 7, "card_authorization_valid_days")
    assert_fields(prop, {"no_show_charge_policy": "FIRST_NIGHT_PLUS_TAX"})

    outlet = validate_success(
        api.create_outlet(
            f.without(
                f.build_outlet_payload(prop["id"], outlet_code="LOBBY", outlet_name="Lobby Lounge"),
                "requires_shift_settlement",
            ),
            ADMIN,
        ),
        201,
    )
    assert_fields(outlet, {"requires_shift_settlement": True, "status": "ACTIVE"})

    day = validate_success(
        api.create_business_date(
            f.without(f.build_business_date_payload(prop["id"], "2026-08-01"), "out_of_order_room_count"),
            AUDITOR,
        ),
        201,
    )
    assert_int(day["out_of_order_room_count"], 0, "out_of_order_room_count")
    assert_int(day["rooms_available_count"], 100, "rooms_available_count")
    assert_money_fields(
        day,
        {
            "benchmark_calendar_room_revenue_amount": 0.00,
            "benchmark_weekday_room_revenue_amount": 0.00,
        },
    )

    folio = validate_success(
        api.create_folio(
            f.build_folio_payload(
                prop["id"],
                day["id"],
                confirmation_code="CF-DEF1",
                guest_name="Ida Wren",
                room_number="100",
            ),
            FRONT_DESK,
        ),
        201,
    )
    assert_fields(
        folio,
        {"is_comp": False, "stay_status": "RESERVED", "settlement_status": "UNSETTLED"},
    )
    assert_money(folio["credit_limit_amount"], 500.00, "credit_limit_amount")


def test_one_read_of_a_guest_account_carries_both_dimensions_and_its_derived_money(api):
    """Stay status, settlement status and the four money figures arrive in one payload.

    PRD section 3.7 keeps the two dimensions genuinely independent yet exposes both on the
    account, and re-derives `charges_total_amount`, `credits_total_amount`, `balance_amount`
    and `settlement_status` after every line. PRD section 3.2 re-derives `rate_variance_pct`
    on every read, which is 0.00 when the contracted rate equals the rack rate, and PRD
    section 2.4 increments the account's `version` on creation, on arrival and again when a
    journal line re-derives its balance.

    Design: Corner/entities/entity_retrieval_folio_read_returns_both_dimensions_and_derived_money
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-RD1",
        guest_name="Jai Bloom",
        room_number="1601",
        contracted_rate_amount=200.00,
    )
    fx.check_in(api, folio["id"])
    fx.post_journal_line(
        api, bd["id"], "MISC_CHARGE", 45.00, FRONT_DESK, folio_id=folio["id"], memo="Minibar"
    )

    row = validate_success(api.get_folio(folio["id"], REVENUE_MANAGER))
    assert_fields(
        row,
        {
            "stay_status": "IN_HOUSE",
            "settlement_status": "UNSETTLED",
            "settlement_hold": False,
            "confirmation_code": "CF-RD1",
            "room_number": "1601",
        },
    )
    assert_money_fields(
        row,
        {
            "charges_total_amount": 45.00,
            "credits_total_amount": 0.00,
            "balance_amount": 45.00,
            "credit_limit_amount": 500.00,
        },
    )
    assert_number(row["rate_variance_pct"], 0.00, "rate_variance_pct")
    assert_common_fields(row, expected_version=3)


def test_listing_operating_days_pages_at_the_boundary_and_reports_the_set_size(api):
    """total_count counts the filtered set, not the page, and the declared bounds hold.

    PRD section 2.3 defaults `limit` to 10 and `offset` to 0, forbids a limit below 1 or
    above 100, and has `total_count` count the rows matching the filters *before* paging
    while `has_more` reports whether rows remain. PRD section 3.1 narrows the operating-day
    listing by `property_id`, `business_date` and `status`.

    Design: Corner/entities/entity_listing_business_dates_paginate_with_total_count_and_has_more
    """
    prop = fx.create_property(api)
    for day in ("2026-08-01", "2026-08-02", "2026-08-03"):
        fx.create_business_date(api, prop["id"], day, out_of_order_room_count=4)

    first, meta = validate_paginated(
        api.list_business_dates(CONTROLLER, property_id=prop["id"], limit=2, offset=0)
    )
    assert_row_count(first, 2, "first page")
    assert_page_meta(meta, total_count=3, has_more=True, limit=2, offset=0)

    last, meta = validate_paginated(
        api.list_business_dates(CONTROLLER, property_id=prop["id"], limit=2, offset=2)
    )
    assert_row_count(last, 1, "second page")
    assert_page_meta(meta, total_count=3, has_more=False)

    unpaged, meta = validate_paginated(
        api.list_business_dates(CONTROLLER, property_id=prop["id"])
    )
    assert_row_count(unpaged, 3, "the default page")
    assert_page_meta(meta, limit=10, offset=0, total_count=3, has_more=False)

    one_day, meta = validate_paginated(
        api.list_business_dates(CONTROLLER, property_id=prop["id"], business_date="2026-08-02")
    )
    assert_row_count(one_day, 1, "the 2026-08-02 filter")
    assert_page_meta(meta, total_count=1)

    open_days, _ = validate_paginated(
        api.list_business_dates(CONTROLLER, property_id=prop["id"], status="OPEN")
    )
    assert_row_count(open_days, 3, "OPEN days")
    closed, meta = validate_paginated(
        api.list_business_dates(CONTROLLER, property_id=prop["id"], status="CLOSED")
    )
    assert_empty(closed, "CLOSED days")
    assert_page_meta(meta, total_count=0, has_more=False)

    validate_error(
        api.list_business_dates(CONTROLLER, property_id=prop["id"], limit=0),
        E.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.list_business_dates(CONTROLLER, property_id=prop["id"], limit=101),
        E.ERR_INVALID_REQUEST,
    )


def test_each_collection_answers_a_missing_row_with_its_own_not_found_code(api):
    """A well-formed but unknown id yields the collection's own 404 inside the error envelope.

    PRD section 2.12 resolves each path identifier in order and names one code per
    collection, and PRD section 2.2 carries `error_id` and `message` inside `data` rather
    than at the top level. The happy path is untouched by the refusals.

    Design: Corner/entities/entity_not_found_unknown_folio_id_returns_folio_not_found
    """
    prop = fx.create_property(api)

    response = api.get_folio(MISSING_UUID, FRONT_DESK)
    validate_error(response, E.ERR_FOLIO_NOT_FOUND)
    body = response.json()
    assert body["response_type"] == "error", f"response_type: {body['response_type']!r}"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
        f"expected a non-empty message, got {body['data'].get('message')!r}"
    )

    validate_error(api.get_business_date(MISSING_UUID, AUDITOR), E.ERR_BUSINESS_DATE_NOT_FOUND)
    validate_error(api.get_outlet_ticket(MISSING_UUID, AUDITOR), E.ERR_TICKET_NOT_FOUND)
    validate_error(api.get_settlement_batch(MISSING_UUID, AUDITOR), E.ERR_BATCH_NOT_FOUND)
    validate_error(api.get_allowance(MISSING_UUID, AUDITOR), E.ERR_ALLOWANCE_NOT_FOUND)
    validate_error(
        api.get_authorization_document(MISSING_UUID, AUDITOR), E.ERR_DOCUMENT_NOT_FOUND
    )
    validate_error(
        api.get_card_authorization(MISSING_UUID, AUDITOR), E.ERR_AUTHORIZATION_NOT_FOUND
    )
    validate_error(api.get_revenue_report(MISSING_UUID, AUDITOR), E.ERR_REPORT_NOT_FOUND)
    validate_error(api.get_journal_posting(MISSING_UUID, AUDITOR), E.ERR_POSTING_NOT_FOUND)
    validate_error(api.get_ledger_account(MISSING_UUID, AUDITOR), E.ERR_LEDGER_ACCOUNT_NOT_FOUND)
    validate_error(api.get_outlet(MISSING_UUID, AUDITOR), E.ERR_OUTLET_NOT_FOUND)
    validate_error(api.get_accounting_period(MISSING_UUID, AUDITOR), E.ERR_PERIOD_NOT_FOUND)

    assert_fields(validate_success(api.get_property(prop["id"], ADMIN)), {"id": prop["id"]})


def test_a_missing_required_field_is_refused_before_any_business_rule_runs(api):
    """400 on absence, nothing half-written, and zero is still a legal declared count.

    PRD section 2.12 checks the request shape at step three — before path existence, before
    ownership and before any state gate — and refuses an absent required field with
    ERR_INVALID_REQUEST (HTTP 400). PRD section 3.5 accepts a `declared_amount` of zero or
    more, so re-sending the very same window with 0.00 succeeds at 201.

    Design: Corner/entities/entity_required_fields_settlement_batch_without_declared_amount_is_refused
    """
    prop = fx.create_property(api)
    outlet = fx.create_outlet(
        api, prop["id"], outlet_code="LOBBY", outlet_name="Lobby Lounge", requires_shift_settlement=True
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    manager = make_outlet_manager_headers(outlet["id"])
    window = f.build_settlement_batch_payload(
        bd["id"],
        outlet["id"],
        0.00,
        tender_type="CASH",
        shift_start_at="2026-08-01T14:00:00.000Z",
        shift_end_at="2026-08-01T22:00:00.000Z",
    )

    validate_error(
        api.create_settlement_batch(f.without(window, "declared_amount"), manager),
        E.ERR_INVALID_REQUEST,
    )
    assert_empty(
        validate_success(api.list_settlement_batches(AUDITOR, business_date_id=bd["id"])),
        "settlement batches",
    )
    assert_int(
        fx.read_business_date(api, bd["id"])["unresolved_settlement_batch_count"],
        0,
        "unresolved_settlement_batch_count",
    )

    validate_error(
        api.create_folio(
            f.without(f.build_folio_payload(prop["id"], bd["id"]), "guest_name"), FRONT_DESK
        ),
        E.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_outlet_ticket(
            f.without(f.build_outlet_ticket_payload(outlet["id"], bd["id"]), "gross_amount"),
            manager,
        ),
        E.ERR_INVALID_REQUEST,
    )

    accepted = validate_success(api.create_settlement_batch(window, manager), 201)
    assert_money(accepted["declared_amount"], 0.00, "declared_amount")


def test_rate_variance_is_signed_derived_and_never_taken_from_the_body(api):
    """A discount reads negative, an upsell positive, and a smuggled value is ignored.

    PRD section 3.2 computes `rate_variance_pct` as the contracted rate less the property's
    `standard_room_rate_amount`, divided by that same rack rate, times one hundred, rounded
    half up to two decimals, re-derived on every read from that one account and the rack rate
    alone. PRD section 2.12 ignores unknown body field names rather than rejecting them, so a
    supplied figure is neither stored nor fatal. And PRD section 3.2 needs paperwork only when
    the absolute variance strictly exceeds the tolerance, which 60.00 does not.

    Design: Corner/entities/entity_computed_fields_rate_variance_is_derived_and_a_supplied_value_is_ignored
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    upsell = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-UP1",
        guest_name="Kip Doyle",
        room_number="1701",
        contracted_rate_amount=250.00,
        rate_plan_code="SUITE",
    )

    discounted = validate_success(
        api.create_folio(
            f.build_folio_payload(
                prop["id"],
                bd["id"],
                confirmation_code="CF-DN1",
                guest_name="Lu Ferro",
                room_number="1702",
                contracted_rate_amount=80.00,
                rate_plan_code="STAFF",
                market_segment="CORPORATE",
                rate_variance_pct=999.99,
            ),
            FRONT_DESK,
        ),
        201,
    )
    assert_number(discounted["rate_variance_pct"], -60.00, "rate_variance_pct")
    assert_number(
        validate_success(api.get_folio(upsell["id"], FRONT_DESK))["rate_variance_pct"],
        25.00,
        "rate_variance_pct",
    )

    at_rack = fx.create_folio(
        api, prop["id"], bd["id"], confirmation_code="CF-RK1", contracted_rate_amount=200.00
    )
    assert_number(at_rack["rate_variance_pct"], 0.00, "rate_variance_pct")
    free = fx.create_folio(
        api, prop["id"], bd["id"], confirmation_code="CF-ZR1", contracted_rate_amount=0.00
    )
    assert_number(free["rate_variance_pct"], -100.00, "rate_variance_pct")

    assert_fields(fx.check_in(api, upsell["id"]), {"stay_status": "IN_HOUSE"})
    assert_fields(fx.check_in(api, discounted["id"]), {"stay_status": "IN_HOUSE"})


def test_a_journal_line_stamps_its_channel_from_the_role_not_from_the_body(api):
    """The identical payload yields FRONT_DESK for one caller and NIGHT_AUDIT for the other.

    PRD section 2.8 has the server stamp `source_channel`, never the client, and PRD section
    3.7 stamps FRONT_DESK when the caller is a FrontDeskAgent and NIGHT_AUDIT for every other
    caller, with `posted_by_user_id` taken from the acting operator. PRD section 2.8 leaves
    `night_index` null on every class but ROOM and OCCUPANCY_TAX, and leaves the three
    provenance keys null on an original line.

    Design: Corner/entities/entity_system_fields_journal_posting_stamps_poster_and_source_channel
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api, prop["id"], bd["id"], confirmation_code="CF-SYS1", contracted_rate_amount=200.00
    )
    fx.check_in(api, folio["id"])
    body = f.build_journal_posting_payload(
        bd["id"],
        "MISC_CHARGE",
        60.00,
        folio_id=folio["id"],
        memo="Spa",
        posted_by_user_id="u_smuggled",
        source_channel="LEDGER_SWEEP",
    )

    by_desk = validate_success(api.create_journal_posting(body, FRONT_DESK), 201)
    by_audit = validate_success(api.create_journal_posting(body, AUDITOR), 201)

    assert_fields(by_desk, {"source_channel": "FRONT_DESK"})
    assert by_desk["posted_by_user_id"] == FRONT_DESK["X-User-ID"], by_desk["posted_by_user_id"]
    assert_fields(by_audit, {"source_channel": "NIGHT_AUDIT"})
    assert by_audit["posted_by_user_id"] == AUDITOR["X-User-ID"], by_audit["posted_by_user_id"]

    for row in (by_desk, by_audit):
        assert_append_only_shape(row)
        assert_fields(
            row,
            {
                "night_index": None,
                "reverses_posting_id": None,
                "outlet_ticket_id": None,
                "allowance_id": None,
                "ledger_account_id": None,
                "business_date_id": bd["id"],
            },
        )

    assert_row_count(
        validate_success(api.list_journal_postings(AUDITOR, business_date_id=bd["id"])),
        2,
        "journal lines of the day",
    )
    account = fx.read_folio(api, folio["id"])
    assert_money_fields(account, {"charges_total_amount": 120.00, "balance_amount": 120.00})


def test_bad_enums_and_out_of_range_numbers_are_all_refused_at_the_shape_gate(api):
    """An unknown enum, an integer below its floor and a string for a number all read 400.

    PRD section 2.12 rejects a field whose JSON type is wrong or whose enum value lies outside
    its declared set with ERR_INVALID_REQUEST (HTTP 400), before any business rule is
    consulted. PRD section 3.2 declares `nights_count` at least 1, PRD section 2.8 forbids a
    zero `amount`, and PRD section 3.1 caps `out_of_order_room_count` at the property's
    `room_count_total`. Nothing is written by any of them.

    Design: Corner/entities/entity_type_constraints_bad_enum_and_out_of_range_numbers_are_refused
    """
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)

    def folio_body(**overrides):
        return f.build_folio_payload(
            prop["id"],
            bd["id"],
            confirmation_code="CF-BAD1",
            guest_name="Nia Kwon",
            room_number="1901",
            **overrides,
        )

    validate_error(
        api.create_folio(folio_body(market_segment="WHOLESALE"), FRONT_DESK),
        E.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_folio(folio_body(nights_count=0), FRONT_DESK), E.ERR_INVALID_REQUEST
    )
    validate_error(
        api.create_folio(folio_body(contracted_rate_amount="two hundred"), FRONT_DESK),
        E.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_journal_posting(
            f.build_journal_posting_payload(bd["id"], "MISC_CHARGE", 0.00), AUDITOR
        ),
        E.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_business_date(
            f.build_business_date_payload(prop["id"], "2026-08-05", out_of_order_room_count=101),
            AUDITOR,
        ),
        E.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_ledger_account(
            f.build_ledger_account_payload(prop["id"], "PETTY_CASH"), CONTROLLER
        ),
        E.ERR_INVALID_REQUEST,
    )
    assert_empty(
        validate_success(api.list_folios(FRONT_DESK, property_id=prop["id"])),
        "guest accounts",
    )


def test_a_journal_line_has_no_version_and_is_corrected_only_by_appending(api):
    """The original row survives its own correction, and the pair nets the account to zero.

    PRD section 2.4 gives a journal line only `id` and `created_at` — neither `updated_at`
    nor `version` appears in its representation at all — because PRD section 2.8 makes the
    journal append-only. Reversal therefore mints a new row negating the original and naming
    it in `reverses_posting_id`, answering 201, while PRD section 3.7 re-derives the account
    from the resulting pair: charges 90.00, credits −90.00, balance 0.00 and SETTLED.

    Design: Corner/entities/entity_immutability_journal_postings_carry_no_version_and_no_mutating_endpoint
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api, prop["id"], bd["id"], confirmation_code="CF-IMM1", contracted_rate_amount=200.00
    )
    fx.check_in(api, folio["id"])
    original = fx.post_journal_line(
        api, bd["id"], "MISC_CHARGE", 90.00, AUDITOR, folio_id=folio["id"], memo="Spa"
    )
    assert_append_only_shape(validate_success(api.get_journal_posting(original["id"], AUDITOR)))

    mirror = validate_success(
        api.reverse_journal_posting(original["id"], CONTROLLER, {"memo": "Corrected by control"}),
        201,
    )
    assert mirror["id"] != original["id"], "the reversal must be a new row"
    assert_money(mirror["amount"], -90.00, "the reversing amount")
    assert_fields(
        mirror, {"charge_type": "MISC_CHARGE", "reverses_posting_id": original["id"]}
    )
    assert mirror["posted_by_user_id"] == CONTROLLER["X-User-ID"], mirror["posted_by_user_id"]

    untouched = validate_success(api.get_journal_posting(original["id"], AUDITOR))
    assert_money(untouched["amount"], 90.00, "the original amount")
    assert_fields(untouched, {"reverses_posting_id": None})

    assert_row_count(
        validate_success(api.list_journal_postings(AUDITOR, folio_id=folio["id"])),
        2,
        "lines of the account",
    )
    assert_row_count(
        validate_success(
            api.list_journal_postings(AUDITOR, reverses_posting_id=original["id"])
        ),
        1,
        "reversing lines",
    )

    account = fx.read_folio(api, folio["id"])
    assert_money_fields(
        account,
        {
            "charges_total_amount": 90.00,
            "credits_total_amount": -90.00,
            "balance_amount": 0.00,
        },
    )
    assert_fields(account, {"settlement_status": "SETTLED"})


def test_an_unresolvable_body_reference_answers_the_referenced_collections_own_404(api):
    """The check is per field, so each broken key names its own collection.

    PRD section 2.12 resolves body references in a fixed order — `property_id`, then
    `business_date_id`, then the account keys, then `outlet_id`, then `ledger_account_id` —
    and reports the collection's own 404 rather than a generic 400 or 422. No orphan is
    created by any refusal.

    Design: Corner/entities/entity_parent_relationships_children_require_a_resolvable_parent_id
    """
    prop = fx.create_property(api)
    outlet = fx.create_outlet(
        api, prop["id"], outlet_code="LOBBY", outlet_name="Lobby Lounge"
    )
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    manager = make_outlet_manager_headers(outlet["id"])

    validate_error(
        api.create_outlet(
            f.build_outlet_payload(
                MISSING_UUID, outlet_code="SPA", outlet_name="Harbor Spa", outlet_type="REMOTE_POS"
            ),
            ADMIN,
        ),
        E.ERR_PROPERTY_NOT_FOUND,
    )
    validate_error(
        api.create_outlet_ticket(
            f.build_outlet_ticket_payload(outlet["id"], MISSING_UUID), manager
        ),
        E.ERR_BUSINESS_DATE_NOT_FOUND,
    )
    validate_error(
        api.create_outlet_ticket(
            f.build_outlet_ticket_payload(MISSING_UUID, bd["id"]), manager
        ),
        E.ERR_OUTLET_NOT_FOUND,
    )
    validate_error(
        api.create_journal_posting(
            f.build_journal_posting_payload(
                bd["id"], "PAYMENT", -10.00, ledger_account_id=MISSING_UUID
            ),
            AUDITOR,
        ),
        E.ERR_LEDGER_ACCOUNT_NOT_FOUND,
    )

    assert_row_count(
        validate_success(api.list_outlets(ADMIN, property_id=prop["id"])), 1, "outlets"
    )


def test_one_request_may_not_straddle_two_properties(api):
    """Both ids resolve, so the refusal is the 422 that guards the flat topology.

    PRD section 2.7 requires every record named by a single request to resolve to the same
    property and refuses a mismatch with ERR_CROSS_PROPERTY_REFERENCE (HTTP 422) — on a
    hand-posted line, on an opened check and on a declared batch alike. Neither side is
    written, and the identical posting inside one property is accepted.

    Design: Corner/entities/entity_flat_topology_two_properties_may_not_be_mixed_in_one_request
    """
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    grand = fx.create_property(api, name="Harbor Grand")
    cliffside = fx.create_property(api, name="Cliffside Inn")
    day_a = fx.create_business_date(api, grand["id"], "2026-08-01", out_of_order_room_count=4)
    day_b = fx.create_business_date(api, cliffside["id"], "2026-08-01", out_of_order_room_count=4)
    folio_b = fx.create_folio(
        api, cliffside["id"], day_b["id"], confirmation_code="CF-XP1", contracted_rate_amount=200.00
    )
    cafe_b = fx.create_outlet(
        api, cliffside["id"], outlet_code="CAFE", outlet_name="Cliffside Cafe"
    )
    manager_b = make_outlet_manager_headers(cafe_b["id"])

    validate_error(
        api.create_journal_posting(
            f.build_journal_posting_payload(
                day_a["id"], "MISC_CHARGE", 25.00, folio_id=folio_b["id"]
            ),
            AUDITOR,
        ),
        E.ERR_CROSS_PROPERTY_REFERENCE,
    )
    validate_error(
        api.create_outlet_ticket(
            f.build_outlet_ticket_payload(cafe_b["id"], day_a["id"]), manager_b
        ),
        E.ERR_CROSS_PROPERTY_REFERENCE,
    )
    validate_error(
        api.create_settlement_batch(
            f.build_settlement_batch_payload(
                day_a["id"],
                cafe_b["id"],
                10.00,
                tender_type="CASH",
                shift_start_at="2026-08-01T14:00:00.000Z",
                shift_end_at="2026-08-01T22:00:00.000Z",
            ),
            manager_b,
        ),
        E.ERR_CROSS_PROPERTY_REFERENCE,
    )

    assert_money(fx.read_folio(api, folio_b["id"])["balance_amount"], 0.00, "balance_amount")
    assert_money(
        fx.read_business_date(api, day_a["id"])["total_revenue_amount"],
        0.00,
        "total_revenue_amount",
    )

    accepted = validate_success(
        api.create_journal_posting(
            f.build_journal_posting_payload(
                day_b["id"], "MISC_CHARGE", 25.00, folio_id=folio_b["id"]
            ),
            AUDITOR,
        ),
        201,
    )
    assert_money(accepted["amount"], 25.00, "amount")
