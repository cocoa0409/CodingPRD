"""Credential, complaint, hearing and assignment state-machine behaviour.

Every test builds its own preconditions: the harness relaunches the API server
before each test, so each one starts against an empty database.
"""

import test_helpers.fixtures as fixtures
from test_helpers import (
    ApiErrorId,
    SCHEDULING_COORDINATOR_USER_ID,
    adjudicate_complaint_payload,
    complete_assignment_payload,
    continue_hearing_payload,
    create_credential_payload,
    make_program_admin_headers,
    make_quality_reviewer_headers,
    review_complaint_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_certified_credential_application_opens_in_pending_written(
    api, credentialing_officer_headers
):
    """PRD §3.3: "A new credential's `status` is `PENDING_WRITTEN`, its `written_best_score` and `oral_best_score` are null, its `written_attempt_count` and `oral_attempt_count` are 0, its `cycle_credit_hours` is 0, its `renewal_count` is 0, and its three cycle dates — `issued_on`, `expires_on`, and `grace_through` — are all null until the credential is first activated."
    PRD §3.3: "The target tier is fixed at creation and never changes; the separate field `tier` stays null until the credential is activated and then mirrors `target_tier` for as long as the credential remains active, reverting to null if it lapses or is revoked."
    PRD §3.2: "The first credential application opened in their name promotes `APPLICANT → CANDIDATE`, and that promotion increments the interpreter's `version` by 1."

    Design: Corner/State Machines/credential_initial_state_branches_on_target_tier_and_language_class
    """
    language = fixtures.bootstrap_language()
    interpreter = fixtures.enrol_interpreter()
    assert interpreter["roster_status"] == "APPLICANT", (
        f"expected APPLICANT on enrolment, got {interpreter['roster_status']}"
    )

    response = api.create_credential(
        create_credential_payload(
            interpreter["id"], language["id"], interpreter["version"], "CERTIFIED"
        ),
        credentialing_officer_headers,
    )
    credential = validate_success(response, 201)

    assert credential["status"] == "PENDING_WRITTEN", (
        f"expected PENDING_WRITTEN, got {credential['status']} on a CERTIFIED "
        "application in a DESIGNATED language"
    )
    assert credential["target_tier"] == "CERTIFIED", (
        f"expected target_tier CERTIFIED, got {credential['target_tier']}"
    )
    assert credential["tier"] is None, (
        f"expected tier null before activation, got {credential['tier']}"
    )
    assert credential["written_best_score"] is None, (
        f"expected written_best_score null, got {credential['written_best_score']}"
    )
    assert credential["oral_best_score"] is None, (
        f"expected oral_best_score null, got {credential['oral_best_score']}"
    )
    assert credential["written_attempt_count"] == 0, (
        f"expected 0 written attempts, got {credential['written_attempt_count']}"
    )
    assert credential["oral_attempt_count"] == 0, (
        f"expected 0 oral attempts, got {credential['oral_attempt_count']}"
    )
    assert credential["cycle_credit_hours"] == 0, (
        f"expected cycle_credit_hours 0, got {credential['cycle_credit_hours']}"
    )
    assert credential["renewal_count"] == 0, (
        f"expected renewal_count 0, got {credential['renewal_count']}"
    )
    for field in ("issued_on", "expires_on", "grace_through"):
        assert credential[field] is None, (
            f"expected {field} null before first activation, got {credential[field]}"
        )

    promoted = fixtures.read_interpreter(interpreter["id"])
    assert promoted["roster_status"] == "CANDIDATE", (
        f"expected CANDIDATE after the first application, got "
        f"{promoted['roster_status']}"
    )
    assert promoted["version"] == interpreter["version"] + 1, (
        f"expected interpreter version {interpreter['version'] + 1} after the "
        f"promotion, got {promoted['version']}"
    )


def test_provisional_credential_in_a_rare_language_opens_in_pending_ethics(
    api, credentialing_officer_headers
):
    """PRD §3.3: "When the target tier is `PROVISIONAL` and the language's `tier_class` is `RARE`, the create call itself performs `PENDING_WRITTEN → PENDING_ETHICS` before returning, so the resource the client receives is already sitting in `PENDING_ETHICS` with its `version` incremented for that auto-transition."
    PRD §3.3: "A new credential's `status` is `PENDING_WRITTEN`, its `written_best_score` and `oral_best_score` are null, its `written_attempt_count` and `oral_attempt_count` are 0, its `cycle_credit_hours` is 0, its `renewal_count` is 0, and its three cycle dates — `issued_on`, `expires_on`, and `grace_through` — are all null until the credential is first activated."
    PRD §2.4: "Most resources additionally carry `updated_at` — same format as `created_at`, refreshed on every mutation of the row — and `version`, an integer that starts at 1 on creation and increases by exactly 1 each time the row is mutated."

    Design: Corner/State Machines/credential_initial_state_branches_on_target_tier_and_language_class
    """
    rare_language = fixtures.bootstrap_rare_language()
    interpreter = fixtures.enrol_interpreter()

    response = api.create_credential(
        create_credential_payload(
            interpreter["id"], rare_language["id"], interpreter["version"], "PROVISIONAL"
        ),
        credentialing_officer_headers,
    )
    credential = validate_success(response, 201)

    assert credential["status"] == "PENDING_ETHICS", (
        f"expected PENDING_ETHICS on a PROVISIONAL application in a RARE "
        f"language, got {credential['status']}"
    )
    assert credential["version"] == 2, (
        f"expected version 2 (creation plus the auto-transition), got "
        f"{credential['version']}"
    )
    assert credential["tier"] is None, (
        f"expected tier null before activation, got {credential['tier']}"
    )
    for field in ("issued_on", "expires_on", "grace_through"):
        assert credential[field] is None, (
            f"expected {field} null before first activation, got {credential[field]}"
        )
    assert credential["written_attempt_count"] == 0, (
        f"expected 0 written attempts on the examination-free route, got "
        f"{credential['written_attempt_count']}"
    )
    assert credential["oral_attempt_count"] == 0, (
        f"expected 0 oral attempts on the examination-free route, got "
        f"{credential['oral_attempt_count']}"
    )


def test_adjudicating_a_filed_complaint_is_refused_as_invalid_state(
    api, program_admin_headers
):
    """PRD §2.12: "Complaint `status` admits the requested transition — otherwise `ERR_INVALID_COMPLAINT_STATE` (409). Applies to `POST /complaints/{id}/review`, `POST /complaints/{id}/adjudicate`, `POST /complaints/{id}/appeal`, and `POST /complaints/{id}/appeal-decision`."
    PRD §3.9: "A substantiation is the loud branch, `REVIEWED → SUBSTANTIATED`, and it cascades in four hops."
    PRD §3.9: "Filing sets `status` to `FILED`, records `filed_by_user_id` from the acting `X-User-ID`, and leaves `reviewer_user_id`, `reviewer_recommendation`, `adjudicator_user_id`, `disposition`, `adjudicated_at` and `appeal_filed_at` all null with `remand_count` at 0."
    PRD §3.9: "Intake changes neither the interpreter's roster standing nor their `complaint_points` — nothing is proven yet."

    Design: Corner/State Machines/complaint_adjudicate_before_review_returns_invalid_state
    """
    interpreter = fixtures.enrol_interpreter()
    complaint = fixtures.file_complaint(
        interpreter["id"],
        filer_user_id="qr-001",
        category="ETHICS",
        severity="SEVERE",
        narrative="Interpreter discussed the case with a juror in the hallway.",
    )
    assert complaint["status"] == "FILED", (
        f"expected FILED on intake, got {complaint['status']}"
    )
    assert complaint["filed_by_user_id"] == "qr-001", (
        f"expected filed_by_user_id qr-001, got {complaint['filed_by_user_id']}"
    )

    response = api.adjudicate_complaint(
        complaint["id"],
        adjudicate_complaint_payload("SUBSTANTIATED", "REVOCATION"),
        make_program_admin_headers("pa-001"),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_COMPLAINT_STATE, 409)

    unchanged = fixtures.read_complaint(complaint["id"])
    assert unchanged["status"] == "FILED", (
        f"expected the complaint to stay FILED, got {unchanged['status']}"
    )
    for field in ("disposition", "adjudicator_user_id", "adjudicated_at"):
        assert unchanged[field] is None, (
            f"expected {field} still null after the refused adjudication, got "
            f"{unchanged[field]}"
        )
    assert unchanged["version"] == complaint["version"], (
        f"expected version {complaint['version']} after a refused call, got "
        f"{unchanged['version']}"
    )

    actions, actions_meta = validate_paginated(
        api.list_disciplinary_actions(
            program_admin_headers, params={"interpreter_id": interpreter["id"]}
        )
    )
    assert actions_meta["total_count"] == 0, (
        f"expected no disciplinary action, got {actions_meta['total_count']}"
    )
    assert actions == [], f"expected no disciplinary action rows, got {actions}"

    holder = fixtures.read_interpreter(interpreter["id"])
    assert holder["roster_status"] == "APPLICANT", (
        f"expected roster_status APPLICANT, got {holder['roster_status']}"
    )
    assert holder["complaint_points"] == 0, (
        f"expected complaint_points 0, got {holder['complaint_points']}"
    )


def test_reviewing_a_complaint_twice_is_refused_on_the_second_call(api):
    """PRD §3.9: "Review is a `QualityReviewer`'s exclusive act, `FILED → REVIEWED`. The reviewer supplies a `recommendation` of `SUBSTANTIATE` or `DISMISS` and written `findings`; the service records `reviewer_user_id` from the caller's `X-User-ID` and copies the recommendation into `reviewer_recommendation`."
    PRD §2.12: "Complaint `status` admits the requested transition — otherwise `ERR_INVALID_COMPLAINT_STATE` (409). Applies to `POST /complaints/{id}/review`, `POST /complaints/{id}/adjudicate`, `POST /complaints/{id}/appeal`, and `POST /complaints/{id}/appeal-decision`."
    PRD §2.4: "Most resources additionally carry `updated_at` — same format as `created_at`, refreshed on every mutation of the row — and `version`, an integer that starts at 1 on creation and increases by exactly 1 each time the row is mutated."

    Design: Corner/State Machines/complaint_review_twice_is_rejected_on_the_second_call
    """
    interpreter = fixtures.enrol_interpreter()
    complaint = fixtures.file_complaint(
        interpreter["id"],
        filer_user_id="qr-001",
        category="ACCURACY",
        severity="MAJOR",
        narrative="Two answers rendered in summary form.",
    )

    first = validate_success(
        api.review_complaint(
            complaint["id"],
            review_complaint_payload("SUBSTANTIATE", "Recording confirms summarisation."),
            make_quality_reviewer_headers("qr-002"),
        ),
        200,
    )
    assert first["status"] == "REVIEWED", (
        f"expected REVIEWED after the first review, got {first['status']}"
    )
    assert first["reviewer_user_id"] == "qr-002", (
        f"expected reviewer_user_id qr-002, got {first['reviewer_user_id']}"
    )
    assert first["reviewer_recommendation"] == "SUBSTANTIATE", (
        f"expected reviewer_recommendation SUBSTANTIATE, got "
        f"{first['reviewer_recommendation']}"
    )
    assert first["version"] == 2, (
        f"expected version 2 after one mutation, got {first['version']}"
    )

    second = api.review_complaint(
        complaint["id"],
        review_complaint_payload("DISMISS", "Second look: rendition acceptable."),
        make_quality_reviewer_headers("qr-003"),
    )
    validate_error(second, ApiErrorId.ERR_INVALID_COMPLAINT_STATE, 409)

    unchanged = fixtures.read_complaint(complaint["id"])
    assert unchanged["reviewer_user_id"] == "qr-002", (
        f"expected reviewer_user_id to stay qr-002, got {unchanged['reviewer_user_id']}"
    )
    assert unchanged["reviewer_recommendation"] == "SUBSTANTIATE", (
        f"expected reviewer_recommendation to stay SUBSTANTIATE, got "
        f"{unchanged['reviewer_recommendation']}"
    )
    assert unchanged["status"] == "REVIEWED", (
        f"expected status to stay REVIEWED, got {unchanged['status']}"
    )
    assert unchanged["version"] == 2, (
        f"expected version to stay 2 after the refused call, got "
        f"{unchanged['version']}"
    )


def test_continued_hearing_refuses_a_second_continuance(
    api, scheduling_coordinator_headers
):
    """PRD §3.5: "A `SchedulingCoordinator` or `ProgramAdmin` continues a hearing that is `SCHEDULED` or `COVERED`, supplying a `reason_code` of `COURT_CONGESTION`, `PARTY_REQUEST`, or `NO_INTERPRETER_AVAILABLE`; the logical clock must still be strictly before `scheduled_start`."
    PRD §3.5: "The hearing moves to `CONTINUED`, `continuance_count` is increased by 1, `continuance_reason_code` records the supplied code, and `version` is incremented by 1 — which invalidates any `expected_hearing_version` a client was holding."
    PRD §3.5: "A continued hearing is terminal — the coordinator files a fresh hearing for the new date rather than reopening this one — and it is excluded from every counter in language-access reporting, so a continuance never depresses a courthouse's coverage rate."
    PRD §3.5: "Requesting a continuance for a hearing already `SERVED`, `UNMET`, or `CONTINUED` is refused with `ERR_HEARING_NOT_SCHEDULABLE`."

    Design: Corner/State Machines/continued_hearing_is_terminal_and_refuses_a_second_continuance
    """
    config = fixtures.setup_program_config()
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CV-2026-0910",
        hearing_type="CIVIL_MOTION",
        in_custody=False,
        scheduled_start="2026-09-15T09:00:00.000Z",
        scheduled_end="2026-09-15T10:00:00.000Z",
    )
    assert hearing["status"] == "SCHEDULED", (
        f"expected SCHEDULED on creation, got {hearing['status']}"
    )
    assert hearing["continuance_count"] == 0, (
        f"expected continuance_count 0 on creation, got {hearing['continuance_count']}"
    )

    continued = validate_success(
        api.continue_hearing(
            hearing["id"],
            continue_hearing_payload("COURT_CONGESTION"),
            scheduling_coordinator_headers,
        ),
        200,
    )
    assert continued["status"] == "CONTINUED", (
        f"expected CONTINUED after the first continuance, got {continued['status']}"
    )
    assert continued["continuance_count"] == 1, (
        f"expected continuance_count 1, got {continued['continuance_count']}"
    )
    assert continued["continuance_reason_code"] == "COURT_CONGESTION", (
        f"expected continuance_reason_code COURT_CONGESTION, got "
        f"{continued['continuance_reason_code']}"
    )
    assert continued["version"] == hearing["version"] + 1, (
        f"expected hearing version {hearing['version'] + 1} after the continuance, "
        f"got {continued['version']}"
    )

    second = api.continue_hearing(
        hearing["id"],
        continue_hearing_payload("PARTY_REQUEST"),
        scheduling_coordinator_headers,
    )
    validate_error(second, ApiErrorId.ERR_HEARING_NOT_SCHEDULABLE, 409)

    unchanged = fixtures.read_hearing(hearing["id"])
    assert unchanged["status"] == "CONTINUED", (
        f"expected the hearing to stay CONTINUED, got {unchanged['status']}"
    )
    assert unchanged["continuance_count"] == 1, (
        f"expected continuance_count to stay 1 after the refused second call, got "
        f"{unchanged['continuance_count']}"
    )
    assert unchanged["continuance_reason_code"] == "COURT_CONGESTION", (
        f"expected continuance_reason_code to stay COURT_CONGESTION, got "
        f"{unchanged['continuance_reason_code']}"
    )
    assert unchanged["version"] == continued["version"], (
        f"expected version to stay {continued['version']} after the refused second "
        f"call, got {unchanged['version']}"
    )


def test_no_show_fires_every_declared_side_effect_in_one_call(
    api, scheduling_coordinator_headers, quality_reviewer_headers
):
    """PRD §3.7: "A no-show is recorded by a `SchedulingCoordinator` or `ProgramAdmin` against a `CONFIRMED` assignment once the logical clock has reached or passed the hearing's `scheduled_start`, and it is the one operation that touches both status dimensions in a single call."
    PRD §3.7: "On the service dimension it drives `CONFIRMED → NO_SHOW`; on the compliance dimension it drives `CLEAR → UNDER_QUALITY_REVIEW`."
    PRD §3.7: "The encumbered claim moves `ENCUMBERED → VOIDED`, releasing its provisional amount from the courthouse's `encumbered_pay_cents` — the interpreter who did not appear is paid nothing, unlike the interpreter whose assignment was cancelled late."
    PRD §3.7: "A complaint is filed automatically, in `FILED` status with `category` set to `NO_SHOW`, `severity` set to `MAJOR`, `assignment_id` pointing at this assignment, and `filed_by_user_id` set to the acting caller's `X-User-ID`."
    PRD §3.7: "The hearing moves `COVERED → UNMET` with its `version` incremented by 1: a no-show records the hearing as uncovered for the language-access record and does not reopen it for scheduling."
    PRD §3.7: "The assignment's `version` is incremented by 1."
    PRD §3.8: "Two total fields describe the two moments: `provisional_total_cents` is frozen at claim creation and is never overwritten, while `final_total_cents` stays null until the claim reaches `FINALIZED`."
    PRD §3.9: "Intake changes neither the interpreter's roster standing nor their `complaint_points` — nothing is proven yet."

    Design: Corner/State Machines/no_show_fires_every_declared_side_effect_in_one_call
    """
    bundle = fixtures.setup_confirmed_assignment(
        hearing_overrides={
            "case_number": "CR-2026-0925",
            "hearing_type": "MOTION",
            "in_custody": False,
            "scheduled_start": "2026-08-25T09:00:00.000Z",
            "scheduled_end": "2026-08-25T11:00:00.000Z",
        }
    )
    assignment = bundle["assignment"]
    claim = bundle["pay_claim"]
    provisional = claim["provisional_total_cents"]
    assert claim["status"] == "ENCUMBERED", (
        f"expected the confirm to leave an ENCUMBERED claim, got {claim['status']}"
    )
    assert bundle["hearing"]["status"] == "COVERED", (
        f"expected the hearing COVERED after confirmation, got "
        f"{bundle['hearing']['status']}"
    )
    courthouse_before = fixtures.read_courthouse(bundle["courthouse"]["id"])
    assert courthouse_before["encumbered_pay_cents"] == provisional, (
        f"expected encumbered_pay_cents {provisional} before the no-show, got "
        f"{courthouse_before['encumbered_pay_cents']}"
    )

    fixtures.set_clock("2026-08-25T09:30:00.000Z")
    after = validate_success(
        api.no_show_assignment(assignment["id"], scheduling_coordinator_headers), 200
    )

    assert after["service_status"] == "NO_SHOW", (
        f"expected service_status NO_SHOW, got {after['service_status']}"
    )
    assert after["compliance_status"] == "UNDER_QUALITY_REVIEW", (
        f"expected compliance_status UNDER_QUALITY_REVIEW, got "
        f"{after['compliance_status']}"
    )
    assert after["version"] == assignment["version"] + 1, (
        f"expected assignment version {assignment['version'] + 1}, got "
        f"{after['version']}"
    )

    voided = fixtures.read_pay_claim(claim["id"])
    assert voided["status"] == "VOIDED", (
        f"expected the claim VOIDED after the no-show, got {voided['status']}"
    )
    assert voided["final_total_cents"] is None, (
        f"expected final_total_cents null on a voided claim, got "
        f"{voided['final_total_cents']}"
    )
    assert voided["provisional_total_cents"] == provisional, (
        f"expected provisional_total_cents preserved at {provisional}, got "
        f"{voided['provisional_total_cents']}"
    )

    courthouse_after = fixtures.read_courthouse(bundle["courthouse"]["id"])
    assert courthouse_after["encumbered_pay_cents"] == 0, (
        f"expected encumbered_pay_cents released to 0, got "
        f"{courthouse_after['encumbered_pay_cents']}"
    )
    assert courthouse_after["obligated_pay_cents"] == 0, (
        f"expected obligated_pay_cents 0 — a no-show pays nothing, got "
        f"{courthouse_after['obligated_pay_cents']}"
    )
    assert (
        courthouse_after["available_pay_cents"]
        == courthouse_after["pay_budget_cents"]
    ), (
        f"expected available_pay_cents back to the full budget "
        f"{courthouse_after['pay_budget_cents']}, got "
        f"{courthouse_after['available_pay_cents']}"
    )

    complaints, complaints_meta = validate_paginated(
        api.list_complaints(
            quality_reviewer_headers, params={"assignment_id": assignment["id"]}
        )
    )
    assert complaints_meta["total_count"] == 1, (
        f"expected exactly one auto-filed complaint, got "
        f"{complaints_meta['total_count']}"
    )
    auto = complaints[0]
    assert auto["status"] == "FILED", (
        f"expected the auto-filed complaint FILED, got {auto['status']}"
    )
    assert auto["category"] == "NO_SHOW", (
        f"expected category NO_SHOW, got {auto['category']}"
    )
    assert auto["severity"] == "MAJOR", (
        f"expected severity MAJOR, got {auto['severity']}"
    )
    assert auto["assignment_id"] == assignment["id"], (
        f"expected assignment_id {assignment['id']}, got {auto['assignment_id']}"
    )
    assert auto["interpreter_id"] == bundle["interpreter"]["id"], (
        f"expected interpreter_id {bundle['interpreter']['id']}, got "
        f"{auto['interpreter_id']}"
    )
    assert auto["filed_by_user_id"] == SCHEDULING_COORDINATOR_USER_ID, (
        f"expected filed_by_user_id {SCHEDULING_COORDINATOR_USER_ID}, got "
        f"{auto['filed_by_user_id']}"
    )

    hearing_after = fixtures.read_hearing(bundle["hearing"]["id"])
    assert hearing_after["status"] == "UNMET", (
        f"expected the hearing UNMET after the no-show, got {hearing_after['status']}"
    )
    assert hearing_after["version"] == bundle["hearing"]["version"] + 1, (
        f"expected hearing version {bundle['hearing']['version'] + 1}, got "
        f"{hearing_after['version']}"
    )

    interpreter_after = fixtures.read_interpreter(bundle["interpreter"]["id"])
    assert interpreter_after["roster_status"] == "ACTIVE", (
        f"expected roster_status still ACTIVE — nothing is proven at intake, got "
        f"{interpreter_after['roster_status']}"
    )
    assert interpreter_after["complaint_points"] == 0, (
        f"expected complaint_points still 0 at intake, got "
        f"{interpreter_after['complaint_points']}"
    )


def test_revocation_cascades_to_every_credential_of_the_interpreter(api):
    """PRD §3.9: "**Hop one** creates a single disciplinary action in `IN_EFFECT` status, recording `complaint_id` and copying `interpreter_id` from the complaint, with `action_type` set to the requested sanction and `points` taken from the sanction scale — 5 for a `LETTER`, 10 for `PROBATION`, 12 for a `SUSPENSION`, 20 for a `REVOCATION`."
    PRD §3.9: "**Hop two** is triggered by that action becoming in-effect: the interpreter's `complaint_points` is recomputed to include the new points, both quality scores are recomputed, and the interpreter's `roster_status` moves `ACTIVE → SUSPENDED` for a suspension, with `suspension_through` set to the action's `effective_through`, or `ACTIVE → REVOKED` for a revocation."
    PRD §3.9: "A revocation is broader still: it cancels every `PROPOSED` or `CONFIRMED` assignment of the interpreter regardless of date with the same reason code, and it drives every credential of theirs in `PENDING_WRITTEN`, `PENDING_ORAL`, `PENDING_ETHICS`, `ACTIVE`, or `LAPSED` to `REVOKED`, processed in credential `created_at` ascending order."
    PRD §3.9: "Both branches record `adjudicator_user_id` from the caller's `X-User-ID` and `adjudicated_at` from the logical clock, which starts the appeal window; both set `disposition` to match; and both increment the complaint's `version` by 1."
    PRD §3.2: "`credential_tier` is the highest tier among the interpreter's credentials whose status is `ACTIVE`, ranked `MASTER` above `CERTIFIED` above `REGISTERED` above `PROVISIONAL`, and reads `NONE` when no credential of theirs is active."
    PRD §3.2: "`credentialed_language_ids` lists the language of each of those active credentials, ordered by the credential's own `created_at` ascending."
    PRD §3.2: "The separate field `complaint_points` is the plain, unweighted sum of `points` over the same `IN_EFFECT` and `EXPIRED` rows, with no decay and no floor."
    PRD §3.1: "Registration also initialises the derived `active_credentialed_count` to 0; thereafter it always equals the number of credentials in this language whose status is `ACTIVE`, and it is recomputed by every credential activation, lapse and revocation."
    PRD §3.3: "The target tier is fixed at creation and never changes; the separate field `tier` stays null until the credential is activated and then mirrors `target_tier` for as long as the credential remains active, reverting to null if it lapses or is revoked."

    Design: Corner/State Machines/revocation_cascades_down_to_every_credential_of_the_interpreter
    """
    fixtures.set_clock()
    spanish = fixtures.bootstrap_language()
    korean = fixtures.bootstrap_language(
        code="kor",
        name="Korean",
        tier_class="NON_DESIGNATED",
        oral_exam_available=True,
    )
    bundle = fixtures.setup_active_interpreter(spanish["id"])
    interpreter = bundle["interpreter"]
    active_credential = bundle["credential"]
    pending_credential = fixtures.open_credential(
        interpreter["id"], korean["id"], target_tier="REGISTERED"
    )
    assert active_credential["status"] == "ACTIVE", (
        f"expected the Spanish credential ACTIVE, got {active_credential['status']}"
    )
    assert pending_credential["status"] == "PENDING_WRITTEN", (
        f"expected the Korean credential PENDING_WRITTEN, got "
        f"{pending_credential['status']}"
    )

    complaint = fixtures.setup_reviewed_complaint(
        interpreter["id"],
        category="ETHICS",
        severity="SEVERE",
        narrative="Interpreter accepted a payment from a party to the case.",
        findings="Bank records confirm the payment.",
    )
    adjudicated = validate_success(
        api.adjudicate_complaint(
            complaint["id"],
            adjudicate_complaint_payload("SUBSTANTIATED", "REVOCATION"),
            make_program_admin_headers("pa-001"),
        ),
        200,
    )
    assert adjudicated["status"] == "SUBSTANTIATED", (
        f"expected status SUBSTANTIATED, got {adjudicated['status']}"
    )
    assert adjudicated["disposition"] == "SUBSTANTIATED", (
        f"expected disposition SUBSTANTIATED, got {adjudicated['disposition']}"
    )
    assert adjudicated["adjudicator_user_id"] == "pa-001", (
        f"expected adjudicator_user_id pa-001, got "
        f"{adjudicated['adjudicator_user_id']}"
    )
    assert adjudicated["adjudicated_at"].startswith("2026-08-01T00:00:00"), (
        f"expected adjudicated_at on the logical clock 2026-08-01T00:00:00, got "
        f"{adjudicated['adjudicated_at']}"
    )

    actions = fixtures.disciplinary_actions_for(interpreter["id"])
    assert len(actions) == 1, (
        f"expected exactly one disciplinary action, got {len(actions)}"
    )
    action = actions[0]
    assert action["action_type"] == "REVOCATION", (
        f"expected action_type REVOCATION, got {action['action_type']}"
    )
    assert action["points"] == 20, (
        f"expected 20 points for a revocation, got {action['points']}"
    )
    assert action["status"] == "IN_EFFECT", (
        f"expected the action IN_EFFECT, got {action['status']}"
    )
    assert action["effective_from"] == "2026-08-01", (
        f"expected effective_from 2026-08-01, got {action['effective_from']}"
    )
    assert action["effective_through"] is None, (
        f"expected effective_through null — a revocation is permanent, got "
        f"{action['effective_through']}"
    )

    revoked_holder = fixtures.read_interpreter(interpreter["id"])
    assert revoked_holder["roster_status"] == "REVOKED", (
        f"expected roster_status REVOKED, got {revoked_holder['roster_status']}"
    )
    assert revoked_holder["credential_tier"] == "NONE", (
        f"expected credential_tier NONE once no credential is active, got "
        f"{revoked_holder['credential_tier']}"
    )
    assert revoked_holder["credentialed_language_ids"] == [], (
        f"expected credentialed_language_ids emptied, got "
        f"{revoked_holder['credentialed_language_ids']}"
    )
    assert revoked_holder["complaint_points"] == 20, (
        f"expected complaint_points 20, got {revoked_holder['complaint_points']}"
    )

    score = fixtures.read_quality_score(interpreter["id"])
    assert score["rolling_12_month_score"] == 20, (
        f"expected rolling_12_month_score 100 - 4*20 = 20, got "
        f"{score['rolling_12_month_score']}"
    )
    assert score["lifetime_score"] == 20, (
        f"expected lifetime_score 100 - 4*20 - 2*0 = 20, got "
        f"{score['lifetime_score']}"
    )
    assert score["complaint_points"] == 20, (
        f"expected complaint_points 20 on the computed read, got "
        f"{score['complaint_points']}"
    )

    for credential in (active_credential, pending_credential):
        after = fixtures.read_credential(credential["id"])
        assert after["status"] == "REVOKED", (
            f"expected credential {credential['id']} REVOKED by the cascade, got "
            f"{after['status']}"
        )
        assert after["tier"] is None, (
            f"expected tier cleared on the revoked credential, got {after['tier']}"
        )

    assert fixtures.read_language(spanish["id"])["active_credentialed_count"] == 0, (
        "expected the Spanish active_credentialed_count back to 0 after the "
        "revocation cascade"
    )
    assert fixtures.read_language(korean["id"])["active_credentialed_count"] == 0, (
        "expected the Korean active_credentialed_count to stay 0 — its credential "
        "was never active"
    )


def test_vendor_served_completion_skips_the_pay_ledger_entirely(
    api, scheduling_coordinator_headers, fiscal_officer_headers
):
    """PRD §3.6: "A vendor-served assignment is the program's last resort for a rare language with nobody on the roster: `interpreter_id` is null exactly when `vendor_served` is true, and such an assignment carries no credential pin, no roster checks and, as §3.7 explains, no pay claim."
    PRD §3.7: "A vendor-served assignment skips the claim creation entirely — no claim, no encumbrance, no ledger movement — because the vendor bills the court outside the program's ledger."
    PRD §3.7: "For a rostered interpreter the path is `CHECKED_IN → COMPLETED` and `actual_end_utc` must be strictly after `check_in_utc`; for a vendor-served assignment the path is `CONFIRMED → COMPLETED` — there is no check-in for a vendor — and `actual_end_utc` must be strictly after the hearing's `scheduled_start`."
    PRD §3.7: "For a vendor-served assignment every one of those pay-ledger hops is skipped: no claim is created and none is finalized."
    PRD §3.7: "Completion moves the hearing `COVERED → SERVED` and increments the hearing's `version` by 1."
    PRD §2.9: "A claim in `VOIDED` status appears in neither sum, and a vendor-served assignment produces no claim at all and therefore never touches either sum."

    Design: Corner/State Machines/vendor_served_completion_skips_the_pay_ledger_entirely
    """
    fixtures.set_clock()
    rare_language = fixtures.bootstrap_rare_language()
    courthouse = fixtures.bootstrap_courthouse()
    fixtures.bootstrap_rate_schedule()
    hearing = fixtures.schedule_hearing(
        courthouse["id"],
        rare_language["id"],
        case_number="CR-2026-0930",
        hearing_type="MOTION",
        in_custody=False,
        scheduled_start="2026-09-10T09:00:00.000Z",
        scheduled_end="2026-09-10T10:00:00.000Z",
        requested_delivery_mode="TELEPHONIC",
    )
    assignment = fixtures.propose_assignment(
        hearing["id"],
        delivery_mode="TELEPHONIC",
        vendor_served=True,
        estimated_one_way_miles=0,
    )
    assert assignment["interpreter_id"] is None, (
        f"expected interpreter_id null on a vendor row, got "
        f"{assignment['interpreter_id']}"
    )
    assert assignment["credential_id"] is None, (
        f"expected credential_id null — a vendor row carries no credential pin, got "
        f"{assignment['credential_id']}"
    )

    confirmed = validate_success(
        api.confirm_assignment(assignment["id"], scheduling_coordinator_headers), 200
    )
    assert confirmed["service_status"] == "CONFIRMED", (
        f"expected service_status CONFIRMED, got {confirmed['service_status']}"
    )
    claims_after_confirm, confirm_meta = validate_paginated(
        api.list_pay_claims(
            fiscal_officer_headers, params={"assignment_id": assignment["id"]}
        )
    )
    assert confirm_meta["total_count"] == 0, (
        f"expected no pay claim after a vendor confirm, got "
        f"{confirm_meta['total_count']}"
    )
    assert claims_after_confirm == [], (
        f"expected no pay claim rows after a vendor confirm, got "
        f"{claims_after_confirm}"
    )
    ledger_after_confirm = fixtures.read_courthouse(courthouse["id"])
    assert ledger_after_confirm["encumbered_pay_cents"] == 0, (
        f"expected encumbered_pay_cents 0 after a vendor confirm, got "
        f"{ledger_after_confirm['encumbered_pay_cents']}"
    )
    assert (
        ledger_after_confirm["available_pay_cents"]
        == ledger_after_confirm["pay_budget_cents"]
    ), (
        f"expected available_pay_cents untouched at "
        f"{ledger_after_confirm['pay_budget_cents']}, got "
        f"{ledger_after_confirm['available_pay_cents']}"
    )

    fixtures.set_clock("2026-09-10T10:05:00.000Z")
    completed = validate_success(
        api.complete_assignment(
            assignment["id"],
            complete_assignment_payload("2026-09-10T10:00:00.000Z"),
            scheduling_coordinator_headers,
        ),
        200,
    )
    assert completed["service_status"] == "COMPLETED", (
        f"expected CONFIRMED -> COMPLETED with no check-in, got "
        f"{completed['service_status']}"
    )
    assert completed["actual_end_utc"] == "2026-09-10T10:00:00.000Z", (
        f"expected actual_end_utc 2026-09-10T10:00:00.000Z, got "
        f"{completed['actual_end_utc']}"
    )

    claims_after_complete, complete_meta = validate_paginated(
        api.list_pay_claims(
            fiscal_officer_headers, params={"assignment_id": assignment["id"]}
        )
    )
    assert complete_meta["total_count"] == 0, (
        f"expected still no pay claim after a vendor completion, got "
        f"{complete_meta['total_count']}"
    )
    assert claims_after_complete == [], (
        f"expected no pay claim rows after a vendor completion, got "
        f"{claims_after_complete}"
    )
    ledger_after_complete = fixtures.read_courthouse(courthouse["id"])
    assert ledger_after_complete["obligated_pay_cents"] == 0, (
        f"expected obligated_pay_cents 0 — nothing was finalized, got "
        f"{ledger_after_complete['obligated_pay_cents']}"
    )
    assert ledger_after_complete["encumbered_pay_cents"] == 0, (
        f"expected encumbered_pay_cents 0 after a vendor completion, got "
        f"{ledger_after_complete['encumbered_pay_cents']}"
    )

    served = fixtures.read_hearing(hearing["id"])
    assert served["status"] == "SERVED", (
        f"expected the hearing SERVED — the bubble-up still fires for a vendor, got "
        f"{served['status']}"
    )


def test_suspension_expiry_on_the_daily_sweep_reinstates_the_roster_but_keeps_the_points(
    api, program_admin_headers
):
    """PRD §3.9: "Its `effective_from` is the logical-clock date, and its `effective_through` is 365 days after `effective_from` for a `LETTER`, 180 days after for `PROBATION`, the requested `suspension_days` after for a `SUSPENSION`, and null for a `REVOCATION`, which is permanent."
    PRD §3.9: "**Hop two** is triggered by that action becoming in-effect: the interpreter's `complaint_points` is recomputed to include the new points, both quality scores are recomputed, and the interpreter's `roster_status` moves `ACTIVE → SUSPENDED` for a suspension, with `suspension_through` set to the action's `effective_through`, or `ACTIVE → REVOKED` for a revocation."
    PRD §3.10: "**Step two, sanction expiry and reinstatement.** Every disciplinary action in `IN_EFFECT` status whose `effective_through` is not null and lies strictly before the current logical-clock date moves `IN_EFFECT → EXPIRED`."
    PRD §3.10: "A `SUSPENDED` interpreter with no remaining `IN_EFFECT` suspension against them is then reinstated: `suspension_through` is cleared to null, `complaint_points` and both quality scores are recomputed, and their `roster_status` returns to `ACTIVE` when they still hold a credential in `ACTIVE` status, or to `INACTIVE` when they do not."
    PRD §3.9: "`IN_EFFECT → EXPIRED` is clock-driven: once `effective_through` is not null and the logical-clock date has moved strictly past it, the daily operations run expires the action — and an expired action's `points` still count toward `complaint_points` and toward both quality scores, because the program remembers a served sanction."
    PRD §3.2: "Then `rolling_12_month_score` is 100 less four times the recent-points figure, floored at 0 so it never reports a negative number."
    PRD §3.2: "And `lifetime_score` is 100 less four times the recent-points figure less twice the older-points figure, also floored at 0."
    PRD §3.10: "Its response carries `swept_at`, the logical-clock instant the run executed, together with six identifier arrays: `lapsed_credential_ids`, `downgraded_interpreter_ids`, `expired_action_ids`, `reinstated_interpreter_ids`, `unmet_hearing_ids`, `cancelled_assignment_ids`, and `voided_pay_claim_ids`."
    PRD §3.10: "The run is idempotent with respect to the logical clock: invoked a second time without the clock having moved, it returns all-empty arrays and mutates nothing."

    Design: Corner/State Machines/suspension_expiry_on_the_daily_sweep_reinstates_the_roster_but_keeps_the_points
    """
    fixtures.set_clock()
    language = fixtures.bootstrap_language()
    bundle = fixtures.setup_active_interpreter(language["id"])
    interpreter = bundle["interpreter"]
    credential = bundle["credential"]
    assert credential["expires_on"] == "2028-07-31", (
        f"expected the credential cycle to end 2028-07-31 so expiry cannot "
        f"interfere, got {credential['expires_on']}"
    )

    sanction = fixtures.setup_sanction(
        interpreter["id"],
        "SUSPENSION",
        severity="MAJOR",
        category="PROFESSIONALISM",
        suspension_days=30,
        narrative="Interpreter left the courtroom during testimony.",
    )
    action = sanction["action"]
    assert action is not None, "expected the substantiation to create an action"
    assert action["action_type"] == "SUSPENSION", (
        f"expected action_type SUSPENSION, got {action['action_type']}"
    )
    assert action["points"] == 12, (
        f"expected 12 points for a suspension, got {action['points']}"
    )
    assert action["status"] == "IN_EFFECT", (
        f"expected the action IN_EFFECT, got {action['status']}"
    )
    assert action["effective_from"] == "2026-08-01", (
        f"expected effective_from 2026-08-01, got {action['effective_from']}"
    )
    assert action["effective_through"] == "2026-08-31", (
        f"expected effective_through 2026-08-01 plus 30 days = 2026-08-31, got "
        f"{action['effective_through']}"
    )

    suspended = fixtures.read_interpreter(interpreter["id"])
    assert suspended["roster_status"] == "SUSPENDED", (
        f"expected roster_status SUSPENDED, got {suspended['roster_status']}"
    )
    assert suspended["suspension_through"] == "2026-08-31", (
        f"expected suspension_through 2026-08-31, got "
        f"{suspended['suspension_through']}"
    )
    assert suspended["complaint_points"] == 12, (
        f"expected complaint_points 12, got {suspended['complaint_points']}"
    )
    assert suspended["rolling_12_month_score"] == 52, (
        f"expected rolling_12_month_score 100 - 4*12 = 52, got "
        f"{suspended['rolling_12_month_score']}"
    )
    assert suspended["lifetime_score"] == 52, (
        f"expected lifetime_score 100 - 4*12 - 2*0 = 52, got "
        f"{suspended['lifetime_score']}"
    )

    fixtures.set_clock("2026-09-01T00:00:00.000Z")
    first_sweep = validate_success(api.run_daily_sweep(program_admin_headers), 200)
    assert first_sweep["swept_at"].startswith("2026-09-01T00:00:00"), (
        f"expected swept_at on the logical clock 2026-09-01T00:00:00, got "
        f"{first_sweep['swept_at']}"
    )
    assert first_sweep["expired_action_ids"] == [action["id"]], (
        f"expected expired_action_ids [{action['id']}], got "
        f"{first_sweep['expired_action_ids']}"
    )
    assert first_sweep["reinstated_interpreter_ids"] == [interpreter["id"]], (
        f"expected reinstated_interpreter_ids [{interpreter['id']}], got "
        f"{first_sweep['reinstated_interpreter_ids']}"
    )
    assert first_sweep["lapsed_credential_ids"] == [], (
        f"expected no lapsed credentials, got {first_sweep['lapsed_credential_ids']}"
    )
    assert first_sweep["unmet_hearing_ids"] == [], (
        f"expected no unmet hearings, got {first_sweep['unmet_hearing_ids']}"
    )

    expired_actions = fixtures.disciplinary_actions_for(interpreter["id"])
    assert len(expired_actions) == 1, (
        f"expected the single action row to survive the sweep, got "
        f"{len(expired_actions)}"
    )
    expired = expired_actions[0]
    assert expired["status"] == "EXPIRED", (
        f"expected the action EXPIRED after the sweep, got {expired['status']}"
    )
    assert expired["points"] == 12, (
        f"expected the expired action to keep its 12 points, got {expired['points']}"
    )

    reinstated = fixtures.read_interpreter(interpreter["id"])
    assert reinstated["roster_status"] == "ACTIVE", (
        f"expected roster_status back to ACTIVE, got {reinstated['roster_status']}"
    )
    assert reinstated["suspension_through"] is None, (
        f"expected suspension_through cleared, got {reinstated['suspension_through']}"
    )
    assert reinstated["credential_tier"] == "CERTIFIED", (
        f"expected credential_tier CERTIFIED — the credential never lapsed, got "
        f"{reinstated['credential_tier']}"
    )
    assert reinstated["complaint_points"] == 12, (
        f"expected complaint_points still 12 — reinstatement is not forgiveness, got "
        f"{reinstated['complaint_points']}"
    )
    assert reinstated["rolling_12_month_score"] == 52, (
        f"expected rolling_12_month_score still 52, got "
        f"{reinstated['rolling_12_month_score']}"
    )
    assert reinstated["lifetime_score"] == 52, (
        f"expected lifetime_score still 52, got {reinstated['lifetime_score']}"
    )

    second_sweep = validate_success(api.run_daily_sweep(program_admin_headers), 200)
    for array_name in (
        "lapsed_credential_ids",
        "downgraded_interpreter_ids",
        "expired_action_ids",
        "reinstated_interpreter_ids",
        "unmet_hearing_ids",
        "cancelled_assignment_ids",
        "voided_pay_claim_ids",
    ):
        assert second_sweep[array_name] == [], (
            f"expected {array_name} empty on the idempotent second sweep, got "
            f"{second_sweep[array_name]}"
        )

    unchanged_interpreter = fixtures.read_interpreter(interpreter["id"])
    assert unchanged_interpreter["version"] == reinstated["version"], (
        f"expected interpreter version to stay {reinstated['version']} across the "
        f"second sweep, got {unchanged_interpreter['version']}"
    )
    unchanged_action = fixtures.disciplinary_actions_for(interpreter["id"])[0]
    assert unchanged_action["version"] == expired["version"], (
        f"expected action version to stay {expired['version']} across the second "
        f"sweep, got {unchanged_action['version']}"
    )
    assert unchanged_action["status"] == "EXPIRED", (
        f"expected the action to stay EXPIRED, got {unchanged_action['status']}"
    )
