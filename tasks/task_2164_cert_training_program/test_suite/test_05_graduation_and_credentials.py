"""Graduation review, the second segregation wall and minting the credential."""

from test_helpers import (
    ApiErrorId,
    COORD_ISSUER,
    COORD_REVIEWER,
    COORD_THIRD,
    TEST_USERS,
    advance_cohort,
    assert_credential,
    assert_hours,
    assert_score,
    make_coordinator_headers,
    read_cohort,
    read_program,
    read_trainee,
    record_completion,
    setup_credentialed_trainees,
    setup_graduated_trainees,
    setup_passed_core_trainees,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
REVIEWER = TEST_USERS["reviewer_coordinator_headers"]
ISSUER = TEST_USERS["issuer_coordinator_headers"]
TWO_TRAINEES = (("tara", "Tara Nolan"), ("dev", "Dev Okafor"))


def test_graduating_while_the_cohort_is_still_teaching_is_refused(api):
    """PRD §3.5: "An individual graduation then advances the trainee `ENROLLED → GRADUATED`
    and requires three things: the cohort must be standing at `GRADUATION_REVIEW`, failing
    which the request is refused with `ERR_COHORT_NOT_IN_REVIEW`; the trainee's
    `passed_core_count` must exactly equal the number of curriculum modules that are both
    core and active; and no completion belonging to that trainee may still be awaiting its
    demonstration."

    Design: Difficulty/cross_entity_state_dependency/graduation_requires_the_cohort_to_be_in_review
    """
    ctx = setup_passed_core_trainees()
    assert read_cohort(ctx)["status"] == "IN_SESSION"
    trainee = read_trainee(ctx, "tara")
    assert trainee["passed_core_count"] == 3, "the trainee-local requirement is satisfied"

    validate_error(
        api.trainee_enrollment(trainee["id"], {"action": "GRADUATE"}, REVIEWER),
        ApiErrorId.ERR_COHORT_NOT_IN_REVIEW.value,
    )
    assert read_trainee(ctx, "tara")["enrollment_status"] == "ENROLLED"


def test_the_identical_graduation_succeeds_once_the_cohort_enters_review(api):
    """PRD §3.5: "Before any individual can graduate, a coordinator must have moved the
    whole cohort into `GRADUATION_REVIEW`, and it is at that moment that the acting
    coordinator's opaque `X-User-ID` is captured on `graduation_reviewer_user_id`."
    PRD §3.2: "Moving `IN_SESSION → GRADUATION_REVIEW` requires that every core active
    module now has at least one class session on this cohort in `DELIVERED` standing, and
    that `seats_confirmed` is at least 1; on success the acting coordinator's `X-User-ID` is
    stamped onto `graduation_reviewer_user_id` and the owning program's
    `pending_graduation_count` is increased by 1."
    PRD §3.5: "On success, the trainee's `readiness_score` is recomputed using the certified
    variant described in §3.9."
    PRD §2.10: "The currency dimension is driven entirely by the credential machine and is
    never advanced by an enrollment action; conversely, no currency transition changes the
    enrollment dimension."

    Design: Difficulty/cross_entity_state_dependency/graduation_requires_the_cohort_to_be_in_review
    """
    ctx = setup_passed_core_trainees()
    trainee_id = ctx["trainees"]["tara"]["id"]
    validate_error(
        api.trainee_enrollment(trainee_id, {"action": "GRADUATE"}, REVIEWER),
        ApiErrorId.ERR_COHORT_NOT_IN_REVIEW.value,
    )

    cohort = advance_cohort(ctx, "GRADUATION_REVIEW", headers=REVIEWER)
    assert cohort["status"] == "GRADUATION_REVIEW"
    assert cohort["graduation_reviewer_user_id"] == COORD_REVIEWER
    assert read_program(ctx)["pending_graduation_count"] == 1

    graduated = validate_success(
        api.trainee_enrollment(trainee_id, {"action": "GRADUATE"}, REVIEWER)
    )
    assert graduated["enrollment_status"] == "GRADUATED"
    assert_score(graduated["readiness_score"], 96.00, "readiness_score")
    assert graduated["currency_status"] == "NOT_CREDENTIALED", (
        "graduation never touches the currency dimension"
    )


def test_graduating_short_of_the_core_curriculum_is_refused(api):
    """PRD §3.5: "A trainee who is short a core module, or who still holds a
    `SKILLS_PENDING` completion, is refused with `ERR_CORE_MODULES_INCOMPLETE` and HTTP 422."
    PRD §3.4: "When the module does require a demonstration, the completion advances
    `RECORDED → SKILLS_PENDING` instead and waits for a signature."

    Design: Corner/validations/graduating_without_every_core_module_is_refused
    """
    ctx = setup_passed_core_trainees(record_c=False)
    advance_cohort(ctx, "GRADUATION_REVIEW", headers=REVIEWER)
    trainee_id = ctx["trainees"]["tara"]["id"]

    validate_error(
        api.trainee_enrollment(trainee_id, {"action": "GRADUATE"}, REVIEWER),
        ApiErrorId.ERR_CORE_MODULES_INCOMPLETE.value,
    )

    pending = record_completion(ctx, "tara", "session_c", 300, store_as="tara_c")
    assert pending["status"] == "SKILLS_PENDING"

    validate_error(
        api.trainee_enrollment(trainee_id, {"action": "GRADUATE"}, REVIEWER),
        ApiErrorId.ERR_CORE_MODULES_INCOMPLETE.value,
    )

    trainee = read_trainee(ctx, "tara")
    assert trainee["enrollment_status"] == "ENROLLED"
    assert trainee["passed_core_count"] == 2
    assert_hours(trainee["earned_contact_hours"], 5.0, "earned_contact_hours")


def test_the_graduation_reviewer_may_not_mint_the_credential(api):
    """PRD §2.7: "The second wall separates graduation review from credential issuance: the
    coordinator who moved a cohort into graduation review — whose opaque identifier was
    stamped onto that cohort's `graduation_reviewer_user_id` — must not be the coordinator
    who mints credentials for that cohort's trainees. In both cases the violation is
    reported as `ERR_SEGREGATION_OF_DUTIES` with HTTP 403."
    PRD §3.5: "The acting identifier is recorded on the credential as `issued_by_user_id`,
    which is an opaque operator identifier and never a reference to a persisted row."
    PRD §3.5: "`reinstatement_count` opens at 0, `refresher_hours_in_term` opens at 0,
    `status` opens at `ACTIVE`, and the trainee's `currency_status` moves `NOT_CREDENTIALED →
    CURRENT`."

    Design: Corner/rbac/graduation_reviewer_cannot_mint_the_credential
    """
    ctx = setup_graduated_trainees()
    trainee_id = ctx["trainees"]["tara"]["id"]
    assert read_cohort(ctx)["graduation_reviewer_user_id"] == COORD_REVIEWER

    validate_error(
        api.create_credential({"trainee_id": trainee_id}, REVIEWER),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    _, meta = validate_paginated(api.list_credentials(AUDITOR, {"trainee_id": trainee_id}))
    assert meta["total_count"] == 0

    credential = validate_success(
        api.create_credential({"trainee_id": trainee_id}, ISSUER), 201
    )
    assert credential["issued_by_user_id"] == COORD_ISSUER
    assert credential["status"] == "ACTIVE"
    assert read_trainee(ctx, "tara")["currency_status"] == "CURRENT"


def test_credential_number_is_a_deterministic_sequence_inside_the_cohort(api):
    """PRD §3.5: "A minted credential is stamped with a `credential_number` formed from the
    cohort's `cohort_code`, a hyphen, and a four-digit issuance sequence within that cohort
    ordered by issuance and starting at `0001` — the third credential minted in a cohort
    coded `CERT-2026A` therefore reads `CERT-2026A-0003`."
    PRD §3.5: "At issuance the count is necessarily 0, so a new credential is always
    `STANDARD` with 8.0 required hours, no surplus and no extension; `term_start_on` is the
    logical clock, `expires_on` is 365 days after `term_start_on`, and `grace_ends_on` is a
    further 60 days after `expires_on`."

    Design: Corner/calculations/credential_number_is_a_deterministic_cohort_sequence
    """
    ctx = setup_graduated_trainees(trainees=TWO_TRAINEES)

    first = validate_success(
        api.create_credential({"trainee_id": ctx["trainees"]["tara"]["id"]}, ISSUER), 201
    )
    second = validate_success(
        api.create_credential({"trainee_id": ctx["trainees"]["dev"]["id"]}, ISSUER), 201
    )

    assert_credential(first)
    assert first["credential_number"] == "C-2026A-0001"
    assert second["credential_number"] == "C-2026A-0002"
    assert first["issued_by_user_id"] == COORD_ISSUER
    assert first["status"] == "ACTIVE"
    assert first["reinstatement_count"] == 0
    assert first["renewal_tier"] == "STANDARD"
    assert_hours(first["required_refresher_hours"], 8.0, "required_refresher_hours")
    assert read_trainee(ctx, "tara")["currency_status"] == "CURRENT"


def test_a_second_credential_for_the_same_volunteer_is_refused(api):
    """PRD §3.5: "The trainee must already stand at `GRADUATED` and must not already have a
    credential row; a second mint for the same volunteer is refused with
    `ERR_CREDENTIAL_ALREADY_ISSUED`."

    Design: Corner/validations/second_credential_for_the_same_trainee_is_refused
    """
    ctx = setup_credentialed_trainees()
    trainee_id = ctx["trainees"]["tara"]["id"]

    validate_error(
        api.create_credential({"trainee_id": trainee_id},
                              make_coordinator_headers(COORD_THIRD)),
        ApiErrorId.ERR_CREDENTIAL_ALREADY_ISSUED.value,
    )

    rows, meta = validate_paginated(
        api.list_credentials(AUDITOR, {"trainee_id": trainee_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["issued_by_user_id"] == COORD_ISSUER
    assert rows[0]["credential_number"] == "C-2026A-0001"
