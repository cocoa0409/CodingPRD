"""The cyclic machines: the stay negotiation loop and the subscription machine."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers.fixtures import (
    setup_basic_scenario,
    setup_declined_stay,
    file_stay,
    decline_stay,
    read_stay,
    read_member,
    host_version,
    make_host_operator_headers,
    make_member_headers,
    make_platform_admin_headers,
    set_clock,
)


def test_a_declined_request_reopens_as_a_second_round_negotiation(api):
    """PRD §3.6: "A successful counter-request returns the stay to `REQUESTED` and
    sets its `request_depth` to 2, putting it back in front of the host as a
    second-round negotiation rather than a first-round hold."
    PRD §3.4: "Declining a stay is simpler but not trivial: it requires the request
    to be `REQUESTED`, and it advances `request_depth` to exactly 1 on this
    response — that is the mechanism that admits the member's later counter-request
    exactly once."

    Design: Difficulty/non_linear_state_machine/stay_request_second_negotiation_round
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_declined_stay(decline_arrival="2026-07-05")
    assert parts["stay"]["request_status"] == "DECLINED"
    assert parts["stay"]["request_depth"] == 1

    resp = api.counter_stay_request(
        parts["stay"]["id"],
        {"arrival_date": "2026-07-06", "nights": 2, "party_size": 2},
        make_member_headers(parts["member"]["id"]),
    )
    reopened = validate_success(resp)
    assert reopened["request_status"] == "REQUESTED"
    assert reopened["request_depth"] == 2


def test_a_second_decline_after_the_counter_makes_a_third_counter_illegal(api):
    """PRD §3.6: "A member who owns a stay that sits at `DECLINED` may ask the host
    to look again, provided the stay's `request_depth` is exactly 1 — the depth the
    decline itself set"
    PRD §2.10: "State suitability is checked next, yielding `ERR_INVALID_STATE`
    (HTTP 409) whenever a target resource is not in a state that permits the
    requested operation."

    Design: Difficulty/non_linear_state_machine/stay_request_second_negotiation_round
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_declined_stay(decline_arrival="2026-07-05")
    host_id, member_id = parts["host"]["id"], parts["member"]["id"]

    reopened = validate_success(
        api.counter_stay_request(
            parts["stay"]["id"],
            {"arrival_date": "2026-07-06", "nights": 2, "party_size": 2},
            make_member_headers(member_id),
        )
    )
    assert reopened["request_depth"] == 2

    second_decline = decline_stay(host_id, parts["stay"]["id"])
    assert second_decline["request_status"] == "DECLINED"
    assert second_decline["request_depth"] == 3

    resp = api.counter_stay_request(
        parts["stay"]["id"],
        {"arrival_date": "2026-07-08", "nights": 2, "party_size": 1},
        make_member_headers(member_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    after = read_stay(parts["stay"]["id"], host_id)
    assert after["request_status"] == "DECLINED"
    assert after["request_depth"] == 3


def test_a_cancelled_subscription_can_be_lapsed_and_renewed_back_to_active(api):
    """PRD §3.3: "A `LAPSED` subscription is restored to `ACTIVE` by renewal. A
    member may end their own subscription by cancelling it, which sets
    `subscription_status` to `CANCELLED` and requires the acting member to own the
    resource"
    PRD §3.3: "A cancelled subscription is not strictly terminal: the platform may
    lapse it back to `LAPSED` for a re-engagement campaign, after which renewal can
    bring it back to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/member_subscription_cycle_with_no_terminal_state
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1, plan_tier="PLUS",
                                 self_contained_required=True, category="WINERY",
                                 state_code="CA")
    member_id = parts["member"]["id"]
    admin = make_platform_admin_headers()

    lapsed = validate_success(
        api.member_subscription_action(member_id, {"action": "LAPSE"}, admin)
    )
    assert lapsed["subscription_status"] == "LAPSED"

    renewed = validate_success(
        api.member_subscription_action(member_id, {"action": "RENEW"}, admin)
    )
    assert renewed["subscription_status"] == "ACTIVE"

    cancelled = validate_success(
        api.cancel_member_subscription(member_id, make_member_headers(member_id))
    )
    assert cancelled["subscription_status"] == "CANCELLED"

    relapsed = validate_success(
        api.member_subscription_action(member_id, {"action": "LAPSE"}, admin)
    )
    assert relapsed["subscription_status"] == "LAPSED"


def test_the_subscription_gate_is_re_evaluated_on_every_pass(api):
    """PRD §3.3: "Member eligibility for transactional work is checked separately
    from subscription bookkeeping: a member must have `subscription_status` `ACTIVE`
    and must not have `removal_status` `REMOVED`, and a member failing either test is
    refused with `ERR_MEMBER_NOT_ELIGIBLE` (HTTP 403) when they try to open or
    re-open a stay."

    Design: Difficulty/non_linear_state_machine/member_subscription_cycle_with_no_terminal_state
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1, plan_tier="PLUS",
                                 self_contained_required=True, category="WINERY",
                                 state_code="CA")
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    vehicle_id = parts["vehicle"]["id"]
    admin = make_platform_admin_headers()

    validate_success(
        api.member_subscription_action(member_id, {"action": "LAPSE"}, admin)
    )
    resp = api.create_stay_request(
        {
            "host_id": host_id,
            "member_id": member_id,
            "vehicle_id": vehicle_id,
            "arrival_date": "2026-06-20",
            "nights": 2,
            "party_size": 1,
            "electric_request_code": "NONE",
            "request_depth": 0,
            "same_day_hold": False,
        },
        make_member_headers(member_id),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE, 403)

    member = read_member(member_id)
    assert member["removal_status"] == "NONE", (
        "the gate that fired was the subscription test, not the removal test"
    )