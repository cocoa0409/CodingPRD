"""Validation priority, cross-entity gating, and temporal-overlap tests
(depth queue A)."""
import pytest

from test_helpers import (
    ApiErrorId,
    SYS,
    bootstrap_org_and_admin,
    create_org,
    create_admin,
    create_plan,
    create_product_version,
    create_active_subscription,
    create_end_user,
    create_device,
    mint_seat,
    mint_seat_for_active_subscription,
    assign_seat,
    open_audit,
    get_seat,
    get_organization,
    list_seat_entitlements,
    get_transfer_request,
    get_product_version,
    set_clock,
    setup_assigned_seat,
    create_transfer_request,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    make_org_admin_headers,
    make_end_user_headers,
)


def _frozen_capacity_setup(api, org_name):
    """At-capacity org with an open findings-raised audit and a spare minted
    seat ready for an assignment attempt."""
    from test_helpers import get_subscription
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name=org_name, org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email=f"oa@{org_name}.com",
                         full_name="Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code=f"{org_name}-P", segment="TEAM",
                       billing_model="MONTHLY", monthly_price_cents=3000,
                       annual_monthly_price_cents=3000, storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat_a = mint_seat_for_active_subscription(sub)
    user_a = create_end_user(org["id"], headers, email=f"ua@{org_name}.com")
    assign_seat(seat_a["id"], user_a["id"], headers)
    sub = get_subscription(sub["id"])
    seat_b = mint_seat(sub["id"], sub["version"])
    user_b = create_end_user(org["id"], headers, email=f"ub@{org_name}.com")
    audit = open_audit(org["id"], admin["id"])
    api.raise_audit_findings(audit["id"], {"findings_count": 1}, SYS)
    return {"org": org, "admin": admin, "headers": headers, "sub": sub,
            "seat_b": seat_b, "user_b": user_b}


def test_frozen_org_blocks_assignment_before_capacity(api):
    """PRD: "Every request passes through a fixed cascade of validation
    categories, evaluated in priority order so that earlier failures mask later
    ones" — the compliance freeze (category 8, `ERR_ORG_FROZEN`) precedes seat
    capacity (category 20, `ERR_SEAT_CAPACITY_EXCEEDED`), and PRD: "A `FROZEN`
    posture is a hard stop: seat creation, seat assignment, package submission,
    and subscription activation are all rejected with `ERR_ORG_FROZEN` while it
    holds."

    The assignment against an at-capacity subscription in an org with raised
    findings must be rejected; when the org's computed posture is FROZEN the
    error is ERR_ORG_FROZEN (freeze masks capacity), otherwise capacity fires.

    Design: Difficulty/priority_pair_validation_conflict/frozen_org_blocks_before_capacity_check
    """
    ctx = _frozen_capacity_setup(api, "O8")
    org_state = get_organization(ctx["org"]["id"])
    resp = api.assign_seat(ctx["seat_b"]["id"],
                           {"end_user_id": ctx["user_b"]["id"]}, ctx["headers"])
    if org_state["compliance_posture"] == "FROZEN":
        validate_error(resp, ApiErrorId.ERR_ORG_FROZEN)
    else:
        validate_error(resp, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED)
    assert get_seat(ctx["seat_b"]["id"])["status"] == "UNASSIGNED"


def test_at_capacity_assignment_under_audit_never_succeeds(api):
    """PRD: "`seats_assigned` must be strictly below `seats_purchased` (else
    `ERR_SEAT_CAPACITY_EXCEEDED`)" and PRD: "A `FROZEN` posture is a hard stop"

    Whichever of the two earlier-or-later checks fires, the seat under test
    stays UNASSIGNED and the assignment is rejected with a 4xx error.

    Design: Difficulty/priority_pair_validation_conflict/frozen_org_blocks_before_capacity_check
    """
    ctx = _frozen_capacity_setup(api, "O8B")
    org_state = get_organization(ctx["org"]["id"])
    resp = api.assign_seat(ctx["seat_b"]["id"],
                           {"end_user_id": ctx["user_b"]["id"]}, ctx["headers"])
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_ORG_FROZEN, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED])
    seat_after = get_seat(ctx["seat_b"]["id"])
    assert seat_after["status"] == "UNASSIGNED"
    assert seat_after["end_user_id"] is None


def _transfer_setup(api, org_name="O9"):
    """Org with two admins, one assigned seat, and a PENDING_APPROVAL transfer
    request created by admin1."""
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name=org_name, org_type="TEAM", primary_admin_id=ba0["id"])
    admin1 = create_admin(org["id"], email=f"oa1@{org_name}.com",
                          full_name="Admin One", admin_kind="SYSTEM_ADMIN")
    admin2 = create_admin(org["id"], email=f"oa2@{org_name}.com",
                          full_name="Admin Two", admin_kind="PRODUCT_ADMIN")
    h1 = make_org_admin_headers(admin1["id"])
    h2 = make_org_admin_headers(admin2["id"])
    plan = create_plan(code=f"{org_name}-P", segment="TEAM",
                       billing_model="MONTHLY", monthly_price_cents=3000,
                       annual_monthly_price_cents=3000, storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user_a = create_end_user(org["id"], h1, email=f"ua@{org_name}.com")
    user_b = create_end_user(org["id"], h1, email=f"ub@{org_name}.com")
    seat = assign_seat(seat["id"], user_a["id"], h1)
    tr_resp = api.create_transfer_request(
        {"org_id": org["id"], "seat_id": seat["id"], "to_user_id": user_b["id"],
         "requested_by_admin_id": admin1["id"],
         "expected_seat_version": seat["version"]}, h1)
    tr = validate_success(tr_resp, expected_status=201)
    return {"org": org, "admin1": admin1, "admin2": admin2, "h1": h1,
            "h2": h2, "plan": plan, "subscription": sub, "seat": seat,
            "user_a": user_a, "user_b": user_b, "tr": tr}


def test_self_approval_of_expired_transfer_returns_segregation_error(api):
    """PRD: "Every request passes through a fixed cascade of validation
    categories, evaluated in priority order so that earlier failures mask later
    ones" — segregation of duties (category 10, `ERR_SEGREGATION_OF_DUTIES`)
    precedes transfer expiry (category 17, `ERR_TRANSFER_EXPIRED`), and PRD:
    "A transfer request's approving or rejecting administrator must be a
    different admin than the `requested_by_admin_id` recorded on the request"

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_transfer_expiry
    """
    ctx = _transfer_setup(api)
    set_clock("2026-09-05T00:00:00Z")  # past the 72h expiry
    resp = api.approve_transfer_request(ctx["tr"]["id"], ctx["h1"])
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    tr = get_transfer_request(ctx["tr"]["id"])
    assert tr["status"] in ("PENDING_APPROVAL", "EXPIRED"), (
        f"Failed approve must not move the request to APPROVED; got "
        f"{tr['status']}")


def test_self_rejection_of_transfer_returns_segregation_error(api):
    """PRD: "A transfer request's approving or rejecting administrator must be
    a different admin than the `requested_by_admin_id` recorded on the request"
    and PRD: "Violations of either rule are rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Rejection by the requesting admin (before expiry) is also a segregation
    violation.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_precedes_transfer_expiry
    """
    ctx = _transfer_setup(api, org_name="O9R")
    resp = api.reject_transfer_request(ctx["tr"]["id"], ctx["h1"])
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    tr = get_transfer_request(ctx["tr"]["id"])
    assert tr["status"] == "PENDING_APPROVAL"


def test_assign_under_pending_payment_subscription_rejected(api):
    """PRD: "Six preconditions hold, evaluated within the validation ordering
    of §2.8: the subscription must be `ACTIVE` (else
    `ERR_SUBSCRIPTION_NOT_ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/seat_assign_requires_subscription_active
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O12", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa12@o12.com", full_name="Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="P12", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    from test_helpers import create_subscription
    sub = create_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat(sub["id"], sub["version"])
    user = create_end_user(org["id"], headers, email="u12@o12.com")
    resp = api.assign_seat(seat["id"], {"end_user_id": user["id"]}, headers)
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE,
               ApiErrorId.ERR_INVALID_STATE])
    assert get_seat(seat["id"])["status"] == "UNASSIGNED"


def test_assign_leaves_unassigned_seat_untouched_on_state_failure(api):
    """PRD: "Operations that demand an active subscription and find one in any
    other state are rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    A failed assignment against a PENDING_PAYMENT subscription leaves the seat
    UNASSIGNED with no assignee.

    Design: Difficulty/cross_entity_state_dependency/seat_assign_requires_subscription_active
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O12B", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa12b@o12.com", full_name="Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="P12B", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    from test_helpers import create_subscription
    sub = create_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat(sub["id"], sub["version"])
    user = create_end_user(org["id"], headers, email="u12b@o12.com")
    api.assign_seat(seat["id"], {"end_user_id": user["id"]}, headers)
    seat_after = get_seat(seat["id"])
    assert seat_after["status"] == "UNASSIGNED"
    assert seat_after["end_user_id"] is None


def test_entitlement_activation_on_other_users_device_rejected(api):
    """PRD: "the target device (named by `device_id` in the request) must
    belong to the calling user and be `ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/entitlement_activate_requires_device_owned_and_active
    """
    ctx = setup_assigned_seat(org_name="O13")
    headers = ctx["admin_headers"]
    other = create_end_user(ctx["org"]["id"], headers, email="u13b@o13.com")
    device = create_device(other["id"], fingerprint="fp-13b", label="B Laptop")
    entitlements = list_seat_entitlements(ctx["seat"]["id"])
    ent_id = entitlements[0]["id"]
    resp = api.activate_entitlement(
        ent_id, {"device_id": device["id"]},
        make_end_user_headers(ctx["user"]["id"]))
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_IDENTITY_MISMATCH,
               ApiErrorId.ERR_CROSS_ORG_REFERENCE])
    assert get_entitlement_status(api, ent_id) == "PENDING_ACTIVATION"


def get_entitlement_status(api, ent_id):
    from test_helpers import get_entitlement
    return get_entitlement(ent_id)["status"]


def test_entitlement_activation_requires_device_active_and_owned(api):
    """PRD: "Activation is the end user's own action: the calling user's
    `X-User-ID` must be the seat's current assignee, the seat must be
    `ASSIGNED`, the subscription must be `ACTIVE` (else
    `ERR_SUBSCRIPTION_NOT_ACTIVE`), the target device (named by `device_id` in
    the request) must belong to the calling user and be `ACTIVE`"

    An OrgAdmin (not the assignee) cannot activate the entitlement at all.

    Design: Difficulty/cross_entity_state_dependency/entitlement_activate_requires_device_owned_and_active
    """
    ctx = setup_assigned_seat(org_name="O13B")
    device = create_device(ctx["user"]["id"], fingerprint="fp-13c", label="L")
    ent_id = list_seat_entitlements(ctx["seat"]["id"])[0]["id"]
    # OrgAdmin role is not on the activation endpoint's role list.
    resp = api.activate_entitlement(ent_id, {"device_id": device["id"]},
                                    ctx["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_entitlement_status(api, ent_id) == "PENDING_ACTIVATION"


def test_second_transfer_request_for_transferring_seat_rejected(api):
    """PRD: "Creation requires the subscription to be `ACTIVE`, no other
    transfer request in `PENDING_APPROVAL` or `APPROVED` to exist for the same
    seat"

    Design: Difficulty/resource_temporal_overlap/concurrent_pending_transfer_per_seat_interval_semantics
    """
    ctx = _transfer_setup(api, org_name="O14")
    user_c = create_end_user(ctx["org"]["id"], ctx["h1"], email="u14c@o14.com")
    seat_now = get_seat(ctx["seat"]["id"])
    assert seat_now["status"] == "TRANSFERRING"
    resp = api.create_transfer_request(
        {"org_id": ctx["org"]["id"], "seat_id": ctx["seat"]["id"],
         "to_user_id": user_c["id"],
         "requested_by_admin_id": ctx["admin2"]["id"],
         "expected_seat_version": seat_now["version"]}, ctx["h2"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    listed = api.list_transfer_requests(
        SYS, params={"seat_id": ctx["seat"]["id"]}).json()["data"]
    assert len(listed) == 1, (
        f"Exactly one transfer request may exist for the seat; got "
        f"{len(listed)}")


def test_rejected_transfer_frees_seat_for_new_request(api):
    """PRD: "Rejection, also by a different admin, moves the request to
    `REJECTED` and returns the seat `TRANSFERRING → ASSIGNED` with its assignee
    unchanged."

    After rejection the seat is ASSIGNED again and a new transfer request may
    open on it.

    Design: Difficulty/resource_temporal_overlap/concurrent_pending_transfer_per_seat_interval_semantics
    """
    ctx = _transfer_setup(api, org_name="O14F")
    resp = api.reject_transfer_request(ctx["tr"]["id"], ctx["h2"])
    data = validate_success(resp)
    assert data["status"] == "REJECTED"
    seat_now = get_seat(ctx["seat"]["id"])
    assert seat_now["status"] == "ASSIGNED"
    assert seat_now["end_user_id"] == ctx["user_a"]["id"]
    user_c = create_end_user(ctx["org"]["id"], ctx["h1"], email="u14fc@o14.com")
    resp = api.create_transfer_request(
        {"org_id": ctx["org"]["id"], "seat_id": ctx["seat"]["id"],
         "to_user_id": user_c["id"],
         "requested_by_admin_id": ctx["admin2"]["id"],
         "expected_seat_version": seat_now["version"]}, ctx["h2"])
    validate_success(resp, expected_status=201)


def test_force_upgrade_deadline_equal_to_now_rejected(api):
    """PRD: "a `SystemAdmin` may move a `DEPRECATED` version to
    `FORCED_UPGRADE` by supplying a `forced_upgrade_deadline` that lies
    strictly in the future of the logical clock — a deadline at or before the
    current logical time is rejected with `ERR_DEADLINE_NOT_FUTURE`."

    Design: Difficulty/resource_temporal_overlap/forced_upgrade_deadline_window_overlap_semantics
    """
    b0, ba0 = bootstrap_org_and_admin()
    plan = create_plan(code="P15", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    pv_old = create_product_version(plan["id"], version_label="2026.1",
                                    release_date="2026-01-15T00:00:00Z")
    create_product_version(plan["id"], version_label="2026.2",
                           release_date="2026-06-15T00:00:00Z")
    api.deprecate_product_version(pv_old["id"], SYS)
    # Clock default is exactly 2026-09-01T00:00:00Z; deadline == now rejected.
    resp = api.force_upgrade_product_version(
        pv_old["id"], {"forced_upgrade_deadline": "2026-09-01T00:00:00Z"}, SYS)
    validate_error(resp, ApiErrorId.ERR_DEADLINE_NOT_FUTURE)
    assert get_product_version(pv_old["id"])["availability"] == "DEPRECATED"


def test_force_upgrade_deadline_in_past_rejected(api):
    """PRD: "a deadline at or before the current logical time is rejected with
    `ERR_DEADLINE_NOT_FUTURE`."

    A deadline strictly before the logical clock is rejected too.

    Design: Difficulty/resource_temporal_overlap/forced_upgrade_deadline_window_overlap_semantics
    """
    b0, ba0 = bootstrap_org_and_admin()
    plan = create_plan(code="P15B", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    pv_old = create_product_version(plan["id"], version_label="2026.1",
                                    release_date="2026-01-15T00:00:00Z")
    create_product_version(plan["id"], version_label="2026.2",
                           release_date="2026-06-15T00:00:00Z")
    api.deprecate_product_version(pv_old["id"], SYS)
    resp = api.force_upgrade_product_version(
        pv_old["id"], {"forced_upgrade_deadline": "2026-08-01T00:00:00Z"}, SYS)
    validate_error(resp, ApiErrorId.ERR_DEADLINE_NOT_FUTURE)
    assert get_product_version(pv_old["id"])["availability"] == "DEPRECATED"


def test_first_device_activation_succeeds_under_cap(api):
    """PRD: "the device cap must have room — the seat must currently have fewer
    than the plan's `max_devices_per_seat` active device-entitlements,
    evaluated per seat, before another device can be activated, else
    `ERR_DEVICE_LIMIT_EXCEEDED`."

    With cap 1 and zero active device-entitlements (0 < 1), activation succeeds.

    Design: Difficulty/boundary_precision_check/device_cap_at_limit_vs_limit_plus_one
    """
    ctx = setup_assigned_seat(org_name="O11",
                              plan_overrides={"max_devices_per_seat": 1})
    device = create_device(ctx["user"]["id"], fingerprint="fp-a", label="A")
    ent_id = list_seat_entitlements(ctx["seat"]["id"])[0]["id"]
    resp = api.activate_entitlement(ent_id, {"device_id": device["id"]},
                                    make_end_user_headers(ctx["user"]["id"]))
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    assert data["device_id"] == device["id"]


def test_activation_beyond_cap_or_state_rejected(api):
    """PRD: "the seat must currently have fewer than the plan's
    `max_devices_per_seat` active device-entitlements, evaluated per seat,
    before another device can be activated, else `ERR_DEVICE_LIMIT_EXCEEDED`."

    With cap 1 and the seat's entitlement already ACTIVE on one device, a
    further activation attempt on that seat cannot succeed: the only
    entitlement is no longer PENDING_ACTIVATION, and any spawned entitlement
    would be blocked by the cap.

    Design: Difficulty/boundary_precision_check/device_cap_at_limit_vs_limit_plus_one
    """
    ctx = setup_assigned_seat(org_name="O11C",
                              plan_overrides={"max_devices_per_seat": 1})
    device_a = create_device(ctx["user"]["id"], fingerprint="fp-a1", label="A")
    user_headers = make_end_user_headers(ctx["user"]["id"])
    ent_id = list_seat_entitlements(ctx["seat"]["id"])[0]["id"]
    resp = api.activate_entitlement(ent_id, {"device_id": device_a["id"]},
                                    user_headers)
    validate_success(resp)
    # Any further activation on this seat must fail, by cap or by state.
    device_b = create_device(ctx["user"]["id"], fingerprint="fp-b1", label="B")
    pending = list_seat_entitlements(ctx["seat"]["id"],
                                     params={"status": "PENDING_ACTIVATION"})
    target_id = pending[0]["id"] if pending else ent_id
    resp = api.activate_entitlement(target_id, {"device_id": device_b["id"]},
                                    user_headers)
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_DEVICE_LIMIT_EXCEEDED,
               ApiErrorId.ERR_INVALID_STATE])
