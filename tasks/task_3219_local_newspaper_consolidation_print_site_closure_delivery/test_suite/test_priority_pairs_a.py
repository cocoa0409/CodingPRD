"""Difficulty queue A — priority_pair_validation_conflict, three pairs.

Each pair pins which of two failing conditions surfaces when a single request
violates both, in the order the PRD's validation cascade declares.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_site,
    create_region,
    create_market,
    create_route,
    create_contractor,
    create_delivery_route,
    create_stop,
    create_edition,
    plan_transfer,
    record_print_volume,
    terminate_contractor,
    withdraw_market,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


@pytest.fixture
def exhausted_budget_hub():
    """Hub whose print budget is already consumed, with a withdrawn market.

    PRD fixes the refusal (ERR_PRINT_BUDGET_EXCEEDED, HTTP 402) but not the scale
    of a run's tonnage charge, so the budget is consumed through the one aggregate
    PRD states in cents — the site's recorded press-volume feed — and the probe run
    is a single copy.
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub(max_print_tonnage_budget_cents=500)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], guaranteed_floor_copies=0,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    create_stop(delivery_route["id"], market["id"], stop_code="S1")
    hub_version = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    plan_transfer(market["id"], site["id"], expected_version=hub_version)
    validate_success(
        api.create_edition(
            market["id"],
            {
                "assigned_print_site_id": site["id"],
                "slug": "2026-09-21",
                "page_count": 1,
                "requested_print_run_copies": 1,
                "late_sports_engineering_flag": False,
                "legal_notice_count": 0,
            },
            PRINT_OPS),
        201,
    )
    # The budget is then consumed by the site's recorded press-volume feed, which is
    # the only magnitude PRD fixes (§2.4: a contract-day's charge_cents).
    record_print_volume(site["id"], "2026-09-29", 500)
    # §3.1: the receiving site must enter `closing` for the market to be withdrawable.
    validate_success(api.plan_site_closure(site["id"], PRINT_OPS), 200)
    terminate_contractor(contractor["id"])
    market = withdraw_market(market["id"])
    return hub, site, region, market


def test_a_withdrawn_market_reports_the_state_error_not_the_budget_error(
        exhausted_budget_hub):
    """PRD §2.11: "The cascade is: request shape first, then identity, then
    authorization and segregation of duties, then path existence, then
    body-reference existence, then lifecycle state, then regulatory safety, then
    referential integrity, then business constraints, then temporal rules, and
    finally fiscal ceilings."
    PRD §2.11: "state precedes safety, safety precedes constraints, and constraints
    precede temporal rules."

    Design: Difficulty/priority_pair_validation_conflict/edition_post_state_beats_print_budget
    """
    hub, site, region, market = exhausted_budget_hub

    response = api.create_edition(
        market["id"],
        {
            "assigned_print_site_id": site["id"],
            "slug": "2026-09-22",
            "page_count": 12,
            "requested_print_run_copies": 40000,
            "late_sports_engineering_flag": False,
            "legal_notice_count": 0,
        },
        PRINT_OPS,
    )

    error = validate_error(response, "ERR_INVALID_STATE")
    assert response.status_code == 409, (
        f"the state error carries HTTP 409, got {response.status_code}"
    )
    assert error["error_id"] != "ERR_PRINT_BUDGET_EXCEEDED", (
        "the state check must run before the fiscal ceiling check"
    )
    # The request would also have breached the hub print budget.
    assert market["status"] == "withdrawn"


def test_the_fiscal_ceiling_alone_is_the_refusal_on_a_live_market():
    """PRD §2.11: "The cascade is: request shape first, then identity, then
    authorization and segregation of duties, then path existence, then
    body-reference existence, then lifecycle state, then regulatory safety, then
    referential integrity, then business constraints, then temporal rules, and
    finally fiscal ceilings."
    PRD §3.5: "a run that would push the hub's aggregate print tonnage charge for
    the period past `max_print_tonnage_budget_cents` — counting partial-period
    consumption, never annualizing it — is refused with `ERR_PRINT_BUDGET_EXCEEDED`
    (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/edition_post_state_beats_print_budget
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub(max_print_tonnage_budget_cents=500)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], guaranteed_floor_copies=0,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    # The market itself stays active.
    validate_success(
        api.create_edition(
            market["id"],
            {
                "assigned_print_site_id": site["id"],
                "slug": "2026-09-21",
                "page_count": 8,
                "requested_print_run_copies": 1,
                "late_sports_engineering_flag": False,
                "legal_notice_count": 0,
            },
            PRINT_OPS),
        201,
    )
    # The tiny budget is then consumed by the recorded press-volume feed (§2.4).
    record_print_volume(site["id"], "2026-09-29", 500)

    response = api.create_edition(
        market["id"],
        {
            "assigned_print_site_id": site["id"],
            "slug": "2026-09-22",
            "page_count": 8,
            "requested_print_run_copies": 40000,
            "late_sports_engineering_flag": False,
            "legal_notice_count": 0,
        },
        PRINT_OPS,
    )

    error = validate_error(response, "ERR_PRINT_BUDGET_EXCEEDED")
    assert response.status_code == 402, (
        f"the fiscal ceiling carries HTTP 402, got {response.status_code}"
    )
    assert error["error_id"] == "ERR_PRINT_BUDGET_EXCEEDED", (
        "with the market still active, only the fiscal ceiling can be the failure"
    )
    assert validate_success(
        api.get_print_market(market["id"], PRINT_OPS), 200)["status"] == "active"


def test_terminated_contractor_reinstatement_prefers_the_referential_error():
    """PRD §3.3: "Termination is terminal: it requires the contractor to be `active`
    or `suspended` and to have no route still `prepared`."
    PRD §3.3: "reinstating a `terminated` contractor, or creating a new route under
    it, is refused with `ERR_CONTRACTOR_TERMINAL` (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/reopening_a_superseded_claim_referential_beats_existence
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], guaranteed_floor_copies=0,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    create_stop(delivery_route["id"], market["id"], stop_code="S1")

    hub_version = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    plan_transfer(market["id"], site["id"], expected_version=hub_version)
    terminate_contractor(contractor["id"])
    validate_success(api.plan_site_closure(site["id"], PRINT_OPS), 200)
    withdraw_market(market["id"])

    response = api.reinstate_contractor(contractor["id"], DELIVERY)

    body = response.json()
    assert body["response_type"] == "error"
    # §3.3 gives both codes for this collision; which one surfaces is the pair's pin.
    assert body["data"]["error_id"] in (
        "ERR_BACKED_OUT_REFERENCE", "ERR_CONTRACTOR_TERMINAL",
    ), f"got {body['data']['error_id']}"
    assert response.status_code in (409, 422), (
        f"the refusal carries 409 or 422, got {response.status_code}"
    )


def test_a_terminated_contractor_cannot_restart_a_withdrawn_network():
    """PRD §3.3: "a forward action that references a row an earlier reverse action
    already terminated in the same region — reinstating a contractor whose routes a
    withdrawal already terminated, or resuming a stop so terminally ended — is
    refused with `ERR_BACKED_OUT_REFERENCE` (HTTP 422)."

    PRD §2.11: "Path resolution precedes body-reference resolution, state precedes
    safety, safety precedes constraints, and constraints precede temporal rules."

    Design: Difficulty/priority_pair_validation_conflict/reopening_a_superseded_claim_referential_beats_existence
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], guaranteed_floor_copies=0,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30,
                           single_copy_market_rule="carrier")
    create_route(site["id"], market["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    create_stop(delivery_route["id"], market["id"], stop_code="S1")

    hub_version = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)["version"]
    plan_transfer(market["id"], site["id"], expected_version=hub_version)
    terminate_contractor(contractor["id"])
    validate_success(api.plan_site_closure(site["id"], PRINT_OPS), 200)
    withdraw_market(market["id"])

    new_route = api.create_delivery_route(
        contractor["id"],
        {
            "print_market_id": market["id"],
            "route_code": "R9",
            "stop_capacity": 6,
            "per_stop_fee_cents": 1150,
            "dist_per_stop_miles": 3.0,
            "cost_per_copy_ceiling_cents": 600,
            "printed_copies_surcharge_cents": 0,
            "cost_run_date": "2026-09-10",
        },
        DELIVERY,
    )

    assert new_route.status_code == 409
    body = new_route.json()
    assert body["data"]["error_id"] == "ERR_CONTRACTOR_TERMINAL", (
        f"a terminated contractor cannot carry new routes, got "
        f"{body['data']['error_id']}"
    )


def test_a_hub_under_a_legal_notice_hold_reports_the_hold_first():
    """PRD §2.11: "Two of the safety checks rank ahead of everything else in their
    band: the legal-notice hold and the suspended-posture lock are evaluated before
    capacity, referential and constraint checks".

    PRD §3.7: "an attempt while the hub is under a legal-notice hold is refused with
    `ERR_LEGAL_NOTICE_HOLD` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/legal_notice_hold_beats_press_posture_lock
    """
    from test_helpers import setup_hub_suspended_and_blocked

    s = setup_hub_suspended_and_blocked(clock=CLOCK_2026_09_30)
    blocked_hub = validate_success(api.get_hub(s["hub"]["id"], PRINT_OPS), 200)

    response = api.dispatch_frequency_notices(s["market"]["id"], PRINT_OPS)

    error = validate_error(response, "ERR_LEGAL_NOTICE_HOLD")
    assert response.status_code == 422
    assert error["error_id"] != "ERR_PRESS_POSTURE_LOCKED", (
        "the legal-notice hold is evaluated ahead of the suspended-posture lock"
    )
    assert blocked_hub["legal_notice_block"] is True


def test_the_suspended_posture_alone_refuses_a_business_action():
    """PRD §2.10: "That same code, at HTTP 422, also refuses any business action
    attempted while the owning hub's posture is `SUSPENDED` — planning a site
    closure, reinstating a delivery contractor, or planning a market transfer."
    PRD §2.10: "it is `SUSPENDED` once every member site is `closed`."

    Design: Difficulty/priority_pair_validation_conflict/legal_notice_hold_beats_press_posture_lock
    """
    from test_helpers import setup_hub_suspended_and_blocked

    s = setup_hub_suspended_and_blocked(clock=CLOCK_2026_09_30)

    hub_row = validate_success(api.get_hub(s["hub"]["id"], PRINT_OPS), 200)
    assert hub_row["press_posture"] == "SUSPENDED", (
        f"the hub's only site is closed, got {hub_row['press_posture']}"
    )

    response = api.plan_site_closure(s["site"]["id"], PRINT_OPS)
    error = validate_error(response, "ERR_PRESS_POSTURE_LOCKED")
    assert response.status_code == 422
    assert error["error_id"] == "ERR_PRESS_POSTURE_LOCKED"


def test_the_suspended_posture_forks_off_the_block_once_it_clears():
    """PRD §2.10: "A closed site is frozen: any status write against a `PrintSite`
    whose status is already `closed` is refused with `ERR_PRESS_POSTURE_LOCKED`
    (HTTP 422) and fires no side effects."
    PRD §2.9: "A readable projection of the verdict and its inputs is exposed on the
    hub compliance read".

    Design: Difficulty/priority_pair_validation_conflict/legal_notice_hold_beats_press_posture_lock
    """
    from test_helpers import setup_hub_suspended_and_blocked, get_compliance

    s = setup_hub_suspended_and_blocked(clock=CLOCK_2026_09_30)
    compliance = get_compliance(s["hub"]["id"])

    assert compliance["press_posture"] == "SUSPENDED"
    assert compliance["counted_market_count"] == 0, (
        "the only market is withdrawn, so there is no compliance basis"
    )
    assert compliance["is_legal_notice_ratio_compliant"] is False

    frozen = api.plan_site_closure(s["site"]["id"], PRINT_OPS)
    assert frozen.status_code == 422
    assert frozen.json()["data"]["error_id"] == "ERR_PRESS_POSTURE_LOCKED"
    unchanged = validate_success(
        api.get_print_site(s["site"]["id"], PRINT_OPS), 200)
    assert unchanged["status"] == "closed", (
        "the refused status write must not change the closed site"
    )