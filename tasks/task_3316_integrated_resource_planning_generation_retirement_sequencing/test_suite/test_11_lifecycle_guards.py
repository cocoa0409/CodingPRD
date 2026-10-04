"""Lifecycle guards: invalid transitions, cascade locks, clock auto-transition, reopen compensation (PRD §2.4, §3.1, §3.4, §3.8, §3.9, §3.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_forecast,
    add_position,
    add_portfolio,
    compute_snapshot,
    create_comment_payload,
    create_draft_plan_with_basics,
    create_forecast_payload,
    create_plan,
    file_comment,
    get_plan,
    get_success_data,
    open_plan_for_comment,
    register_candidate,
    register_resource,
    retire_resource,
    set_clock,
    setup_approved_plan,
    setup_plan_rejected,
    setup_plan_under_review,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01
from test_helpers.fixtures import PLANNER, COMMENTER, COMMISSIONER


def test_retire_on_decided_resource_rejected(api):
    """PRD §3.4: "Retiring a unit that is not `ACTIVE` is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/retire_on_decided_resource_rejected
    """
    plan = create_plan(plan_name="IRP Inv")
    resource = register_resource(unit_name="GAS-CT-X", resource_type="GAS_CT",
                                 nameplate_mw=200, in_service_year=2005,
                                 fuel_type="NATURAL_GAS")
    retire_resource(resource["id"], retirement_year=2030, plan_id=plan["id"])

    resp = api.retire_resource(
        resource["id"], {"retirement_year": 2032, "plan_id": plan["id"]}, PLANNER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api.get_resource(resource["id"], PLANNER))
    assert after["status"] == "DECIDED"
    assert after["retirement_year"] == 2030
    assert after["version"] == 2


def test_mothball_from_active_rejected(api):
    """PRD §3.4: "A planner may mothball the unit when its retirement is imminent —
    specifically when `retirement_year` is no more than one calendar year beyond the
    clock's current year — moving it `DECIDED → MOTHBALLED`, a terminal state."

    Design: Corner/state_machines/mothball_from_active_rejected
    """
    resource = register_resource(unit_name="HYDRO-1", resource_type="HYDRO",
                                 nameplate_mw=80, in_service_year=1975, fuel_type="WATER")

    resp = api.mothball_resource(resource["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api.get_resource(resource["id"], PLANNER))
    assert after["status"] == "ACTIVE"


def test_award_on_cancelled_commitment_rejected(api):
    """PRD §3.9: "Award is the commission's act: a `Commissioner` moves a commitment
    `ISSUED → AWARDED`, with the same plan-status gate as issue
    (`ERR_PLAN_NOT_APPROVED` otherwise) and a state gate that rejects award of a
    commitment not in `ISSUED` with `ERR_COMMITMENT_NOT_ISSUABLE` (HTTP 409)."

    Design: Corner/state_machines/award_on_cancelled_commitment_rejected
    """
    plan, _portfolio, _snapshot = setup_approved_plan(plan_name="IRP Aw")
    candidate = register_candidate(candidate_name="K-AW")

    commitment = get_success_data(api.create_commitment(
        plan["id"],
        {"candidate_id": candidate["id"], "committed_mw": 50,
         "solicitation_type": "RFP"},
        PLANNER,
    ))
    validate_success(api.cancel_commitment(commitment["id"], PLANNER))

    resp = api.award_commitment(commitment["id"], COMMISSIONER)
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_NOT_ISSUABLE)

    after = get_success_data(api.get_commitment(commitment["id"], PLANNER))
    assert after["status"] == "CANCELLED"


def test_ack_on_acknowledged_comment_rejected(api):
    """PRD §3.10: "A comment is born `RECEIVED`; a planner may acknowledge it
    (`RECEIVED → ACKNOWLEDGED`, version bumping) only while the plan remains
    `OPEN_FOR_COMMENT`."

    Design: Corner/state_machines/ack_on_acknowledged_comment_rejected
    """
    set_clock(CLOCK_AUG_01)
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP Ack", preferred=False)
    open_plan_for_comment(plan["id"])
    comment = file_comment(plan["id"], commenter_name="C One",
                           commenter_email="c1@example.org", body="Comment body.")

    validate_success(api.acknowledge_comment(plan["id"], comment["id"], PLANNER))

    resp = api.acknowledge_comment(plan["id"], comment["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_success_data(api.get_comment_flat(comment["id"], PLANNER))
    assert after["status"] == "ACKNOWLEDGED"
    assert after["version"] == 2


def test_forecast_lock_bubble_up_on_open_comment(api):
    """PRD §3.1: "Once the plan leaves `DRAFT` for the first time, every one of its
    forecast rows flips `locked` to true, and any further modification of a locked row
    is rejected with `ERR_FORECAST_LOCKED` (HTTP 409)."

    Design: Corner/state_machines/forecast_lock_bubble_up_on_open_comment
    """
    set_clock(CLOCK_AUG_01)
    plan = create_plan(plan_name="IRP Lock")
    forecast = get_success_data(api.create_forecast(
        plan["id"],
        create_forecast_payload(scenario_tag="BASE", forecast_year=2030,
                                residential_mw=100),
        PLANNER,
    ))
    add_portfolio(plan["id"], portfolio_name="PF-Lock")
    open_plan_for_comment(plan["id"])

    resp = api.update_forecast(plan["id"], forecast["id"], {"residential_mw": 120}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_FORECAST_LOCKED)

    after = get_success_data(api.get_forecast(plan["id"], forecast["id"], PLANNER))
    assert after["residential_mw"] == pytest.approx(100, abs=0.005)
    assert after["locked"] is True


def test_portfolio_freeze_blocks_position_add_but_not_snapshot(api):
    """PRD §3.3: "Position add and remove are allowed only while the portfolio is
    `DRAFT`; on a `FROZEN` portfolio they are rejected with `ERR_PORTFOLIO_FROZEN`
    (HTTP 409)."
    PRD §3.5: "Snapshot compute is allowed while the portfolio is `DRAFT` or `FROZEN` —
    recompute-after-flag is precisely how a frozen portfolio's snapshots are refreshed
    after a retirement cascade — even though position add and remove are restricted to
    `DRAFT`."

    Design: Corner/state_machines/portfolio_freeze_blocks_position_add
    """
    plan, portfolio = setup_plan_under_review(plan_name="IRP Frz")
    candidate = register_candidate(candidate_name="K-FRZ", resource_type="WIND",
                                   nameplate_mw=100, online_year=2028,
                                   capex_usd_per_kw=1100, fixed_om_usd_per_kw_year=20,
                                   fuel_type="WIND", build_lead_years=2)

    resp = api.add_position(
        portfolio["id"], {"candidate_id": candidate["id"], "committed_mw": 30}, PLANNER
    )
    validate_error(resp, ApiErrorId.ERR_PORTFOLIO_FROZEN)

    snapshot = compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")
    assert snapshot["forecast_year"] == 2030


def test_decided_to_retired_auto_transition_on_clock(api):
    """PRD §2.4: "Setting the clock forward has a real side effect: any fleet resource
    in `DECIDED` status whose `retirement_year` is less than or equal to the new clock
    calendar year automatically transitions to `RETIRED`, and each auto-transitioned
    resource's `version` increments by 1."

    Design: Corner/state_machines/decided_to_retired_auto_transition_on_clock
    """
    plan = create_plan(plan_name="IRP Auto")
    resource = register_resource(unit_name="COAL-AUTO", resource_type="COAL",
                                 nameplate_mw=300, in_service_year=1990, fuel_type="COAL")
    resource2 = register_resource(unit_name="COAL-LATE", resource_type="COAL",
                                  nameplate_mw=300, in_service_year=1995, fuel_type="COAL")
    retire_resource(resource["id"], retirement_year=2028, plan_id=plan["id"])
    retire_resource(resource2["id"], retirement_year=2035, plan_id=plan["id"])

    set_clock("2028-01-02T00:00:00Z")

    after = get_success_data(api.get_resource(resource["id"], PLANNER))
    assert after["status"] == "RETIRED"
    assert after["version"] == 3

    after2 = get_success_data(api.get_resource(resource2["id"], PLANNER))
    assert after2["status"] == "DECIDED"
    assert after2["version"] == 2


def test_reopen_unfreezes_portfolios_and_unlocks_forecasts(api):
    """PRD §3.8: "The transition `REJECTED → DRAFT` increments `reopen_count` by 1,
    unfreezes every portfolio (`FROZEN → DRAFT`, each portfolio's `version` bumping),
    unlocks every forecast row, clears `preferred_portfolio_id`, `approved_snapshot_id`,
    both comment-window dates, and `submitted_on`, and bumps the plan's `version` —
    returning the plan to a fully editable state for another pass through the cycle."

    Design: Corner/state_machines/reopen_unfreezes_portfolios_and_unlocks_forecasts
    """
    plan, portfolio = setup_plan_rejected(plan_name="IRP Comp")
    candidate = register_candidate(candidate_name="K-COMP", resource_type="WIND",
                                   nameplate_mw=100, online_year=2028,
                                   capex_usd_per_kw=1100, fixed_om_usd_per_kw_year=20,
                                   fuel_type="WIND", build_lead_years=2)

    reopened = validate_success(api.reopen_plan(plan["id"], PLANNER))
    assert reopened["status"] == "DRAFT"
    assert reopened["reopen_count"] == 1
    assert reopened["preferred_portfolio_id"] is None

    portfolio_after = get_success_data(api.get_portfolio(portfolio["id"], PLANNER))
    assert portfolio_after["status"] == "DRAFT"

    resp = api.add_position(
        portfolio["id"], {"candidate_id": candidate["id"], "committed_mw": 25}, PLANNER
    )
    position = validate_success(resp, expected_status=201)
    assert position["selected"] is True
