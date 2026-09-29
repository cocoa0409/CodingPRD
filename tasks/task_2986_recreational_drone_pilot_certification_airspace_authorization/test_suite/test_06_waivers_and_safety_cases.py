"""Waiver applications, safety cases and the review loop.

Covers the non-linear review cycle a waiver walks between `SUBMITTED`,
`UNDER_REVIEW` and `REVISION_REQUESTED`, the dependency submission has on the
applicant's live certification, the specific assurance and integrity level a
safety case is stamped with at creation, the clearance ceiling that level is
measured against, and the segregation of duties between the reviewer who clears
a case and the approver who decides the waiver.
"""

from test_helpers import (
    COMPLIANCE_OFFICER,
    MAX_APPROVABLE_SAIL,
    SAFETY_REVIEWER,
    SAFETY_REVIEWER_2,
    SAFETY_REVIEWER_ID,
    SAFETY_REVIEWER_ID_2,
    WAIVER_APPROVER,
    WAIVER_APPROVER_ID,
    WAIVER_VALIDITY_DAYS,
    AirRiskClass,
    ApiErrorId,
    Clock,
    OperatorCategory,
    PilotStatus,
    Role,
    SafetyCaseReviewStatus,
    TestCode,
    WaiverStatus,
    WaiverType,
    assert_pilot,
    assert_safety_case,
    assert_waiver,
    factories,
    fixtures,
    make_headers,
    make_pilot_headers,
    shift_days,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_waiver_review_loop_revisits_under_review_and_ends_approved(api):
    """PRD §3.5: "The pilot submits the application, which is admissible from `DRAFT` or from `REVISION_REQUESTED` and lands in `SUBMITTED`."
    PRD §3.5: "A `SafetyReviewer` takes a `SUBMITTED` application to `UNDER_REVIEW`, and from `UNDER_REVIEW` has exactly two moves."
    PRD §3.5: "The first is to request a revision, supplying `reviewer_findings`: the waiver returns to `REVISION_REQUESTED`, `revision_round` is incremented by one, and every safety case of the waiver moves from `PENDING` to `REVISION_REQUESTED` with the findings stored on it."
    PRD §3.5: "The cycle `SUBMITTED → UNDER_REVIEW → REVISION_REQUESTED → SUBMITTED` is the review loop, and it closes at most twice."
    PRD §3.5: "It moves the waiver to `APPROVED`, stores the granted ceiling, sets `approved_by_user_id` to the approver's `X-User-ID`, and sets `valid_until` to the current instant advanced by 180 whole days with the time-of-day preserved."

    Design: Difficulty/non_linear_state_machine/waiver_review_revision_cycle_revisits_under_review
    """
    clock = Clock(api)
    clock.set("2026-08-05T00:00:00Z")

    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=800
    )
    owner = make_pilot_headers(pilot["id"])

    waiver = fixtures.create_draft_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.OVER_PEOPLE.value,
        700,
        operation_description="Overhead coverage of a ticketed outdoor event with a tethered corridor.",
    )
    assert_waiver(waiver, status=WaiverStatus.DRAFT.value, revision_round=0)
    case = fixtures.attach_safety_case(
        api, waiver, ground_risk_class=2, air_risk_class=AirRiskClass.ARC_B.value
    )
    assert_safety_case(
        case, sail_level=3, review_status=SafetyCaseReviewStatus.PENDING.value
    )

    submitted = validate_success(api.submit_waiver(waiver["id"], headers=owner))
    assert_waiver(submitted, status=WaiverStatus.SUBMITTED.value, revision_round=0)

    first_review = validate_success(
        api.begin_waiver_review(waiver["id"], headers=SAFETY_REVIEWER)
    )
    assert_waiver(first_review, status=WaiverStatus.UNDER_REVIEW.value, revision_round=0)

    sent_back = validate_success(
        api.request_waiver_revision(
            waiver["id"],
            factories.revision_request_payload(
                reviewer_findings="Parachute deployment altitude is not documented; resubmit with the minimum safe height."
            ),
            headers=SAFETY_REVIEWER,
        )
    )
    assert_waiver(
        sent_back, status=WaiverStatus.REVISION_REQUESTED.value, revision_round=1
    )

    resubmitted = validate_success(api.submit_waiver(waiver["id"], headers=owner))
    assert_waiver(resubmitted, status=WaiverStatus.SUBMITTED.value, revision_round=1)

    second_review = validate_success(
        api.begin_waiver_review(waiver["id"], headers=SAFETY_REVIEWER)
    )
    # Entering review a second time is not itself a revision, so the round holds at 1.
    assert_waiver(
        second_review, status=WaiverStatus.UNDER_REVIEW.value, revision_round=1
    )

    cleared = validate_success(
        api.clear_waiver_safety_case(
            waiver["id"],
            factories.clear_safety_case_payload(
                reviewer_findings="Deployment altitude now documented at 150 ft; the assurance level is accepted."
            ),
            headers=SAFETY_REVIEWER,
        )
    )
    assert_waiver(cleared, status=WaiverStatus.CLEARED.value, revision_round=1)

    decided = validate_success(
        api.decide_waiver(
            waiver["id"],
            factories.approve_waiver_payload(granted_ceiling_ft=700),
            headers=WAIVER_APPROVER,
        )
    )
    assert_waiver(
        decided,
        status=WaiverStatus.APPROVED.value,
        revision_round=1,
        granted_ceiling_ft=700,
        valid_until=shift_days("2026-08-05T00:00:00Z", WAIVER_VALIDITY_DAYS),
    )
    assert decided["approved_by_user_id"] == WAIVER_APPROVER_ID, (
        f"expected the deciding approver {WAIVER_APPROVER_ID} to be stamped, "
        f"got {decided['approved_by_user_id']}"
    )


def test_revision_cycle_mirrors_onto_the_same_safety_case_row(api):
    """PRD §3.5: "It is created with `review_status` `PENDING`, `reviewer_findings` null and `cleared_by_user_id` null."
    PRD §3.5: "The first is to request a revision, supplying `reviewer_findings`: the waiver returns to `REVISION_REQUESTED`, `revision_round` is incremented by one, and every safety case of the waiver moves from `PENDING` to `REVISION_REQUESTED` with the findings stored on it."
    PRD §3.5: "Resubmission from `REVISION_REQUESTED` additionally returns every safety case of the waiver from `REVISION_REQUESTED` to `PENDING` and clears its `reviewer_findings` back to null, so the reviewer sees a clean slate."
    PRD §3.5: "Clearance moves the waiver to `CLEARED` and moves every safety case of the waiver from `PENDING` to `CLEARED`, stamping the reviewer's own `X-User-ID` into `cleared_by_user_id`."

    Design: Difficulty/non_linear_state_machine/waiver_review_revision_cycle_revisits_under_review
    """
    clock = Clock(api)
    clock.set("2026-08-05T00:00:00Z")

    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=800
    )
    owner = make_pilot_headers(pilot["id"])

    waiver = fixtures.create_draft_waiver(
        api, pilot["id"], aircraft["id"], WaiverType.OVER_PEOPLE.value, 700
    )
    case = fixtures.attach_safety_case(
        api, waiver, ground_risk_class=2, air_risk_class=AirRiskClass.ARC_B.value
    )
    assert case["reviewer_findings"] is None, (
        f"a fresh safety case carries no findings, got {case['reviewer_findings']!r}"
    )
    assert case["cleared_by_user_id"] is None, (
        f"a fresh safety case names no clearing officer, got {case['cleared_by_user_id']!r}"
    )

    validate_success(api.submit_waiver(waiver["id"], headers=owner))
    validate_success(api.begin_waiver_review(waiver["id"], headers=SAFETY_REVIEWER))

    findings = "Expand the ground-risk mitigation section with the stand-off calculation."
    validate_success(
        api.request_waiver_revision(
            waiver["id"],
            factories.revision_request_payload(reviewer_findings=findings),
            headers=SAFETY_REVIEWER,
        )
    )
    after_revision = validate_success(
        api.get_safety_case(case["id"], headers=SAFETY_REVIEWER)
    )
    assert_safety_case(
        after_revision,
        review_status=SafetyCaseReviewStatus.REVISION_REQUESTED.value,
        sail_level=3,
    )
    assert after_revision["reviewer_findings"] == findings, (
        f"expected the reviewer findings to be stored on the case, "
        f"got {after_revision['reviewer_findings']!r}"
    )

    validate_success(api.submit_waiver(waiver["id"], headers=owner))
    after_resubmission = validate_success(
        api.get_safety_case(case["id"], headers=SAFETY_REVIEWER)
    )
    assert_safety_case(
        after_resubmission,
        review_status=SafetyCaseReviewStatus.PENDING.value,
        sail_level=3,
    )
    assert after_resubmission["reviewer_findings"] is None, (
        f"resubmission clears the findings back to null, "
        f"got {after_resubmission['reviewer_findings']!r}"
    )

    validate_success(api.begin_waiver_review(waiver["id"], headers=SAFETY_REVIEWER))
    validate_success(
        api.clear_waiver_safety_case(
            waiver["id"],
            factories.clear_safety_case_payload(),
            headers=SAFETY_REVIEWER,
        )
    )
    after_clearance = validate_success(
        api.get_safety_case(case["id"], headers=SAFETY_REVIEWER)
    )
    assert_safety_case(
        after_clearance,
        review_status=SafetyCaseReviewStatus.CLEARED.value,
        sail_level=3,
    )
    assert after_clearance["cleared_by_user_id"] == SAFETY_REVIEWER_ID, (
        f"expected the clearing reviewer {SAFETY_REVIEWER_ID} to be stamped, "
        f"got {after_clearance['cleared_by_user_id']}"
    )

    listed, meta = validate_paginated(
        api.list_safety_cases(params={"waiver_id": waiver["id"]}, headers=SAFETY_REVIEWER)
    )
    assert meta["total_count"] == 1, (
        f"the loop must not create a second safety case, got {meta['total_count']}"
    )
    assert listed[0]["id"] == case["id"], (
        f"expected the original case {case['id']} to survive the loop, got {listed[0]['id']}"
    )


def test_submission_is_refused_while_the_applicant_pilot_is_lapsed(api):
    """PRD §2.11: "16. **Certification gate**, on `POST /drone-ops/airspace-authorizations`, `POST /drone-ops/waivers/{id}/submit`, `POST /drone-ops/flights`, `POST /drone-ops/flights/{id}/launch` and `POST /drone-ops/airspace-authorizations/{id}/decide`: the pilot's `status` is `CERTIFIED` — otherwise `ERR_PILOT_NOT_CERTIFIED` (409)."
    PRD §3.5: "Submission requires the pilot to be `CERTIFIED` — a lapsed or suspended pilot cannot push an application forward, which is the cross-entity guard that keeps waiver review tied to live certification — and requires at least one safety case to exist for the waiver, otherwise the submission is refused with `ERR_SAFETY_CASE_MISSING`."
    PRD §3.2: "The review rewrites `currency_expires_at` and `currency_basis`; moves the pilot from `CERTIFIED` to `LAPSED` when the recomputed expiry is at or before the current instant; moves the pilot from `LAPSED` back to `CERTIFIED` when the recomputed expiry is strictly after the current instant, which happens once a fresh certificate or a fresh completed flight has pushed the anchor forward; transitions any of that pilot's certificates in `ACTIVE` whose `expires_at` is at or before the current instant to `EXPIRED`; and recomputes `risk_score`."

    Design: Difficulty/cross_entity_state_dependency/waiver_submission_depends_on_pilot_certification_state
    """
    clock = Clock(api)

    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    assert_pilot(
        pilot,
        status=PilotStatus.CERTIFIED.value,
        currency_expires_at="2026-10-30T00:00:00Z",
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=700
    )
    owner = make_pilot_headers(pilot["id"])

    waiver = fixtures.create_draft_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.NIGHT.value,
        500,
        operation_description="Night thermal inspection of a fenced substation with lighting on the airframe.",
    )
    case = fixtures.attach_safety_case(
        api, waiver, ground_risk_class=2, air_risk_class=AirRiskClass.ARC_B.value
    )
    assert_safety_case(
        case, sail_level=3, review_status=SafetyCaseReviewStatus.PENDING.value
    )

    clock.set("2026-10-31T00:00:00Z")
    reviewed = validate_success(
        api.currency_review(pilot["id"], headers=COMPLIANCE_OFFICER)
    )
    assert_pilot(reviewed, status=PilotStatus.LAPSED.value)

    validate_error(
        api.submit_waiver(waiver["id"], headers=owner),
        ApiErrorId.PILOT_NOT_CERTIFIED.value,
        409,
    )

    unchanged_waiver = validate_success(api.get_waiver(waiver["id"], headers=owner))
    assert_waiver(
        unchanged_waiver, status=WaiverStatus.DRAFT.value, revision_round=0
    )
    unchanged_case = validate_success(
        api.get_safety_case(case["id"], headers=SAFETY_REVIEWER)
    )
    assert_safety_case(
        unchanged_case,
        review_status=SafetyCaseReviewStatus.PENDING.value,
        sail_level=3,
    )


def test_recertifying_the_pilot_unblocks_the_unchanged_waiver_submission(api):
    """PRD §3.1: "Booking is admissible only from `UNCERTIFIED` or from `LAPSED` — a pilot who is already `KNOWLEDGE_PENDING`, already `CERTIFIED`, or `REVOKED` is refused with `ERR_PILOT_INVALID_STATE` — and it moves the pilot to `KNOWLEDGE_PENDING`."
    PRD §3.1: "The pass mark depends entirely on which exam was sat: the recreational knowledge test is graded against a mark of 100, and the commercial exam against a mark of 70."
    PRD §3.1: "The pilot then moves from `KNOWLEDGE_PENDING` to `CERTIFIED`, `certified_at` is set to the new certificate's `issued_at`, and `currency_expires_at` together with `currency_basis` are recomputed as described in §3.2."
    PRD §3.2: "Under `COMMERCIAL_BASIS`, which applies whenever the `operator_category` is `COMMERCIAL`, both constraints bite and the earlier of the two wins: the projected expiry is the base expiry when the base expiry is the earlier instant, and the recency expiry otherwise."
    PRD §3.5: "Submission requires the pilot to be `CERTIFIED` — a lapsed or suspended pilot cannot push an application forward, which is the cross-entity guard that keeps waiver review tied to live certification — and requires at least one safety case to exist for the waiver, otherwise the submission is refused with `ERR_SAFETY_CASE_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/waiver_submission_depends_on_pilot_certification_state
    """
    clock = Clock(api)

    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=700
    )
    owner = make_pilot_headers(pilot["id"])

    waiver = fixtures.create_draft_waiver(
        api, pilot["id"], aircraft["id"], WaiverType.NIGHT.value, 500
    )
    case = fixtures.attach_safety_case(
        api, waiver, ground_risk_class=2, air_risk_class=AirRiskClass.ARC_B.value
    )

    clock.set("2026-10-31T00:00:00Z")
    lapsed = validate_success(api.currency_review(pilot["id"], headers=COMPLIANCE_OFFICER))
    assert_pilot(lapsed, status=PilotStatus.LAPSED.value)
    validate_error(
        api.submit_waiver(waiver["id"], headers=owner),
        ApiErrorId.PILOT_NOT_CERTIFIED.value,
        409,
    )

    resit = validate_success(
        api.schedule_knowledge_test(
            pilot["id"],
            factories.knowledge_test_payload(
                TestCode.PART107_COMMERCIAL.value, clock.now
            ),
            headers=COMPLIANCE_OFFICER,
        ),
        201,
    )
    graded = validate_success(
        api.grade_knowledge_test(
            resit["id"], factories.grade_payload(raw_score=72), headers=COMPLIANCE_OFFICER
        )
    )
    assert graded["passed"] is True, (
        f"a commercial score of 72 clears the mark of 70, got passed={graded['passed']!r}"
    )

    recertified = validate_success(api.get_pilot(pilot["id"], headers=owner))
    assert_pilot(
        recertified,
        status=PilotStatus.CERTIFIED.value,
        currency_expires_at="2027-01-29T00:00:00Z",
    )

    submitted = validate_success(api.submit_waiver(waiver["id"], headers=owner))
    assert_waiver(
        submitted,
        status=WaiverStatus.SUBMITTED.value,
        revision_round=0,
        pilot_id=pilot["id"],
        aircraft_id=aircraft["id"],
        requested_ceiling_ft=500,
    )
    still_pending = validate_success(
        api.get_safety_case(case["id"], headers=SAFETY_REVIEWER)
    )
    assert_safety_case(
        still_pending,
        review_status=SafetyCaseReviewStatus.PENDING.value,
        sail_level=3,
    )


def test_review_triggers_are_refused_on_a_draft_waiver(api):
    """PRD §2.11: "13. **Declared source state**, on every state-changing endpoint: the addressed resource sits in a state from which the requested transition is declared, with the code naming the entity whose state blocks it — `ERR_PILOT_INVALID_STATE`, `ERR_TEST_ALREADY_GRADED`, `ERR_MODULE_INVALID_STATE`, `ERR_AIRCRAFT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, `ERR_FLIGHT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` or `ERR_TFR_INVALID_STATE`, each HTTP 409."
    PRD §3.5: "The application is created in `DRAFT` with `revision_round` 0 and with `granted_ceiling_ft`, `valid_until`, `approved_by_user_id` and `denial_reason` all null."
    PRD §3.5: "A `SafetyReviewer` takes a `SUBMITTED` application to `UNDER_REVIEW`, and from `UNDER_REVIEW` has exactly two moves."
    PRD §3.5: "The reviewer's second move is to clear the safety case, optionally recording `reviewer_findings`."

    Design: Corner/state_machines/waiver_triggers_from_undeclared_states_are_rejected
    """
    clock = Clock(api)
    clock.set("2026-08-05T00:00:00Z")

    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=700
    )
    owner = make_pilot_headers(pilot["id"])

    waiver = fixtures.create_draft_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.NIGHT.value,
        400,
        operation_description="Night inspection of a rail yard with lit obstacle markers.",
    )
    assert_waiver(
        waiver,
        status=WaiverStatus.DRAFT.value,
        revision_round=0,
        granted_ceiling_ft=None,
        valid_until=None,
    )
    case = fixtures.attach_safety_case(
        api, waiver, ground_risk_class=2, air_risk_class=AirRiskClass.ARC_B.value
    )
    assert_safety_case(
        case, sail_level=3, review_status=SafetyCaseReviewStatus.PENDING.value
    )

    validate_error(
        api.begin_waiver_review(waiver["id"], headers=SAFETY_REVIEWER),
        ApiErrorId.WAIVER_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.clear_waiver_safety_case(
            waiver["id"], factories.clear_safety_case_payload(), headers=SAFETY_REVIEWER
        ),
        ApiErrorId.WAIVER_INVALID_STATE.value,
        409,
    )

    after = validate_success(api.get_waiver(waiver["id"], headers=owner))
    assert_waiver(after, status=WaiverStatus.DRAFT.value, revision_round=0)
    after_case = validate_success(
        api.get_safety_case(case["id"], headers=SAFETY_REVIEWER)
    )
    assert_safety_case(
        after_case, review_status=SafetyCaseReviewStatus.PENDING.value, sail_level=3
    )
    assert after_case["cleared_by_user_id"] is None, (
        "a refused clearance must not stamp a clearing officer, "
        f"got {after_case['cleared_by_user_id']!r}"
    )


def test_resubmission_and_an_early_decision_are_refused_mid_review(api):
    """PRD §2.11: "13. **Declared source state**, on every state-changing endpoint: the addressed resource sits in a state from which the requested transition is declared, with the code naming the entity whose state blocks it — `ERR_PILOT_INVALID_STATE`, `ERR_TEST_ALREADY_GRADED`, `ERR_MODULE_INVALID_STATE`, `ERR_AIRCRAFT_INVALID_STATE`, `ERR_AUTHORIZATION_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`, `ERR_FLIGHT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE` or `ERR_TFR_INVALID_STATE`, each HTTP 409."
    PRD §3.5: "The pilot submits the application, which is admissible from `DRAFT` or from `REVISION_REQUESTED` and lands in `SUBMITTED`."
    PRD §3.5: "A `WaiverApprover` then decides a `CLEARED` application by supplying a `decision` of `APPROVE` or `DENY`, with `granted_ceiling_ft` and `denial_reason` as conditional inputs."

    Design: Corner/state_machines/waiver_triggers_from_undeclared_states_are_rejected
    """
    clock = Clock(api)
    clock.set("2026-08-05T00:00:00Z")

    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=700
    )
    owner = make_pilot_headers(pilot["id"])

    waiver = fixtures.create_draft_waiver(
        api, pilot["id"], aircraft["id"], WaiverType.NIGHT.value, 400
    )
    case = fixtures.attach_safety_case(
        api, waiver, ground_risk_class=2, air_risk_class=AirRiskClass.ARC_B.value
    )

    submitted = validate_success(api.submit_waiver(waiver["id"], headers=owner))
    assert_waiver(submitted, status=WaiverStatus.SUBMITTED.value)

    validate_error(
        api.submit_waiver(waiver["id"], headers=owner),
        ApiErrorId.WAIVER_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.clear_waiver_safety_case(
            waiver["id"], factories.clear_safety_case_payload(), headers=SAFETY_REVIEWER
        ),
        ApiErrorId.WAIVER_INVALID_STATE.value,
        409,
    )

    under_review = validate_success(
        api.begin_waiver_review(waiver["id"], headers=SAFETY_REVIEWER)
    )
    assert_waiver(under_review, status=WaiverStatus.UNDER_REVIEW.value)

    validate_error(
        api.decide_waiver(
            waiver["id"],
            factories.approve_waiver_payload(granted_ceiling_ft=400),
            headers=WAIVER_APPROVER,
        ),
        ApiErrorId.WAIVER_INVALID_STATE.value,
        409,
    )

    after = validate_success(api.get_waiver(waiver["id"], headers=owner))
    assert_waiver(
        after,
        status=WaiverStatus.UNDER_REVIEW.value,
        revision_round=0,
        granted_ceiling_ft=None,
        valid_until=None,
    )
    assert after["approved_by_user_id"] is None, (
        f"a refused decision must not stamp an approver, got {after['approved_by_user_id']!r}"
    )
    after_case = validate_success(
        api.get_safety_case(case["id"], headers=SAFETY_REVIEWER)
    )
    assert_safety_case(
        after_case, review_status=SafetyCaseReviewStatus.PENDING.value, sail_level=3
    )


def test_two_risk_pairs_reach_the_same_assurance_level_via_the_bvlos_uplift(api):
    """PRD §3.5: "At creation the service computes the case's `sail_level`, the specific assurance and integrity level, once."
    PRD §3.5: "Translate the `air_risk_class` to an index: `ARC_A` is 0, `ARC_B` is 1, `ARC_C` is 2, `ARC_D` is 3."
    PRD §3.5: "Add a beyond-visual-line-of-sight uplift of 1 when the parent waiver's `waiver_type` is `BVLOS`, and 0 for `OVER_PEOPLE` and `NIGHT`."
    PRD §3.5: "Sum the `ground_risk_class`, the air-risk index and the uplift, and cap the total at 6 — the result is the `sail_level`, always an integer from 1 to 6."
    PRD §3.5: "It is created with `review_status` `PENDING`, `reviewer_findings` null and `cleared_by_user_id` null."

    Design: Corner/calculations/sail_level_composes_ground_risk_air_risk_and_the_bvlos_uplift
    """
    pilot = fixtures.create_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft = fixtures.create_aircraft(
        api, pilot["id"], takeoff_weight_g=900, max_altitude_ft=1200
    )

    night_waiver = fixtures.create_draft_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.NIGHT.value,
        500,
        operation_description="Night survey of a rail corridor.",
    )
    night_case = fixtures.attach_safety_case(
        api, night_waiver, ground_risk_class=2, air_risk_class=AirRiskClass.ARC_C.value
    )
    assert_safety_case(
        night_case,
        waiver_id=night_waiver["id"],
        ground_risk_class=2,
        air_risk_class=AirRiskClass.ARC_C.value,
        sail_level=4,
        review_status=SafetyCaseReviewStatus.PENDING.value,
    )

    bvlos_waiver = fixtures.create_draft_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.BVLOS.value,
        500,
        operation_description="Linear inspection beyond visual line of sight.",
    )
    bvlos_case = fixtures.attach_safety_case(
        api, bvlos_waiver, ground_risk_class=2, air_risk_class=AirRiskClass.ARC_B.value
    )
    assert_safety_case(
        bvlos_case,
        waiver_id=bvlos_waiver["id"],
        ground_risk_class=2,
        air_risk_class=AirRiskClass.ARC_B.value,
        sail_level=4,
        review_status=SafetyCaseReviewStatus.PENDING.value,
    )

    assert bvlos_case["sail_level"] == night_case["sail_level"], (
        "a lower air-risk class plus the beyond-visual-line-of-sight uplift must land on "
        f"the same level: got {bvlos_case['sail_level']} against {night_case['sail_level']}"
    )
    for case in (night_case, bvlos_case):
        assert case["cleared_by_user_id"] is None, (
            "computing the level must not review the case, "
            f"got cleared_by_user_id={case['cleared_by_user_id']!r}"
        )


def test_the_assurance_level_is_capped_when_the_raw_sum_overflows(api):
    """PRD §3.5: "Translate the `air_risk_class` to an index: `ARC_A` is 0, `ARC_B` is 1, `ARC_C` is 2, `ARC_D` is 3."
    PRD §3.5: "Add a beyond-visual-line-of-sight uplift of 1 when the parent waiver's `waiver_type` is `BVLOS`, and 0 for `OVER_PEOPLE` and `NIGHT`."
    PRD §3.5: "Sum the `ground_risk_class`, the air-risk index and the uplift, and cap the total at 6 — the result is the `sail_level`, always an integer from 1 to 6."
    PRD §3.5: "The cap matters because the highest inputs overflow it: ground risk class 4 with `ARC_D` and a beyond-visual-line-of-sight operation sums to 8 and is reported as 6."

    Design: Corner/calculations/sail_level_composes_ground_risk_air_risk_and_the_bvlos_uplift
    """
    pilot = fixtures.create_pilot(api, OperatorCategory.COMMERCIAL.value)
    aircraft = fixtures.create_aircraft(
        api, pilot["id"], takeoff_weight_g=900, max_altitude_ft=1200
    )

    waiver = fixtures.create_draft_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.OVER_PEOPLE.value,
        500,
        operation_description="Crowd photography above a stadium concourse.",
    )
    case = fixtures.attach_safety_case(
        api, waiver, ground_risk_class=4, air_risk_class=AirRiskClass.ARC_D.value
    )
    assert_safety_case(
        case,
        waiver_id=waiver["id"],
        ground_risk_class=4,
        air_risk_class=AirRiskClass.ARC_D.value,
        sail_level=6,
        review_status=SafetyCaseReviewStatus.PENDING.value,
    )
    assert case["sail_level"] > MAX_APPROVABLE_SAIL, (
        f"a capped level of {case['sail_level']} must sit above the clearable ceiling "
        f"of {MAX_APPROVABLE_SAIL}"
    )


def test_clearance_is_refused_and_inert_above_the_acceptable_assurance_level(api):
    """PRD §2.11: "31. **Safety case acceptability**, on `POST /drone-ops/waivers/{id}/clear-safety-case` only: the safety case's `sail_level` is at most 5 — otherwise `ERR_SAIL_LEVEL_UNACCEPTABLE` (422)."
    PRD §3.5: "Clearance requires the `sail_level` to be at most 5; a case at `sail_level` 6 is refused with `ERR_SAIL_LEVEL_UNACCEPTABLE` and can never be cleared, because `sail_level` is fixed at creation and no revision recomputes it — the applicant must file a fresh application with a lower risk classification."
    PRD §3.5: "Sum the `ground_risk_class`, the air-risk index and the uplift, and cap the total at 6 — the result is the `sail_level`, always an integer from 1 to 6."

    Design: Corner/endpoints/clearing_a_safety_case_is_conditional_on_its_sail_level
    """
    clock = Clock(api)
    clock.set("2026-12-01T00:00:00Z")

    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_aircraft(
        api, pilot["id"], takeoff_weight_g=900, max_altitude_ft=1200
    )

    waiver, case = fixtures.create_under_review_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.BVLOS.value,
        500,
        4,
        AirRiskClass.ARC_C.value,
        operation_description="Pipeline patrol beyond visual line of sight.",
    )
    assert_safety_case(case, sail_level=6)
    assert_waiver(waiver, status=WaiverStatus.UNDER_REVIEW.value, revision_round=0)

    validate_error(
        api.clear_waiver_safety_case(
            waiver["id"],
            factories.clear_safety_case_payload(
                reviewer_findings="Ground risk unmitigated for an urban corridor."
            ),
            headers=SAFETY_REVIEWER,
        ),
        ApiErrorId.SAIL_LEVEL_UNACCEPTABLE.value,
        422,
    )

    after_waiver = validate_success(api.get_waiver(waiver["id"], headers=SAFETY_REVIEWER))
    assert_waiver(
        after_waiver, status=WaiverStatus.UNDER_REVIEW.value, revision_round=0
    )
    after_case = validate_success(
        api.get_safety_case(case["id"], headers=SAFETY_REVIEWER)
    )
    assert_safety_case(
        after_case, review_status=SafetyCaseReviewStatus.PENDING.value, sail_level=6
    )
    assert after_case["cleared_by_user_id"] is None, (
        "a refused clearance must leave the clearing officer unset, "
        f"got {after_case['cleared_by_user_id']!r}"
    )


def test_clearance_succeeds_at_exactly_the_acceptable_assurance_level(api):
    """PRD §2.11: "31. **Safety case acceptability**, on `POST /drone-ops/waivers/{id}/clear-safety-case` only: the safety case's `sail_level` is at most 5 — otherwise `ERR_SAIL_LEVEL_UNACCEPTABLE` (422)."
    PRD §3.5: "The reviewer's second move is to clear the safety case, optionally recording `reviewer_findings`."
    PRD §3.5: "Clearance moves the waiver to `CLEARED` and moves every safety case of the waiver from `PENDING` to `CLEARED`, stamping the reviewer's own `X-User-ID` into `cleared_by_user_id`."

    Design: Corner/endpoints/clearing_a_safety_case_is_conditional_on_its_sail_level
    """
    clock = Clock(api)
    clock.set("2026-12-01T00:00:00Z")

    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.COMMERCIAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_aircraft(
        api, pilot["id"], takeoff_weight_g=900, max_altitude_ft=1200
    )

    waiver, case = fixtures.create_under_review_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.NIGHT.value,
        500,
        3,
        AirRiskClass.ARC_C.value,
        operation_description="Night thermal survey of a substation.",
    )
    assert_safety_case(case, sail_level=MAX_APPROVABLE_SAIL)

    cleared = validate_success(
        api.clear_waiver_safety_case(waiver["id"], headers=SAFETY_REVIEWER)
    )
    assert_waiver(cleared, status=WaiverStatus.CLEARED.value, revision_round=0)

    after_case = validate_success(
        api.get_safety_case(case["id"], headers=SAFETY_REVIEWER)
    )
    assert_safety_case(
        after_case,
        review_status=SafetyCaseReviewStatus.CLEARED.value,
        sail_level=MAX_APPROVABLE_SAIL,
    )
    assert after_case["cleared_by_user_id"] == SAFETY_REVIEWER_ID, (
        f"expected the clearing reviewer {SAFETY_REVIEWER_ID} to be recorded, "
        f"got {after_case['cleared_by_user_id']}"
    )


def test_the_clearing_reviewer_cannot_decide_the_waiver_they_cleared(api):
    """PRD §2.11: "2. **Role admissibility**, on every endpoint: `X-User-Role` names one of the six declared roles and that role appears in the endpoint's authorised list — otherwise `ERR_UNAUTHORIZED` (403)."
    PRD §2.11: "4. **Waiver-decision segregation**, on `POST /drone-ops/waivers/{id}/decide` only: `X-User-ID` differs from the `cleared_by_user_id` of the waiver's safety case — otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §3.5: "Clearance moves the waiver to `CLEARED` and moves every safety case of the waiver from `PENDING` to `CLEARED`, stamping the reviewer's own `X-User-ID` into `cleared_by_user_id`."
    PRD §3.5: "Both branches require the deciding `X-User-ID` to differ from the safety case's `cleared_by_user_id`; the same human may not both clear and approve, and an attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_same_user_cannot_clear_a_safety_case_and_then_decide_that_waiver
    """
    clock = Clock(api)
    clock.set("2026-11-01T00:00:00Z")

    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.RECREATIONAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )

    waiver, case = fixtures.create_cleared_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.NIGHT.value,
        400,
        2,
        AirRiskClass.ARC_B.value,
        reviewer_headers=SAFETY_REVIEWER,
        operation_description="Night survey of a quarry face.",
    )
    assert_waiver(waiver, status=WaiverStatus.CLEARED.value)
    assert_safety_case(
        case, sail_level=3, review_status=SafetyCaseReviewStatus.CLEARED.value
    )
    assert case["cleared_by_user_id"] == SAFETY_REVIEWER_ID, (
        f"expected the clearing identity {SAFETY_REVIEWER_ID} on the safety case, "
        f"got {case['cleared_by_user_id']}"
    )

    clearer_as_approver = make_headers(SAFETY_REVIEWER_ID, Role.WAIVER_APPROVER.value)
    refusal = api.decide_waiver(
        waiver["id"],
        factories.approve_waiver_payload(granted_ceiling_ft=400),
        headers=clearer_as_approver,
    )
    validate_error(refusal, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    assert refusal.json()["data"]["message"], (
        "the refusal must carry a human-readable message"
    )

    after_refusal = validate_success(
        api.get_waiver(waiver["id"], headers=COMPLIANCE_OFFICER)
    )
    assert_waiver(
        after_refusal,
        status=WaiverStatus.CLEARED.value,
        granted_ceiling_ft=None,
        valid_until=None,
    )
    assert after_refusal["approved_by_user_id"] is None, (
        "the refused decision must leave no approver stamped, "
        f"got {after_refusal['approved_by_user_id']!r}"
    )

    approved = validate_success(
        api.decide_waiver(
            waiver["id"],
            factories.approve_waiver_payload(granted_ceiling_ft=400),
            headers=WAIVER_APPROVER,
        )
    )
    assert_waiver(
        approved, status=WaiverStatus.APPROVED.value, granted_ceiling_ft=400
    )
    assert approved["approved_by_user_id"] == WAIVER_APPROVER_ID, (
        f"expected the second approver {WAIVER_APPROVER_ID} on the identical body, "
        f"got {approved['approved_by_user_id']}"
    )


def test_merely_beginning_a_review_does_not_bar_deciding_that_waiver(api):
    """PRD §2.11: "4. **Waiver-decision segregation**, on `POST /drone-ops/waivers/{id}/decide` only: `X-User-ID` differs from the `cleared_by_user_id` of the waiver's safety case — otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."
    PRD §3.5: "Clearance moves the waiver to `CLEARED` and moves every safety case of the waiver from `PENDING` to `CLEARED`, stamping the reviewer's own `X-User-ID` into `cleared_by_user_id`."
    PRD §3.5: "That stamp is readable through the safety-case reads, which is what makes the segregation-of-duties rule observable to clients rather than a hidden trap."
    PRD §3.5: "Both branches require the deciding `X-User-ID` to differ from the safety case's `cleared_by_user_id`; the same human may not both clear and approve, and an attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_same_user_cannot_clear_a_safety_case_and_then_decide_that_waiver
    """
    clock = Clock(api)
    clock.set("2026-11-01T00:00:00Z")

    pilot = fixtures.create_certified_pilot(
        api, OperatorCategory.RECREATIONAL.value, scheduled_at=clock.now
    )
    aircraft = fixtures.create_registered_aircraft(
        api, pilot["id"], takeoff_weight_g=249, max_altitude_ft=900
    )

    # The first reviewer opens the review; a second reviewer is the one who clears.
    waiver, case = fixtures.create_cleared_waiver(
        api,
        pilot["id"],
        aircraft["id"],
        WaiverType.OVER_PEOPLE.value,
        400,
        2,
        AirRiskClass.ARC_B.value,
        reviewer_headers=SAFETY_REVIEWER_2,
        operation_description="Crowd overflight at a village fete.",
    )
    assert_waiver(waiver, status=WaiverStatus.CLEARED.value)
    assert case["cleared_by_user_id"] == SAFETY_REVIEWER_ID_2, (
        f"expected the clearing identity {SAFETY_REVIEWER_ID_2} on the safety case, "
        f"got {case['cleared_by_user_id']}"
    )

    opener_as_approver = make_headers(SAFETY_REVIEWER_ID, Role.WAIVER_APPROVER.value)
    approved = validate_success(
        api.decide_waiver(
            waiver["id"],
            factories.approve_waiver_payload(granted_ceiling_ft=400),
            headers=opener_as_approver,
        )
    )
    assert_waiver(
        approved,
        status=WaiverStatus.APPROVED.value,
        granted_ceiling_ft=400,
        valid_until=shift_days("2026-11-01T00:00:00Z", WAIVER_VALIDITY_DAYS),
    )
    assert approved["approved_by_user_id"] == SAFETY_REVIEWER_ID, (
        f"expected {SAFETY_REVIEWER_ID}, who only opened the review, to be accepted as "
        f"the approver, got {approved['approved_by_user_id']}"
    )
