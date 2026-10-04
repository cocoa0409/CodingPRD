"""Corner queue B — section: rbac.

Subscriber ownership, cross-role exclusivity and the newsroom segregation-of-duties
rule.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_hub_with_clock,
    create_region,
    create_market,
    create_route,
    create_contractor,
    create_delivery_route,
    create_stop,
    create_subscriber,
    create_position,
    create_newsroom_change,
    hub_version,
    make_subscriber_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_01, CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]
CS = TEST_USERS["customer_service_headers"]
NEWSROOM_MANAGER = TEST_USERS["newsroom_manager_headers"]


def test_subscriber_may_only_act_on_its_own_contract():
    """PRD §2.1: "When `X-User-Role` is `Subscriber`, by contrast, `X-User-ID` is
    the `id` of the acting `SubscriberContract`; ownership checks on a subscriber
    contract compare the contract's own `id` to `X-User-ID`, and a subscriber may
    only read, cancel or migrate their own contract."

    Design: Corner/rbac/subscriber_may_only_act_on_its_own_contract
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    region = create_region(hub["id"])
    market = create_market(region["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    sub_a = create_subscriber(stop["id"], subscriber_ref="SUB-A",
                              remaining_print_issues=20)
    sub_b = create_subscriber(stop["id"], subscriber_ref="SUB-B",
                              remaining_print_issues=20)

    own = validate_success(
        api.get_subscriber(sub_a["id"], make_subscriber_headers(sub_a["id"])), 200)
    assert own["subscriber_ref"] == "SUB-A"

    cross = api.get_subscriber(sub_b["id"], make_subscriber_headers(sub_a["id"]))
    error = validate_error(cross, "ERR_UNAUTHORIZED")
    assert cross.status_code == 403, (
        f"reading another contract is refused, got {cross.status_code}"
    )
    assert error["error_id"] == "ERR_UNAUTHORIZED"
    assert "SUB-B" not in cross.text, (
        "the refused cross-contract read must leak no field of the other contract"
    )


def test_delivery_manager_cannot_offer_a_retention_action():
    """PRD §2.1: "`CustomerService` owns subscriber notification, migration,
    retention offers and refunds."
    PRD §3.6: "a `CustomerService` operator offers one with a `retention_offer_code`
    such as `CREDIT30` or `DIGITAL12`, a `retention_credit_cents` of at least zero,
    and the `eligibility_policy_id` the subscriber must satisfy".

    Design: Corner/rbac/delivery_manager_cannot_offer_a_retention_action
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    region = create_region(hub["id"])
    market = create_market(region["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    subscriber = create_subscriber(stop["id"], subscriber_ref="SUB-R",
                                   remaining_print_issues=40,
                                   paid_through_utc="2027-06-01T00:00:00Z")

    payload = {
        "retention_offer_code": "CREDIT30",
        "retention_credit_cents": 3000,
        "eligibility_policy_id": "STANDARD",
    }

    refused = api.offer_retention_action(subscriber["id"], payload, DELIVERY)
    error = validate_error(refused, "ERR_UNAUTHORIZED")
    assert refused.status_code == 403
    assert error["error_id"] == "ERR_UNAUTHORIZED"

    accepted = validate_success(
        api.offer_retention_action(subscriber["id"], payload, CS), 201)
    assert accepted["status"] == "open"
    assert accepted["subscriber_contract_id"] == subscriber["id"]

    actions = validate_success(
        api.list_subscriber_retention_actions(subscriber["id"], CS), 200)
    assert len(actions) == 1, (
        f"the subscriber has exactly one retention action, got {len(actions)}"
    )


def test_same_operator_may_not_approve_its_own_newsroom_change():
    """PRD §2.1: "no operator may approve a headcount movement that it created
    itself, and an attempt to do so is refused with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."
    PRD §2.11: "Self-approval is checked at the same rank as ordinary authorization,
    so a newsroom change approved by its own creator reports
    `ERR_SEGREGATION_OF_DUTIES` rather than a generic permission failure."

    Design: Corner/rbac/same_operator_may_not_approve_its_own_newsroom_change
    """
    from test_helpers import make_newsroom_manager_headers

    api.set_current_utc({"current_utc": CLOCK_2026_09_01}, ADMIN)
    hub = create_hub()
    region = create_region(hub["id"])
    position = create_position(region["id"])

    creator = make_newsroom_manager_headers("ops-11")
    other = make_newsroom_manager_headers("ops-22")

    from test_helpers import create_newsroom_change_response, get_success_data

    # Re-create through the explicit operator so the creator identity is known.
    version = hub_version(hub["id"])
    created = get_success_data(create_newsroom_change_response(
        position["id"], region["id"], region["id"], version,
        headers=creator, effective_date="2026-09-11",
        layoff_order_index=2, requested_slots=3))

    self_approval = api.approve_newsroom_change(created["id"], creator)
    error = validate_error(self_approval, "ERR_SEGREGATION_OF_DUTIES")
    assert self_approval.status_code == 403
    assert error["error_id"] == "ERR_SEGREGATION_OF_DUTIES"

    approved = validate_success(
        api.approve_newsroom_change(created["id"], other), 200)
    assert approved["status"] == "approved", (
        "a different operator's approval succeeds"
    )