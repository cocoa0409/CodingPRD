"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the server is restarted before each individual test. Setup
uses the lenient ``get_success_data`` validator so a broken precondition
surfaces as a clear "Setup step failed" error rather than a confusing
assertion failure downstream.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, expected_cap_cents
from .factories import (
    claim_payload,
    demand_curve_payload,
    freeze_payload,
    itinerary_payload,
    observation_payload,
    payment_payload,
    protection_payload,
    rebooking_option_payload,
    risk_pool_payload,
    route_payload,
)
from .test_users import (
    TEST_USERS,
    TRAVELER_OTIS,
    TRAVELER_RAE,
)

CLOCK_START = TEST_DEFAULTS["CLOCK_DEFAULT"]

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]
RISK = TEST_USERS["risk_analyst_headers"]
TRAVELER = TEST_USERS["traveler_headers"]


# ─── Clock helpers ───────────────────────────────────────────────────────────

def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    """Set the logical clock. Must be called first in every test.

    The clock endpoint returns no resource payload (PRD §2.2: "For 2xx responses
    with no data, it contains an empty object"), so only the status and envelope
    are checked here.
    """
    response = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    assert response.status_code == 200, (
        f"POST /_clock/set_current_utc failed: {response.status_code} {response.text}")
    return response.json()


def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock, running the scheduled sweep."""
    response = api_client.advance_clock({"to_iso8601": to_iso8601}, ADMIN)
    assert response.status_code == 200, (
        f"POST /_clock/advance failed: {response.status_code} {response.text}")
    return response.json()


# ─── Tier 1: single-entity creation ─────────────────────────────────────────

def create_route(**overrides) -> dict:
    """Register a route and return it."""
    return get_success_data(api_client.create_route(route_payload(**overrides), ADMIN))


def create_itinerary(route_id: str, traveler_user_id: str = "tv-mara", **overrides) -> dict:
    """Create an itinerary on a route, owned by `traveler_user_id`."""
    overrides.setdefault("traveler_user_id", traveler_user_id)
    payload = itinerary_payload(route_id, **overrides)
    return get_success_data(api_client.create_itinerary(payload, headers_for(payload["traveler_user_id"])))


def headers_for(traveler_user_id: str) -> dict:
    """Headers for the given traveler identity (opaque role)."""
    known = {
        "tv-mara": "traveler_headers",
        "tv-otis": "traveler_otis_headers",
        "tv-rae": "traveler_rae_headers",
    }
    return TEST_USERS[known.get(traveler_user_id, "traveler_headers")]


def publish_curve(route_id: str, **overrides) -> dict:
    """Publish (or supersede) the route's demand curve."""
    return get_success_data(
        api_client.publish_curve(demand_curve_payload(route_id, **overrides), OPS)
    )


def observe(route_id: str, itinerary_id: str, fare_cents: int, seats_left: int = 6) -> dict:
    """Append a live fare observation to an itinerary."""
    return get_success_data(
        api_client.create_observation(
            observation_payload(route_id, itinerary_id, fare_cents=fare_cents,
                                seats_left=seats_left),
            OPS,
        )
    )


def open_freeze(itinerary_id: str, expected_itinerary_version, deposit_cents: int = 250,
                headers=None) -> dict:
    """Open a freeze manifest on an itinerary. Returns the DRAFT freeze."""
    return get_success_data(
        api_client.open_freeze(
            itinerary_id,
            freeze_payload(deposit_cents=deposit_cents,
                           expected_itinerary_version=expected_itinerary_version),
            headers or TRAVELER,
        )
    )


def activate_freeze(freeze_id: str, expected_freeze_version, headers=None) -> dict:
    """One activation step: DRAFT -> HELD, or HELD -> FROZEN."""
    return get_success_data(
        api_client.activate_freeze(
            freeze_id, {"expected_freeze_version": expected_freeze_version},
            headers or TRAVELER,
        )
    )


def arm_watch(itinerary_id: str, expected_itinerary_version, headers=None) -> dict:
    """Arm a fare watch on an itinerary. Returns the WatchSubscription."""
    return get_success_data(
        api_client.arm_watch(
            itinerary_id, {"expected_itinerary_version": expected_itinerary_version},
            headers or TRAVELER,
        )
    )


def quote_protection(itinerary_id: str, headers=None, **overrides) -> dict:
    """Quote a protection product on an itinerary."""
    return get_success_data(
        api_client.quote_protection(
            protection_payload(itinerary_id, **overrides), headers or TRAVELER
        )
    )


def record_payment(itinerary_id: str, **overrides) -> dict:
    """Record a payment, captured by default."""
    return get_success_data(
        api_client.create_payment(payment_payload(itinerary_id, **overrides), OPS)
    )


def open_risk_pool(region: str = TEST_DEFAULTS["REGION"], pool_code: str = "WEST-RP-1") -> dict:
    return get_success_data(
        api_client.open_risk_pool(risk_pool_payload(region=region, pool_code=pool_code), RISK)
    )


# ─── Tier 2: entity hierarchy ───────────────────────────────────────────────

def setup_route_with_curve_and_itinerary(**route_overrides):
    """The recurring three-step preamble: route + published curve + itinerary.

    Returns (route, itinerary, curve).
    """
    route = create_route(**route_overrides)
    curve = publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    return route, itinerary, curve


def setup_route_with_draft_freeze(**route_overrides):
    """Route + curve + itinerary + a freeze left in DRAFT.

    Returns (route, itinerary, freeze).
    """
    route, itinerary, _ = setup_route_with_curve_and_itinerary(**route_overrides)
    freeze = open_freeze(itinerary["id"], itinerary["version"])
    return route, itinerary, freeze


# ─── Tier 3: full lifecycle shortcuts ───────────────────────────────────────

def create_freeze_in_state(itinerary_id: str, target_state: str, deposit_cents: int = 250,
                           headers=None) -> dict:
    """Walk a fresh freeze to `target_state` (DRAFT, HELD or FROZEN)."""
    headers = headers or TRAVELER
    freeze = open_freeze(itinerary_id, _itinerary_version(itinerary_id, headers),
                         deposit_cents=deposit_cents, headers=headers)
    if target_state == "DRAFT":
        return freeze
    freeze = activate_freeze(freeze["id"], freeze["version"], headers)
    if target_state == "HELD":
        return freeze
    return activate_freeze(freeze["id"], freeze["version"], headers)


def _itinerary_version(itinerary_id: str, headers) -> int:
    return get_success_data(api_client.get_itinerary(itinerary_id, headers))["version"]


def create_and_freeze(traveler_user_id: str = "tv-mara",
                      observation_fare_cents: int = 10000, deposit_cents: int = 250,
                      **route_overrides):
    """Route + curve + itinerary + observation + freeze driven to FROZEN.

    The observation is appended *before* the freeze is opened so the freeze's
    exposure chain has a live arrival fare to size itself against.

    Returns (route, itinerary, freeze).
    """
    route = create_route(**route_overrides)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], traveler_user_id)
    observe(route["id"], itinerary["id"], observation_fare_cents)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=deposit_cents,
                                    headers=headers_for(traveler_user_id))
    return route, itinerary, freeze


def create_frozen_freeze(route_id: str, traveler_user_id: str = "tv-mara",
                         observation_fare_cents: int = 10000, deposit_cents: int = 250):
    """A FROZEN freeze plus its itinerary, on an already-created route."""
    publish_curve(route_id)
    itinerary = create_itinerary(route_id, traveler_user_id)
    observe(route_id, itinerary["id"], observation_fare_cents)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=deposit_cents)
    return itinerary, freeze


def create_activated_freeze(route_id: str, traveler_user_id: str = "tv-mara",
                            deposit_cents: int = 250, observation_fare_cents=None):
    """A freeze left in HELD (one activation step) plus its itinerary."""
    publish_curve(route_id)
    itinerary = create_itinerary(route_id, traveler_user_id)
    if observation_fare_cents is not None:
        observe(route_id, itinerary["id"], observation_fare_cents)
    freeze = create_freeze_in_state(itinerary["id"], "HELD", deposit_cents=deposit_cents)
    return itinerary, freeze


def create_filed_claim(freeze_id: str, market_price_cents: int, headers=None) -> dict:
    """File a guarantee claim against a FROZEN freeze. Returns the FILED claim."""
    return get_success_data(
        api_client.file_claim(
            claim_payload(freeze_id, market_price_cents=market_price_cents),
            headers or TRAVELER,
        )
    )


def create_approved_claim(claim_id: str, claim_version: int, review_by="ingrid",
                          approve_by="pavel"):
    """Drive a claim FILED -> UNDER_REVIEW -> APPROVED with two distinct adjusters."""
    review = get_success_data(
        api_client.review_claim(claim_id, {"review_note": "first-pass review"},
                                TEST_USERS[f"adjuster_{review_by}_headers"])
    )
    approved = get_success_data(
        api_client.approve_claim(claim_id, {"approval_note": "conformant"},
                                 TEST_USERS[f"adjuster_{approve_by}_headers"])
    )
    return approved


# ─── Tier 4: threshold / accumulation targeting ─────────────────────────────

def setup_route_with_frozen_freeze(base_fare_cents: int = 8900,
                                   observation_fare_cents: int = 10000,
                                   deposit_cents: int = 250,
                                   peak_price_day_index: int = 4,
                                   seats_left: int = 9,
                                   **route_overrides):
    """Route (base 8900 by default) + curve + itinerary + observation + FROZEN freeze.

    Returns (route, itinerary, freeze).
    """
    route_overrides.setdefault("peak_price_day_index", peak_price_day_index)
    route_overrides.setdefault("seats_left", seats_left)
    return create_and_freeze(
        "tv-mara",
        observation_fare_cents=observation_fare_cents,
        deposit_cents=deposit_cents,
        base_fare_cents=base_fare_cents,
        **route_overrides,
    )


def setup_route_with_two_frozen_freezes(observation_fare_cents: int = 10000,
                                        base_fare_cents: int = 8900,
                                        deposit_cents: int = 250,
                                        **route_overrides):
    """One route carrying two itineraries, each with its own FROZEN freeze.

    Returns (route, itinerary_a, freeze_a, itinerary_b, freeze_b).
    """
    route_overrides.setdefault("base_fare_cents", base_fare_cents)
    route = create_route(**route_overrides)
    publish_curve(route["id"])
    itin_a = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itin_a["id"], observation_fare_cents)
    freeze_a = create_freeze_in_state(itin_a["id"], "FROZEN", deposit_cents=deposit_cents)

    itin_b = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itin_b["id"], observation_fare_cents)
    freeze_b = create_freeze_in_state(itin_b["id"], "FROZEN", deposit_cents=deposit_cents)
    return route, itin_a, freeze_a, itin_b, freeze_b


def setup_route_at_high_water_mark(high_water_cents: int = 8236,
                                   observation_fare_cents: int = 10000,
                                   deposit_cents: int = 250,
                                   **route_overrides):
    """A route whose base fare is the high-water mark at freeze time.

    The route is registered at `high_water_cents`, patched up to 8900 so the
    live base fare is higher, the freeze is pinned at the (lower) registration
    fare and THEN closed, so the freeze's manifest is the high-water mark while
    the live base fare drives the overshoot rule. Returns (route, itinerary, freeze).
    """
    route = create_route(base_fare_cents=high_water_cents,
                         **{k: v for k, v in route_overrides.items()
                            if k != "base_fare_cents"})
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    get_success_data(api_client.update_route(route["id"], {"base_fare_cents": 8900}, ADMIN))
    observe(route["id"], itinerary["id"], observation_fare_cents)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=deposit_cents)
    route = get_success_data(api_client.get_route(route["id"], ADMIN))
    return route, itinerary, freeze


def setup_route_with_two_frozen_freezes_at_high_water_mark(
        observation_fare_cents: int = 10000, deposit_cents: int = 250):
    """Two itineraries on one high-water-mark route, each with a FROZEN freeze."""
    route = create_route(base_fare_cents=8236, hedge_ratio_pct=0.6)
    publish_curve(route["id"])
    itin_a = create_itinerary(route["id"], "tv-mara")
    get_success_data(api_client.update_route(route["id"], {"base_fare_cents": 8900}, ADMIN))
    observe(route["id"], itin_a["id"], observation_fare_cents)
    freeze_a = create_freeze_in_state(itin_a["id"], "FROZEN", deposit_cents=deposit_cents)

    itin_b = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itin_b["id"], observation_fare_cents)
    freeze_b = create_freeze_in_state(itin_b["id"], "FROZEN", deposit_cents=deposit_cents)
    route = get_success_data(api_client.get_route(route["id"], ADMIN))
    return route, itin_a, freeze_a, itin_b, freeze_b


# ─── Tier 5: claim-pipeline and multi-role scenarios ────────────────────────

def setup_claim_ready_for_settlement(market_price_cents: int = 16500,
                                     observation_fare_cents: int = 14000,
                                     base_fare_cents: int = 8900,
                                     approver_adjuster: str = "pavel",
                                     **route_overrides):
    """Route + itinerary + FROZEN freeze + a claim parked in APPROVED.

    The reviewing adjuster (`ingrid`) and the approving adjuster (`pavel`) differ,
    so only the settlement identity still has to be chosen by the caller.

    Returns a dict of named ids: route_id, itinerary_id, freeze_id, claim_id,
    claim_version.
    """
    route_overrides.setdefault("base_fare_cents", base_fare_cents)
    route = create_route(**route_overrides)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], observation_fare_cents)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    claim = create_filed_claim(freeze["id"], market_price_cents)
    approved = create_approved_claim(claim["id"], claim["version"],
                                     review_by="ingrid", approve_by=approver_adjuster)
    route = get_success_data(api_client.get_route(route["id"], ADMIN))
    return {
        "route": route,
        "itinerary": itinerary,
        "freeze": get_success_data(api_client.get_freeze(freeze["id"], TRAVELER)),
        "claim": approved,
        "claim_id": claim["id"],
        "claim_version": approved["version"],
    }


def setup_freeze_at_high_water_mark_with_claim(market_price_cents: int = 22800,
                                               observation_fare_cents: int = 10000):
    """High-water-mark freeze carrying a filed claim, for depth/continuum checks."""
    route = create_route(base_fare_cents=8236, hedge_ratio_pct=0.6)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    get_success_data(api_client.update_route(route["id"], {"base_fare_cents": 8900}, ADMIN))
    observe(route["id"], itinerary["id"], observation_fare_cents)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    claim = create_filed_claim(freeze["id"], market_price_cents)
    return route, itinerary, freeze, claim


# ─── Tier 5b: change-protection scenarios ───────────────────────────────────

def setup_change_protection_active(traveler_user_id: str = "tv-otis",
                                   declared_probability: float = 0.70):
    """Route (MIDWEST/ORD) + curve + itinerary + an ACTIVE CHANGE protection."""
    route = create_route(origin_airport="ORD", destination_airport="LHR",
                         flight_number="HA707", region="MIDWEST",
                         base_fare_cents=13200, peak_price_day_index=0, seats_left=6,
                         fare_band_cents=[9000, 12000, 15000, 17000, 19000])
    publish_curve(route["id"], each_day_prices_cents=[9000, 9000, 9000, 9000, 9000],
                  seats_left_at_each_day=[6, 6, 6, 6, 6])
    itinerary = create_itinerary(route["id"], traveler_user_id,
                                 departure_date="2026-12-01T00:00:00Z")
    headers = TEST_USERS["traveler_otis_headers"]
    protection = quote_protection(itinerary["id"], headers=headers, product_type="CHANGE",
                                  cancellation_disruption_probability=declared_probability)
    protection = get_success_data(
        api_client.activate_protection(protection["id"],
                                       {"expected_protection_version": protection["version"]},
                                       headers)
    )
    return route, itinerary, protection


def setup_change_protection_with_held_option(new_departure_date: str = "2026-12-05T00:00:00Z",
                                             option_fare_cents: int = 12300,
                                             declared_probability: float = 0.70):
    """ACTIVE CHANGE protection + a change event with one option SELECTED and HELD.

    Returns (route, itinerary, protection, change_event, option).
    """
    route, itinerary, protection = setup_change_protection_active(
        declared_probability=declared_probability)
    headers = TEST_USERS["traveler_otis_headers"]
    change_event = get_success_data(
        api_client.file_change_event(
            {"protection_id": protection["id"], "new_departure_date": new_departure_date,
             "gap_direction": "ORIGIN_DIRECTION"},
            headers)
    )
    option = get_success_data(
        api_client.offer_option(
            rebooking_option_payload(change_event["id"], departure_date=new_departure_date,
                                     option_fare_cents=option_fare_cents),
            headers)
    )
    get_success_data(api_client.select_option(change_event["id"], {"option_id": option["id"]},
                                              headers))
    option = get_success_data(api_client.accept_option(option["id"], {}, headers))
    change_event = get_success_data(api_client.get_change_event(change_event["id"], headers))
    return route, itinerary, protection, change_event, option


def setup_change_protection_with_open_event(new_departure_date: str = "2026-12-04T00:00:00Z",
                                            declared_probability: float = 0.70):
    """ACTIVE CHANGE protection plus an OPEN change event with no option.

    Returns (route, itinerary, protection, change_event).
    """
    route, itinerary, protection = setup_change_protection_active(
        declared_probability=declared_probability)
    headers = TEST_USERS["traveler_otis_headers"]
    change_event = get_success_data(
        api_client.file_change_event(
            {"protection_id": protection["id"], "new_departure_date": new_departure_date,
             "gap_direction": "ORIGIN_DIRECTION"},
            headers)
    )
    return route, itinerary, protection, change_event


# ─── Tier 5c: posture / hedging scenarios ───────────────────────────────────

def setup_surged_route_with_frozen_freeze(deposit_cents: int = 250,
                                          observation_fare_cents: int = 10000):
    """A route carrying a FROZEN freeze, then moved into SURGE.

    Returns (route, itinerary, freeze).
    """
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], observation_fare_cents)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=deposit_cents)
    get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "SURGE", "posture_reason_code": "DEMAND_PEAK",
             "expected_route_version": route["version"]},
            ADMIN)
    )
    route = get_success_data(api_client.get_route(route["id"], ADMIN))
    return route, itinerary, freeze


def setup_pool_and_route(absorbed_regression: bool = False):
    """A WEST risk pool plus a route in the same region.

    Returns (pool, route). The returned route is always re-read, because
    registering the pool and marking a position advance derivations that move
    the route's version.
    """
    pool = open_risk_pool()
    route = create_route()
    if absorbed_regression:
        position = get_success_data(
            api_client.open_hedging_position(
                {"route_id": route["id"], "coverage_date": "2026-09-15T00:00:00Z",
                 "hedge_price_cents": 9000, "contract_quantity_cents": 500000,
                 "expected_route_version": route["version"]},
                RISK)
        )
        get_success_data(
            api_client.mark_hedging_position(position["id"],
                                             {"projected_day_cost_cents": 7000}, RISK)
        )
        get_success_data(api_client.hedge_regression_sweep({"pool_id": pool["id"]}, RISK))
    route = get_success_data(api_client.get_route(route["id"], ADMIN))
    return pool, route


def setup_passive_watch_reading_wait(observation_fare_cents: int = 10000,
                                     traveler_user_id: str = "tv-mara"):
    """Route + curve + itinerary observed *inside* its tier ceiling, plus an ARMED watch.

    On such an itinerary the tier ceiling (30000) exceeds the latest fare, so the
    cost-of-waiting evaluation always reads WAIT.

    Returns (route, itinerary, watch).
    """
    route, itinerary, _ = setup_route_with_curve_and_itinerary()
    observe(route["id"], itinerary["id"], observation_fare_cents)
    itinerary = get_success_data(api_client.get_itinerary(itinerary["id"], TRAVELER))
    watch = arm_watch(itinerary["id"], itinerary["version"], TRAVELER)
    return route, itinerary, watch


def setup_route_with_armed_watch_and_frozen_freeze(observation_fare_cents: int = 10000,
                                                   deposit_cents: int = 250):
    """Route + curve + itinerary observed + ARMED watch + FROZEN freeze.

    Returns (route, itinerary, watch, freeze).
    """
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], observation_fare_cents)
    itinerary = get_success_data(api_client.get_itinerary(itinerary["id"], TRAVELER))
    watch = arm_watch(itinerary["id"], itinerary["version"], TRAVELER)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=deposit_cents)
    return route, itinerary, watch, freeze


# ─── Small read helpers used inside tests ───────────────────────────────────

def read_route(route_id: str) -> dict:
    return get_success_data(api_client.get_route(route_id, ADMIN))


def raise_exposure_ceiling(route: dict, ceiling_cents: int = 500000) -> dict:
    """Widen a route's per-route exposure cap and return the refreshed route.

    PRD §3.3 makes the per-route cap bind on activation, so a scenario that
    needs several freezes in flight on one route must widen the ceiling *before*
    appending the observations that size the freezes' exposure chains.
    """
    get_success_data(
        api_client.update_route(route["id"], {"max_guarantee_exposure_cents": ceiling_cents},
                                ADMIN)
    )
    return read_route(route["id"])


def read_itinerary(itinerary_id: str) -> dict:
    return get_success_data(api_client.get_itinerary(itinerary_id, TRAVELER))


def read_freeze(freeze_id: str) -> dict:
    return get_success_data(api_client.get_freeze(freeze_id, TRAVELER))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, TEST_USERS["adjuster_rosa_headers"]))


def read_payment(payment_id: str) -> dict:
    return get_success_data(api_client.get_payment(payment_id, OPS))


def read_protection(protection_id: str) -> dict:
    return get_success_data(api_client.get_protection(protection_id, TRAVELER))


def read_change_event(change_event_id: str) -> dict:
    return get_success_data(
        api_client.get_change_event(change_event_id, TEST_USERS["traveler_otis_headers"]))


def read_option(option_id: str) -> dict:
    return get_success_data(
        api_client.get_option(option_id, TEST_USERS["traveler_otis_headers"]))


def read_watch(watch_id: str) -> dict:
    return get_success_data(api_client.get_watch(watch_id, TRAVELER))


def read_hedging_position(position_id: str) -> dict:
    return get_success_data(api_client.get_hedging_position(position_id, RISK))
