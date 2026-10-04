"""Quote binding: the exposure ledger invariant, overlap geometry, OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_bound_exposure_invariant,
    bind_quote,
    community_version,
    create_property,
    create_quote,
    get_community,
    get_quote,
    list_quotes,
    setup_classified_community,
    validate_error,
    void_quote,
)

INSURER = TEST_USERS["insurer_headers"]


def _ledger_falls(api):
    ctx = setup_classified_community(api, name="Ledger Falls")
    community_id = ctx["community"]["id"]
    prop = create_property(
        api, community_id, address="4 Maple Ave", distance_to_nearest_hydrant_ft=300,
        distance_to_nearest_station_road_miles=1.0, construction_type="FRAME",
        insured_value_cents=200000000,
    )
    q1 = create_quote(api, prop["id"], coverage_amount_cents=25000000, term_months=6)
    q2 = create_quote(
        api, prop["id"], coverage_amount_cents=10000000, term_months=6,
        coverage_start_date="2028-01-01", coverage_end_date="2028-06-30",
    )
    return ctx, prop, q1, q2


def test_bind_accumulates_exposure_ledger(api):
    """PRD §3.8: "Binding also records `bound_by` and `bound_at`, adds
    `coverage_amount_cents` to the community's `bound_exposure_cents`" and
    "a community's `bound_exposure_cents` always equals the sum of
    `coverage_amount_cents` over the `BOUND` quotes of properties belonging
    to that community."

    Design: Difficulty/compensating_invariant/bind_void_exposure_ledger_conservation
    """
    ctx, prop, q1, q2 = _ledger_falls(api)
    community_id = ctx["community"]["id"]
    bind_quote(api, community_id, q1["id"])
    assert get_community(api, community_id)["bound_exposure_cents"] == 25000000
    bind_quote(api, community_id, q2["id"])
    community = get_community(api, community_id)
    assert community["bound_exposure_cents"] == 35000000
    assert_bound_exposure_invariant(community, list_quotes(api, property_id=prop["id"]))


def test_void_compensates_exposure_ledger(api):
    """PRD §3.8: "a quote in `BOUND` (any other status is
    `ERR_QUOTE_INVALID_STATE`) moves to `VOIDED`, its `coverage_amount_cents`
    is subtracted back out of `bound_exposure_cents`" — after the forward
    and compensating pair the ledger reads exactly the remaining 10,000,000.

    Design: Difficulty/compensating_invariant/bind_void_exposure_ledger_conservation
    """
    ctx, prop, q1, q2 = _ledger_falls(api)
    community_id = ctx["community"]["id"]
    bind_quote(api, community_id, q1["id"])
    bind_quote(api, community_id, q2["id"])
    void_quote(api, q1["id"])
    community = get_community(api, community_id)
    assert community["bound_exposure_cents"] == 10000000
    assert get_quote(api, q1["id"])["status"] == "VOIDED"
    assert get_quote(api, q2["id"])["status"] == "BOUND"
    assert_bound_exposure_invariant(community, list_quotes(api, property_id=prop["id"]))


def _overlapton(api):
    ctx = setup_classified_community(api, name="Overlapton")
    community_id = ctx["community"]["id"]
    prop = create_property(
        api, community_id, address="9 Elm St", distance_to_nearest_hydrant_ft=300,
        distance_to_nearest_station_road_miles=1.0, construction_type="FRAME",
        insured_value_cents=200000000,
    )
    q1 = create_quote(
        api, prop["id"], coverage_amount_cents=10000000, term_months=12,
        coverage_start_date="2027-01-01", coverage_end_date="2027-12-31",
    )
    bind_quote(api, community_id, q1["id"])
    q2 = create_quote(
        api, prop["id"], coverage_amount_cents=5000000, term_months=6,
        coverage_start_date="2027-12-31", coverage_end_date="2028-06-30",
    )
    q3 = create_quote(
        api, prop["id"], coverage_amount_cents=5000000, term_months=12,
        coverage_start_date="2028-01-01", coverage_end_date="2028-12-31",
    )
    return ctx, prop, q2, q3


def test_bound_intervals_sharing_one_day_collide(api):
    """PRD §3.8: "the new closed interval must not touch any other `BOUND`
    quote's interval on the same property — two intervals collide whenever
    each starts on or before the other's end, so even sharing a single
    calendar day is rejected with `ERR_QUOTE_COVERAGE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/bound_quote_coverage_closed_interval_overlap
    """
    ctx, prop, q2, _ = _overlapton(api)
    resp = api.bind_premium_quote(
        q2["id"], {"expected_community_version": community_version(api, ctx["community"]["id"])},
        INSURER,
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_COVERAGE_OVERLAP)
    assert get_quote(api, q2["id"])["status"] == "QUOTED"


def test_bound_intervals_strictly_disjoint_bind_freely(api):
    """PRD §3.8: "two intervals collide whenever each starts on or before the
    other's end" — a window opening 2028-01-01 starts strictly after the
    BOUND 2027-12-31 end, so the bind succeeds.

    Design: Difficulty/resource_temporal_overlap/bound_quote_coverage_closed_interval_overlap
    """
    ctx, prop, _, q3 = _overlapton(api)
    bound = bind_quote(api, ctx["community"]["id"], q3["id"])
    assert bound["status"] == "BOUND"


def test_exposure_cap_exceeded_returns_error(api):
    """PRD §3.8: "the bind must not push the community's
    `bound_exposure_cents` over its cap of five million dollars (500000000
    cents), else `ERR_EXPOSURE_CAP_EXCEEDED` (HTTP 422)." 300,000,000 bound
    plus 250,000,000 more exceeds the cap only in aggregate.

    Design: Corner/validations/exposure_cap_exceeded_returns_error
    """
    ctx = setup_classified_community(api, name="Exposure City")
    community_id = ctx["community"]["id"]
    prop = create_property(
        api, community_id, address="8 Pine St", distance_to_nearest_hydrant_ft=300,
        distance_to_nearest_station_road_miles=1.0, construction_type="FRAME",
        insured_value_cents=200000000,
    )
    q1 = create_quote(
        api, prop["id"], coverage_amount_cents=300000000, term_months=12,
        coverage_start_date="2027-01-01", coverage_end_date="2027-12-31",
    )
    bind_quote(api, community_id, q1["id"])
    q2 = create_quote(
        api, prop["id"], coverage_amount_cents=250000000, term_months=12,
        coverage_start_date="2028-01-01", coverage_end_date="2028-12-31",
    )
    resp = api.bind_premium_quote(
        q2["id"], {"expected_community_version": community_version(api, community_id)}, INSURER
    )
    validate_error(resp, ApiErrorId.ERR_EXPOSURE_CAP_EXCEEDED)
    assert get_quote(api, q2["id"])["status"] == "QUOTED"
    assert get_community(api, community_id)["bound_exposure_cents"] == 300000000


def test_occ_bind_stale_version_returns_412(api):
    """PRD §2.7: "Binding a premium quote requires
    `expected_community_version` equal to the community's current `version`"
    and "the request is rejected with `ERR_STALE_VERSION` (HTTP 412)" —
    the version captured before the first bind is stale for the second.

    Design: Corner/complexity_layers/occ_bind_stale_version_returns_412
    """
    ctx = setup_classified_community(api, name="OCC2")
    community_id = ctx["community"]["id"]
    prop = create_property(
        api, community_id, address="6 Oak St", distance_to_nearest_hydrant_ft=300,
        distance_to_nearest_station_road_miles=1.0, construction_type="FRAME",
        insured_value_cents=200000000,
    )
    q1 = create_quote(api, prop["id"], coverage_amount_cents=1000000, term_months=6)
    q2 = create_quote(
        api, prop["id"], coverage_amount_cents=1000000, term_months=6,
        coverage_start_date="2028-01-01", coverage_end_date="2028-06-30",
    )
    stale = community_version(api, community_id)
    bind_quote(api, community_id, q1["id"], expected_version=stale)
    resp = api.bind_premium_quote(q2["id"], {"expected_community_version": stale}, INSURER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_quote(api, q2["id"])["status"] == "QUOTED"


def test_quote_voided_cannot_bind_again(api):
    """PRD §3.8: "The quote must be `QUOTED` (else `ERR_QUOTE_INVALID_STATE`)"
    — a VOIDED quote is terminal and rejects a later bind.

    Design: Corner/state_machines/quote_voided_cannot_bind_again
    """
    ctx = setup_classified_community(api, name="Voidville")
    community_id = ctx["community"]["id"]
    prop = create_property(
        api, community_id, address="2 Vine St", distance_to_nearest_hydrant_ft=300,
        distance_to_nearest_station_road_miles=1.0, construction_type="FRAME",
        insured_value_cents=100000000,
    )
    quote = create_quote(api, prop["id"], coverage_amount_cents=1000000)
    bind_quote(api, community_id, quote["id"])
    void_quote(api, quote["id"])
    resp = api.bind_premium_quote(
        quote["id"], {"expected_community_version": community_version(api, community_id)}, INSURER
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_INVALID_STATE)
