"""Exact boundaries: the free extension allowance and the commitment window edge."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import BANKER_HEADERS


def two_lock_world(api, *, lock_days=30):
    """Two contracts in one community, each holding one lock on its own application."""
    world = fixtures.seed_reference_data(api)
    site1 = fixtures.create_home_site(api, world["cm1"], lot_number="L1", address="1 Elm")
    site2 = fixtures.create_home_site(api, world["cm1"], lot_number="L2", address="2 Elm")

    contract1 = fixtures.create_contract(api, site1["id"], world["b1"])
    contract2 = fixtures.create_contract(api, site2["id"], world["b1"])
    world.update({"hs1": site1["id"], "hs2": site2["id"],
                  "ct1": contract1["id"], "ct2": contract2["id"]})

    app1 = fixtures.create_application(api, world["ct1"], application_number="APP-1")
    app2 = fixtures.create_application(api, world["ct2"], application_number="APP-2")
    app1 = get_success_data(api.qualify_loan_application(app1["id"], BANKER_HEADERS))
    app2 = get_success_data(api.qualify_loan_application(app2["id"], BANKER_HEADERS))
    world.update({"la1": app1["id"], "la2": app2["id"]})

    lock1 = get_success_data(
        api.create_rate_lock(
            world["la1"],
            f.rate_lock_payload(world["fc1"], lock_days=lock_days,
                                expected_application_version=app1["version"]),
            BANKER_HEADERS,
        )
    )
    lock2 = get_success_data(
        api.create_rate_lock(
            world["la2"],
            f.rate_lock_payload(world["fc1"], lock_days=lock_days,
                                expected_application_version=app2["version"]),
            BANKER_HEADERS,
        )
    )
    world.update({"lk1": lock1["id"], "lk2": lock2["id"]})
    return world


def test_a_fifteen_day_extension_sits_exactly_on_the_free_allowance(api):
    """Fifteen extra days bill nothing because the allowance is inclusive.

    PRD §3.5: "The first 15 extra days are free."
    PRD §3.5: "The rule prices the *extra* days a lock is being asked to cover,
    measured against the lock's original `lock_days` rather than against days already
    elapsed, and it prices them in two marginal bands above a free allowance."
    Design: Difficulty/boundary_precision_check/extension_free_day_boundary_at_exactly_fifteen_days
    """
    world = two_lock_world(api, lock_days=30)
    extended = get_success_data(api.extend_rate_lock(world["lk1"], 45, BANKER_HEADERS))
    assert extended["lock_days"] == 45, extended["lock_days"]
    assert extended["lock_cost_cents"] == 0, (
        f"extra_days of exactly 15 is still free, got {extended['lock_cost_cents']}"
    )


def test_one_day_past_the_free_allowance_bills_exactly_one_mid_tier_day(api):
    """Sixteen extra days bill one mid-tier day, so the boundary costs 45 cents.

    PRD §2.9: "The mid-tier rate is 45 cents per day and the high-tier rate is 110
    cents per day."
    PRD §3.5: "The next 15 days beyond that allowance are billed at a mid-tier rate
    per day. Every further extra day is billed at a high-tier rate per day."
    Design: Difficulty/boundary_precision_check/extension_free_day_boundary_at_exactly_fifteen_days
    """
    world = two_lock_world(api, lock_days=30)

    at_allowance = get_success_data(api.extend_rate_lock(world["lk1"], 45, BANKER_HEADERS))
    past_allowance = get_success_data(api.extend_rate_lock(world["lk2"], 46, BANKER_HEADERS))

    assert at_allowance["lock_cost_cents"] == 0, at_allowance["lock_cost_cents"]
    assert past_allowance["lock_cost_cents"] == 45, (
        f"one billed day at the mid tier is 45, got {past_allowance['lock_cost_cents']}"
    )
    assert past_allowance["lock_cost_cents"] - at_allowance["lock_cost_cents"] == 45, (
        "a one-day delta across the boundary changes the answer by exactly one mid-tier day"
    )


def window_edge_world(api):
    """A commitment whose usable window ends at 2030-01-01, plus two qualified applications.

    The reference pool is planted with a window that closes before the pool built here
    opens, so the two commitments cannot overlap (PRD section 3.6).
    """
    world = fixtures.seed_reference_data(
        api,
        committed_units=1,
        commitment_start_iso="2026-09-01T00:00:00Z",
        commitment_end_iso="2026-09-02T00:00:00Z",
    )
    site1 = fixtures.create_home_site(
        api, world["cm1"], lot_number="L1", address="1 Elm",
        advertised_rate_expires_iso="2031-01-01T00:00:00Z",
    )
    site2 = fixtures.create_home_site(
        api, world["cm1"], lot_number="L2", address="2 Elm",
        advertised_rate_expires_iso="2031-01-01T00:00:00Z",
    )
    commitment = fixtures.create_commitment(
        api, world["cm1"], commitment_code="EDGE",
        commitment_start_iso="2026-09-02T00:00:00Z",
        commitment_end_iso="2030-01-01T00:00:00Z", committed_units=10,
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


def test_a_lock_created_at_the_commitment_end_instant_is_admitted(api):
    """The window's end is inclusive, so a lock at exactly the end instant succeeds.

    PRD §2.10: "Priority 12 requires that the current logical clock lie within the
    selected forward commitment's window, treating `commitment_start_iso` and
    `commitment_end_iso` as inclusive bounds".
    PRD §3.5: "its eligible pool is every commitment belonging to the contract's
    community that is `OPEN`, has at least one unit available, and has a window
    containing the current clock inclusive of both endpoints".
    Design: Difficulty/boundary_precision_check/commitment_window_inclusive_end_boundary_rejected_one_second_late
    """
    world = window_edge_world(api)
    fixtures.set_clock(api, "2030-01-01T00:00:00Z")

    lock = fixtures.give_lock(api, world, lock_days=30)
    assert lock["lock_status"] == "ACTIVE", (
        f"the end instant is inside the window, got {lock['lock_status']}"
    )

    commitment = fixtures.read_commitment(api, world["fc1"])
    assert commitment["units_drawn"] == 0, (
        "creating a lock draws no unit until the lock is consumed"
    )
    assert commitment["units_available"] == 10, commitment["units_available"]


def test_a_lock_one_second_past_the_commitment_end_is_rejected(api):
    """One second later the same call fails on the window, and no row is created.

    PRD §2.10: "Priority 12 requires that the current logical clock lie within the
    selected forward commitment's window, treating `commitment_start_iso` and
    `commitment_end_iso` as inclusive bounds; failure yields
    `ERR_COMMITMENT_WINDOW_CLOSED` at HTTP 409".
    PRD §3.5: "A commitment whose window does not contain the current clock yields
    `ERR_COMMITMENT_WINDOW_CLOSED` at HTTP 409".
    Design: Difficulty/boundary_precision_check/commitment_window_inclusive_end_boundary_rejected_one_second_late
    """
    world = window_edge_world(api)
    fixtures.set_clock(api, "2030-01-01T00:00:00Z")
    fixtures.give_lock(api, world, lock_days=30)

    fixtures.set_clock(api, "2030-01-01T00:00:01Z")
    application = fixtures.read_application(api, world["la2"])
    refused = api.create_rate_lock(
        world["la2"],
        f.rate_lock_payload(
            world["fc1"], lock_days=30,
            expected_application_version=application["version"],
        ),
        BANKER_HEADERS,
    )
    validate_error(refused, "ERR_COMMITMENT_WINDOW_CLOSED", 409)

    locks, _ = fixtures.rows(
        api.list_application_rate_locks(world["la2"], world["banker_headers"])
    )
    assert locks == [], f"the rejected call must leave no row, got {locks}"