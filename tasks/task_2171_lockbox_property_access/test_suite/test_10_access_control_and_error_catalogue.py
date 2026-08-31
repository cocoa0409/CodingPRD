"""Authentication, role admission, ownership, stale views and the not-found catalogue."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_second_agent,
    build_user_headers,
    device_attempt,
    intake_lockbox,
    lockbox_payload,
    member_event,
    placement_payload,
    read_association,
    read_grant,
    read_lockbox,
    read_member,
    register_association,
    report_lockbox_lost,
    request_grant,
    setup_assigned_box,
    setup_placed_box,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    assign_lockbox,
    association_payload,
    create_listing,
    enroll_member,
    make_member_headers,
)


def _suspended_member_with_an_unpaid_replacement():
    """Ana is SUSPENDED and also carries an unpaid replacement charge, so an assignment to her
    violates both the eligibility rule and the solvency rule at once."""
    ctx = setup_assigned_box(serial="LB-0001", model="LB_PRO", replacement_cost_cents=12000)
    spare = intake_lockbox(
        ctx["association_id"],
        serial_number="LB-0002",
        model="LB_PRO",
        replacement_cost_cents=12000,
    )
    report_lockbox_lost(ctx["lockbox_id"])
    member_event(ctx["agent_id"], "SUSPEND", reason="Unpaid replacement invoice")
    ctx["spare_lockbox"] = spare
    ctx["spare_lockbox_id"] = spare["id"]
    return ctx


def test_assignment_to_a_suspended_delinquent_member_reports_the_eligibility_error(api, admin_headers):
    """PRD §2.6: "10. **Referenced member eligibility** (priority 42) — else
    `ERR_MEMBER_NOT_ELIGIBLE`."
    PRD §2.6: "17. **Member solvency** (priority 75) — else `ERR_MEMBER_BALANCE_DELINQUENT`."
    PRD §3.4: "Assignment is administrator-only and gated twice on the receiving member: their
    `membership_status` must be `ACTIVE` or `PROBATION`, else `ERR_MEMBER_NOT_ELIGIBLE`, and
    their `outstanding_balance_cents` must be exactly zero, else `ERR_MEMBER_BALANCE_DELINQUENT`
    (HTTP 402) — the association will not hand more hardware to someone who has not settled for
    the last piece."

    Design: Difficulty/priority_pair_validation_conflict/assign_to_suspended_delinquent_member_state_precedes_fiscal
    """
    ctx = _suspended_member_with_an_unpaid_replacement()
    spare = read_lockbox(ctx["spare_lockbox_id"])

    response = api.lockbox_state(
        ctx["spare_lockbox_id"],
        {
            "action": "ASSIGN",
            "member_id": ctx["agent_id"],
            "expected_lockbox_version": spare["version"],
        },
        admin_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE.value)
    assert response.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_MEMBER_BALANCE_DELINQUENT.value


def test_rejected_assignment_leaves_the_box_in_stock_and_the_balance_standing(api, admin_headers):
    """PRD §2.6: "When a request violates several rules at once, exactly one error comes back,
    and which one is not a matter of implementation convenience. Checks are evaluated in a
    strict ascending order and the first failure wins."
    PRD §3.4: "A box in `IN_STOCK` is inert. Assigning it to a keyholder moves it to `ASSIGNED`
    and writes the supplied `member_id` into `assigned_member_id`."

    Design: Difficulty/priority_pair_validation_conflict/assign_to_suspended_delinquent_member_state_precedes_fiscal
    """
    ctx = _suspended_member_with_an_unpaid_replacement()
    spare = read_lockbox(ctx["spare_lockbox_id"])
    api.lockbox_state(
        ctx["spare_lockbox_id"],
        {
            "action": "ASSIGN",
            "member_id": ctx["agent_id"],
            "expected_lockbox_version": spare["version"],
        },
        admin_headers,
    )

    unchanged = read_lockbox(ctx["spare_lockbox_id"])
    assert unchanged["status"] == "IN_STOCK"
    assert unchanged.get("assigned_member_id") is None

    member = read_member(ctx["agent_id"])
    assert member["membership_status"] == "SUSPENDED"
    assert member["outstanding_balance_cents"] == 12300


def test_request_with_an_empty_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "Every request to this API carries two headers: `X-User-ID`, identifying the
    caller, and `X-User-Role`, naming the capability set the caller is acting under. If either
    header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) before anything else is examined."

    Design: Corner/validations/request_with_empty_x_user_id_header_unauthenticated
    """
    response = api.create_association(
        association_payload(), build_user_headers("", "AssociationAdmin")
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.json()["response_type"] == "error"


def test_member_cannot_place_a_lockbox_assigned_to_another_member(api, admin_headers):
    """PRD §2.1: "Concretely, a `Member` may act on a listing only when its `listing_agent_id`
    equals `X-User-ID`, on a lockbox only when its `assigned_member_id` equals `X-User-ID`, on a
    placement only when its `placed_by_member_id` equals `X-User-ID`, and on a showing only when
    its `showing_member_id` equals `X-User-ID`. A violation of any of these is
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/member_cannot_place_a_lockbox_assigned_to_another_member
    """
    ctx = setup_assigned_box(serial="LB-0001", model="LB_STD", replacement_cost_cents=9000)
    add_second_agent(ctx)
    other_listing = create_listing(
        ctx["association_id"],
        ctx["other_agent_id"],
        mls_number="MLS-1002",
        address_line="34 Cedar Ave",
    )

    response = api.create_placement(
        placement_payload(ctx["lockbox_id"], other_listing["id"]),
        make_member_headers(ctx["other_agent_id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    lockbox = read_lockbox(ctx["lockbox_id"])
    assert lockbox["status"] == "ASSIGNED"
    assert lockbox.get("current_listing_id") is None


def test_security_auditor_cannot_take_a_lockbox_into_inventory(api, auditor_headers, admin_headers):
    """PRD §2.1: "Auditors open, lock, close and reopen incident reviews and may read broadly,
    but may not mutate inventory, membership, credentials, grants or money."
    PRD §2.1: "If both headers are present but the role is not one of the four recognised names,
    or is a recognised name that the addressed endpoint does not admit, the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/security_auditor_cannot_create_a_lockbox
    """
    association = register_association()

    response = api.create_lockbox(
        lockbox_payload(
            association["id"],
            serial_number="LB-0001",
            model="LB_STD",
            replacement_cost_cents=9000,
        ),
        auditor_headers,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    rows, _ = validate_paginated(
        api.list_lockboxes(admin_headers, params={"association_id": association["id"]})
    )
    assert rows == []


def test_association_admin_cannot_open_an_incident_review(api, admin_headers, auditor_headers):
    """PRD §2.1: "An `AssociationAdmin` may never open or close an incident review."
    PRD §2.1: "If both headers are present but the role is not one of the four recognised names,
    or is a recognised name that the addressed endpoint does not admit, the request is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/association_admin_cannot_open_an_incident_review
    """
    association = register_association()

    response = api.create_incident_review(
        {
            "association_id": association["id"],
            "window_start": "2026-08-06T00:00:00Z",
            "window_end": "2026-08-06T23:59:59Z",
        },
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    rows, _ = validate_paginated(
        api.list_incident_reviews(
            auditor_headers, params={"association_id": association["id"]}
        )
    )
    assert rows == []


def test_member_cannot_approve_a_grant_but_may_revoke_their_own(api, admin_headers):
    """PRD §3.5: "Approval is the association's decision and belongs to an `AssociationAdmin`."
    PRD §3.5: "Revocation is accepted from either `REQUESTED` or `APPROVED` and is available to
    an administrator, to the owning `Member`, and to the member, lockbox and listing cascades
    described in §2.9; an explicit revocation advances the listing's `version` by one, while a
    cascade-driven revocation does not."

    Design: Corner/rbac/member_cannot_approve_an_access_grant
    """
    ctx = setup_placed_box()
    grant = request_grant(
        ctx["listing_id"],
        ctx["lockbox_id"],
        member_id=ctx["agent_id"],
        grant_type="INSPECTOR",
        window_start="2026-08-06T14:00:00Z",
        window_end="2026-08-06T16:00:00Z",
    )

    refused = api.grant_state(
        grant["id"],
        {"action": "APPROVE", "expected_grant_version": grant["version"]},
        make_member_headers(ctx["agent_id"]),
    )
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert read_grant(grant["id"])["status"] == "REQUESTED"

    revoked = api.grant_state(
        grant["id"],
        {"action": "REVOKE", "expected_grant_version": grant["version"]},
        make_member_headers(ctx["agent_id"]),
    )
    data = validate_success(revoked, 200)
    assert data["status"] == "REVOKED"


def test_lockbox_device_cannot_read_the_access_log(api, device_headers, auditor_headers):
    """PRD §2.1: "A `LockboxDevice` is the hardware gateway itself. When `X-User-Role` is
    `LockboxDevice`, `X-User-ID` is an opaque device identifier not tied to any persisted
    entity; it is never compared to an entity's `id`. Its sole capability is appending an access
    attempt to the audit log, and it has no read access at all."

    Design: Corner/rbac/lockbox_device_cannot_read_the_access_log
    """
    association = register_association()
    lockbox = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
    )
    event = device_attempt(
        lockbox["id"], actor_type="UNKNOWN", occurred_at="2026-08-01T09:00:00Z"
    )

    refused = api.list_access_events(device_headers, params={"lockbox_id": lockbox["id"]})
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    allowed = api.list_access_events(auditor_headers, params={"lockbox_id": lockbox["id"]})
    rows, _ = validate_paginated(allowed)
    assert len(rows) == 1
    assert rows[0]["id"] == event["id"]


def test_stale_lockbox_version_rejects_a_reassignment(api, admin_headers):
    """PRD §2.5: "**Driving a lockbox state action.** A `POST /lockboxes/{lockboxId}/state`
    request must carry `expected_lockbox_version` as a required field, holding the client's last
    observed `version` of the addressed lockbox. If it does not equal the lockbox's current
    `version`, the action is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "Reassignment is a self-loop: an already-`ASSIGNED` box may be assigned again to a
    *different* `member_id`, which supersedes the prior holder."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lockbox_version_rejects_reassignment
    """
    association = register_association()
    ana = enroll_member(association["id"], full_name="Ana Reyes", email="ana@example.com")
    ben = enroll_member(association["id"], full_name="Ben Ortiz", email="ben@example.com")
    lockbox = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_PRO",
        replacement_cost_cents=12000,
    )
    observed_version = lockbox["version"]
    assign_lockbox(lockbox["id"], ana["id"])

    stale = api.lockbox_state(
        lockbox["id"],
        {
            "action": "ASSIGN",
            "member_id": ben["id"],
            "expected_lockbox_version": observed_version,
        },
        admin_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

    held = read_lockbox(lockbox["id"])
    assert held["assigned_member_id"] == ana["id"]
    assert held["version"] == 2

    retry = api.lockbox_state(
        lockbox["id"],
        {
            "action": "ASSIGN",
            "member_id": ben["id"],
            "expected_lockbox_version": held["version"],
        },
        admin_headers,
    )
    reassigned = validate_success(retry, 200)
    assert reassigned["assigned_member_id"] == ben["id"]
    assert reassigned["status"] == "ASSIGNED"

    assert read_association(association["id"])["boxes_in_field_count"] == 1


def test_state_action_on_an_unknown_showing_returns_appointment_not_found(api, admin_headers):
    """PRD §2.6: "3. **Path existence** (priority 10) — every identifier in the URL resolves,
    left to right, else the matching not-found error."
    PRD §2.6: "8. **Stale parent version** (priority 35) — every supplied expected-version field
    matches, else `ERR_STALE_VERSION`."

    Design: Corner/errors/showing_appointment_unknown_id_returns_not_found
    """
    register_association()

    response = api.showing_state(
        NON_EXISTENT_UUID,
        {"action": "CONFIRM", "expected_appointment_version": 1},
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value)


def test_each_resource_family_reports_its_own_not_found_code(api, admin_headers, auditor_headers):
    """PRD §2.4: "Path identifiers are validated left to right. Where a URL nests one identifier
    inside another's collection, the outer identifier is resolved first, and the first identifier
    that fails to resolve determines the 404 that is returned: `ERR_ASSOCIATION_NOT_FOUND`,
    `ERR_MEMBER_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_LOCKBOX_NOT_FOUND`,
    `ERR_LISTING_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND` or `ERR_CHARGE_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/errors/every_resource_type_returns_its_own_not_found_code
    """
    register_association()

    probes = [
        (api.get_association(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_ASSOCIATION_NOT_FOUND),
        (api.get_member(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_MEMBER_NOT_FOUND),
        (api.get_contractor(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_CONTRACTOR_NOT_FOUND),
        (api.get_placement(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_PLACEMENT_NOT_FOUND),
        (api.get_credential(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_CREDENTIAL_NOT_FOUND),
        (api.get_grant(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_GRANT_NOT_FOUND),
        (api.get_access_event(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_EVENT_NOT_FOUND),
        (api.get_incident_review(NON_EXISTENT_UUID, auditor_headers), ApiErrorId.ERR_REVIEW_NOT_FOUND),
        (api.get_billing_charge(NON_EXISTENT_UUID, admin_headers), ApiErrorId.ERR_CHARGE_NOT_FOUND),
    ]

    for response, expected in probes:
        assert response.status_code == 404, (
            f"Expected 404 for {expected.value}, got {response.status_code}"
        )
        validate_error(response, expected.value)
        assert response.json()["response_type"] == "error"
