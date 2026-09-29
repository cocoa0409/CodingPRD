"""Two window rules with deliberately different interval semantics.

PRD s3.8 treats an exclusivity window as half-open, so touching windows are fine, and
treats a roster batch window as closed, so touching windows already collide.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_BATCH_OVERLAP_CAPACITY_EXCEEDED,
    ERR_EXCLUSIVITY_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_athlete_tax_ledger,
    assert_collective_ledger,
    assert_contract_dimensions,
    assert_contribution_money,
    assert_error_envelope_shape,
    assert_timestamp_equals,
    read_data,
    rows_of,
)
from test_helpers.factories import (
    contribution_payload,
    deal_contract_payload,
    roster_allocation_payload,
)
from test_helpers.fixtures import (
    build_athlete,
    build_collective,
    build_donor,
    build_funded_collective,
    build_open_tier,
    read_athlete,
    read_collective,
)
from test_helpers.test_users import make_director_headers


def _athlete_with_one_apparel_deal(api):
    """One APPAREL contract covering 2026-08-01 up to 2026-09-01."""
    collective = build_collective(
        api,
        "015100",
        name="Exclusivity Collective",
        institution_name="California Institution D",
        home_state_code="CA",
        association_ruleset="NCAA_2024",
    )
    tier = build_open_tier(api, collective["id"], "T2", 40000, 2)
    donor = build_donor(
        api,
        collective["id"],
        tier["id"],
        display_name="Wes Whiskey",
        email="wes@example.com",
    )
    contribution = validate_success(
        api.create_contribution(
            contribution_payload(
                donor["id"],
                307723,
                designation="UNRESTRICTED",
                processor_outcome="APPROVE",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert_contribution_money(contribution, net_amount_cents=300000)
    athlete = build_athlete(
        api,
        collective["id"],
        "ath-xan",
        full_name="Xan Xray",
        sport="FOOTBALL",
        class_year=2028,
    )
    first = read_data(
        api.create_deal_contract(
            deal_contract_payload(
                collective["id"],
                athlete["id"],
                100000,
                effective_start_at="2026-08-01T00:00:00Z",
                effective_end_at="2026-09-01T00:00:00Z",
                funding_designation="UNRESTRICTED",
                exclusivity_category="APPAREL",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert first["exclusivity_category"] == "APPAREL"
    return {
        "collective_id": collective["id"],
        "athlete_id": athlete["id"],
        "first_id": first["id"],
    }


def _apparel_deal(collective_id, athlete_id, start, end):
    return deal_contract_payload(
        collective_id,
        athlete_id,
        100000,
        effective_start_at=start,
        effective_end_at=end,
        funding_designation="UNRESTRICTED",
        exclusivity_category="APPAREL",
    )


def test_an_apparel_window_that_only_touches_the_first_is_permitted(api):
    """A second APPAREL deal starting exactly when the first ends is accepted.

    PRD s3.8: "two contracts for the same athlete carrying the same non-`NONE`
    `exclusivity_category` may not have overlapping effective windows, where each window
    is the half-open interval running from `effective_start_at` up to but not including
    `effective_end_at` ... Adjacency is explicitly permitted — one window's
    `effective_end_at` exactly equal to the other's `effective_start_at` is not an
    overlap".

    Design: Difficulty/resource_temporal_overlap/exclusivity_window_half_open_adjacency_permitted_overlap_rejected
    """
    ctx = _athlete_with_one_apparel_deal(api)

    adjacent = read_data(
        api.create_deal_contract(
            _apparel_deal(
                ctx["collective_id"],
                ctx["athlete_id"],
                "2026-09-01T00:00:00Z",
                "2026-10-01T00:00:00Z",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )
    assert adjacent["exclusivity_category"] == "APPAREL"
    assert_timestamp_equals(adjacent["effective_start_at"], "2026-09-01T00:00:00Z")
    assert_contract_dimensions(adjacent, lifecycle_status="DRAFT")

    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]), annual_committed_value_cents=200000
    )
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]), committed_unreleased_cents=200000
    )


def test_an_apparel_window_that_truly_intersects_is_refused(api):
    """A window starting one day before the first ends intersects it and is refused.

    PRD s3.8: "any true overlap is refused with `ERR_EXCLUSIVITY_WINDOW_CONFLICT`", and
    "only contracts whose `lifecycle_status` is `DRAFT` or `ACTIVE` are considered", which
    both existing DRAFT deals are. The refused window shares 2026-08-31 to 2026-09-01 with
    the first deal.

    Design: Difficulty/resource_temporal_overlap/exclusivity_window_half_open_adjacency_permitted_overlap_rejected
    """
    ctx = _athlete_with_one_apparel_deal(api)
    validate_success(
        api.create_deal_contract(
            _apparel_deal(
                ctx["collective_id"],
                ctx["athlete_id"],
                "2026-09-01T00:00:00Z",
                "2026-10-01T00:00:00Z",
            ),
            make_director_headers(),
        ),
        expected_status=201,
    )

    response = api.create_deal_contract(
        _apparel_deal(
            ctx["collective_id"],
            ctx["athlete_id"],
            "2026-08-31T00:00:00Z",
            "2026-09-15T00:00:00Z",
        ),
        make_director_headers(),
    )
    validate_error(response, ERR_EXCLUSIVITY_WINDOW_CONFLICT, expected_status=409)
    assert_error_envelope_shape(response)

    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]), annual_committed_value_cents=200000
    )
    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]), committed_unreleased_cents=200000
    )


def _roster_pool_with_one_footballer(api):
    """A pool large enough that only the window rule can refuse a batch."""
    funded = build_funded_collective(
        api,
        "016100",
        5000000,
        home_state_code="TX",
        association_ruleset="NCAA_2024",
        designation="ROSTER_POOL",
        tier_code="T4",
        annual_dues_cents=300000,
        benefit_rank=4,
        email="yara@example.com",
        name="Batch Capacity Collective",
        institution_name="Texas Institution D",
    )
    assert_contribution_money(
        funded["contribution"], processing_fee_cents=105000, net_amount_cents=4895000
    )
    athlete = build_athlete(
        api,
        funded["collective_id"],
        "ath-zed",
        full_name="Zed Zulu",
        sport="FOOTBALL",
        class_year=2028,
    )
    return {"collective_id": funded["collective_id"], "athlete_id": athlete["id"]}


def _football_batch(api, collective_id, batch_code, start, end):
    """Post a 300000-cent FOOTBALL batch, quoting the collective's current version."""
    collective = read_collective(api, collective_id)
    response = api.create_roster_allocation(
        roster_allocation_payload(
            collective_id,
            batch_code,
            "FOOTBALL",
            300000,
            "EQUAL_SHARE",
            start,
            end,
            expected_collective_version=collective["version"],
            funding_designation="ROSTER_POOL",
            exclusivity_category="NONE",
        ),
        make_director_headers(),
    )
    return collective["version"], response


def test_two_batch_windows_that_merely_touch_are_both_admitted(api):
    """Touching batch windows collide, but one prior collision is still under capacity.

    PRD s3.8: "A new batch is refused with `ERR_BATCH_OVERLAP_CAPACITY_EXCEEDED` when the
    number of **distinct** existing `allocation_batch_code` values on the same collective
    and the same sport whose windows collide with the new batch's window already stands at
    two or more, counting only contracts whose `lifecycle_status` is `DRAFT` or `ACTIVE`."
    B2 starts exactly where B1 ends, so it collides with exactly one existing batch code
    and is admitted.

    Design: Difficulty/resource_temporal_overlap/roster_batch_closed_interval_aggregate_capacity_saturation
    """
    ctx = _roster_pool_with_one_footballer(api)

    _, first = _football_batch(
        api,
        ctx["collective_id"],
        "B1",
        "2026-08-01T00:00:00Z",
        "2026-09-01T00:00:00Z",
    )
    first_batch = read_data(first, expected_status=201)
    assert first_batch["created_contract_count"] == 1
    assert first_batch["allocated_total_cents"] == 300000

    _, second = _football_batch(
        api,
        ctx["collective_id"],
        "B2",
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    second_batch = read_data(second, expected_status=201)
    assert second_batch["created_contract_count"] == 1
    assert second_batch["allocated_total_cents"] == 300000

    assert_collective_ledger(
        read_collective(api, ctx["collective_id"]),
        settled_net_funds_cents=4895000,
        committed_unreleased_cents=600000,
        funding_posture="OPEN",
    )
    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]), annual_committed_value_cents=600000
    )


def test_a_third_batch_colliding_with_both_predecessors_is_refused(api):
    """A window straddling both existing batches meets two collisions and is refused whole.

    PRD s3.8: "here the windows are treated as **closed** intervals, so two windows collide
    when the first's start is at or before the second's end **and** the second's start is at
    or before the first's end", so 2026-08-15 to 2026-09-15 collides with both B1 and B2.
    PRD s3.8 also states that a refused batch "creates nothing at all — the batch is
    all-or-nothing".

    Design: Difficulty/resource_temporal_overlap/roster_batch_closed_interval_aggregate_capacity_saturation
    """
    ctx = _roster_pool_with_one_footballer(api)
    _football_batch(
        api, ctx["collective_id"], "B1", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    _football_batch(
        api, ctx["collective_id"], "B2", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
    )

    version_before, response = _football_batch(
        api, ctx["collective_id"], "B3", "2026-08-15T00:00:00Z", "2026-09-15T00:00:00Z"
    )
    validate_error(response, ERR_BATCH_OVERLAP_CAPACITY_EXCEEDED, expected_status=409)
    assert_error_envelope_shape(response)

    collective = read_collective(api, ctx["collective_id"])
    assert collective["version"] == version_before
    assert_collective_ledger(
        collective,
        settled_net_funds_cents=4895000,
        committed_unreleased_cents=600000,
        funding_posture="OPEN",
    )
    assert_athlete_tax_ledger(
        read_athlete(api, ctx["athlete_id"]), annual_committed_value_cents=600000
    )
    assert (
        rows_of(
            api.list_deal_contracts(
                {"allocation_batch_code": "B3"}, make_director_headers()
            )
        )
        == []
    )
