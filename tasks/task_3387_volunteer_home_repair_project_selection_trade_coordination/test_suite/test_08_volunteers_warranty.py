"""Volunteer eligibility, warranty windows and reserves, material staging, and
assessment completion stamping (PRD §3.3/§3.6/§3.8/§3.9)."""

from test_helpers import (
    ApiErrorId,
    ANON,
    api_client,
    approve_warranty_claim,
    complete_assessment,
    create_assessment,
    create_cycle,
    create_eligible_volunteer,
    create_enrollment_payload,
    create_material_order,
    create_published_event,
    create_volunteer_payload,
    create_warranty_claim,
    create_warranty_claim_payload,
    create_verified_application,
    enroll_volunteer,
    get_cycle,
    get_enrollment,
    get_event,
    get_material_order,
    get_project,
    get_volunteer,
    list_scope_items_for_assessment,
    make_homeowner_headers,
    make_volunteer_headers,
    material_line_payload,
    reset_clock,
    resolve_warranty_claim,
    scope_item_payload,
    set_clock,
    setup_selected_project,
    setup_warranty_active_project,
    validate_created,
    validate_error,
    validate_ok,
    STAFF,
)


def test_volunteer_deactivation_withdraws_open_enrollments():
    """PRD §3.6: "Staff may deactivate a volunteer (`REGISTERED` →
    `DEACTIVATED`), which withdraws that volunteer's `ENROLLED` or `CONFIRMED`
    enrollments on events in `PUBLISHED` or `LOCKED`; reinstatement flips the
    volunteer back to `REGISTERED`."
    PRD §3.6: "A volunteer's derived `is_eligible` is the conjunction of four
    facts: the volunteer is `REGISTERED`, a `waiver_signed_on` date is present,
    a `safety_training_completed_on` date is present, and the training date
    plus 365 days is on or after the logical clock date — training completed
    exactly 365 days ago still qualifies."

    Deactivation withdraws only that volunteer's open enrollment; the other
    enrollment and the event's open_slots reflect it immediately, and the
    deactivated volunteer is ineligible despite valid waiver and training.

    Design: Corner/state_machines/volunteer_deactivation_withdraws_open_enrollments
    """
    ctx = setup_selected_project()
    event = create_published_event(
        ctx["project"]["id"], name="Deact Day", event_date="2026-10-10",
        max_volunteers=3,
    )
    staying = create_eligible_volunteer(full_name="Stay Vol")
    leaving = create_eligible_volunteer(full_name="Leave Vol")
    enr1 = enroll_volunteer(event["id"], staying["id"])
    enr2 = enroll_volunteer(event["id"], leaving["id"])
    validate_ok(
        api_client.patch_volunteer(
            leaving["id"], {"status": "DEACTIVATED"}, STAFF
        )
    )
    assert get_enrollment(enr2["id"])["status"] == "WITHDRAWN", (
        "cascade from deactivation"
    )
    assert get_enrollment(enr1["id"])["status"] == "ENROLLED", "unaffected"
    assert get_event(event["id"])["open_slots"] == 2, (
        "one of three seats re-freed"
    )
    assert get_volunteer(leaving["id"])["is_eligible"] is False


def test_training_validity_365_day_inclusive_boundary():
    """PRD §3.6: "A volunteer's derived `is_eligible` is the conjunction of
    four facts: the volunteer is `REGISTERED`, a `waiver_signed_on` date is
    present, a `safety_training_completed_on` date is present, and the training
    date plus 365 days is on or after the logical clock date — training
    completed exactly 365 days ago still qualifies."

    At clock date 2026-09-01: training completed 2025-09-01 is exactly 365 days
    old and still qualifies; 2025-08-31 has lapsed by one day and enrollment
    fails.

    Design: Corner/validations/training_validity_365_day_inclusive_boundary
    """
    ctx = setup_selected_project()
    event = create_published_event(
        ctx["project"]["id"], name="Train Day", event_date="2026-10-10",
        max_volunteers=5,
    )
    v_old = create_eligible_volunteer(
        full_name="Old Train", trained_on="2025-08-31"
    )
    v_ok = create_eligible_volunteer(
        full_name="Ok Train", trained_on="2025-09-01"
    )
    assert get_volunteer(v_old["id"])["is_eligible"] is False, (
        "2025-08-31 + 365 days = 2026-08-31 < 2026-09-01"
    )
    assert get_volunteer(v_ok["id"])["is_eligible"] is True, (
        "2025-09-01 + 365 days = 2026-09-01 >= 2026-09-01, inclusive"
    )
    resp = api_client.create_enrollment(
        create_enrollment_payload(event["id"], v_old["id"]),
        make_volunteer_headers(v_old["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ELIGIBLE)
    enrolled = enroll_volunteer(event["id"], v_ok["id"])
    assert enrolled["status"] == "ENROLLED"


def test_volunteer_registration_applies_defaults():
    """PRD §3.6: "Volunteers self-register through an open call carrying
    `full_name`, `email`, an optional `skills` array drawn from the trade
    values `NONE`, `CARPENTRY`, `ELECTRICAL`, `PLUMBING`, `ROOFING`, and `HVAC`
    (defaulting to an empty array), and an optional `team_leader_eligible` flag
    (defaulting to false)."
    PRD §3.6: "A new volunteer is `REGISTERED` with `waiver_signed_on` and
    `safety_training_completed_on` both null."

    Registration with only name and email yields the documented defaults, and
    is_eligible is false with no waiver and no training on file.

    Design: Corner/entities/volunteer_registration_applies_defaults
    """
    resp = api_client.create_volunteer(
        create_volunteer_payload(full_name="Bare Vol", email="bare@x.example"),
        ANON,
    )
    data = validate_created(resp)
    assert data["skills"] == []
    assert data["team_leader_eligible"] is False
    assert data["status"] == "REGISTERED"
    assert data["waiver_signed_on"] is None
    assert data["safety_training_completed_on"] is None
    assert data["is_eligible"] is False


def test_warranty_claim_on_anniversary_accepted():
    """PRD §3.9: "Completion stamps `completed_on` from the logical clock, sets
    `warranty_valid_until` to twelve calendar months after `completed_on`
    inclusive, releases the remaining reserve back to the cycle — the cycle's
    `reserved_cents` drops by the project's `reserved_balance_cents`, which
    itself goes to zero — moves the application `SELECTED` → `FULFILLED`, and
    finalizes `reconciled_cost_cents`."
    PRD §3.9: "The project must be `WARRANTY_ACTIVE` (`ERR_PROJECT_NOT_COMPLETED`),
    and the claim must arrive while the logical clock date is on or before
    `warranty_valid_until`: a claim filed exactly on the anniversary date is
    valid, and a later one is `ERR_WARRANTY_EXPIRED`."

    Completed 2026-10-10 -> warranty_valid_until 2027-10-10; a claim filed on
    the anniversary date is accepted and stamped from the logical clock.

    Design: Difficulty/boundary_precision_check/warranty_claim_on_anniversary_accepted_day_after_expired
    """
    ctx = setup_warranty_active_project()
    project = ctx["project"]
    assert project["status"] == "WARRANTY_ACTIVE"
    assert str(project["warranty_valid_until"]).startswith("2027-10-10"), (
        "completed_on 2026-10-10 + 12 calendar months"
    )
    set_clock("2027-10-10T09:00:00Z")
    claim = create_warranty_claim(
        project["id"],
        ctx["application"]["id"],
        claim_amount_cents=5_000,
        description="ramp bolt loose",
    )
    assert claim["status"] == "SUBMITTED"
    assert str(claim["submitted_on"]).startswith("2027-10-10"), (
        "the anniversary date is INCLUSIVE"
    )


def test_warranty_claim_day_after_anniversary_expired():
    """PRD §3.9: "The project must be `WARRANTY_ACTIVE` (`ERR_PROJECT_NOT_COMPLETED`),
    and the claim must arrive while the logical clock date is on or before
    `warranty_valid_until`: a claim filed exactly on the anniversary date is
    valid, and a later one is `ERR_WARRANTY_EXPIRED`."

    One day after the anniversary the window is shut, while the project is
    still WARRANTY_ACTIVE (closure is a separate staff action).

    Design: Difficulty/boundary_precision_check/warranty_claim_on_anniversary_accepted_day_after_expired
    """
    ctx = setup_warranty_active_project()
    project = ctx["project"]
    set_clock("2027-10-11T09:00:00Z")
    resp = api_client.create_warranty_claim(
        create_warranty_claim_payload(
            project["id"], description="second issue", claim_amount_cents=6_000
        ),
        make_homeowner_headers(ctx["application"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)
    assert get_project(project["id"])["status"] == "WARRANTY_ACTIVE"


def test_warranty_reserve_cap_and_remaining_accounting():
    """PRD §3.9: "The reserve is the lesser of two figures — eight percent of
    the project's `reconciled_cost_cents`, rounded half up, and a hard cap of
    250,000 cents — and the remaining reserve is that figure minus the
    `payout_cents` of the project's claims already in `APPROVED` or
    `RESOLVED`; a payout exactly equal to the remaining reserve succeeds."
    PRD §3.9: "An approved claim is later resolved (`APPROVED` → `RESOLVED`)
    with an optional `resolution_note`, and resolution raises the cycle's
    `spent_cents` by `payout_cents`."

    Reconciled cost 100000 pins the reserve at 8000: a payout equal to the
    full remaining reserve succeeds (inclusive boundary), the next approval
    against the exhausted reserve fails, and RESOLVED moves exactly the payout
    into spent.

    Design: Corner/calculations/warranty_reserve_cap_and_remaining_accounting
    """
    ctx = setup_warranty_active_project()
    project_id = ctx["project"]["id"]
    app_id = ctx["application"]["id"]
    claim1 = create_warranty_claim(
        project_id, app_id, claim_amount_cents=9_000, description="paint peeling"
    )
    approved = approve_warranty_claim(claim1["id"], 8_000)
    assert approved["status"] == "APPROVED", (
        "8000 == the full 8% reserve of reconciled 100000; boundary inclusive"
    )
    claim2 = create_warranty_claim(
        project_id, app_id, claim_amount_cents=4_000, description="second defect"
    )
    resp = api_client.patch_warranty_claim(
        claim2["id"], {"status": "APPROVED", "payout_cents": 4_000}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_CAP_EXCEEDED)
    resolved = resolve_warranty_claim(claim1["id"], resolution_note="repainted")
    assert resolved["status"] == "RESOLVED"
    assert get_cycle(ctx["cycle"]["id"])["spent_cents"] == 8_000, (
        "only resolved payouts hit the ledger"
    )


def test_material_order_skip_stage_returns_invalid_state():
    """PRD §3.8: "Staff then stage the order (`ORDERED` → `STAGED`) and record
    delivery (`STAGED` → `DELIVERED`); delivery raises the cycle's
    `spent_cents` by `total_cents` and recomputes posture, which may fire the
    automatic `PLANNING` → `READY` promotion."

    ORDERED -> DELIVERED skipping STAGED is rejected; the staging step is a
    real vertex, not a formality.

    Design: Corner/endpoints/material_order_skip_stage_returns_invalid_state
    """
    ctx = setup_selected_project()
    order = create_material_order(
        ctx["project"]["id"],
        lines=[
            material_line_payload(
                item_name="paint kit", quantity=2, unit_price_dollars=25.00
            )
        ],
    )
    assert order["total_cents"] == 5_175, (
        "subtotal 5000 + round_half_up(175.00) = 175"
    )
    resp = api_client.patch_material_order(
        order["id"], {"status": "DELIVERED"}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_material_order(order["id"])["status"] == "ORDERED"


def test_warranty_claim_before_completion_returns_project_not_completed():
    """PRD §3.9: "The project must be `WARRANTY_ACTIVE`
    (`ERR_PROJECT_NOT_COMPLETED`), and the claim must arrive while the logical
    clock date is on or before `warranty_valid_until`: a claim filed exactly on
    the anniversary date is valid, and a later one is `ERR_WARRANTY_EXPIRED`."

    The warranty surface is unreachable while the project is still PLANNING,
    even from the rightful homeowner.

    Design: Corner/endpoints/warranty_claim_before_completion_returns_project_not_completed
    """
    ctx = setup_selected_project()
    resp = api_client.create_warranty_claim(
        create_warranty_claim_payload(
            ctx["project"]["id"], description="too early", claim_amount_cents=1_000
        ),
        make_homeowner_headers(ctx["application"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_COMPLETED)


def test_assessment_complete_stamps_completed_on_from_clock():
    """PRD §3.3: "Completion creates every scope item in status `INCLUDED`,
    with each item's `midpoint_cents` computed as the sum of `est_low_cents`
    and `est_high_cents` halved and rounded half up to the cent, and stamps
    `completed_on` from the logical clock; the assessment is then `COMPLETED`."

    With the clock pinned at 2026-09-01 the completion stamp reads 2026-09-01
    (never the 2026-09-02 scheduled date), and the 100000..200001 item's
    midpoint is round_half_up(150000.5) = 150001.

    Design: Corner/entities/assessment_complete_stamps_completed_on_from_clock
    """
    reset_clock()
    cycle = create_cycle()
    app = create_verified_application(cycle["id"], homeowner_name="Stamp Site")
    asm = create_assessment(app["id"], scheduled_on="2026-09-02")
    completed = complete_assessment(
        asm["id"],
        scope_items=[
            scope_item_payload(
                category="SAFETY",
                est_low_cents=100_000,
                est_high_cents=200_001,
                description="rail",
            )
        ],
        safety_hazard_max_severity=2,
        accessibility_needs_count=1,
    )
    assert completed["status"] == "COMPLETED"
    assert str(completed["completed_on"]).startswith("2026-09-01"), (
        "stamped from the logical clock, not the scheduled date"
    )
    items = list_scope_items_for_assessment(asm["id"])
    assert items[0]["midpoint_cents"] == 150_001, (
        "round_half_up((100000 + 200001) / 2) rounds up"
    )
