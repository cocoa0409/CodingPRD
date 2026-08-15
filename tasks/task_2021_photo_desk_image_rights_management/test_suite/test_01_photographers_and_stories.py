"""Photographer roster, story requests, and the sourcing decision (PRD §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    commission_assignment,
    commission_decision_payload,
    create_active_license,
    create_photographer,
    create_photographer_payload,
    create_story,
    get_story_fresh,
    ingest_cleared_wire_image,
    make_photographer_headers,
    record_usage_run,
    submit_assignment_image,
    submit_assignment,
    validate_error,
    validate_success,
    assert_photographer,
    assert_story_request,
    wire_stock_decision_payload,
)


def test_photographer_creation_applies_defaults(api, photo_editor_headers):
    """PRD §3.1: "`rights_reversion_months` is optional and defaults to 24 calendar
    months." PRD §3.1: "Both start at zero." PRD §3.1: "A photographer's `status`
    begins at `ACTIVE`."

    Design: Corner/entities/photographer_creation_applies_defaults
    """
    resp = api.create_photographer(create_photographer_payload(), photo_editor_headers)
    data = validate_success(resp, 201)
    assert_photographer(data)
    assert data["rights_reversion_months"] == 24, "omitted rights_reversion_months must default to 24"
    assert data["status"] == "ACTIVE"
    assert data["accrued_earnings_cents"] == 0
    assert data["paid_out_cents"] == 0


def test_story_second_decide_rejected(api, photo_editor_headers):
    """PRD §3.2: "Calling the decision on a request no longer `OPEN` is rejected
    with `ERR_STORY_ALREADY_DECIDED`."

    Design: Corner/validations/story_second_decide_rejected
    """
    photographer = create_photographer()
    story = create_story()
    decided, _ = commission_assignment(photographer["id"], story_id=story["id"])
    assert decided["status"] == "DECIDED"

    image = ingest_cleared_wire_image()
    resp = api.decide_story_request(
        story["id"], wire_stock_decision_payload(image["id"]), photo_editor_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STORY_ALREADY_DECIDED)


def test_suspended_photographer_cannot_be_commissioned(api, photo_editor_headers):
    """PRD §3.1: "A `SUSPENDED` photographer cannot be commissioned: a sourcing
    decision naming a suspended photographer is rejected with
    `ERR_PHOTOGRAPHER_SUSPENDED`." PRD §3.1: "A `PhotoEditor` may suspend a
    photographer — moving `ACTIVE` to `SUSPENDED` — and later reactivate them
    back to `ACTIVE`."

    Design: Corner/validations/suspended_photographer_cannot_be_commissioned
    """
    photographer = create_photographer()
    suspended = validate_success(
        api.suspend_photographer(photographer["id"], photo_editor_headers), 200,
    )
    assert suspended["status"] == "SUSPENDED"

    story = create_story()
    resp = api.decide_story_request(
        story["id"], commission_decision_payload(photographer["id"]), photo_editor_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PHOTOGRAPHER_SUSPENDED)

    reactivated = validate_success(
        api.reactivate_photographer(photographer["id"], photo_editor_headers), 200,
    )
    assert reactivated["status"] == "ACTIVE"
    decided = validate_success(
        api.decide_story_request(
            story["id"], commission_decision_payload(photographer["id"]), photo_editor_headers,
        ),
        200,
    )
    assert decided["status"] == "DECIDED"


def test_story_fulfilled_by_matching_usage_run(api, photo_editor_headers):
    """PRD §3.2: "A story request reaches `FULFILLED` automatically: when a usage
    run is recorded under a license whose `story_request_id` is this request, the
    system moves the request from `DECIDED` to `FULFILLED` without any explicit
    editor action."

    Design: Corner/state_machines/story_fulfilled_by_matching_usage_run
    """
    image = ingest_cleared_wire_image()
    story = create_story(headline="Flood aftermath", slug="flood-aftermath")
    decided = validate_success(
        api.decide_story_request(
            story["id"], wire_stock_decision_payload(image["id"]), photo_editor_headers,
        ),
        200,
    )
    assert_story_request(decided)
    assert decided["status"] == "DECIDED"
    assert decided["sourced_image_id"] == image["id"]

    lic = create_active_license(image["id"], story_request_id=story["id"])
    record_usage_run(image["id"], lic["id"], headers=photo_editor_headers,
                     story_slug="flood-aftermath", published_at="2026-08-03T12:00:00Z")

    after = get_story_fresh(story["id"])
    assert after["status"] == "FULFILLED", (
        f"story must auto-transition to FULFILLED on the matching usage run, got {after['status']}"
    )


def test_commission_on_trailing_buffer_day_rejected(api, photo_editor_headers):
    """PRD §3.2: "The desk also enforces a travel-buffer double-booking rule: the
    commissioned shoot window padded by one calendar day on each side — the closed
    interval from the day before `shoot_start` through the day after `shoot_end` —
    must not intersect the similarly padded window of any other assignment of the
    same photographer in `COMMISSIONED`, `IN_PROGRESS`, `SUBMITTED`, or
    `REVISION_REQUESTED` status; touching the buffer day counts as a conflict and
    is rejected with `ERR_PHOTOGRAPHER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/photographer_double_booking_buffer_closed
    """
    photographer = create_photographer()
    story1 = create_story(slug="bridge-fire")
    commission_assignment(
        photographer["id"], story_id=story1["id"],
        shoot_start="2026-08-10T09:00:00Z", shoot_end="2026-08-12T17:00:00Z",
    )
    # Existing buffered window: [2026-08-09, 2026-08-13] closed. A shoot starting
    # on the trailing buffer day 2026-08-13 touches it -> conflict.
    story2 = create_story(slug="court-verdict")
    resp = api.decide_story_request(
        story2["id"],
        commission_decision_payload(
            photographer["id"],
            shoot_start="2026-08-13T09:00:00Z", shoot_end="2026-08-13T17:00:00Z",
        ),
        photo_editor_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PHOTOGRAPHER_DOUBLE_BOOKED)


def test_commission_on_leading_buffer_day_rejected_and_clear_day_allowed(api, photo_editor_headers):
    """PRD §3.2: "The desk also enforces a travel-buffer double-booking rule: the
    commissioned shoot window padded by one calendar day on each side — the closed
    interval from the day before `shoot_start` through the day after `shoot_end` —
    must not intersect the similarly padded window of any other assignment of the
    same photographer in `COMMISSIONED`, `IN_PROGRESS`, `SUBMITTED`, or
    `REVISION_REQUESTED` status; touching the buffer day counts as a conflict and
    is rejected with `ERR_PHOTOGRAPHER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/photographer_double_booking_buffer_closed
    """
    photographer = create_photographer()
    story1 = create_story(slug="bridge-fire")
    commission_assignment(
        photographer["id"], story_id=story1["id"],
        shoot_start="2026-08-10T09:00:00Z", shoot_end="2026-08-12T17:00:00Z",
    )
    # Leading buffer day 2026-08-09 is inside the padded window -> conflict.
    story2 = create_story(slug="court-verdict")
    resp = api.decide_story_request(
        story2["id"],
        commission_decision_payload(
            photographer["id"],
            shoot_start="2026-08-09T09:00:00Z", shoot_end="2026-08-09T17:00:00Z",
        ),
        photo_editor_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PHOTOGRAPHER_DOUBLE_BOOKED)

    # 2026-08-15 leaves a gap beyond the padded window under any reading -> allowed.
    story3 = create_story(slug="harbor-festival")
    decided = validate_success(
        api.decide_story_request(
            story3["id"],
            commission_decision_payload(
                photographer["id"],
                shoot_start="2026-08-15T09:00:00Z", shoot_end="2026-08-15T17:00:00Z",
            ),
            photo_editor_headers,
        ),
        200,
    )
    assert decided["status"] == "DECIDED"
