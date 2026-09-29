"""Role, identity and ownership gates, each refused at its own precedence position."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f  # noqa: E402
from test_helpers.api_errors import (  # noqa: E402
    ERR_SELF_APPROVAL_FORBIDDEN,
    ERR_STORE_SCOPE_VIOLATION,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_DEVICE_IDENTITY_MISMATCH,
)
from test_helpers.assertions import (  # noqa: E402
    assert_audit_action_present,
    assert_fields,
    assert_meta,
    assert_money,
)
from test_helpers.constants import (  # noqa: E402
    ACTION_APPLY,
    ACTION_APPROVE,
    ACTION_SUBMIT,
    AVAIL_AVAILABLE,
    AUDIT_PRICE_REQUEST_APPROVAL_RECORDED,
    AUDIT_PRICE_REQUEST_APPROVED,
    BURGER_BASE_CENTS,
    BURGER_ZONE_A_CENTS,
    CATEGORY_ENTREE,
    CATEGORY_SIDE,
    CLOCK_T0,
    DEVICE_CODE_K001,
    DEVICE_CODE_K002,
    FRIES_BASE_CENTS,
    HEALTH_OFFLINE,
    HEALTH_ONLINE,
    PAYMENT_COMPLIANT,
    PCR_APPLIED,
    PCR_APPROVED,
    PCR_PENDING_APPROVAL,
    SKU_BURGER,
    SKU_FRIES,
    STORE_CODE_S001,
    STORE_CODE_S002,
    SUBJECT_PRICE_CHANGE_REQUEST,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    ANALYST,
    ANALYST_2,
    APPROVER,
    APPROVER_2,
    COMPLIANCE,
    CONTENT_MANAGER,
    USER_ANALYST_1,
    USER_APPROVER_1,
    USER_APPROVER_2,
    headers_with_unknown_role,
    headers_without_role,
    make_approver_headers,
    make_device_agent_headers,
    make_store_operator_headers,
)

FUTURE_EFFECTIVE = "2026-08-10T00:00:00Z"


def test_each_exclusive_write_is_refused_to_a_role_that_owns_a_different_slice(api):
    """PRD: "When both headers are well-formed but the named role is not authorised for the endpoint being addressed, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/every_exclusive_operation_is_refused_to_the_neighbouring_role
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    device = world.device(store["id"], DEVICE_CODE_K001)

    validate_error(api.create_price_zone(f.price_zone_payload("ZONE_X"), CONTENT_MANAGER),
                   ERR_UNAUTHORIZED_ROLE, 403)
    validate_error(
        api.create_store(f.store_payload(cluster["id"], zone["id"], "S099"), ANALYST),
        ERR_UNAUTHORIZED_ROLE, 403,
    )
    validate_error(api.create_content_bundle(f.content_bundle_payload(cluster["id"]), APPROVER),
                   ERR_UNAUTHORIZED_ROLE, 403)
    validate_error(
        api.payment_attestation(device["id"], f.attestation_payload(), CONTENT_MANAGER),
        ERR_UNAUTHORIZED_ROLE, 403,
    )

    attested = validate_success(
        api.payment_attestation(device["id"], f.attestation_payload(), COMPLIANCE), 200)
    assert attested["payment_compliance_state"] == PAYMENT_COMPLIANT, (
        "the identical payload from the owning role succeeds: the refusal was about the role"
    )

    rows, meta = validate_paginated(api.list_price_zones(ADMIN, params={"limit": 100}))
    assert len(rows) == 1
    assert_meta(meta, total_count=1)


def test_a_blank_or_unknown_role_is_unauthenticated_before_anything_else(api):
    """PRD: "If either header is absent, blank, or if `X-User-Role` names a role that is not one of the seven declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/a_missing_role_header_is_unauthenticated_before_any_role_check
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)

    validate_error(api.get_price_zone(zone["id"], headers_without_role()),
                   ERR_UNAUTHENTICATED, 401)
    validate_error(api.create_price_zone(f.price_zone_payload("ZONE_Y"),
                                         headers_with_unknown_role()),
                   ERR_UNAUTHENTICATED, 401)
    validate_error(api.get_price_zone(NON_EXISTENT_UUID, headers_without_role()),
                   ERR_UNAUTHENTICATED, 401)

    rows, meta = validate_paginated(api.list_price_zones(ADMIN, params={"limit": 100}))
    assert len(rows) == 1
    assert_meta(meta, total_count=1)


def test_a_device_agent_may_only_report_for_its_own_device(api):
    """PRD: "When `X-User-Role` is `DeviceAgent`, `X-User-ID` is the `id` of the acting `Device`, and it must equal the device identifier named in the request path; a device acting as any device other than itself is rejected with `ERR_DEVICE_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/a_device_agent_may_only_speak_for_its_own_device
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    first = world.device(store["id"], DEVICE_CODE_K001)
    second = world.device(store["id"], DEVICE_CODE_K002)
    agent = make_device_agent_headers(first["id"])

    validate_error(api.send_heartbeat(second["id"], f.heartbeat_payload(), agent),
                   ERR_DEVICE_IDENTITY_MISMATCH, 403)
    validate_error(api.send_heartbeat(NON_EXISTENT_UUID, f.heartbeat_payload(), agent),
                   ERR_DEVICE_IDENTITY_MISMATCH, 403)

    own = validate_success(api.send_heartbeat(first["id"], f.heartbeat_payload(), agent), 200)
    assert_fields(own, rolling_health_score=100, health_state=HEALTH_ONLINE)

    untouched = world.get_device(second["id"])
    assert untouched["last_heartbeat_utc"] is None, "the refused heartbeat left no trace"
    assert_fields(untouched, rolling_health_score=0, health_state=HEALTH_OFFLINE,
                  consecutive_missed_heartbeats=0)


def test_a_store_operator_is_scoped_to_the_rows_its_own_store_owns(api):
    """PRD: "Store scope — a `StoreOperator`'s `X-User-ID` equals the `id` of the store that owns the addressed resource, whether that is the store itself, one of its availability rows, one of its devices, or the device that captured the addressed order → `ERR_STORE_SCOPE_VIOLATION` (403)."

    Design: Corner/rbac/a_store_operator_cannot_reach_into_another_stores_rows
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    first_store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    second_store = world.store(cluster["id"], zone["id"], STORE_CODE_S002)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    fries = world.item(SKU_FRIES, category=CATEGORY_SIDE, base_price_cents=FRIES_BASE_CENTS,
                       contrast_ratio=6.2)
    own = make_store_operator_headers(first_store["id"])
    stranger = make_store_operator_headers(second_store["id"])

    row = validate_success(
        api.create_item_availability(
            first_store["id"],
            f.availability_payload(burger["id"], on_hand_units=40, par_units=20), own),
        201,
    )
    assert row["available_units"] == 40

    validate_error(
        api.create_item_availability(
            first_store["id"],
            f.availability_payload(fries["id"], on_hand_units=10, par_units=5), stranger),
        ERR_STORE_SCOPE_VIOLATION, 403,
    )
    validate_error(
        api.item_availability_action(
            row["id"], f.eighty_six_payload("2026-08-05T21:00:00Z",
                                            eighty_six_reason="Not my store"), stranger),
        ERR_STORE_SCOPE_VIOLATION, 403,
    )

    unchanged = validate_success(api.get_item_availability(row["id"], own), 200)
    assert_fields(unchanged, availability_state=AVAIL_AVAILABLE, available_units=40)

    in_scope = validate_success(
        api.create_item_availability(
            first_store["id"],
            f.availability_payload(fries["id"], on_hand_units=10, par_units=5), own),
        201,
    )
    assert_fields(in_scope, available_units=10, availability_state=AVAIL_AVAILABLE)


def test_the_workflow_verbs_are_partitioned_between_the_two_pricing_roles(api):
    """PRD: "Only the operator whose `X-User-ID` equals `requested_by_user_id` may submit; another operator's attempt is refused with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/the_price_workflow_verbs_are_partitioned_between_analyst_and_approver
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_ZONE")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    request = world.price_change_request(burger["id"], zone["id"], 569, CLOCK_T0,
                                         world.get_item(burger["id"])["version"], ANALYST,
                                         justification="Commodity cost increase")
    assert_money(request["baseline_price_cents"], BURGER_ZONE_A_CENTS, "baseline_price_cents")
    assert_fields(request, uplift_bp=179, required_approvals=1)

    validate_error(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_SUBMIT), APPROVER),
        ERR_UNAUTHORIZED_ROLE, 403,
    )
    submitted = validate_success(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_SUBMIT), ANALYST),
        200,
    )
    assert submitted["state"] == PCR_PENDING_APPROVAL

    validate_error(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_APPROVE), ANALYST_2),
        ERR_UNAUTHORIZED_ROLE, 403,
    )
    approved = validate_success(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_APPROVE), APPROVER),
        200,
    )
    assert approved["state"] == PCR_APPROVED

    validate_error(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_APPLY), APPROVER),
        ERR_UNAUTHORIZED_ROLE, 403,
    )
    applied = validate_success(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_APPLY), ANALYST),
        200,
    )
    assert applied["state"] == PCR_APPLIED
    assert_money(applied["applied_price_cents"], 569, "applied_price_cents")


def test_two_distinct_approvers_are_needed_and_the_requester_is_never_one(api):
    """PRD: "In both approval branches the approving `X-User-ID` must differ from `requested_by_user_id` and must not already appear in `approval_user_ids`; either violation is refused with `ERR_SELF_APPROVAL_FORBIDDEN`."

    Design: Corner/rbac/two_distinct_approvers_satisfy_the_dual_tier_but_the_requester_never_can
    """
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_ZONE")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE,
                        base_price_cents=BURGER_BASE_CENTS)
    request = world.price_change_request(burger["id"], zone["id"], 599, FUTURE_EFFECTIVE,
                                         world.get_item(burger["id"])["version"], ANALYST,
                                         justification="Commodity cost increase")
    assert_fields(request, uplift_bp=716, required_approvals=2)
    submitted = world.pcr_action(request["id"], ACTION_SUBMIT, ANALYST)
    assert submitted["state"] == PCR_PENDING_APPROVAL

    first = validate_success(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_APPROVE), APPROVER),
        200,
    )
    assert_fields(first, state=PCR_PENDING_APPROVAL)
    assert first["approval_user_ids"] == [USER_APPROVER_1]

    validate_error(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_APPROVE),
                                        make_approver_headers(USER_ANALYST_1)),
        ERR_SELF_APPROVAL_FORBIDDEN, 403,
    )
    still_one = validate_success(api.get_price_change_request(request["id"], ANALYST), 200)
    assert still_one["approval_user_ids"] == [USER_APPROVER_1]

    second = validate_success(
        api.price_change_request_action(request["id"], f.action_payload(ACTION_APPROVE),
                                        APPROVER_2),
        200,
    )
    assert second["state"] == PCR_APPROVED
    assert second["approval_user_ids"] == [USER_APPROVER_1, USER_APPROVER_2]

    rows = world.audit(COMPLIANCE, subject_kind=SUBJECT_PRICE_CHANGE_REQUEST,
                       subject_id=request["id"])
    assert_audit_action_present(rows, AUDIT_PRICE_REQUEST_APPROVAL_RECORDED, count=1)
    assert_audit_action_present(rows, AUDIT_PRICE_REQUEST_APPROVED, count=1)
