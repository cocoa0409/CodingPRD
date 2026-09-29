"""
Composite setup helpers for the State Fish Hatchery Stocking Program API.

The harness restarts the server before every test, so each test starts against an
empty database and every precondition has to be built through the API itself.
These helpers do that building in the order the PRD's workflows demand, and they
return a plain dictionary context so a test can reach any record it needs.

Two habits here are deliberate. First, every helper that must quote an optimistic
concurrency token re-reads the parent immediately before the write, so that a
helper's own earlier hop can never invalidate its later one. Second, a
`HatcheryManager` is always addressed with the `id` of the station it actually
runs, because PRD 2.1 makes that role the one entity-backed identity.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    ACCESS_REMOTE,
    INSPECTION_TYPE_PRE_TRANSFER,
    MODE_PRIORITY_WATERFALL,
    RESULT_NEGATIVE,
    STAGE_FINGERLING,
    STAGE_FRY,
    STAGE_YEARLING,
    WATER_CLASS_COLDWATER_STREAM,
    WATER_SOURCE_WELL,
)
from .test_users import (
    ADMIN_HEADERS,
    BIO_CARLA_HEADERS,
    BIO_DANA_HEADERS,
    BIO_FRANK_HEADERS,
    PUB_ERIN_HEADERS,
    VET_ANNA_HEADERS,
    VET_BRUNO_HEADERS,
    make_hatchery_manager_headers,
)

OMIT = f.OMIT


# ─── Logical clock ────────────────────────────────────

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock, running every clock-driven re-evaluation."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), ADMIN_HEADERS))


# ─── Stations ─────────────────────────────────────────

def create_hatchery(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_hatchery(f.hatchery_payload(**overrides), ADMIN_HEADERS)
    )


def manager_of(hatchery: Dict[str, Any]) -> Dict[str, str]:
    """Headers for the manager of this station: `X-User-ID` is the station's `id`."""
    return make_hatchery_manager_headers(hatchery["id"])


def read_hatchery(api: ApiClient, hatchery: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.get_hatchery(hatchery["id"], manager_of(hatchery)))


def log_effluent_reading(
    api: ApiClient, hatchery: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_effluent_reading(
            f.effluent_reading_payload(hatchery["id"], **overrides), manager_of(hatchery)
        )
    )


# ─── Waters ───────────────────────────────────────────

def create_water(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_water(f.water_payload(**overrides), ADMIN_HEADERS))


def close_water(api: ApiClient, water: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.close_water(water["id"], ADMIN_HEADERS))


# ─── Fleet ────────────────────────────────────────────

def create_transport_unit(
    api: ApiClient, hatchery: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_transport_unit(
            f.transport_unit_payload(hatchery["id"], **overrides), manager_of(hatchery)
        )
    )


# ─── Brood groups ─────────────────────────────────────

def create_brood_stock(
    api: ApiClient, hatchery: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_brood_stock(
            f.brood_stock_payload(hatchery["id"], **overrides), manager_of(hatchery)
        )
    )


def open_spawning_window(
    api: ApiClient, hatchery: Dict[str, Any], brood_stock: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(
        api.open_spawning_window(brood_stock["id"], manager_of(hatchery))
    )


def read_brood_stock(
    api: ApiClient, hatchery: Dict[str, Any], brood_stock_id: str
) -> Dict[str, Any]:
    return get_success_data(api.get_brood_stock(brood_stock_id, manager_of(hatchery)))


# ─── Egg takes ────────────────────────────────────────

def create_spawn_event(
    api: ApiClient, hatchery: Dict[str, Any], brood_stock: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_spawn_event(
            f.spawn_event_payload(brood_stock["id"], **overrides), manager_of(hatchery)
        )
    )


def record_take(
    api: ApiClient, hatchery: Dict[str, Any], spawn_event: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.record_take(
            spawn_event["id"], f.record_take_payload(**overrides), manager_of(hatchery)
        )
    )


def lot_for_spawn_event(
    api: ApiClient, hatchery: Dict[str, Any], spawn_event_id: str
) -> Dict[str, Any]:
    """
    Find the rearing lot a recorded take brought into existence. PRD 2.3 notes
    that filtering lots by `spawn_event_id` "is how a lot brought into existence
    by a recorded egg take is discovered, since lots have no creation endpoint".
    """
    response = api.list_rearing_lots(
        manager_of(hatchery), {"spawn_event_id": spawn_event_id}
    )
    lots = get_success_data(response)
    assert isinstance(lots, list) and lots, (
        f"Recording a take must create a rearing lot for spawn event {spawn_event_id}"
    )
    return lots[0]


# ─── Rearing ──────────────────────────────────────────

def read_lot(api: ApiClient, hatchery: Dict[str, Any], lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rearing_lot(lot_id, manager_of(hatchery)))


def lot_version(api: ApiClient, hatchery: Dict[str, Any], lot_id: str) -> int:
    return int(read_lot(api, hatchery, lot_id)["version"])


def record_feeding(
    api: ApiClient,
    hatchery: Dict[str, Any],
    lot_id: str,
    fed_at: str,
    feed_lbs: float,
    avg_weight_g_after: float,
    mortality_count: Any = OMIT,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_feeding(
            lot_id,
            f.feeding_payload(fed_at, feed_lbs, avg_weight_g_after, mortality_count),
            manager_of(hatchery),
        )
    )


def advance_stage(
    api: ApiClient, hatchery: Dict[str, Any], lot_id: str, to_stage: str
) -> Dict[str, Any]:
    return get_success_data(
        api.advance_stage(lot_id, f.advance_stage_payload(to_stage), manager_of(hatchery))
    )


# ─── Fish health ──────────────────────────────────────

def open_inspection(
    api: ApiClient,
    lot_id: str,
    vet_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_health_inspection(
            f.health_inspection_payload(lot_id, **overrides),
            vet_headers or VET_ANNA_HEADERS,
        )
    )


def record_result(
    api: ApiClient,
    inspection_id: str,
    result: str = RESULT_NEGATIVE,
    pathogen_code: Any = OMIT,
    vet_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_result(
            inspection_id,
            f.record_result_payload(result, pathogen_code),
            vet_headers or VET_ANNA_HEADERS,
        )
    )


def record_treatment(
    api: ApiClient,
    inspection_id: str,
    vet_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.record_treatment(
            inspection_id,
            f.record_treatment_payload(**overrides),
            vet_headers or VET_ANNA_HEADERS,
        )
    )


def certify(
    api: ApiClient, inspection_id: str, vet_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Sign a certificate. The signer defaults to a different veterinarian from the
    sampler, because PRD 3.5 refuses the sampling veterinarian's own signature.
    """
    return get_success_data(
        api.certify_inspection(inspection_id, vet_headers or VET_BRUNO_HEADERS)
    )


def read_inspection(
    api: ApiClient, inspection_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read an inspection back. Every role but `PublicRequester` may do so."""
    return get_success_data(
        api.get_health_inspection(inspection_id, headers or VET_ANNA_HEADERS)
    )


# ─── Demand and allocation ────────────────────────────

def create_stocking_request(
    api: ApiClient,
    water: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_stocking_request(
            f.stocking_request_payload(water["id"], **overrides),
            headers or BIO_CARLA_HEADERS,
        )
    )


def create_allocation_plan(
    api: ApiClient, hatchery: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_allocation_plan(
            f.allocation_plan_payload(hatchery["id"], **overrides), ADMIN_HEADERS
        )
    )


def read_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_allocation_plan(plan_id, ADMIN_HEADERS))


def plan_version(api: ApiClient, plan_id: str) -> int:
    return int(read_plan(api, plan_id)["version"])


def attach_request(
    api: ApiClient,
    request: Dict[str, Any],
    plan: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Queue a request onto a plan, re-reading the plan's `version` immediately
    beforehand so that a previous attach in the same setup cannot make this one
    stale.
    """
    return get_success_data(
        api.attach_to_plan(
            request["id"],
            f.attach_to_plan_payload(plan["id"], plan_version(api, plan["id"])),
            headers or BIO_CARLA_HEADERS,
        )
    )


def run_plan(api: ApiClient, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Run the selector, quoting the plan version as it stands after every attach."""
    return get_success_data(
        api.run_allocation_plan(
            plan["id"], f.run_plan_payload(plan_version(api, plan["id"])), ADMIN_HEADERS
        )
    )


def read_request(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_stocking_request(request_id, ADMIN_HEADERS))


def read_water(api: ApiClient, water_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_water(water_id, ADMIN_HEADERS))


# ─── Trips ────────────────────────────────────────────

def create_stocking_event(
    api: ApiClient,
    hatchery: Dict[str, Any],
    request: Dict[str, Any],
    lot_id: str,
    unit: Dict[str, Any],
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Schedule a trip, re-reading the lot's `version` immediately beforehand so the
    mandatory `expected_lot_version` always matches whatever the setup last did to
    the lot.
    """
    payload = f.stocking_event_payload(
        request["id"],
        lot_id,
        unit["id"],
        lot_version(api, hatchery, lot_id),
        **overrides,
    )
    return get_success_data(api.create_stocking_event(payload, manager_of(hatchery)))


def load_event(
    api: ApiClient,
    hatchery: Dict[str, Any],
    event_id: str,
    loaded_at: str,
    load_water_temp_c: float,
    measured_load_lbs: Any = OMIT,
) -> Dict[str, Any]:
    return get_success_data(
        api.load_stocking_event(
            event_id,
            f.load_payload(loaded_at, load_water_temp_c, measured_load_lbs),
            manager_of(hatchery),
        )
    )


def release_event(
    api: ApiClient,
    hatchery: Dict[str, Any],
    event_id: str,
    arrived_at: str,
    site_water_temp_c: float,
    tempering_minutes: int,
    transport_mortality_count: Any = OMIT,
) -> Dict[str, Any]:
    return get_success_data(
        api.release_stocking_event(
            event_id,
            f.release_payload(
                arrived_at,
                site_water_temp_c,
                tempering_minutes,
                transport_mortality_count,
            ),
            manager_of(hatchery),
        )
    )


def read_event(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_stocking_event(event_id, ADMIN_HEADERS))


def read_unit(api: ApiClient, unit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_transport_unit(unit_id, ADMIN_HEADERS))


# ─── Composite scenarios ──────────────────────────────
#
# Each of these builds on the one above it, so a test can enter the workflow at
# whatever depth its subject needs. They return a mutable context dictionary
# keyed by record name; every record in it is the body the API returned at the
# moment it was created, so tests that care about later state re-read it.


def station_at_rest(api: ApiClient, **hatchery_overrides: Any) -> Dict[str, Any]:
    """A registered station, all three ledgers seeded at rest and posture `OPEN`."""
    hatchery = create_hatchery(api, **hatchery_overrides)
    return {"hatchery": hatchery, "manager": manager_of(hatchery)}


def spawning_group(
    api: ApiClient,
    hatchery_overrides: Optional[Dict[str, Any]] = None,
    brood_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A station whose brood group has been declared ripe and stands in `SPAWNING`."""
    ctx = station_at_rest(api, **(hatchery_overrides or {}))
    brood_stock = create_brood_stock(api, ctx["hatchery"], **(brood_overrides or {}))
    open_spawning_window(api, ctx["hatchery"], brood_stock)
    ctx["brood_stock"] = read_brood_stock(api, ctx["hatchery"], brood_stock["id"])
    return ctx


def lot_at_egg(
    api: ApiClient,
    hatchery_overrides: Optional[Dict[str, Any]] = None,
    brood_overrides: Optional[Dict[str, Any]] = None,
    spawn_overrides: Optional[Dict[str, Any]] = None,
    take_overrides: Optional[Dict[str, Any]] = None,
    take_clock: str = f.instant(2026, 8, 10),
) -> Dict[str, Any]:
    """
    A recorded egg take and therefore a rearing lot at `EGG` and `UNSCREENED`.

    The clock is moved to the take instant first, because PRD 3.3 requires
    `taken_at` not to be after the logical clock.
    """
    ctx = spawning_group(api, hatchery_overrides, brood_overrides)
    ctx["spawn_event"] = create_spawn_event(
        api, ctx["hatchery"], ctx["brood_stock"], **(spawn_overrides or {})
    )
    set_clock(api, take_clock)
    ctx["clock"] = take_clock
    take_body = dict(take_overrides or {})
    take_body.setdefault("taken_at", take_clock)
    ctx["spawn_event"] = record_take(
        api, ctx["hatchery"], ctx["spawn_event"], **take_body
    )
    ctx["lot"] = lot_for_spawn_event(api, ctx["hatchery"], ctx["spawn_event"]["id"])
    return ctx


def yearling_lot(
    api: ApiClient,
    hatchery_overrides: Optional[Dict[str, Any]] = None,
    brood_overrides: Optional[Dict[str, Any]] = None,
    spawn_overrides: Optional[Dict[str, Any]] = None,
    take_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A lot grown to `YEARLING` through two feedings and three stage advances.

    Both feedings are chosen so the arithmetic lands on round pounds: at
    453.592 grams to the pound, 4.53592 g is exactly 0.01 lb per fish and
    45.3592 g exactly 0.1 lb per fish. After the second feeding the lot holds
    16000 fish at 45.3592 g, which is 1600.00 lb of standing crop.
    """
    ctx = lot_at_egg(api, hatchery_overrides, brood_overrides, spawn_overrides, take_overrides)
    lot_id = ctx["lot"]["id"]
    record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 10), 300.0, 4.53592, 2000
    )
    advance_stage(api, ctx["hatchery"], lot_id, STAGE_FRY)
    advance_stage(api, ctx["hatchery"], lot_id, STAGE_FINGERLING)
    set_clock(api, f.instant(2026, 8, 20))
    ctx["clock"] = f.instant(2026, 8, 20)
    record_feeding(
        api, ctx["hatchery"], lot_id, f.instant(2026, 8, 20), 1500.0, 45.3592, 2000
    )
    ctx["lot"] = advance_stage(api, ctx["hatchery"], lot_id, STAGE_YEARLING)
    return ctx


def sampled_lot(
    api: ApiClient,
    hatchery_overrides: Optional[Dict[str, Any]] = None,
    brood_overrides: Optional[Dict[str, Any]] = None,
    spawn_overrides: Optional[Dict[str, Any]] = None,
    take_overrides: Optional[Dict[str, Any]] = None,
    sample_clock: str = f.instant(2026, 8, 25),
    inspection_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A `YEARLING` lot with one `PRE_TRANSFER` inspection open in `SAMPLED` status.

    The clock is moved to the sampling instant first, because PRD 3.5 requires
    `sampled_at` not to be after the logical clock. Opening the inspection also
    drives the lot to `UNDER_INSPECTION`.
    """
    ctx = yearling_lot(api, hatchery_overrides, brood_overrides, spawn_overrides, take_overrides)
    set_clock(api, sample_clock)
    ctx["clock"] = sample_clock
    overrides: Dict[str, Any] = {
        "inspection_type": INSPECTION_TYPE_PRE_TRANSFER,
        "sample_size": 60,
        "sampled_at": sample_clock,
    }
    overrides.update(inspection_overrides or {})
    ctx["inspection"] = open_inspection(
        api, ctx["lot"]["id"], VET_ANNA_HEADERS, **overrides
    )
    return ctx


def passed_inspection(api: ApiClient, **sampled_kwargs: Any) -> Dict[str, Any]:
    """
    A `PASSED` inspection sampled by vet-anna and awaiting another vet's signature.

    The lot stays `UNDER_INSPECTION` with a null `certificate_expires_at` until the
    certificate is actually signed.
    """
    ctx = sampled_lot(api, **sampled_kwargs)
    ctx["inspection"] = record_result(
        api, ctx["inspection"]["id"], RESULT_NEGATIVE, vet_headers=VET_ANNA_HEADERS
    )
    return ctx


def certified_yearling_lot(
    api: ApiClient,
    hatchery_overrides: Optional[Dict[str, Any]] = None,
    brood_overrides: Optional[Dict[str, Any]] = None,
    spawn_overrides: Optional[Dict[str, Any]] = None,
    take_overrides: Optional[Dict[str, Any]] = None,
    certify_clock: str = f.instant(2026, 8, 25),
) -> Dict[str, Any]:
    """
    A `YEARLING` lot carrying a signed health certificate.

    The sample is drawn by one veterinarian and the certificate signed by
    another, as PRD 3.5's segregation-of-duties gate requires. Certifying at
    2026-08-25 puts the certificate's expiry 30 days out, at 2026-09-24.
    """
    ctx = passed_inspection(
        api,
        hatchery_overrides=hatchery_overrides,
        brood_overrides=brood_overrides,
        spawn_overrides=spawn_overrides,
        take_overrides=take_overrides,
        sample_clock=certify_clock,
    )
    ctx["inspection"] = certify(api, ctx["inspection"]["id"], VET_BRUNO_HEADERS)
    ctx["lot"] = read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    return ctx


def granted_request(
    api: ApiClient,
    ctx: Dict[str, Any],
    water_overrides: Optional[Dict[str, Any]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
    request_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    A water, a request against it, and a plan that has run and granted the request.

    With the default 2400-fish ask against a 5000-fish pool the waterfall grants
    the whole ask, because 2400 is already a whole multiple of the 25-fish unit.
    """
    ctx["water"] = create_water(api, **(water_overrides or {}))
    ctx["request"] = create_stocking_request(
        api, ctx["water"], request_headers, **(request_overrides or {})
    )
    ctx["plan"] = create_allocation_plan(api, ctx["hatchery"], **(plan_overrides or {}))
    attach_request(api, ctx["request"], ctx["plan"], ADMIN_HEADERS)
    ctx["plan"] = run_plan(api, ctx["plan"])
    ctx["request"] = read_request(api, ctx["request"]["id"])
    return ctx


def scheduled_trip(
    api: ApiClient,
    hatchery_overrides: Optional[Dict[str, Any]] = None,
    water_overrides: Optional[Dict[str, Any]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
    unit_overrides: Optional[Dict[str, Any]] = None,
    event_overrides: Optional[Dict[str, Any]] = None,
    trip_clock: str = f.instant(2026, 9, 1, 8),
    request_headers: Optional[Dict[str, str]] = None,
    certify_lot: bool = True,
) -> Dict[str, Any]:
    """
    A trip in `SCHEDULED` status against a certified lot and a granted request.

    The default trip carries 2400 fish at 0.1 lb each, so `planned_load_lbs` is
    240.00, `transport_cost_cents` is 81000 and `oxygen_flow_lpm` is 3.600.

    With `certify_lot=False` the lot is left `UNSCREENED` with a null
    `certificate_expires_at`, which is legal at scheduling because PRD 3.8 checks
    the certificate at load rather than at creation.
    """
    if certify_lot:
        ctx = certified_yearling_lot(api, hatchery_overrides)
    else:
        ctx = yearling_lot(api, hatchery_overrides)
    ctx = granted_request(
        api, ctx, water_overrides, request_overrides, plan_overrides, request_headers
    )
    ctx["unit"] = create_transport_unit(api, ctx["hatchery"], **(unit_overrides or {}))
    set_clock(api, trip_clock)
    ctx["clock"] = trip_clock
    ctx["event"] = create_stocking_event(
        api,
        ctx["hatchery"],
        ctx["request"],
        ctx["lot"]["id"],
        ctx["unit"],
        **(event_overrides or {}),
    )
    return ctx


def in_transit_trip(
    api: ApiClient,
    loaded_at: str = f.instant(2026, 9, 1, 8),
    load_water_temp_c: float = 12.0,
    measured_load_lbs: Any = 240.0,
    **scheduled_kwargs: Any,
) -> Dict[str, Any]:
    """
    A loaded trip in `IN_TRANSIT` status, its truck `IN_USE`.

    At 12.0 degrees the load plan keeps the full 0.50 lb/gal density, so a
    500-gallon tank gives a 250.00 lb volume ceiling and `max_fish_allowed` of
    2500 — comfortably above the 2400 fish the default trip carries.
    """
    ctx = scheduled_trip(api, **scheduled_kwargs)
    ctx["event"] = load_event(
        api,
        ctx["hatchery"],
        ctx["event"]["id"],
        loaded_at,
        load_water_temp_c,
        measured_load_lbs,
    )
    return ctx


def released_trip(
    api: ApiClient,
    arrived_at: str = f.instant(2026, 9, 1, 11),
    site_water_temp_c: float = 4.5,
    tempering_minutes: int = 48,
    transport_mortality_count: Any = 20,
    **in_transit_kwargs: Any,
) -> Dict[str, Any]:
    """
    A released trip, with every reservation in the system settled.

    A 12.0-degree load into 4.5-degree water is a delta of 7.50, which requires
    eight whole one-degree steps and therefore 48 minutes of tempering.
    """
    ctx = in_transit_trip(api, **in_transit_kwargs)
    ctx["event"] = release_event(
        api,
        ctx["hatchery"],
        ctx["event"]["id"],
        arrived_at,
        site_water_temp_c,
        tempering_minutes,
        transport_mortality_count,
    )
    return ctx


# ─── Compliance shortcuts ─────────────────────────────

def log_exceedance(
    api: ApiClient,
    hatchery: Dict[str, Any],
    sampled_at: str = f.instant(2026, 7, 31, 6),
    tss_mg_l: float = 26.5,
    flow_af: float = 0.5,
) -> Dict[str, Any]:
    """
    Log a discharge sample that classifies itself `EXCEEDANCE` against the default
    20.0 mg/L permit limit, without consuming much of the water right.
    """
    return log_effluent_reading(
        api,
        hatchery,
        sampled_at=sampled_at,
        tss_mg_l=tss_mg_l,
        total_phosphorus_mg_l=0.05,
        flow_af=flow_af,
    )


def freeze_station(
    api: ApiClient,
    hatchery: Dict[str, Any],
    first_sampled_at: str = f.instant(2026, 7, 31, 6),
    second_sampled_at: str = f.instant(2026, 7, 31, 12),
) -> Dict[str, Any]:
    """
    Drive a station to `FROZEN` by logging two exceedance samples inside the
    ninety-day rolling window. Returns the station as it reads afterwards.
    """
    log_exceedance(api, hatchery, first_sampled_at)
    log_exceedance(api, hatchery, second_sampled_at)
    return read_hatchery(api, hatchery)


# ─── A contested allocation pool ──────────────────────

def three_request_pool(
    api: ApiClient, allocation_mode: str = MODE_PRIORITY_WATERFALL, **plan_overrides: Any
) -> Dict[str, Any]:
    """
    Three waters, three queued requests and one 1000-fish pool.

    The three destinations are chosen so that the frozen priority scores are
    distinct and the order of service is unambiguous: Antero scores
    0.45*80 + 0.35*90 + 0.20*100.00 + 10 = 97.50, Lost Creek (a `REMOTE` water
    asked for by a member of the public) scores 82.00 * 0.80 + 10 - 5 = 70.60, and
    Tarryall scores 0.45*55 + 0.35*40 + 0.20*100.00 + 10 = 68.75. The asks are 640,
    300 and 210 fish against a pool of 1000 with a 20 per cent public share, so
    every rounding and capping step of PRD 3.7 bites somewhere.

    The plan is left in `DRAFT` with all three requests `QUEUED`; the caller runs
    it, because the run is usually the trigger under test.
    """
    ctx = station_at_rest(
        api,
        name="Golden Springs Hatchery",
        water_source_type=WATER_SOURCE_WELL,
        annual_water_right_af=200.0,
        rearing_capacity_lbs=5000.0,
        oxygen_supply_lpm=40.0,
        annual_budget_cents=90000000,
    )
    ctx["water_p1"] = create_water(
        api,
        name="Antero Reservoir",
        county="Park",
        habitat_suitability_score=80,
        angler_demand_index=90,
        plan_target_count=2000,
    )
    ctx["water_p2"] = create_water(
        api,
        name="Lost Creek Beaver Ponds",
        county="Park",
        water_class=WATER_CLASS_COLDWATER_STREAM,
        habitat_suitability_score=60,
        angler_demand_index=100,
        plan_target_count=2000,
        access_type=ACCESS_REMOTE,
    )
    ctx["water_p3"] = create_water(
        api,
        name="Tarryall Creek",
        county="Park",
        water_class=WATER_CLASS_COLDWATER_STREAM,
        habitat_suitability_score=55,
        angler_demand_index=40,
        plan_target_count=2000,
    )
    ctx["request_a"] = create_stocking_request(
        api,
        ctx["water_p1"],
        BIO_DANA_HEADERS,
        requested_count=640,
        justification="Antero opener, plan target unmet",
    )
    ctx["request_b"] = create_stocking_request(
        api,
        ctx["water_p2"],
        PUB_ERIN_HEADERS,
        requested_count=300,
        justification="Backcountry pond, public petition",
    )
    ctx["request_c"] = create_stocking_request(
        api,
        ctx["water_p3"],
        BIO_FRANK_HEADERS,
        requested_count=210,
        justification="Tarryall put-and-grow supplement",
    )
    ctx["plan"] = create_allocation_plan(
        api,
        ctx["hatchery"],
        available_count=1000,
        allocation_mode=allocation_mode,
        **plan_overrides,
    )
    for key in ("request_a", "request_b", "request_c"):
        attach_request(api, ctx[key], ctx["plan"], ADMIN_HEADERS)
    ctx["plan"] = read_plan(api, ctx["plan"]["id"])
    return ctx
