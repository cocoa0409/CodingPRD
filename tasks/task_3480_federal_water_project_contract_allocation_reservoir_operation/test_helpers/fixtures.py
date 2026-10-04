"""Composite fixtures that walk the API to a wanted state.

Every test starts against an empty deployment - the harness restarts the API
server before each test - so each test has to build the world it needs from
scratch, through the public API only. These helpers do that walking and
return the entities, identifiers and observed versions the test then asserts
against. They are organised from the simplest to the most far-reaching:

  Tier 1  atomic steps: one public API call each, with the correct role
  Tier 2  project seeding: districts, contracts, the singleton reservoir
  Tier 3  the water year: open it, post hydrology, publish announcements
  Tier 4  domain scenarios: shortage sharing, compliance holds, revenue
          periods, delivery recording, the transfer review loop
  Tier 5  terminal states: executed transfers, closed years, settled periods

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error.

Composite setups return a ``world`` - a plain dict with these keys:

  reservoir            the singleton project reservoir (or None)
  district_sr/jr/tp    the senior, junior and third-party districts
  contract_sr/jr       C-100 SENIOR 6,000 af on district_sr, C-200 JUNIOR
                       4,000 af on district_jr (or the settlement trio when
                       the world was built with contract_plan="settlement";
                       contract_tp exists only when the plan includes it)
  year                 the water year, refreshed after every mutation
  year_initial_version the year version observed at creation (1)
  announcement         the currently PUBLISHED announcement (or None)
  line_sr/jr(/tp)      the announcement's allocation line per contract
  admin_headers / operator_headers / hydrology_headers / env_headers /
  finance_headers / director_headers
                       ready-made header dicts for the six opaque roles
  mgr_sr/jr/tp_headers DistrictManager headers bound to each district's id -
                       the only headers ownership-gated calls may use
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CLOCK_FEBRUARY_03_10,
    CLOCK_FEBRUARY_05,
    CLOCK_JANUARY,
    CLOCK_JANUARY_20,
    CLOCK_OCTOBER,
    CONTRACT_A,
    CONTRACT_B,
    CONTRACT_C,
    CONTRACT_JR,
    CONTRACT_SR,
    CONTRACT_TP,
    OBSERVED_ON_BASE,
    PERIOD_FEBRUARY,
    QUORUM_TWO,
    RATE_STANDARD,
    RUNOFF_BASE,
    SNOWPACK_BASE,
    YEAR_LABEL,
)
from .test_users import (
    ENVIRONMENTAL_OFFICER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    HYDROLOGY_OFFICER_HEADERS,
    RECLAMATION_OPERATOR_HEADERS,
    REGIONAL_DIRECTOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    make_district_manager_headers,
)

# The reader role for plain lookups: every role may read, so the operations
# desk's headers are the conventional choice.
READ_HEADERS = RECLAMATION_OPERATOR_HEADERS


def rows(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read a list response as (rows, meta)."""
    return validate_paginated(response)


# ═══════════════════════════════════════════════════════════════════════════
# Tier 1: atomic steps - one public API call each
# ═══════════════════════════════════════════════════════════════════════════

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock and return what the write reported."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), SYSTEM_ADMIN_HEADERS))


def create_district(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_district(f.district_payload(**overrides), SYSTEM_ADMIN_HEADERS))


def create_contract(api: ApiClient, district_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_contract(f.contract_payload(district_id, **overrides), SYSTEM_ADMIN_HEADERS))


def get_contract(api: ApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contract(contract_id, READ_HEADERS))


def suspend_contract(api: ApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.suspend_contract(contract_id, FINANCE_OFFICER_HEADERS))


def create_reservoir(api: ApiClient, profile: str = "small", **overrides: Any) -> Dict[str, Any]:
    """Create the singleton project reservoir from one of the three named
    profiles ("small", "big", "flood"), with any field overridable."""
    builders = {
        "small": f.small_reservoir_payload,
        "big": f.big_reservoir_payload,
        "flood": f.flood_reservoir_payload,
    }
    return get_success_data(api.create_reservoir(builders[profile](**overrides), SYSTEM_ADMIN_HEADERS))


def get_reservoir(api: ApiClient, reservoir_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_reservoir(reservoir_id, READ_HEADERS))


def create_water_year(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_water_year(f.water_year_payload(**overrides), RECLAMATION_OPERATOR_HEADERS))


def get_water_year(api: ApiClient, year_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_water_year(year_id, READ_HEADERS))


def finalize_water_year(api: ApiClient, year_id: str) -> Dict[str, Any]:
    return get_success_data(api.finalize_water_year(year_id, RECLAMATION_OPERATOR_HEADERS))


def post_observation(api: ApiClient, year_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_hydrology_observation(year_id, payload, HYDROLOGY_OFFICER_HEADERS))


def create_announcement(api: ApiClient, year_id: str, expected_water_year_version: int) -> Dict[str, Any]:
    """Create a DRAFT announcement; the version pins the OCC check (PRD §2.7)."""
    return get_success_data(
        api.create_allocation_announcement(
            year_id, f.announcement_payload(expected_water_year_version), RECLAMATION_OPERATOR_HEADERS
        )
    )


def publish_announcement(api: ApiClient, announcement_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_allocation_announcement(announcement_id, RECLAMATION_OPERATOR_HEADERS))


def list_announcements(api: ApiClient, year_id: str, **params: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return rows(api.list_allocation_announcements(year_id, READ_HEADERS, params or None))


def find_announcement(api: ApiClient, year_id: str, announcement_id: str) -> Dict[str, Any]:
    """Read one announcement back; the contract exposes announcement reads only
    through the per-year list, so this filters that list by id."""
    found, _ = list_announcements(api, year_id, limit=100)
    for ann in found:
        if ann["id"] == announcement_id:
            return ann
    raise AssertionError(f"announcement {announcement_id} not found on year {year_id}")


def get_line(api: ApiClient, line_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_allocation_line(line_id, READ_HEADERS))


def find_line(api: ApiClient, announcement_id: str, contract_id: str) -> Dict[str, Any]:
    found, _ = rows(
        api.list_allocation_lines(
            READ_HEADERS, {"announcement_id": announcement_id, "contract_id": contract_id}
        )
    )
    assert len(found) == 1, f"expected exactly one line for ({announcement_id}, {contract_id}), got {len(found)}"
    return found[0]


def create_release(api: ApiClient, reservoir_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_release_order(reservoir_id, f.release_order_payload(**overrides), RECLAMATION_OPERATOR_HEADERS)
    )


def execute_release(api: ApiClient, release_id: str) -> Dict[str, Any]:
    return get_success_data(api.execute_release_order(release_id, RECLAMATION_OPERATOR_HEADERS))


def find_release(api: ApiClient, reservoir_id: str, release_id: str) -> Dict[str, Any]:
    """Read one release back; release reads come through the per-reservoir list."""
    found, _ = rows(api.list_release_orders(reservoir_id, READ_HEADERS, {"limit": 100}))
    for rel in found:
        if rel["id"] == release_id:
            return rel
    raise AssertionError(f"release {release_id} not found on reservoir {reservoir_id}")


def create_constraint(api: ApiClient, reservoir_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        api.create_environmental_constraint(reservoir_id, payload, ENVIRONMENTAL_OFFICER_HEADERS)
    )


def list_constraints(api: ApiClient, reservoir_id: str, **params: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return rows(api.list_environmental_constraints(reservoir_id, READ_HEADERS, params or None))


def list_incidents(api: ApiClient, **params: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return rows(api.list_compliance_incidents(READ_HEADERS, params or None))


def get_incident(api: ApiClient, incident_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_compliance_incident(incident_id, READ_HEADERS))


def find_open_incident(api: ApiClient, reservoir_id: Optional[str] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {"status": "OPEN"}
    if reservoir_id:
        params["reservoir_id"] = reservoir_id
    found, _ = list_incidents(api, **params)
    assert len(found) >= 1, "expected at least one OPEN compliance incident"
    return found[0]


def resolve_incident(api: ApiClient, incident_id: str, resolution: str = "FLOW_RESTORED") -> Dict[str, Any]:
    return get_success_data(
        api.resolve_compliance_incident(
            incident_id, f.resolve_incident_payload(resolution), ENVIRONMENTAL_OFFICER_HEADERS
        )
    )


def create_delivery_order(
    api: ApiClient, contract_id: str, water_year_id: str, ordered_af: int, district_id: str
) -> Dict[str, Any]:
    """Order water; the caller must own the contract, so the manager headers
    are bound to the district that owns it (PRD §3.6)."""
    return get_success_data(
        api.create_delivery_order(
            f.delivery_order_payload(contract_id, water_year_id, ordered_af),
            make_district_manager_headers(district_id),
        )
    )


def record_delivery(api: ApiClient, order_id: str, delivered_af: int) -> Dict[str, Any]:
    return get_success_data(
        api.record_delivery(order_id, f.record_delivery_payload(delivered_af), RECLAMATION_OPERATOR_HEADERS)
    )


def get_delivery_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_delivery_order(order_id, READ_HEADERS))


def list_delivery_orders(api: ApiClient, **params: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return rows(api.list_delivery_orders(READ_HEADERS, params or None))


def create_revenue_period(
    api: ApiClient, reservoir_id: str, period_month: str = PERIOD_FEBRUARY, rate_cents_per_mwh: int = RATE_STANDARD
) -> Dict[str, Any]:
    return get_success_data(
        api.create_revenue_period(
            f.revenue_period_payload(reservoir_id, period_month, rate_cents_per_mwh),
            FINANCE_OFFICER_HEADERS,
        )
    )


def settle_period(api: ApiClient, period_id: str) -> Dict[str, Any]:
    return get_success_data(api.settle_revenue_period(period_id, FINANCE_OFFICER_HEADERS))


def create_transfer(
    api: ApiClient,
    from_contract_id: str,
    to_contract_id: str,
    water_year_id: str,
    quantity_af: int,
    seller_district_id: str,
    price_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Propose a transfer as the seller district (PRD §3.8)."""
    return get_success_data(
        api.create_transfer_request(
            f.transfer_payload(from_contract_id, to_contract_id, water_year_id, quantity_af, price_cents),
            make_district_manager_headers(seller_district_id),
        )
    )


def get_transfer(api: ApiClient, transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_transfer_request(transfer_id, READ_HEADERS))


def decide_transfer(api: ApiClient, transfer_id: str, decision: str, rationale: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api.decide_transfer_request(transfer_id, f.decide_payload(decision, rationale), REGIONAL_DIRECTOR_HEADERS)
    )


def resubmit_transfer(
    api: ApiClient,
    transfer_id: str,
    seller_district_id: str,
    quantity_af: Optional[int] = None,
    price_cents: Optional[int] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.resubmit_transfer_request(
            transfer_id,
            f.resubmit_payload(quantity_af, price_cents),
            make_district_manager_headers(seller_district_id),
        )
    )


def execute_transfer(api: ApiClient, transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api.execute_transfer_request(transfer_id, RECLAMATION_OPERATOR_HEADERS))


def file_review(
    api: ApiClient, transfer_id: str, claimed_impact_af: int, basis: str, reviewer_district_id: str
) -> Dict[str, Any]:
    """File a third-party impact review; the reviewer district is taken from
    the caller's X-User-ID (PRD §3.8)."""
    return get_success_data(
        api.create_impact_review(
            transfer_id,
            f.impact_review_payload(claimed_impact_af, basis),
            make_district_manager_headers(reviewer_district_id),
        )
    )


def get_review(api: ApiClient, review_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_impact_review(review_id, READ_HEADERS))


def resolve_review(api: ApiClient, review_id: str, outcome: str, rationale: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api.resolve_impact_review(review_id, f.resolve_review_payload(outcome, rationale), REGIONAL_DIRECTOR_HEADERS)
    )


def create_agreement(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_shortage_agreement(f.shortage_agreement_payload(**overrides), RECLAMATION_OPERATOR_HEADERS)
    )


def get_agreement(api: ApiClient, agreement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_shortage_agreement(agreement_id, READ_HEADERS))


def ratify_agreement(api: ApiClient, agreement_id: str, district_id: str) -> Dict[str, Any]:
    """Ratify as the calling district; the signatory appended is the caller's
    X-User-ID district (PRD §3.4)."""
    return get_success_data(
        api.ratify_shortage_agreement(agreement_id, make_district_manager_headers(district_id))
    )


def activate_agreement(api: ApiClient, agreement_id: str, water_year_label: int = YEAR_LABEL) -> Dict[str, Any]:
    return get_success_data(
        api.activate_shortage_agreement(
            agreement_id, f.activate_agreement_payload(water_year_label), REGIONAL_DIRECTOR_HEADERS
        )
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2: project seeding
# ═══════════════════════════════════════════════════════════════════════════

def seed_districts(api: ApiClient) -> Dict[str, Dict[str, Any]]:
    """The three canonical districts: senior, junior and third-party."""
    return {
        "sr": get_success_data(api.create_district(f.senior_district_payload(), SYSTEM_ADMIN_HEADERS)),
        "jr": get_success_data(api.create_district(f.junior_district_payload(), SYSTEM_ADMIN_HEADERS)),
        "tp": get_success_data(api.create_district(f.third_party_district_payload(), SYSTEM_ADMIN_HEADERS)),
    }


# Contract plans: which contracts are executed on which district.
_CONTRACT_PLANS: Dict[str, Sequence[Tuple[str, str, Dict[str, Any]]]] = {
    # C-100 SENIOR 6,000 af on the senior district, C-200 JUNIOR 4,000 af on
    # the junior district.
    "standard": (("contract_sr", "sr", CONTRACT_SR), ("contract_jr", "jr", CONTRACT_JR)),
    "standard_with_third": (
        ("contract_sr", "sr", CONTRACT_SR),
        ("contract_jr", "jr", CONTRACT_JR),
        ("contract_tp", "tp", CONTRACT_TP),
    ),
    # The repayment-settlement trio: obligations 7M / 5M / 3M cents.
    "settlement": (
        ("contract_sr", "sr", CONTRACT_A),
        ("contract_jr", "jr", CONTRACT_B),
        ("contract_tp", "tp", CONTRACT_C),
    ),
}


def setup_project(
    api: ApiClient,
    reservoir_profile: Optional[str] = "small",
    contract_plan: Optional[str] = "standard",
    clock: str = CLOCK_OCTOBER,
) -> Dict[str, Any]:
    """Seed the standing world: the clock, the singleton reservoir (unless the
    profile is None), the three districts, and the contracts named by the plan
    (unless the plan is None). Returns the world dict."""
    set_clock(api, clock)

    world: Dict[str, Any] = {
        "reservoir": create_reservoir(api, reservoir_profile) if reservoir_profile else None,
        "announcement": None,
        "year": None,
        "line_sr": None,
        "line_jr": None,
        "line_tp": None,
        "admin_headers": SYSTEM_ADMIN_HEADERS,
        "operator_headers": RECLAMATION_OPERATOR_HEADERS,
        "hydrology_headers": HYDROLOGY_OFFICER_HEADERS,
        "env_headers": ENVIRONMENTAL_OFFICER_HEADERS,
        "finance_headers": FINANCE_OFFICER_HEADERS,
        "director_headers": REGIONAL_DIRECTOR_HEADERS,
    }

    districts = seed_districts(api)
    world["district_sr"] = districts["sr"]
    world["district_jr"] = districts["jr"]
    world["district_tp"] = districts["tp"]
    world["mgr_sr_headers"] = make_district_manager_headers(districts["sr"]["id"])
    world["mgr_jr_headers"] = make_district_manager_headers(districts["jr"]["id"])
    world["mgr_tp_headers"] = make_district_manager_headers(districts["tp"]["id"])

    if contract_plan:
        for key, district_key, spec in _CONTRACT_PLANS[contract_plan]:
            world[key] = create_contract(api, districts[district_key]["id"], **spec)

    return world


# ═══════════════════════════════════════════════════════════════════════════
# Tier 3: the water year - open, observe, announce, publish, revise
# ═══════════════════════════════════════════════════════════════════════════

def open_year(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Open the operating year and record it (and its initial version) on the world."""
    year = create_water_year(api, **overrides)
    world["year"] = year
    world["year_initial_version"] = year["version"]
    return world


def refresh_year(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    world["year"] = get_water_year(api, world["year"]["id"])
    return world["year"]


def refresh_reservoir(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    world["reservoir"] = get_reservoir(api, world["reservoir"]["id"])
    return world["reservoir"]


def refresh_contracts(api: ApiClient, world: Dict[str, Any]) -> None:
    for key in ("contract_sr", "contract_jr", "contract_tp"):
        if world.get(key):
            world[key] = get_contract(api, world[key]["id"])


def refresh_lines(api: ApiClient, world: Dict[str, Any]) -> None:
    """Re-read the current announcement's lines for every contract in the world."""
    if not world.get("announcement"):
        return
    pairs = (("contract_sr", "line_sr"), ("contract_jr", "line_jr"), ("contract_tp", "line_tp"))
    for contract_key, line_key in pairs:
        if world.get(contract_key):
            world[line_key] = find_line(api, world["announcement"]["id"], world[contract_key]["id"])


def post_hydrology(
    api: ApiClient,
    world: Dict[str, Any],
    snowpack: Optional[int] = SNOWPACK_BASE,
    runoff: Optional[int] = RUNOFF_BASE,
    inflow: Optional[int] = None,
    observed_on: str = OBSERVED_ON_BASE,
) -> None:
    """Post the year's hydrology. Any of the three postings can be skipped by
    passing None; the latest observed_on governs forecast use (PRD §3.2)."""
    year_id = world["year"]["id"]
    if snowpack is not None:
        post_observation(api, year_id, f.snowpack_payload(snowpack, observed_on))
    if runoff is not None:
        post_observation(api, year_id, f.runoff_forecast_payload(runoff, observed_on))
    if inflow is not None:
        post_observation(api, year_id, f.inflow_payload(inflow, observed_on))


def publish_new_announcement(api: ApiClient, world: Dict[str, Any], clock: Optional[str] = None) -> Dict[str, Any]:
    """Create a DRAFT at the year's current version and publish it, then refresh
    the world's year, current announcement and per-contract lines."""
    if clock is not None:
        set_clock(api, clock)
    year = refresh_year(api, world)
    draft = create_announcement(api, year["id"], year["version"])
    world["announcement"] = publish_announcement(api, draft["id"])
    refresh_year(api, world)
    refresh_lines(api, world)
    return world["announcement"]


def setup_open_year(
    api: ApiClient,
    reservoir_profile: Optional[str] = "small",
    contract_plan: Optional[str] = "standard",
    snowpack: Optional[int] = SNOWPACK_BASE,
    runoff: Optional[int] = RUNOFF_BASE,
    inflow: Optional[int] = None,
    observed_on: str = OBSERVED_ON_BASE,
    hydrology_clock: str = CLOCK_JANUARY,
    seed_clock: str = CLOCK_OCTOBER,
    **year_overrides: Any,
) -> Dict[str, Any]:
    """Project + year + hydrology, but no announcement yet: the year is OPEN."""
    world = setup_project(api, reservoir_profile, contract_plan, clock=seed_clock)
    open_year(api, world, **year_overrides)
    set_clock(api, hydrology_clock)
    post_hydrology(api, world, snowpack, runoff, inflow, observed_on)
    return world


def setup_announced_year(
    api: ApiClient,
    reservoir_profile: Optional[str] = "small",
    contract_plan: Optional[str] = "standard",
    snowpack: Optional[int] = SNOWPACK_BASE,
    runoff: Optional[int] = RUNOFF_BASE,
    inflow: Optional[int] = None,
    observed_on: str = OBSERVED_ON_BASE,
    publish_clock: str = CLOCK_JANUARY,
    seed_clock: str = CLOCK_OCTOBER,
    **year_overrides: Any,
) -> Dict[str, Any]:
    """The workhorse fixture: project, year, hydrology, and a first published
    announcement. With the defaults (small reservoir, snowpack 80, runoff
    forecast 5,000, January publish) the declared supply is 7,500 acre-feet,
    the tier is NONE, and the waterfall lines are 6,000 senior / 1,500 junior.
    """
    world = setup_open_year(
        api,
        reservoir_profile,
        contract_plan,
        snowpack,
        runoff,
        inflow,
        observed_on,
        hydrology_clock=publish_clock,
        seed_clock=seed_clock,
        **year_overrides,
    )
    publish_new_announcement(api, world)
    return world


def publish_revision(
    api: ApiClient,
    world: Dict[str, Any],
    snowpack: Optional[int] = None,
    runoff: Optional[int] = None,
    observed_on: str = "2027-01-20T00:00:00Z",
    clock: Optional[str] = CLOCK_JANUARY_20,
) -> Dict[str, Any]:
    """Publish a mid-season revision: optionally post fresher observations
    first, move the clock, then create and publish the next announcement. The
    new announcement supersedes the old and the year stays ANNOUNCED (PRD §3.3).
    Returns the newly published announcement."""
    if snowpack is not None or runoff is not None:
        post_hydrology(api, world, snowpack, runoff, observed_on=observed_on)
    return publish_new_announcement(api, world, clock=clock)


# ═══════════════════════════════════════════════════════════════════════════
# Tier 4: domain scenarios
# ═══════════════════════════════════════════════════════════════════════════

# ── Shortage sharing (PRD §3.4) ────────────────────────────────────────────

def setup_shortage_agreement(
    api: ApiClient,
    world: Dict[str, Any],
    quorum: int = QUORUM_TWO,
    ratifiers: Sequence[str] = ("sr", "jr"),
    activate: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft an agreement and ratify it with the named district sides. The
    default (quorum 2, ratified by senior and junior) leaves it RATIFIED.
    ``activate=True`` also activates it against the world's water-year label
    and refreshes the announcement and lines, which are recomputed in place
    under the sharing formula."""
    agreement = create_agreement(api, quorum_district_count=quorum, **overrides)
    for side in ratifiers:
        agreement = ratify_agreement(api, agreement["id"], world[f"district_{side}"]["id"])
    if activate:
        agreement = activate_agreement(api, agreement["id"], world["year"]["label"])
        world["announcement"] = find_announcement(api, world["year"]["id"], world["announcement"]["id"])
        refresh_lines(api, world)
    return agreement


# ── Reservoir releases and compliance (PRD §3.5) ───────────────────────────

def schedule_and_execute_release(
    api: ApiClient,
    world: Dict[str, Any],
    release_cfs: int,
    duration_days: int,
    scheduled_start: str,
    execute_clock: str,
    purpose: str = "POWER",
) -> Dict[str, Any]:
    """Schedule a release and execute it inside its window."""
    release = create_release(
        api, world["reservoir"]["id"],
        purpose=purpose, release_cfs=release_cfs, duration_days=duration_days,
        scheduled_start=scheduled_start,
    )
    set_clock(api, execute_clock)
    return execute_release(api, release["id"])


def setup_compliance_violation(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    weak_cfs: int = 400,
    weak_days: int = 5,
    weak_start: str = "2027-02-01T00:00:00Z",
    min_flow_cfs: int = 500,
    enforce_start: str = "2027-01-01T00:00:00Z",
    enforce_end: str = "2027-03-01T00:00:00Z",
    execute_clock: str = CLOCK_FEBRUARY_03_10,
) -> Dict[str, Any]:
    """Drive the reservoir onto COMPLIANCE_HOLD: schedule a weak release, then
    register a MIN_FLOW constraint it will violate, then execute it inside the
    window. The release executes anyway and opens an incident, which flips the
    reservoir's posture to COMPLIANCE_HOLD (PRD §3.5).

    With no world, builds a bare big-reservoir project (no contracts, no year);
    pass an announced world to layer the violation onto an operating season.
    Returns {"world", "release", "constraint", "incident"}."""
    if world is None:
        world = setup_project(api, reservoir_profile="big", contract_plan=None)
    release = create_release(
        api, world["reservoir"]["id"],
        purpose="DELIVERY", release_cfs=weak_cfs, duration_days=weak_days,
        scheduled_start=weak_start,
    )
    constraint = create_constraint(
        api, world["reservoir"]["id"],
        f.min_flow_constraint_payload(min_flow_cfs, enforce_start=enforce_start, enforce_end=enforce_end),
    )
    set_clock(api, execute_clock)
    release = execute_release(api, release["id"])
    incident = find_open_incident(api, world["reservoir"]["id"])
    refresh_reservoir(api, world)
    return {"world": world, "release": release, "constraint": constraint, "incident": incident}


def create_delivery(api: ApiClient, world: Dict[str, Any], side: str = "sr", ordered_af: int = 100) -> Dict[str, Any]:
    """Order water against a contract of the world, as its own district."""
    return create_delivery_order(
        api,
        world[f"contract_{side}"]["id"],
        world["year"]["id"],
        ordered_af,
        world[f"district_{side}"]["id"],
    )


def deliver_steps(api: ApiClient, order_id: str, amounts: Iterable[int]) -> Dict[str, Any]:
    """Record a sequence of deliveries against an order; returns the order as
    of the last recording."""
    order = None
    for amount in amounts:
        order = record_delivery(api, order_id, amount)
    return order


def setup_flagged_delivery(
    api: ApiClient,
    ordered_af: int = 100,
    side: str = "sr",
    **violation_kwargs: Any,
) -> Dict[str, Any]:
    """An announced year on the big reservoir, a compliance violation that puts
    the reservoir on hold, and a delivery order created while the hold stands -
    so the order starts FLAGGED (PRD §3.6). Returns
    {"world", "order", "incident", "release", "constraint"}."""
    world = setup_announced_year(api, reservoir_profile="big")
    outcome = setup_compliance_violation(api, world, **violation_kwargs)
    order = create_delivery(api, world, side=side, ordered_af=ordered_af)
    return {**outcome, "order": order}


# ── Hydropower revenue (PRD §3.7) ──────────────────────────────────────────

def setup_revenue_scenario(
    api: ApiClient,
    releases: Sequence[Tuple[int, int, str]] = (
        (1_000, 10, "2027-02-01T00:00:00Z"),
        (500, 4, "2027-02-20T00:00:00Z"),
    ),
    executions: Sequence[Tuple[int, str]] = ((0, CLOCK_FEBRUARY_05),),
    period_month: str = PERIOD_FEBRUARY,
    rate_cents_per_mwh: int = RATE_STANDARD,
    contract_plan: Optional[str] = "standard",
    reservoir_profile: str = "big",
    settle: bool = False,
) -> Dict[str, Any]:
    """Build a revenue scenario: the big reservoir, contracts, a set of
    (release_cfs, duration_days, scheduled_start) releases created up front,
    the named ones executed as (index, clock) pairs, and the revenue period
    opened over the month. With the defaults the projected figures include the
    still-SCHEDULED second release; pass ``settle=True`` to also settle, which
    restricts the input set to EXECUTED releases.

    Returns {"world", "releases", "period"}."""
    world = setup_project(api, reservoir_profile=reservoir_profile, contract_plan=contract_plan)
    created: List[Dict[str, Any]] = []
    for release_cfs, duration_days, scheduled_start in releases:
        created.append(
            create_release(
                api, world["reservoir"]["id"],
                purpose="POWER", release_cfs=release_cfs, duration_days=duration_days,
                scheduled_start=scheduled_start,
            )
        )
    for index, clock in executions:
        set_clock(api, clock)
        created[index] = execute_release(api, created[index]["id"])
    period = create_revenue_period(api, world["reservoir"]["id"], period_month, rate_cents_per_mwh)
    if settle:
        period = settle_period(api, period["id"])
        refresh_contracts(api, world)
        refresh_reservoir(api, world)
    return {"world": world, "releases": created, "period": period}


# ── Transfers, review loop, objection window (PRD §3.8) ───────────────────

def create_transfer_request(
    api: ApiClient,
    world: Dict[str, Any],
    quantity_af: int = 100,
    price_cents: Optional[int] = None,
    seller: str = "sr",
    buyer: str = "jr",
) -> Dict[str, Any]:
    """Propose a transfer between two contracts of the world, as the seller."""
    return create_transfer(
        api,
        world[f"contract_{seller}"]["id"],
        world[f"contract_{buyer}"]["id"],
        world["year"]["id"],
        quantity_af,
        world[f"district_{seller}"]["id"],
        price_cents,
    )


def setup_transfer_under_review(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    quantity_af: int = 100,
    price_cents: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An announced world plus a transfer sitting UNDER_REVIEW."""
    if world is None:
        world = setup_announced_year(api)
    transfer = create_transfer_request(api, world, quantity_af, price_cents)
    return world, transfer


def approve_transfer(
    api: ApiClient, world: Dict[str, Any], transfer_id: str, rationale: Optional[str] = None
) -> Dict[str, Any]:
    """Approve a transfer; the objection window opens at the logical clock and
    closes 72 hours later (PRD §3.8)."""
    return decide_transfer(api, transfer_id, "APPROVE", rationale)


def advance_to_window_end(api: ApiClient, transfer: Dict[str, Any]) -> None:
    """Move the clock to exactly the transfer's objection_window_end; execution
    at equality is allowed."""
    set_clock(api, transfer["objection_window_end"])


def setup_transfer_approved(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    quantity_af: int = 1_000,
    price_cents: Optional[int] = 50_000,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An announced world plus a transfer that is APPROVED, with the clock still
    at the approval instant (the objection window is open)."""
    world, transfer = setup_transfer_under_review(api, world, quantity_af, price_cents)
    transfer = approve_transfer(api, world, transfer["id"])
    return world, transfer


def loop_transfer_revisions(
    api: ApiClient,
    world: Dict[str, Any],
    transfer_id: str,
    amendments: Sequence[Optional[int]] = (900, 800, None),
) -> Dict[str, Any]:
    """Run REQUEST_REVISION / resubmit rounds: one per amendment, amending the
    quantity where the amendment is not None. With the default three rounds the
    transfer's revision_count reaches the cap of three (PRD §3.8)."""
    for quantity in amendments:
        decide_transfer(api, transfer_id, "REQUEST_REVISION", rationale="revise")
        resubmit_transfer(api, transfer_id, world["district_sr"]["id"], quantity_af=quantity)
    return get_transfer(api, transfer_id)


def file_third_party_review(
    api: ApiClient,
    world: Dict[str, Any],
    transfer_id: str,
    claimed_impact_af: int = 300,
    basis: str = "JUNIOR_IMPAIRMENT",
    reviewer: str = "tp",
) -> Dict[str, Any]:
    """File an impact review from a district that is not a transfer party."""
    return file_review(api, transfer_id, claimed_impact_af, basis, world[f"district_{reviewer}"]["id"])


# ═══════════════════════════════════════════════════════════════════════════
# Tier 5: terminal states
# ═══════════════════════════════════════════════════════════════════════════

def setup_transfer_executed(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    quantity_af: int = 1_000,
    price_cents: Optional[int] = 50_000,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An announced world plus an EXECUTED transfer: approved, the clock
    advanced to exactly the objection window's end, executed, and the world's
    allocation lines refreshed to show the transfer ledgers (PRD §3.8)."""
    world, transfer = setup_transfer_approved(api, world, quantity_af, price_cents)
    advance_to_window_end(api, transfer)
    transfer = execute_transfer(api, transfer["id"])
    refresh_lines(api, world)
    return world, transfer


def setup_closed_year(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An announced world whose year is then finalized to CLOSED (PRD §3.3)."""
    world = setup_announced_year(api, **kwargs)
    world["year"] = finalize_water_year(api, world["year"]["id"])
    return world
