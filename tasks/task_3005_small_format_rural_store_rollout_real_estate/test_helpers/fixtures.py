"""Composite setup helpers for the rural store rollout workflow.

Every helper builds its preconditions from scratch through the PRD's own
endpoints, because each test starts against an empty database.  Setup calls go
through the lenient success validator so that a broken precondition surfaces as
"Setup failed" rather than as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_developer_payload,
    create_distribution_center_payload,
    create_existing_store_payload,
    create_rollout_payload,
    create_site_agreement_payload,
    create_store_payload,
    create_trade_area_payload,
)
from .test_users import (
    TEST_USERS,
    make_finance_analyst_headers,
    make_program_admin_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
REAL_ESTATE = TEST_USERS["real_estate_manager_headers"]
NETWORK = TEST_USERS["network_planner_headers"]
OPERATIONS = TEST_USERS["operations_lead_headers"]
FINANCE = TEST_USERS["finance_analyst_headers"]


def _must(data: dict, step: str) -> dict:
    assert isinstance(data, dict) and "id" in data or step == "clock", (
        f"Setup failed at step {step}: {data}"
    )
    return data


# ==========================================================================
# Tier 0 -- single-call helpers
# ==========================================================================
def create_rollout(**overrides) -> dict:
    """Create a rollout program (DRAFT)."""
    data = get_success_data(api.create_rollout(create_rollout_payload(**overrides), ADMIN))
    assert data.get("id"), f"Setup failed creating rollout: {data}"
    return data


def create_active_rollout(**overrides) -> dict:
    """Create a program and activate it.  Returns the program dict."""
    rollout = create_rollout(**overrides)
    data = get_success_data(api.activate_rollout(rollout["id"], ADMIN))
    assert data.get("id"), f"Setup failed activating rollout: {data}"
    return data


def read_rollout(rollout_id: str) -> dict:
    return get_success_data(api.get_rollout(rollout_id, ADMIN))


def set_clock(rollout_id: str, to_iso8601: str) -> dict:
    data = get_success_data(
        api.set_clock(
            {"rollout_program_id": rollout_id, "to_iso8601": to_iso8601}, ADMIN
        )
    )
    return data


def create_trade_area(rollout_id: str, **overrides) -> dict:
    payload = create_trade_area_payload(rollout_program_id=rollout_id, **overrides)
    data = get_success_data(api.create_trade_area(payload, ADMIN))
    assert data.get("id"), f"Setup failed creating trade area: {data}"
    return data


def screen_trade_area(rollout_id: str, trade_area_id: str) -> dict:
    """Screen a trade area with its current version.  Returns the trade area."""
    current = get_success_data(api.get_trade_area(trade_area_id, ADMIN))
    data = get_success_data(
        api.screen_trade_area(
            trade_area_id,
            {
                "rollout_program_id": rollout_id,
                "expected_trade_area_version": current["version"],
            },
            ADMIN,
        )
    )
    assert data.get("id"), f"Setup failed screening trade area {trade_area_id}: {data}"
    return data


def create_qualified_trade_area(rollout_id: str, name: str = "TA-A", **overrides) -> dict:
    """Create a trade area and screen it to QUALIFIED."""
    ta = create_trade_area(rollout_id, name=name, **overrides)
    return screen_trade_area(rollout_id, ta["id"])


def create_store(rollout_id: str, trade_area_id: str, **overrides) -> dict:
    payload = create_store_payload(
        rollout_program_id=rollout_id, trade_area_id=trade_area_id, **overrides
    )
    data = get_success_data(api.create_store(payload, ADMIN))
    assert data.get("id"), f"Setup failed creating store: {data}"
    return data


def create_existing_store(
    rollout_id: str, trade_area_id: str, name: str = "Legacy X", **overrides
) -> dict:
    payload = create_existing_store_payload(
        rollout_program_id=rollout_id, trade_area_id=trade_area_id, name=name, **overrides
    )
    data = get_success_data(api.create_store(payload, ADMIN))
    assert data.get("id"), f"Setup failed registering existing store: {data}"
    return data


def read_store(store_id: str) -> dict:
    return get_success_data(api.get_store(store_id, ADMIN))


def set_volume_index(rollout_id: str, store_id: str, volume_index) -> dict:
    data = get_success_data(
        api.update_store(
            store_id,
            {"rollout_program_id": rollout_id, "volume_index": volume_index},
            NETWORK,
        )
    )
    assert data.get("id"), f"Setup failed updating volume_index: {data}"
    return data


def select_format(rollout_id: str, store_id: str) -> dict:
    """Run format selection with the store's current version."""
    current = read_store(store_id)
    data = get_success_data(
        api.select_format(
            store_id,
            {
                "rollout_program_id": rollout_id,
                "expected_store_version": current["version"],
            },
            REAL_ESTATE,
        )
    )
    assert data.get("id"), f"Setup failed selecting format for {store_id}: {data}"
    return data


def create_pipeline_store(rollout_id: str, trade_area_id: str, **overrides) -> dict:
    """Store in a QUALIFIED trade area with format selected (still PROPOSED)."""
    store = create_store(rollout_id, trade_area_id, **overrides)
    return select_format(rollout_id, store["id"])


def create_developer(rollout_id: str, name: str = "DevCo") -> dict:
    data = get_success_data(
        api.create_developer(
            create_developer_payload(rollout_program_id=rollout_id, name=name), ADMIN
        )
    )
    assert data.get("id"), f"Setup failed creating developer: {data}"
    return data


def create_site_agreement(rollout_id: str, store_id: str, developer_id: str, **overrides) -> dict:
    payload = create_site_agreement_payload(
        rollout_program_id=rollout_id,
        store_id=store_id,
        developer_id=developer_id,
        **overrides,
    )
    data = get_success_data(api.create_site_agreement(payload, REAL_ESTATE))
    assert data.get("id"), f"Setup failed creating site agreement: {data}"
    return data


def execute_agreement(rollout_id: str, agreement_id: str) -> dict:
    data = get_success_data(
        api.execute_agreement(agreement_id, {"rollout_program_id": rollout_id}, REAL_ESTATE)
    )
    assert data.get("id"), f"Setup failed executing agreement {agreement_id}: {data}"
    return data


def activate_agreement(rollout_id: str, agreement_id: str) -> dict:
    data = get_success_data(
        api.activate_agreement(agreement_id, {"rollout_program_id": rollout_id}, REAL_ESTATE)
    )
    assert data.get("id"), f"Setup failed activating agreement {agreement_id}: {data}"
    return data


def record_delivery(rollout_id: str, agreement_id: str, actual_delivery_date: str) -> dict:
    data = get_success_data(
        api.record_delivery(
            agreement_id,
            {
                "rollout_program_id": rollout_id,
                "actual_delivery_date": actual_delivery_date,
            },
            REAL_ESTATE,
        )
    )
    assert data.get("id"), f"Setup failed recording delivery for {agreement_id}: {data}"
    return data


def create_distribution_center(rollout_id: str, name: str = "D", **overrides) -> dict:
    data = get_success_data(
        api.create_distribution_center(
            create_distribution_center_payload(
                rollout_program_id=rollout_id, name=name, **overrides
            ),
            NETWORK,
        )
    )
    assert data.get("id"), f"Setup failed creating DC: {data}"
    return data


def create_dc_assignment(
    rollout_id: str, store_id: str, dc_id: str, **overrides
) -> dict:
    payload = {
        "rollout_program_id": rollout_id,
        "store_id": store_id,
        "distribution_center_id": dc_id,
        "stem_miles": overrides.pop("stem_miles", 90),
        "deliveries_per_week": overrides.pop("deliveries_per_week", 1),
    }
    data = get_success_data(api.create_dc_assignment(payload, NETWORK))
    assert data.get("id"), f"Setup failed assigning DC: {data}"
    return data


def create_route_plan(rollout_id: str, store_id: str) -> dict:
    data = get_success_data(
        api.create_route_plan(
            {"rollout_program_id": rollout_id, "store_id": store_id}, NETWORK
        )
    )
    assert data.get("id"), f"Setup failed creating route plan: {data}"
    return data


def create_opening_plan(
    rollout_id: str,
    store_id: str,
    opening_date: str = "2026-12-05T00:00:00Z",
    peak_season: bool = False,
) -> dict:
    data = get_success_data(
        api.create_opening_plan(
            {
                "rollout_program_id": rollout_id,
                "store_id": store_id,
                "opening_date": opening_date,
                "peak_season": peak_season,
            },
            OPERATIONS,
        )
    )
    assert data.get("id"), f"Setup failed creating opening plan: {data}"
    return data


def lock_opening_plan(rollout_id: str, opening_plan_id: str) -> dict:
    data = get_success_data(
        api.lock_opening_plan(
            opening_plan_id, {"rollout_program_id": rollout_id}, OPERATIONS
        )
    )
    assert data.get("id"), f"Setup failed locking opening plan {opening_plan_id}: {data}"
    return data


def create_cannibalization_study(rollout_id: str, store_id: str, overlap_entries) -> dict:
    data = get_success_data(
        api.create_cannibalization_study(
            {
                "rollout_program_id": rollout_id,
                "store_id": store_id,
                "overlap_entries": overlap_entries,
            },
            FINANCE,
        )
    )
    assert data.get("id"), f"Setup failed creating cannibalization study: {data}"
    return data


def finalize_study(rollout_id: str, study_id: str) -> dict:
    data = get_success_data(
        api.finalize_cannibalization_study(
            study_id, {"rollout_program_id": rollout_id}, FINANCE
        )
    )
    assert data.get("id"), f"Setup failed finalizing study {study_id}: {data}"
    return data


def create_capital_project(rollout_id: str, kind: str, store_id: str, **overrides) -> dict:
    payload = {
        "rollout_program_id": rollout_id,
        "kind": kind,
        "store_id": store_id,
    }
    payload.update(overrides)
    data = get_success_data(api.create_capital_project(payload, FINANCE))
    assert data.get("id"), f"Setup failed creating capital project: {data}"
    return data


def submit_capital_project(
    rollout_id: str, project_id: str, analyst_user_id: str | None = None
) -> dict:
    headers = (
        make_finance_analyst_headers(analyst_user_id)
        if analyst_user_id is not None
        else FINANCE
    )
    data = get_success_data(
        api.submit_capital_project(
            project_id, {"rollout_program_id": rollout_id}, headers
        )
    )
    assert data.get("id"), f"Setup failed submitting capital project {project_id}: {data}"
    return data


def decide_capital_project(
    rollout_id: str, project_id: str, decision: str, admin_user_id: str | None = None
) -> dict:
    """Decide with the program's current version as the OCC expectation."""
    program = read_rollout(rollout_id)
    headers = (
        make_program_admin_headers(admin_user_id) if admin_user_id is not None else ADMIN
    )
    data = get_success_data(
        api.decide_capital_project(
            project_id,
            {
                "rollout_program_id": rollout_id,
                "decision": decision,
                "expected_program_version": program["version"],
            },
            headers,
        )
    )
    assert data.get("id"), f"Setup failed deciding capital project {project_id}: {data}"
    return data


# ==========================================================================
# Tier 2/3 -- composite scenarios
# ==========================================================================
def setup_active_program_with_qualified_area(
    budget_cents: int = 2000000000,
    name: str = "P",
    area_name: str = "C",
    area_overrides: dict | None = None,
):
    """ACTIVE program + QUALIFIED trade area.  Returns (rollout, trade_area)."""
    rollout = create_active_rollout(name=name, new_build_capital_budget_cents=budget_cents)
    ta = create_qualified_trade_area(
        rollout["id"], name=area_name, **(area_overrides or {})
    )
    return rollout, ta


def setup_store_with_format(rollout_id: str, trade_area_id: str, **overrides) -> dict:
    return create_pipeline_store(rollout_id, trade_area_id, **overrides)


def setup_store_site_control(
    rollout_id: str,
    store_id: str,
    developer_name: str = "DevCo",
    committed_delivery_date: str = "2026-11-01T00:00:00Z",
    **overrides,
):
    """Store with an EXECUTED agreement (store in SITE_CONTROL).

    Returns (developer, agreement).
    """
    developer = create_developer(rollout_id, name=developer_name)
    agreement = create_site_agreement(
        rollout_id,
        store_id,
        developer["id"],
        committed_delivery_date=committed_delivery_date,
        **overrides,
    )
    agreement = execute_agreement(rollout_id, agreement["id"])
    return developer, agreement


def setup_store_under_construction(
    rollout_id: str,
    store_id: str,
    developer_name: str = "DevCo",
    committed_delivery_date: str = "2026-11-01T00:00:00Z",
    **overrides,
):
    """Store UNDER_CONSTRUCTION with an ACTIVE agreement.

    Returns (developer, agreement).
    """
    developer, agreement = setup_store_site_control(
        rollout_id,
        store_id,
        developer_name=developer_name,
        committed_delivery_date=committed_delivery_date,
        **overrides,
    )
    agreement = activate_agreement(rollout_id, agreement["id"])
    return developer, agreement
