"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints: the harness restarts the server before every test, so each test
starts against an empty database. All roles use opaque X-User-ID values per
PRD §2.1, so the shared TEST_USERS headers are used throughout, with
make_*_headers builders reserved for SoD scenarios that need a specific id.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLERK_1
from .factories import (
    create_ancillary_product_payload,
    create_club_payload,
    create_household_member_payload,
    create_membership_payload,
    create_part_stock_payload,
    create_primary_member_payload,
    create_provider_payload,
    create_service_call_payload,
    create_settlement_period_payload,
    create_tier_payload,
    unique_email,
)
from .test_users import TEST_USERS, make_settlement_clerk_headers

ADMIN = TEST_USERS["club_admin_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
DISP = TEST_USERS["dispatcher_headers"]
POPS = TEST_USERS["provider_ops_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]
FIN = TEST_USERS["federation_finance_headers"]
AGENT = TEST_USERS["agent_headers"]


def _setup_fail(step: str, resp) -> AssertionError:
    body = ""
    try:
        body = resp.text
    except Exception:
        pass
    return AssertionError(f"Setup failed at {step}: status={getattr(resp, 'status_code', '?')} body={body}")


def set_clock(to_iso8601: str) -> None:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    if resp.status_code != 200:
        raise _setup_fail("set_clock", resp)


def create_club(**overrides) -> Dict[str, Any]:
    resp = api_client.create_club(create_club_payload(**overrides), ADMIN)
    if resp.status_code != 201:
        raise _setup_fail("create_club", resp)
    return get_success_data(resp)


def create_tier(code: str = "CLASSIC", **overrides) -> Dict[str, Any]:
    resp = api_client.create_tier(create_tier_payload(code, **overrides), ADMIN)
    if resp.status_code != 201:
        raise _setup_fail("create_tier", resp)
    return get_success_data(resp)


def create_membership(home_club_id: str, tier_code: str = "CLASSIC", **overrides) -> Dict[str, Any]:
    resp = api_client.create_membership(create_membership_payload(home_club_id, tier_code, **overrides), MSR)
    if resp.status_code != 201:
        raise _setup_fail("create_membership", resp)
    return get_success_data(resp)


def add_primary_member(membership_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.add_household_member(membership_id, create_primary_member_payload(**overrides), MSR)
    if resp.status_code != 201:
        raise _setup_fail("add_primary_member", resp)
    return get_success_data(resp)


def add_household_member(membership_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.add_household_member(membership_id, create_household_member_payload(**overrides), MSR)
    if resp.status_code != 201:
        raise _setup_fail("add_household_member", resp)
    return get_success_data(resp)


def create_provider(servicing_club_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_provider(create_provider_payload(servicing_club_id, **overrides), ADMIN)
    if resp.status_code != 201:
        raise _setup_fail("create_provider", resp)
    return get_success_data(resp)


def create_part_stock(provider_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_part_stock(provider_id, create_part_stock_payload(**overrides), ADMIN)
    if resp.status_code != 201:
        raise _setup_fail("create_part_stock", resp)
    return get_success_data(resp)


def create_service_call(membership_id: str, requesting_member_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_service_call(
        create_service_call_payload(membership_id, requesting_member_id, **overrides), DISP
    )
    if resp.status_code != 201:
        raise _setup_fail("create_service_call", resp)
    return get_success_data(resp)


def dispatch_call(call_id: str, expected_version: int) -> Dict[str, Any]:
    """Dispatch a call and require a Dispatch to be created (non-empty pool)."""
    resp = api_client.dispatch_service_call(call_id, {"expected_service_call_version": expected_version}, DISP)
    if resp.status_code != 200:
        raise _setup_fail("dispatch_call", resp)
    data = get_success_data(resp)
    if not isinstance(data, dict) or "id" not in data:
        raise AssertionError(f"Setup failed at dispatch_call: expected a Dispatch body, got {data!r}")
    return data


def accept_dispatch(dispatch_id: str, en_route: bool = True) -> Dict[str, Any]:
    resp = api_client.accept_dispatch(dispatch_id, {"en_route": en_route}, POPS)
    if resp.status_code != 200:
        raise _setup_fail("accept_dispatch", resp)
    return get_success_data(resp)


def arrive_dispatch(dispatch_id: str) -> Dict[str, Any]:
    resp = api_client.arrive_dispatch(dispatch_id, POPS)
    if resp.status_code != 200:
        raise _setup_fail("arrive_dispatch", resp)
    return get_success_data(resp)


def complete_dispatch(dispatch_id: str, **payload) -> Dict[str, Any]:
    resp = api_client.complete_dispatch(dispatch_id, payload, POPS)
    if resp.status_code != 200:
        raise _setup_fail("complete_dispatch", resp)
    return get_success_data(resp)


def fail_dispatch(dispatch_id: str, failure_reason: str = "PROVIDER_DECLINED") -> Dict[str, Any]:
    resp = api_client.fail_dispatch(dispatch_id, {"failure_reason": failure_reason}, POPS)
    if resp.status_code != 200:
        raise _setup_fail("fail_dispatch", resp)
    return get_success_data(resp)


def create_ancillary_product(**overrides) -> Dict[str, Any]:
    resp = api_client.create_ancillary_product(create_ancillary_product_payload(**overrides), ADMIN)
    if resp.status_code != 201:
        raise _setup_fail("create_ancillary_product", resp)
    return get_success_data(resp)


def create_ancillary_sale(membership_id: str, product_id: str, agent_headers=None) -> Dict[str, Any]:
    resp = api_client.create_ancillary_sale(
        {"membership_id": membership_id, "product_id": product_id}, agent_headers or AGENT
    )
    if resp.status_code != 201:
        raise _setup_fail("create_ancillary_sale", resp)
    return get_success_data(resp)


def create_settlement_period(servicing_club_id: str, **overrides) -> Dict[str, Any]:
    resp = api_client.create_settlement_period(
        create_settlement_period_payload(servicing_club_id, **overrides), CLERK
    )
    if resp.status_code != 201:
        raise _setup_fail("create_settlement_period", resp)
    return get_success_data(resp)


def get_membership(membership_id: str) -> Dict[str, Any]:
    resp = api_client.get_membership(membership_id, MSR)
    if resp.status_code != 200:
        raise _setup_fail("get_membership", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1/2: club + tier + membership scenario bases
# ---------------------------------------------------------------------------

def setup_club_and_tiers(tiers: Optional[List[str]] = None, tier_overrides: Optional[Dict[str, dict]] = None,
                         club_overrides: Optional[dict] = None) -> Dict[str, Any]:
    """One ACTIVE club (default code NCA, territory [CA]) plus the named tiers.

    Returns {"club": club, "tiers": {code: tier}}.
    """
    club = create_club(**(club_overrides or {}))
    created: Dict[str, Any] = {}
    for code in (tiers or ["CLASSIC"]):
        created[code] = create_tier(code, **(tier_overrides or {}).get(code, {}))
    return {"club": club, "tiers": created}


def setup_membership_scenario(tier_code: str = "CLASSIC", with_primary: bool = True,
                              club_overrides: Optional[dict] = None,
                              tier_overrides: Optional[dict] = None,
                              tiers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Club + tier(s) + ACTIVE membership (+ optional primary household row).

    Returns {"club", "tiers", "membership", "primary"} — "primary" is None when
    with_primary is False.
    """
    tier_codes = tiers or [tier_code]
    base = setup_club_and_tiers(tier_codes, {tier_code: (tier_overrides or {})}, club_overrides)
    membership = create_membership(base["club"]["id"], tier_code)
    primary = add_primary_member(membership["id"]) if with_primary else None
    return {
        "club": base["club"],
        "tiers": base["tiers"],
        "membership": membership,
        "primary": primary,
    }


def setup_dispatchable_scenario(tier_code: str = "CLASSIC",
                                club_overrides: Optional[dict] = None,
                                tier_overrides: Optional[dict] = None,
                                provider_overrides: Optional[dict] = None,
                                tiers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Club + tier + membership + primary member + one dispatch-capable provider."""
    base = setup_membership_scenario(
        tier_code, with_primary=True,
        club_overrides=club_overrides, tier_overrides=tier_overrides, tiers=tiers,
    )
    provider_overrides = dict(provider_overrides or {})
    provider_overrides.setdefault("home_base_state_code", (base["club"]["territory_state_codes"] or ["CA"])[0])
    provider = create_provider(base["club"]["id"], **provider_overrides)
    base["provider"] = provider
    return base


def create_and_dispatch_call(membership_id: str, requesting_member_id: str, **call_overrides) -> Dict[str, Any]:
    """Create a service call and dispatch it. Returns {"call", "dispatch"}."""
    call = create_service_call(membership_id, requesting_member_id, **call_overrides)
    dispatch = dispatch_call(call["id"], call["version"])
    return {"call": call, "dispatch": dispatch}


def create_and_complete_call(membership_id: str, requesting_member_id: str,
                             complete_payload: Optional[dict] = None,
                             **call_overrides) -> Dict[str, Any]:
    """Create a call, dispatch it, drive it to COMPLETED.

    Returns {"call", "dispatch"} where "dispatch" is the COMPLETED dispatch.
    """
    pair = create_and_dispatch_call(membership_id, requesting_member_id, **call_overrides)
    accept_dispatch(pair["dispatch"]["id"], en_route=True)
    arrive_dispatch(pair["dispatch"]["id"])
    done = complete_dispatch(pair["dispatch"]["id"], **(complete_payload or {}))
    return {"call": pair["call"], "dispatch": done}


# ---------------------------------------------------------------------------
# Tier 3: foreign-call / settlement scenarios
# ---------------------------------------------------------------------------

def setup_foreign_call_scenario(servicing_billing_policy: Optional[str] = None,
                                tier_overrides: Optional[dict] = None,
                                provider_overrides: Optional[dict] = None) -> Dict[str, Any]:
    """Home club NCA [CA] + servicing club SCA [CS] + CLASSIC member of NCA +
    TOW provider under SCA. Nothing is called yet."""
    home = create_club(club_code="NCA", name="NorCal Auto", territory_state_codes=["CA"])
    serv_overrides: Dict[str, Any] = dict(
        club_code="SCA", name="SoCal Auto", territory_state_codes=["CS"],
    )
    if servicing_billing_policy:
        serv_overrides["billing_policy"] = servicing_billing_policy
    servicing = create_club(**serv_overrides)
    tier = create_tier("CLASSIC", **(tier_overrides or {}))
    membership = create_membership(home["id"], "CLASSIC")
    primary = add_primary_member(membership["id"])
    provider_kwargs: Dict[str, Any] = dict(home_base_state_code="CS")
    provider_kwargs.update(provider_overrides or {})
    provider = create_provider(servicing["id"], **provider_kwargs)
    return {
        "home_club": home,
        "servicing_club": servicing,
        "tier": tier,
        "membership": membership,
        "primary": primary,
        "provider": provider,
    }


def complete_foreign_tow_call(scenario: Dict[str, Any], actual_tow_miles: int,
                              requested_tow_miles: int = 10,
                              breakdown_state: str = "CS") -> Dict[str, Any]:
    """Complete one foreign TOW call inside a setup_foreign_call_scenario world.

    Returns {"call", "dispatch", "line"} where line is the created SettlementLine.
    """
    pair = create_and_complete_call(
        scenario["membership"]["id"], scenario["primary"]["id"],
        complete_payload={"actual_tow_miles": actual_tow_miles},
        breakdown_location_state=breakdown_state,
        requested_tow_miles=requested_tow_miles,
    )
    resp = api_client.list_settlement_lines(
        CLERK, params={"service_call_id": pair["call"]["id"]}
    )
    if resp.status_code != 200:
        raise _setup_fail("list_settlement_lines", resp)
    lines = get_success_data(resp)
    if not lines:
        raise AssertionError("Setup failed at complete_foreign_tow_call: no settlement line created")
    return {"call": pair["call"], "dispatch": pair["dispatch"], "line": lines[0]}


def setup_swept_period(servicing_billing_policy: Optional[str] = None,
                       clerk_user_id: str = CLERK_1) -> Dict[str, Any]:
    """One completed foreign TOW call (10 actual miles, no parts) plus a period
    for the servicing club, swept CLOSED. Clock lands at period end.

    Returns scenario dict with "period" and the completed call's "line".
    """
    scenario = setup_foreign_call_scenario(servicing_billing_policy)
    done = complete_foreign_tow_call(scenario, actual_tow_miles=10)
    period = create_settlement_period(scenario["servicing_club"]["id"])
    set_clock("2026-10-01T00:00:00Z")
    clerk_headers = make_settlement_clerk_headers(clerk_user_id)
    resp = api_client.close_settlement_period(period["id"], clerk_headers)
    if resp.status_code != 200:
        raise _setup_fail("close_settlement_period", resp)
    scenario.update({"period": get_success_data(resp), "line": done["line"],
                     "call": done["call"], "dispatch": done["dispatch"]})
    return scenario
