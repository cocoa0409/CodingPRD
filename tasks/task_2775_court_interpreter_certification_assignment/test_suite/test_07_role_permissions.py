"""Role authority, shared operations and segregation of duties (PRD §2.1, §2.10, §2.12, §4).

Every expectation here is grounded in the endpoint/role authority table of PRD §4
and the role prose of §2.1: an operation a role does not own is refused with
`ERR_UNAUTHORIZED` (403), an `Interpreter` acting on someone else's resource is
refused with `ERR_NOT_RESOURCE_OWNER` (403), and a caller who would review their
own filing or decide their own adjudication is refused with
`ERR_SEGREGATION_OF_DUTIES` (409).
"""

import pytest

import test_helpers.fixtures as fixtures
from test_helpers import (
    PROGRAM_ADMIN_USER_ID,
    QUALITY_REVIEWER_ALT_USER_ID,
    QUALITY_REVIEWER_USER_ID,
    SCHEDULING_COORDINATOR_USER_ID,
    TEST_USERS,
    adjudicate_complaint_payload,
    appeal_decision_payload,
    complete_assignment_payload,
    create_assignment_payload,
    create_complaint_payload,
    create_credential_payload,
    create_hearing_payload,
    create_interpreter_payload,
    create_unmet_need_report_payload,
    ethics_training_payload,
    exam_attempt_payload,
    make_interpreter_headers,
    pay_pay_claim_payload,
    renew_credential_payload,
    review_complaint_payload,
    revoke_credential_payload,
    set_clock_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
CREDENTIALING = TEST_USERS["credentialing_officer_headers"]
COORDINATOR = TEST_USERS["scheduling_coordinator_headers"]
FISCAL = TEST_USERS["fiscal_officer_headers"]
REVIEWER = TEST_USERS["quality_reviewer_headers"]
REVIEWER_ALT = TEST_USERS["quality_reviewer_alt_headers"]


# ---------------------------------------------------------------------------
# Corner/RBAC/every_role_runs_its_own_exclusive_operations_along_one_end_to_end_case
# ---------------------------------------------------------------------------
def test_coordinator_interpreter_and_fiscal_officer_each_run_their_own_leg_of_one_case(api):
    """PRD §2.1: "A `SchedulingCoordinator` works the case calendar: creating hearings, continuing them, pulling the ranked eligible-interpreter pool, proposing assignments, cancelling them, and recording no-shows."
    PRD §2.1: "An `Interpreter` acts only for themselves: accepting, declining, checking in to and completing their own assignments, submitting their own pay claims, and appealing a substantiated complaint against them."
    PRD §2.1: "A `FiscalOfficer` approves and pays interpreter claims and does nothing else that mutates state."
    PRD §3.8: "The `Interpreter` who served the assignment submits their own claim, `FINALIZED → SUBMITTED`."
    PRD §3.8: "Finally the same `FiscalOfficer` role issues the warrant, `APPROVED → PAID`, supplying a `payment_reference` that is recorded on the claim; that transition moves `final_total_cents` out of the interpreter's `pending_pay_cents` and into their `paid_pay_cents`."

    Design: Corner/RBAC/every_role_runs_its_own_exclusive_operations_along_one_end_to_end_case
    """
    config = fixtures.setup_program_config()
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    interpreter = bundle["interpreter"]
    owner = make_interpreter_headers(interpreter["id"])

    hearing = validate_success(
        api.create_hearing(
            create_hearing_payload(
                config["courthouse"]["id"],
                config["language"]["id"],
                case_number="CR-2026-5001",
                hearing_type="PLEA",
            ),
            COORDINATOR,
        ),
        201,
    )
    assignment = validate_success(
        api.create_assignment(
            create_assignment_payload(
                hearing["id"], hearing["version"], interpreter["id"]
            ),
            COORDINATOR,
        ),
        201,
    )
    assert assignment["service_status"] == "PROPOSED", (
        f"expected PROPOSED, got {assignment['service_status']} after the coordinator proposed"
    )

    confirmed = validate_success(api.confirm_assignment(assignment["id"], owner))
    assert confirmed["service_status"] == "CONFIRMED", (
        f"expected CONFIRMED, got {confirmed['service_status']} after the interpreter accepted"
    )

    claims, meta = validate_paginated(
        api.list_pay_claims(FISCAL, params={"assignment_id": assignment["id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected 1 claim visible to the fiscal officer, got {meta['total_count']}"
    )
    claim = claims[0]
    assert claim["status"] == "ENCUMBERED", (
        f"expected ENCUMBERED, got {claim['status']} on the provisional claim"
    )

    validate_success(api.set_clock(set_clock_payload("2026-09-10T09:00:00.000Z"), ADMIN))

    checked_in = validate_success(api.check_in_assignment(assignment["id"], owner))
    assert checked_in["service_status"] == "CHECKED_IN", (
        f"expected CHECKED_IN, got {checked_in['service_status']} after the interpreter checked in"
    )
    completed = validate_success(
        api.complete_assignment(
            assignment["id"],
            complete_assignment_payload("2026-09-10T10:30:00.000Z"),
            owner,
        )
    )
    assert completed["service_status"] == "COMPLETED", (
        f"expected COMPLETED, got {completed['service_status']} after the interpreter completed"
    )

    submitted = validate_success(api.submit_pay_claim(claim["id"], owner))
    assert submitted["status"] == "SUBMITTED", (
        f"expected SUBMITTED, got {submitted['status']} after the interpreter submitted"
    )
    approved = validate_success(api.approve_pay_claim(claim["id"], FISCAL))
    assert approved["status"] == "APPROVED", (
        f"expected APPROVED, got {approved['status']} after the fiscal officer approved"
    )
    paid = validate_success(
        api.pay_pay_claim(claim["id"], pay_pay_claim_payload("WARRANT-2026-0091"), FISCAL)
    )
    assert paid["status"] == "PAID", (
        f"expected PAID, got {paid['status']} after the fiscal officer issued the warrant"
    )
    assert paid["payment_reference"] == "WARRANT-2026-0091", (
        f"expected the supplied warrant reference, got {paid['payment_reference']}"
    )


def test_the_credentialing_officer_alone_runs_the_pipeline_and_the_renewal(api):
    """PRD §2.1: "A `CredentialingOfficer` runs the credentialing pipeline: opening credential applications, recording examination attempts, advancing a credential through its stages, and renewing a cycle."
    PRD §3.3: "The target tier is fixed at creation and never changes; the separate field `tier` stays null until the credential is activated and then mirrors `target_tier` for as long as the credential remains active, reverting to null if it lapses or is revoked."
    PRD §3.4: "Renewal is how a credential earns another cycle, and a `CredentialingOfficer` performs it by submitting `cycle_credit_hours`, the continuing-education hours completed for the cycle just ending."
    PRD §3.4: "Renewing a credential that is still `ACTIVE` is a self-loop, `ACTIVE → ACTIVE`: because the clock has not yet passed `expires_on`, the extension is measured from the existing `expires_on`, so an early renewer neither gains nor loses days and their cycle boundary simply slides forward by one full cycle."

    Design: Corner/RBAC/every_role_runs_its_own_exclusive_operations_along_one_end_to_end_case
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)

    interpreter = validate_success(
        api.create_interpreter(create_interpreter_payload(), CREDENTIALING), 201
    )
    trained = validate_success(
        api.record_ethics_training(
            interpreter["id"], ethics_training_payload(), CREDENTIALING
        )
    )
    assert trained["ethics_training_status"] == "COMPLETED", (
        f"expected COMPLETED, got {trained['ethics_training_status']} after the officer recorded ethics"
    )

    credential = validate_success(
        api.create_credential(
            create_credential_payload(
                interpreter["id"], config["language"]["id"], trained["version"]
            ),
            CREDENTIALING,
        ),
        201,
    )
    assert credential["status"] == "PENDING_WRITTEN", (
        f"expected PENDING_WRITTEN, got {credential['status']} on the opened application"
    )
    assert credential["tier"] is None, (
        f"expected tier null before activation, got {credential['tier']}"
    )

    validate_success(
        api.create_exam_attempt(
            credential["id"],
            exam_attempt_payload("WRITTEN", 86, "2026-08-01"),
            CREDENTIALING,
        ),
        201,
    )
    after_written = validate_success(
        api.advance_credential(credential["id"], CREDENTIALING)
    )
    assert after_written["status"] == "PENDING_ORAL", (
        f"expected PENDING_ORAL, got {after_written['status']} after the written advance"
    )

    validate_success(
        api.create_exam_attempt(
            credential["id"],
            exam_attempt_payload("ORAL", 74, "2026-08-01"),
            CREDENTIALING,
        ),
        201,
    )
    after_oral = validate_success(api.advance_credential(credential["id"], CREDENTIALING))
    assert after_oral["status"] == "PENDING_ETHICS", (
        f"expected PENDING_ETHICS, got {after_oral['status']} after the oral advance"
    )

    activated = validate_success(api.advance_credential(credential["id"], CREDENTIALING))
    assert activated["status"] == "ACTIVE", (
        f"expected ACTIVE, got {activated['status']} after the final advance"
    )
    assert activated["tier"] == "CERTIFIED", (
        f"expected tier CERTIFIED to mirror target_tier, got {activated['tier']}"
    )

    renewed = validate_success(
        api.renew_credential(
            credential["id"], renew_credential_payload(20.0), CREDENTIALING
        )
    )
    assert renewed["status"] == "ACTIVE", (
        f"expected the ACTIVE self-loop, got {renewed['status']} after renewal"
    )
    assert renewed["renewal_count"] == 1, (
        f"expected renewal_count 1, got {renewed['renewal_count']}"
    )
    assert renewed["cycle_credit_hours"] == pytest.approx(20.0), (
        f"expected the submitted 20.0 credit hours, got {renewed['cycle_credit_hours']}"
    )


def test_the_quality_reviewer_reviews_and_only_the_program_admin_adjudicates(api):
    """PRD §2.1: "A `QualityReviewer` reviews complaints, files new ones, and pulls language-access compliance reports."
    PRD §3.9: "Review is a `QualityReviewer`'s exclusive act, `FILED → REVIEWED`."
    PRD §3.9: "Adjudication belongs to a `ProgramAdmin` and to nobody else — not to the reviewer whose recommendation it weighs."
    PRD §3.9: "A dismissal is the quiet branch: `REVIEWED → DISMISSED`, no disciplinary action is created, and the interpreter's `complaint_points` is unchanged."

    Design: Corner/RBAC/every_role_runs_its_own_exclusive_operations_along_one_end_to_end_case
    """
    fixtures.set_clock()
    interpreter = fixtures.enrol_interpreter()

    complaint = validate_success(
        api.create_complaint(
            create_complaint_payload(
                interpreter["id"],
                category="PROFESSIONALISM",
                severity="MINOR",
                narrative="Counsel reports the interpreter arrived without a court badge.",
            ),
            REVIEWER,
        ),
        201,
    )
    assert complaint["status"] == "FILED", (
        f"expected FILED, got {complaint['status']} on intake"
    )
    assert complaint["filed_by_user_id"] == QUALITY_REVIEWER_USER_ID, (
        f"expected filer {QUALITY_REVIEWER_USER_ID}, got {complaint['filed_by_user_id']}"
    )

    reviewed = validate_success(
        api.review_complaint(
            complaint["id"],
            review_complaint_payload(
                "DISMISS", "The badge was reissued by court security the same morning."
            ),
            REVIEWER_ALT,
        )
    )
    assert reviewed["status"] == "REVIEWED", (
        f"expected REVIEWED, got {reviewed['status']} after the reviewer acted"
    )
    assert reviewed["reviewer_user_id"] == QUALITY_REVIEWER_ALT_USER_ID, (
        f"expected reviewer {QUALITY_REVIEWER_ALT_USER_ID}, got {reviewed['reviewer_user_id']}"
    )
    assert reviewed["reviewer_recommendation"] == "DISMISS", (
        f"expected DISMISS, got {reviewed['reviewer_recommendation']}"
    )

    adjudicated = validate_success(
        api.adjudicate_complaint(
            complaint["id"], adjudicate_complaint_payload("DISMISSED"), ADMIN
        )
    )
    assert adjudicated["status"] == "DISMISSED", (
        f"expected DISMISSED, got {adjudicated['status']} after adjudication"
    )
    assert adjudicated["disposition"] == "DISMISSED", (
        f"expected disposition DISMISSED, got {adjudicated['disposition']}"
    )
    assert adjudicated["adjudicator_user_id"] == PROGRAM_ADMIN_USER_ID, (
        f"expected adjudicator {PROGRAM_ADMIN_USER_ID}, got {adjudicated['adjudicator_user_id']}"
    )


def test_only_the_program_admin_revokes_a_credential_and_drives_the_operations_endpoints(api):
    """PRD §3.4: "Revocation is the terminal exit, available only to a `ProgramAdmin` and accompanied by a written `reason`."
    PRD §3.4: "It may be applied to a credential in any of `PENDING_WRITTEN`, `PENDING_ORAL`, `PENDING_ETHICS`, `ACTIVE`, or `LAPSED`, and it sets `status` to `REVOKED` and clears `tier` to null."
    PRD §3.2: "`ACTIVE → INACTIVE` happens the moment the interpreter's last activated credential stops being activated, which requires that the count of their credentials in `ACTIVE` status has fallen to zero; that transition also sets `credential_tier` to `NONE` and empties `credentialed_language_ids` to an empty list."
    PRD §3.10: "The daily operations run is a `ProgramAdmin`-only capability that advances every clock-driven consequence in the program to the current logical time, and its three steps run in a fixed order because the later steps depend on what the earlier ones did."
    PRD §3.10: "Its response carries `swept_at`, the logical-clock instant the run executed, together with six identifier arrays: `lapsed_credential_ids`, `downgraded_interpreter_ids`, `expired_action_ids`, `reinstated_interpreter_ids`, `unmet_hearing_ids`, `cancelled_assignment_ids`, and `voided_pay_claim_ids`."
    PRD §3.10: "The logical clock itself is set by an administrator-only test-driving capability that takes the target instant as `to_iso8601` and answers with the resulting `current_utc`."

    Design: Corner/RBAC/every_role_runs_its_own_exclusive_operations_along_one_end_to_end_case
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])

    revoked = validate_success(
        api.revoke_credential(
            bundle["credential"]["id"],
            revoke_credential_payload(
                "Holder relinquished the credential on relocating out of state."
            ),
            ADMIN,
        )
    )
    assert revoked["status"] == "REVOKED", (
        f"expected REVOKED, got {revoked['status']} after the administrator revoked"
    )
    assert revoked["tier"] is None, (
        f"expected tier cleared to null, got {revoked['tier']}"
    )

    holder = validate_success(api.get_interpreter(bundle["interpreter"]["id"], ADMIN))
    assert holder["roster_status"] == "INACTIVE", (
        f"expected INACTIVE, got {holder['roster_status']} after the last credential was revoked"
    )
    assert holder["credential_tier"] == "NONE", (
        f"expected credential_tier NONE, got {holder['credential_tier']}"
    )
    assert holder["credentialed_language_ids"] == [], (
        f"expected an empty language list, got {holder['credentialed_language_ids']}"
    )

    clock = validate_success(
        api.set_clock(set_clock_payload("2026-09-01T00:00:00.000Z"), ADMIN)
    )
    assert "current_utc" in clock, (
        f"expected the clock response to carry current_utc, got keys {sorted(clock)}"
    )

    sweep = validate_success(api.run_daily_sweep(ADMIN))
    for field in (
        "lapsed_credential_ids",
        "downgraded_interpreter_ids",
        "expired_action_ids",
        "reinstated_interpreter_ids",
        "unmet_hearing_ids",
        "cancelled_assignment_ids",
        "voided_pay_claim_ids",
    ):
        assert sweep[field] == [], (
            f"expected {field} empty when the sweep had nothing to do, got {sweep[field]}"
        )
    assert "swept_at" in sweep, (
        f"expected the sweep response to carry swept_at, got keys {sorted(sweep)}"
    )


# ---------------------------------------------------------------------------
# Corner/RBAC/shared_operations_are_accepted_from_each_of_the_roles_that_declare_them
# ---------------------------------------------------------------------------
def test_roster_enrolment_and_ethics_recording_accept_both_declared_roles(api):
    """PRD §2.1: "It also shares roster enrolment and ethics recording with `CredentialingOfficer`, calendar and assignment work with `SchedulingCoordinator`, complaint intake with `QualityReviewer` and `SchedulingCoordinator`, compliance reporting with `QualityReviewer`, and it may perform every read in the system."
    PRD §3.2: "Enrolment sets `roster_status` to `APPLICANT` and `ethics_training_status` to `NOT_STARTED`, and it initialises `complaint_points` to 0 with `rolling_12_month_score` and `lifetime_score` both at 100."
    PRD §3.2: "A `CredentialingOfficer` or `ProgramAdmin` records completion by supplying the `completed_on` date and the `provider` that delivered the course; the service sets `ethics_training_status` to `COMPLETED`, copies the supplied date into `ethics_completed_on`, and increments the interpreter's `version` by 1."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` is true exactly when rows remain beyond the current page."

    Design: Corner/RBAC/shared_operations_are_accepted_from_each_of_the_roles_that_declare_them
    """
    fixtures.set_clock()

    by_admin = validate_success(
        api.create_interpreter(create_interpreter_payload(), ADMIN), 201
    )
    assert by_admin["roster_status"] == "APPLICANT", (
        f"expected APPLICANT, got {by_admin['roster_status']} on the administrator's enrolment"
    )
    assert by_admin["ethics_training_status"] == "NOT_STARTED", (
        f"expected NOT_STARTED, got {by_admin['ethics_training_status']} on enrolment"
    )

    by_officer = validate_success(
        api.create_interpreter(
            create_interpreter_payload(
                full_name="Beto Cruz",
                email="beto.cruz@courts.example.gov",
                home_county_code="DEL",
            ),
            CREDENTIALING,
        ),
        201,
    )
    assert by_officer["roster_status"] == "APPLICANT", (
        f"expected APPLICANT, got {by_officer['roster_status']} on the officer's enrolment"
    )

    trained_by_admin = validate_success(
        api.record_ethics_training(by_admin["id"], ethics_training_payload(), ADMIN)
    )
    assert trained_by_admin["ethics_training_status"] == "COMPLETED", (
        f"expected COMPLETED, got {trained_by_admin['ethics_training_status']}"
    )
    assert trained_by_admin["ethics_completed_on"] == "2026-08-01", (
        f"expected the supplied completion date, got {trained_by_admin['ethics_completed_on']}"
    )

    trained_by_officer = validate_success(
        api.record_ethics_training(
            by_officer["id"], ethics_training_payload(), CREDENTIALING
        )
    )
    assert trained_by_officer["ethics_training_status"] == "COMPLETED", (
        f"expected COMPLETED, got {trained_by_officer['ethics_training_status']}"
    )

    rows, meta = validate_paginated(api.list_interpreters(ADMIN))
    assert meta["total_count"] == 2, (
        f"expected both enrolments on the roster, got total_count {meta['total_count']}"
    )
    assert len(rows) == 2, f"expected 2 rows, got {len(rows)}"


def test_complaint_intake_accepts_each_of_its_three_declared_roles(api):
    """PRD §3.9: "Intake is open to a `QualityReviewer`, a `SchedulingCoordinator`, or a `ProgramAdmin`, who names the `interpreter_id` complained about, optionally an `assignment_id` when the complaint concerns a specific appearance rather than the interpreter's conduct generally, a `category` of `ACCURACY`, `ETHICS`, `PROFESSIONALISM`, or `NO_SHOW`, a `severity` of `MINOR`, `MAJOR`, or `SEVERE`, and a `narrative` describing what happened."
    PRD §3.9: "Filing sets `status` to `FILED`, records `filed_by_user_id` from the acting `X-User-ID`, and leaves `reviewer_user_id`, `reviewer_recommendation`, `adjudicator_user_id`, `disposition`, `adjudicated_at` and `appeal_filed_at` all null with `remand_count` at 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` is true exactly when rows remain beyond the current page."

    Design: Corner/RBAC/shared_operations_are_accepted_from_each_of_the_roles_that_declare_them
    """
    fixtures.set_clock()
    interpreter = fixtures.enrol_interpreter()

    filings = {}
    for label, headers, expected_filer in (
        ("coordinator", COORDINATOR, SCHEDULING_COORDINATOR_USER_ID),
        ("reviewer", REVIEWER, QUALITY_REVIEWER_USER_ID),
        ("administrator", ADMIN, PROGRAM_ADMIN_USER_ID),
    ):
        filed = validate_success(
            api.create_complaint(
                create_complaint_payload(
                    interpreter["id"],
                    category="PROFESSIONALISM",
                    severity="MINOR",
                    narrative=f"Intake taken at the {label} desk.",
                ),
                headers,
            ),
            201,
        )
        assert filed["status"] == "FILED", (
            f"expected FILED for the {label} filing, got {filed['status']}"
        )
        assert filed["filed_by_user_id"] == expected_filer, (
            f"expected filer {expected_filer} for the {label} filing, got {filed['filed_by_user_id']}"
        )
        assert filed["reviewer_user_id"] is None, (
            f"expected reviewer_user_id null on intake, got {filed['reviewer_user_id']}"
        )
        assert filed["remand_count"] == 0, (
            f"expected remand_count 0 on intake, got {filed['remand_count']}"
        )
        filings[label] = filed["id"]

    assert len(set(filings.values())) == 3, (
        f"expected three distinct complaints, got {filings}"
    )
    rows, meta = validate_paginated(api.list_complaints(ADMIN))
    assert meta["total_count"] == 3, (
        f"expected all three filings persisted, got total_count {meta['total_count']}"
    )
    assert len(rows) == 3, f"expected 3 rows, got {len(rows)}"


def test_confirm_and_complete_accept_the_coordinator_as_well_as_the_interpreter(api):
    """PRD §3.7: "Acceptance is `PROPOSED → CONFIRMED`, and either the named `Interpreter` or a `SchedulingCoordinator` may perform it."
    PRD §3.7: "Completion closes out served interpretation and may be performed by the interpreter or by a `SchedulingCoordinator`."
    PRD §3.7: "For a rostered interpreter, completion also settles the money: the pay claim moves `ENCUMBERED → FINALIZED` with `variant` set to `FINAL` and `final_total_cents` computed by the final arithmetic of §3.8, the courthouse's `encumbered_pay_cents`, `obligated_pay_cents` and `available_pay_cents` are all recomputed, and the interpreter's `pending_pay_cents` is recomputed to include the newly finalized amount."
    PRD §3.8: "Then take the larger of that rounded figure and the rate schedule's `minimum_call_hours`; the result is `billable_hours`, always a multiple of 0.25 and always carried to two decimal places."
    PRD §3.8: "Multiply `billable_hours` by the selected hourly rate and then by the multiplier, and round the product to whole cents half up; that is `service_cents`."
    PRD §3.8: "For any language that is not `RARE`, `rare_premium_cents` is 0."
    PRD §3.8: "If the assignment's `delivery_mode` is anything other than `IN_PERSON`, or if the variant's one-way mileage is at or below the schedule's `travel_free_radius_miles`, the reimbursable mileage is 0."
    PRD §3.8: "Add the three already-rounded components — `service_cents`, `rare_premium_cents`, and `travel_cents` — to obtain the total."

    Design: Corner/RBAC/shared_operations_are_accepted_from_each_of_the_roles_that_declare_them
    """
    config = fixtures.setup_program_config()
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    interpreter = bundle["interpreter"]
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"], config["language"]["id"]
    )
    assignment = fixtures.propose_assignment(hearing["id"], interpreter["id"])

    confirmed = validate_success(api.confirm_assignment(assignment["id"], COORDINATOR))
    assert confirmed["service_status"] == "CONFIRMED", (
        f"expected CONFIRMED, got {confirmed['service_status']} after the coordinator accepted"
    )

    fixtures.set_clock("2026-09-10T09:00:00.000Z")
    fixtures.check_in_assignment(assignment["id"], interpreter["id"])

    completed = validate_success(
        api.complete_assignment(
            assignment["id"],
            complete_assignment_payload("2026-09-10T10:30:00.000Z"),
            COORDINATOR,
        )
    )
    assert completed["service_status"] == "COMPLETED", (
        f"expected COMPLETED, got {completed['service_status']} after the coordinator closed out"
    )

    claim = fixtures.pay_claim_for_assignment(assignment["id"])
    assert claim["status"] == "FINALIZED", (
        f"expected FINALIZED, got {claim['status']} after completion settled the money"
    )
    assert claim["variant"] == "FINAL", (
        f"expected variant FINAL, got {claim['variant']}"
    )
    assert claim["billable_hours"] == pytest.approx(2.0), (
        f"expected the 2.0 minimum-call floor, got {claim['billable_hours']}"
    )
    assert claim["service_cents"] == 17500, (
        f"expected 17500 service cents, got {claim['service_cents']}"
    )
    assert claim["rare_premium_cents"] == 0, (
        f"expected no rare premium on a designated language, got {claim['rare_premium_cents']}"
    )
    assert claim["travel_cents"] == 0, (
        f"expected no travel inside the free radius, got {claim['travel_cents']}"
    )
    assert claim["final_total_cents"] == 17500, (
        f"expected 17500 final cents, got {claim['final_total_cents']}"
    )


def test_calendar_writes_and_compliance_reporting_accept_their_second_declared_role(api):
    """PRD §3.5: "A `SchedulingCoordinator` or `ProgramAdmin` places one on a courthouse calendar by supplying `courthouse_id`, the `language_id` the hearing needs, the court's `case_number`, the `hearing_type`, an `in_custody` flag that is true when the limited-English party is held in custody, the `scheduled_start` and `scheduled_end` instants as ISO 8601 UTC timestamps with three fractional digits, and the `requested_delivery_mode` the calendar is asking for — `IN_PERSON`, `VRI`, or `TELEPHONIC`."
    PRD §3.5: "Creation sets `status` to `SCHEDULED` and `continuance_count` to 0, and leaves `continuance_reason_code` null."
    PRD §3.6: "Creating the assignment itself is a coordinator or administrator action carrying `hearing_id`, the `expected_hearing_version` pin from §2.7, the `delivery_mode` that will actually be used, an optional `interpreter_id`, an optional `vendor_served` flag defaulting to false, and an optional `estimated_one_way_miles` defaulting to 0 that will drive the provisional travel reimbursement."
    PRD §3.10: "A `ProgramAdmin` or `QualityReviewer` produces a report by naming the `courthouse_id` and the reporting window's `period_start` and `period_end`, both plain `YYYY-MM-DD` dates."
    PRD §3.10: "When `resolved_hearing_count` is 0 the division is undefined, and the program pins the convention: `coverage_rate_pct` is exactly 100.00 for an empty pool."
    PRD §3.10: "Otherwise the verdict is `COMPLIANT`."

    Design: Corner/RBAC/shared_operations_are_accepted_from_each_of_the_roles_that_declare_them
    """
    config = fixtures.setup_program_config()
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])

    hearing = validate_success(
        api.create_hearing(
            create_hearing_payload(
                config["courthouse"]["id"],
                config["language"]["id"],
                case_number="CR-2026-6001",
                hearing_type="PLEA",
            ),
            ADMIN,
        ),
        201,
    )
    assert hearing["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {hearing['status']} on the administrator's hearing"
    )
    assert hearing["continuance_count"] == 0, (
        f"expected continuance_count 0, got {hearing['continuance_count']}"
    )

    assignment = validate_success(
        api.create_assignment(
            create_assignment_payload(
                hearing["id"], hearing["version"], bundle["interpreter"]["id"]
            ),
            ADMIN,
        ),
        201,
    )
    assert assignment["service_status"] == "PROPOSED", (
        f"expected PROPOSED, got {assignment['service_status']} on the administrator's proposal"
    )

    fixtures.set_clock("2026-09-15T00:00:00.000Z")
    report = validate_success(
        api.create_unmet_need_report(
            create_unmet_need_report_payload(
                config["courthouse"]["id"], "2026-08-01", "2026-09-01"
            ),
            REVIEWER,
        ),
        201,
    )
    assert report["resolved_hearing_count"] == 0, (
        f"expected an empty pool, got {report['resolved_hearing_count']} resolved hearings"
    )
    assert report["coverage_rate_pct"] == pytest.approx(100.00, abs=0.01), (
        f"expected 100.00 for an empty pool, got {report['coverage_rate_pct']}"
    )
    assert report["compliance_status"] == "COMPLIANT", (
        f"expected COMPLIANT, got {report['compliance_status']}"
    )


# ---------------------------------------------------------------------------
# Corner/RBAC/another_roles_exclusive_operation_is_forbidden_for_everyone_including_the_program_admin
# ---------------------------------------------------------------------------
def _world_for_forbidden_operations():
    """Config, an ACTIVE credential, a CONFIRMED assignment with its ENCUMBERED
    claim, and one FILED complaint — the live state each denial is aimed at."""
    world = fixtures.setup_confirmed_assignment()
    world["complaint"] = fixtures.file_complaint(
        world["interpreter"]["id"],
        category="ACCURACY",
        severity="MAJOR",
        narrative="Defence counsel questions the rendition of two key terms.",
    )
    return world


FORBIDDEN_OPERATIONS = [
    pytest.param(
        lambda api, w: api.create_assignment(
            create_assignment_payload(
                w["hearing"]["id"], w["hearing"]["version"], w["interpreter"]["id"]
            ),
            CREDENTIALING,
        ),
        id="post_assignments_as_credentialing_officer",
    ),
    pytest.param(
        lambda api, w: api.create_credential(
            create_credential_payload(
                w["interpreter"]["id"],
                w["language"]["id"],
                w["interpreter"]["version"],
                "MASTER",
            ),
            COORDINATOR,
        ),
        id="post_credentials_as_scheduling_coordinator",
    ),
    pytest.param(
        lambda api, w: api.renew_credential(
            w["credential"]["id"], renew_credential_payload(20.0), ADMIN
        ),
        id="renew_credential_as_program_admin",
    ),
    pytest.param(
        lambda api, w: api.check_in_assignment(w["assignment"]["id"], ADMIN),
        id="check_in_assignment_as_program_admin",
    ),
    pytest.param(
        lambda api, w: api.approve_pay_claim(
            w["pay_claim"]["id"], make_interpreter_headers(w["interpreter"]["id"])
        ),
        id="approve_pay_claim_as_interpreter",
    ),
    pytest.param(
        lambda api, w: api.review_complaint(
            w["complaint"]["id"], review_complaint_payload(), FISCAL
        ),
        id="review_complaint_as_fiscal_officer",
    ),
    pytest.param(
        lambda api, w: api.adjudicate_complaint(
            w["complaint"]["id"], adjudicate_complaint_payload("DISMISSED"), REVIEWER_ALT
        ),
        id="adjudicate_complaint_as_quality_reviewer",
    ),
    pytest.param(
        lambda api, w: api.create_hearing(
            create_hearing_payload(
                w["courthouse"]["id"],
                w["language"]["id"],
                case_number="CR-2026-7001",
                hearing_type="MOTION",
            ),
            make_interpreter_headers(w["interpreter"]["id"]),
        ),
        id="post_hearings_as_interpreter",
    ),
    pytest.param(
        lambda api, w: api.set_clock(
            set_clock_payload("2026-09-10T09:00:00.000Z"), COORDINATOR
        ),
        id="set_clock_as_scheduling_coordinator",
    ),
]


@pytest.mark.parametrize("operation", FORBIDDEN_OPERATIONS)
def test_another_roles_exclusive_operation_is_refused_with_err_unauthorized(api, operation):
    """PRD §2.1: "When the headers are well formed but the named role is not among the roles authorized for the requested endpoint (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.12: "Authorization: the acting role appears in the endpoint's authorized-role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

    Design: Corner/RBAC/another_roles_exclusive_operation_is_forbidden_for_everyone_including_the_program_admin
    """
    world = _world_for_forbidden_operations()
    validate_error(operation(api, world), "ERR_UNAUTHORIZED")


def test_check_in_denies_the_wrong_role_before_it_denies_the_wrong_owner(api):
    """PRD §2.12: "Authorization: the acting role appears in the endpoint's authorized-role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §2.12: "Interpreter-role ownership: an `Interpreter` caller's `X-User-ID` matches the target resource's interpreter — otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to `POST /assignments/{id}/confirm`, `POST /assignments/{id}/decline`, `POST /assignments/{id}/check-in`, `POST /assignments/{id}/complete`, `POST /pay-claims/{id}/submit`, and `POST /complaints/{id}/appeal`."
    PRD §3.7: "Checking in is the interpreter's own act and nobody else's, `CONFIRMED → CHECKED_IN`."

    Design: Corner/RBAC/another_roles_exclusive_operation_is_forbidden_for_everyone_including_the_program_admin
    """
    world = fixtures.setup_confirmed_assignment()
    stranger = fixtures.enrol_interpreter(
        full_name="Beto Cruz",
        email="beto.cruz@courts.example.gov",
        home_county_code="DEL",
    )

    validate_error(
        api.check_in_assignment(world["assignment"]["id"], ADMIN), "ERR_UNAUTHORIZED"
    )
    validate_error(
        api.check_in_assignment(
            world["assignment"]["id"], make_interpreter_headers(stranger["id"])
        ),
        "ERR_NOT_RESOURCE_OWNER",
    )

    unchanged = fixtures.read_assignment(world["assignment"]["id"])
    assert unchanged["service_status"] == "CONFIRMED", (
        f"expected CONFIRMED after both denials, got {unchanged['service_status']}"
    )
    assert unchanged["check_in_utc"] is None, (
        f"expected check_in_utc still null, got {unchanged['check_in_utc']}"
    )


def test_the_role_check_masks_the_complaint_state_check(api):
    """PRD §2.12: "The ladder is global — a check at a lower number always masks a check at a higher number — and it is the reason a request that is both unauthorized and malformed reports only the authorization failure."
    PRD §2.12: "Authorization: the acting role appears in the endpoint's authorized-role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §2.12: "Complaint `status` admits the requested transition — otherwise `ERR_INVALID_COMPLAINT_STATE` (409). Applies to `POST /complaints/{id}/review`, `POST /complaints/{id}/adjudicate`, `POST /complaints/{id}/appeal`, and `POST /complaints/{id}/appeal-decision`."
    PRD §2.1: "It may not adjudicate a complaint and may not decide an appeal; that separation is the core segregation of duties in the program."

    Design: Corner/RBAC/another_roles_exclusive_operation_is_forbidden_for_everyone_including_the_program_admin
    """
    fixtures.set_clock()
    interpreter = fixtures.enrol_interpreter()
    complaint = fixtures.file_complaint(
        interpreter["id"],
        category="ACCURACY",
        severity="MAJOR",
        narrative="Defence counsel questions the rendition of two key terms.",
    )
    assert complaint["status"] == "FILED", (
        f"expected FILED, got {complaint['status']} before the denial"
    )

    # Adjudication is closed to the QualityReviewer role (ladder rung 2) and this
    # complaint has not been reviewed yet (ladder rung 12); the lower rung answers.
    validate_error(
        api.adjudicate_complaint(
            complaint["id"],
            adjudicate_complaint_payload("SUBSTANTIATED", "PROBATION"),
            REVIEWER_ALT,
        ),
        "ERR_UNAUTHORIZED",
    )

    unchanged = fixtures.read_complaint(complaint["id"])
    assert unchanged["status"] == "FILED", (
        f"expected FILED after the denial, got {unchanged['status']}"
    )
    assert unchanged["adjudicator_user_id"] is None, (
        f"expected adjudicator_user_id still null, got {unchanged['adjudicator_user_id']}"
    )
    assert unchanged["disposition"] is None, (
        f"expected disposition still null, got {unchanged['disposition']}"
    )


def test_denied_writes_create_no_rows_and_leave_the_clock_where_it_was(api):
    """PRD §2.12: "Authorization: the acting role appears in the endpoint's authorized-role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §2.5: "An administrative test-driving capability sets the clock to a supplied instant, and any attempt to move the clock backwards is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` is true exactly when rows remain beyond the current page."

    Design: Corner/RBAC/another_roles_exclusive_operation_is_forbidden_for_everyone_including_the_program_admin
    """
    world = fixtures.setup_confirmed_assignment()

    validate_error(
        api.create_hearing(
            create_hearing_payload(
                world["courthouse"]["id"],
                world["language"]["id"],
                case_number="CR-2026-7002",
                hearing_type="MOTION",
            ),
            make_interpreter_headers(world["interpreter"]["id"]),
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.create_credential(
            create_credential_payload(
                world["interpreter"]["id"],
                world["language"]["id"],
                world["interpreter"]["version"],
                "MASTER",
            ),
            COORDINATOR,
        ),
        "ERR_UNAUTHORIZED",
    )
    validate_error(
        api.set_clock(set_clock_payload("2026-09-10T09:00:00.000Z"), COORDINATOR),
        "ERR_UNAUTHORIZED",
    )

    _, hearing_meta = validate_paginated(api.list_hearings(ADMIN))
    assert hearing_meta["total_count"] == 1, (
        f"expected only the fixture hearing, got total_count {hearing_meta['total_count']}"
    )
    _, credential_meta = validate_paginated(api.list_credentials(ADMIN))
    assert credential_meta["total_count"] == 1, (
        f"expected only the fixture credential, got total_count {credential_meta['total_count']}"
    )

    # The refused clock move never landed: a forward step to an instant well before
    # the refused target is still accepted, which a moved clock would refuse.
    validate_success(api.set_clock(set_clock_payload("2026-08-02T00:00:00.000Z"), ADMIN))


# ---------------------------------------------------------------------------
# Corner/RBAC/the_filer_cannot_review_and_the_adjudicator_cannot_decide_the_appeal
# ---------------------------------------------------------------------------
def test_the_filer_cannot_review_the_complaint_but_a_second_reviewer_can(api):
    """PRD §2.10: "Complaint-review independence: the `QualityReviewer` whose `X-User-ID` records a review must differ from the complaint's `filed_by_user_id`."
    PRD §2.10: "A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD §2.12: "Segregation of duties, per §2.10 — otherwise `ERR_SEGREGATION_OF_DUTIES` (409). Applies to `POST /complaints/{id}/review` and `POST /complaints/{id}/appeal-decision`."
    PRD §3.9: "The reviewer must not be the filer: a caller whose `X-User-ID` equals `filed_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "The reviewer supplies a `recommendation` of `SUBSTANTIATE` or `DISMISS` and written `findings`; the service records `reviewer_user_id` from the caller's `X-User-ID` and copies the recommendation into `reviewer_recommendation`."

    Design: Corner/RBAC/the_filer_cannot_review_and_the_adjudicator_cannot_decide_the_appeal
    """
    fixtures.set_clock()
    interpreter = fixtures.enrol_interpreter()
    complaint = validate_success(
        api.create_complaint(
            create_complaint_payload(
                interpreter["id"],
                category="ACCURACY",
                severity="MAJOR",
                narrative="Defence counsel questions the rendition of two key terms.",
            ),
            REVIEWER,
        ),
        201,
    )
    assert complaint["filed_by_user_id"] == QUALITY_REVIEWER_USER_ID, (
        f"expected filer {QUALITY_REVIEWER_USER_ID}, got {complaint['filed_by_user_id']}"
    )

    body = review_complaint_payload(
        "SUBSTANTIATE", "The recording confirms both reported defects."
    )
    validate_error(
        api.review_complaint(complaint["id"], body, REVIEWER),
        "ERR_SEGREGATION_OF_DUTIES",
    )

    still_filed = fixtures.read_complaint(complaint["id"])
    assert still_filed["status"] == "FILED", (
        f"expected FILED after the refused self-review, got {still_filed['status']}"
    )
    assert still_filed["reviewer_user_id"] is None, (
        f"expected reviewer_user_id still null, got {still_filed['reviewer_user_id']}"
    )
    assert still_filed["reviewer_recommendation"] is None, (
        f"expected reviewer_recommendation still null, got {still_filed['reviewer_recommendation']}"
    )

    reviewed = validate_success(api.review_complaint(complaint["id"], body, REVIEWER_ALT))
    assert reviewed["status"] == "REVIEWED", (
        f"expected REVIEWED from the second reviewer, got {reviewed['status']}"
    )
    assert reviewed["reviewer_user_id"] == QUALITY_REVIEWER_ALT_USER_ID, (
        f"expected reviewer {QUALITY_REVIEWER_ALT_USER_ID}, got {reviewed['reviewer_user_id']}"
    )
    assert reviewed["reviewer_recommendation"] == "SUBSTANTIATE", (
        f"expected SUBSTANTIATE, got {reviewed['reviewer_recommendation']}"
    )


def test_the_adjudicator_cannot_decide_the_appeal_but_a_second_administrator_can(api):
    """PRD §2.10: "Appeal-decision independence: the `ProgramAdmin` whose `X-User-ID` decides an appeal must differ from the `adjudicator_user_id` that the same complaint's adjudication recorded."
    PRD §2.10: "A violation carries the same `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD §3.9: "Both branches record `adjudicator_user_id` from the caller's `X-User-ID` and `adjudicated_at` from the logical clock, which starts the appeal window; both set `disposition` to match; and both increment the complaint's `version` by 1."
    PRD §3.9: "Appeal is the disciplined interpreter's own remedy and no one else's."
    PRD §3.9: "The interpreter supplies written `grounds`, and the complaint moves `SUBSTANTIATED → APPEALED` with `appeal_filed_at` recording the logical clock."
    PRD §3.9: "Deciding the appeal is again a `ProgramAdmin` act, and the decider must not be the administrator whose `X-User-ID` is recorded in `adjudicator_user_id`; a self-review of one's own adjudication is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "`APPEALED → UPHELD` confirms the sanction: the disciplinary action stays `IN_EFFECT` and the interpreter's `complaint_points` is unchanged."

    Design: Corner/RBAC/the_filer_cannot_review_and_the_adjudicator_cannot_decide_the_appeal
    """
    fixtures.set_clock()
    interpreter = fixtures.enrol_interpreter()
    complaint = fixtures.file_complaint(
        interpreter["id"],
        category="ACCURACY",
        severity="MAJOR",
        narrative="Defence counsel questions the rendition of two key terms.",
    )
    fixtures.review_complaint(complaint["id"], recommendation="SUBSTANTIATE")

    adjudicated = validate_success(
        api.adjudicate_complaint(
            complaint["id"],
            adjudicate_complaint_payload("SUBSTANTIATED", "PROBATION"),
            ADMIN,
        )
    )
    assert adjudicated["status"] == "SUBSTANTIATED", (
        f"expected SUBSTANTIATED, got {adjudicated['status']}"
    )
    assert adjudicated["adjudicator_user_id"] == PROGRAM_ADMIN_USER_ID, (
        f"expected adjudicator {PROGRAM_ADMIN_USER_ID}, got {adjudicated['adjudicator_user_id']}"
    )

    appealed = fixtures.appeal_complaint(complaint["id"], interpreter["id"])
    assert appealed["status"] == "APPEALED", (
        f"expected APPEALED, got {appealed['status']} after the interpreter's own appeal"
    )
    assert appealed["appeal_filed_at"] is not None, (
        "expected appeal_filed_at recorded from the logical clock, got null"
    )

    decision = appeal_decision_payload("UPHELD")
    validate_error(
        api.decide_appeal(complaint["id"], decision, ADMIN),
        "ERR_SEGREGATION_OF_DUTIES",
    )
    still_appealed = fixtures.read_complaint(complaint["id"])
    assert still_appealed["status"] == "APPEALED", (
        f"expected APPEALED after the refused self-review, got {still_appealed['status']}"
    )

    decided = validate_success(
        api.decide_appeal(
            complaint["id"], decision, TEST_USERS["program_admin_alt_headers"]
        )
    )
    assert decided["status"] == "UPHELD", (
        f"expected UPHELD from the second administrator, got {decided['status']}"
    )
