"""
The endpoint surface and the error catalogue: CRUD round trips, action-endpoint
side effects, derived rollups, and each error id proven independently triggerable
(PRD Sections 2.4, 2.8, 3.1-3.9, 4, 5).

Every test here translates one instance of the corner index sections `endpoints`
and `errors`.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import (
    AGREEMENT_STATUS_ACTIVE,
    AGREEMENT_STATUS_DRAFT,
    ANALYST,
    AUDIT_STATUS_NONE,
    AUDIT_STATUS_REQUESTED,
    BASIS_VARIANT_FINAL,
    BASIS_VARIANT_PROVISIONAL,
    BIZ_AFFAIRS,
    DEAL_STATUS_CLOSED,
    DEAL_STATUS_DRAFT,
    DEAL_STATUS_EXECUTED,
    DEAL_STATUS_EXPIRED,
    DEAL_TYPE_LABEL_SERVICES,
    DEAL_TYPE_PROFIT_SHARE,
    DEFAULT_CLOCK_INSTANT,
    DEFAULT_OBJECTION_WINDOW_DAYS,
    DEFAULT_POST_TERM_COLLECTION_DAYS,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_ARTIST_NOT_FOUND,
    ERR_AUDIT_WINDOW_EXPIRED,
    ERR_DEAL_NOT_COLLECTING,
    ERR_DEAL_NOT_FOUND,
    ERR_DISTRIBUTOR_NOT_FOUND,
    ERR_INVALID_AGREEMENT_STATE,
    ERR_INVALID_DEAL_STATE,
    ERR_INVALID_RELEASE_STATE,
    ERR_INVALID_RUN_STATE,
    ERR_INVALID_STATEMENT_STATE,
    ERR_INVENTORY_OBLIGATION_BREACH,
    ERR_LIQUIDATION_EXCEEDS_RESERVE,
    ERR_MARKETING_SPEND_NOT_FOUND,
    ERR_PERIOD_OUTSIDE_TERM,
    ERR_PHYSICAL_RUN_NOT_FOUND,
    ERR_PROVISIONAL_NOT_ISSUABLE,
    ERR_RELEASE_NOT_FOUND,
    ERR_RELEASE_NOT_PROMOTABLE,
    ERR_RETURNS_EXCEED_SHIPPED,
    ERR_REVENUE_REPORT_NOT_FOUND,
    ERR_STATEMENT_NOT_FOUND,
    FORMAT_CD,
    FORMAT_DIGITAL,
    FORMAT_VINYL,
    INITIAL_VERSION,
    LABEL_ADMIN,
    RELEASE_STATUS_REVERSION_PENDING,
    REPORT_STATUS_SUBMITTED,
    RESERVE_STATUS_HELD,
    RESERVE_STATUS_LIQUIDATED,
    RESERVE_STATUS_PARTIALLY_LIQUIDATED,
    RUN_STATUS_MANUFACTURED,
    RUN_STATUS_PLANNED,
    RUN_STATUS_RECONCILED,
    STATEMENT_STATUS_DRAFT,
    STATEMENT_STATUS_FINALIZED,
    STATEMENT_STATUS_ISSUED,
    STATEMENT_STATUS_PREPARED,
    assert_date,
    assert_field,
    assert_field_money,
    assert_fields,
    assert_fields_money,
    assert_instant_equals,
    assert_instant_precision,
    assert_null,
    assert_pagination_meta,
    assert_pct_equals,
    assert_status,
    assert_version_bumped,
    assert_version_is,
    do_activate_agreement,
    do_close_deal,
    do_enter_post_term_collection,
    do_execute_deal,
    do_expire_deal,
    do_manufacture,
    do_prepare_statement,
    do_release_to_market,
    do_set_clock,
    do_terminate_deal,
    given_active_agreement,
    given_distributor_and_artist,
    given_finalized_statement,
    given_issued_statement,
    given_released_catalog,
    given_shipped_run,
    given_submitted_report,
    ids_of,
    mk_artist,
    mk_deal,
    mk_distributor,
    mk_release,
    mk_run,
    mk_statement,
    read_agreement,
    read_deal,
    read_distributor,
    read_release,
    read_report,
    read_run,
    read_statement,
    run_version,
    validate_list,
)

PHYSICAL_PARTNER = {
    "name": "Harbourside Physical",
    "legal_entity": "Harbourside Physical Ltd",
}


def test_a_created_distributor_deal_and_artist_read_back_their_stored_fields(api):
    """The plain CRUD surface: records carry "`created_at`, the instant the record
    was written, formatted as an ISO 8601 UTC timestamp with exactly three
    fractional digits", `version` "begins at 1 when the record is created", and the
    omitted optional inputs take their declared defaults - 0.1200 preserved to four
    decimals, `active_deal_count` 0, `objection_window_days` 30 and
    `post_term_collection_days` 180.

    Design: Corner/endpoints/create_read_and_list_round_trip_echoes_every_stored_field
    """
    resp = api.create_distributor(
        f.distributor_payload(default_returns_reserve_pct=f.pct4("0.1200")), LABEL_ADMIN
    )
    distributor = validate_success(resp, 201)
    assert_version_is(distributor, INITIAL_VERSION, entity="distributor")
    assert_instant_equals(distributor["created_at"], DEFAULT_CLOCK_INSTANT, "created_at")
    assert_instant_precision(distributor["created_at"], "created_at")
    assert_instant_precision(distributor["updated_at"], "updated_at")

    read_back = validate_success(api.get_distributor(distributor["id"], LABEL_ADMIN), 200)
    assert_fields(
        read_back,
        id=distributor["id"],
        name="Vector Digital",
        legal_entity="Vector Digital LLC",
        active_deal_count=0,
    )
    assert_pct_equals(
        read_back["default_returns_reserve_pct"], "0.1200", "default_returns_reserve_pct"
    )

    artist = mk_artist(api)
    artist_read = validate_success(api.get_artist(artist["id"], ANALYST), 200)
    assert_fields_money(
        artist_read, lifetime_paid_cents=0, unrecouped_advance_total_cents=0
    )

    resp = api.create_deal(
        f.deal_payload(
            distributor["id"],
            distribution_fee_pct=f.pct4("0.1500"),
            territory_codes=("US", "GB"),
            advance_amount_cents=250000,
            marketing_budget_cents=400000,
        ),
        LABEL_ADMIN,
    )
    deal = validate_success(resp, 201)
    assert_status(deal, DEAL_STATUS_DRAFT)
    assert_fields(
        deal,
        territory_codes=["US", "GB"],
        objection_window_days=DEFAULT_OBJECTION_WINDOW_DAYS,
        post_term_collection_days=DEFAULT_POST_TERM_COLLECTION_DAYS,
    )
    assert_fields_money(
        deal, advance_amount_cents=250000, marketing_budget_cents=400000
    )
    assert_null(
        deal,
        "profit_share_label_pct",
        "services_fee_pct",
        "services_monthly_fee_cents",
    )


def test_the_deal_collection_applies_its_filters_and_its_page_window(api):
    """The collection surface and the entity-specific 404: three deals on one
    distributor page two at a time, the `status` filter narrows to zero while every
    deal is `DRAFT`, and an unknown distributor id is "`ERR_DISTRIBUTOR_NOT_FOUND`"
    rather than a generic not-found. The explicitly supplied 45 and 120 windows
    survive the round trip.

    Design: Corner/endpoints/create_read_and_list_round_trip_echoes_every_stored_field
    """
    distributor = mk_distributor(api)
    fee_deal = mk_deal(api, distributor["id"], distribution_fee_pct=f.pct4("0.1500"))
    profit_deal = mk_deal(
        api,
        distributor["id"],
        deal_type=DEAL_TYPE_PROFIT_SHARE,
        profit_share_label_pct=f.pct4("0.6500"),
        term_start_date="2026-02-01",
        term_end_date="2027-01-31",
        cross_collateralized=False,
        objection_window_days=45,
        post_term_collection_days=120,
    )
    services_deal = mk_deal(
        api,
        distributor["id"],
        deal_type=DEAL_TYPE_LABEL_SERVICES,
        services_fee_pct=f.pct4("0.1000"),
        services_monthly_fee_cents=25000,
        term_start_date="2026-03-01",
        term_end_date="2026-11-30",
        territory_codes=("DE",),
        cross_collateralized=False,
    )
    assert_fields(
        profit_deal, objection_window_days=45, post_term_collection_days=120
    )

    first_page, first_meta = validate_list(
        api.list_deals(
            ANALYST,
            params={"distributor_id": distributor["id"], "limit": 2, "offset": 0},
        )
    )
    assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)
    assert len(first_page) == 2

    second_page, second_meta = validate_list(
        api.list_deals(
            ANALYST,
            params={"distributor_id": distributor["id"], "limit": 2, "offset": 2},
        )
    )
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
    assert len(second_page) == 1

    paged_ids = ids_of(first_page) + ids_of(second_page)
    assert len(set(paged_ids)) == 3
    assert set(paged_ids) == {fee_deal["id"], profit_deal["id"], services_deal["id"]}

    executed, executed_meta = validate_list(
        api.list_deals(
            ANALYST,
            params={
                "distributor_id": distributor["id"],
                "status": DEAL_STATUS_EXECUTED,
                "limit": 50,
                "offset": 0,
            },
        )
    )
    assert executed == []
    assert executed_meta["total_count"] == 0

    validate_error(
        api.get_distributor(NON_EXISTENT_UUID, LABEL_ADMIN),
        ERR_DISTRIBUTOR_NOT_FOUND,
        404,
    )


def test_manufacturing_books_the_actual_quantity_and_then_locks_the_run(api):
    """The manufacture action endpoint's declared side effects in one call:
    "the planned per-unit cost applied to the actual quantity, not to
    `units_planned`", so 1200 units at 250 cents book 300000 rather than the
    planned 1500 units' 375000, the run moves PLANNED -> MANUFACTURED with
    version 2, and a repeat call is refused on the fulfilment axis while the
    reserve axis stays HELD.

    Design: Corner/endpoints/manufacture_action_writes_cost_and_refuses_a_second_call
    """
    ctx = given_released_catalog(
        api,
        distributor_kw=dict(PHYSICAL_PARTNER, default_returns_reserve_pct=f.pct4("0.1200")),
        deal_kw={"post_term_collection_days": 90},
        releases=[{"title": "Heavyweight", "formats": (FORMAT_VINYL, FORMAT_DIGITAL)}],
    )
    run = mk_run(
        api,
        ctx["release_id"],
        ctx["dist_id"],
        units_planned=1500,
        unit_manufacturing_cost_cents=250,
        window_start="2026-04-01",
        window_end="2026-06-30",
    )
    assert_status(run, RUN_STATUS_PLANNED)
    assert_status(run, RESERVE_STATUS_HELD, field="reserve_status")
    assert_version_is(run, INITIAL_VERSION, entity="physical run")
    assert_pct_equals(run["returns_reserve_pct"], "0.1200", "returns_reserve_pct")

    manufactured = validate_success(
        api.manufacture_run(run["id"], f.manufacture_payload(1200), LABEL_ADMIN), 200
    )
    assert_field_money(manufactured, "manufacturing_cost_cents", 300000)
    assert_field(manufactured, "units_manufactured", 1200)
    assert_status(manufactured, RUN_STATUS_MANUFACTURED)
    assert_version_bumped(run, manufactured, entity="physical run")

    validate_error(
        api.manufacture_run(run["id"], f.manufacture_payload(100), LABEL_ADMIN),
        ERR_INVALID_RUN_STATE,
        409,
    )
    after_rejection = read_run(api, run["id"])
    assert_field_money(after_rejection, "manufacturing_cost_cents", 300000)
    assert_field(after_rejection, "units_manufactured", 1200)
    assert_version_is(after_rejection, manufactured["version"], entity="physical run")

    runs, _ = validate_list(
        api.list_runs(
            ANALYST,
            params={
                "release_id": ctx["release_id"],
                "status": RUN_STATUS_MANUFACTURED,
                "limit": 50,
                "offset": 0,
            },
        )
    )
    assert ids_of(runs) == [run["id"]]
    assert_status(runs[0], RESERVE_STATUS_HELD, field="reserve_status")


def test_the_distributors_active_deal_count_follows_three_deals_around_the_lifecycle(api):
    """The derived rollup is recomputed, not incremented: "it is the number of
    distribution deals naming this distributor whose status is `EXECUTED`,
    `TERMINATION_NOTICE` or `POST_TERM_COLLECTION`, and it is recomputed whenever
    a deal enters or leaves that set". Three deals on one distributor walk the
    counter 0 -> 2 -> 1 -> 1 -> 2 -> 1.

    Design: Corner/endpoints/distributor_active_deal_count_recomputes_on_every_lifecycle_hop
    """
    ctx = given_distributor_and_artist(api)
    short_terms = {
        "term_start_date": "2026-01-01",
        "term_end_date": "2026-06-30",
        "post_term_collection_days": 30,
    }
    long_terms = {
        "term_start_date": "2026-01-01",
        "term_end_date": "2026-12-31",
        "post_term_collection_days": 30,
    }
    deal_a = mk_deal(api, ctx["dist_id"], **short_terms)
    mk_release(api, deal_a["id"], ctx["artist_id"], title="Deal A Single")
    deal_b = mk_deal(api, ctx["dist_id"], **long_terms)
    mk_release(api, deal_b["id"], ctx["artist_id"], title="Deal B Single")
    deal_c = mk_deal(api, ctx["dist_id"], **long_terms)
    mk_release(api, deal_c["id"], ctx["artist_id"], title="Deal C Single")

    assert_field(read_distributor(api, ctx["dist_id"]), "active_deal_count", 0)

    do_execute_deal(api, deal_a["id"], advance_payment_reference="WIRE-E3-000A")
    do_execute_deal(api, deal_b["id"], advance_payment_reference="WIRE-E3-000B")
    assert_field(read_distributor(api, ctx["dist_id"]), "active_deal_count", 2)

    do_set_clock(api, "2026-08-05T00:00:00.000Z")
    expired = do_expire_deal(api, deal_a["id"])
    assert_status(expired, DEAL_STATUS_EXPIRED)
    assert_field(read_distributor(api, ctx["dist_id"]), "active_deal_count", 1)

    do_terminate_deal(api, deal_b["id"])
    assert_field(read_distributor(api, ctx["dist_id"]), "active_deal_count", 1)

    do_enter_post_term_collection(api, deal_a["id"])
    assert_field(read_distributor(api, ctx["dist_id"]), "active_deal_count", 2)

    do_set_clock(api, "2026-08-31T00:00:00.000Z")
    closed = do_close_deal(api, deal_a["id"])
    assert_status(closed, DEAL_STATUS_CLOSED)
    assert_field(read_distributor(api, ctx["dist_id"]), "active_deal_count", 1)

    assert_status(read_deal(api, deal_c["id"]), DEAL_STATUS_DRAFT)


def test_an_agreement_resolves_its_artist_and_its_release_independently(api):
    """The two-sided link: a fabricated `artist_id` and a fabricated `release_id`
    each report their own 404, and the accepted draft stores the supplied
    featured performer rather than the release's primary artist. Both balances
    obey "Nothing is recoupable until the agreement is activated", after which
    "`unrecouped_artist_advance_cents` is seeded from `advance_amount_cents`" at
    50000 and the recording half at 10000 == 20000 x 0.5000.

    Design: Corner/endpoints/agreement_links_artist_and_release_and_resolves_both_foreign_keys
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"post_term_collection_days": 90},
        releases=[{"title": "Duet"}],
    )
    featured = mk_artist(api, legal_name="Bo Lantern")
    terms = {
        "royalty_rate_pct": f.pct4("0.1500"),
        "escalated_royalty_rate_pct": f.pct4("0.1800"),
        "advance_amount_cents": 50000,
        "recording_costs_cents": 20000,
        "recording_recoupable_pct": f.pct4("0.5000"),
        "marketing_recoup_share_pct": f.pct4("0.5000"),
    }

    validate_error(
        api.create_agreement(
            f.agreement_payload(NON_EXISTENT_UUID, ctx["release_id"], **terms),
            LABEL_ADMIN,
        ),
        ERR_ARTIST_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_agreement(
            f.agreement_payload(featured["id"], NON_EXISTENT_UUID, **terms), LABEL_ADMIN
        ),
        ERR_RELEASE_NOT_FOUND,
        404,
    )

    agreement = validate_success(
        api.create_agreement(
            f.agreement_payload(featured["id"], ctx["release_id"], **terms), LABEL_ADMIN
        ),
        201,
    )
    assert_fields(
        agreement, artist_id=featured["id"], release_id=ctx["release_id"]
    )
    assert agreement["artist_id"] != ctx["artist_id"]
    assert_status(agreement, AGREEMENT_STATUS_DRAFT)
    assert_version_is(agreement, INITIAL_VERSION, entity="agreement")
    assert_fields_money(
        agreement, unrecouped_artist_advance_cents=0, unrecouped_recording_cents=0
    )

    activated = do_activate_agreement(api, agreement["id"])
    assert_status(activated, AGREEMENT_STATUS_ACTIVE)
    assert_fields_money(
        activated,
        unrecouped_artist_advance_cents=50000,
        unrecouped_recording_cents=10000,
    )

    by_release, _ = validate_list(
        api.list_agreements(
            ANALYST, params={"release_id": ctx["release_id"], "limit": 50, "offset": 0}
        )
    )
    assert ids_of(by_release) == [agreement["id"]]
    by_featured, _ = validate_list(
        api.list_agreements(
            ANALYST, params={"artist_id": featured["id"], "limit": 50, "offset": 0}
        )
    )
    assert ids_of(by_featured) == [agreement["id"]]
    by_primary, _ = validate_list(
        api.list_agreements(
            ANALYST, params={"artist_id": ctx["artist_id"], "limit": 50, "offset": 0}
        )
    )
    assert by_primary == []


def test_a_pressing_run_is_refused_on_a_streaming_only_release(api):
    """Two releases on one deal differ only in the `formats` array: "its `formats`
    must contain at least one of `VINYL`, `CD` or `CASSETTE`, and planning a run
    against a purely digital release is refused with `ERR_INVALID_RELEASE_STATE`
    (409)". The CD release accepts the same body and keeps the supplied 0.2500
    rather than the partner's 0.2000.

    Design: Corner/endpoints/physical_run_rejects_a_digital_only_release
    """
    ctx = given_released_catalog(
        api,
        distributor_kw=dict(PHYSICAL_PARTNER, default_returns_reserve_pct=f.pct4("0.2000")),
        deal_kw={"post_term_collection_days": 90},
        releases=[
            {"title": "Streaming Only", "formats": (FORMAT_DIGITAL,)},
            {"title": "Jewel Case", "formats": (FORMAT_CD, FORMAT_DIGITAL)},
        ],
    )
    digital_release, cd_release = ctx["releases"]
    body = {
        "units_planned": 1000,
        "unit_manufacturing_cost_cents": 300,
        "window_start": "2026-04-01",
        "window_end": "2026-06-30",
    }

    validate_error(
        api.create_run(
            f.run_payload(digital_release["id"], ctx["dist_id"], **body), LABEL_ADMIN
        ),
        ERR_INVALID_RELEASE_STATE,
        409,
    )

    run = validate_success(
        api.create_run(
            f.run_payload(
                cd_release["id"],
                ctx["dist_id"],
                returns_reserve_pct=f.pct4("0.2500"),
                **body
            ),
            LABEL_ADMIN,
        ),
        201,
    )
    assert_status(run, RUN_STATUS_PLANNED)
    assert_status(run, RESERVE_STATUS_HELD, field="reserve_status")
    assert_pct_equals(run["returns_reserve_pct"], "0.2500", "returns_reserve_pct")

    digital_runs, _ = validate_list(
        api.list_runs(
            ANALYST,
            params={"release_id": digital_release["id"], "limit": 50, "offset": 0},
        )
    )
    assert digital_runs == []
    partner_runs, _ = validate_list(
        api.list_runs(
            ANALYST, params={"distributor_id": ctx["dist_id"], "limit": 50, "offset": 0}
        )
    )
    assert ids_of(partner_runs) == [run["id"]]


def test_each_read_path_names_the_entity_its_own_segment_addresses(api):
    """Rank 3 of the ladder says "Every identifier embedded in the URL path
    resolves to an existing record, validated left to right" and "The identifier
    is the one matching the missing record type", so the same unused UUID draws
    eight distinct 404 ids across eight collections; the line-append path also
    proves rank 3 beats rank 6 with a fully valid body.

    Design: Corner/errors/every_path_id_returns_its_own_entity_not_found
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"marketing_budget_cents": 100000, "post_term_collection_days": 90},
        releases=[{"title": "Anchor"}],
    )

    seen = [
        validate_error(
            api.get_agreement(NON_EXISTENT_UUID, ANALYST), ERR_AGREEMENT_NOT_FOUND, 404
        ),
        validate_error(
            api.get_report(NON_EXISTENT_UUID, ANALYST), ERR_REVENUE_REPORT_NOT_FOUND, 404
        ),
        validate_error(
            api.get_run(NON_EXISTENT_UUID, ANALYST), ERR_PHYSICAL_RUN_NOT_FOUND, 404
        ),
        validate_error(
            api.get_statement(NON_EXISTENT_UUID, ANALYST), ERR_STATEMENT_NOT_FOUND, 404
        ),
        validate_error(
            api.get_release(NON_EXISTENT_UUID, ANALYST), ERR_RELEASE_NOT_FOUND, 404
        ),
        validate_error(api.get_deal(NON_EXISTENT_UUID, ANALYST), ERR_DEAL_NOT_FOUND, 404),
        validate_error(
            api.get_artist(NON_EXISTENT_UUID, ANALYST), ERR_ARTIST_NOT_FOUND, 404
        ),
        validate_error(
            api.get_spend(NON_EXISTENT_UUID, ANALYST), ERR_MARKETING_SPEND_NOT_FOUND, 404
        ),
    ]
    assert len({entry["error_id"] for entry in seen}) == 8
    for entry in seen:
        assert entry["message"]

    validate_error(
        api.append_line(
            NON_EXISTENT_UUID,
            f.line_payload(ctx["release_id"], stream_count=1000),
            ctx["partner_headers"],
        ),
        ERR_REVENUE_REPORT_NOT_FOUND,
        404,
    )


def test_three_entities_each_answer_a_repeated_transition_with_their_own_conflict(api):
    """Rank 8 gives every record type its own 409: "The identifier names the record
    type: `ERR_INVALID_DEAL_STATE`, `ERR_INVALID_RELEASE_STATE`,
    `ERR_INVALID_AGREEMENT_STATE`". Re-executing an EXECUTED deal, re-activating
    an ACTIVE agreement and re-preparing an ISSUED statement give three distinct
    ids, and none of the three rejections moves a version.

    Design: Corner/errors/repeated_transitions_report_each_entitys_own_state_conflict
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"post_term_collection_days": 90},
        releases=[{"title": "Twice Told"}],
    )
    ctx = given_active_agreement(api, ctx)
    ctx = given_issued_statement(api, ctx)

    deal_error = validate_error(
        api.execute_deal(
            ctx["deal_id"], f.execute_payload("WIRE-X2-0002"), LABEL_ADMIN
        ),
        ERR_INVALID_DEAL_STATE,
        409,
    )
    agreement_error = validate_error(
        api.activate_agreement(ctx["agreement_id"], LABEL_ADMIN),
        ERR_INVALID_AGREEMENT_STATE,
        409,
    )
    statement_error = validate_error(
        api.prepare_statement(ctx["statement_id"], ANALYST),
        ERR_INVALID_STATEMENT_STATE,
        409,
    )
    assert (
        len(
            {
                deal_error["error_id"],
                agreement_error["error_id"],
                statement_error["error_id"],
            }
        )
        == 3
    )

    deal_after = read_deal(api, ctx["deal_id"])
    assert_field(deal_after, "advance_payment_reference", "WIRE-2026-0031")
    assert_version_is(deal_after, ctx["deal"]["version"], entity="deal")
    assert_version_is(
        read_agreement(api, ctx["agreement_id"]),
        ctx["agreement"]["version"],
        entity="agreement",
    )
    statement_after = read_statement(api, ctx["statement_id"])
    assert_status(statement_after, STATEMENT_STATUS_ISSUED)
    assert_version_is(
        statement_after, ctx["statement"]["version"], entity="statement"
    )
    assert statement_after["objection_deadline"] is not None


def test_an_expired_deal_and_a_reverting_release_each_close_their_own_door(api):
    """Two cross-entity gates that sit beside the plain from-state check. Accepting
    a SUBMITTED report needs a deal whose "status must be `EXECUTED`,
    `TERMINATION_NOTICE` or `POST_TERM_COLLECTION`, since a `DRAFT`, `EXPIRED` or
    `CLOSED` deal cannot absorb receipts", and "a release in `REVERSION_PENDING`
    or `REVERTED` may not accrue new marketing and the attempt is rejected with
    `ERR_RELEASE_NOT_PROMOTABLE` (409)" - at creation, not at approval.

    Design: Corner/errors/expired_deal_and_reverting_release_block_new_accounting
    """
    ctx = given_released_catalog(
        api,
        deal_kw={
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-06-30",
            "post_term_collection_days": 90,
        },
        releases=[{"title": "Short Term"}],
    )
    ctx = given_submitted_report(api, ctx, lines=[{"stream_count": 250000}])
    assert_status(ctx["report"], REPORT_STATUS_SUBMITTED)

    expired = do_expire_deal(api, ctx["deal_id"])
    assert_status(expired, DEAL_STATUS_EXPIRED)
    assert_date(
        expired["post_term_collection_end_date"],
        "2026-09-28",
        "post_term_collection_end_date",
    )

    validate_error(
        api.accept_report(
            ctx["report_id"], f.accept_report_payload(expired["version"]), ANALYST
        ),
        ERR_DEAL_NOT_COLLECTING,
        409,
    )
    after = read_report(api, ctx["report_id"])
    assert_status(after, REPORT_STATUS_SUBMITTED)
    assert_field_money(read_deal(api, ctx["deal_id"]), "net_receipts_to_date_cents", 0)

    terminated_deal = mk_deal(
        api,
        ctx["dist_id"],
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        marketing_budget_cents=100000,
        post_term_collection_days=90,
    )
    reverting = mk_release(
        api, terminated_deal["id"], ctx["artist_id"], title="Cut Short"
    )
    do_execute_deal(
        api, terminated_deal["id"], advance_payment_reference="WIRE-X3-000B"
    )
    do_release_to_market(api, reverting["id"])
    do_terminate_deal(api, terminated_deal["id"])
    assert_status(
        read_release(api, reverting["id"]), RELEASE_STATUS_REVERSION_PENDING
    )

    validate_error(
        api.create_spend(
            f.spend_payload(reverting["id"], amount_cents=50000), LABEL_ADMIN
        ),
        ERR_RELEASE_NOT_PROMOTABLE,
        409,
    )
    spends, _ = validate_list(
        api.list_spends(
            ANALYST, params={"release_id": reverting["id"], "limit": 50, "offset": 0}
        )
    )
    assert spends == []


def test_an_out_of_term_period_and_an_interim_variant_fail_for_different_reasons(api):
    """Two 422s on one agreement, separated by cause. Preparation checks that "On
    the `DRAFT` entry the statement's period must lie inside the deal's accountable
    span", which for an EXECUTED deal falls back to term_end_date 2026-12-31, so a
    period ending 2027-01-31 is refused; and "only a `FINAL` statement may be
    published at all; issuing a `PROVISIONAL` statement is refused with
    `ERR_PROVISIONAL_NOT_ISSUABLE` (422)" even though PREPARED is a legal
    from-state of issue.

    Design: Corner/errors/statement_period_and_variant_constraints_are_reported_distinctly
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"post_term_collection_days": 90},
        releases=[{"title": "Interim"}],
    )
    ctx = given_active_agreement(api, ctx)

    out_of_term = validate_success(
        api.create_statement(
            f.statement_payload(
                ctx["agreement_id"],
                period_start="2026-10-01",
                period_end="2027-01-31",
                basis_variant=BASIS_VARIANT_FINAL,
            ),
            ANALYST,
        ),
        201,
    )
    assert_status(out_of_term, STATEMENT_STATUS_DRAFT)
    validate_error(
        api.prepare_statement(out_of_term["id"], ANALYST), ERR_PERIOD_OUTSIDE_TERM, 422
    )
    assert_status(read_statement(api, out_of_term["id"]), STATEMENT_STATUS_DRAFT)

    provisional = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-04-01",
        period_end="2026-06-30",
        basis_variant=BASIS_VARIANT_PROVISIONAL,
    )
    prepared = do_prepare_statement(api, provisional["id"])
    assert_field(prepared, "basis_variant", BASIS_VARIANT_PROVISIONAL)
    assert_status(prepared, STATEMENT_STATUS_PREPARED)

    validate_error(
        api.issue_statement(provisional["id"], BIZ_AFFAIRS),
        ERR_PROVISIONAL_NOT_ISSUABLE,
        422,
    )
    still_prepared = read_statement(api, provisional["id"])
    assert_status(still_prepared, STATEMENT_STATUS_PREPARED)
    assert_version_is(
        still_prepared, prepared["version"], entity="statement"
    )
    assert_null(
        still_prepared, "issued_at", "issued_by_user_id", "objection_deadline"
    )


def test_the_inventory_floor_and_the_returns_ceiling_are_each_refused_then_satisfied(api):
    """Two of the three fiscal breaches on the physical axis, each followed by the
    legal version of the same call: "A breach is refused with
    `ERR_INVENTORY_OBLIGATION_BREACH` (422)" for 20 units retained against a
    ceil(900 x 0.0500) floor of 45 - shipping 900 of 1020 clears it - and "the
    cumulative total may never exceed `units_shipped`" for 901 returns against
    900 shipped, while 90 returns land exactly on the 0.1000 tier and re-size the
    reserve from 162000 to 202500.

    Design: Corner/errors/physical_run_fiscal_breaches_are_each_triggerable
    """
    ctx = given_released_catalog(
        api,
        distributor_kw=dict(PHYSICAL_PARTNER, default_returns_reserve_pct=f.pct4("0.2000")),
        deal_kw={"post_term_collection_days": 90},
        releases=[{"title": "Warehouse", "formats": (FORMAT_VINYL,)}],
    )
    run = mk_run(
        api,
        ctx["release_id"],
        ctx["dist_id"],
        units_planned=1020,
        unit_manufacturing_cost_cents=250,
        window_start="2026-04-01",
        window_end="2026-06-30",
    )
    manufactured = do_manufacture(api, run["id"], 1020)
    assert_field_money(manufactured, "manufacturing_cost_cents", 255000)

    validate_error(
        api.ship_run(run["id"], f.ship_payload(1000, 900), ctx["partner_headers"]),
        ERR_INVENTORY_OBLIGATION_BREACH,
        422,
    )
    after_breach = read_run(api, run["id"])
    assert_status(after_breach, RUN_STATUS_MANUFACTURED)
    assert_version_is(
        after_breach, manufactured["version"], entity="physical run"
    )

    shipped = validate_success(
        api.ship_run(run["id"], f.ship_payload(900, 900), ctx["partner_headers"]), 200
    )
    assert_pct_equals(shipped["effective_reserve_pct"], "0.2000", "effective_reserve_pct")
    assert_fields_money(
        shipped,
        reserve_initial_cents=162000,
        reserve_held_cents=162000,
        physical_net_receipts_cents=555000,
    )

    validate_error(
        api.record_returns(
            run["id"], f.record_returns_payload(901), ctx["partner_headers"]
        ),
        ERR_RETURNS_EXCEED_SHIPPED,
        422,
    )
    assert_field(read_run(api, run["id"]), "units_returned", 0)

    returned = validate_success(
        api.record_returns(
            run["id"], f.record_returns_payload(90), ctx["partner_headers"]
        ),
        200,
    )
    assert_pct_equals(
        returned["effective_reserve_pct"], "0.2500", "effective_reserve_pct"
    )
    assert_fields_money(
        returned,
        reserve_initial_cents=202500,
        reserve_held_cents=202500,
        physical_net_receipts_cents=474000,
    )


def test_two_liquidations_at_sixty_percent_over_draw_the_reserve(api):
    """The third fiscal breach and the one coupling between the run's two axes:
    "the percentage always applies to `reserve_initial_cents`, never to the
    diminishing held balance, so two successive liquidations at 0.6000 over-draw
    and the second is refused", while 0.4000 lands exactly on the remaining 81000
    and closes the run, because "whenever the reserve axis reaches `LIQUIDATED`
    in a request" the fulfilment axis is carried to RECONCILED with it.

    Design: Corner/errors/physical_run_fiscal_breaches_are_each_triggerable
    """
    ctx = given_released_catalog(
        api,
        distributor_kw=dict(PHYSICAL_PARTNER, default_returns_reserve_pct=f.pct4("0.2000")),
        deal_kw={"post_term_collection_days": 90},
        releases=[{"title": "Warehouse", "formats": (FORMAT_VINYL,)}],
    )
    ctx = given_shipped_run(
        api,
        ctx,
        run_kw={
            "units_planned": 1020,
            "unit_manufacturing_cost_cents": 250,
            "window_start": "2026-04-01",
            "window_end": "2026-06-30",
        },
        units_manufactured=1020,
        units_shipped=900,
        wholesale_unit_price_cents=900,
        returned_units=90,
    )
    assert_field_money(ctx["run"], "reserve_initial_cents", 202500)

    first = validate_success(
        api.liquidate_reserve(
            ctx["run_id"],
            f.liquidate_payload(run_version(api, ctx["run_id"]), f.pct4("0.6000")),
            ANALYST,
        ),
        200,
    )
    assert_fields_money(
        first, reserve_held_cents=81000, reserve_liquidated_cents=121500
    )
    assert_status(first, RESERVE_STATUS_PARTIALLY_LIQUIDATED, field="reserve_status")

    current_version = run_version(api, ctx["run_id"])
    validate_error(
        api.liquidate_reserve(
            ctx["run_id"], f.liquidate_payload(current_version, f.pct4("0.6000")), ANALYST
        ),
        ERR_LIQUIDATION_EXCEEDS_RESERVE,
        422,
    )

    final = validate_success(
        api.liquidate_reserve(
            ctx["run_id"], f.liquidate_payload(current_version, f.pct4("0.4000")), ANALYST
        ),
        200,
    )
    assert_fields_money(
        final, reserve_held_cents=0, reserve_liquidated_cents=202500
    )
    assert_status(final, RESERVE_STATUS_LIQUIDATED, field="reserve_status")
    assert_status(final, RUN_STATUS_RECONCILED)


def test_the_audit_right_runs_out_three_hundred_and_sixty_five_days_after_finalization(api):
    """The audit window is anchored on finalized_at, a month later than issued_at
    here, and its edge is inclusive: "The request must arrive no later than 365
    days after `finalized_at`; the window is inclusive of that instant, and a
    request beyond it is refused with `ERR_AUDIT_WINDOW_EXPIRED` (422)". So
    2027-09-02 is refused and 2027-09-01 is accepted on the same statement.

    Design: Corner/errors/audit_window_expires_365_days_after_finalization
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"objection_window_days": 30, "post_term_collection_days": 90},
        releases=[{"title": "Books Open"}],
    )
    ctx = given_active_agreement(api, ctx)
    ctx = given_finalized_statement(
        api, ctx, finalize_clock="2026-09-01T00:00:00.000Z"
    )
    finalized = ctx["statement"]
    assert_instant_equals(finalized["issued_at"], DEFAULT_CLOCK_INSTANT, "issued_at")
    assert_instant_equals(
        finalized["finalized_at"], "2026-09-01T00:00:00.000Z", "finalized_at"
    )
    assert_status(finalized, AUDIT_STATUS_NONE, field="audit_status")

    scope = f.request_audit_payload(
        "2026-04-01", "2026-06-30", auditor_name="Kessler & Ruiz LLP"
    )
    do_set_clock(api, "2027-09-02T00:00:00.000Z")
    validate_error(
        api.request_audit(ctx["statement_id"], scope, ctx["artist_headers"]),
        ERR_AUDIT_WINDOW_EXPIRED,
        422,
    )
    refused = read_statement(api, ctx["statement_id"])
    assert_status(refused, AUDIT_STATUS_NONE, field="audit_status")
    assert_null(
        refused, "audit_scope_period_start", "audit_scope_period_end", "auditor_name"
    )

    do_set_clock(api, "2027-09-01T00:00:00.000Z")
    requested = validate_success(
        api.request_audit(ctx["statement_id"], scope, ctx["artist_headers"]), 200
    )
    assert_status(requested, AUDIT_STATUS_REQUESTED, field="audit_status")
    assert_status(requested, STATEMENT_STATUS_FINALIZED)
    assert_field(requested, "auditor_name", "Kessler & Ruiz LLP")
    assert_date(
        requested["audit_scope_period_start"], "2026-04-01", "audit_scope_period_start"
    )
    assert_version_bumped(finalized, requested, entity="statement")
