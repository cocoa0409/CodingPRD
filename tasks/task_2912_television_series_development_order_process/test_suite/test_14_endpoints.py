"""Endpoint surfaces: computed reads, clock-derived reads, filtered listings and links.

The reads here are grouped by what they prove about the surface rather than by
resource: that a projection applies its declared defaults, that a clock move alone
re-derives a read, that a filter narrows the count as well as the rows, and that
each parent-scoped child collection is navigable by the role that needs it.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    DEV_PILOT_DELIVERED,
    EXCLUSIVITY_FREE,
    EXCLUSIVITY_HOLDING_DEAL,
    FEASIBILITY_BASIS_PATTERN,
    GL_OPEN,
    GUILD_TIER_HIGH,
    HOLDING_ACTIVE,
    NEG_AGREED,
    NEG_NETWORK_OFFER,
    OFFER_SIDE_NETWORK,
    PITCH_SUBMITTED,
    PRODUCTION_WRAPPED,
    SCREENING_CERTIFIED,
    SCREENING_INVALIDATED,
    TERM_IN_TERM,
    TERM_PENDING_START,
    VERDICT_FEASIBLE,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    agency_rep_headers,
    business_affairs_headers,
    development_exec_headers,
    finance_controller_headers,
    platform_admin_headers,
    research_analyst_headers,
    studio_partner_headers,
)

FUTURE_TERM = {"start_date": "2026-10-01", "end_date": "2027-10-01"}
SECOND_WRITERS = (
    {"full_name": "Bo Nakamura"},
    {"full_name": "Cyd Okonkwo"},
    {"full_name": "Dara Vance"},
)


def test_the_feasibility_read_applies_the_pattern_basis_and_the_default_episode_count(api):
    """With no query parameters the projection uses PATTERN and the slate's default of 10.

    PRD 3.8: "`basis`, which selects the variant and defaults to `PATTERN`, and
    `episode_count`, which defaults to the slate's `default_episode_count` when the
    caller omits it."

    Design: Corner/endpoints/feasibility_read_defaults_to_the_pattern_basis_and_the_slates_default_episode_count
    """
    ctx = build_scenario(api, "script_complete")

    response = api.get_feasibility(ctx.project_id, finance_controller_headers())
    projection = validate_success(response)
    a.assert_response_type(response, "object")
    meta = response.json()["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
    assert isinstance(meta["api_request_timestamp"], str) and meta["api_request_timestamp"]

    # The pattern budget of 32000000 plus 4375000 of development amortised over 10
    # episodes is 32437500; the provisional deficit of 2437500 is above the 1500000
    # breakpoint, so the tier is 9000 and the fee is 29193750.
    a.assert_feasibility(
        projection,
        basis=FEASIBILITY_BASIS_PATTERN,
        episode_count=10,
        per_episode_cost_cents=32437500,
        tier_factor_bps=9000,
        license_fee_final_cents=29193750,
        deficit_per_episode_cents=3243750,
        total_deficit_cents=32437500,
        verdict=VERDICT_FEASIBLE,
    )


def test_moving_the_clock_alone_flips_the_term_state_and_the_exclusivity(api):
    """Nothing is written to the deal, yet both derived reads change with the clock.

    PRD 2.4: "Moving the clock transitions nothing by itself - no entity changes
    state because time passed. What it changes is the answer that every
    clock-derived read gives from that point onward: a holding deal's `term_state`,
    a writer's `exclusivity_status`".

    Design: Corner/endpoints/advancing_the_clock_into_a_holding_deal_term_flips_term_state_and_exclusivity
    """
    ctx = build_scenario(api, "writer")
    deal = validate_success(
        api.create_holding_deal(
            f.holding_deal_payload(
                ctx.writer_id, ctx.slate_id, annual_cost_cents=6000000, **FUTURE_TERM
            ),
            business_affairs_headers(),
        ),
        201,
    )

    before = validate_success(api.get_holding_deal(deal["id"], business_affairs_headers()))
    assert before["term_state"] == TERM_PENDING_START, "the clock reads 2026-08-01"
    assert (
        validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))[
            "exclusivity_status"
        ]
        == EXCLUSIVITY_FREE
    )
    slate_before = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate_before, reserved=6000000, available=394000000)

    moved = validate_success(
        api.set_clock("2026-10-01T00:00:00Z", platform_admin_headers())
    )
    assert moved["current_utc"] is not None

    after = validate_success(api.get_holding_deal(deal["id"], business_affairs_headers()))
    assert after["term_state"] == TERM_IN_TERM
    assert after["status"] == HOLDING_ACTIVE
    assert after["termination_reason"] is None

    writer = validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))
    assert writer["exclusivity_status"] == EXCLUSIVITY_HOLDING_DEAL

    slate_after = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate_after, reserved=6000000, available=394000000)


def test_the_holding_deal_listing_counts_the_filtered_set_and_not_the_table(api):
    """Three deals on the queried slate and one on another: limit 2 offset 1 reports three.

    PRD 2.3: "`total_count` reports how many rows matched the request's filters (not
    how many rows exist in the collection as a whole)".

    Design: Corner/endpoints/holding_deal_listing_filters_by_slate_and_pages_with_limit_and_offset
    """
    ctx = fx.bootstrap(api)
    slate_2028 = validate_success(
        api.create_slate(f.cable_slate_payload(), platform_admin_headers()), 201
    )["id"]

    on_slate_27 = []
    for day, overrides in enumerate(SECOND_WRITERS, start=2):
        # Each deal is filed on its own day so the created_at ordering is total.
        fx.set_clock(api, f"2026-08-0{day}T00:00:00Z")
        writer = fx.create_writer(api, ctx.agency_id, dict(overrides))["id"]
        on_slate_27.append(
            validate_success(
                api.create_holding_deal(
                    f.holding_deal_payload(
                        writer, ctx.slate_id, annual_cost_cents=5000000
                    ),
                    business_affairs_headers(),
                ),
                201,
            )["id"]
        )

    fx.set_clock(api, "2026-08-05T00:00:00Z")
    other_writer = fx.create_writer(api, ctx.agency_id, {"full_name": "Eli Marsh"})["id"]
    validate_success(
        api.create_holding_deal(
            f.holding_deal_payload(other_writer, slate_2028, annual_cost_cents=3000000),
            business_affairs_headers(),
        ),
        201,
    )

    response = api.list_holding_deals(
        business_affairs_headers(), {"slate_id": ctx.slate_id, "limit": 2, "offset": 1}
    )
    rows, meta = validate_paginated(response)
    a.assert_response_type(response, "array")
    assert len(rows) == 2
    assert all(row["slate_id"] == ctx.slate_id for row in rows)
    a.assert_ids(rows, on_slate_27[1:])
    a.assert_created_at_ascending(rows)
    a.assert_pagination_meta(meta, limit=2, offset=1, total_count=3, has_more=False)

    queried = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(queried, reserved=15000000)
    other = validate_success(api.get_slate(slate_2028, business_affairs_headers()))
    a.assert_slate_dollar_ledger(other, reserved=3000000)


def test_the_side_holding_the_standing_offer_may_not_accept_its_own_sheet(api):
    """BusinessAffairs opened the offer, so BusinessAffairs cannot close it.

    PRD 3.7: "A `StudioPartner` may accept only while `last_offer_side` is
    `NETWORK`, moving the negotiation `NETWORK_OFFER -> AGREED`; `BusinessAffairs`
    may accept only while `last_offer_side` is `STUDIO`, moving it `STUDIO_COUNTER
    -> AGREED`. The wrong side accepting its own offer is refused with
    `ERR_ACCEPT_BY_OFFERING_SIDE`."

    Design: Corner/endpoints/the_side_that_tabled_the_standing_offer_cannot_accept_it
    """
    ctx = build_scenario(api, "negotiation")

    refused = api.accept_negotiation(ctx.negotiation_id, business_affairs_headers())
    validate_error(refused, e.ERR_ACCEPT_BY_OFFERING_SIDE, 409)

    standing = validate_success(
        api.list_project_negotiations(ctx.project_id, business_affairs_headers())
    )
    offer = next(row for row in standing if row["id"] == ctx.negotiation_id)
    assert offer["status"] == NEG_NETWORK_OFFER
    assert offer["round_number"] == 1
    assert offer["last_offer_side"] == OFFER_SIDE_NETWORK
    assert offer["agreed_at"] is None

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_episode_ledger(slate, committed=0, reserved=10, available=10)

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_PILOT_DELIVERED


def test_one_holding_deal_create_resolves_both_keys_and_moves_both_derived_reads(api):
    """The slate's reservation and the writer's exclusivity both change in the same cycle.

    PRD 3.3: "the slate's `reserved_holding_cents` rises by `annual_cost_cents`,
    which lowers `available_dev_cents` by exactly the same amount, the writer's
    `exclusivity_status` is recomputed - it becomes `HOLDING_DEAL` as soon as the
    term contains the clock date".

    Design: Corner/endpoints/creating_a_holding_deal_links_writer_and_slate_and_moves_both_derived_reads
    """
    ctx = build_scenario(api, "writer")

    created = validate_success(
        api.create_holding_deal(
            f.holding_deal_payload(
                ctx.writer_id,
                ctx.slate_id,
                annual_cost_cents=6000000,
                start_date="2026-08-01",
                end_date="2027-08-01",
            ),
            business_affairs_headers(),
        ),
        201,
    )
    assert created["writer_id"] == ctx.writer_id
    assert created["slate_id"] == ctx.slate_id
    assert created["status"] == HOLDING_ACTIVE
    assert created["term_state"] == TERM_IN_TERM
    assert created["termination_reason"] is None
    a.assert_created_version_one(created)

    writer = validate_success(api.get_writer(ctx.writer_id, business_affairs_headers()))
    assert writer["exclusivity_status"] == EXCLUSIVITY_HOLDING_DEAL
    assert writer["open_step_count"] == 0

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(
        slate, committed=0, reserved=6000000, available=394000000
    )

    rows, meta = validate_paginated(
        api.list_holding_deals(
            business_affairs_headers(),
            {"writer_id": ctx.writer_id, "limit": 10, "offset": 0},
        )
    )
    a.assert_ids(rows, [created["id"]])
    a.assert_pagination_meta(meta, total_count=1)


def test_every_child_collection_is_navigable_by_the_role_that_needs_it(api):
    """One greenlit walk exposes the pilot, the screening, the negotiation, the deal and the queue.

    PRD 3.7: "A project's negotiations may be listed, which is the one read surface
    a `StudioPartner` is given on the development side."

    Design: Corner/endpoints/every_child_collection_read_finds_the_rows_its_parent_write_created
    """
    ctx = build_scenario(api, "greenlight")

    pilots, pilot_meta = validate_paginated(
        api.list_project_pilot_orders(ctx.project_id, research_analyst_headers())
    )
    a.assert_ids(pilots, [ctx.pilot_order_id])
    assert pilots[0]["production_status"] == PRODUCTION_WRAPPED
    a.assert_pagination_meta(pilot_meta, total_count=1)

    screenings, screening_meta = validate_paginated(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    a.assert_ids(screenings, [ctx.screening_id])
    assert screenings[0]["status"] == SCREENING_CERTIFIED
    # 32.31 + 19.04 + 14.36 is 65.71, and 65.71 * 100 / 103.0 rounds to 63.8.
    a.assert_score(screenings[0]["norm_adjusted_score"], 63.8, "norm_adjusted_score")
    a.assert_pagination_meta(screening_meta, total_count=1)

    negotiations = validate_success(
        api.list_project_negotiations(ctx.project_id, studio_partner_headers())
    )
    assert [row["id"] for row in negotiations] == [ctx.negotiation_id]
    assert negotiations[0]["status"] == NEG_AGREED
    assert negotiations[0]["episode_count"] == 10
    a.assert_cents(
        negotiations[0]["total_license_commitment_cents"],
        300000000,
        "total_license_commitment_cents",
    )

    deals, deal_meta = validate_paginated(
        api.list_script_deals(
            finance_controller_headers(),
            {
                "project_id": ctx.project_id,
                "writer_id": ctx.writer_id,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    a.assert_ids(deals, [ctx.deal_id])
    a.assert_cents(
        deals[0]["guaranteed_commitment_cents"], 4375000, "guaranteed_commitment_cents"
    )
    a.assert_pagination_meta(deal_meta, total_count=1)

    queue, queue_meta = validate_paginated(
        api.list_greenlight_requests(
            finance_controller_headers(),
            {"project_id": ctx.project_id, "status": GL_OPEN, "limit": 10, "offset": 0},
        )
    )
    a.assert_ids(queue, [ctx.greenlight_id])
    assert queue[0]["negotiation_id"] == ctx.negotiation_id
    a.assert_pagination_meta(queue_meta, total_count=1)

    invalidated, invalidated_meta = validate_paginated(
        api.list_screenings(
            ctx.pilot_order_id,
            research_analyst_headers(),
            {"status": SCREENING_INVALIDATED, "limit": 10, "offset": 0},
        )
    )
    assert invalidated == [], "the status filter narrows rather than being ignored"
    a.assert_pagination_meta(invalidated_meta, total_count=0)


def test_the_agency_scoped_reads_return_the_reps_own_writer_and_pitch(api):
    """The rep reads its own writer and pitch, and a rival's empty listing is a 200.

    PRD 2.1: "ownership checks compare the `agency_id` on the resource being touched
    to `X-User-ID`: the `agency_id` in a pitch submission payload, or the
    `agency_id` of the writer or pitch named in the path."

    Design: Corner/endpoints/the_agency_scoped_reads_return_the_writer_and_pitch_by_id_and_in_the_listing
    """
    ctx = build_scenario(api, "pitch")
    rival = validate_success(
        api.create_agency(f.rival_agency_payload(), platform_admin_headers()), 201
    )["id"]

    writer = validate_success(
        api.get_writer(ctx.writer_id, agency_rep_headers(ctx.agency_id))
    )
    assert writer["full_name"] == "Ada Reyes"
    assert writer["agency_id"] == ctx.agency_id
    assert writer["guild_minimum_tier"] == GUILD_TIER_HIGH
    assert writer["exclusivity_status"] == EXCLUSIVITY_FREE
    assert writer["open_step_count"] == 0
    a.assert_created_version_one(writer)

    pitch = validate_success(
        api.get_pitch(ctx.pitch_id, agency_rep_headers(ctx.agency_id))
    )
    assert pitch["status"] == PITCH_SUBMITTED
    assert pitch["agency_id"] == ctx.agency_id
    assert pitch["slate_id"] == ctx.slate_id
    assert pitch["underlying_ip_key"] == "IP-FAULT-LINES"
    assert pitch["packaging_elements"] == []

    response = api.list_pitches(
        development_exec_headers(),
        {
            "agency_id": ctx.agency_id,
            "status": PITCH_SUBMITTED,
            "limit": 10,
            "offset": 0,
        },
    )
    rows, meta = validate_paginated(response)
    a.assert_response_type(response, "array")
    a.assert_ids(rows, [ctx.pitch_id])
    a.assert_pagination_meta(meta, limit=10, offset=0, total_count=1, has_more=False)

    empty, empty_meta = validate_paginated(
        api.list_pitches(
            agency_rep_headers(rival), {"agency_id": rival, "limit": 10, "offset": 0}
        )
    )
    assert empty == [], "the rival agency has filed nothing, which is a 200 and not a 403"
    a.assert_pagination_meta(empty_meta, total_count=0)
