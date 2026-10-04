"""Composite setup helpers.

Each test starts against an empty database (the harness restarts the server
before every test), so these fixtures build preconditions from scratch using
only PRD-declared endpoints. Setup calls are validated with the lenient
get_success_data() so a setup failure surfaces as a clear "Setup failed" error.

Identity threading: after a fixture creates an entity that backs a role
identity, every ownership-gated call in the same fixture uses the per-instance
header builder (make_plant_director_headers / make_retailer_buyer_headers /
make_brand_manager_headers) with the real entity id — never the shared
TEST_USERS fallback for entity-backed roles.

Clock discipline: the logical clock starts at exactly 2026-09-01T00:00:00Z and
is advanced only through the unprefixed POST /_clock/set_current_utc. Every
date a fixture sets is reachable from that start.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO, THRESHOLDS
from .factories import (
    create_announce_closure_payload,
    create_brand_payload,
    create_brand_term,
    create_capital_cycle_payload,
    create_clock_payload,
    create_combined_negotiation_payload,
    create_decide_payload,
    create_divestiture_payload,
    create_innovation_project_payload,
    create_item_payload,
    create_negotiation_respond_payload,
    create_plant_payload,
    create_qualification_run_payload,
    create_rationalization_case_payload,
    create_retailer_payload,
    create_sell_down_payload,
    create_product_transfer_payload,
    create_sign_spa_payload,
)
from .test_users import (
    TEST_USERS,
    make_plant_director_headers,
    make_retailer_buyer_headers,
)

PM = TEST_USERS["portfolio_manager_headers"]
PM_PROPOSER = TEST_USERS["portfolio_manager_proposer_headers"]
PM_DECIDER = TEST_USERS["portfolio_manager_decider_headers"]
SCP = TEST_USERS["supply_chain_planner_headers"]
FC = TEST_USERS["finance_controller_headers"]


# ─── Clock (Tier 0 — everything temporal hangs off this) ────────────────────

def set_clock(to_iso8601: str, headers=None) -> str:
    """Advance the logical clock via the UNPREFIXED platform endpoint.

    Returns the server's current_utc echo. Any of the six roles may call it.
    """
    resp = api_client.set_clock(create_clock_payload(to_iso8601), headers or PM)
    data = get_success_data(resp)
    return data["current_utc"]


def compute_sell_through_deadline(decide_iso: str) -> str:
    """sell_through_deadline = decide timestamp + 90 days (time-of-day preserved)."""
    dt = datetime.fromisoformat(decide_iso.replace("Z", "+00:00"))
    deadline = dt + timedelta(days=THRESHOLDS["SELL_THROUGH_DAYS"])
    return deadline.strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Single-entity creators (validated, 201) ─────────────────────────────────

def create_brand(headers=None, **overrides) -> dict:
    resp = api_client.create_brand(create_brand_payload(**overrides), headers or PM)
    return get_success_data(resp)


def create_non_core_brand(headers=None, **overrides) -> dict:
    """A divestiture-candidate brand: core_flag false unless caller overrides."""
    overrides.setdefault("core_flag", False)
    return create_brand(headers=headers, **overrides)


def create_plant(headers=None, **overrides) -> dict:
    resp = api_client.create_plant(create_plant_payload(**overrides), headers or PM)
    return get_success_data(resp)


def create_retailer(headers=None, **overrides) -> dict:
    resp = api_client.create_retailer(
        create_retailer_payload(**overrides), headers or PM
    )
    return get_success_data(resp)


def create_item(brand_id: str, primary_plant_id: str, headers=None, **overrides) -> dict:
    resp = api_client.create_item(
        create_item_payload(brand_id, primary_plant_id, **overrides), headers or PM
    )
    return get_success_data(resp)


# ─── Tier 2: entity hierarchy basics ─────────────────────────────────────────

def setup_brand_and_plant(brand_overrides=None, plant_overrides=None):
    """Brand + Plant. Returns (brand, plant)."""
    brand = create_brand(**(brand_overrides or {}))
    plant = create_plant(**(plant_overrides or {}))
    return brand, plant


def setup_listed_item(item_overrides=None, brand_overrides=None, plant_overrides=None):
    """Brand + Plant + one LISTED item. Returns (brand, plant, item)."""
    brand, plant = setup_brand_and_plant(brand_overrides, plant_overrides)
    item = create_item(brand["id"], plant["id"], **(item_overrides or {}))
    return brand, plant, item


# ─── Tier 1/3: rationalization-case lifecycle ────────────────────────────────

def propose_case(item_id: str, proposer_headers=None) -> dict:
    """Create a SCORED rationalization case; item LISTED -> CUT_PROPOSED."""
    resp = api_client.create_rationalization_case(
        create_rationalization_case_payload(item_id), proposer_headers or PM_PROPOSER
    )
    return get_success_data(resp)


def decide_case(case_id: str, decision: str, decider_headers=None) -> dict:
    """Decide a SCORED case; decider defaults to a DIFFERENT user than the proposer."""
    resp = api_client.decide_rationalization_case(
        case_id, create_decide_payload(decision), decider_headers or PM_DECIDER
    )
    return get_success_data(resp)


def setup_scored_case(item_overrides=None, proposer_headers=None):
    """Brand + Plant + LISTED item + SCORED case (item now CUT_PROPOSED).

    Returns (brand, plant, item, case).
    """
    brand, plant, item = setup_listed_item(item_overrides)
    case = propose_case(item["id"], proposer_headers)
    return brand, plant, item, case


def setup_executing_case(
    item_overrides=None,
    decide_clock_iso=None,
    proposer_headers=None,
    decider_headers=None,
):
    """Case approved: EXECUTING; item SELL_THROUGH with deadline set.

    decide_clock_iso optionally moves the logical clock before the APPROVE so
    the sell_through_deadline anchors to that instant (+90 days). With no
    clock move the approval happens at the 2026-09-01T00:00:00Z default and
    the deadline is 2026-11-30T00:00:00Z.

    Returns (brand, plant, item, case).
    """
    brand, plant, item, case = setup_scored_case(item_overrides, proposer_headers)
    if decide_clock_iso is not None:
        set_clock(decide_clock_iso)
    case = decide_case(case["id"], "APPROVE", decider_headers)
    return brand, plant, item, case


def setup_executed_case(item_overrides=None, proposer_headers=None, decider_headers=None):
    """Full case lifecycle: approve at default clock, advance to the 90-day
    deadline, finalize -> case EXECUTED, item DISCONTINUED.

    Returns (brand, plant, item, case) with post-finalize item and case.
    """
    brand, plant, item, case = setup_executing_case(
        item_overrides=item_overrides,
        proposer_headers=proposer_headers,
        decider_headers=decider_headers,
    )
    set_clock(compute_sell_through_deadline(CLOCK_START_ISO))
    case = finalize_case(case["id"])
    item = get_item(item["id"])
    return brand, plant, item, case


def finalize_case(case_id: str, headers=None) -> dict:
    resp = api_client.finalize_rationalization_case(case_id, headers or PM)
    return get_success_data(resp)


def get_item(item_id: str, headers=None) -> dict:
    resp = api_client.get_item(item_id, headers or PM)
    return get_success_data(resp)


def sell_down(item_id: str, units_sold: int, expected_item_version=None, headers=None) -> dict:
    """OCC sell-down. When expected_item_version is omitted, the item's current
    version is read first so the call is fresh (happy-path helper)."""
    if expected_item_version is None:
        expected_item_version = get_item(item_id, headers)["version"]
    resp = api_client.sell_down_item(
        item_id,
        create_sell_down_payload(units_sold, expected_item_version),
        headers or SCP,
    )
    return get_success_data(resp)


# ─── Tier 3: divestiture pipeline ────────────────────────────────────────────

def setup_divestiture_proposed(brand_overrides=None, divestiture_overrides=None):
    """Non-core brand + PROPOSED divestiture (brand now UNDER_REVIEW).

    Returns (brand, divestiture).
    """
    overrides = {"core_flag": False}
    overrides.update(brand_overrides or {})
    brand = create_brand(**overrides)
    resp = api_client.create_divestiture(
        create_divestiture_payload(brand["id"], **(divestiture_overrides or {})), PM
    )
    divestiture = get_success_data(resp)
    return brand, divestiture


def get_tsa_for_divestiture(divestiture_id: str, headers=None) -> dict:
    """The only read channel for the TSA created by sign-spa: list filtered by
    divestiture_id, expected to hold exactly one agreement."""
    resp = api_client.list_tsas(headers or PM, params={"divestiture_id": divestiture_id})
    tsas = get_success_data(resp)
    assert isinstance(tsas, list) and len(tsas) == 1, (
        f"Expected exactly one TSA for divestiture {divestiture_id}, got {tsas}"
    )
    return tsas[0]


def setup_divestiture_spa_signed(
    tsa_monthly_fee_cents=None,
    tsa_start_date=None,
    tsa_end_date=None,
    brand_overrides=None,
    divestiture_overrides=None,
):
    """Divestiture SPA_SIGNED; TSA created in DRAFT; brand DIVESTING.

    Returns (brand, divestiture, tsa).
    """
    brand, divestiture = setup_divestiture_proposed(brand_overrides, divestiture_overrides)
    spa_overrides = {}
    if tsa_monthly_fee_cents is not None:
        spa_overrides["tsa_monthly_fee_cents"] = tsa_monthly_fee_cents
    if tsa_start_date is not None:
        spa_overrides["tsa_start_date"] = tsa_start_date
    if tsa_end_date is not None:
        spa_overrides["tsa_end_date"] = tsa_end_date
    resp = api_client.sign_divestiture_spa(
        divestiture["id"], create_sign_spa_payload(**spa_overrides), PM
    )
    divestiture = get_success_data(resp)
    tsa = get_tsa_for_divestiture(divestiture["id"])
    return brand, divestiture, tsa


def setup_divestiture_closed(
    tsa_monthly_fee_cents=None,
    tsa_start_date=None,
    tsa_end_date=None,
    brand_overrides=None,
    divestiture_overrides=None,
):
    """Divestiture CLOSED; TSA ACTIVE; brand DIVESTED.

    Close requires logical clock >= TSA start_date; if a later start date is
    supplied the fixture advances the clock to it first (reachable from the
    2026-09-01 default). Returns (brand, divestiture, tsa).
    """
    brand, divestiture, tsa = setup_divestiture_spa_signed(
        tsa_monthly_fee_cents=tsa_monthly_fee_cents,
        tsa_start_date=tsa_start_date,
        tsa_end_date=tsa_end_date,
        brand_overrides=brand_overrides,
        divestiture_overrides=divestiture_overrides,
    )
    start = datetime.fromisoformat(tsa["start_date"].replace("Z", "+00:00"))
    default = datetime.fromisoformat(CLOCK_START_ISO.replace("Z", "+00:00"))
    if start > default:
        set_clock(tsa["start_date"])
    resp = api_client.close_divestiture(divestiture["id"], PM)
    divestiture = get_success_data(resp)
    tsa = get_tsa_for_divestiture(divestiture["id"])
    return brand, divestiture, tsa


def terminate_tsa(tsa_id: str, headers=None) -> dict:
    resp = api_client.terminate_tsa(tsa_id, headers or FC)
    return get_success_data(resp)


def setup_divestiture_separated(**kwargs):
    """Full pipeline: CLOSED -> TSA TERMINATED -> SEPARATED; brand EXITED.

    Terminate happens at the current clock (at least the TSA start_date);
    callers needing a specific penalty move the clock BEFORE calling
    terminate_tsa themselves. Returns (brand, divestiture, tsa).
    """
    brand, divestiture, tsa = setup_divestiture_closed(**kwargs)
    tsa = terminate_tsa(tsa["id"])
    resp = api_client.separate_divestiture(divestiture["id"], PM)
    divestiture = get_success_data(resp)
    return brand, divestiture, tsa


# ─── Tier 2/3: product transfers & qualification runs ────────────────────────

def setup_transfer_planned(
    item_overrides=None,
    source_capacity=1000000,
    target_capacity=1000000,
):
    """Brand + source/target OPERATING plants + LISTED item at source +
    PLANNED transfer source -> target.

    Returns (brand, source_plant, target_plant, item, transfer).
    """
    brand = create_brand()
    source_plant = create_plant(quarterly_capacity_units=source_capacity)
    target_plant = create_plant(quarterly_capacity_units=target_capacity)
    item = create_item(brand["id"], source_plant["id"], **(item_overrides or {}))
    resp = api_client.create_product_transfer(
        create_product_transfer_payload(
            item["id"], source_plant["id"], target_plant["id"]
        ),
        SCP,
    )
    transfer = get_success_data(resp)
    return brand, source_plant, target_plant, item, transfer


def record_run(transfer_id: str, target_plant_id: str, headers=None, **run_overrides) -> dict:
    """Record one qualification run as the PlantDirector OF THE TARGET PLANT
    (identity threading: X-User-ID == transfer.target_plant_id)."""
    resp = api_client.record_qualification_run(
        transfer_id,
        create_qualification_run_payload(**run_overrides),
        headers or make_plant_director_headers(target_plant_id),
    )
    return get_success_data(resp)


def record_pass_run(transfer_id: str, target_plant_id: str, run_date=None, **overrides) -> dict:
    """A clean PASS run (default 100 rejected of 10000 = 100bp <= 250bp)."""
    if run_date is not None:
        overrides["run_date"] = run_date
    overrides.setdefault("units_produced", 10000)
    overrides.setdefault("units_rejected", 100)
    return record_run(transfer_id, target_plant_id, **overrides)


def record_fail_run(transfer_id: str, target_plant_id: str, run_date=None, **overrides) -> dict:
    """A FAIL run (default 251 of 10000 = 251bp > 250bp)."""
    if run_date is not None:
        overrides["run_date"] = run_date
    overrides.setdefault("units_produced", 10000)
    overrides.setdefault("units_rejected", 251)
    return record_run(transfer_id, target_plant_id, **overrides)


def get_transfer(transfer_id: str, headers=None) -> dict:
    resp = api_client.get_product_transfer(transfer_id, headers or SCP)
    return get_success_data(resp)


def setup_transfer_executed(item_overrides=None, source_capacity=1000000, target_capacity=1000000):
    """Transfer driven to EXECUTED by two consecutive PASS runs.

    Returns (brand, source_plant, target_plant, item, transfer) with the
    post-execution item (primary_plant_id rewritten) and transfer.
    """
    brand, source_plant, target_plant, item, transfer = setup_transfer_planned(
        item_overrides=item_overrides,
        source_capacity=source_capacity,
        target_capacity=target_capacity,
    )
    record_pass_run(transfer["id"], target_plant["id"], run_date="2026-09-02T00:00:00Z")
    record_pass_run(transfer["id"], target_plant["id"], run_date="2026-09-03T00:00:00Z")
    transfer = get_transfer(transfer["id"])
    item = get_item(item["id"])
    return brand, source_plant, target_plant, item, transfer


# ─── Tier 2: combined negotiations ───────────────────────────────────────────

def setup_negotiation_terms_proposed(
    num_brands=2,
    baseline_facings=(100, 60),
    proposed_facings=(90, 50),
    period_code=None,
    effective_from=None,
    effective_to=None,
    retailer_overrides=None,
    brand_overrides=None,
):
    """Retailer + N ACTIVE brands + TERMS_PROPOSED negotiation.

    Returns (retailer, brands, negotiation).
    """
    retailer = create_retailer(**(retailer_overrides or {}))
    brands = [create_brand(**(brand_overrides or {})) for _ in range(num_brands)]
    terms = []
    for i, brand in enumerate(brands):
        base = baseline_facings[i] if i < len(baseline_facings) else 50
        prop = proposed_facings[i] if i < len(proposed_facings) else 40
        terms.append(create_brand_term(brand["id"], base, prop))
    overrides = {}
    if period_code is not None:
        overrides["period_code"] = period_code
    if effective_from is not None:
        overrides["effective_from"] = effective_from
    if effective_to is not None:
        overrides["effective_to"] = effective_to
    resp = api_client.create_combined_negotiation(
        create_combined_negotiation_payload(retailer["id"], terms, **overrides), PM
    )
    negotiation = get_success_data(resp)
    return retailer, brands, negotiation


def respond_to_negotiation(negotiation: dict, response: str, headers=None) -> dict:
    """Respond as the RetailerBuyer OF THIS RETAILER (identity threading:
    X-User-ID == negotiation.retailer_id)."""
    resp = api_client.respond_to_negotiation(
        negotiation["id"],
        create_negotiation_respond_payload(response),
        headers or make_retailer_buyer_headers(negotiation["retailer_id"]),
    )
    return get_success_data(resp)


# ─── Tier 2/4: capital cycles & innovation projects ──────────────────────────

def setup_capital_cycle(headers=None, **overrides) -> dict:
    resp = api_client.create_capital_cycle(
        create_capital_cycle_payload(**overrides), headers or FC
    )
    return get_success_data(resp)


def create_project(brand_id: str, funding_cycle_id: str, headers=None, **overrides) -> dict:
    resp = api_client.create_innovation_project(
        create_innovation_project_payload(brand_id, funding_cycle_id, **overrides),
        headers or PM,
    )
    return get_success_data(resp)


def run_selection(cycle_id: str, headers=None) -> dict:
    resp = api_client.run_capital_cycle_selection(cycle_id, headers or FC)
    return get_success_data(resp)


# ─── Tier 5: plant-closure ritual ────────────────────────────────────────────

def announce_closure(plant_id: str, closure_date=None, headers=None) -> dict:
    resp = api_client.announce_plant_closure(
        plant_id, create_announce_closure_payload(closure_date), headers or PM
    )
    return get_success_data(resp)


def complete_closure(plant_id: str, headers=None) -> dict:
    resp = api_client.complete_plant_closure(plant_id, headers or PM)
    return get_success_data(resp)


def setup_closing_plant(closure_date=None):
    """An empty OPERATING plant moved to CLOSING. Returns the plant."""
    plant = create_plant()
    return announce_closure(plant["id"], closure_date)


def setup_closed_plant(closure_date=None):
    """An empty plant driven OPERATING -> CLOSING -> CLOSED. Returns the plant."""
    plant = setup_closing_plant(closure_date)
    return complete_closure(plant["id"])
