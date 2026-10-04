"""Entity basics: creation defaults, computed fields, append-only rows, list envelope (PRD §2.2–§2.5, §3.1, §3.3)."""
import pytest

from test_helpers import (
    add_portfolio,
    assert_plan,
    assert_position,
    create_forecast_payload,
    create_plan,
    create_plan_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    register_candidate,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PLANNER


def test_plan_create_returns_defaults_and_common_fields(api):
    """PRD §3.1: "The plan is born in `DRAFT` status with `reopen_count` at 0."
    PRD §2.5: "Every persisted entity carries an `id` — a server-minted UUID with no
    type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional
    digits. Most entities additionally carry `updated_at` (same timestamp format,
    refreshed on every mutation) and `version` (an integer starting at 1, incremented
    by 1 on every mutation of that entity)."

    Design: Corner/entities/plan_create_returns_defaults_and_common_fields
    """
    resp = api.create_plan(
        create_plan_payload(plan_name="Carolinas IRP 2026", cycle_year=2026,
                            planning_horizon_years=15),
        PLANNER,
    )
    plan = validate_success(resp, expected_status=201)
    assert_plan(plan)
    assert plan["status"] == "DRAFT"
    assert plan["reopen_count"] == 0
    assert plan["version"] == 1
    assert plan["approved_snapshot_id"] is None
    assert plan["preferred_portfolio_id"] is None


def test_forecast_computed_fields_ignore_client_input(api):
    """PRD §3.1: "Two totals are computed on every forecast row. The `total_peak_mw` is
    the plain, unweighted sum of the four class contributions. The `effective_load_mw`
    is the figure reliability modeling actually consumes, and it is variant-aware."
    PRD §3.1: "Under the default `COINCIDENT` variant, the effective load is the
    residential contribution at full value, plus the commercial contribution at full
    value, plus the industrial contribution multiplied by an industrial coincidence
    factor of 0.95, plus the electrification contribution at full value (a factor of
    1.00)."

    Design: Corner/entities/forecast_computed_fields_ignore_client_input
    """
    plan = create_plan(plan_name="IRP CF")

    resp = api.create_forecast(
        plan["id"],
        create_forecast_payload(scenario_tag="BASE", forecast_year=2030,
                                residential_mw=1000, commercial_mw=800,
                                industrial_mw=500, electrification_mw=200),
        PLANNER,
    )
    forecast = validate_success(resp, expected_status=201)
    # Unweighted sum vs coincidence-weighted effective load.
    assert forecast["total_peak_mw"] == pytest.approx(2500.00, abs=0.005)
    assert forecast["effective_load_mw"] == pytest.approx(2475.00, abs=0.005)
    assert forecast["locked"] is False


def test_position_append_only_has_no_version_field(api):
    """PRD §2.5: "A `Position` is an append-only junction row and carries only `id` and
    `created_at`; it has no `updated_at` and no `version`, and it is never updated —
    removal is expressed by flipping its `selected` flag."

    Design: Corner/entities/position_append_only_has_no_version_field
    """
    plan = create_plan(plan_name="IRP Pos")
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-Pos")
    candidate = register_candidate(candidate_name="K-POS")

    resp = api.add_position(
        portfolio["id"], {"candidate_id": candidate["id"], "committed_mw": 40}, PLANNER
    )
    position = validate_success(resp, expected_status=201)
    assert_position(position)
    assert position["selected"] is True
    assert position["committed_mw"] == pytest.approx(40, abs=0.005)
    assert is_valid_uuid(position["id"])
    assert is_iso8601_timestamp(position["created_at"])


def test_plan_list_pagination_envelope(api):
    """PRD §2.3: "List endpoints accept the query parameters `limit` and `offset`.
    `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults
    to 0. Every list response reports the applied `limit` and `offset` in `meta`, along
    with `total_count` (the full size of the filtered result set) and `has_more`
    (whether results remain past the current page)."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/plan_list_pagination_envelope
    """
    create_plan(plan_name="IRP Page1")
    create_plan(plan_name="IRP Page2")

    resp = api.list_plans(PLANNER, params={"limit": 1, "offset": 1})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 1
    assert meta["offset"] == 1
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
