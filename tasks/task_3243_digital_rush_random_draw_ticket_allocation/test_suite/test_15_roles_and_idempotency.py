"""Role gates, segregation of duties and order idempotency."""
import pytest

from test_helpers import (
    validate_error, validate_success, get_success_data, ApiErrorId,
)
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.test_users import make_allocations_coordinator_headers


def test_release_is_denied_to_a_patron(api):
    """PRD §2.6: "Only then is the acting role tested against the endpoint's own
    list of permitted roles, and a role that is declared but not permitted on
    this operation receives `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/release_operation_is_denied_to_every_role_except_ops_manager
    """
    production, performance, allocation = X.setup_scheduled_allocation(
        daily_quantity=5, per_order_limit=2,
    )
    patron = X.register_patron(email="role_patron@example.com")

    response = api.release_allocation(
        allocation["id"], C.BASE_CLOCK_DAY,
        {"expected_production_version": production["version"],
         "expected_performance_version": performance["version"],
         "expected_allocation_version": allocation["version"]},
        X.patron_headers(patron),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_release_is_denied_to_the_coordinator_who_attested_it(api):
    """PRD §2.6: "A role that is declared but not permitted on this operation
    receives `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "A request that presents a declared role which is not permitted on
    the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/release_operation_is_denied_to_every_role_except_ops_manager
    """
    production, performance, allocation = X.setup_scheduled_allocation(
        daily_quantity=5, per_order_limit=2,
    )

    response = api.release_allocation(
        allocation["id"], C.BASE_CLOCK_DAY,
        {"expected_production_version": production["version"],
         "expected_performance_version": performance["version"],
         "expected_allocation_version": allocation["version"]},
        X.COORD,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    unchanged = X.get_allocation(performance, allocation["id"])
    assert unchanged["status"] == "SCHEDULED", \
        "a denied release stamps nothing"
    assert unchanged["quantity_released_today"] == 0


def test_the_two_step_release_records_two_different_operators(api):
    """PRD §3.3: "The `AllocationsCoordinator` who attested the quantities at
    scheduling time is recorded as `qa_checked_by` on the allocation, and the
    `OpsManager` who authorises the release is recorded as `released_by`."

    Design: Corner/roles/allocation_attestation_and_release_are_written_by_different_operators
    """
    production, performance = X.setup_active_performance()[1:]
    attester = make_allocations_coordinator_headers("ac-lena")
    allocation = api.create_allocation(
        performance["id"],
        {
            "ticket_type": "RUSH",
            "daily_quantity": 5,
            "discount_pct": 0.5,
            "release_time_local": "09:00",
            "refundable": True,
            "per_order_limit": 2,
        },
        attester,
    )
    created = validate_success(allocation, expected_status=201)
    scheduled = validate_success(
        api.schedule_allocation(created["id"],
                                {"expected_allocation_version": created["version"]},
                                attester))
    released = validate_success(
        api.release_allocation(
            created["id"], C.BASE_CLOCK_DAY,
            {"expected_production_version": production["version"],
             "expected_performance_version": performance["version"],
             "expected_allocation_version": scheduled["version"]},
            X.OPS))

    assert released["qa_checked_by"] == "ac-lena", (
        "scheduling stamps the attesting coordinator, got "
        f"{released['qa_checked_by']}"
    )
    assert released["released_by"] == X.OPS["X-User-ID"], (
        f"the release stamps the authorising operator, got {released['released_by']}"
    )
    assert released["qa_checked_by"] != released["released_by"], \
        "the two operator fields hold different values on a completed release"


def test_a_release_authorised_by_its_own_attester_is_refused(api):
    """PRD §3.3: "a release authorised by the same operator who attested it —
    that is, one where the acting operator's identifier equals the allocation's
    `qa_checked_by` — is refused with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/roles/allocation_attestation_and_release_are_written_by_different_operators
    """
    production, performance = X.setup_active_performance()[1:]
    same_operator = X.build_user_headers("shared-operator", "OpsManager")
    coordinator_as_ops = X.build_user_headers("shared-operator",
                                              "AllocationsCoordinator")
    created = validate_success(
        api.create_allocation(
            performance["id"],
            {"ticket_type": "RUSH", "daily_quantity": 5, "discount_pct": 0.5,
             "release_time_local": "09:00", "refundable": True,
             "per_order_limit": 2},
            coordinator_as_ops),
        expected_status=201)
    scheduled = validate_success(
        api.schedule_allocation(created["id"],
                                {"expected_allocation_version": created["version"]},
                                coordinator_as_ops))

    response = api.release_allocation(
        created["id"], C.BASE_CLOCK_DAY,
        {"expected_production_version": production["version"],
         "expected_performance_version": performance["version"],
         "expected_allocation_version": scheduled["version"]},
        same_operator,
    )
    validate_error(response, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)


def test_a_replayed_order_returns_the_original_rather_than_buying_twice(api):
    """PRD §3.5: "The key is what makes the operation safe to retry: a repeat of
    the same key with the same payload replays the original response rather than
    opening a second order, so a client that loses a response to a timeout does
    not buy twice."

    Design: Corner/cross_cutting_layers/idempotent_purchase_replay_returns_the_original_order
    """
    production, performance, allocation = X.setup_released_allocation(
        ticket_type="RUSH", daily_quantity=5, discount_pct=0.5, refundable=True,
        per_order_limit=2,
    )
    patron = X.register_patron(email="idem_patron@example.com")
    X.join_queue(performance, allocation, patron)
    X.ops_run("2026-09-12T09:05:00Z")

    payload = {"performance_id": performance["id"],
               "allocation_id": allocation["id"],
               "quantity": 2, "idempotency_key": "idem-key-1"}
    first = validate_success(
        api.create_purchase(payload, X.patron_headers(patron)),
        expected_status=201)
    second = validate_success(
        api.create_purchase(payload, X.patron_headers(patron)),
        expected_status=201)

    assert second["id"] == first["id"], (
        "the replay returns the original order identifier, got "
        f"{second['id']} against {first['id']}"
    )
    assert X.get_allocation(performance, allocation["id"])["quantity_sold_today"] == 2, (
        "the day's sold count advances exactly once across two identical "
        "requests"
    )