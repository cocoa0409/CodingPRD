"""Interval semantics: half-open commitment windows and closed lock intervals."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import BANKER_HEADERS


def fresh_community(api):
    """One community, one buyer and no forward commitment, so a test owns the window space.

    The shared reference fixture plants a pool of its own, and PRD section 3.6 refuses
    a purchase whose half-open window would run into a live commitment of the same
    community, so the interval tests below start from a bare community.
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    community = fixtures.create_community(api)
    buyer = fixtures.create_buyer(api)
    return {
        "community": community,
        "cm1": community["id"],
        "buyer": buyer,
        "b1": buyer["id"],
        "banker_headers": fixtures.BANKER_HEADERS,
    }


def test_a_commitment_starting_exactly_at_the_prior_end_is_admitted(api):
    """Adjacency with a zero-length gap is legal because the window is half-open.

    PRD §3.6: "The purchase is refused with `ERR_COMMITMENT_WINDOW_OVERLAP` at HTTP
    409 if the new commitment's half-open window would run into an existing `OPEN` or
    `EXHAUSTED` commitment of the same community".
    PRD §3.6: "window overlap is judged on the half-open interval bounded by the start
    instant inclusively and the end instant exclusively."
    Design: Difficulty/resource_temporal_overlap/forward_commitment_closed_open_window_adjacency_allowed
    """
    world = fresh_community(api)

    first = fixtures.create_commitment(
        api, world["cm1"], commitment_code="FC1",
        commitment_start_iso="2026-09-01T00:00:00Z",
        commitment_end_iso="2027-01-01T00:00:00Z",
        committed_units=10,
    )
    assert first["commitment_status"] == "OPEN", first["commitment_status"]

    second = fixtures.create_commitment(
        api, world["cm1"], commitment_code="FC2", investor_name="Freddie",
        committed_rate_bps=512,
        commitment_start_iso="2027-01-01T00:00:00Z",
        commitment_end_iso="2028-01-01T00:00:00Z",
        committed_units=8,
    )
    assert second["commitment_status"] == "OPEN", (
        f"a start at the prior end instant is adjacency, not overlap, "
        f"got {second['commitment_status']}"
    )

    community = fixtures.read_community(api, world["cm1"])
    assert community["forward_units_committed"] == 18, (
        f"both open pools count toward the committed rollup, "
        f"got {community['forward_units_committed']}"
    )


def test_a_commitment_starting_inside_a_live_window_is_refused(api):
    """A start strictly inside the live half-open window is a true overlap.

    PRD §3.6: "The purchase is refused with `ERR_COMMITMENT_WINDOW_OVERLAP` at HTTP
    409 if the new commitment's half-open window would run into an existing `OPEN` or
    `EXHAUSTED` commitment of the same community".
    PRD §2.10: "Priority 16 governs the purchase of a new forward commitment: its
    half-open window from `commitment_start_iso` inclusive to `commitment_end_iso`
    exclusive must not overlap an existing `OPEN` or `EXHAUSTED` commitment of the
    same community".
    Design: Difficulty/resource_temporal_overlap/forward_commitment_closed_open_window_adjacency_allowed
    """
    world = fresh_community(api)
    fixtures.create_commitment(
        api, world["cm1"], commitment_code="FC1",
        commitment_start_iso="2026-09-01T00:00:00Z",
        commitment_end_iso="2027-01-01T00:00:00Z",
        committed_units=10,
    )
    fixtures.create_commitment(
        api, world["cm1"], commitment_code="FC2", investor_name="Freddie",
        committed_rate_bps=512,
        commitment_start_iso="2027-01-01T00:00:00Z",
        commitment_end_iso="2028-01-01T00:00:00Z",
        committed_units=8,
    )

    refused = api.create_forward_commitment(
        world["cm1"],
        f.forward_commitment_payload(
            commitment_code="FC3", investor_name="Ginnie", committed_rate_bps=505,
            committed_units=4,
            commitment_start_iso="2027-06-01T00:00:00Z",
            commitment_end_iso="2028-06-01T00:00:00Z",
        ),
        BANKER_HEADERS,
    )
    validate_error(refused, "ERR_COMMITMENT_WINDOW_OVERLAP", 409)

    commitments, _ = fixtures.rows(
        api.list_community_forward_commitments(world["cm1"], world["banker_headers"])
    )
    assert len(commitments) == 2, (
        f"only the two non-overlapping commitments exist, got {len(commitments)}"
    )


def one_unit_pool_world(api):
    """A single-unit commitment funding two contracts with two qualified applications.

    Built from a bare community so the single-unit pool is the only live commitment in
    it; a second pool would otherwise be the one the clock's selector reaches.
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    community = fixtures.create_community(api)
    buyer = fixtures.create_buyer(api)
    world = {
        "cm1": community["id"],
        "b1": buyer["id"],
        "banker_headers": fixtures.BANKER_HEADERS,
    }
    site1 = fixtures.create_home_site(api, world["cm1"], lot_number="L1", address="1 Elm")
    site2 = fixtures.create_home_site(api, world["cm1"], lot_number="L2", address="2 Elm")
    commitment = fixtures.create_commitment(
        api, world["cm1"], commitment_code="FC1", committed_units=1
    )
    world["commitment"] = commitment
    world["fc1"] = commitment["id"]
    world.update({"hs1": site1["id"], "hs2": site2["id"]})

    contract1 = fixtures.create_contract(api, world["hs1"], world["b1"])
    contract2 = fixtures.create_contract(api, world["hs2"], world["b1"])
    world.update({"ct1": contract1["id"], "ct2": contract2["id"]})

    app1 = fixtures.create_application(api, world["ct1"], application_number="APP-1")
    app2 = fixtures.create_application(api, world["ct2"], application_number="APP-2")
    app1 = get_success_data(api.qualify_loan_application(app1["id"], BANKER_HEADERS))
    app2 = get_success_data(api.qualify_loan_application(app2["id"], BANKER_HEADERS))
    world.update({"la1": app1["id"], "la2": app2["id"]})
    return world


def test_a_second_overlapping_interval_is_refused_on_a_one_unit_pool(api):
    """Two competing intervals need two units; the one-unit pool has only one.

    PRD §3.5: "The lock's closed validity interval must not overlap more competing
    `ACTIVE` intervals on the same commitment's unit pool than the pool has units
    available at the proposed start instant, or the request fails with
    `ERR_LOCK_WINDOW_OVERLAP` at HTTP 409."
    PRD §2.10: "Priority 17 governs a new rate lock: its closed validity interval from
    `lock_start_iso` to `lock_expires_iso` inclusive must not overlap more concurrent
    `ACTIVE` lock intervals on the same commitment's unit pool than that commitment
    has units available at the proposed start instant; failure yields
    `ERR_LOCK_WINDOW_OVERLAP` at HTTP 409".
    Design: Difficulty/resource_temporal_overlap/rate_lock_closed_interval_pool_capacity_on_commitment
    """
    world = one_unit_pool_world(api)
    first_lock = fixtures.give_lock(api, world, lock_days=180)
    assert first_lock["lock_status"] == "ACTIVE", first_lock["lock_status"]

    application = fixtures.read_application(api, world["la2"])
    refused = api.create_rate_lock(
        world["la2"],
        f.rate_lock_payload(
            world["fc1"], lock_days=180,
            expected_application_version=application["version"],
        ),
        BANKER_HEADERS,
    )
    validate_error(refused, "ERR_LOCK_WINDOW_OVERLAP", 409)


def test_the_pool_was_not_the_reason_the_second_lock_was_refused(api):
    """The commitment still shows one unit available, so capacity was never exhausted.

    PRD §2.10: "Priority 18 requires that the selected commitment have at least one
    unit available; failure yields `ERR_FORWARD_COMMITMENT_EXHAUSTED` at HTTP 409,
    and the check applies to rate-lock creation."
    PRD §2.7: "The `units_drawn` counter accumulates one whole unit for every rate
    lock that has been consumed against the commitment".
    Design: Difficulty/resource_temporal_overlap/rate_lock_closed_interval_pool_capacity_on_commitment
    """
    world = one_unit_pool_world(api)
    first_lock = fixtures.give_lock(api, world, lock_days=180)

    application = fixtures.read_application(api, world["la2"])
    api.create_rate_lock(
        world["la2"],
        f.rate_lock_payload(
            world["fc1"], lock_days=180,
            expected_application_version=application["version"],
        ),
        BANKER_HEADERS,
    )

    commitment = fixtures.read_commitment(api, world["fc1"])
    assert commitment["units_available"] == 1, (
        f"an ACTIVE lock has drawn nothing yet, got {commitment['units_available']}"
    )
    assert commitment["units_drawn"] == 0, commitment["units_drawn"]

    locks, _ = fixtures.rows(
        api.list_commitment_rate_locks(world["fc1"], world["banker_headers"])
    )
    assert len(locks) == 1, f"only the accepted lock exists, got {len(locks)}"
    assert locks[0]["id"] == first_lock["id"], locks[0]["id"]