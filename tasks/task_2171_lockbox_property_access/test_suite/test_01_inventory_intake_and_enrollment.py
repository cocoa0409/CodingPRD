"""Association registration, hardware intake and member enrollment."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_association,
    assert_lockbox,
    assert_member,
    association_payload,
    enroll_member,
    intake_lockbox,
    lockbox_payload,
    member_payload,
    placement_payload,
    read_lockbox,
    register_association,
    setup_assigned_box,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, create_listing, make_member_headers


def test_association_registration_applies_every_published_policy_default(api, admin_headers):
    """PRD §3.1: "Those dials are all optional at registration and each has a published
    default: `temp_code_daily_limit` defaults to 3 and caps how many one-day member codes
    a single member may self-issue in a UTC calendar day; `temp_code_overage_fee_cents`
    defaults to 500 and is what staff pay to push a code past that cap on a member's
    behalf; `removal_grace_days` defaults to 3 whole days and is the breathing room a
    listing agent gets to retrieve a box after a deal closes; `late_removal_daily_fee_cents`
    defaults to 1500 and `late_removal_cap_cents` defaults to 15000, together bounding the
    penalty for leaving a box behind; `credential_cap_per_member` defaults to 2 and bounds
    how many active keyholder credentials one member may hold; `grant_buffer_minutes`
    defaults to 15 and is the service buffer appended to every approved access window; and
    `recovery_target_pct` defaults to 95.00 and is the board's aspiration for on-time box
    recovery."
    PRD §3.1: "A freshly registered association starts with `posture` set to `OPEN`,
    `recovery_rate_pct` set to 0.00, and every counter at zero."

    Design: Corner/entities/association_creation_applies_every_policy_default
    """
    response = api.create_association(association_payload(), admin_headers)
    data = validate_success(response, 201)
    assert_association(data)

    assert data["temp_code_daily_limit"] == 3
    assert data["temp_code_overage_fee_cents"] == 500
    assert data["removal_grace_days"] == 3
    assert data["late_removal_daily_fee_cents"] == 1500
    assert data["late_removal_cap_cents"] == 15000
    assert data["credential_cap_per_member"] == 2
    assert data["grant_buffer_minutes"] == 15
    assert float(data["recovery_target_pct"]) == 95.00
    assert data["posture"] == "OPEN"
    assert data["version"] == 1
    assert data["lockbox_total_count"] == 0
    assert data["unplaced_inventory_count"] == 0
    assert float(data["recovery_rate_pct"]) == 0.00


def test_lockbox_read_back_returns_every_stored_intake_field(api, member_headers):
    """PRD §3.1: "Intake records the owning `association_id`, the hardware
    `serial_number`, the `model` — either `LB_STD` or `LB_PRO` — the board-published
    `replacement_cost_cents`, which must be greater than zero, and `in_service_since`, the
    ISO date the unit entered service and the origin of the depreciation clock."
    PRD §3.1: "The unit lands in `IN_STOCK`, raising both `lockbox_total_count` and
    `unplaced_inventory_count` by one, with `assigned_member_id` and `current_listing_id`
    both empty."

    Design: Corner/entities/lockbox_read_back_returns_every_stored_input_field
    """
    association = register_association()
    lockbox = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_PRO",
        replacement_cost_cents=12000,
        in_service_since="2025-08-01",
    )

    body = api.get_lockbox(lockbox["id"], member_headers)
    data = validate_success(body, 200)
    assert body.json()["response_type"] == "object"
    assert_lockbox(data)

    assert data["serial_number"] == "LB-0001"
    assert data["model"] == "LB_PRO"
    assert data["replacement_cost_cents"] == 12000
    assert data["in_service_since"] == "2025-08-01"
    assert data["status"] == "IN_STOCK"
    assert data.get("assigned_member_id") is None
    assert data.get("current_listing_id") is None
    assert data.get("loss_type") is None
    assert data.get("police_report_number") is None


def test_lockbox_listing_reports_total_count_and_has_more(api, admin_headers):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as they
    were applied, `total_count` as the number of rows matching the filters before the page
    window was applied, and `has_more` as a boolean that is true when rows remain beyond
    the current page."

    Design: Corner/entities/lockbox_list_pagination_reports_total_count_and_has_more
    """
    association = register_association()
    for serial in ("LB-0001", "LB-0002", "LB-0003"):
        intake_lockbox(
            association["id"],
            serial_number=serial,
            model="LB_STD",
            replacement_cost_cents=9000,
        )

    first = api.list_lockboxes(
        admin_headers,
        params={"association_id": association["id"], "limit": 2, "offset": 0},
    )
    rows, meta = validate_paginated(first)
    assert first.json()["response_type"] == "array"
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    second = api.list_lockboxes(
        admin_headers,
        params={"association_id": association["id"], "limit": 2, "offset": 2},
    )
    rows2, meta2 = validate_paginated(second)
    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["offset"] == 2
    assert meta2["has_more"] is False


def test_reading_an_unknown_lockbox_returns_lockbox_not_found(api, admin_headers):
    """PRD §2.4: "Path identifiers are validated left to right. Where a URL nests one
    identifier inside another's collection, the outer identifier is resolved first, and the
    first identifier that fails to resolve determines the 404 that is returned:
    `ERR_ASSOCIATION_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`,
    `ERR_LOCKBOX_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`,
    `ERR_CREDENTIAL_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`,
    `ERR_EVENT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or `ERR_CHARGE_NOT_FOUND`, each carrying
    HTTP 404."

    Design: Corner/entities/get_lockbox_with_unknown_id_returns_not_found
    """
    register_association()

    response = api.get_lockbox(NON_EXISTENT_UUID, admin_headers)
    validate_error(response, ApiErrorId.ERR_LOCKBOX_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_member_creation_without_dues_paid_through_is_invalid(api, admin_headers):
    """PRD §3.2: "Enrolling a member records their `association_id`, `full_name`, `email`
    — which must be unique within the association — and `dues_paid_through`, the ISO date
    through which association dues are paid."
    PRD §2.6: "**Request shape** (priority 20) — required fields present, enum members
    legal, integers inside their declared bounds, ISO 8601 timestamps parseable, `limit`
    inside 1 through 100 and `offset` at least 0, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_member_missing_required_field_invalid_request
    """
    association = register_association()

    response = api.create_member(
        {
            "association_id": association["id"],
            "full_name": "Ana Reyes",
            "email": "ana@example.com",
        },
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    listed = api.list_members(admin_headers, params={"association_id": association["id"]})
    rows, meta = validate_paginated(listed)
    assert rows == []
    assert meta["total_count"] == 0


def test_member_creation_ignores_client_supplied_system_fields(api, admin_headers):
    """PRD §3.2: "A member is conceptually born in `PENDING`, but never observably rests
    there: the system resolves the standing inside the creating request. If
    `dues_paid_through`, read at the end of that date, is later than the current logical
    clock, the member is created with `membership_status` of `ACTIVE`; otherwise they are
    created `EXPIRED`."
    PRD §3.2: "New members start with `active_credential_count` of 0 and
    `outstanding_balance_cents` of 0."

    Design: Corner/entities/member_system_fields_input_ignored_on_create
    """
    association = register_association()

    response = api.create_member(
        member_payload(
            association["id"],
            membership_status="TERMINATED",
            outstanding_balance_cents=9999,
        ),
        admin_headers,
    )
    data = validate_success(response, 201)
    assert_member(data)

    assert data["membership_status"] == "ACTIVE"
    assert data["outstanding_balance_cents"] == 0
    assert data["active_credential_count"] == 0
    assert data["version"] == 1


def test_member_with_lapsed_dues_is_created_expired(api, admin_headers):
    """PRD §3.2: "If `dues_paid_through`, read at the end of that date, is later than the
    current logical clock, the member is created with `membership_status` of `ACTIVE`;
    otherwise they are created `EXPIRED`. Either way this is part of creation rather than a
    mutation, so the new member's `version` remains 1."
    PRD §2.4: "Before any caller sets it, the clock reads exactly `2026-08-01T00:00:00Z`,
    and it never falls back to the host's real time."

    Design: Corner/entities/member_created_with_lapsed_dues_auto_expires_at_creation
    """
    association = register_association()

    lapsed = enroll_member(
        association["id"],
        full_name="Lapsed Larry",
        email="larry@example.com",
        dues_paid_through="2026-07-31",
    )
    current = enroll_member(
        association["id"],
        full_name="Ana Reyes",
        email="ana@example.com",
        dues_paid_through="2027-01-31",
    )

    lapsed_read = validate_success(api.get_member(lapsed["id"], admin_headers))
    current_read = validate_success(api.get_member(current["id"], admin_headers))

    assert lapsed_read["membership_status"] == "EXPIRED"
    assert lapsed_read["version"] == 1
    assert current_read["membership_status"] == "ACTIVE"
    assert current_read["version"] == 1


def test_access_event_carries_no_version_or_updated_at(api, device_headers, admin_headers):
    """PRD §2.4: "Access-log entries — the `AccessEvent` family — are the one exception and
    are deliberately austere: an access event carries `id` and `created_at` only. It has no
    `updated_at` and no `version`, because it is append-only evidence and is never modified
    after it is written."
    PRD §3.6: "Otherwise, if neither a `credential_id` nor a `grant_id` was supplied, the
    outcome is `DENIED_NO_CREDENTIAL`."

    Design: Corner/entities/access_event_is_immutable_and_carries_no_version
    """
    association = register_association()
    lockbox = intake_lockbox(
        association["id"],
        serial_number="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
    )

    response = api.device_access_attempt(
        {
            "lockbox_id": lockbox["id"],
            "actor_type": "UNKNOWN",
            "occurred_at": "2026-08-01T09:00:00Z",
        },
        device_headers,
    )
    data = validate_success(response, 201)
    assert "id" in data and "created_at" in data
    assert "version" not in data, "an access event must never carry a version"
    assert "updated_at" not in data, "an access event must never carry updated_at"

    stored = validate_success(api.get_access_event(data["id"], admin_headers))
    assert stored["outcome"] == "DENIED_NO_CREDENTIAL"
    assert stored.get("listing_id") is None
    assert stored.get("matched_appointment_id") is None


def test_lockbox_intake_rejects_an_unknown_model(api, admin_headers):
    """PRD §3.1: "Intake records the owning `association_id`, the hardware
    `serial_number`, the `model` — either `LB_STD` or `LB_PRO` — the board-published
    `replacement_cost_cents`, which must be greater than zero, and `in_service_since`, the
    ISO date the unit entered service and the origin of the depreciation clock."
    PRD §2.6: "**Request shape** (priority 20) — required fields present, enum members
    legal, integers inside their declared bounds, ISO 8601 timestamps parseable, `limit`
    inside 1 through 100 and `offset` at least 0, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/lockbox_invalid_model_enum_returns_invalid_request
    """
    association = register_association()

    response = api.create_lockbox(
        lockbox_payload(
            association["id"],
            serial_number="LB-0001",
            model="LB_ULTRA",
            replacement_cost_cents=9000,
        ),
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, _ = validate_paginated(
        api.list_lockboxes(admin_headers, params={"association_id": association["id"]})
    )
    assert rows == []


def test_placement_with_unknown_listing_returns_listing_not_found(api, admin_headers):
    """PRD §2.4: "The same catalogue governs foreign keys supplied in a request body: each
    is resolved in the order the endpoint declares its inputs, and the first unresolvable
    reference produces the corresponding not-found error."
    PRD §2.6: "**Body foreign-key existence** (priority 15) — every foreign key in the body
    resolves, in the order the endpoint declares its inputs, else the matching not-found
    error."

    Design: Corner/entities/placement_with_unknown_listing_id_returns_not_found
    """
    ctx = setup_assigned_box()

    response = api.create_placement(
        placement_payload(ctx["lockbox_id"], NON_EXISTENT_UUID),
        make_member_headers(ctx["agent_id"]),
    )
    validate_error(response, ApiErrorId.ERR_LISTING_NOT_FOUND.value)

    lockbox = read_lockbox(ctx["lockbox_id"])
    assert lockbox["status"] == "ASSIGNED"
    assert lockbox.get("current_listing_id") is None

    rows, _ = validate_paginated(
        api.list_placements(ADMIN, params={"lockbox_id": ctx["lockbox_id"]})
    )
    assert rows == []


def test_duplicate_serial_number_within_association_rejected(api, admin_headers):
    """PRD §3.1: "Serial numbers must be unique within an association; a collision is
    `ERR_DUPLICATE_SERIAL`."

    Design: Corner/entities/duplicate_serial_number_within_association_rejected
    """
    first_association = register_association()
    second_association = register_association(
        name="Puget Sound Association", jurisdiction_code="WA-PIERCE"
    )
    intake_lockbox(
        first_association["id"],
        serial_number="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
    )

    collision = api.create_lockbox(
        lockbox_payload(
            first_association["id"],
            serial_number="LB-0001",
            model="LB_STD",
            replacement_cost_cents=9000,
        ),
        admin_headers,
    )
    validate_error(collision, ApiErrorId.ERR_DUPLICATE_SERIAL.value)

    other_association = api.create_lockbox(
        lockbox_payload(
            second_association["id"],
            serial_number="LB-0001",
            model="LB_STD",
            replacement_cost_cents=9000,
        ),
        admin_headers,
    )
    validate_success(other_association, 201)

    rows_a, _ = validate_paginated(
        api.list_lockboxes(admin_headers, params={"association_id": first_association["id"]})
    )
    rows_b, _ = validate_paginated(
        api.list_lockboxes(admin_headers, params={"association_id": second_association["id"]})
    )
    assert len(rows_a) == 1
    assert len(rows_b) == 1


def test_duplicate_mls_number_within_association_rejected(api, admin_headers):
    """PRD §3.4: "Creating one records the `association_id`, the `listing_agent_id` naming
    the member who owns the listing, the `address_line` of the property, the `mls_number` —
    unique within the association, else `ERR_DUPLICATE_MLS_NUMBER` — and optionally
    `concurrent_showing_limit`, which defaults to 1 and must be at least 1."

    Design: Corner/validations/duplicate_mls_number_within_association_rejected
    """
    association = register_association()
    agent = enroll_member(association["id"])
    create_listing(
        association["id"], agent["id"], mls_number="MLS-1001", address_line="12 Pine St"
    )

    response = api.create_listing(
        {
            "association_id": association["id"],
            "listing_agent_id": agent["id"],
            "address_line": "99 Fir Ct",
            "mls_number": "MLS-1001",
        },
        make_member_headers(agent["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_MLS_NUMBER.value)

    rows, _ = validate_paginated(
        api.list_listings(admin_headers, params={"association_id": association["id"]})
    )
    assert len(rows) == 1
