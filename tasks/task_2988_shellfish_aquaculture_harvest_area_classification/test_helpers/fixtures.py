"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its
preconditions from scratch using only endpoints the PRD declares. All setup
calls go through `get_success_data()` so a broken precondition surfaces as a
clear "Setup step failed" rather than as a confusing assertion failure.

Identity threading: `HatcheryOperator` and `SeafoodDealer` headers are always
built with the acting record's own `id`, because the PRD makes those two roles
record-backed. `FarmOperator` identity is opaque but is recorded as the lease's
`operator_user_id`, so every lease-scoped call in a chain reuses the very
headers that drafted the lease.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH
from .factories import (
    classification_decision_payload,
    date_of,
    dealer_payload,
    dealer_renewal_payload,
    growing_area_payload,
    growout_unit_payload,
    harvest_authorization_payload,
    harvest_lot_payload,
    harvest_vessel_payload,
    hatchery_payload,
    husbandry_log_payload,
    illness_investigation_payload,
    iso,
    lease_decision_payload,
    lease_payload,
    nursery_complete_payload,
    nursery_start_payload,
    plus_days,
    rainfall_event_payload,
    review_payload,
    screening_payload,
    seed_lot_payload,
    ship_payload,
    shipment_payload,
    tag_payload,
    traceback_payload,
    vibrio_control_plan_payload,
    water_sample_payload,
)
from .test_users import (
    TEST_USERS,
    make_hatchery_operator_headers,
    make_seafood_dealer_headers,
)

AUTHORITY = TEST_USERS["authority_headers"]
REVIEWER_A = TEST_USERS["reviewer_headers"]
REVIEWER_B = TEST_USERS["reviewer_b_headers"]
OPERATOR = TEST_USERS["operator_headers"]
OPERATOR_B = TEST_USERS["operator_b_headers"]


# --------------------------------------------------------------------------
# Tier 0 — the logical clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601, headers=None):
    """Set the server's logical clock and return the instant it now reads."""
    data = get_success_data(
        api_client.set_clock(to_iso8601, headers or AUTHORITY)
    )
    return data["current_utc"]


# --------------------------------------------------------------------------
# Tier 1 — growing areas and monitoring data
# --------------------------------------------------------------------------
def create_growing_area(overrides=None):
    payload = growing_area_payload(**(overrides or {}))
    return get_success_data(api_client.create_growing_area(payload, AUTHORITY))


def ingest_water_sample(area_id, overrides=None):
    payload = water_sample_payload(**(overrides or {}))
    return get_success_data(
        api_client.create_water_sample(area_id, payload, AUTHORITY)
    )


def ingest_rainfall_event(area_id, overrides=None):
    payload = rainfall_event_payload(**(overrides or {}))
    return get_success_data(api_client.create_rainfall_event(area_id, payload, AUTHORITY))


def create_area_with_accepted_samples(mpn_values, station_code="ST-1",
                                      start_date=(2026, 7, 1), area_overrides=None):
    """Register an area and ingest one accepted sample per value, one per
    calendar day from `start_date` so no ingest supersedes an earlier row.

    Returns (area_as_last_read, samples).
    """
    area = create_growing_area(area_overrides)
    year, month, day = start_date
    samples = []
    for offset, mpn in enumerate(mpn_values):
        collected = plus_days(f"{year:04d}-{month:02d}-{day:02d}", offset)
        samples.append(get_success_data(api_client.create_water_sample(
            area["id"],
            water_sample_payload(
                station_code=station_code,
                collected_at=collected + "T09:00:00Z",
                fecal_coliform_mpn=mpn,
            ),
            AUTHORITY,
        )))
    area = get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))
    return area, samples


def create_area_with_decision_data(area_overrides=None):
    """An area holding five clean accepted samples, so a classification decision
    clears the minimum-sample rung and reads `eligible_classification` APPROVED.
    """
    return create_area_with_accepted_samples(
        [4, 4, 4, 4, 4], area_overrides=area_overrides,
    )


def record_classification_decision(area, classification, overrides=None):
    payload = classification_decision_payload(
        classification, area["version"], **(overrides or {})
    )
    return get_success_data(
        api_client.create_classification_decision(area["id"], payload, AUTHORITY)
    )


# --------------------------------------------------------------------------
# Tier 1 — hatcheries
# --------------------------------------------------------------------------
def create_hatchery(overrides=None):
    payload = hatchery_payload(**(overrides or {}))
    return get_success_data(api_client.create_hatchery(payload, AUTHORITY))


# --------------------------------------------------------------------------
# Tier 2 — leases through the review fork to APPROVED
# --------------------------------------------------------------------------
def create_draft_lease(area_id, operator_headers=None, overrides=None):
    payload = lease_payload(area_id, **(overrides or {}))
    return get_success_data(
        api_client.create_lease(payload, operator_headers or OPERATOR)
    )


def create_lease_under_review(area_id=None, operator_headers=None, overrides=None):
    headers = operator_headers or OPERATOR
    if area_id is None:
        area_id = create_growing_area()["id"]
    lease = create_draft_lease(area_id, headers, overrides)
    lease = get_success_data(api_client.submit_lease(lease["id"], {}, headers))
    return lease


def create_lease_pending_decision(area_id=None, operator_headers=None,
                                  overrides=None):
    """Draft, submit, and clear both legs with two distinct reviewers so the
    join fires and the lease reaches PENDING_DECISION."""
    headers = operator_headers or OPERATOR
    lease = create_lease_under_review(area_id, headers, overrides)
    get_success_data(api_client.navigation_review(
        lease["id"], review_payload("CLEARED"), REVIEWER_A))
    lease = get_success_data(api_client.environmental_review(
        lease["id"], review_payload("CLEARED"), REVIEWER_B))
    return lease


def create_approved_lease(area_id=None, operator_headers=None,
                          rent_paid_through_date="2027-12-31", overrides=None):
    headers = operator_headers or OPERATOR
    lease = create_lease_pending_decision(area_id, headers, overrides)
    decision = lease_decision_payload("APPROVE")
    if rent_paid_through_date is not None:
        decision["rent_paid_through_date"] = rent_paid_through_date
    lease = get_success_data(
        api_client.decide_lease(lease["id"], decision, AUTHORITY)
    )
    return lease


def create_lease_in_revision_requested(area_id=None, operator_headers=None,
                                       overrides=None):
    """Draft, submit, then record a navigation objection."""
    headers = operator_headers or OPERATOR
    lease = create_lease_under_review(area_id, headers, overrides)
    lease = get_success_data(api_client.navigation_review(
        lease["id"], review_payload("OBJECTION"), REVIEWER_A))
    return lease


# --------------------------------------------------------------------------
# Tier 3 — seed lots walked to a plantable state
# --------------------------------------------------------------------------
def create_received_seed_lot(lease, hatchery=None, overrides=None):
    hatchery = hatchery or create_hatchery()
    payload = seed_lot_payload(hatchery["id"], lease["id"], **(overrides or {}))
    lot = get_success_data(api_client.create_seed_lot(
        payload, make_hatchery_operator_headers(hatchery["id"])))
    return lot, hatchery


def create_screened_seed_lot(lease, hatchery=None, overrides=None,
                             screened_on="2026-06-02"):
    lot, hatchery = create_received_seed_lot(lease, hatchery, overrides)
    lot = get_success_data(api_client.screen_seed_lot(
        lot["id"], screening_payload("NEGATIVE", screened_on), AUTHORITY))
    return lot, hatchery


def create_nursery_seed_lot(lease, hatchery=None, overrides=None,
                            operator_headers=None,
                            nursery_started_on="2026-06-03"):
    lot, hatchery = create_screened_seed_lot(lease, hatchery, overrides)
    lot = get_success_data(api_client.start_nursery(
        lot["id"], nursery_start_payload(nursery_started_on),
        operator_headers or OPERATOR))
    return lot, hatchery


def create_plantable_seed_lot(lease, hatchery=None, overrides=None,
                              operator_headers=None,
                              nursery_started_on="2026-06-03",
                              nursery_completed_on="2026-07-01",
                              surviving_seed_count=None):
    """Walk a seed lot all the way to READY_FOR_PLANTING with a full seed pool."""
    lot, hatchery = create_nursery_seed_lot(
        lease, hatchery, overrides, operator_headers, nursery_started_on)
    if surviving_seed_count is None:
        surviving_seed_count = lot["received_seed_count"]
    lot = get_success_data(api_client.complete_nursery(
        lot["id"],
        nursery_complete_payload(nursery_completed_on, surviving_seed_count),
        operator_headers or OPERATOR))
    return lot, hatchery


# --------------------------------------------------------------------------
# Tier 3 — deployments and husbandry currency
# --------------------------------------------------------------------------
def create_deployed_unit(lease, seed_lot, operator_headers=None, overrides=None):
    payload = growout_unit_payload(lease["id"], seed_lot["id"], **(overrides or {}))
    return get_success_data(
        api_client.create_growout_unit(payload, operator_headers or OPERATOR)
    )


def record_husbandry_log(unit_id, log_type, performed_at,
                         operator_headers=None, overrides=None):
    payload = husbandry_log_payload(log_type, performed_at, **(overrides or {}))
    return get_success_data(
        api_client.create_husbandry_log(unit_id, payload, operator_headers or OPERATOR)
    )


def make_unit_husbandry_current(unit, inspection_at, operator_headers=None,
                                predator_control_at=None):
    """File the logs the two currency tests read. `BOTTOM` gear additionally
    needs a predator-control log, since only enclosing gear passes that test
    automatically."""
    record_husbandry_log(unit["id"], "INSPECTION", inspection_at, operator_headers)
    if unit["gear_type"] == "BOTTOM":
        record_husbandry_log(
            unit["id"], "PREDATOR_CONTROL",
            predator_control_at or inspection_at, operator_headers,
        )
    return get_success_data(
        api_client.get_growout_unit(unit["id"], operator_headers or OPERATOR)
    )


# --------------------------------------------------------------------------
# Tier 3 — vessels, dealers and vibrio plans
# --------------------------------------------------------------------------
def create_vessel(operator_headers=None, overrides=None):
    payload = harvest_vessel_payload(**(overrides or {}))
    return get_success_data(
        api_client.create_harvest_vessel(payload, operator_headers or OPERATOR)
    )


def create_dealer(overrides=None):
    payload = dealer_payload(**(overrides or {}))
    return get_success_data(api_client.create_dealer(payload, AUTHORITY))


def create_listed_dealer(overrides=None, icssl_listed_through="2027-06-30",
                         certified_through="2027-06-30"):
    """Certify a dealer and take it to `LISTED` — the listing dimension moves
    only on a renewal that supplies `icssl_listed_through`."""
    dealer = create_dealer(overrides)
    dealer = get_success_data(api_client.renew_dealer_certification(
        dealer["id"],
        dealer_renewal_payload(
            dealer["version"], certified_through,
            icssl_listed_through=icssl_listed_through,
        ),
        AUTHORITY,
    ))
    return dealer


def publish_vibrio_plan(season_month, overrides=None):
    payload = vibrio_control_plan_payload(season_month, **(overrides or {}))
    return get_success_data(api_client.create_vibrio_control_plan(payload, AUTHORITY))


# --------------------------------------------------------------------------
# Tier 4 — authorizations
# --------------------------------------------------------------------------
def issue_authorization(lease, unit, vessel, dealer, window_start, window_end,
                        operator_headers=None, overrides=None):
    payload = harvest_authorization_payload(
        lease["id"], unit["id"], vessel["id"], dealer["id"],
        window_start, window_end, **(overrides or {}),
    )
    return get_success_data(
        api_client.create_harvest_authorization(payload, operator_headers or OPERATOR)
    )


# --------------------------------------------------------------------------
# Tier 5 — full-chain worlds
#
# The default calendar these builders use:
#   logical clock            2026-08-01T00:00:00Z (the pre-set value)
#   seed shipped_on          2026-06-01, disease certificate issued 2026-05-20
#   screening                2026-06-02
#   nursery                  2026-06-03 -> 2026-07-01 (28 days)
#   deployment              2026-07-05 -> planned retrieval 2026-10-01
#   inspection log           2026-07-25T00:00:00Z (7 days old at the clock)
#   authorization window     2026-08-01T00:00:00Z -> 2026-08-01T12:00:00Z
#   vibrio plan              season_month 8
# --------------------------------------------------------------------------
DEFAULT_CLOCK = CLOCK_EPOCH
DEFAULT_INSPECTION_AT = iso(2026, 7, 25)
DEFAULT_WINDOW_START = iso(2026, 8, 1)
DEFAULT_WINDOW_END = iso(2026, 8, 1, 12)
DEFAULT_HARVEST_CLOCK = iso(2026, 8, 1, 8)
DEFAULT_FIRST_OUT = iso(2026, 8, 1, 1)
DEFAULT_LAST_OUT = iso(2026, 8, 1, 2)
DEFAULT_PLACED_IN_CONTROL = iso(2026, 8, 1, 3)


def setup_authorization_ready(clock=DEFAULT_CLOCK,
                              area_overrides=None,
                              lease_overrides=None,
                              seed_lot_overrides=None,
                              unit_overrides=None,
                              vessel_overrides=None,
                              dealer_overrides=None,
                              plan_overrides=None,
                              season_month=8,
                              inspection_at=DEFAULT_INSPECTION_AT,
                              rent_paid_through_date="2027-12-31",
                              operator_headers=None,
                              publish_plan=True):
    """Area + approved lease + plantable seed + deployed, husbandry-current gear
    + vessel + listed dealer + this season's vibrio plan.

    Returns a dict keyed area, lease, hatchery, seed_lot, unit, vessel, dealer,
    plan, operator_headers, dealer_headers.
    """
    headers = operator_headers or OPERATOR
    set_clock(clock)
    area = create_growing_area(area_overrides)
    lease = create_approved_lease(
        area["id"], headers, rent_paid_through_date, lease_overrides)
    seed_lot, hatchery = create_plantable_seed_lot(
        lease, None, seed_lot_overrides, headers)
    unit = create_deployed_unit(lease, seed_lot, headers, unit_overrides)
    unit = make_unit_husbandry_current(unit, inspection_at, headers)
    vessel = create_vessel(headers, vessel_overrides)
    dealer = create_listed_dealer(dealer_overrides)
    plan = publish_vibrio_plan(season_month, plan_overrides) if publish_plan else None
    return {
        "area": area,
        "lease": lease,
        "hatchery": hatchery,
        "seed_lot": seed_lot,
        "unit": unit,
        "vessel": vessel,
        "dealer": dealer,
        "plan": plan,
        "operator_headers": headers,
        "dealer_headers": make_seafood_dealer_headers(dealer["id"]),
    }


def setup_issued_authorization(window_start=DEFAULT_WINDOW_START,
                              window_end=DEFAULT_WINDOW_END,
                              auth_overrides=None, **world_kwargs):
    """An authorization sitting in ISSUED over a live window."""
    world = setup_authorization_ready(**world_kwargs)
    world["authorization"] = issue_authorization(
        world["lease"], world["unit"], world["vessel"], world["dealer"],
        window_start, window_end, world["operator_headers"], auth_overrides,
    )
    return world


def setup_active_authorization(window_start=DEFAULT_WINDOW_START,
                              window_end=DEFAULT_WINDOW_END,
                              auth_overrides=None, **world_kwargs):
    """An authorization activated inside its window, with the gear in HARVESTING."""
    world = setup_issued_authorization(
        window_start, window_end, auth_overrides, **world_kwargs)
    world["authorization"] = get_success_data(
        api_client.activate_harvest_authorization(
            world["authorization"]["id"], world["operator_headers"])
    )
    world["unit"] = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], world["operator_headers"])
    )
    return world


def land_lot(world, first_out_of_water_at=DEFAULT_FIRST_OUT,
             last_out_of_water_at=DEFAULT_LAST_OUT,
             placed_in_temperature_control_at=DEFAULT_PLACED_IN_CONTROL,
             lot_overrides=None):
    payload = harvest_lot_payload(
        first_out_of_water_at, last_out_of_water_at,
        placed_in_temperature_control_at, **(lot_overrides or {}),
    )
    return get_success_data(api_client.create_harvest_lot(
        world["authorization"]["id"], payload, world["operator_headers"]))


def setup_landed_lot(harvest_clock=DEFAULT_HARVEST_CLOCK,
                     first_out_of_water_at=DEFAULT_FIRST_OUT,
                     last_out_of_water_at=DEFAULT_LAST_OUT,
                     placed_in_temperature_control_at=DEFAULT_PLACED_IN_CONTROL,
                     lot_overrides=None, **world_kwargs):
    """Activate an authorization, advance the clock past the harvest instants,
    then land one lot. Returns the world with `lot` added."""
    world = setup_active_authorization(**world_kwargs)
    if harvest_clock is not None:
        set_clock(harvest_clock)
    world["lot"] = land_lot(
        world, first_out_of_water_at, last_out_of_water_at,
        placed_in_temperature_control_at, lot_overrides,
    )
    return world


def tag_lot(world, lot=None, harvest_date=None, dealer_certification_no=None):
    lot = lot or world["lot"]
    payload = tag_payload(
        harvest_date or date_of(lot["first_out_of_water_at"]),
        dealer_certification_no or world["dealer"]["certification_no"],
    )
    return get_success_data(api_client.tag_harvest_lot(
        lot["id"], payload, world["operator_headers"]))


def setup_tagged_lot(**kwargs):
    world = setup_landed_lot(**kwargs)
    world["lot"] = tag_lot(world)
    return world


def assemble_shipment(world, lot_ids=None, shipment_overrides=None):
    payload = shipment_payload(
        world["dealer"]["id"],
        lot_ids if lot_ids is not None else [world["lot"]["id"]],
        **(shipment_overrides or {}),
    )
    return get_success_data(
        api_client.create_shipment(payload, world["dealer_headers"])
    )


def setup_created_shipment(shipment_overrides=None, **kwargs):
    world = setup_tagged_lot(**kwargs)
    world["shipment"] = assemble_shipment(
        world, None, shipment_overrides)
    return world


def setup_shipped_shipment(shipped_at=None, shipment_overrides=None, **kwargs):
    world = setup_created_shipment(shipment_overrides, **kwargs)
    world["shipment"] = get_success_data(api_client.ship_shipment(
        world["shipment"]["id"],
        ship_payload(shipped_at or DEFAULT_HARVEST_CLOCK),
        world["dealer_headers"],
    ))
    return world


def open_investigation(world, shipment=None, reported_at=None,
                       investigation_overrides=None):
    shipment = shipment or world["shipment"]
    payload = illness_investigation_payload(
        reported_at or DEFAULT_HARVEST_CLOCK, **(investigation_overrides or {})
    )
    return get_success_data(api_client.create_illness_investigation(
        shipment["id"], payload, AUTHORITY))


def setup_open_investigation(investigation_overrides=None, **kwargs):
    world = setup_shipped_shipment(**kwargs)
    world["investigation"] = open_investigation(
        world, None, None, investigation_overrides)
    return world


def setup_investigation_in_traceback(scope_variant="NARROW", **kwargs):
    world = setup_open_investigation(**kwargs)
    world["investigation"] = get_success_data(api_client.run_traceback(
        world["investigation"]["id"], traceback_payload(scope_variant), AUTHORITY))
    return world


# --------------------------------------------------------------------------
# Cascade triggers
# --------------------------------------------------------------------------
def trigger_rainfall_closure(area_id, observed_at, inches_24h=1.50,
                             gauge_code="RG-1"):
    """Record a qualifying rainfall accumulation, which closes an OPEN area and
    runs the four-hop area-closure cascade. Returns the rainfall event."""
    return ingest_rainfall_event(area_id, {
        "gauge_code": gauge_code,
        "observed_at": observed_at,
        "inches_24h": inches_24h,
    })


def reread(world):
    """Re-read every record a cascade could have touched."""
    out = {}
    if "area" in world:
        out["area"] = get_success_data(
            api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    if "lease" in world:
        out["lease"] = get_success_data(
            api_client.get_lease(world["lease"]["id"], AUTHORITY))
    if "seed_lot" in world:
        out["seed_lot"] = get_success_data(
            api_client.get_seed_lot(world["seed_lot"]["id"], AUTHORITY))
    if "unit" in world:
        out["unit"] = get_success_data(
            api_client.get_growout_unit(world["unit"]["id"], AUTHORITY))
    if "vessel" in world:
        out["vessel"] = get_success_data(
            api_client.get_harvest_vessel(world["vessel"]["id"], AUTHORITY))
    if "authorization" in world:
        out["authorization"] = get_success_data(
            api_client.get_harvest_authorization(
                world["authorization"]["id"], AUTHORITY))
    if "lot" in world:
        out["lot"] = get_success_data(
            api_client.get_harvest_lot(world["lot"]["id"], AUTHORITY))
    if "dealer" in world:
        out["dealer"] = get_success_data(
            api_client.get_dealer(world["dealer"]["id"], AUTHORITY))
    if "shipment" in world:
        out["shipment"] = get_success_data(
            api_client.get_shipment(world["shipment"]["id"], AUTHORITY))
    if "investigation" in world:
        out["investigation"] = get_success_data(
            api_client.get_illness_investigation(
                world["investigation"]["id"], AUTHORITY))
    return out


# --------------------------------------------------------------------------
# Tier 6 — the reference world the depth tests share.
#
# One calendar, reused verbatim, so every arithmetic expectation in the depth
# suite is reproducible:
#
#   logical clock at setup      2026-08-01T00:00:00Z
#   growing area                GA-114, threshold 1.00 in / 96 h, 3 clean
#                               samples required, clean limit 14.0 MPN
#   vibrio plan                 season_month 8, 300 min, high temp 23.0 C,
#                               reduction 60 min
#   hatchery                    NCSP-77, certificate through 2027-03-31,
#                               pathogen-free for CRASSOSTREA_VIRGINICA
#   dealer                      NC-1234-SS, certified through 2027-06-30,
#                               taken to LISTED by a renewal
#   vessel                      NC-4410, MECHANICAL, capacity 2
#   lease                       L-2988-01, plots P1/P2/P3, BOTTOM and
#                               RACK_AND_BAG, 200 authorized gear units,
#                               rent paid through 2026-12-31
#   seed lot                    100 000 received, shipped 2026-04-01,
#                               disease certificate issued 2026-03-15,
#                               screened 2026-04-03, nursery 2026-04-05 ->
#                               2026-05-01, 60 000 surviving (60.00 %)
#   grow-out unit               plot P1, BOTTOM, 40 gear units, 25 000 seed,
#                               deployed 2026-05-05, planned 2026-10-15,
#                               inspected 2026-07-20T12:00:00Z, predator
#                               control 2026-07-20T13:00:00Z
#   authorization               window 2026-08-10T06:00:00Z -> 18:00:00Z,
#                               600 projected bushels
#   harvest                     activated at 2026-08-10T06:00:00Z, clock moved
#                               to 11:00:00Z, first out 06:00, last out 08:00,
#                               placed in temperature control 10:30
# --------------------------------------------------------------------------
DW_CLOCK = iso(2026, 8, 1)
DW_AREA_CODE = "GA-114"
DW_LEASE_CODE = "L-2988-01"
DW_DEALER_CERT_NO = "NC-1234-SS"
DW_INSPECTION_AT = iso(2026, 7, 20, 12)
DW_PREDATOR_AT = iso(2026, 7, 20, 13)
DW_WINDOW_START = iso(2026, 8, 10, 6)
DW_WINDOW_END = iso(2026, 8, 10, 18)
DW_ACTIVATE_CLOCK = iso(2026, 8, 10, 6)
DW_HARVEST_CLOCK = iso(2026, 8, 10, 11)
DW_FIRST_OUT = iso(2026, 8, 10, 6)
DW_LAST_OUT = iso(2026, 8, 10, 8)
DW_PLACED_IN_CONTROL = iso(2026, 8, 10, 10, 30)

DW_STAGES = (
    "area", "lease", "seed", "unit", "issued", "active", "landed", "tagged",
    "shipment", "shipped",
)


def dw_area_payload(**overrides):
    payload = {
        "code": DW_AREA_CODE,
        "water_body": "Pamlico Sound",
        "rainfall_closure_threshold_in": 1.00,
        "rainfall_closure_hours": 96,
        "reopen_sample_count_required": 3,
        "clean_sample_mpn_limit": 14.0,
        "conditional_management_plan_on_file": False,
    }
    payload.update(overrides)
    return payload


def dw_lease_payload_overrides(**overrides):
    payload = {
        "lease_code": DW_LEASE_CODE,
        "requested_acreage": 5.0,
        "plot_codes": ["P1", "P2", "P3"],
        "gear_types_permitted": ["BOTTOM", "RACK_AND_BAG"],
        "authorized_gear_units": 200,
    }
    payload.update(overrides)
    return payload


def dw_hatchery_payload(**overrides):
    payload = {
        "name": "Sound Hatchery",
        "state_code": "NC",
        "ncsp_certificate_no": "NCSP-77",
        "certificate_expires_on": "2027-03-31",
        "pathogen_free_species": ["CRASSOSTREA_VIRGINICA"],
    }
    payload.update(overrides)
    return payload


def dw_dealer_payload(**overrides):
    payload = {
        "name": "Coastal Shellstock",
        "state_code": "NC",
        "certification_category": "SHELLSTOCK_SHIPPER",
        "certification_no": DW_DEALER_CERT_NO,
        "certified_through": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def dw_vessel_payload(**overrides):
    payload = {
        "name": "Miss Pamlico",
        "registration_no": "NC-4410",
        "refrigeration_type": "MECHANICAL",
        "concurrent_authorization_capacity": 2,
    }
    payload.update(overrides)
    return payload


def dw_plan_payload_overrides(**overrides):
    payload = {
        "max_time_to_temperature_minutes": 300,
        "high_water_temp_c": 23.0,
        "high_temp_reduction_minutes": 60,
    }
    payload.update(overrides)
    return payload


def dw_seed_lot_payload_overrides(**overrides):
    payload = {
        "species": "CRASSOSTREA_VIRGINICA",
        "received_seed_count": 100000,
        "disease_certificate_no": "DC-9001",
        "disease_cert_issued_on": "2026-03-15",
        "shipped_on": "2026-04-01",
    }
    payload.update(overrides)
    return payload


def dw_unit_payload_overrides(**overrides):
    payload = {
        "plot_code": "P1",
        "gear_type": "BOTTOM",
        "gear_units": 40,
        "seed_count_planted": 25000,
        "deployed_on": "2026-05-05",
        "planned_retrieval_on": "2026-10-15",
    }
    payload.update(overrides)
    return payload


def dw_auth_payload_overrides(**overrides):
    payload = {"projected_bushels": 600}
    payload.update(overrides)
    return payload


def dw_lot_payload_overrides(**overrides):
    payload = {"bushels": 10, "water_temp_c": 24.0}
    payload.update(overrides)
    return payload


def dw_walk_seed_lot(lease, hatchery, seed_stage="plantable",
                     operator_headers=None, overrides=None,
                     screened_on="2026-04-03",
                     nursery_started_on="2026-04-05",
                     nursery_completed_on="2026-05-01",
                     surviving_seed_count=60000):
    """Walk one seed lot along the reference calendar as far as `seed_stage`."""
    headers = operator_headers or OPERATOR
    payload = seed_lot_payload(
        hatchery["id"], lease["id"],
        **dw_seed_lot_payload_overrides(**(overrides or {})),
    )
    lot = get_success_data(api_client.create_seed_lot(
        payload, make_hatchery_operator_headers(hatchery["id"])))
    if seed_stage == "received":
        return lot
    lot = get_success_data(api_client.screen_seed_lot(
        lot["id"], screening_payload("NEGATIVE", screened_on), AUTHORITY))
    if seed_stage == "screened":
        return lot
    lot = get_success_data(api_client.start_nursery(
        lot["id"], nursery_start_payload(nursery_started_on), headers))
    if seed_stage == "nursery":
        return lot
    lot = get_success_data(api_client.complete_nursery(
        lot["id"],
        nursery_complete_payload(nursery_completed_on, surviving_seed_count),
        headers))
    return lot


def dw_deploy_unit(lease, seed_lot, operator_headers=None, overrides=None,
                   husbandry=True, inspection_at=DW_INSPECTION_AT,
                   predator_control_at=DW_PREDATOR_AT):
    """Deploy one grow-out unit on the reference calendar and, unless asked
    otherwise, file the inspection and predator-control logs that the two
    husbandry currency tests read."""
    headers = operator_headers or OPERATOR
    payload = growout_unit_payload(
        lease["id"], seed_lot["id"],
        **dw_unit_payload_overrides(**(overrides or {})),
    )
    unit = get_success_data(api_client.create_growout_unit(payload, headers))
    if husbandry:
        if inspection_at is not None:
            record_husbandry_log(unit["id"], "INSPECTION", inspection_at, headers)
        if predator_control_at is not None:
            record_husbandry_log(
                unit["id"], "PREDATOR_CONTROL", predator_control_at, headers,
                {"control_method": "NETTING"},
            )
        unit = get_success_data(api_client.get_growout_unit(unit["id"], headers))
    return unit


def design_world(stage="unit",
                 clock=DW_CLOCK,
                 area_overrides=None,
                 lease_overrides=None,
                 rent_paid_through_date="2026-12-31",
                 hatchery_overrides=None,
                 dealer_overrides=None,
                 list_dealer=True,
                 vessel_overrides=None,
                 publish_plan=True,
                 season_month=8,
                 plan_overrides=None,
                 seed_stage="plantable",
                 seed_lot_overrides=None,
                 surviving_seed_count=60000,
                 unit_overrides=None,
                 husbandry=True,
                 inspection_at=DW_INSPECTION_AT,
                 predator_control_at=DW_PREDATOR_AT,
                 window_start=DW_WINDOW_START,
                 window_end=DW_WINDOW_END,
                 auth_overrides=None,
                 activate_clock=DW_ACTIVATE_CLOCK,
                 harvest_clock=DW_HARVEST_CLOCK,
                 first_out_of_water_at=DW_FIRST_OUT,
                 last_out_of_water_at=DW_LAST_OUT,
                 placed_in_temperature_control_at=DW_PLACED_IN_CONTROL,
                 lot_overrides=None,
                 shipment_overrides=None,
                 shipped_at=None,
                 sample_mpns=None,
                 sample_start_date="2026-07-01",
                 sample_station_code="ST-1",
                 classification=None,
                 classification_overrides=None,
                 operator_headers=None):
    """Build the reference world up to and including `stage`.

    Stages, in order: area, lease, seed, unit, issued, active, landed, tagged,
    shipment, shipped. Returns a dict whose keys are the records built so far
    plus `operator_headers` and, once a dealer exists, `dealer_headers`.

    `sample_mpns` ingests one accepted water sample per calendar day starting at
    `sample_start_date`, which is how an area earns the five accepted samples a
    classification decision needs; `classification` then records a decision at
    the area's current version.
    """
    if stage not in DW_STAGES:
        raise ValueError(f"unknown design_world stage: {stage}")
    depth = DW_STAGES.index(stage)
    headers = operator_headers or OPERATOR
    world = {"operator_headers": headers}

    if clock is not None:
        set_clock(clock)
    world["area"] = create_growing_area(dw_area_payload(**(area_overrides or {})))
    if sample_mpns:
        world["samples"] = [
            ingest_water_sample(world["area"]["id"], {
                "station_code": sample_station_code,
                "collected_at": plus_days(sample_start_date, offset) + "T09:00:00Z",
                "fecal_coliform_mpn": mpn,
            })
            for offset, mpn in enumerate(sample_mpns)
        ]
        world["area"] = get_success_data(
            api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    if classification is not None:
        world["area"] = record_classification_decision(
            world["area"], classification, classification_overrides)
    if depth == 0:
        return world

    world["lease"] = create_approved_lease(
        world["area"]["id"], headers, rent_paid_through_date,
        dw_lease_payload_overrides(**(lease_overrides or {})),
    )
    if depth == 1:
        return world

    if publish_plan:
        world["plan"] = publish_vibrio_plan(
            season_month, dw_plan_payload_overrides(**(plan_overrides or {})))
    world["hatchery"] = create_hatchery(
        dw_hatchery_payload(**(hatchery_overrides or {})))
    world["seed_lot"] = dw_walk_seed_lot(
        world["lease"], world["hatchery"], seed_stage, headers,
        seed_lot_overrides, surviving_seed_count=surviving_seed_count,
    )
    if depth == 2:
        return world

    world["vessel"] = create_vessel(
        headers, dw_vessel_payload(**(vessel_overrides or {})))
    dealer_body = dw_dealer_payload(**(dealer_overrides or {}))
    if list_dealer:
        world["dealer"] = create_listed_dealer(dealer_body)
    else:
        world["dealer"] = create_dealer(dealer_body)
    world["dealer_headers"] = make_seafood_dealer_headers(world["dealer"]["id"])
    world["unit"] = dw_deploy_unit(
        world["lease"], world["seed_lot"], headers, unit_overrides,
        husbandry, inspection_at, predator_control_at,
    )
    if depth == 3:
        return world

    if activate_clock is not None:
        set_clock(activate_clock)
    world["authorization"] = issue_authorization(
        world["lease"], world["unit"], world["vessel"], world["dealer"],
        window_start, window_end, headers,
        dw_auth_payload_overrides(**(auth_overrides or {})),
    )
    if depth == 4:
        return world

    world["authorization"] = get_success_data(
        api_client.activate_harvest_authorization(
            world["authorization"]["id"], headers))
    world["unit"] = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], headers))
    if depth == 5:
        return world

    if harvest_clock is not None:
        set_clock(harvest_clock)
    world["lot"] = land_lot(
        world, first_out_of_water_at, last_out_of_water_at,
        placed_in_temperature_control_at,
        dw_lot_payload_overrides(**(lot_overrides or {})),
    )
    if depth == 6:
        return world

    world["lot"] = tag_lot(world)
    if depth == 7:
        return world

    world["shipment"] = assemble_shipment(world, None, shipment_overrides)
    if depth == 8:
        return world

    world["shipment"] = get_success_data(api_client.ship_shipment(
        world["shipment"]["id"],
        ship_payload(shipped_at or harvest_clock or DW_HARVEST_CLOCK),
        world["dealer_headers"],
    ))
    world["lot"] = get_success_data(
        api_client.get_harvest_lot(world["lot"]["id"], headers))
    return world


def dw_land_lot(world, first_out_of_water_at=DW_FIRST_OUT,
                last_out_of_water_at=DW_LAST_OUT,
                placed_in_temperature_control_at=DW_PLACED_IN_CONTROL,
                authorization=None, **lot_overrides):
    """Land one more lot on the reference calendar, optionally under a second
    authorization."""
    target = dict(world)
    if authorization is not None:
        target["authorization"] = authorization
    return land_lot(
        target, first_out_of_water_at, last_out_of_water_at,
        placed_in_temperature_control_at,
        dw_lot_payload_overrides(**lot_overrides),
    )


def dw_tag_lot(world, lot):
    """Tag a specific lot with the reference dealer's certification number and
    the lot's own harvest date."""
    return tag_lot(world, lot)


def dw_assemble_shipment(world, lot_ids, **shipment_overrides):
    return assemble_shipment(world, lot_ids, shipment_overrides)


def dw_ship(world, shipment, shipped_at):
    return get_success_data(api_client.ship_shipment(
        shipment["id"], ship_payload(shipped_at), world["dealer_headers"]))


def dw_ingest_clean_samples(area_id, collected_dates, mpn=5, station_code="ST-1"):
    """Ingest one accepted, clean sample per calendar date."""
    return [
        ingest_water_sample(area_id, {
            "station_code": station_code,
            "collected_at": day + "T09:00:00Z",
            "fecal_coliform_mpn": mpn,
        })
        for day in collected_dates
    ]
