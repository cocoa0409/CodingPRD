"""
The entity contract of creation, retrieval and listing, and the request-shape
rules that guard the inputs (PRD Sections 2.2, 2.3, 2.4, 2.6, 2.8, 2.10, 3.1,
3.2, 3.3, 3.4, 3.5, 3.7).

Every test here translates one instance of the corner-case index section
`entities`: the declared defaults, the server-owned derived fields, the
entity-specific 404 identifiers and the per-field rejections.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import (
    AGREEMENT_STATUS_DRAFT,
    ANALYST,
    DEAL_STATUS_DRAFT,
    DEAL_STATUS_EXECUTED,
    DEAL_TYPE_DISTRIBUTION_FEE,
    DEAL_TYPE_LABEL_SERVICES,
    DEAL_TYPE_PROFIT_SHARE,
    DEFAULT_DSP_CODE,
    DEFAULT_LIMIT,
    DEFAULT_OBJECTION_WINDOW_DAYS,
    DEFAULT_POST_TERM_COLLECTION_DAYS,
    DEFAULT_RETURNS_RESERVE_PCT,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_ARTIST_NOT_FOUND,
    ERR_DEAL_NOT_FOUND,
    ERR_DISTRIBUTOR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MARKETING_SPEND_NOT_FOUND,
    ERR_PHYSICAL_RUN_NOT_FOUND,
    ERR_RELEASE_NOT_FOUND,
    ERR_REVENUE_REPORT_NOT_FOUND,
    ERR_STATEMENT_NOT_FOUND,
    FORMAT_DIGITAL,
    FORMAT_VINYL,
    INITIAL_VERSION,
    LABEL_ADMIN,
    RECOUPABILITY_HALF,
    RECOUPABILITY_NONE,
    RECOUPMENT_STATUS_UNRECOUPED,
    RESERVE_STATUS_HELD,
    RESPONSE_TYPE_ARRAY,
    RESPONSE_TYPE_OBJECT,
    RUN_STATUS_PLANNED,
    SPEND_CATEGORY_PUBLICITY,
    SPEND_CATEGORY_VIDEO_PRODUCTION,
    SPEND_STATUS_DRAFT,
    assert_append_only_common_fields,
    assert_error_meta_has_no_pagination,
    assert_field,
    assert_field_money,
    assert_fields_money,
    assert_mutable_common_fields,
    assert_null,
    assert_pagination_meta,
    assert_pct_equals,
    assert_request_meta,
    assert_status,
    assert_total_count,
    assert_version_is,
    find_by_id,
    given_released_catalog,
    given_submitted_report,
    ids_of,
    make_partner_headers,
    mk_artist,
    mk_deal,
    mk_distributor,
    mk_release,
    mk_report,
    read_artist,
    read_distributor,
    validate_list,
)

# Two deliberately malformed literals. Neither has a constant in
# test_helpers.constants because neither is a member of any declared enum or
# width, which is exactly why the PRD requires them to be rejected.
UNKNOWN_TIER = "STUDENT"
SHORT_UPC = "01234567"


def _distribution_fee_deal_payload(distributor_id, **overrides):
    """The fully populated DISTRIBUTION_FEE payload of PRD Section 3.1: the fee
    field its own structure requires, and nothing belonging to the other two."""
    kwargs = dict(
        deal_type=DEAL_TYPE_DISTRIBUTION_FEE,
        distribution_fee_pct=f.pct4("0.1500"),
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        territory_codes=("US", "GB"),
        cross_collateralized=True,
        advance_amount_cents=200000,
        marketing_budget_cents=500000,
        objection_window_days=30,
        post_term_collection_days=90,
    )
    kwargs.update(overrides)
    return f.deal_payload(distributor_id, **kwargs)


def test_a_created_deal_returns_the_declared_draft_state_and_zeroed_ledgers(api):
    """"A freshly created deal has status DRAFT. Its advance_payment_reference,
    executed_at, termination_effective_date and post_term_collection_end_date are
    all null, its recoupment_status reads UNRECOUPED, and every derived counter
    ... sits at 0." The 201 therefore carries version 1, the five counters at 0
    and the three fee fields of the other two structures null, none of which the
    client supplied.

    Design: Corner/entities/deal_creation_and_retrieval_round_trip
    """
    distributor = mk_distributor(api, default_returns_reserve_pct=f.pct4("0.1000"))

    response = api.create_deal(
        _distribution_fee_deal_payload(distributor["id"]), LABEL_ADMIN
    )
    deal = validate_success(response, 201)

    assert_request_meta(response)
    assert response.json()["response_type"] == RESPONSE_TYPE_OBJECT
    assert_mutable_common_fields(deal, "DistributionDeal")
    assert_version_is(deal, INITIAL_VERSION, "DistributionDeal")

    assert_status(deal, DEAL_STATUS_DRAFT)
    assert_field(deal, "recoupment_status", RECOUPMENT_STATUS_UNRECOUPED)
    assert_null(
        deal,
        "advance_payment_reference",
        "executed_at",
        "termination_effective_date",
        "post_term_collection_end_date",
    )
    assert_fields_money(
        deal,
        advance_amount_cents=200000,
        advance_recouped_cents=0,
        unrecouped_advance_cents=0,
        net_receipts_to_date_cents=0,
        post_recoupment_net_receipts_cents=0,
        marketing_committed_cents=0,
    )
    assert_null(
        deal,
        "profit_share_label_pct",
        "services_fee_pct",
        "services_monthly_fee_cents",
    )
    assert_pct_equals(
        deal["distribution_fee_pct"], f.pct4("0.1500"), "distribution_fee_pct"
    )
    assert_field(deal, "territory_codes", ["US", "GB"])


def test_reading_a_created_deal_back_returns_the_same_record(api):
    """Creation returns the record and "every other successful call - reads,
    lifecycle transitions, computed projections and the clock control - returns
    200 with the affected or requested record", so an unmutated deal read
    immediately afterwards must agree with the create response field for field,
    still at version 1 with territory_codes ["US", "GB"].

    Design: Corner/entities/deal_creation_and_retrieval_round_trip
    """
    distributor = mk_distributor(api, default_returns_reserve_pct=f.pct4("0.1000"))
    created = validate_success(
        api.create_deal(_distribution_fee_deal_payload(distributor["id"]), LABEL_ADMIN),
        201,
    )

    response = api.get_deal(created["id"], ANALYST)
    fetched = validate_success(response, 200)

    assert_request_meta(response)
    assert set(fetched) == set(created), (
        "the GET exposes a different field set than the create response: %r vs %r"
        % (sorted(fetched), sorted(created))
    )
    for field in sorted(created):
        assert_field(fetched, field, created[field])
    assert_field(fetched, "id", created["id"])
    assert_version_is(fetched, INITIAL_VERSION, "DistributionDeal")
    assert_field(fetched, "territory_codes", ["US", "GB"])


def _three_deals_for_one_distributor_and_one_for_another(api):
    """Four DRAFT deals in a pinned creation order: three under distributor A,
    then one under distributor B."""
    dist_a = mk_distributor(api, name="Vector Digital", legal_entity="Vector Digital LLC")
    dist_b = mk_distributor(api, name="Kestrel Audio", legal_entity="Kestrel Audio Ltd")

    first = mk_deal(api, dist_a["id"], deal_type=DEAL_TYPE_DISTRIBUTION_FEE)
    second = mk_deal(api, dist_a["id"], deal_type=DEAL_TYPE_PROFIT_SHARE)
    third = mk_deal(api, dist_a["id"], deal_type=DEAL_TYPE_LABEL_SERVICES)
    other = mk_deal(api, dist_b["id"], deal_type=DEAL_TYPE_DISTRIBUTION_FEE)
    return dist_a["id"], dist_b["id"], [first, second, third], other


def test_listing_deals_of_one_distributor_pages_that_filtered_total(api):
    """"deals filter by `distributor_id`", and `total_count` "reports how many
    records match the filter before paging is applied". Three of the four deals
    belong to distributor A, so limit=2 offset=0 returns 2 rows with
    total_count 3 and has_more true, and offset=2 returns the remaining 1 row
    with has_more false - never distributor B's deal.

    Design: Corner/entities/deal_listing_pagination_metadata_and_distributor_filter
    """
    dist_a, _dist_b, own, other = _three_deals_for_one_distributor_and_one_for_another(api)

    first_page = api.list_deals(LABEL_ADMIN, {"distributor_id": dist_a, "limit": 2, "offset": 0})
    items, meta = validate_list(first_page)

    assert first_page.json()["response_type"] == RESPONSE_TYPE_ARRAY
    assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)
    assert ids_of(items) == [own[0]["id"], own[1]["id"]], (
        "the first filtered page is not the two oldest deals of distributor A: %r"
        % (ids_of(items),)
    )

    second_items, second_meta = validate_list(
        api.list_deals(LABEL_ADMIN, {"distributor_id": dist_a, "limit": 2, "offset": 2})
    )
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
    assert ids_of(second_items) == [own[2]["id"]], (
        "the second filtered page is not the newest deal of distributor A: %r"
        % (ids_of(second_items),)
    )

    for row in items + second_items:
        assert_field(row, "distributor_id", dist_a)
    assert other["id"] not in ids_of(items) + ids_of(second_items), (
        "distributor B's deal leaked into a page filtered on distributor A"
    )


def test_listing_deals_defaults_its_paging_and_honours_a_status_filter(api):
    """`limit` "defaults to 10 when omitted" and `offset` "defaults to 0", and
    each list endpoint "accepts the relevant foreign key as an optional filter
    alongside `status`". Unparameterised, all four DRAFT deals come back on one
    page of 10; narrowed to distributor A with status EXECUTED, nothing matches
    and total_count is 0.

    Design: Corner/entities/deal_listing_pagination_metadata_and_distributor_filter
    """
    dist_a, _dist_b, own, other = _three_deals_for_one_distributor_and_one_for_another(api)

    items, meta = validate_list(api.list_deals(LABEL_ADMIN))

    assert_pagination_meta(meta, limit=DEFAULT_LIMIT, offset=0, total_count=4, has_more=False)
    assert ids_of(items) == [own[0]["id"], own[1]["id"], own[2]["id"], other["id"]], (
        "the unfiltered listing is not in ascending created_at order: %r" % (ids_of(items),)
    )
    for row in items:
        assert_status(row, DEAL_STATUS_DRAFT)

    executed_items, executed_meta = validate_list(
        api.list_deals(LABEL_ADMIN, {"distributor_id": dist_a, "status": DEAL_STATUS_EXECUTED})
    )
    assert executed_items == [], (
        "a status=EXECUTED filter matched deals that are all still DRAFT: %r"
        % (ids_of(executed_items),)
    )
    assert_pagination_meta(
        executed_meta, limit=DEFAULT_LIMIT, offset=0, total_count=0, has_more=False
    )


def test_every_templated_read_reports_its_own_missing_record_identifier(api):
    """"Every identifier embedded in the URL path resolves to an existing record
    ... The identifier is the one matching the missing record type" - and that
    "rank applies to every endpoint with a templated path segment". Against an
    empty database each of the twelve templated reads answers with its own 404
    identifier, and the error envelope's meta carries no paging fields.

    Design: Corner/entities/not_found_ids_across_every_templated_read
    """
    probes = [
        (lambda: api.get_distributor(NON_EXISTENT_UUID, LABEL_ADMIN), ERR_DISTRIBUTOR_NOT_FOUND),
        (lambda: api.get_artist(NON_EXISTENT_UUID, LABEL_ADMIN), ERR_ARTIST_NOT_FOUND),
        (lambda: api.get_deal(NON_EXISTENT_UUID, LABEL_ADMIN), ERR_DEAL_NOT_FOUND),
        (lambda: api.get_recoupment_summary(NON_EXISTENT_UUID, LABEL_ADMIN), ERR_DEAL_NOT_FOUND),
        (lambda: api.get_release(NON_EXISTENT_UUID, LABEL_ADMIN), ERR_RELEASE_NOT_FOUND),
        (
            lambda: api.list_release_revenue_lines(NON_EXISTENT_UUID, LABEL_ADMIN),
            ERR_RELEASE_NOT_FOUND,
        ),
        (lambda: api.get_agreement(NON_EXISTENT_UUID, LABEL_ADMIN), ERR_AGREEMENT_NOT_FOUND),
        (lambda: api.get_spend(NON_EXISTENT_UUID, LABEL_ADMIN), ERR_MARKETING_SPEND_NOT_FOUND),
        (lambda: api.get_report(NON_EXISTENT_UUID, LABEL_ADMIN), ERR_REVENUE_REPORT_NOT_FOUND),
        (
            lambda: api.list_report_lines(NON_EXISTENT_UUID, LABEL_ADMIN),
            ERR_REVENUE_REPORT_NOT_FOUND,
        ),
        (lambda: api.get_run(NON_EXISTENT_UUID, LABEL_ADMIN), ERR_PHYSICAL_RUN_NOT_FOUND),
        (lambda: api.get_statement(NON_EXISTENT_UUID, LABEL_ADMIN), ERR_STATEMENT_NOT_FOUND),
    ]

    for call, expected_error_id in probes:
        response = call()
        validate_error(response, expected_error_id)
        assert_error_meta_has_no_pagination(response)


def test_omitting_a_required_creation_field_is_a_request_shape_rejection(api):
    """Rank 5 of the ladder demands "required fields present" and reports any
    violation as `ERR_INVALID_REQUEST` (400). Only `objection_window_days` and
    `post_term_collection_days` on a deal and `advance_share_cents` on a release
    are declared optional, so dropping `deal_type`, `territory_codes` or
    `advance_amount_cents` from a deal, or `upc` or `formats` from a release,
    is rejected and nothing is persisted.

    Design: Corner/entities/required_input_field_omission_rejected
    """
    distributor = mk_distributor(api)
    artist = mk_artist(api)
    deal = mk_deal(api, distributor["id"])

    for missing in ("deal_type", "territory_codes", "advance_amount_cents"):
        payload = _distribution_fee_deal_payload(distributor["id"])
        del payload[missing]
        validate_error(api.create_deal(payload, LABEL_ADMIN), ERR_INVALID_REQUEST)

    for missing in ("upc", "formats"):
        payload = f.release_payload(deal["id"], artist["id"])
        del payload[missing]
        validate_error(api.create_release(payload, LABEL_ADMIN), ERR_INVALID_REQUEST)

    assert_total_count(api.list_deals(LABEL_ADMIN, {"distributor_id": distributor["id"]}), 1)
    assert_total_count(api.list_releases(LABEL_ADMIN, {"deal_id": deal["id"]}), 0)


def test_omitted_optional_inputs_take_their_declared_defaults(api):
    """Four declared omission defaults: `default_returns_reserve_pct` "when
    omitted, defaults to 0.2000"; `objection_window_days` "defaults to 30" and
    `post_term_collection_days` "defaults to 180"; `advance_share_cents` "is
    optional, defaults to 0"; and a run's `returns_reserve_pct` "when it is
    omitted it is copied from the shipping partner's
    `default_returns_reserve_pct`", so the run opens at 0.2000, PLANNED and HELD.

    Design: Corner/entities/optional_input_defaults_applied_on_omission
    """
    distributor = validate_success(
        api.create_distributor(f.distributor_payload(), LABEL_ADMIN), 201
    )
    assert_pct_equals(
        distributor["default_returns_reserve_pct"],
        DEFAULT_RETURNS_RESERVE_PCT,
        "default_returns_reserve_pct",
    )
    assert_field(distributor, "active_deal_count", 0)

    deal = validate_success(
        api.create_deal(
            f.deal_payload(distributor["id"], deal_type=DEAL_TYPE_DISTRIBUTION_FEE),
            LABEL_ADMIN,
        ),
        201,
    )
    assert_field(deal, "objection_window_days", DEFAULT_OBJECTION_WINDOW_DAYS)
    assert_field(deal, "post_term_collection_days", DEFAULT_POST_TERM_COLLECTION_DAYS)

    artist = mk_artist(api)
    release = validate_success(
        api.create_release(
            f.release_payload(
                deal["id"], artist["id"], formats=(FORMAT_DIGITAL, FORMAT_VINYL)
            ),
            LABEL_ADMIN,
        ),
        201,
    )
    assert_field_money(release, "advance_share_cents", 0)

    rate_card = validate_success(
        api.create_rate_card(f.rate_card_payload(), LABEL_ADMIN), 201
    )
    assert_null(rate_card, "effective_to")

    run = validate_success(
        api.create_run(f.run_payload(release["id"], distributor["id"]), LABEL_ADMIN), 201
    )
    assert_pct_equals(
        run["returns_reserve_pct"], DEFAULT_RETURNS_RESERVE_PCT, "returns_reserve_pct"
    )
    assert_status(run, RUN_STATUS_PLANNED)
    assert_status(run, RESERVE_STATUS_HELD, field="reserve_status")


def test_a_spends_recoupability_and_actor_fields_are_written_by_the_server(api):
    """Category alone fixes recoupability: it is derived "at creation without the
    requester choosing it", with "`VIDEO_PRODUCTION` and `TOUR_SUPPORT` produce
    `HALF_RECOUPABLE`, and `PUBLICITY` produces `NON_RECOUPABLE`", and "A new
    spend has status `DRAFT`, with `requested_by_user_id`, `decided_by_user_id`,
    `approved_at`, `settled_amount_cents` and `revision_note` all null". A
    client-supplied `id` "is ignored".

    Design: Corner/entities/computed_and_system_fields_are_server_owned_on_creation
    """
    distributor = mk_distributor(api)
    artist = mk_artist(api)
    deal = mk_deal(api, distributor["id"], marketing_budget_cents=1000000)
    release = mk_release(api, deal["id"], artist["id"])

    publicity = validate_success(
        api.create_spend(
            f.spend_payload(
                release["id"],
                category=SPEND_CATEGORY_PUBLICITY,
                amount_cents=40000,
                id=NON_EXISTENT_UUID,
            ),
            LABEL_ADMIN,
        ),
        201,
    )
    assert_field(publicity, "recoupability", RECOUPABILITY_NONE)
    assert publicity["id"] != NON_EXISTENT_UUID, (
        "the server adopted a client-supplied id instead of minting its own"
    )
    assert_status(publicity, SPEND_STATUS_DRAFT)
    assert_null(
        publicity,
        "requested_by_user_id",
        "decided_by_user_id",
        "approved_at",
        "settled_amount_cents",
        "revision_note",
    )

    video = validate_success(
        api.create_spend(
            f.spend_payload(
                release["id"],
                category=SPEND_CATEGORY_VIDEO_PRODUCTION,
                amount_cents=60000,
            ),
            LABEL_ADMIN,
        ),
        201,
    )
    assert_field(video, "recoupability", RECOUPABILITY_HALF)
    assert_status(video, SPEND_STATUS_DRAFT)
    assert_null(video, "requested_by_user_id", "decided_by_user_id", "approved_at")


def test_a_draft_agreement_seeds_no_ledger_and_no_cross_entity_total(api):
    """"A drafted agreement has status `DRAFT`, a null `active_royalty_rate_pct`,
    null `proposed_royalty_rate_pct` and `proposed_advance_amount_cents`, a null
    `post_term_collection_end_date`, and both recoupment balances ... sitting at
    0." A 500,000-cent artist advance and 200,000 of recording cost therefore
    seed nothing, the artist's two derived totals stay at 0, and the
    distributor's `active_deal_count` stays at 0 while the deal is DRAFT.

    Design: Corner/entities/computed_and_system_fields_are_server_owned_on_creation
    """
    distributor = mk_distributor(api)
    artist = mk_artist(api)
    deal = mk_deal(api, distributor["id"], advance_amount_cents=800000)
    release = mk_release(api, deal["id"], artist["id"], advance_share_cents=800000)

    agreement = validate_success(
        api.create_agreement(
            f.agreement_payload(
                artist["id"],
                release["id"],
                advance_amount_cents=500000,
                recording_costs_cents=200000,
                recording_recoupable_pct=f.pct4("0.5000"),
            ),
            LABEL_ADMIN,
        ),
        201,
    )

    assert_status(agreement, AGREEMENT_STATUS_DRAFT)
    assert_null(
        agreement,
        "active_royalty_rate_pct",
        "proposed_royalty_rate_pct",
        "proposed_advance_amount_cents",
        "post_term_collection_end_date",
    )
    assert_fields_money(
        agreement,
        unrecouped_artist_advance_cents=0,
        unrecouped_recording_cents=0,
    )

    assert_fields_money(
        read_artist(api, artist["id"]),
        lifetime_paid_cents=0,
        unrecouped_advance_total_cents=0,
    )
    assert_field(read_distributor(api, distributor["id"]), "active_deal_count", 0)


def test_out_of_range_and_ill_typed_inputs_are_all_rejected_at_rank_five(api):
    """Rank 5 checks "types correct, enum members recognised, percentages
    carrying exactly four decimals and sitting inside their declared range ...
    a term's end strictly after its start, `upc` between 12 and 14 ASCII digits"
    and a spend `amount_cents` that "must be strictly positive". A 0.3500 fee
    (ceiling 0.3000), the two-decimal 0.15, reversed term dates, an eight-digit
    upc, an empty `formats`, an unknown tier and a zero spend are each
    `ERR_INVALID_REQUEST`, and none of them is persisted.

    Design: Corner/entities/type_and_range_constraints_rejected_on_input
    """
    distributor = mk_distributor(api)
    artist = mk_artist(api)
    deal = mk_deal(api, distributor["id"], marketing_budget_cents=1000000)
    release = mk_release(api, deal["id"], artist["id"])

    validate_error(
        api.create_deal(
            _distribution_fee_deal_payload(
                distributor["id"], distribution_fee_pct=f.pct4("0.3500")
            ),
            LABEL_ADMIN,
        ),
        ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_deal(
            _distribution_fee_deal_payload(
                distributor["id"], distribution_fee_pct=f.pct("0.15")
            ),
            LABEL_ADMIN,
        ),
        ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_deal(
            _distribution_fee_deal_payload(
                distributor["id"],
                term_start_date="2026-12-31",
                term_end_date="2026-01-01",
            ),
            LABEL_ADMIN,
        ),
        ERR_INVALID_REQUEST,
    )

    validate_error(
        api.create_release(
            f.release_payload(deal["id"], artist["id"], upc=SHORT_UPC), LABEL_ADMIN
        ),
        ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_release(
            f.release_payload(deal["id"], artist["id"], formats=()), LABEL_ADMIN
        ),
        ERR_INVALID_REQUEST,
    )

    validate_error(
        api.create_rate_card(f.rate_card_payload(tier=UNKNOWN_TIER), LABEL_ADMIN),
        ERR_INVALID_REQUEST,
    )

    validate_error(
        api.create_spend(
            f.spend_payload(release["id"], amount_cents=0), LABEL_ADMIN
        ),
        ERR_INVALID_REQUEST,
    )

    assert_total_count(api.list_deals(LABEL_ADMIN), 1)
    assert_total_count(api.list_releases(LABEL_ADMIN, {"deal_id": deal["id"]}), 1)
    assert_total_count(api.list_rate_cards(LABEL_ADMIN), 0)
    assert_total_count(api.list_spends(LABEL_ADMIN, {"release_id": release["id"]}), 0)


def test_a_rate_card_and_a_revenue_line_expose_no_version_counter(api):
    """"Two record types are immutable once written and therefore carry only `id`
    and `created_at`: the stream rate card and the DSP revenue line. Both
    `updated_at` and `version` are absent from those two payloads entirely." A
    newly appended line also has "`applied_rate_micros_per_stream`,
    `resolved_revenue_cents` and `net_receipts_cents` all null", and the two
    listings that expose them repeat the same append-only shape.

    Design: Corner/entities/immutable_entities_carry_no_version_and_no_write_surface
    """
    ctx = given_released_catalog(api)

    card = validate_success(
        api.create_rate_card(f.rate_card_payload(), LABEL_ADMIN), 201
    )
    assert_append_only_common_fields(card, "StreamRateCard")

    report = mk_report(api, ctx["deal_id"], ctx["partner_headers"])
    response = api.append_line(
        report["id"], f.line_payload(ctx["release_id"]), ctx["partner_headers"]
    )
    line = validate_success(response, 201)
    assert_append_only_common_fields(line, "DspRevenueLine")
    assert_null(
        line,
        "applied_rate_micros_per_stream",
        "resolved_revenue_cents",
        "net_receipts_cents",
    )

    cards, cards_meta = validate_list(
        api.list_rate_cards(LABEL_ADMIN, {"dsp_code": DEFAULT_DSP_CODE})
    )
    assert_pagination_meta(
        cards_meta, limit=DEFAULT_LIMIT, offset=0, total_count=1, has_more=False
    )
    assert_append_only_common_fields(find_by_id(cards, card["id"]), "StreamRateCard")

    listed_lines, lines_meta = validate_list(api.list_report_lines(report["id"], LABEL_ADMIN))
    assert_pagination_meta(
        lines_meta, limit=DEFAULT_LIMIT, offset=0, total_count=1, has_more=False
    )
    assert_append_only_common_fields(find_by_id(listed_lines, line["id"]), "DspRevenueLine")


def test_pricing_a_line_writes_its_money_without_giving_it_a_version(api):
    """Pricing writes onto the line but opens no write surface: "A revenue line's
    computed money fields are written by the report-level operations that price
    and allocate it, but the line itself is never re-created, re-parented or
    edited by a client, and it exposes no version counter for a client to echo."
    250,000 streams at 4,000 micros price to 100,000 cents, while
    `net_receipts_cents` stays null until acceptance and `version` never appears.

    Design: Corner/entities/immutable_entities_carry_no_version_and_no_write_surface
    """
    ctx = given_released_catalog(api)
    ctx = given_submitted_report(api, ctx)

    listed_lines, meta = validate_list(
        api.list_report_lines(ctx["report_id"], LABEL_ADMIN)
    )
    assert_pagination_meta(
        meta, limit=DEFAULT_LIMIT, offset=0, total_count=1, has_more=False
    )

    line = find_by_id(listed_lines, ctx["lines"][0]["id"])
    assert_append_only_common_fields(line, "DspRevenueLine")
    assert_field(line, "applied_rate_micros_per_stream", 4000)
    assert_field_money(line, "resolved_revenue_cents", 100000)
    assert_null(line, "net_receipts_cents")


def test_a_body_foreign_key_that_resolves_to_nothing_names_its_own_entity(api):
    """"Every foreign key supplied in the request body resolves to an existing
    record - `distributor_id`, `artist_id`, `deal_id`, `primary_artist_id`,
    `release_id`, `artist_agreement_id` and `supersedes_agreement_id` -
    otherwise the matching one of `ERR_DISTRIBUTOR_NOT_FOUND`,
    `ERR_ARTIST_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`, `ERR_RELEASE_NOT_FOUND` or
    `ERR_AGREEMENT_NOT_FOUND` (404)." Each of the eight creating operations that
    accepts a foreign key therefore answers for the entity its own key names.

    Design: Corner/entities/flat_topology_body_foreign_keys_resolved_per_entity
    """
    distributor = mk_distributor(api)
    artist = mk_artist(api)
    deal = mk_deal(api, distributor["id"], marketing_budget_cents=1000000)
    release = mk_release(
        api, deal["id"], artist["id"], formats=(FORMAT_DIGITAL, FORMAT_VINYL)
    )
    partner_headers = make_partner_headers(distributor["id"])

    validate_error(
        api.create_deal(
            _distribution_fee_deal_payload(NON_EXISTENT_UUID), LABEL_ADMIN
        ),
        ERR_DISTRIBUTOR_NOT_FOUND,
    )
    validate_error(
        api.create_release(
            f.release_payload(NON_EXISTENT_UUID, artist["id"]), LABEL_ADMIN
        ),
        ERR_DEAL_NOT_FOUND,
    )
    validate_error(
        api.create_release(
            f.release_payload(deal["id"], NON_EXISTENT_UUID), LABEL_ADMIN
        ),
        ERR_ARTIST_NOT_FOUND,
    )
    validate_error(
        api.create_agreement(
            f.agreement_payload(
                artist["id"], release["id"], supersedes_agreement_id=NON_EXISTENT_UUID
            ),
            LABEL_ADMIN,
        ),
        ERR_AGREEMENT_NOT_FOUND,
    )
    validate_error(
        api.create_spend(f.spend_payload(NON_EXISTENT_UUID), LABEL_ADMIN),
        ERR_RELEASE_NOT_FOUND,
    )
    validate_error(
        api.create_report(f.report_payload(NON_EXISTENT_UUID), partner_headers),
        ERR_DEAL_NOT_FOUND,
    )
    validate_error(
        api.create_run(f.run_payload(release["id"], NON_EXISTENT_UUID), LABEL_ADMIN),
        ERR_DISTRIBUTOR_NOT_FOUND,
    )
    validate_error(
        api.create_statement(f.statement_payload(NON_EXISTENT_UUID), ANALYST),
        ERR_AGREEMENT_NOT_FOUND,
    )
