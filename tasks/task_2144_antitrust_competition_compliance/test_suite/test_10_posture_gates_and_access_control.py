"""Posture as a programme-wide gate: the freeze cascade, the ladder order that
decides which refusal surfaces, and the identity checks that guard every write.
"""
from test_helpers import (
    ADMIN, COUNSEL, ApiErrorId, adjust_exposure, book_attendance,
    contact_escalation_payload, create_approved_association,
    create_attendance_payload, create_business_unit_payload,
    create_contact_payload, create_participation_payload, create_trained_employee,
    log_contact, make_business_lead_headers, make_counsel_headers,
    make_employee_headers, open_contact_review, propose_association,
    read_attendance, read_business_unit, read_contact, read_employee,
    read_participation, register_business_unit, register_employee,
    revoke_clearance, schedule_meeting, set_clock, setup_active_participation,
    validate_error, validate_paginated, validate_success,
)

COATINGS_UNIT = {
    "name": "Industrial Coatings EMEA",
    "market_code": "EU-COAT",
    "exposure_budget_points": 200,
}

HEAVY_PRICING_CONTACT = {
    "competitor_name": "Novamer GmbH",
    "contact_channel": "IN_PERSON_UNSTRUCTURED",
    "topic_tags": ["CUSTOMER_ALLOCATION", "BID"],
    "pricing_topic": True,
    "occurred_at": "2026-07-28T15:30:00Z",
}


def _restricted_unit_with_live_booking():
    """An ACTIVE participation, one future booking, and a ledger at 65.00."""
    bundle = setup_active_participation(bu_overrides=dict(COATINGS_UNIT),
                                        role_category="PRICING")
    meeting = schedule_meeting(bundle["association"]["id"],
                               scheduled_start="2026-09-10T09:00:00Z",
                               scheduled_end="2026-09-10T11:00:00Z",
                               agenda_received=True)
    bundle["attendance"] = book_attendance(
        meeting["id"], bundle["participation"]["id"], bundle["unit"]["id"])
    adjust_exposure(bundle["unit"]["id"], 45,
                    "Carry-over findings from the 2025 EC sector inquiry")
    contact = log_contact(bundle["unit"]["id"], bundle["employee"]["id"],
                          **HEAVY_PRICING_CONTACT)
    open_contact_review(contact["id"], counsel_id="counsel-2")
    bundle["contact"] = contact
    return bundle


def test_escalation_doubles_the_charge_and_drives_the_ledger_into_frozen(api):
    """PRD §3.6: "Escalating, which takes a `reason`, moves `UNDER_REVIEW →
    ESCALATED` and does the reverse. The surcharge is the contact's current
    `exposure_points_charged` multiplied by one less than the escalation
    multiplier of 2.0 — in other words, an amount equal to the existing charge,
    rounded half up to 2 decimal places — added to `exposure_points_charged` so
    the charge is doubled, and added to the unit's ledger, with the unit's
    `version` incrementing by 1."
    PRD §2.8: "The posture is `FROZEN` when `exposure_points` is at least 80.00,
    **or** when the unit has any leniency application whose `marker_status` is
    `MARKER_REQUESTED`, `MARKER_GRANTED` or `PERFECTED`."

    Design: Difficulty/transitive_cascade/escalation_freeze_suspend_cancel_four_hop_chain
    """
    set_clock()
    bundle = _restricted_unit_with_live_booking()
    assert read_business_unit(bundle["unit"]["id"])["posture"] == "RESTRICTED"

    data = validate_success(api.escalate_contact(
        bundle["contact"]["id"],
        contact_escalation_payload(
            "Delegate confirmed forward list prices were discussed"),
        make_counsel_headers("counsel-2")))

    assert data["status"] == "ESCALATED"
    assert data["exposure_points_charged"] == 40.00
    stored_unit = read_business_unit(bundle["unit"]["id"])
    assert stored_unit["exposure_points"] == 85.00
    assert stored_unit["manual_exposure_adjustment_points"] == 45.00
    assert stored_unit["posture"] == "FROZEN"


def test_freeze_suspends_the_participation_and_cancels_its_future_booking(api):
    """PRD §2.8: "Then, in the first cascade hop, every participation of that
    unit whose status is `PARTIALLY_APPROVED` or `ACTIVE` moves to `SUSPENDED`,
    processed in `created_at` ascending order. Suspension does **not** release
    the participation's reserved review minutes — the reservation is held
    through the freeze."
    PRD §2.8: "Then, in the second hop, each newly suspended participation
    cancels every one of its attendances that is still `PLANNED` and whose
    meeting begins strictly after the current logical clock, processed in
    meeting start ascending order and then `created_at` ascending order; each
    cancellation records the cascade origin as its `cancellation_reason` and
    releases the delegate's occupancy interval."

    Design: Difficulty/transitive_cascade/escalation_freeze_suspend_cancel_four_hop_chain
    """
    set_clock()
    bundle = _restricted_unit_with_live_booking()

    validate_success(api.escalate_contact(
        bundle["contact"]["id"],
        contact_escalation_payload(
            "Delegate confirmed forward list prices were discussed"),
        make_counsel_headers("counsel-2")))

    participation = read_participation(bundle["participation"]["id"])
    assert participation["status"] == "SUSPENDED"
    assert participation["review_minutes_reserved"] == 30, (
        "the reservation is held through the freeze")
    assert read_business_unit(bundle["unit"]["id"])["review_minutes_consumed"] == 30
    assert read_attendance(bundle["attendance"]["id"])["status"] == "CANCELLED"


def test_frozen_posture_outranks_the_exposure_budget_on_a_contact_log(api):
    """PRD §2.7: "**Frozen posture.** The governing business unit's `posture` is
    not `FROZEN` — otherwise `ERR_BUSINESS_UNIT_FROZEN`, HTTP 409. Applies to
    eight writes: competitor-contact logging, participation nomination,
    participation submission, legal clearance, business justification,
    participation reinstatement, meeting-attendance booking, and transaction
    registration."
    PRD §2.7: "**Exposure budget.** The unit's `exposure_points` plus the points
    this contact would be charged is no greater than the unit's
    `exposure_budget_points` — otherwise `ERR_EXPOSURE_BUDGET_EXCEEDED`, HTTP
    422."
    PRD §2.7: "Requests are validated against a single, strictly ordered ladder.
    Rules are evaluated in ascending priority order, the **first** failing rule
    determines the response, later failures are never reported, and no side
    effect of any kind — not a cascade, not a counter increment, not a `version`
    bump — is applied when any rule fails."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_exposure_budget_on_contact_log
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=60)
    employee = register_employee(unit["id"], role_category="LEGAL")
    adjust_exposure(unit["id"], 85,
                    "Regulator dawn raid at a sister unit; interim exposure loading")
    assert read_business_unit(unit["id"])["posture"] == "FROZEN"

    resp = api.create_contact(
        create_contact_payload(unit["id"], employee["id"],
                               contact_channel="WRITTEN_FORMAL",
                               topic_tags=["STANDARDS"]),
        make_employee_headers(employee["id"]))

    validate_error(resp, ApiErrorId.ERR_BUSINESS_UNIT_FROZEN.value)
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] != "ERR_EXPOSURE_BUDGET_EXCEEDED"


def test_frozen_refusal_applies_no_side_effect_of_any_kind(api):
    """PRD §2.7: "Requests are validated against a single, strictly ordered
    ladder. Rules are evaluated in ascending priority order, the **first**
    failing rule determines the response, later failures are never reported, and
    no side effect of any kind — not a cascade, not a counter increment, not a
    `version` bump — is applied when any rule fails."
    PRD §2.8: "`FROZEN` refuses all eight of the posture-gated writes listed at
    rung 11 of the validation ladder with `ERR_BUSINESS_UNIT_FROZEN`, and it
    also cascades."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_outranks_exposure_budget_on_contact_log
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=60)
    employee = register_employee(unit["id"], role_category="LEGAL")
    adjust_exposure(unit["id"], 85,
                    "Regulator dawn raid at a sister unit; interim exposure loading")

    api.create_contact(
        create_contact_payload(unit["id"], employee["id"],
                               contact_channel="WRITTEN_FORMAL",
                               topic_tags=["STANDARDS"]),
        make_employee_headers(employee["id"]))

    stored_unit = read_business_unit(unit["id"])
    assert stored_unit["exposure_points"] == 85.00, "the ledger is untouched"
    _rows, meta = validate_paginated(api.list_contacts(
        COUNSEL, params={"business_unit_id": unit["id"]}))
    assert meta["total_count"] == 0, "nothing is written"


def test_training_gate_outranks_the_association_approval_gate(api):
    """PRD §2.7: "**Training currency.** The acting or nominated employee's
    `training_status` is `CURRENT` — otherwise `ERR_TRAINING_NOT_CURRENT`, HTTP
    422. This rule is **conditional**: it is skipped entirely when the
    employee's `role_category` is neither `SALES` nor `PRICING`. It guards four
    writes: competitor-contact logging, participation nomination, participation
    submission, and clearance grant."
    PRD §2.7: "**Association approval.** The trade association's `status` is
    `APPROVED` — otherwise `ERR_ASSOCIATION_NOT_APPROVED`, HTTP 422. Guards
    three writes: participation nomination, participation submission, and
    meeting scheduling."

    Design: Difficulty/priority_pair_validation_conflict/training_not_current_outranks_association_not_approved_on_nomination
    """
    set_clock()
    unit = register_business_unit(name="Industrial Adhesives EMEA",
                                  market_code="EU-ADHES")
    employee = register_employee(unit["id"], role_category="SALES")
    association = propose_association(name="Benelux Adhesives Forum",
                                      approval_tier="TIER_2_MEDIUM",
                                      competitor_density_pct=25)
    assert association["status"] == "PROPOSED"

    resp = api.create_participation(
        create_participation_payload(unit["id"], association["id"], employee["id"],
                                     "Technical committee delegate"),
        make_business_lead_headers(unit["id"]))

    validate_error(resp, ApiErrorId.ERR_TRAINING_NOT_CURRENT.value)
    assert resp.status_code == 422
    assert resp.json()["data"]["error_id"] != "ERR_ASSOCIATION_NOT_APPROVED"
    assert read_employee(employee["id"])["training_status"] == "NONE"


def test_nomination_refused_at_the_training_gate_writes_no_participation(api):
    """PRD §2.7: "Rules are evaluated in ascending priority order, the
    **first** failing rule determines the response, later failures are never
    reported, and no side effect of any kind — not a cascade, not a counter
    increment, not a `version` bump — is applied when any rule fails."
    PRD §3.2: "Their `training_status` reads `EXPIRED`, and until a fresh
    completion lands they cannot log a competitor contact, cannot be nominated
    to a trade association, cannot be pushed into the approval fork, and cannot
    be granted speaking clearance — all four rejected with
    `ERR_TRAINING_NOT_CURRENT`."

    Design: Difficulty/priority_pair_validation_conflict/training_not_current_outranks_association_not_approved_on_nomination
    """
    set_clock()
    unit = register_business_unit(name="Industrial Adhesives EMEA",
                                  market_code="EU-ADHES")
    employee = register_employee(unit["id"], role_category="SALES")
    association = propose_association(name="Benelux Adhesives Forum",
                                      approval_tier="TIER_2_MEDIUM",
                                      competitor_density_pct=25)

    api.create_participation(
        create_participation_payload(unit["id"], association["id"], employee["id"],
                                     "Technical committee delegate"),
        make_business_lead_headers(unit["id"]))

    _rows, meta = validate_paginated(api.list_participations(
        COUNSEL, params={"business_unit_id": unit["id"]}))
    assert meta["total_count"] == 0


def test_delegate_clearance_gate_outranks_the_occupancy_conflict(api):
    """PRD §2.7: "**Delegate clearance.** The nominated delegate's
    `clearance_status` is `GRANTED` — otherwise `ERR_CLEARANCE_NOT_GRANTED`,
    HTTP 422. Applies to attendance booking."
    PRD §2.7: "**Delegate occupancy.** The delegate's closed occupancy interval
    does not intersect any of their other occupying attendances — otherwise
    `ERR_ATTENDEE_WINDOW_CONFLICT`, HTTP 409. Applies to attendance booking."
    PRD §3.1: "Revocation deliberately does **not** cancel existing planned
    attendances: a revocation is a personnel record, and the delegate's calendar
    bookings stay on the books — and keep occupying their intervals — until the
    business lead cancels them explicitly."

    Design: Difficulty/priority_pair_validation_conflict/clearance_not_granted_outranks_attendee_window_conflict
    """
    set_clock()
    bundle = setup_active_participation(bu_overrides=dict(COATINGS_UNIT))
    unit_id, part_id = bundle["unit"]["id"], bundle["participation"]["id"]
    meeting_1 = schedule_meeting(bundle["association"]["id"],
                                 scheduled_start="2026-09-10T09:00:00Z",
                                 scheduled_end="2026-09-10T11:00:00Z",
                                 agenda_received=True)
    book_attendance(meeting_1["id"], part_id, unit_id)
    meeting_2 = schedule_meeting(bundle["association"]["id"],
                                 scheduled_start="2026-09-10T12:00:00Z",
                                 scheduled_end="2026-09-10T13:00:00Z",
                                 meeting_type="BOARD", agenda_received=True)
    revoke_clearance(bundle["employee"]["id"])

    resp = api.create_attendance(
        create_attendance_payload(meeting_2["id"], part_id),
        make_business_lead_headers(unit_id))

    validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_GRANTED.value)
    assert resp.status_code == 422
    assert resp.json()["data"]["error_id"] != "ERR_ATTENDEE_WINDOW_CONFLICT"
    assert read_employee(bundle["employee"]["id"])["clearance_status"] == "REVOKED"


def test_booking_refused_at_the_clearance_gate_leaves_the_calendar_intact(api):
    """PRD §3.1: "A revocation, which takes a `reason`, is legal from `NONE`,
    `GRANTED` and `SUSPENDED`, and drives `clearance_status` to the terminal
    `REVOKED`."
    PRD §3.1: "Revocation deliberately does **not** cancel existing planned
    attendances: a revocation is a personnel record, and the delegate's calendar
    bookings stay on the books — and keep occupying their intervals — until the
    business lead cancels them explicitly."

    Design: Difficulty/priority_pair_validation_conflict/clearance_not_granted_outranks_attendee_window_conflict
    """
    set_clock()
    bundle = setup_active_participation(bu_overrides=dict(COATINGS_UNIT))
    unit_id, part_id = bundle["unit"]["id"], bundle["participation"]["id"]
    meeting_1 = schedule_meeting(bundle["association"]["id"],
                                 scheduled_start="2026-09-10T09:00:00Z",
                                 scheduled_end="2026-09-10T11:00:00Z",
                                 agenda_received=True)
    attendance_1 = book_attendance(meeting_1["id"], part_id, unit_id)
    meeting_2 = schedule_meeting(bundle["association"]["id"],
                                 scheduled_start="2026-09-10T12:00:00Z",
                                 scheduled_end="2026-09-10T13:00:00Z",
                                 meeting_type="BOARD", agenda_received=True)
    revoke_clearance(bundle["employee"]["id"])

    api.create_attendance(create_attendance_payload(meeting_2["id"], part_id),
                          make_business_lead_headers(unit_id))

    assert read_attendance(attendance_1["id"])["status"] == "PLANNED"
    _rows, meta = validate_paginated(api.list_attendances(
        COUNSEL, params={"meeting_id": meeting_2["id"]}))
    assert meta["total_count"] == 0


def test_restricted_posture_blocks_nominations_but_never_self_reporting(api):
    """PRD §2.8: "`RESTRICTED` refuses new trade-association nominations for
    that unit with `ERR_BUSINESS_UNIT_RESTRICTED`, but deliberately still
    permits competitor-contact logging — self-reporting is never blocked,
    because a programme that punishes disclosure stops receiving it."
    PRD §2.8: "Both thresholds are inclusive at the lower edge: a ledger reading
    of exactly 40.00 is `RESTRICTED`, and exactly 80.00 is `FROZEN`."

    Design: Corner/cross_cutting_complexity_layers/restricted_posture_blocks_new_participations_but_not_contact_logging
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=200)
    employee = register_employee(unit["id"], role_category="LEGAL")
    association = create_approved_association(approval_tier="TIER_1_LOW",
                                              competitor_density_pct=0)
    adjust_exposure(unit["id"], 40, "Legacy register migration")
    stored_unit = read_business_unit(unit["id"])
    assert stored_unit["exposure_points"] == 40.00
    assert stored_unit["posture"] == "RESTRICTED"

    refused = api.create_participation(
        create_participation_payload(unit["id"], association["id"], employee["id"],
                                     "Standards drafting delegate"),
        make_business_lead_headers(unit["id"]))
    validate_error(refused, ApiErrorId.ERR_BUSINESS_UNIT_RESTRICTED.value)
    assert refused.status_code == 409

    logged = validate_success(api.create_contact(
        create_contact_payload(unit["id"], employee["id"]),
        make_employee_headers(employee["id"])), 201)
    assert logged["exposure_points_charged"] == 5.00

    after = read_business_unit(unit["id"])
    assert after["exposure_points"] == 45.00
    assert after["posture"] == "RESTRICTED"
    _rows, meta = validate_paginated(api.list_participations(
        COUNSEL, params={"business_unit_id": unit["id"]}))
    assert meta["total_count"] == 0


def test_employee_cannot_log_a_contact_for_a_colleague(api):
    """PRD §2.1: "When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of
    the acting employee record; ownership checks compare the resource's
    owning-employee field to `X-User-ID` — directly where the payload carries
    `employee_id`, and indirectly through a training assignment's employee, a
    participation's nominated delegate, or a contact's logging employee."
    PRD §2.1: "A properly authorised `BusinessLead` or `Employee` who reaches
    for a resource belonging to a different unit or a different person yields
    `ERR_NOT_RESOURCE_OWNER`, also HTTP 403."

    Design: Corner/rbac/employee_cannot_log_a_contact_on_behalf_of_another_employee
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=200)
    employee_a = register_employee(unit["id"], role_category="LEGAL")
    employee_b = register_employee(unit["id"], role_category="LEGAL")

    resp = api.create_contact(
        create_contact_payload(unit["id"], employee_b["id"]),
        make_employee_headers(employee_a["id"]))

    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert resp.status_code == 403

    _rows, meta = validate_paginated(api.list_contacts(
        COUNSEL, params={"business_unit_id": unit["id"]}))
    assert meta["total_count"] == 0
    assert read_business_unit(unit["id"])["exposure_points"] == 0.00


def test_request_without_identity_headers_is_unauthenticated_first(api):
    """PRD §2.1: "Every request, without exception, must carry two headers:
    `X-User-ID` and `X-User-Role`. If either header is absent, or if
    `X-User-Role` carries a string that is not one of the four declared roles,
    the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. This check
    runs before anything else — before body parsing, before existence lookups,
    before any state inspection."

    Design: Corner/rbac/request_without_auth_headers_returns_unauthenticated
    """
    set_clock()

    resp = api.create_business_unit({"name": "Anonymous Unit"},
                                    {"Content-Type": "application/json"})

    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert resp.status_code == 401
    assert resp.json()["data"]["error_id"] != "ERR_INVALID_REQUEST", (
        "authentication is checked before the payload is parsed")

    _rows, meta = validate_paginated(api.list_business_units(COUNSEL))
    assert meta["total_count"] == 0
