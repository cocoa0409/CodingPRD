"""Offtake contracting: OCC on the project version, the negotiation cycle,
the price floor, and validation priority."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_exercised_instrument,
    create_offtake_payload,
    create_project,
    get_success_data,
    validate_error,
    validate_success,
)


def test_offtake_create_stale_project_version(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §2.7: "When opening an offtake negotiation against a project, the
    request must carry `expected_project_version`, the client-side last
    observed `version` of the project. If the project's current `version` has
    advanced beyond that value ... the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412), since the current writer's view of the
    project is stale."

    Design: Corner/cross_cutting_complexity_layers/offtake_create_stale_project_version
    """
    project = create_project(name="OCC Farm", technology="SOLAR",
                             target_capacity_mw=25, resource_class="A")
    pid = project["id"]
    stale_version = project["version"]
    create_exercised_instrument(pid, parcel_id="PCL-O1",
                                start_date="2026-09-01T00:00:00Z",
                                end_date="2028-09-01T00:00:00Z")
    # Any project mutation advances the version past the captured one.
    get_success_data(
        api.transition_project(pid, {"to": "SITE_SECURED"}, developer_admin_headers)
    )
    resp = api.create_offtake_agreement(
        pid,
        create_offtake_payload(stale_version, base_price_usd_mwh=42.00),
        origination_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = get_success_data(api.get_project(pid, developer_admin_headers))["version"]
    created = validate_success(
        api.create_offtake_agreement(
            pid,
            create_offtake_payload(fresh_version, base_price_usd_mwh=42.00),
            origination_manager_headers,
        ),
        expected_status=201,
    )
    assert created["status"] == "NEGOTIATING"


def test_offtake_negotiation_counter_cycle(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.3: "Moving from `NEGOTIATING` to `COUNTERED` increments the
    agreement's `counter_count` (which starts at 0), and moving from
    `COUNTERED` back to `NEGOTIATING` increments it again — each direction of
    the loop counts one round. On either transition the payload may supply a
    replacement `base_price_usd_mwh`, which overwrites the agreement's price
    when present."

    Design: Difficulty/non_linear_state_machine/offtake_negotiation_counter_cycle
    """
    project = create_project(name="Cycle Farm", target_capacity_mw=100, resource_class="B")
    pid = project["id"]
    agreement = validate_success(
        api.create_offtake_agreement(
            pid,
            create_offtake_payload(project["version"], buyer_type="CORPORATE",
                                   base_price_usd_mwh=38.00, term_years=12,
                                   delivery_start_date="2028-06-01T00:00:00Z"),
            origination_manager_headers,
        ),
        expected_status=201,
    )
    aid = agreement["id"]
    countered = get_success_data(
        api.transition_offtake_agreement(
            aid, {"to": "COUNTERED", "base_price_usd_mwh": 41.50}, origination_manager_headers
        )
    )
    assert countered["counter_count"] == 1
    back = get_success_data(
        api.transition_offtake_agreement(aid, {"to": "NEGOTIATING"}, origination_manager_headers)
    )
    assert back["counter_count"] == 2
    countered2 = get_success_data(
        api.transition_offtake_agreement(aid, {"to": "COUNTERED"}, origination_manager_headers)
    )
    assert countered2["counter_count"] == 3
    executed = get_success_data(
        api.transition_offtake_agreement(aid, {"to": "EXECUTED"}, origination_manager_headers)
    )
    assert executed["status"] == "EXECUTED"
    assert executed["counter_count"] == 3
    # Mid-cycle price revision retained.
    assert executed["base_price_usd_mwh"] == pytest.approx(41.50, abs=0.001)


def test_offtake_counter_cycle_without_price_revision_keeps_price(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.3: "On either transition the payload may supply a replacement
    `base_price_usd_mwh`, which overwrites the agreement's price when present."

    Design: Difficulty/non_linear_state_machine/offtake_negotiation_counter_cycle
    """
    project = create_project(name="Cycle Farm 2", target_capacity_mw=80)
    pid = project["id"]
    agreement = validate_success(
        api.create_offtake_agreement(
            pid,
            create_offtake_payload(project["version"], base_price_usd_mwh=36.25),
            origination_manager_headers,
        ),
        expected_status=201,
    )
    aid = agreement["id"]
    get_success_data(
        api.transition_offtake_agreement(aid, {"to": "COUNTERED"}, origination_manager_headers)
    )
    back = get_success_data(
        api.transition_offtake_agreement(aid, {"to": "NEGOTIATING"}, origination_manager_headers)
    )
    # No replacement supplied on either transition: price unchanged.
    assert back["counter_count"] == 2
    assert back["base_price_usd_mwh"] == pytest.approx(36.25, abs=0.001)


def test_state_beats_fiscal_on_terminated_offtake(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §2.9: "then from-state validity of the requested transition
    (priority 6, `ERR_INVALID_STATE`) ... then structural constraints ...
    (priority 9 ... `ERR_ACTIVE_OFFTAKE_EXISTS`) ... then the money rules
    (priority 11 — `ERR_PRICE_FLOOR_BREACH` ...)".
    PRD §3.3: "Termination is permitted from any status other than `EXPIRED`
    or `TERMINATED` (an attempt from either fails with `ERR_INVALID_STATE`)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_terminated_offtake
    """
    project = create_project(name="Prio Farm A", technology="SOLAR",
                             target_capacity_mw=50, resource_class="B")
    pid = project["id"]
    agreement = validate_success(
        api.create_offtake_agreement(
            pid,
            create_offtake_payload(project["version"], base_price_usd_mwh=30.00,
                                   escalator_pct=1.5, term_years=10),
            origination_manager_headers,
        ),
        expected_status=201,
    )
    aid = agreement["id"]
    get_success_data(
        api.transition_offtake_agreement(aid, {"to": "TERMINATED"}, origination_manager_headers)
    )
    # Both a from-state violation (TERMINATED is terminal) and a price-floor
    # breach: the higher-priority state error wins.
    resp = api.transition_offtake_agreement(
        aid, {"to": "EXECUTED", "base_price_usd_mwh": 15.00}, origination_manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api.get_offtake_agreement(aid, origination_manager_headers))
    assert current["status"] == "TERMINATED"
    assert current["base_price_usd_mwh"] == pytest.approx(30.00, abs=0.001)


def test_execute_below_floor_alone_breaches_price_floor(
    api, developer_admin_headers, origination_manager_headers
):
    """PRD §3.3: "First, the agreement's `base_price_usd_mwh` must be at least
    20.00 dollars per MWh — a price below the floor fails with
    `ERR_PRICE_FLOOR_BREACH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_terminated_offtake
    """
    project = create_project(name="Floor Farm", target_capacity_mw=40)
    pid = project["id"]
    agreement = validate_success(
        api.create_offtake_agreement(
            pid,
            create_offtake_payload(project["version"], base_price_usd_mwh=19.99),
            origination_manager_headers,
        ),
        expected_status=201,
    )
    resp = api.transition_offtake_agreement(
        agreement["id"], {"to": "EXECUTED"}, origination_manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_PRICE_FLOOR_BREACH)
