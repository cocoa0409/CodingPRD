"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so each fixture builds its preconditions from scratch using
only PRD-declared endpoints. Setup calls use get_success_data so a broken
precondition surfaces as a clear setup failure. The logical clock starts at
exactly 2026-09-01T00:00:00Z (PRD §2.4); fixtures that need another clock set
it explicitly through the unprefixed clock endpoint.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import (
    BLENDED_COMPONENTS,
    DEFAULT_CLOCK,
    FIXED_ONLY_COMPONENTS,
    TEST_DEFAULTS,
)
from .factories import (
    create_alumina_agreement_payload,
    create_curtailment_decision_payload,
    create_environmental_permit_payload,
    create_hedge_position_payload,
    create_labor_agreement_payload,
    create_potline_payload,
    create_power_contract_payload,
    create_price_observation_payload,
    create_restart_plan_payload,
    create_smelter_payload,
)
from .test_users import (
    TEST_USERS,
    make_smelter_manager_headers,
    make_controller_headers,
    make_vp_operations_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENERGY = TEST_USERS["energy_manager_headers"]
TRADER = TEST_USERS["trading_analyst_headers"]
MANAGER = TEST_USERS["smelter_manager_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
VP = TEST_USERS["vp_operations_headers"]
EHS = TEST_USERS["ehs_manager_headers"]


# --- Tier 1: single-resource creation ---

def create_smelter(**overrides):
    """Onboard a smelter. Returns the created Smelter."""
    return get_success_data(api.create_smelter(create_smelter_payload(**overrides), ADMIN))


def create_active_contract(smelter_id, components=None, activate=True, **overrides):
    """Create a power contract (default: fixed-only window covering the default
    clock) and activate it. Returns the contract as read after activation."""
    payload = create_power_contract_payload(
        smelter_id, components=components or FIXED_ONLY_COMPONENTS, **overrides
    )
    contract = get_success_data(api.create_power_contract(payload, ENERGY))
    if activate:
        contract = get_success_data(api.activate_power_contract(contract["id"], ENERGY))
    return contract


def create_potline(smelter_id, **overrides):
    """Create a potline (starts OPERATING). Returns the created Potline."""
    return get_success_data(api.create_potline(create_potline_payload(smelter_id, **overrides), MANAGER))


def create_spl_permit(smelter_id, permit_type="SPL_DISPOSAL", **overrides):
    """Register an environmental permit (ACTIVE on creation)."""
    return get_success_data(
        api.create_environmental_permit(
            create_environmental_permit_payload(smelter_id, permit_type=permit_type, **overrides),
            EHS,
        )
    )


def create_labor_agreement(smelter_id, notice_period_days=0, **overrides):
    """Register the smelter's labor agreement (ACTIVE on creation)."""
    return get_success_data(
        api.create_labor_agreement(
            create_labor_agreement_payload(
                smelter_id, notice_period_days=notice_period_days, **overrides
            ),
            ADMIN,
        )
    )


def create_hedge(smelter_id, volume_tonnes=20000, delivery_month="2026-09", **overrides):
    """Open a hedge position (OPEN on creation)."""
    return get_success_data(
        api.create_hedge_position(
            create_hedge_position_payload(
                smelter_id, volume_tonnes=volume_tonnes, delivery_month=delivery_month, **overrides
            ),
            TRADER,
        )
    )


def create_alumina_agreement(smelter_id, **overrides):
    """Register an alumina transfer-pricing agreement (effective immediately)."""
    return get_success_data(
        api.create_alumina_agreement(create_alumina_agreement_payload(smelter_id, **overrides), CONTROLLER)
    )


def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin only; unprefixed endpoint)."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# --- Market data ---

def post_price_observation(instrument, region_code, observed_at, price_usd, headers=None):
    return get_success_data(
        api.create_price_observation(
            create_price_observation_payload(
                instrument=instrument,
                region_code=region_code,
                observed_at=observed_at,
                price_usd=price_usd,
            ),
            headers or TRADER,
        )
    )


def post_standard_price_set(region="NA_NORTHWEST", lme=2400.00, premium=380.00,
                            alumina=340.00, spot=48.00):
    """Post the standard four-instrument price set used by the decision
    economics snapshot: LME (GLOBAL), regional premium, alumina index (GLOBAL),
    and power spot for the smelter's region."""
    post_price_observation("ALUMINUM_LME", "GLOBAL", "2026-08-15T00:00:00Z", lme)
    post_price_observation("REGIONAL_PREMIUM", region, "2026-08-15T00:00:00Z", premium)
    post_price_observation("ALUMINA_INDEX", "GLOBAL", "2026-08-15T00:00:00Z", alumina)
    post_price_observation("POWER_SPOT", region, "2026-08-20T00:00:00Z", spot, headers=ENERGY)


# --- Tier 2: site hierarchies ---

def setup_site(components=None, with_potline=True, potline_kwargs=None, **smelter_overrides):
    """Smelter + ACTIVE power contract (+ one OPERATING potline).
    Returns dict(smelter=..., contract=..., potline=... or None)."""
    smelter = create_smelter(**smelter_overrides)
    contract = create_active_contract(smelter["id"], components=components)
    potline = create_potline(smelter["id"], **(potline_kwargs or {})) if with_potline else None
    return {"smelter": smelter, "contract": contract, "potline": potline}


def setup_idled_potline(**kwargs):
    """Site with the potline emergency-idled (curtail depth 100). The potline is
    IDLE with active_decision_id null."""
    env = setup_site(**kwargs)
    env["potline"] = get_success_data(
        api.curtail_potline(env["potline"]["id"], {"depth_pct": 100}, MANAGER)
    )
    return env


def setup_planned_restart(with_permit=True, planned_restart_at="2026-09-05T00:00:00Z", **kwargs):
    """Idled potline plus a PLANNED restart plan; optionally with an ACTIVE
    SPL_DISPOSAL permit registered."""
    env = setup_idled_potline(**kwargs)
    env["permit"] = create_spl_permit(env["smelter"]["id"]) if with_permit else None
    env["plan"] = get_success_data(
        api.create_restart_plan(
            create_restart_plan_payload(env["potline"]["id"], planned_restart_at=planned_restart_at),
            MANAGER,
        )
    )
    return env


# --- Tier 3: decision pipeline ---

def propose_decision(potline_id, depth_pct=50, proposer_id="mgr-1", **overrides):
    """Propose a curtailment decision carrying the potline's live version.
    Returns the created decision (ECONOMIC_REVIEW)."""
    potline = get_success_data(api.get_potline(potline_id, MANAGER))
    payload = create_curtailment_decision_payload(
        potline_id, potline["version"], depth_pct=depth_pct, **overrides
    )
    return get_success_data(
        api.create_curtailment_decision(payload, make_smelter_manager_headers(proposer_id))
    )


def approve_decision(decision_id, economic_reviewer_id="ctrl-1", labor_approver_id="vp-1"):
    """Walk a decision ECONOMIC_REVIEW -> LABOR_REVIEW -> APPROVED with
    segregated reviewers. Returns the APPROVED decision."""
    get_success_data(
        api.economic_approve_decision(decision_id, make_controller_headers(economic_reviewer_id))
    )
    return get_success_data(
        api.labor_approve_decision(decision_id, make_vp_operations_headers(labor_approver_id))
    )


def setup_approved_decision(notice_period_days=0, hedge_volume=20000, depth_pct=50,
                            with_hedge=True, with_labor=True, with_prices=True,
                            proposer_id="mgr-1", **site_kwargs):
    """Full pre-execution environment: site (fixed-only contract, potline),
    optional ACTIVE labor agreement, optional standard price set, optional OPEN
    hedge (default 20000t for 2026-09 -> coverage 0.6667 on a 1000 tpd site),
    and an APPROVED decision at the given depth."""
    env = setup_site(**site_kwargs)
    if with_labor:
        env["labor_agreement"] = create_labor_agreement(
            env["smelter"]["id"], notice_period_days=notice_period_days
        )
    if with_prices:
        post_standard_price_set()
    if with_hedge:
        env["hedge"] = create_hedge(env["smelter"]["id"], volume_tonnes=hedge_volume)
    env["decision"] = propose_decision(env["potline"]["id"], depth_pct=depth_pct,
                                       proposer_id=proposer_id)
    env["decision"] = approve_decision(env["decision"]["id"])
    return env


def setup_executed_decision(depth_pct=50, **kwargs):
    """An APPROVED decision executed: potline CURTAILED (or IDLE at depth 100)
    with active_decision_id set."""
    env = setup_approved_decision(depth_pct=depth_pct, **kwargs)
    env["decision"] = get_success_data(
        api.execute_decision(env["decision"]["id"], make_smelter_manager_headers("mgr-1"))
    )
    env["potline"] = get_success_data(api.get_potline(env["potline"]["id"], MANAGER))
    return env


def setup_executed_and_reversed(**kwargs):
    """An executed decision already reversed once (decision REVERSED, potline
    back to OPERATING)."""
    env = setup_executed_decision(**kwargs)
    env["decision"] = get_success_data(
        api.reverse_decision(env["decision"]["id"], make_smelter_manager_headers("mgr-1"))
    )
    env["potline"] = get_success_data(api.get_potline(env["potline"]["id"], MANAGER))
    return env
