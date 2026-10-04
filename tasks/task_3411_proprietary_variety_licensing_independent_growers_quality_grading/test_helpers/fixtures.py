"""Composite setup helpers.

Every fixture builds preconditions from scratch via the public API (the server
restarts before every test) and uses get_success_data so setup failures surface
as clear "Setup failed" errors. Ownership-gated calls always thread the real
Grower.id through make_grower_principal_headers; grading helpers keep the
submitter, certifier, and receiver ids distinct so the segregation rule holds.

Canonical timeline (strawberry defaults): clock pinned 2026-06-01; planting
confirmed 2026-08-01 (clock 08-02); lot harvested 2026-10-06T06:00 (clock
06:30), received 12:00 (clock 12:30) -> precool 6.0h, compliant at pulp 3.5C;
pool week [2026-10-05, 2026-10-12); close/settle at clock 2026-10-12.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as F
from .constants import (CLOCK_BASE, CLOCK_PLANT, PLANTED_ON, POOL_WEEK_START,
                        POOL_WEEK_END, POOL_CLOSE_CLOCK, POOL_ESTIMATED_PRICE,
                        POOL_ACTUAL_PRICE)
from .test_users import (TEST_USERS, make_grower_principal_headers,
                         make_quality_grader_headers,
                         make_cooling_operator_headers, GRADER_SUBMITTER,
                         GRADER_CERTIFIER, COOLING_OP_1)

ADMIN = TEST_USERS["platform_admin_headers"]
BREEDER = TEST_USERS["breeding_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
NURSERY = TEST_USERS["nursery_manager_headers"]
SETTLEMENT = TEST_USERS["settlement_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: thin primitives (one call each)
# ---------------------------------------------------------------------------

def set_clock(current_utc=CLOCK_BASE):
    get_success_data(api_client.set_clock(F.set_clock_payload(current_utc), ADMIN))


def create_variety(**overrides):
    return get_success_data(api_client.create_variety(
        F.create_variety_payload(**overrides), BREEDER))


def release_variety(variety_id):
    return get_success_data(api_client.release_variety(variety_id, BREEDER))


def create_released_variety(**overrides):
    v = create_variety(**overrides)
    return get_success_data(api_client.release_variety(v["id"], BREEDER))


def recall_variety(variety_id, **overrides):
    """RELEASED -> RECALLED; returns the RecallOrder created ISSUED."""
    return get_success_data(api_client.recall_variety(
        variety_id, F.recall_variety_payload(**overrides), BREEDER))


def create_grower(**overrides):
    return get_success_data(api_client.create_grower(
        F.create_grower_payload(**overrides), ADMIN))


def suspend_grower(grower_id, **overrides):
    return get_success_data(api_client.suspend_grower(
        grower_id, COMPLIANCE, F.suspend_grower_payload(**overrides)))


def exit_grower(grower_id):
    return get_success_data(api_client.exit_grower(grower_id, COMPLIANCE))


def apply_for_agreement(grower, variety, **overrides):
    """GrowerPrincipal applies for its own agreement (stays PENDING_REVIEW)."""
    return get_success_data(api_client.create_agreement(
        F.create_agreement_payload(grower["id"], variety["id"], **overrides),
        make_grower_principal_headers(grower["id"])))


def decide_agreement(agreement_id, decision="APPROVE", **overrides):
    return get_success_data(api_client.decide_agreement(
        agreement_id, F.decide_agreement_payload(decision, **overrides), COMPLIANCE))


def get_agreement(agreement_id):
    return get_success_data(api_client.get_agreement(agreement_id, ADMIN))


def create_active_agreement(grower, variety, **overrides):
    """Agreement walked to ACTIVE: apply + decide APPROVE. Returns the fresh
    agreement (version 2) as returned by decide."""
    a = apply_for_agreement(grower, variety, **overrides)
    return decide_agreement(a["id"], "APPROVE")


def create_plant_lot(agreement, variety, **overrides):
    return get_success_data(api_client.create_plant_lot(
        F.create_plant_lot_payload(agreement["id"], variety["id"], **overrides),
        NURSERY))


def get_plant_lot(lot_id):
    return get_success_data(api_client.get_plant_lot(lot_id, ADMIN))


def create_harvest_window(variety, **overrides):
    return get_success_data(api_client.create_harvest_window(
        F.create_harvest_window_payload(variety["id"], **overrides), ADMIN))


def get_harvest_window(window_id):
    return get_success_data(api_client.get_harvest_window(window_id, ADMIN))


def plan_planting(agreement, lot, grower, planned_plants=None):
    """Plan a planting with the OCC guard satisfied: re-reads the agreement's
    current version and submits it as expected_agreement_version."""
    current = get_agreement(agreement["id"])
    kw = {}
    if planned_plants is not None:
        kw["planned_plants"] = planned_plants
    return get_success_data(api_client.create_planting(
        F.create_planting_payload(agreement["id"], lot["id"],
                                  current["version"], **kw),
        make_grower_principal_headers(grower["id"])))


def get_planting(planting_id):
    return get_success_data(api_client.get_planting(planting_id, ADMIN))


def confirm_planting(planting, grower, plants_planted_actual=None,
                     planted_on=PLANTED_ON):
    """PLANNED -> PLANTED. Caller must ensure a covering harvest window exists
    and the logical clock is >= planted_on."""
    kw = {"planted_on": planted_on}
    if plants_planted_actual is not None:
        kw["plants_planted_actual"] = plants_planted_actual
    return get_success_data(api_client.confirm_planting(
        planting["id"], F.confirm_planting_payload(**kw),
        make_grower_principal_headers(grower["id"])))


def complete_planting(planting, grower):
    return get_success_data(api_client.complete_planting(
        planting["id"], make_grower_principal_headers(grower["id"])))


def create_lot_in_transit(planting, grower, **overrides):
    """Record a harvest lot with the OCC guard satisfied: re-reads the
    planting's current version. First lot flips the planting to HARVESTING."""
    current = get_planting(planting["id"])
    return get_success_data(api_client.create_harvest_lot(
        F.create_harvest_lot_payload(planting["id"], current["version"],
                                     **overrides),
        make_grower_principal_headers(grower["id"])))


def get_harvest_lot(lot_id):
    return get_success_data(api_client.get_harvest_lot(lot_id, ADMIN))


def receive_lot(lot_id, operator_id=COOLING_OP_1, **overrides):
    return get_success_data(api_client.receive_harvest_lot(
        lot_id, F.receive_lot_payload(**overrides),
        make_cooling_operator_headers(operator_id)))


def submit_grade(lot_id, grader_id=GRADER_SUBMITTER, **scores):
    return get_success_data(api_client.grade_harvest_lot(
        lot_id, F.grade_payload(**scores),
        make_quality_grader_headers(grader_id)))


def certify_lot(lot_id, certifier_id=GRADER_CERTIFIER):
    return get_success_data(api_client.certify_grade(
        lot_id, make_quality_grader_headers(certifier_id)))


def dispute_grade(lot_id, grower, **overrides):
    return get_success_data(api_client.dispute_grade(
        lot_id, F.dispute_grade_payload(**overrides),
        make_grower_principal_headers(grower["id"])))


def create_pool(**overrides):
    return get_success_data(api_client.create_pool_period(
        F.create_pool_payload(**overrides), SETTLEMENT))


def get_pool(pool_id):
    return get_success_data(api_client.get_pool_period(pool_id, SETTLEMENT))


def close_pool(pool_id, estimated_price=POOL_ESTIMATED_PRICE):
    return get_success_data(api_client.close_pool_period(
        pool_id, F.close_pool_payload(
            estimated_price_cents_per_kg=estimated_price), SETTLEMENT))


def settle_pool(pool_id, actual_price=POOL_ACTUAL_PRICE):
    return get_success_data(api_client.settle_pool_period(
        pool_id, F.settle_pool_payload(
            actual_price_cents_per_kg=actual_price), SETTLEMENT))


def get_statement(statement_id):
    return get_success_data(
        api_client.get_settlement_statement(statement_id, SETTLEMENT))


def find_statement(pool_id, grower_id):
    """The single statement of (pool, grower); fails loudly if not exactly 1."""
    data = get_success_data(api_client.list_settlement_statements(
        SETTLEMENT, params={"pool_period_id": pool_id, "grower_id": grower_id}))
    assert len(data) == 1, f"expected 1 statement, got {len(data)}"
    return data[0]


def dispute_statement(statement_id, grower, **overrides):
    return get_success_data(api_client.dispute_statement(
        statement_id, F.dispute_statement_payload(**overrides),
        make_grower_principal_headers(grower["id"])))


def resolve_statement(statement_id, resolution="UPHOLD", **overrides):
    return get_success_data(api_client.resolve_statement(
        statement_id, F.resolve_statement_payload(resolution, **overrides),
        SETTLEMENT))


def pay_statement(statement_id):
    return get_success_data(api_client.pay_statement(statement_id, SETTLEMENT))


def enforce_recall(recall_order_id):
    return get_success_data(
        api_client.enforce_recall_order(recall_order_id, COMPLIANCE))


# ---------------------------------------------------------------------------
# Tier 1/2: state progression + hierarchy composites
# ---------------------------------------------------------------------------

def setup_active_agreement(variety_overrides=None, grower_overrides=None,
                           agreement_overrides=None):
    """Variety RELEASED + grower ACTIVE + agreement ACTIVE.
    Returns (variety, grower, agreement)."""
    variety = create_released_variety(**(variety_overrides or {}))
    grower = create_grower(**(grower_overrides or {}))
    agreement = create_active_agreement(grower, variety,
                                        **(agreement_overrides or {}))
    return variety, grower, agreement


def setup_planting_planned(quantity_plants=2000, planned_plants=1500,
                           variety_overrides=None, grower_overrides=None,
                           agreement_overrides=None):
    """Adds a plant lot and a PLANNED planting. Returns dict bundle."""
    variety, grower, agreement = setup_active_agreement(
        variety_overrides, grower_overrides, agreement_overrides)
    lot = create_plant_lot(agreement, variety, quantity_plants=quantity_plants)
    planting = plan_planting(agreement, lot, grower, planned_plants)
    return {"variety": variety, "grower": grower, "agreement": agreement,
            "lot": lot, "planting": planting}


def setup_planting_confirmed(planned_plants=1500, plants_actual=1500,
                             planted_on=PLANTED_ON, window_overrides=None,
                             **kwargs):
    """Full chain through a PLANTED planting with the harvest window booked.
    Creates the canonical covering window, advances the clock to the
    confirm day, then confirms. Returns dict bundle including the window."""
    bundle = setup_planting_planned(planned_plants=planned_plants, **kwargs)
    window = create_harvest_window(bundle["variety"], **(window_overrides or {}))
    set_clock(CLOCK_PLANT)
    planting = confirm_planting(bundle["planting"], bundle["grower"],
                                plants_actual, planted_on)
    bundle.update({"window": window, "planting": planting})
    return bundle


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts (harvest lot delivery -> certification)
# ---------------------------------------------------------------------------

def setup_lot_in_transit(harvested_at="2026-10-06T06:00:00Z",
                         gross_weight_kg=1200, tare_weight_kg=50,
                         lot_clock="2026-10-06T06:30:00Z", **kwargs):
    """Through a harvest lot IN_TRANSIT / UNGRADED (planting now HARVESTING)."""
    bundle = setup_planting_confirmed(**kwargs)
    set_clock(lot_clock)
    lot = create_lot_in_transit(bundle["planting"], bundle["grower"],
                                harvested_at=harvested_at,
                                gross_weight_kg=gross_weight_kg,
                                tare_weight_kg=tare_weight_kg)
    bundle["harvest_lot"] = lot
    return bundle


def setup_lot_received(received_at="2026-10-06T12:00:00Z", pulp_temp=3.5,
                       receive_clock="2026-10-06T12:30:00Z",
                       operator_id=COOLING_OP_1, **kwargs):
    """Through a RECEIVED lot with cold chain evaluated (compliant at the
    defaults: 6.0h precool, pulp 3.5C)."""
    bundle = setup_lot_in_transit(**kwargs)
    set_clock(receive_clock)
    lot = receive_lot(bundle["harvest_lot"]["id"], operator_id=operator_id,
                      received_at=received_at, pulp_temp_c_at_receipt=pulp_temp)
    bundle["harvest_lot"] = lot
    bundle["received_by"] = operator_id
    return bundle


def setup_lot_submitted(grader_id=GRADER_SUBMITTER, scores=None, **kwargs):
    """Through a SUBMITTED grade (defaults grade PREMIUM)."""
    bundle = setup_lot_received(**kwargs)
    lot = submit_grade(bundle["harvest_lot"]["id"], grader_id=grader_id,
                       **(scores or {}))
    bundle["harvest_lot"] = lot
    bundle["submitted_by"] = grader_id
    return bundle


def setup_lot_certified(certifier_id=GRADER_CERTIFIER, **kwargs):
    """Grading -> certification: lot GRADED with grade CERTIFIED, certified by a
    grader distinct from both submitter and receiver (segregation of duties)."""
    bundle = setup_lot_submitted(**kwargs)
    lot = certify_lot(bundle["harvest_lot"]["id"], certifier_id=certifier_id)
    bundle["harvest_lot"] = lot
    bundle["certified_by"] = certifier_id
    return bundle


# ---------------------------------------------------------------------------
# Tier 3: pool close -> settle -> statement
# ---------------------------------------------------------------------------

def setup_pool_closed(est_price=POOL_ESTIMATED_PRICE,
                      close_clock=POOL_CLOSE_CLOCK, pool_overrides=None,
                      **kwargs):
    """One certified lot inside the pool week; pool OPEN -> CLOSED with the
    provisional pipeline stored. Returns bundle with pool + statement."""
    bundle = setup_lot_certified(**kwargs)
    pool = create_pool(**(pool_overrides or {}))
    set_clock(close_clock)
    pool = close_pool(pool["id"], est_price)
    bundle["pool"] = pool
    bundle["statement"] = find_statement(pool["id"], bundle["grower"]["id"])
    return bundle


def setup_pool_settled(actual_price=POOL_ACTUAL_PRICE, **kwargs):
    """Pool CLOSED -> SETTLED; lots GRADED -> SETTLED; statement ISSUED with
    final amounts and dispute deadline. Returns bundle with pool + statement."""
    bundle = setup_pool_closed(**kwargs)
    pool = settle_pool(bundle["pool"]["id"], actual_price)
    bundle["pool"] = pool
    bundle["harvest_lot"] = get_harvest_lot(bundle["harvest_lot"]["id"])
    bundle["statement"] = get_statement(bundle["statement"]["id"])
    return bundle


def setup_statement_disputed(**kwargs):
    """Pool settled, then the owning grower disputes the ISSUED statement."""
    bundle = setup_pool_settled(**kwargs)
    stmt = dispute_statement(bundle["statement"]["id"], bundle["grower"])
    bundle["statement"] = stmt
    return bundle


# ---------------------------------------------------------------------------
# Tier 5: terminal-state and cascade shortcuts
# ---------------------------------------------------------------------------

def setup_recalled_variety_order(**recall_overrides):
    """Variety RELEASED -> RECALLED; returns (variety, recall_order ISSUED)."""
    variety = create_released_variety()
    order = recall_variety(variety["id"], **recall_overrides)
    return get_success_data(api_client.get_variety(variety["id"], ADMIN)), order


def setup_exit_ready_grower():
    """Grower whose exit gates pass trivially: ACTIVE, no plantings, no
    statements. Returns the grower."""
    return create_grower()


def setup_exited_grower_with_cancelled_planting(quantity_plants=500,
                                                planned_plants=300):
    """Grower EXITED via cascade: agreement TERMINATED, PLANNED planting
    CANCELLED, lot reservation released. Returns the setup bundle with the
    post-exit grower."""
    bundle = setup_planting_planned(quantity_plants=quantity_plants,
                                    planned_plants=planned_plants)
    grower = exit_grower(bundle["grower"]["id"])
    bundle["grower"] = grower
    bundle["agreement"] = get_agreement(bundle["agreement"]["id"])
    bundle["planting"] = get_planting(bundle["planting"]["id"])
    bundle["lot"] = get_plant_lot(bundle["lot"]["id"])
    return bundle
