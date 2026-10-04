"""Composite setup helpers.

Every helper builds its preconditions from scratch through the PRD's own
endpoints (each test runs against a freshly restarted server) and uses the
lenient get_success_data validator so a setup failure surfaces as a clear
"Setup failed" error instead of a misleading assertion failure.

Shared recipe chains (the design indices' replay blocks) live here so tests
stay focused on the claim under test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .constants import CLOCK_START_UTC
from .factories import (
    create_amendment_payload,
    create_contracted_lot_payload,
    create_crop_contract_payload,
    create_customer_chain_payload,
    create_cut_specification_payload,
    create_import_lot_payload,
    create_processing_line_payload,
    create_production_run_payload,
    create_reading_payload,
    create_shipment_payload,
    create_shortage_event_payload,
    create_storage_facility_payload,
    create_supply_agreement_payload,
    create_grower_payload,
)
from .test_users import TEST_USERS, make_chain_customer_headers, make_grower_headers

ADMIN = TEST_USERS["platform_admin_headers"]
GRM = TEST_USERS["grower_relations_manager_headers"]
STORAGE = TEST_USERS["storage_operator_headers"]
QA = TEST_USERS["qa_lead_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ACCOUNT = TEST_USERS["account_manager_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


# ── Tier 0: clock ────────────────────────────────────────────────────────────
def set_clock(current_utc: str = CLOCK_START_UTC, api=None) -> None:
    """Set the logical clock (PRD §2.5). Default pins the documented start."""
    api = api or _api
    resp = api.set_clock({"current_utc": current_utc}, ADMIN)
    assert resp.status_code == 200, f"Setup failed: set_clock -> {resp.status_code} {resp.text}"


# ── Tier 1: single-resource creators ─────────────────────────────────────────
def make_grower(api=None, **overrides) -> dict:
    api = api or _api
    resp = api.create_grower(create_grower_payload(**overrides), GRM)
    return get_success_data(resp)


def make_facility(api=None, **overrides) -> dict:
    api = api or _api
    resp = api.create_storage_facility(create_storage_facility_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_line(api=None, **overrides) -> dict:
    api = api or _api
    resp = api.create_processing_line(create_processing_line_payload(**overrides), ADMIN)
    return get_success_data(resp)


def make_chain(api=None, **overrides) -> dict:
    api = api or _api
    resp = api.create_customer_chain(create_customer_chain_payload(**overrides), ACCOUNT)
    return get_success_data(resp)


def make_contract(grower_id: str, api=None, **overrides) -> dict:
    """Create a contract in DRAFT (not activated)."""
    api = api or _api
    resp = api.create_crop_contract(create_crop_contract_payload(grower_id, **overrides), GRM)
    return get_success_data(resp)


def make_active_contract(grower_id: str, api=None, **overrides) -> dict:
    """Create + activate. Returns the ACTIVE contract."""
    api = api or _api
    contract = make_contract(grower_id, api=api, **overrides)
    resp = api.activate_crop_contract(contract["id"], GRM)
    return get_success_data(resp)


def make_spec(chain_id: str, api=None, **overrides) -> dict:
    """Create a spec in SUBMITTED as the owning chain customer."""
    api = api or _api
    resp = api.create_cut_specification(
        create_cut_specification_payload(chain_id, **overrides),
        make_chain_customer_headers(chain_id),
    )
    return get_success_data(resp)


def validate_spec(spec_id: str, panel_score: float = 8.0, api=None) -> dict:
    api = api or _api
    resp = api.validate_cut_specification(spec_id, {"panel_score": panel_score}, QA)
    return get_success_data(resp)


def make_validated_spec(chain_id: str, api=None, **overrides) -> dict:
    """Create + validate with a passing panel score. Returns VALIDATED spec."""
    api = api or _api
    spec = make_spec(chain_id, api=api, **overrides)
    return validate_spec(spec["id"], api=api)


def make_agreement(chain_id: str, spec_id: str, api=None, **overrides) -> dict:
    """Create a supply agreement in DRAFT."""
    api = api or _api
    resp = api.create_supply_agreement(
        create_supply_agreement_payload(chain_id, spec_id, **overrides), ACCOUNT
    )
    return get_success_data(resp)


def activate_agreement(agreement_id: str, api=None) -> dict:
    api = api or _api
    resp = api.activate_supply_agreement(agreement_id, ACCOUNT)
    return get_success_data(resp)


def make_active_agreement(chain_id: str, spec_id: str, api=None, **overrides) -> dict:
    """Create + activate. Side effect: a VALIDATED spec locks (PRD §3.4/§3.5)."""
    api = api or _api
    agr = make_agreement(chain_id, spec_id, api=api, **overrides)
    return activate_agreement(agr["id"], api=api)


def make_shortage_event(api=None, **overrides) -> dict:
    api = api or _api
    resp = api.create_shortage_event(create_shortage_event_payload(**overrides), GRM)
    return get_success_data(resp)


# ── Tier 2: intake and readings ──────────────────────────────────────────────
def deliver_lot(contract_id: str, facility_id: str, grower_id: str, api=None, **overrides) -> dict:
    """CONTRACTED-mode intake by the owning grower (PRD §3.2)."""
    api = api or _api
    resp = api.create_potato_lot(
        create_contracted_lot_payload(contract_id, facility_id, **overrides),
        make_grower_headers(grower_id),
    )
    return get_success_data(resp)


def import_lot(shortage_event_id: str, facility_id: str, api=None, **overrides) -> dict:
    """IMPORT-mode intake; reserved to the GrowerRelationsManager (PRD §3.2)."""
    api = api or _api
    resp = api.create_potato_lot(
        create_import_lot_payload(shortage_event_id, facility_id, **overrides), GRM
    )
    return get_success_data(resp)


def record_reading(facility_id: str, api=None, **overrides) -> dict:
    api = api or _api
    resp = api.record_reading(facility_id, create_reading_payload(**overrides), STORAGE)
    return get_success_data(resp)


def set_posture_watch(facility_id: str, recorded_at: str = "2026-09-02T00:00:00Z", api=None) -> dict:
    """Drive a facility to WATCH via a sprout reading at 2.5 (>= 2.0, < 4.0)."""
    return record_reading(
        facility_id,
        api=api,
        recorded_at=recorded_at,
        temperature_f=38.5,
        humidity_pct=90.0,
        co2_pct=3.1,
        sprout_index=2.5,
        disease_incidence_pct=1.0,
    )


def set_posture_quarantined(facility_id: str, recorded_at: str = "2026-09-02T00:00:00Z", api=None) -> dict:
    """Drive a facility to QUARANTINED via a disease reading at 7.0 (>= 6.0)."""
    return record_reading(
        facility_id,
        api=api,
        recorded_at=recorded_at,
        temperature_f=41.0,
        humidity_pct=94.0,
        co2_pct=4.0,
        sprout_index=3.5,
        disease_incidence_pct=7.0,
    )


# ── Tier 3: procurement and sales composite setups ──────────────────────────
def setup_procurement(api=None, contract_overrides: dict = None, facility_overrides: dict = None) -> dict:
    """Clock at the documented start + grower GR-100 + facility CELL-1 +
    an ACTIVE 100-acre x 400 cwt/acre contract @2500c, window
    2026-09-01..2026-10-15. Returns {"grower", "facility", "contract"}."""
    api = api or _api
    set_clock(api=api)
    grower = make_grower(api=api)
    facility = make_facility(api=api, **(facility_overrides or {}))
    contract = make_active_contract(grower["id"], api=api, **(contract_overrides or {}))
    return {"grower": grower, "facility": facility, "contract": contract}


def setup_chain_with_validated_spec(api=None, chain_overrides=None, spec_overrides=None) -> dict:
    """Chain CH-ALPHA (TIER_1) + spec SP-A-1 (STRAIGHT) in VALIDATED."""
    api = api or _api
    chain = make_chain(api=api, **(chain_overrides or {}))
    spec = make_validated_spec(chain["id"], api=api, **(spec_overrides or {}))
    return {"chain": chain, "spec": spec}


def setup_full_pipeline(api=None, agreement_overrides=None, spec_overrides=None,
                        chain_overrides=None) -> dict:
    """The standard end-to-end world used by most run/shipment tests:

    clock + grower + facility + ACTIVE contract + one grade-A lot (1000.0 cwt)
    + line LINE-1 (STRAIGHT/CRINKLE) + chain + VALIDATED STRAIGHT spec +
    ACTIVE agreement (default 10000/wk @299c, which locks the spec).

    Returns a dict with every resource keyed by name.
    """
    api = api or _api
    base = setup_procurement(api=api)
    lot = deliver_lot(base["contract"]["id"], base["facility"]["id"], base["grower"]["id"], api=api)
    line = make_line(api=api)
    cs = setup_chain_with_validated_spec(api=api, chain_overrides=chain_overrides,
                                         spec_overrides=spec_overrides)
    agreement = make_active_agreement(cs["chain"]["id"], cs["spec"]["id"], api=api,
                                      **(agreement_overrides or {}))
    return {
        **base,
        "lot": lot,
        "line": line,
        "chain": cs["chain"],
        "spec": cs["spec"],
        "agreement": agreement,
    }


# ── Tier 4: production run lifecycle shortcuts ───────────────────────────────
def make_run(line_id: str, spec_id: str, agreement_id: str, input_lot_ids: list,
             api=None, **overrides) -> dict:
    """Schedule a run; input lots move IN_STORAGE -> ALLOCATED on success."""
    api = api or _api
    resp = api.create_production_run(
        create_production_run_payload(line_id, spec_id, agreement_id, input_lot_ids, **overrides),
        PLANNER,
    )
    return get_success_data(resp)


def advance_run(run_id: str, times: int = 1, api=None) -> dict:
    """Advance a run ``times`` stages; returns the final run body."""
    api = api or _api
    data = None
    for _ in range(times):
        resp = api.advance_run(run_id, PLANNER)
        data = get_success_data(resp)
    return data


def make_run_in_qa_hold(line_id: str, spec_id: str, agreement_id: str, input_lot_ids: list,
                        api=None, **overrides) -> dict:
    """Create + advance five times: SCHEDULED -> ... -> QA_HOLD, with
    actual_cases computed on entry (PRD §3.6)."""
    api = api or _api
    run = make_run(line_id, spec_id, agreement_id, input_lot_ids, api=api, **overrides)
    return advance_run(run["id"], times=5, api=api)


def make_released_run(line_id: str, spec_id: str, agreement_id: str, input_lot_ids: list,
                      measured_color_units: float = 2.5, api=None, **overrides) -> dict:
    """Run driven to QA_HOLD and released at the spec's target color.
    Input lots become CONSUMED; the agreement's lifetime_released_cases grows."""
    api = api or _api
    run = make_run_in_qa_hold(line_id, spec_id, agreement_id, input_lot_ids, api=api, **overrides)
    resp = api.qa_release_run(run["id"], {"measured_color_units": measured_color_units}, QA)
    return get_success_data(resp)


def setup_released_run(api=None, agreement_overrides=None) -> dict:
    """setup_full_pipeline + run R1 RELEASED over the single grade-A lot
    (620 cases at the STRAIGHT yield of 0.62 cases/cwt over 1000.0 cwt)."""
    api = api or _api
    world = setup_full_pipeline(api=api, agreement_overrides=agreement_overrides)
    run = make_released_run(
        world["line"]["id"], world["spec"]["id"], world["agreement"]["id"],
        [world["lot"]["id"]], api=api,
    )
    return {**world, "run": run}


# ── Tier 5: shipments ────────────────────────────────────────────────────────
def make_shipment(agreement_id: str, lines: list, api=None, **overrides) -> dict:
    """Create a shipment (starts IN_TRANSIT) over RELEASED runs."""
    api = api or _api
    resp = api.create_shipment(create_shipment_payload(agreement_id, lines, **overrides), LOGISTICS)
    return get_success_data(resp)
