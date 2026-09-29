"""Cross-entity state gates: ethics training and the compliance dimension.

Two gates that live on a *different* entity from the row being transitioned:

* `PENDING_ETHICS -> ACTIVE` on a credential reads the holding interpreter's
  `ethics_training_status` (PRD §3.3), not anything on the credential itself.
* `SUBMITTED -> APPROVED` on a pay claim reads the parent assignment's
  `compliance_status` (PRD §3.8), which a complaint moves independently of the
  service dimension (PRD §3.7, §3.9).

Every test builds its own world; the server starts empty before each test.
"""

import test_helpers.fixtures as fixtures
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_complaint_payload,
    review_complaint_payload,
    make_program_admin_headers,
    make_quality_reviewer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CREDENTIALING = TEST_USERS["credentialing_officer_headers"]
COORDINATOR = TEST_USERS["scheduling_coordinator_headers"]
FISCAL = TEST_USERS["fiscal_officer_headers"]
ADMIN = TEST_USERS["program_admin_headers"]

# The served-hearing fixture shared by the compliance-gate tests: a TRIAL in
# custody on 2026-08-20 09:00-12:00Z, served 09:00-12:30Z, 40.0 one-way miles.
HEARING_09_TO_12 = {
    "case_number": "CR-2026-0120",
    "hearing_type": "TRIAL",
    "in_custody": True,
    "scheduled_start": "2026-08-20T09:00:00.000Z",
    "scheduled_end": "2026-08-20T12:00:00.000Z",
    "requested_delivery_mode": "IN_PERSON",
}


def _setup_submitted_claim_under_review():
    """Served + submitted claim, then one ACCURACY complaint naming the assignment.

    Returns (bundle, complaint) where bundle carries interpreter, assignment,
    hearing, courthouse and the claim.
    """
    bundle = fixtures.setup_submitted_pay_claim(
        check_in_clock="2026-08-20T09:00:00Z",
        actual_end_utc="2026-08-20T12:30:00.000Z",
        one_way_miles=40.0,
        hearing_overrides=dict(HEARING_09_TO_12),
        assignment_overrides={"estimated_one_way_miles": 40.0},
    )
    complaint = fixtures.file_complaint(
        bundle["interpreter"]["id"],
        bundle["assignment"]["id"],
        filer_user_id="qr-001",
        category="ACCURACY",
        severity="MINOR",
        narrative="Party reports two mistranslated terms during the plea colloquy.",
    )
    return bundle, complaint


# ---------------------------------------------------------------------------
# Credential activation is gated on the HOLDER's ethics field (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------
def test_advance_to_active_refused_while_holder_ethics_training_incomplete(api):
    """PRD §3.3: "The final advancement, `PENDING_ETHICS → ACTIVE`, is the one that issues the licence, and it is gated on the *holder* rather than the credential: the interpreter's `ethics_training_status` must read `COMPLETED`, or the call fails with `ERR_ETHICS_TRAINING_INCOMPLETE`."
    PRD §3.2: "Recording completion does **not** by itself activate anything: a credential waiting on ethics still requires an explicit advancement call from a `CredentialingOfficer`, and until `ethics_training_status` reads `COMPLETED` both that advancement and any attempt to assign the interpreter to a hearing are refused with `ERR_ETHICS_TRAINING_INCOMPLETE`."
    PRD §3.2: "The first credential application opened in their name promotes `APPLICANT → CANDIDATE`, and that promotion increments the interpreter's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/credential_activation_gated_on_interpreter_ethics_field_not_on_credential_state
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    bundle = fixtures.setup_pending_ethics_credential(
        config["language"]["id"], target_tier="CERTIFIED",
        interpreter_overrides={
            "full_name": "Cy Okonkwo",
            "email": "cy.okonkwo@courts.example.gov",
        },
    )
    interpreter, credential = bundle["interpreter"], bundle["credential"]

    assert interpreter["ethics_training_status"] == "NOT_STARTED", (
        f"expected NOT_STARTED, got {interpreter['ethics_training_status']} before "
        "any ethics course was recorded"
    )
    assert interpreter["roster_status"] == "CANDIDATE", (
        f"expected CANDIDATE, got {interpreter['roster_status']} after the first "
        "credential application was opened"
    )
    assert credential["status"] == "PENDING_ETHICS", (
        f"expected PENDING_ETHICS, got {credential['status']} after both "
        "examinations passed"
    )

    response = api.advance_credential(credential["id"], CREDENTIALING)
    validate_error(response, ApiErrorId.ERR_ETHICS_TRAINING_INCOMPLETE)

    after = fixtures.read_credential(credential["id"])
    assert after["status"] == "PENDING_ETHICS", (
        f"expected PENDING_ETHICS, got {after['status']} after the refused advance"
    )
    assert after["version"] == credential["version"], (
        f"expected version {credential['version']}, got {after['version']} — the "
        "refused advance must mutate nothing"
    )
    assert after["tier"] is None, (
        f"expected tier null, got {after['tier']} on a credential that never activated"
    )

    holder = fixtures.read_interpreter(interpreter["id"])
    assert holder["roster_status"] == "CANDIDATE", (
        f"expected CANDIDATE, got {holder['roster_status']} after the refused advance"
    )
    assert holder["credential_tier"] == "NONE", (
        f"expected NONE, got {holder['credential_tier']} with no active credential"
    )


def test_recording_ethics_training_alone_does_not_activate_the_credential(api):
    """PRD §3.2: "A `CredentialingOfficer` or `ProgramAdmin` records completion by supplying the `completed_on` date and the `provider` that delivered the course; the service sets `ethics_training_status` to `COMPLETED`, copies the supplied date into `ethics_completed_on`, and increments the interpreter's `version` by 1."
    PRD §3.2: "Recording completion does **not** by itself activate anything: a credential waiting on ethics still requires an explicit advancement call from a `CredentialingOfficer`, and until `ethics_training_status` reads `COMPLETED` both that advancement and any attempt to assign the interpreter to a hearing are refused with `ERR_ETHICS_TRAINING_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/credential_activation_gated_on_interpreter_ethics_field_not_on_credential_state
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    bundle = fixtures.setup_pending_ethics_credential(
        config["language"]["id"], target_tier="CERTIFIED",
        interpreter_overrides={
            "full_name": "Cy Okonkwo",
            "email": "cy.okonkwo@courts.example.gov",
        },
    )
    interpreter, credential = bundle["interpreter"], bundle["credential"]

    updated = fixtures.complete_ethics_training(
        interpreter["id"], completed_on="2026-08-01"
    )
    assert updated["ethics_training_status"] == "COMPLETED", (
        f"expected COMPLETED, got {updated['ethics_training_status']} after the "
        "course was recorded"
    )
    assert updated["ethics_completed_on"] == "2026-08-01", (
        f"expected 2026-08-01, got {updated['ethics_completed_on']} copied from "
        "the supplied completed_on"
    )
    assert updated["version"] == interpreter["version"] + 1, (
        f"expected version {interpreter['version'] + 1}, got {updated['version']} "
        "after recording ethics completion"
    )

    unchanged = fixtures.read_credential(credential["id"])
    assert unchanged["status"] == "PENDING_ETHICS", (
        f"expected PENDING_ETHICS, got {unchanged['status']} — recording ethics "
        "activates nothing by itself"
    )
    assert unchanged["version"] == credential["version"], (
        f"expected version {credential['version']}, got {unchanged['version']} — "
        "the credential row was not touched by the ethics recording"
    )
    assert unchanged["tier"] is None, (
        f"expected tier null, got {unchanged['tier']} on a still-pending credential"
    )
    assert updated["roster_status"] == "CANDIDATE", (
        f"expected CANDIDATE, got {updated['roster_status']} — the holder is not "
        "promoted by ethics alone"
    )
    assert updated["credential_tier"] == "NONE", (
        f"expected NONE, got {updated['credential_tier']} with no active credential"
    )


def test_advance_after_ethics_recorded_activates_and_bubbles_the_roster(api):
    """PRD §3.3: "The final advancement, `PENDING_ETHICS → ACTIVE`, is the one that issues the licence, and it is gated on the *holder* rather than the credential: the interpreter's `ethics_training_status` must read `COMPLETED`, or the call fails with `ERR_ETHICS_TRAINING_INCOMPLETE`."
    PRD §3.3: "On success the credential's `status` becomes `ACTIVE` and `tier` is set to `target_tier`; `issued_on` records the logical-clock date of this first activation; `expires_on` is set 730 days — two full years — after that date for a `MASTER`, `CERTIFIED`, or `REGISTERED` credential, and 365 days after it for a `PROVISIONAL` one, whose shorter cycle reflects that it rests on no examination; and `grace_through` is set 90 days after `expires_on`."
    PRD §3.3: "The activation then cascades: the language's `active_credentialed_count` is recomputed, the holder's `credential_tier` and `credentialed_language_ids` are recomputed, and the holder's `roster_status` bubbles up from `CANDIDATE` to `ACTIVE` if this is their first active credential or from `INACTIVE` to `ACTIVE` if they had fallen off the roster."
    PRD §3.2: "`credentialed_language_ids` lists the language of each of those active credentials, ordered by the credential's own `created_at` ascending."
    PRD §3.1: "Registration also initialises the derived `active_credentialed_count` to 0; thereafter it always equals the number of credentials in this language whose status is `ACTIVE`, and it is recomputed by every credential activation, lapse and revocation."

    Design: Difficulty/cross_entity_state_dependency/credential_activation_gated_on_interpreter_ethics_field_not_on_credential_state
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    language_id = config["language"]["id"]
    bundle = fixtures.setup_pending_ethics_credential(
        language_id, target_tier="CERTIFIED", with_ethics=True,
        interpreter_overrides={
            "full_name": "Cy Okonkwo",
            "email": "cy.okonkwo@courts.example.gov",
        },
    )
    interpreter, credential = bundle["interpreter"], bundle["credential"]
    assert interpreter["ethics_training_status"] == "COMPLETED", (
        f"expected COMPLETED, got {interpreter['ethics_training_status']} before "
        "the final advance"
    )
    assert credential["status"] == "PENDING_ETHICS", (
        f"expected PENDING_ETHICS, got {credential['status']} before the final advance"
    )

    activated = validate_success(
        api.advance_credential(credential["id"], CREDENTIALING)
    )
    assert activated["status"] == "ACTIVE", (
        f"expected ACTIVE, got {activated['status']} once the holder's ethics "
        "training reads COMPLETED"
    )
    assert activated["tier"] == "CERTIFIED", (
        f"expected CERTIFIED, got {activated['tier']} — tier mirrors target_tier "
        "on activation"
    )
    assert activated["issued_on"] == "2026-08-01", (
        f"expected 2026-08-01, got {activated['issued_on']} from the logical clock"
    )
    assert activated["expires_on"] == "2028-07-31", (
        f"expected 2028-07-31 (issued_on plus 730 days), got {activated['expires_on']}"
    )
    assert activated["grace_through"] == "2028-10-29", (
        f"expected 2028-10-29 (expires_on plus 90 days), got "
        f"{activated['grace_through']}"
    )
    assert activated["version"] == credential["version"] + 1, (
        f"expected version {credential['version'] + 1}, got {activated['version']} "
        "after the activating advance"
    )

    holder = fixtures.read_interpreter(interpreter["id"])
    assert holder["roster_status"] == "ACTIVE", (
        f"expected ACTIVE, got {holder['roster_status']} after the first credential "
        "activated"
    )
    assert holder["credential_tier"] == "CERTIFIED", (
        f"expected CERTIFIED, got {holder['credential_tier']} after activation"
    )
    assert holder["credentialed_language_ids"] == [language_id], (
        f"expected [{language_id}], got {holder['credentialed_language_ids']} after "
        "activation"
    )

    language = fixtures.read_language(language_id)
    assert language["active_credentialed_count"] == 1, (
        f"expected 1, got {language['active_credentialed_count']} after one "
        "credential in this language activated"
    )


# ---------------------------------------------------------------------------
# Fiscal approval is gated on the ASSIGNMENT's compliance dimension (PRD §3.8)
# ---------------------------------------------------------------------------
def test_filing_a_complaint_on_the_assignment_moves_only_the_compliance_dimension(api):
    """PRD §3.9: "When an `assignment_id` is present, however, the named assignment's `compliance_status` moves `CLEAR → UNDER_QUALITY_REVIEW`, which immediately freezes fiscal approval of that assignment's pay claim."
    PRD §3.9: "Filing sets `status` to `FILED`, records `filed_by_user_id` from the acting `X-User-ID`, and leaves `reviewer_user_id`, `reviewer_recommendation`, `adjudicator_user_id`, `disposition`, `adjudicated_at` and `appeal_filed_at` all null with `remand_count` at 0."
    PRD §3.9: "Intake changes neither the interpreter's roster standing nor their `complaint_points` — nothing is proven yet."
    PRD §3.7: "An assignment can perfectly well be `COMPLETED` and `UNDER_QUALITY_REVIEW` at the same time; indeed that combination is the normal one after a served hearing draws an accuracy complaint."

    Design: Difficulty/cross_entity_state_dependency/fiscal_approval_gated_on_assignment_compliance_dimension_then_released_by_dismissal
    """
    bundle, complaint = _setup_submitted_claim_under_review()

    assert complaint["status"] == "FILED", (
        f"expected FILED, got {complaint['status']} on a freshly filed complaint"
    )
    assert complaint["filed_by_user_id"] == "qr-001", (
        f"expected qr-001, got {complaint['filed_by_user_id']} from the acting X-User-ID"
    )
    assert complaint["reviewer_user_id"] is None, (
        f"expected null, got {complaint['reviewer_user_id']} before any review"
    )
    assert complaint["disposition"] is None, (
        f"expected null, got {complaint['disposition']} before any adjudication"
    )
    assert complaint["remand_count"] == 0, (
        f"expected 0, got {complaint['remand_count']} on intake"
    )

    assignment = validate_success(
        api.get_assignment(bundle["assignment"]["id"], COORDINATOR)
    )
    assert assignment["compliance_status"] == "UNDER_QUALITY_REVIEW", (
        f"expected UNDER_QUALITY_REVIEW, got {assignment['compliance_status']} after a "
        "complaint named this assignment"
    )
    assert assignment["service_status"] == "COMPLETED", (
        f"expected COMPLETED, got {assignment['service_status']} — a complaint moves "
        "only the compliance dimension"
    )

    holder = fixtures.read_interpreter(bundle["interpreter"]["id"])
    assert holder["roster_status"] == "ACTIVE", (
        f"expected ACTIVE, got {holder['roster_status']} — intake proves nothing"
    )
    assert holder["complaint_points"] == 0, (
        f"expected 0, got {holder['complaint_points']} on intake"
    )


def test_approval_refused_while_the_assignment_sits_under_quality_review(api):
    """PRD §3.8: "A `FiscalOfficer` then approves it, `SUBMITTED → APPROVED`, but only while the underlying assignment's `compliance_status` reads exactly `CLEAR`: an assignment `UNDER_QUALITY_REVIEW` or carrying a `SUBSTANTIATED_DEFECT` holds the money, and approval is refused with `ERR_QUALITY_REVIEW_OPEN`."
    PRD §3.9: "When an `assignment_id` is present, however, the named assignment's `compliance_status` moves `CLEAR → UNDER_QUALITY_REVIEW`, which immediately freezes fiscal approval of that assignment's pay claim."

    Design: Difficulty/cross_entity_state_dependency/fiscal_approval_gated_on_assignment_compliance_dimension_then_released_by_dismissal
    """
    bundle, _complaint = _setup_submitted_claim_under_review()
    claim = bundle["pay_claim"]
    assert claim["status"] == "SUBMITTED", (
        f"expected SUBMITTED, got {claim['status']} before the approval attempt"
    )

    response = api.approve_pay_claim(claim["id"], FISCAL)
    validate_error(response, ApiErrorId.ERR_QUALITY_REVIEW_OPEN)

    after = fixtures.read_pay_claim(claim["id"])
    assert after["status"] == "SUBMITTED", (
        f"expected SUBMITTED, got {after['status']} — the frozen claim must not advance"
    )
    assert after["version"] == claim["version"], (
        f"expected version {claim['version']}, got {after['version']} — a refused "
        "approval increments nothing"
    )

    assignment = fixtures.read_assignment(bundle["assignment"]["id"])
    assert assignment["compliance_status"] == "UNDER_QUALITY_REVIEW", (
        f"expected UNDER_QUALITY_REVIEW, got {assignment['compliance_status']} after "
        "the refused approval"
    )


def test_dismissal_returns_the_assignment_to_clear_without_touching_the_service_dimension(api):
    """PRD §3.9: "The reviewer supplies a `recommendation` of `SUBSTANTIATE` or `DISMISS` and written `findings`; the service records `reviewer_user_id` from the caller's `X-User-ID` and copies the recommendation into `reviewer_recommendation`."
    PRD §3.9: "Both branches record `adjudicator_user_id` from the caller's `X-User-ID` and `adjudicated_at` from the logical clock, which starts the appeal window; both set `disposition` to match; and both increment the complaint's `version` by 1."
    PRD §3.9: "A dismissal is the quiet branch: `REVIEWED → DISMISSED`, no disciplinary action is created, and the interpreter's `complaint_points` is unchanged."
    PRD §3.9: "If the complaint named an assignment, that assignment's `compliance_status` returns `UNDER_QUALITY_REVIEW → CLEAR` — but only when no *other* complaint against that same assignment is still in `FILED`, `REVIEWED`, or `APPEALED`, because one dismissal does not clear a second open file."
    PRD §3.2: "Enrolment sets `roster_status` to `APPLICANT` and `ethics_training_status` to `NOT_STARTED`, and it initialises `complaint_points` to 0 with `rolling_12_month_score` and `lifetime_score` both at 100."

    Design: Difficulty/cross_entity_state_dependency/fiscal_approval_gated_on_assignment_compliance_dimension_then_released_by_dismissal
    """
    bundle, complaint = _setup_submitted_claim_under_review()

    reviewed = validate_success(
        api.review_complaint(
            complaint["id"],
            review_complaint_payload(
                recommendation="DISMISS",
                findings="The recording shows both terms rendered correctly.",
            ),
            make_quality_reviewer_headers("qr-002"),
        )
    )
    assert reviewed["status"] == "REVIEWED", (
        f"expected REVIEWED, got {reviewed['status']} after the reviewer acted"
    )
    assert reviewed["reviewer_user_id"] == "qr-002", (
        f"expected qr-002, got {reviewed['reviewer_user_id']} from the reviewer's "
        "X-User-ID"
    )
    assert reviewed["reviewer_recommendation"] == "DISMISS", (
        f"expected DISMISS, got {reviewed['reviewer_recommendation']} copied from the "
        "supplied recommendation"
    )

    adjudicated = validate_success(
        api.adjudicate_complaint(
            complaint["id"],
            adjudicate_complaint_payload("DISMISSED"),
            make_program_admin_headers("pa-001"),
        )
    )
    assert adjudicated["status"] == "DISMISSED", (
        f"expected DISMISSED, got {adjudicated['status']} on the quiet branch"
    )
    assert adjudicated["disposition"] == "DISMISSED", (
        f"expected DISMISSED, got {adjudicated['disposition']} — disposition matches "
        "the adjudicated branch"
    )
    assert adjudicated["adjudicator_user_id"] == "pa-001", (
        f"expected pa-001, got {adjudicated['adjudicator_user_id']} from the "
        "administrator's X-User-ID"
    )

    actions, meta = validate_paginated(
        api.list_disciplinary_actions(ADMIN, params={"complaint_id": complaint["id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected 0, got {meta['total_count']} — a dismissal creates no disciplinary "
        f"action (rows: {actions})"
    )

    assignment = fixtures.read_assignment(bundle["assignment"]["id"])
    assert assignment["compliance_status"] == "CLEAR", (
        f"expected CLEAR, got {assignment['compliance_status']} after the only "
        "complaint against this assignment was dismissed"
    )
    assert assignment["service_status"] == "COMPLETED", (
        f"expected COMPLETED, got {assignment['service_status']} — the dismissal does "
        "not touch the service dimension"
    )

    holder = fixtures.read_interpreter(bundle["interpreter"]["id"])
    assert holder["complaint_points"] == 0, (
        f"expected 0, got {holder['complaint_points']} after a dismissal"
    )
    assert holder["rolling_12_month_score"] == 100, (
        f"expected 100, got {holder['rolling_12_month_score']} after a dismissal"
    )
    assert holder["lifetime_score"] == 100, (
        f"expected 100, got {holder['lifetime_score']} after a dismissal"
    )


def test_approval_succeeds_once_the_dismissal_has_cleared_the_compliance_hold(api):
    """PRD §3.8: "A `FiscalOfficer` then approves it, `SUBMITTED → APPROVED`, but only while the underlying assignment's `compliance_status` reads exactly `CLEAR`: an assignment `UNDER_QUALITY_REVIEW` or carrying a `SUBSTANTIATED_DEFECT` holds the money, and approval is refused with `ERR_QUALITY_REVIEW_OPEN`."
    PRD §3.8: "Each of the three transitions increments the claim's `version` by 1."
    PRD §2.9: "`obligated_pay_cents` is the sum of `final_total_cents` over every pay claim whose `status` is one of `FINALIZED`, `SUBMITTED`, `APPROVED`, or `PAID`, reached through the same assignment-to-hearing-to-courthouse path."
    PRD §2.9: "`encumbered_pay_cents` is the sum of `provisional_total_cents` over every pay claim whose `status` is `ENCUMBERED` and whose assignment's hearing sits at this courthouse."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less `obligated_pay_cents`."

    Design: Difficulty/cross_entity_state_dependency/fiscal_approval_gated_on_assignment_compliance_dimension_then_released_by_dismissal
    """
    bundle, complaint = _setup_submitted_claim_under_review()
    claim = bundle["pay_claim"]

    validate_error(
        api.approve_pay_claim(claim["id"], FISCAL),
        ApiErrorId.ERR_QUALITY_REVIEW_OPEN,
    )

    fixtures.review_complaint(
        complaint["id"], recommendation="DISMISS",
        findings="The recording shows both terms rendered correctly.",
        reviewer_user_id="qr-002",
    )
    fixtures.adjudicate_complaint(
        complaint["id"], disposition="DISMISSED", adjudicator_user_id="pa-001"
    )
    released = fixtures.read_assignment(bundle["assignment"]["id"])
    assert released["compliance_status"] == "CLEAR", (
        f"expected CLEAR, got {released['compliance_status']} before the second "
        "approval attempt"
    )

    approved = validate_success(api.approve_pay_claim(claim["id"], FISCAL))
    assert approved["status"] == "APPROVED", (
        f"expected APPROVED, got {approved['status']} once compliance_status read CLEAR"
    )
    assert approved["version"] == claim["version"] + 1, (
        f"expected version {claim['version'] + 1}, got {approved['version']} after the "
        "accepted approval"
    )

    courthouse = fixtures.read_courthouse(bundle["courthouse"]["id"])
    assert courthouse["encumbered_pay_cents"] == 0, (
        f"expected 0, got {courthouse['encumbered_pay_cents']} — no claim at this "
        "courthouse is still ENCUMBERED"
    )
    assert courthouse["obligated_pay_cents"] == approved["final_total_cents"], (
        f"expected {approved['final_total_cents']}, got "
        f"{courthouse['obligated_pay_cents']} for the single APPROVED claim"
    )
    assert courthouse["available_pay_cents"] == (
        courthouse["pay_budget_cents"]
        - courthouse["encumbered_pay_cents"]
        - courthouse["obligated_pay_cents"]
    ), (
        f"expected {courthouse['pay_budget_cents'] - courthouse['encumbered_pay_cents'] - courthouse['obligated_pay_cents']}, "
        f"got {courthouse['available_pay_cents']} for budget less encumbered less obligated"
    )
