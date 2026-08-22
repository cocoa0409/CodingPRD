"""Committing a commissioned officer to a concrete window."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_inspection_order,
    assert_instant_equals,
    change_inspector_status,
    commission_inspector,
    create_lot_payload,
    enrol_owner,
    inspector_version,
    make_field_inspector_headers,
    make_livestock_owner_headers,
    open_district,
    read_inspector,
    read_order,
    read_owner,
    request_inspection,
    schedule_order_payload,
    setup_busy_inspector_day,
    setup_cancelled_order_for_suspended_owner,
    setup_cross_district_inspector,
    setup_suspended_commission,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

BOARD_ADMIN = TEST_USERS["board_admin_headers"]
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


# ─── Competing scheduling guards ──────────────────────────────────────────────

def test_window_collision_is_reported_ahead_of_the_daily_ceiling(api):
    """PRD §3.5: "Both comparisons are strict, which is what makes windows half-open:
    two back-to-back windows inside one district that touch exactly at an endpoint do
    not collide, while two windows that touch exactly at an endpoint across a district
    line do collide, because the 45-minute buffer pushes them into each other. A
    collision yields `ERR_INSPECTOR_WINDOW_CONFLICT`."
    PRD §2.8: "Brand exclusivity by recording priority (`ERR_BRAND_CONFLICT_EXISTS`) is
    evaluated first, then the theft-hold gate on fee operations (`ERR_ORDER_HOLD_ACTIVE`),
    then the district intake posture for an estray impound
    (`ERR_FACILITY_INTAKE_RESTRICTED`), then inspector availability
    (`ERR_INSPECTOR_UNAVAILABLE`), then the buffered window collision
    (`ERR_INSPECTOR_WINDOW_CONFLICT`), then the statutory-hold gate on scheduling an
    auction (`ERR_HOLD_PERIOD_NOT_ELAPSED`), then the claim-window gate on filing an
    estray claim (`ERR_CLAIM_WINDOW_CLOSED`), then the inspector's daily assignment
    ceiling (`ERR_INSPECTOR_DAILY_LIMIT`), then projected facility capacity
    (`ERR_FACILITY_CAPACITY_EXCEEDED`), then the uniqueness constraints
    (`ERR_DUPLICATE_DOCUMENT_NUMBER`, `ERR_DUPLICATE_BADGE_NUMBER`,
    `ERR_DUPLICATE_TERRITORY_CODE`), then the renewability of the prior record at
    recording time (`ERR_PRIOR_REGISTRATION_NOT_RENEWABLE`), then the tendered
    instrument's agreement with the lot (`ERR_BILL_OF_SALE_MISMATCH`), then the
    inspector's home-state match (`ERR_TERRITORY_MISMATCH`), then the owner's fiscal
    standing (`ERR_OWNER_STANDING_SUSPENDED`), then the late-renewal cutoff
    (`ERR_REGISTRATION_UNRENEWABLE`), and last of all the remittance overpayment test
    (`ERR_REMITTANCE_AMOUNT_INVALID`)."

    Design: Difficulty/priority_pair_validation_conflict/window_conflict_temporal_beats_daily_limit_constraint
    """
    scenario = setup_busy_inspector_day(max_daily_assignments=1)
    assert scenario["inspector_version"] == 2

    response = api.schedule_order(
        scenario["pending_order"]["id"],
        schedule_order_payload(
            scenario["inspector"]["id"],
            scenario["inspector_version"],
            scheduled_start_at="2026-08-10T10:00:00Z",
            scheduled_end_at="2026-08-10T12:00:00Z",
        ),
        BOARD_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT.value, 409)


def test_daily_ceiling_is_not_reported_when_the_window_also_collides(api):
    """PRD §3.5: "**Daily ceiling:** among those same occupied orders, the board counts
    how many have a `scheduled_start_at` falling on the same UTC calendar date as the
    proposed start; if that count is already at or above the inspector's
    `max_daily_assignments`, the assignment yields `ERR_INSPECTOR_DAILY_LIMIT`."
    PRD §2.8: "The server therefore evaluates every request through a fixed ladder,
    stopping at the first rung that fails and returning that rung's error."
    PRD §2.8: "Brand exclusivity by recording priority (`ERR_BRAND_CONFLICT_EXISTS`) is
    evaluated first, then the theft-hold gate on fee operations (`ERR_ORDER_HOLD_ACTIVE`),
    then the district intake posture for an estray impound
    (`ERR_FACILITY_INTAKE_RESTRICTED`), then inspector availability
    (`ERR_INSPECTOR_UNAVAILABLE`), then the buffered window collision
    (`ERR_INSPECTOR_WINDOW_CONFLICT`), then the statutory-hold gate on scheduling an
    auction (`ERR_HOLD_PERIOD_NOT_ELAPSED`), then the claim-window gate on filing an
    estray claim (`ERR_CLAIM_WINDOW_CLOSED`), then the inspector's daily assignment
    ceiling (`ERR_INSPECTOR_DAILY_LIMIT`), then projected facility capacity
    (`ERR_FACILITY_CAPACITY_EXCEEDED`), then the uniqueness constraints
    (`ERR_DUPLICATE_DOCUMENT_NUMBER`, `ERR_DUPLICATE_BADGE_NUMBER`,
    `ERR_DUPLICATE_TERRITORY_CODE`), then the renewability of the prior record at
    recording time (`ERR_PRIOR_REGISTRATION_NOT_RENEWABLE`), then the tendered
    instrument's agreement with the lot (`ERR_BILL_OF_SALE_MISMATCH`), then the
    inspector's home-state match (`ERR_TERRITORY_MISMATCH`), then the owner's fiscal
    standing (`ERR_OWNER_STANDING_SUSPENDED`), then the late-renewal cutoff
    (`ERR_REGISTRATION_UNRENEWABLE`), and last of all the remittance overpayment test
    (`ERR_REMITTANCE_AMOUNT_INVALID`)."

    Design: Difficulty/priority_pair_validation_conflict/window_conflict_temporal_beats_daily_limit_constraint
    """
    scenario = setup_busy_inspector_day(max_daily_assignments=1)

    response = api.schedule_order(
        scenario["pending_order"]["id"],
        schedule_order_payload(
            scenario["inspector"]["id"],
            scenario["inspector_version"],
            scheduled_start_at="2026-08-10T10:00:00Z",
            scheduled_end_at="2026-08-10T12:00:00Z",
        ),
        BOARD_ADMIN,
    )
    error = validate_error(response, ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INSPECTOR_DAILY_LIMIT.value

    unchanged = read_order(scenario["pending_order"]["id"])
    assert unchanged["schedule_status"] == "REQUESTED"
    assert unchanged["inspector_id"] is None

    inspector = read_inspector(scenario["inspector"]["id"])
    assert inspector["version"] == 2, "a refused assignment never advances the officer"
    assert inspector["active_assignment_count"] == 1


def test_cancelled_order_reports_not_schedulable_over_suspended_standing(api):
    """PRD §3.5: "The order must be sitting at `REQUESTED`; an order already scheduled,
    in the field, completed or cancelled yields `ERR_ORDER_NOT_SCHEDULABLE`."
    PRD §2.8: "**Eighth**, the state rung: the target row must currently sit in a state
    from which the requested transition is declared, evaluated independently for each
    state dimension a row carries."
    PRD §2.8: "Only once all of the above have passed does the server reach the board's
    substantive rules, and those too are ordered."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_order_state_beats_suspended_owner_fiscal
    """
    scenario = setup_cancelled_order_for_suspended_owner()
    assert scenario["delinquent_order"]["assessed_fee_cents"] == 25000
    assert scenario["sweep"]["suspended_owner_count"] == 1
    assert scenario["cancelled_order"]["schedule_status"] == "CANCELLED"

    owner = read_owner(scenario["owner"]["id"])
    assert owner["standing"] == "SUSPENDED"
    assert owner["posted_arrears_cents"] == 25000

    response = api.schedule_order(
        scenario["cancelled_order"]["id"],
        schedule_order_payload(
            scenario["spare_inspector"]["id"],
            scenario["spare_inspector"]["version"],
            scheduled_start_at="2026-09-05T09:00:00Z",
            scheduled_end_at="2026-09-05T11:00:00Z",
        ),
        BOARD_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_ORDER_NOT_SCHEDULABLE.value, 409)


def test_suspended_standing_is_not_reported_for_a_cancelled_order(api):
    """PRD §3.5: "One further gate is fiscal rather than operational: the order's owner
    must be in good standing."
    PRD §3.5: "An owner whose `standing` reads `SUSPENDED` cannot have new work
    scheduled, and the attempt is refused with `ERR_OWNER_STANDING_SUSPENDED` (HTTP 402
    Payment Required)."
    PRD §3.5: "The order must be sitting at `REQUESTED`; an order already scheduled, in
    the field, completed or cancelled yields `ERR_ORDER_NOT_SCHEDULABLE`."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_order_state_beats_suspended_owner_fiscal
    """
    scenario = setup_cancelled_order_for_suspended_owner()

    response = api.schedule_order(
        scenario["cancelled_order"]["id"],
        schedule_order_payload(
            scenario["spare_inspector"]["id"],
            scenario["spare_inspector"]["version"],
            scheduled_start_at="2026-09-05T09:00:00Z",
            scheduled_end_at="2026-09-05T11:00:00Z",
        ),
        BOARD_ADMIN,
    )
    error = validate_error(response, ApiErrorId.ERR_ORDER_NOT_SCHEDULABLE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_OWNER_STANDING_SUSPENDED.value

    unchanged = read_order(scenario["cancelled_order"]["id"])
    assert unchanged["schedule_status"] == "CANCELLED"
    assert unchanged["inspector_id"] is None
    assert read_inspector(scenario["spare_inspector"]["id"])["version"] == 1


# ─── Commission availability ──────────────────────────────────────────────────

def test_assignment_is_refused_while_the_commission_is_suspended(api):
    """PRD §3.5: "**Availability:** the named inspector's `status` must be `ACTIVE`, and
    their `certification_expires_on` must be strictly later than `scheduled_end_at`; a
    suspended or retired commission, or one that expires at or before the proposed
    window ends, yields `ERR_INSPECTOR_UNAVAILABLE`."
    PRD §3.1: "A `BoardAdmin` may later move an inspector's `status` between `ACTIVE`,
    `SUSPENDED` and `RETIRED` by supplying the new `status`; every such change increments
    the inspector's `version` by one, which by design invalidates any scheduling token a
    client was holding."

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_suspended_inspector
    """
    scenario = setup_suspended_commission()
    assert scenario["inspector"]["status"] == "SUSPENDED"
    assert scenario["inspector"]["version"] == 2

    response = api.schedule_order(
        scenario["order"]["id"],
        schedule_order_payload(
            scenario["inspector"]["id"],
            scenario["inspector"]["version"],
            scheduled_start_at="2026-08-10T09:00:00Z",
            scheduled_end_at="2026-08-10T11:00:00Z",
        ),
        BOARD_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INSPECTOR_UNAVAILABLE.value, 409)
    assert read_order(scenario["order"]["id"])["schedule_status"] == "REQUESTED"


def test_the_same_assignment_succeeds_once_the_commission_returns_to_active(api):
    """PRD §3.5: "**Availability:** the named inspector's `status` must be `ACTIVE`, and
    their `certification_expires_on` must be strictly later than `scheduled_end_at`; a
    suspended or retired commission, or one that expires at or before the proposed
    window ends, yields `ERR_INSPECTOR_UNAVAILABLE`."
    PRD §3.5: "When every gate clears, the order advances `REQUESTED → SCHEDULED`, its
    `inspector_id` and both scheduled instants are stamped from the payload, the assigned
    inspector's `version` increments by one, and that inspector's
    `active_assignment_count` is recomputed."

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_suspended_inspector
    """
    scenario = setup_suspended_commission()

    refused = api.schedule_order(
        scenario["order"]["id"],
        schedule_order_payload(
            scenario["inspector"]["id"], scenario["inspector"]["version"],
            scheduled_start_at="2026-08-10T09:00:00Z",
            scheduled_end_at="2026-08-10T11:00:00Z",
        ),
        BOARD_ADMIN,
    )
    validate_error(refused, ApiErrorId.ERR_INSPECTOR_UNAVAILABLE.value, 409)

    reinstated = change_inspector_status(scenario["inspector"]["id"], "ACTIVE")
    assert reinstated["version"] == 3

    scheduled = validate_success(
        api.schedule_order(
            scenario["order"]["id"],
            schedule_order_payload(
                scenario["inspector"]["id"], reinstated["version"],
                scheduled_start_at="2026-08-10T09:00:00Z",
                scheduled_end_at="2026-08-10T11:00:00Z",
            ),
            BOARD_ADMIN,
        ),
        200,
    )

    assert_inspection_order(scheduled)
    assert scheduled["schedule_status"] == "SCHEDULED"
    assert scheduled["inspector_id"] == scenario["inspector"]["id"]
    assert_instant_equals(
        scheduled["scheduled_start_at"], "2026-08-10T09:00:00Z", "scheduled_start_at"
    )

    inspector = read_inspector(scenario["inspector"]["id"])
    assert inspector["version"] == 4
    assert inspector["active_assignment_count"] == 1


# ─── The buffered window geometry ─────────────────────────────────────────────

def test_touching_windows_collide_across_a_district_line(api):
    """PRD §3.5: "Each occupied window is padded by a travel buffer that depends on
    geography: when the occupied order sits in the same district as the one being
    scheduled the buffer is zero, and when it sits in a different district the buffer is
    45 minutes on each comparison."
    PRD §3.5: "Both comparisons are strict, which is what makes windows half-open: two
    back-to-back windows inside one district that touch exactly at an endpoint do not
    collide, while two windows that touch exactly at an endpoint across a district line
    do collide, because the 45-minute buffer pushes them into each other. A collision
    yields `ERR_INSPECTOR_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/inspector_cross_district_buffer_rejects_touching_windows
    """
    scenario = setup_cross_district_inspector()
    assert scenario["inspector_version"] == 2

    response = api.schedule_order(
        scenario["southern_order"]["id"],
        schedule_order_payload(
            scenario["inspector"]["id"], scenario["inspector_version"],
            scheduled_start_at="2026-08-10T11:00:00Z",
            scheduled_end_at="2026-08-10T13:00:00Z",
        ),
        BOARD_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT.value, 409)

    unchanged = read_order(scenario["southern_order"]["id"])
    assert unchanged["schedule_status"] == "REQUESTED"
    assert unchanged["inspector_id"] is None


def test_touching_windows_are_accepted_inside_one_district(api):
    """PRD §3.5: "Each occupied window is padded by a travel buffer that depends on
    geography: when the occupied order sits in the same district as the one being
    scheduled the buffer is zero, and when it sits in a different district the buffer is
    45 minutes on each comparison."
    PRD §3.5: "Both comparisons are strict, which is what makes windows half-open: two
    back-to-back windows inside one district that touch exactly at an endpoint do not
    collide, while two windows that touch exactly at an endpoint across a district line
    do collide, because the 45-minute buffer pushes them into each other. A collision
    yields `ERR_INSPECTOR_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/inspector_cross_district_buffer_rejects_touching_windows
    """
    scenario = setup_cross_district_inspector()

    scheduled = validate_success(
        api.schedule_order(
            scenario["northern_order"]["id"],
            schedule_order_payload(
                scenario["inspector"]["id"], scenario["inspector_version"],
                scheduled_start_at="2026-08-10T11:00:00Z",
                scheduled_end_at="2026-08-10T13:00:00Z",
            ),
            BOARD_ADMIN,
        ),
        200,
    )

    assert scheduled["schedule_status"] == "SCHEDULED"
    assert_instant_equals(
        scheduled["scheduled_start_at"], "2026-08-10T11:00:00Z", "scheduled_start_at"
    )

    inspector = read_inspector(scenario["inspector"]["id"])
    assert inspector["version"] == 3
    assert inspector["active_assignment_count"] == 2


def test_daily_ceiling_fires_for_non_overlapping_same_day_windows(api):
    """PRD §3.5: "**Daily ceiling:** among those same occupied orders, the board counts
    how many have a `scheduled_start_at` falling on the same UTC calendar date as the
    proposed start; if that count is already at or above the inspector's
    `max_daily_assignments`, the assignment yields `ERR_INSPECTOR_DAILY_LIMIT`."

    Design: Corner/errors/corner_inspector_daily_limit_reached_without_overlap
    """
    owner = enrol_owner("Daily Limit Ranch", contact_email="daily@example.test")
    territory = open_district("T-DAY")
    inspector = commission_inspector(territory["id"], max_daily_assignments=1)
    held = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    validate_success(
        api.schedule_order(
            held["id"],
            schedule_order_payload(
                inspector["id"], inspector["version"],
                scheduled_start_at="2026-08-10T09:00:00Z",
                scheduled_end_at="2026-08-10T10:00:00Z",
            ),
            BOARD_ADMIN,
        ),
        200,
    )
    pending = request_inspection(
        owner["id"], territory["id"], inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    current_version = inspector_version(inspector["id"])
    assert current_version == 2

    response = api.schedule_order(
        pending["id"],
        schedule_order_payload(
            inspector["id"], current_version,
            scheduled_start_at="2026-08-10T14:00:00Z",
            scheduled_end_at="2026-08-10T15:00:00Z",
        ),
        BOARD_ADMIN,
    )

    error = validate_error(response, ApiErrorId.ERR_INSPECTOR_DAILY_LIMIT.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT.value
    assert read_order(pending["id"])["schedule_status"] == "REQUESTED"
    reread = read_inspector(inspector["id"])
    assert reread["active_assignment_count"] == 1 and reread["version"] == 2


def test_scheduled_window_must_sit_inside_the_requested_window(api):
    """PRD §3.5: "The assigned window must fall inside the window the owner offered, and
    it must be a real interval — both conditions are enforced at the request-shape rung
    of §2.8."
    PRD §2.8: "Any of these failing yields `ERR_INVALID_REQUEST` (HTTP 400 Bad Request)."

    Design: Corner/validations/corner_scheduled_window_outside_requested_window_rejected
    """
    owner = enrol_owner("Window Ranch", contact_email="win@example.test")
    territory = open_district("T-WIN")
    inspector = commission_inspector(territory["id"])
    order = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )

    response = api.schedule_order(
        order["id"],
        schedule_order_payload(
            inspector["id"], inspector["version"],
            scheduled_start_at="2026-08-10T16:00:00Z",
            scheduled_end_at="2026-08-10T18:00:00Z",
        ),
        BOARD_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert read_order(order["id"])["schedule_status"] == "REQUESTED"
    assert read_inspector(inspector["id"])["version"] == 1


def test_inspector_from_another_state_is_refused(api):
    """PRD §3.5: "**Jurisdiction:** the inspector's home district and the order's
    district must carry the same `state_code`."
    PRD §3.5: "Working a neighbouring district inside the same state is entirely
    permitted — it is exactly the case the cross-district travel buffer exists for — but
    crossing a state line is refused with `ERR_TERRITORY_MISMATCH` (HTTP 422)."

    Design: Corner/validations/corner_cross_state_inspector_assignment_rejected
    """
    owner = enrol_owner("Border Ranch", contact_email="border@example.test")
    montana = open_district("T-MT", state_code="MT")
    wyoming = open_district("T-WY", state_code="WY")
    inspector = commission_inspector(wyoming["id"])
    order = request_inspection(
        owner["id"], montana["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )

    response = api.schedule_order(
        order["id"],
        schedule_order_payload(
            inspector["id"], inspector["version"],
            scheduled_start_at="2026-08-10T09:00:00Z",
            scheduled_end_at="2026-08-10T11:00:00Z",
        ),
        BOARD_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_TERRITORY_MISMATCH.value, 422)
    unchanged = read_order(order["id"])
    assert unchanged["schedule_status"] == "REQUESTED"
    assert unchanged["inspector_id"] is None
    assert read_inspector(inspector["id"])["version"] == 1


def test_stale_inspector_version_is_refused_then_accepted_after_a_refresh(api):
    """PRD §2.7: "Assigning an inspection order to an inspector —
    `POST /brand-inspection/inspection-orders/{id}/schedule` — requires
    `expected_inspector_version`, carrying the client's last-observed `version` of the
    `Inspector` being assigned."
    PRD §2.7: "If the inspector's `version` has advanced since the client read that
    inspector's calendar, the assignment is refused with `ERR_STALE_INSPECTOR_VERSION`
    (HTTP 412 Precondition Failed)."

    Design: Corner/cross_cutting_layers/corner_occ_stale_inspector_version_rejected
    """
    owner = enrol_owner("OCC Inspector Ranch", contact_email="occi@example.test")
    territory = open_district("T-OCCI")
    inspector = commission_inspector(territory["id"])
    assert inspector["version"] == 1

    first = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    validate_success(
        api.schedule_order(
            first["id"],
            schedule_order_payload(
                inspector["id"], 1,
                scheduled_start_at="2026-08-10T09:00:00Z",
                scheduled_end_at="2026-08-10T10:00:00Z",
            ),
            BOARD_ADMIN,
        ),
        200,
    )
    second = request_inspection(
        owner["id"], territory["id"], inspection_purpose="MOVEMENT",
        requested_window_start_at="2026-08-14T08:00:00Z",
        requested_window_end_at="2026-08-14T17:00:00Z",
    )

    stale = api.schedule_order(
        second["id"],
        schedule_order_payload(
            inspector["id"], 1,
            scheduled_start_at="2026-08-14T09:00:00Z",
            scheduled_end_at="2026-08-14T10:00:00Z",
        ),
        BOARD_ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_INSPECTOR_VERSION.value, 412)

    refreshed = inspector_version(inspector["id"])
    assert refreshed == 2

    scheduled = validate_success(
        api.schedule_order(
            second["id"],
            schedule_order_payload(
                inspector["id"], refreshed,
                scheduled_start_at="2026-08-14T09:00:00Z",
                scheduled_end_at="2026-08-14T10:00:00Z",
            ),
            BOARD_ADMIN,
        ),
        200,
    )
    assert scheduled["schedule_status"] == "SCHEDULED"
    reread = read_inspector(inspector["id"])
    assert reread["version"] == 3
    assert reread["active_assignment_count"] == 2


def test_unknown_order_is_reported_before_an_unknown_inspector(api):
    """PRD §2.8: "Every identifier embedded in the URL must resolve to a live row, and
    identifiers are resolved strictly left to right so that the outermost missing
    resource is the one reported."
    PRD §2.8: "**Fifth**, body reference resolution: every foreign key supplied in the
    request payload must likewise resolve, which covers `owner_id`, `territory_id`,
    `inspector_id`, `prior_registration_id`, `respondent_registration_id`,
    `contested_application_id`, `brand_registration_id`, `bill_of_sale_id`,
    `seller_owner_id`, `buyer_owner_id` and each element of `covered_order_ids`."

    Design: Corner/validations/corner_path_existence_checked_before_body_existence
    """
    territory = open_district("T-ORD")
    inspector = commission_inspector(territory["id"])

    response = api.schedule_order(
        UNKNOWN_ID,
        schedule_order_payload(
            "11111111-1111-4111-8111-111111111111", inspector["version"],
            scheduled_start_at="2026-08-10T09:00:00Z",
            scheduled_end_at="2026-08-10T11:00:00Z",
        ),
        BOARD_ADMIN,
    )

    error = validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.ERR_INSPECTOR_NOT_FOUND.value


def test_cancelling_a_scheduled_order_releases_the_inspector_window(api):
    """PRD §3.5: "Withdrawal voids every lot recorded under the order, moving each to lot
    status `VOIDED`, and where the order had already been assigned it also releases the
    officer — `inspector_id`, `scheduled_start_at` and `scheduled_end_at` are cleared and
    the freed inspector's `version` increments by one."
    PRD §3.1: "The roster read exposes `active_assignment_count`, the number of orders
    currently held by that inspector whose scheduling dimension reads `SCHEDULED` or
    `IN_FIELD`, and the roster listing may be narrowed by `home_territory_id` or by
    commission `status`."

    Design: Corner/state_machines/corner_cancel_order_voids_lots_and_releases_inspector_window
    """
    owner = enrol_owner("Cancel Ranch", contact_email="cancel@example.test")
    territory = open_district("T-CANC")
    inspector = commission_inspector(territory["id"])
    order = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    scheduled = validate_success(
        api.schedule_order(
            order["id"],
            schedule_order_payload(
                inspector["id"], inspector["version"],
                scheduled_start_at="2026-08-10T09:00:00Z",
                scheduled_end_at="2026-08-10T11:00:00Z",
            ),
            BOARD_ADMIN,
        ),
        200,
    )
    assert scheduled["schedule_status"] == "SCHEDULED"
    before = read_inspector(inspector["id"])
    assert before["active_assignment_count"] == 1 and before["version"] == 2

    cancelled = validate_success(
        api.cancel_order(order["id"], make_livestock_owner_headers(owner["id"])), 200
    )

    assert cancelled["schedule_status"] == "CANCELLED"
    assert cancelled["inspector_id"] is None
    assert cancelled["scheduled_start_at"] is None
    assert cancelled["scheduled_end_at"] is None
    assert cancelled["fee_status"] == "UNASSESSED"

    after = read_inspector(inspector["id"])
    assert after["active_assignment_count"] == 0
    assert after["version"] == 3


def test_inspector_cannot_open_another_inspectors_order(api):
    """PRD §3.5: "The assigned inspector opens the work by moving the order
    `SCHEDULED → IN_FIELD`; only the inspector named in `inspector_id` may do so, and
    their commission must still read `ACTIVE` at that moment."
    PRD §2.1: "When `X-User-Role` is `FieldInspector`, `X-User-ID` is the `id` of the
    acting `Inspector` row; ownership checks on an inspection order compare the order's
    `inspector_id` to `X-User-ID`."
    PRD §2.1: "Ownership enforcement carries its own rejection code,
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403 Forbidden), and it guards exactly thirteen write
    operations."

    Design: Corner/rbac/corner_inspector_cannot_begin_another_inspectors_order
    """
    owner = enrol_owner("Wrong Inspector Ranch", contact_email="wrongi@example.test")
    territory = open_district("T-OWN")
    assigned = commission_inspector(territory["id"])
    bystander = commission_inspector(territory["id"])
    order = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    validate_success(
        api.schedule_order(
            order["id"],
            schedule_order_payload(
                assigned["id"], assigned["version"],
                scheduled_start_at="2026-08-10T09:00:00Z",
                scheduled_end_at="2026-08-10T11:00:00Z",
            ),
            BOARD_ADMIN,
        ),
        200,
    )

    response = api.begin_order(
        order["id"], make_field_inspector_headers(bystander["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    unchanged = read_order(order["id"])
    assert unchanged["schedule_status"] == "SCHEDULED"
    assert unchanged["inspector_id"] == assigned["id"]


def test_lot_cannot_be_recorded_before_the_order_is_in_the_field(api):
    """PRD §3.6: "In the field, the assigned inspector records each **lot** of head
    presented under the order, which is only permitted while the order reads `IN_FIELD`."
    PRD §2.8: "This rung yields `ERR_APPLICATION_INVALID_STATE`,
    `ERR_REGISTRATION_INVALID_STATE`, `ERR_CLAIM_INVALID_STATE`,
    `ERR_ORDER_NOT_SCHEDULABLE`, `ERR_ORDER_INVALID_STATE`, `ERR_FEE_INVALID_STATE`,
    `ERR_ESTRAY_INVALID_STATE`, `ERR_INVESTIGATION_INVALID_STATE` or
    `ERR_REMITTANCE_INVALID_STATE`, each at HTTP 409 Conflict."

    Design: Corner/entities/corner_animal_lot_cannot_be_recorded_before_order_is_in_field
    """
    owner = enrol_owner("Parent Rule Ranch", contact_email="parent@example.test")
    territory = open_district("T-PAR")
    inspector = commission_inspector(territory["id"])
    order = request_inspection(
        owner["id"], territory["id"], inspection_purpose="SALE",
        requested_window_start_at="2026-08-10T08:00:00Z",
        requested_window_end_at="2026-08-10T17:00:00Z",
    )
    validate_success(
        api.schedule_order(
            order["id"],
            schedule_order_payload(
                inspector["id"], inspector["version"],
                scheduled_start_at="2026-08-10T09:00:00Z",
                scheduled_end_at="2026-08-10T11:00:00Z",
            ),
            BOARD_ADMIN,
        ),
        200,
    )

    response = api.create_lot(
        order["id"], create_lot_payload(5), make_field_inspector_headers(inspector["id"])
    )

    validate_error(response, ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)
    assert read_order(order["id"])["schedule_status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api.list_animal_lots(BOARD_ADMIN, params={"inspection_order_id": order["id"]})
    )
    assert meta["total_count"] == 0
