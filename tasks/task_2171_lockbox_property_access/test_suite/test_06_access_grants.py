"""Temporary access grants: the daily quota, the approval gates and window geometry."""

from test_helpers import (
    ApiErrorId,
    approve_grant,
    grant_payload,
    only_charge,
    read_association,
    read_grant,
    read_listing,
    read_member,
    register_contractor,
    report_lockbox_lost,
    request_grant,
    setup_placed_box,
    setup_restricted_association,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    contractor_action,
    create_listing,
    intake_lockbox,
    assign_lockbox,
    make_member_headers,
    place_lockbox,
    read_lockbox,
)


def _agent_with_three_one_day_codes():
    """An agent who has already self-issued three one-day member codes today."""
    ctx = setup_placed_box(clock="2026-08-05T00:00:00Z")
    windows = [
        ("2026-08-06T08:00:00Z", "2026-08-06T09:00:00Z"),
        ("2026-08-06T10:00:00Z", "2026-08-06T11:00:00Z"),
        ("2026-08-06T12:00:00Z", "2026-08-06T13:00:00Z"),
    ]
    ctx["issued"] = [
        request_grant(
            ctx["listing_id"],
            ctx["lockbox_id"],
            member_id=ctx["agent_id"],
            grant_type="ONE_DAY_MEMBER",
            window_start=start,
            window_end=end,
        )
        for start, end in windows
    ]
    return ctx


def test_third_one_day_code_at_the_daily_limit_is_still_issued(api, admin_headers):
    """PRD §3.5: "A member's `temp_codes_issued_today` counts the grants that member issued
    with `grant_type` of `ONE_DAY_MEMBER` whose status is anything other than `DENIED`,
    created on the same UTC calendar date as the current logical clock."
    PRD §3.1: "`temp_code_daily_limit` defaults to 3 and caps how many one-day member codes a
    single member may self-issue in a UTC calendar day"

    Design: Difficulty/boundary_precision_check/temp_code_daily_limit_third_issue_allowed_fourth_blocked
    """
    ctx = _agent_with_three_one_day_codes()

    third = read_grant(ctx["issued"][2]["id"])
    assert third["status"] == "REQUESTED"

    rows, _ = validate_paginated(
        api.list_grants(
            admin_headers,
            params={
                "issued_by_member_id": ctx["agent_id"],
                "grant_type": "ONE_DAY_MEMBER",
            },
        )
    )
    assert len(rows) == 3
    assert read_member(ctx["agent_id"])["temp_codes_issued_today"] == 3


def test_fourth_one_day_code_by_the_member_is_blocked_by_the_quota(api, admin_headers):
    """PRD §3.5: "When a `Member` caller would push that count past the association's
    `temp_code_daily_limit`, the request is rejected with `ERR_TEMP_CODE_LIMIT_REACHED`."

    Design: Difficulty/boundary_precision_check/temp_code_daily_limit_third_issue_allowed_fourth_blocked
    """
    ctx = _agent_with_three_one_day_codes()
    listing = read_listing(ctx["listing_id"])

    response = api.create_grant(
        grant_payload(
            ctx["listing_id"],
            ctx["lockbox_id"],
            listing["version"],
            grant_type="ONE_DAY_MEMBER",
            window_start="2026-08-06T14:00:00Z",
            window_end="2026-08-06T15:00:00Z",
        ),
        make_member_headers(ctx["agent_id"]),
    )
    validate_error(response, ApiErrorId.ERR_TEMP_CODE_LIMIT_REACHED.value)

    rows, _ = validate_paginated(
        api.list_grants(
            admin_headers,
            params={
                "issued_by_member_id": ctx["agent_id"],
                "grant_type": "ONE_DAY_MEMBER",
            },
        )
    )
    assert len(rows) == 3
    assert read_member(ctx["agent_id"])["temp_codes_issued_today"] == 3


def _two_contractor_windows_on_one_box():
    """An approved window for a well-insured vendor, and a requested overlapping window for
    a vendor whose coverage has already lapsed."""
    ctx = setup_placed_box()
    insured = register_contractor(
        ctx["association_id"],
        company_name="NorthPeak Inspections",
        insurance_expires_on="2027-01-31",
    )
    lapsed = register_contractor(
        ctx["association_id"],
        company_name="RidgeGlass Repair",
        insurance_expires_on="2026-08-05",
    )
    first = request_grant(
        ctx["listing_id"],
        ctx["lockbox_id"],
        member_id=ctx["agent_id"],
        grant_type="CONTRACTOR_WINDOW",
        contractor_id=insured["id"],
        window_start="2026-08-06T14:00:00Z",
        window_end="2026-08-06T16:00:00Z",
    )
    ctx["approved_grant"] = approve_grant(first["id"])
    ctx["approved_grant_id"] = first["id"]
    second = request_grant(
        ctx["listing_id"],
        ctx["lockbox_id"],
        member_id=ctx["agent_id"],
        grant_type="CONTRACTOR_WINDOW",
        contractor_id=lapsed["id"],
        window_start="2026-08-06T15:00:00Z",
        window_end="2026-08-06T17:00:00Z",
    )
    ctx["pending_grant"] = second
    ctx["pending_grant_id"] = second["id"]
    return ctx


def test_insurance_gate_outranks_the_window_conflict_on_approval(api, admin_headers):
    """PRD §2.6: "12. **Physical-safety gate** (priority 50) — else `ERR_LOCKBOX_MISSING` or
    `ERR_CONTRACTOR_INSURANCE_EXPIRED`."
    PRD §2.6: "14. **Window geometry** (priority 60) — else `ERR_INVALID_WINDOW`,
    `ERR_GRANT_WINDOW_TOO_LONG`, `ERR_GRANT_WINDOW_CONFLICT` or
    `ERR_SHOWING_CAPACITY_EXCEEDED`."
    PRD §2.6: "Checks are evaluated in a strict ascending order and the first failure wins."

    Design: Difficulty/priority_pair_validation_conflict/grant_approval_insurance_safety_precedes_window_conflict
    """
    ctx = _two_contractor_windows_on_one_box()

    response = api.grant_state(
        ctx["pending_grant_id"],
        {"action": "APPROVE", "expected_grant_version": ctx["pending_grant"]["version"]},
        admin_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_CONTRACTOR_INSURANCE_EXPIRED.value)
    assert error["error_id"] != ApiErrorId.ERR_GRANT_WINDOW_CONFLICT.value


def test_grant_rejected_by_the_insurance_gate_stays_requested(api, admin_headers):
    """PRD §3.5: "The vendor gate applies to contractor windows: the named contractor must
    have `status` of `ACTIVE`, and their `insurance_expires_on`, read at the end of that date,
    must be at or after the grant's `window_end`; a suspended vendor or coverage that lapses
    before the window ends is `ERR_CONTRACTOR_INSURANCE_EXPIRED`."
    PRD §3.5: "On a successful approval the grant moves `REQUESTED → APPROVED`, a six-digit
    `access_code` is minted for display, and the listing's `version` advances by one because
    the property's access surface has changed."

    Design: Difficulty/priority_pair_validation_conflict/grant_approval_insurance_safety_precedes_window_conflict
    """
    ctx = _two_contractor_windows_on_one_box()
    api.grant_state(
        ctx["pending_grant_id"],
        {"action": "APPROVE", "expected_grant_version": ctx["pending_grant"]["version"]},
        admin_headers,
    )

    refused = read_grant(ctx["pending_grant_id"])
    assert refused["status"] == "REQUESTED"
    assert refused.get("access_code") is None

    assert read_grant(ctx["approved_grant_id"])["status"] == "APPROVED"


def test_contractor_window_approval_refused_while_the_vendor_is_suspended(api, admin_headers):
    """PRD §3.5: "The vendor gate applies to contractor windows: the named contractor must
    have `status` of `ACTIVE`, and their `insurance_expires_on`, read at the end of that date,
    must be at or after the grant's `window_end`; a suspended vendor or coverage that lapses
    before the window ends is `ERR_CONTRACTOR_INSURANCE_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/contractor_grant_approval_gated_by_contractor_status
    """
    ctx = setup_placed_box()
    vendor = register_contractor(
        ctx["association_id"],
        company_name="NorthPeak Inspections",
        insurance_expires_on="2027-01-31",
    )
    grant = request_grant(
        ctx["listing_id"],
        ctx["lockbox_id"],
        member_id=ctx["agent_id"],
        grant_type="CONTRACTOR_WINDOW",
        contractor_id=vendor["id"],
        window_start="2026-08-06T14:00:00Z",
        window_end="2026-08-06T16:00:00Z",
    )
    contractor_action(vendor["id"], "SUSPEND")

    response = api.grant_state(
        grant["id"],
        {"action": "APPROVE", "expected_grant_version": grant["version"]},
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_CONTRACTOR_INSURANCE_EXPIRED.value)
    assert read_grant(grant["id"])["status"] == "REQUESTED"


def test_contractor_window_approval_succeeds_once_the_vendor_is_reactivated(api, admin_headers):
    """PRD §3.1: "Staff may move a vendor to `SUSPENDED` and back to `ACTIVE` at will;
    neither state is terminal, and the pair forms a cycle `ACTIVE → SUSPENDED → ACTIVE`."
    PRD §3.5: "The vendor gate applies to contractor windows: the named contractor must have
    `status` of `ACTIVE`, and their `insurance_expires_on`, read at the end of that date, must
    be at or after the grant's `window_end`; a suspended vendor or coverage that lapses before
    the window ends is `ERR_CONTRACTOR_INSURANCE_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/contractor_grant_approval_gated_by_contractor_status
    """
    ctx = setup_placed_box()
    vendor = register_contractor(
        ctx["association_id"],
        company_name="NorthPeak Inspections",
        insurance_expires_on="2027-01-31",
    )
    grant = request_grant(
        ctx["listing_id"],
        ctx["lockbox_id"],
        member_id=ctx["agent_id"],
        grant_type="CONTRACTOR_WINDOW",
        contractor_id=vendor["id"],
        window_start="2026-08-06T14:00:00Z",
        window_end="2026-08-06T16:00:00Z",
    )
    contractor_action(vendor["id"], "SUSPEND")
    api.grant_state(
        grant["id"],
        {"action": "APPROVE", "expected_grant_version": grant["version"]},
        admin_headers,
    )
    contractor_action(vendor["id"], "REACTIVATE")

    retry = api.grant_state(
        grant["id"],
        {"action": "APPROVE", "expected_grant_version": grant["version"]},
        admin_headers,
    )
    approved = validate_success(retry, 200)
    assert approved["status"] == "APPROVED"

    stored_vendor = api.get_contractor(vendor["id"], admin_headers)
    vendor_data = validate_success(stored_vendor, 200)
    assert vendor_data["status"] == "ACTIVE"
    assert vendor_data["insurance_expires_on"] == "2027-01-31"


def _occupied_box_with_two_candidates():
    """An approved 14:00-16:00 window plus two requested windows: one starting inside the
    buffered occupation, one starting exactly at its end."""
    ctx = setup_placed_box(clock="2026-08-05T00:00:00Z")
    first = request_grant(
        ctx["listing_id"],
        ctx["lockbox_id"],
        member_id=ctx["agent_id"],
        grant_type="INSPECTOR",
        window_start="2026-08-06T14:00:00Z",
        window_end="2026-08-06T16:00:00Z",
    )
    ctx["approved_grant"] = approve_grant(first["id"])
    ctx["inside_buffer"] = request_grant(
        ctx["listing_id"],
        ctx["lockbox_id"],
        member_id=ctx["agent_id"],
        grant_type="INSPECTOR",
        window_start="2026-08-06T16:10:00Z",
        window_end="2026-08-06T17:00:00Z",
    )
    ctx["at_buffer_end"] = request_grant(
        ctx["listing_id"],
        ctx["lockbox_id"],
        member_id=ctx["agent_id"],
        grant_type="INSPECTOR",
        window_start="2026-08-06T16:15:00Z",
        window_end="2026-08-06T17:00:00Z",
    )
    return ctx


def test_window_starting_inside_the_service_buffer_conflicts(api, admin_headers):
    """PRD §2.10: "When testing whether two approved grants collide on the same physical
    unit, each grant is treated as occupying its window plus a mandatory service buffer of
    `grant_buffer_minutes` minutes appended to the end — so the occupied span runs from
    `window_start` inclusive to `window_end` plus the buffer, exclusive."
    PRD §3.5: "The occupation gate comes last: no other grant on the *same* `lockbox_id` that
    is currently in `APPROVED` may occupy an overlapping span under the half-open buffered
    arithmetic of §2.10, else `ERR_GRANT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/grant_lockbox_occupation_half_open_with_buffer_boundary
    """
    ctx = _occupied_box_with_two_candidates()

    response = api.grant_state(
        ctx["inside_buffer"]["id"],
        {"action": "APPROVE", "expected_grant_version": ctx["inside_buffer"]["version"]},
        admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_GRANT_WINDOW_CONFLICT.value)
    assert read_grant(ctx["inside_buffer"]["id"])["status"] == "REQUESTED"


def test_window_starting_exactly_at_the_buffered_end_is_approved(api, admin_headers):
    """PRD §2.10: "Two occupied spans collide when the first begins strictly before the
    second ends and the second begins strictly before the first ends. Because both comparisons
    are strict, a window that begins exactly at another's buffered end does not collide."

    Design: Difficulty/resource_temporal_overlap/grant_lockbox_occupation_half_open_with_buffer_boundary
    """
    ctx = _occupied_box_with_two_candidates()
    api.grant_state(
        ctx["inside_buffer"]["id"],
        {"action": "APPROVE", "expected_grant_version": ctx["inside_buffer"]["version"]},
        admin_headers,
    )

    response = api.grant_state(
        ctx["at_buffer_end"]["id"],
        {"action": "APPROVE", "expected_grant_version": ctx["at_buffer_end"]["version"]},
        admin_headers,
    )
    approved = validate_success(response, 200)
    assert approved["status"] == "APPROVED"

    rows, _ = validate_paginated(
        api.list_grants(
            admin_headers,
            params={"lockbox_id": ctx["lockbox_id"], "status": "APPROVED"},
        )
    )
    assert len(rows) == 2


def test_zero_length_grant_window_is_rejected(api, admin_headers):
    """PRD §3.5: "The `window_start` must be strictly earlier than the `window_end`, else
    `ERR_INVALID_WINDOW`."

    Design: Corner/validations/grant_window_start_not_before_end_invalid_window
    """
    ctx = setup_placed_box()
    listing = read_listing(ctx["listing_id"])

    response = api.create_grant(
        grant_payload(
            ctx["listing_id"],
            ctx["lockbox_id"],
            listing["version"],
            grant_type="ONE_DAY_MEMBER",
            window_start="2026-08-06T14:00:00Z",
            window_end="2026-08-06T14:00:00Z",
        ),
        make_member_headers(ctx["agent_id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW.value)

    rows, _ = validate_paginated(
        api.list_grants(admin_headers, params={"listing_id": ctx["listing_id"]})
    )
    assert rows == []
    assert read_listing(ctx["listing_id"])["version"] == listing["version"]


def test_one_day_member_window_longer_than_a_day_is_too_long(api, admin_headers):
    """PRD §3.5: "Duration is capped by flavour: a `ONE_DAY_MEMBER` or `INSPECTOR` window may
    span at most twenty-four hours, and a `CONTRACTOR_WINDOW` may span at most seven days;
    exceeding the applicable cap is `ERR_GRANT_WINDOW_TOO_LONG`."
    PRD §3.5: "A member's `temp_codes_issued_today` counts the grants that member issued with
    `grant_type` of `ONE_DAY_MEMBER` whose status is anything other than `DENIED`, created on
    the same UTC calendar date as the current logical clock."

    Design: Corner/validations/one_day_member_grant_longer_than_24_hours_too_long
    """
    ctx = setup_placed_box()
    vendor = register_contractor(
        ctx["association_id"],
        company_name="NorthPeak Inspections",
        insurance_expires_on="2027-01-31",
    )
    listing = read_listing(ctx["listing_id"])

    too_long = api.create_grant(
        grant_payload(
            ctx["listing_id"],
            ctx["lockbox_id"],
            listing["version"],
            grant_type="ONE_DAY_MEMBER",
            window_start="2026-08-06T08:00:00Z",
            window_end="2026-08-07T09:00:00Z",
        ),
        make_member_headers(ctx["agent_id"]),
    )
    validate_error(too_long, ApiErrorId.ERR_GRANT_WINDOW_TOO_LONG.value)

    accepted = api.create_grant(
        grant_payload(
            ctx["listing_id"],
            ctx["lockbox_id"],
            listing["version"],
            grant_type="CONTRACTOR_WINDOW",
            contractor_id=vendor["id"],
            window_start="2026-08-06T08:00:00Z",
            window_end="2026-08-07T09:00:00Z",
        ),
        make_member_headers(ctx["agent_id"]),
    )
    created = validate_success(accepted, 201)
    assert created["status"] == "REQUESTED"
    assert created["grant_type"] == "CONTRACTOR_WINDOW"

    assert read_member(ctx["agent_id"])["temp_codes_issued_today"] == 0


def test_grant_for_a_box_not_on_that_listing_is_refused(api, admin_headers):
    """PRD §3.5: "The named box must actually be on the named property: there must be a
    placement whose `placement_status` is `PLACED` joining that `lockbox_id` to that
    `listing_id`, else `ERR_LOCKBOX_NOT_ON_LISTING`."

    Design: Corner/validations/grant_for_lockbox_not_placed_on_that_listing_referential
    """
    ctx = setup_placed_box(serial="LB-0001", model="LB_STD", replacement_cost_cents=9000)
    other_box = intake_lockbox(
        ctx["association_id"],
        serial_number="LB-0002",
        model="LB_STD",
        replacement_cost_cents=9000,
    )
    assign_lockbox(other_box["id"], ctx["agent_id"])
    other_listing = create_listing(
        ctx["association_id"],
        ctx["agent_id"],
        mls_number="MLS-1002",
        address_line="34 Cedar Ave",
    )
    place_lockbox(other_box["id"], other_listing["id"], ctx["agent_id"])
    listing = read_listing(other_listing["id"])

    response = api.create_grant(
        grant_payload(
            other_listing["id"],
            ctx["lockbox_id"],
            listing["version"],
            grant_type="ONE_DAY_MEMBER",
            window_start="2026-08-06T14:00:00Z",
            window_end="2026-08-06T16:00:00Z",
        ),
        make_member_headers(ctx["agent_id"]),
    )
    validate_error(response, ApiErrorId.ERR_LOCKBOX_NOT_ON_LISTING.value)

    rows, _ = validate_paginated(
        api.list_grants(admin_headers, params={"listing_id": other_listing["id"]})
    )
    assert rows == []


def test_restricted_posture_blocks_only_contractor_windows(api, admin_headers):
    """PRD §2.8: "A `RESTRICTED` association blocks only grants whose `grant_type` is
    `CONTRACTOR_WINDOW`, whether at creation or at approval, with `ERR_ASSOCIATION_RESTRICTED`
    (HTTP 409); one-day member codes and inspector codes continue to flow, and placements are
    unaffected by `RESTRICTED`."

    Design: Corner/validations/restricted_association_blocks_only_contractor_window_grants
    """
    ctx = setup_restricted_association()
    vendor = register_contractor(
        ctx["association_id"],
        company_name="NorthPeak Inspections",
        insurance_expires_on="2027-01-31",
    )
    assert read_association(ctx["association_id"])["posture"] == "RESTRICTED"

    listing = read_listing(ctx["other_listing_id"])
    blocked = api.create_grant(
        grant_payload(
            ctx["other_listing_id"],
            ctx["clean_lockbox_id"],
            listing["version"],
            grant_type="CONTRACTOR_WINDOW",
            contractor_id=vendor["id"],
            window_start="2026-08-06T14:00:00Z",
            window_end="2026-08-06T16:00:00Z",
        ),
        make_member_headers(ctx["other_agent_id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_ASSOCIATION_RESTRICTED.value)

    allowed = api.create_grant(
        grant_payload(
            ctx["other_listing_id"],
            ctx["clean_lockbox_id"],
            listing["version"],
            grant_type="INSPECTOR",
            window_start="2026-08-06T14:00:00Z",
            window_end="2026-08-06T16:00:00Z",
        ),
        make_member_headers(ctx["other_agent_id"]),
    )
    created = validate_success(allowed, 201)
    assert created["status"] == "REQUESTED"
    assert created["grant_type"] == "INSPECTOR"


def test_admin_issuance_over_the_daily_cap_accrues_an_overage_charge(api, admin_headers):
    """PRD §3.5: "An `AssociationAdmin` issuing on a member's behalf is **not** blocked by the
    cap; instead, an over-cap administrator issuance succeeds and raises a charge of
    `charge_type` `TEMP_CODE_OVERAGE` against that member for the association's
    `temp_code_overage_fee_cents`, after which the member's `outstanding_balance_cents` is
    recomputed."
    PRD §3.5: "That charge is the only one in the system with no lockbox attached, so its
    `lockbox_id` is empty, and its `variant_applied` is `NOT_APPLICABLE`."

    Design: Corner/endpoints/admin_issued_grant_over_daily_cap_accrues_overage_charge
    """
    ctx = _agent_with_three_one_day_codes()
    listing = read_listing(ctx["listing_id"])

    response = api.create_grant(
        grant_payload(
            ctx["listing_id"],
            ctx["lockbox_id"],
            listing["version"],
            grant_type="ONE_DAY_MEMBER",
            window_start="2026-08-06T14:00:00Z",
            window_end="2026-08-06T15:00:00Z",
        ),
        admin_headers,
    )
    created = validate_success(response, 201)
    assert created["status"] == "REQUESTED"
    assert created["issued_by_member_id"] == ctx["agent_id"]

    charge = only_charge(member_id=ctx["agent_id"], charge_type="TEMP_CODE_OVERAGE")
    assert charge["amount_cents"] == 500
    assert charge["status"] == "PENDING"
    assert charge.get("lockbox_id") is None
    assert charge["variant_applied"] == "NOT_APPLICABLE"

    member = read_member(ctx["agent_id"])
    assert member["outstanding_balance_cents"] == 513
    assert member["temp_codes_issued_today"] == 4


def test_stale_listing_version_rejects_a_second_grant_create(api, admin_headers):
    """PRD §2.5: "**Requesting an access grant.** A `POST /access-grants` request must carry
    `expected_listing_version` as a required field, holding the client's last observed
    `version` of the listing named by `listing_id`. If it does not equal the listing's current
    `version` — for example because another writer has already had a grant approved on that
    listing, which advances the listing's version — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_listing_version_rejects_second_grant_create
    """
    ctx = setup_placed_box(clock="2026-08-05T00:00:00Z")
    observed = read_listing(ctx["listing_id"])["version"]

    first = validate_success(
        api.create_grant(
            grant_payload(
                ctx["listing_id"],
                ctx["lockbox_id"],
                observed,
                grant_type="INSPECTOR",
                window_start="2026-08-06T08:00:00Z",
                window_end="2026-08-06T09:00:00Z",
            ),
            make_member_headers(ctx["agent_id"]),
        ),
        201,
    )

    stale = api.create_grant(
        grant_payload(
            ctx["listing_id"],
            ctx["lockbox_id"],
            observed,
            grant_type="INSPECTOR",
            window_start="2026-08-06T10:00:00Z",
            window_end="2026-08-06T11:00:00Z",
        ),
        make_member_headers(ctx["agent_id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

    rows, _ = validate_paginated(
        api.list_grants(admin_headers, params={"listing_id": ctx["listing_id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]

    refreshed = read_listing(ctx["listing_id"])["version"]
    retry = api.create_grant(
        grant_payload(
            ctx["listing_id"],
            ctx["lockbox_id"],
            refreshed,
            grant_type="INSPECTOR",
            window_start="2026-08-06T10:00:00Z",
            window_end="2026-08-06T11:00:00Z",
        ),
        make_member_headers(ctx["agent_id"]),
    )
    second = validate_success(retry, 201)
    assert second["status"] == "REQUESTED"

    rows_after, _ = validate_paginated(
        api.list_grants(admin_headers, params={"listing_id": ctx["listing_id"]})
    )
    assert len(rows_after) == 2


def test_grant_on_a_missing_box_reports_the_safety_error_first(api, admin_headers):
    """PRD §3.5: "And a box in `MISSING` can back nothing, so a grant naming one is refused
    with `ERR_LOCKBOX_MISSING`."
    PRD §2.6: "Checks are evaluated in a strict ascending order and the first failure wins."

    Design: Corner/errors/grant_creation_on_a_missing_lockbox_raises_safety_error_first
    """
    ctx = setup_placed_box(clock="2026-08-05T00:00:00Z")
    report_lockbox_lost(ctx["lockbox_id"])

    association = read_association(ctx["association_id"])
    assert association["missing_box_count"] == 1
    assert association["delinquent_placement_count"] == 1
    assert association["active_placement_count"] == 1
    assert association["posture"] == "FROZEN"

    listing = read_listing(ctx["listing_id"])
    response = api.create_grant(
        grant_payload(
            ctx["listing_id"],
            ctx["lockbox_id"],
            listing["version"],
            grant_type="INSPECTOR",
            window_start="2026-08-06T14:00:00Z",
            window_end="2026-08-06T16:00:00Z",
        ),
        make_member_headers(ctx["agent_id"]),
    )
    error = validate_error(response, ApiErrorId.ERR_LOCKBOX_MISSING.value)
    assert error["error_id"] not in (
        ApiErrorId.ERR_ASSOCIATION_FROZEN.value,
        ApiErrorId.ERR_LOCKBOX_NOT_ON_LISTING.value,
    )
    assert read_lockbox(ctx["lockbox_id"])["status"] == "MISSING"
