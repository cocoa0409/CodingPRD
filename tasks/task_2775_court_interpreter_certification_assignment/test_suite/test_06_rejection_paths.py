"""Rejection paths: the error catalogue, uniqueness refusals, credentialing and
renewal gates, assignment guards, service-order guards and the appeal window.

Every test here translates one instance of `section: Errors` from
SCAFFOLD_CORNER_DESIGN.yaml. Bundled instances are split into one test per
rejection (or parametrized over the (setup-variant, expected error_id) pairs),
and every emitted test carries the single `Design:` line of its parent instance.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    appeal_complaint_payload,
    complete_assignment_payload,
    create_assignment_payload,
    create_credential_payload,
    create_interpreter_payload,
    create_language_payload,
    create_rate_schedule_payload,
    exam_attempt_payload,
    make_interpreter_headers,
    renew_credential_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
import test_helpers.fixtures as fixtures

ADMIN = TEST_USERS["program_admin_headers"]
CREDENTIALING = TEST_USERS["credentialing_officer_headers"]
COORDINATOR = TEST_USERS["scheduling_coordinator_headers"]
FISCAL = TEST_USERS["fiscal_officer_headers"]
REVIEWER = TEST_USERS["quality_reviewer_headers"]

# A syntactically valid UUID that no entity in the program ever carries.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Instance: unknown_ids_in_every_entity_family_each_return_the_family_specific_not_found
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "family,expected_error_id",
    [
        ("interpreters", ApiErrorId.ERR_INTERPRETER_NOT_FOUND),
        ("credentials", ApiErrorId.ERR_CREDENTIAL_NOT_FOUND),
        ("hearings", ApiErrorId.ERR_HEARING_NOT_FOUND),
        ("assignments", ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        ("pay-claims", ApiErrorId.ERR_PAY_CLAIM_NOT_FOUND),
        ("complaints", ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        ("disciplinary-actions", ApiErrorId.ERR_DISCIPLINARY_ACTION_NOT_FOUND),
        ("courthouses", ApiErrorId.ERR_CONFIG_RESOURCE_NOT_FOUND),
        ("languages", ApiErrorId.ERR_CONFIG_RESOURCE_NOT_FOUND),
        ("rate-schedules", ApiErrorId.ERR_CONFIG_RESOURCE_NOT_FOUND),
    ],
)
def test_unknown_path_id_returns_the_family_specific_not_found(api, family,
                                                               expected_error_id):
    """PRD §2.6: "An unresolvable interpreter segment yields `ERR_INTERPRETER_NOT_FOUND`; a credential segment, `ERR_CREDENTIAL_NOT_FOUND`; a hearing segment, `ERR_HEARING_NOT_FOUND`; an assignment segment, `ERR_ASSIGNMENT_NOT_FOUND`; a pay-claim segment, `ERR_PAY_CLAIM_NOT_FOUND`; a complaint segment, `ERR_COMPLAINT_NOT_FOUND`; a disciplinary-action segment, `ERR_DISCIPLINARY_ACTION_NOT_FOUND`; and a courthouse segment, `ERR_CONFIG_RESOURCE_NOT_FOUND`. All eight are HTTP 404."
    PRD §2.6: "A `language_id`, `courthouse_id`, or `rate_schedule_id` that does not resolve yields `ERR_CONFIG_RESOURCE_NOT_FOUND`; an `interpreter_id`, `ERR_INTERPRETER_NOT_FOUND`; a `hearing_id`, `ERR_HEARING_NOT_FOUND`; an `assignment_id`, `ERR_ASSIGNMENT_NOT_FOUND`; a `complaint_id`, `ERR_COMPLAINT_NOT_FOUND`."

    Design: Corner/Errors/unknown_ids_in_every_entity_family_each_return_the_family_specific_not_found
    """
    fixtures.set_clock()
    readers = {
        "interpreters": lambda: api.get_interpreter(UNKNOWN_UUID, ADMIN),
        "credentials": lambda: api.get_credential(UNKNOWN_UUID, CREDENTIALING),
        "hearings": lambda: api.get_hearing(UNKNOWN_UUID, COORDINATOR),
        "assignments": lambda: api.get_assignment(UNKNOWN_UUID, COORDINATOR),
        "pay-claims": lambda: api.get_pay_claim(UNKNOWN_UUID, FISCAL),
        "complaints": lambda: api.get_complaint(UNKNOWN_UUID, REVIEWER),
        "disciplinary-actions": lambda: api.get_disciplinary_action(UNKNOWN_UUID, REVIEWER),
        "courthouses": lambda: api.get_courthouse(UNKNOWN_UUID, ADMIN),
        "languages": lambda: api.get_language(UNKNOWN_UUID, ADMIN),
        "rate-schedules": lambda: api.get_rate_schedule(UNKNOWN_UUID, ADMIN),
    }

    response = readers[family]()

    validate_error(response, expected_error_id, 404)


# ---------------------------------------------------------------------------
# Instance: duplicate_language_code_duplicate_email_and_an_overlapping_rate_window_are_each_rejected
# ---------------------------------------------------------------------------
def test_a_second_registration_of_the_same_language_code_is_refused(api):
    """PRD §3.1: "Registering a language records its ISO-639-3 `code` — three lowercase letters, unique across the whole program, with a second registration of the same code refused as `ERR_DUPLICATE_LANGUAGE_CODE` — together with a human-readable `name`, its coverage class in `tier_class`, and whether the program administers an oral performance examination in it via `oral_exam_available`."

    Design: Corner/Errors/duplicate_language_code_duplicate_email_and_an_overlapping_rate_window_are_each_rejected
    """
    fixtures.set_clock()
    first = fixtures.bootstrap_language()

    response = api.create_language(
        create_language_payload(code="spa", name="Castilian Spanish"), ADMIN
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_LANGUAGE_CODE)
    _, meta = validate_paginated(api.list_languages(ADMIN))
    assert meta["total_count"] == 1, (
        f"expected 1 language after the refused duplicate, got {meta['total_count']}"
    )
    assert fixtures.read_language(first["id"])["name"] == "Spanish", (
        "the refused duplicate must not overwrite the registered language's name"
    )


def test_a_second_enrolment_with_the_same_email_is_refused(api):
    """PRD §3.2: "Enrolment, performed by a `CredentialingOfficer` or a `ProgramAdmin`, records `full_name`, a contact `email` that must be unique across the roster — a second enrolment with the same address is refused with `ERR_DUPLICATE_INTERPRETER_EMAIL` — an optional `phone` that is null when omitted, and a `home_county_code` of three uppercase letters that the program later compares against a courthouse's `county_code` when it ranks candidates by geographic availability."

    Design: Corner/Errors/duplicate_language_code_duplicate_email_and_an_overlapping_rate_window_are_each_rejected
    """
    fixtures.set_clock()
    fixtures.enrol_interpreter()

    # The refusal is a roster-wide uniqueness rule, not a per-caller one: a
    # ProgramAdmin retrying the same address is refused just the same.
    response = api.create_interpreter(
        create_interpreter_payload(
            full_name="Ana Reyes Duplicate", email="ana.reyes@courts.example.gov"
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_INTERPRETER_EMAIL)
    _, meta = validate_paginated(api.list_interpreters(ADMIN))
    assert meta["total_count"] == 1, (
        f"expected 1 interpreter after the refused duplicate, got {meta['total_count']}"
    )


def test_a_rate_schedule_window_overlapping_an_existing_one_is_refused(api):
    """PRD §3.1: "Because exactly one schedule must govern any given hearing date, a submission whose window overlaps an existing schedule's window is refused with `ERR_RATE_SCHEDULE_OVERLAP`."

    Design: Corner/Errors/duplicate_language_code_duplicate_email_and_an_overlapping_rate_window_are_each_rejected
    """
    fixtures.set_clock()
    fixtures.bootstrap_rate_schedule()  # open-ended from 2026-01-01

    # A fully bounded window that sits entirely inside the open-ended one.
    response = api.create_rate_schedule(
        create_rate_schedule_payload(
            effective_from="2027-04-01", effective_through="2027-06-30"
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_RATE_SCHEDULE_OVERLAP)
    _, meta = validate_paginated(api.list_rate_schedules(ADMIN))
    assert meta["total_count"] == 1, (
        f"expected 1 rate schedule after the refused overlap, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Instance: provisional_tier_missing_oral_instrument_and_a_live_duplicate_are_each_rejected_on_the_credentialing_surface
# ---------------------------------------------------------------------------
def test_provisional_target_in_a_fully_examinable_language_is_refused(api):
    """PRD §3.3: "A `PROVISIONAL` target is the program's rare-language and no-instrument escape hatch, and it is permitted only when the language's `tier_class` is `RARE` or the language's `oral_exam_available` is false; requesting `PROVISIONAL` for a fully examinable designated language is refused with `ERR_PROVISIONAL_TIER_NOT_PERMITTED` (HTTP 422)."

    Design: Corner/Errors/provisional_tier_missing_oral_instrument_and_a_live_duplicate_are_each_rejected_on_the_credentialing_surface
    """
    fixtures.set_clock()
    language = fixtures.bootstrap_language()  # spa, DESIGNATED, oral_exam_available true
    interpreter = fixtures.enrol_interpreter()

    response = api.create_credential(
        create_credential_payload(
            interpreter["id"], language["id"], interpreter["version"], "PROVISIONAL"
        ),
        CREDENTIALING,
    )

    validate_error(response, ApiErrorId.ERR_PROVISIONAL_TIER_NOT_PERMITTED, 422)


def test_provisional_refusal_outranks_the_live_duplicate_refusal(api):
    """PRD §3.3: "A `PROVISIONAL` target is the program's rare-language and no-instrument escape hatch, and it is permitted only when the language's `tier_class` is `RARE` or the language's `oral_exam_available` is false; requesting `PROVISIONAL` for a fully examinable designated language is refused with `ERR_PROVISIONAL_TIER_NOT_PERMITTED` (HTTP 422)."
    PRD §2.12: "The ladder is global — a check at a lower number always masks a check at a higher number — and it is the reason a request that is both unauthorized and malformed reports only the authorization failure."
    PRD §2.12: "21. A provisional target tier is permitted for the language — otherwise `ERR_PROVISIONAL_TIER_NOT_PERMITTED` (422). Applies to `POST /credentials`."
    PRD §2.12: "23. No other live credential exists for the same interpreter-and-language pair — otherwise `ERR_DUPLICATE_ACTIVE_CREDENTIAL` (409). Applies to `POST /credentials`."

    Design: Corner/Errors/provisional_tier_missing_oral_instrument_and_a_live_duplicate_are_each_rejected_on_the_credentialing_surface
    """
    fixtures.set_clock()
    language = fixtures.bootstrap_language()
    interpreter = fixtures.enrol_interpreter()
    live = fixtures.open_credential(
        interpreter["id"], language["id"], "CERTIFIED", interpreter["version"]
    )
    assert live["status"] == "PENDING_WRITTEN", (
        f"setup expected a live PENDING_WRITTEN credential, got {live['status']}"
    )
    version = fixtures.read_interpreter(interpreter["id"])["version"]

    # This request violates rung 21 and rung 23 at once; the lower rung wins.
    response = api.create_credential(
        create_credential_payload(
            interpreter["id"], language["id"], version, "PROVISIONAL"
        ),
        CREDENTIALING,
    )

    validate_error(response, ApiErrorId.ERR_PROVISIONAL_TIER_NOT_PERMITTED, 422)


def test_a_lower_tier_second_credential_in_the_same_language_is_refused(api):
    """PRD §3.3: "And a live credential is unique per interpreter-and-language pair: if the interpreter already holds a credential in the same language whose status is `ACTIVE`, `LAPSED`, `PENDING_WRITTEN`, `PENDING_ORAL`, or `PENDING_ETHICS`, the create is refused with `ERR_DUPLICATE_ACTIVE_CREDENTIAL`."
    PRD §3.3: "The target tier is fixed at creation and never changes; the separate field `tier` stays null until the credential is activated and then mirrors `target_tier` for as long as the credential remains active, reverting to null if it lapses or is revoked."

    Design: Corner/Errors/provisional_tier_missing_oral_instrument_and_a_live_duplicate_are_each_rejected_on_the_credentialing_surface
    """
    fixtures.set_clock()
    language = fixtures.bootstrap_language()
    interpreter = fixtures.enrol_interpreter()
    live = fixtures.open_credential(
        interpreter["id"], language["id"], "CERTIFIED", interpreter["version"]
    )
    version = fixtures.read_interpreter(interpreter["id"])["version"]

    # REGISTERED ranks below the live CERTIFIED application, so the upgrade
    # exception does not apply and the create is simply refused.
    response = api.create_credential(
        create_credential_payload(
            interpreter["id"], language["id"], version, "REGISTERED"
        ),
        CREDENTIALING,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_CREDENTIAL, 409)
    still = fixtures.read_credential(live["id"])
    assert still["target_tier"] == "CERTIFIED", (
        f"target_tier is fixed at creation, got {still['target_tier']}"
    )
    assert still["status"] == "PENDING_WRITTEN", (
        f"the refused create must not withdraw the live credential, got {still['status']}"
    )


def test_an_oral_attempt_in_a_language_without_an_oral_instrument_is_refused(api):
    """PRD §3.3: "An `ORAL` attempt is additionally only recordable in a language whose `oral_exam_available` is true; otherwise the program refuses it with `ERR_ORAL_EXAM_NOT_OFFERED` (HTTP 422)."
    PRD §3.3: "Each recorded attempt refreshes the credential's best score for that exam type — `written_best_score` and `oral_best_score` each hold the highest `score` seen across that type's attempts, remaining null while no attempt of that type exists — increments the matching `written_attempt_count` or `oral_attempt_count`, and increments the credential's `version` by 1."

    Design: Corner/Errors/provisional_tier_missing_oral_instrument_and_a_live_duplicate_are_each_rejected_on_the_credentialing_surface
    """
    fixtures.set_clock()
    hmn = fixtures.bootstrap_language(
        code="hmn", name="Hmong", tier_class="NON_DESIGNATED", oral_exam_available=False
    )
    interpreter = fixtures.enrol_interpreter()
    credential = fixtures.open_credential(
        interpreter["id"], hmn["id"], "REGISTERED", interpreter["version"]
    )

    refused = api.create_exam_attempt(
        credential["id"],
        exam_attempt_payload(exam_type="ORAL", score=88, taken_on="2026-08-01"),
        CREDENTIALING,
    )
    validate_error(refused, ApiErrorId.ERR_ORAL_EXAM_NOT_OFFERED, 422)

    # The very same endpoint on the very same credential accepts WRITTEN work.
    accepted = api.create_exam_attempt(
        credential["id"],
        exam_attempt_payload(exam_type="WRITTEN", score=88, taken_on="2026-08-01"),
        CREDENTIALING,
    )
    attempt = validate_success(accepted, 201)
    assert attempt["attempt_ordinal"] == 1, (
        f"expected attempt_ordinal 1, got {attempt['attempt_ordinal']}"
    )

    after = fixtures.read_credential(credential["id"])
    assert after["oral_attempt_count"] == 0, (
        f"the refused ORAL attempt must not count, got {after['oral_attempt_count']}"
    )
    assert after["written_attempt_count"] == 1, (
        f"expected written_attempt_count 1, got {after['written_attempt_count']}"
    )
    assert after["oral_best_score"] is None, (
        f"oral_best_score stays null with no oral attempt, got {after['oral_best_score']}"
    )
    assert after["written_best_score"] == 88, (
        f"expected written_best_score 88, got {after['written_best_score']}"
    )


# ---------------------------------------------------------------------------
# Instance: a_fourth_sitting_of_the_same_exam_is_rejected_even_after_the_third_one_passed
# ---------------------------------------------------------------------------
def _three_written_sittings():
    """spa + Ana Reyes + a CERTIFIED credential with 72 FAIL, 74 FAIL, 86 PASS."""
    fixtures.set_clock()
    language = fixtures.bootstrap_language()
    interpreter = fixtures.enrol_interpreter()
    credential = fixtures.open_credential(
        interpreter["id"], language["id"], "CERTIFIED", interpreter["version"]
    )
    attempts = [
        fixtures.record_exam_attempt(credential["id"], "WRITTEN", 72, "2026-08-01"),
        fixtures.record_exam_attempt(credential["id"], "WRITTEN", 74, "2026-10-30"),
        fixtures.record_exam_attempt(credential["id"], "WRITTEN", 86, "2027-01-28"),
    ]
    return credential, attempts


def test_a_fourth_written_sitting_is_refused_even_though_the_third_one_passed(api):
    """PRD §3.3: "At most three attempts of each exam type are ever allowed against one credential, so a fourth attempt of the same type is refused with `ERR_EXAM_ATTEMPT_LIMIT_REACHED`."
    PRD §3.3: "And a candidate who has failed must wait: the supplied `taken_on` must be at least 90 days after the `taken_on` of the most recent failed attempt of the same exam type on this credential, with a gap of exactly 90 days accepted and anything shorter refused as `ERR_EXAM_RETAKE_TOO_SOON`."
    PRD §3.3: "When a written attempt brings `written_attempt_count` to 3 while the credential sits in `PENDING_WRITTEN` and `written_best_score` is still below the written floor for the target tier, the recording call itself drives `PENDING_WRITTEN → DENIED` and increments the credential's `version`."
    PRD §3.3: "The written floor is 90 for a `MASTER` target and 80 for every other target."

    Design: Corner/Errors/a_fourth_sitting_of_the_same_exam_is_rejected_even_after_the_third_one_passed
    """
    credential, attempts = _three_written_sittings()
    assert [a["result"] for a in attempts] == ["FAIL", "FAIL", "PASS"], (
        f"expected FAIL/FAIL/PASS against the CERTIFIED written floor of 80, "
        f"got {[a['result'] for a in attempts]}"
    )
    assert [a["attempt_ordinal"] for a in attempts] == [1, 2, 3], (
        f"expected ordinals 1, 2, 3, got {[a['attempt_ordinal'] for a in attempts]}"
    )

    # 2027-05-01 is far more than 90 days after the most recent FAILED sitting
    # of 2026-10-30, so only the attempt-cap rung can fire.
    response = api.create_exam_attempt(
        credential["id"],
        exam_attempt_payload(exam_type="WRITTEN", score=92, taken_on="2027-05-01"),
        CREDENTIALING,
    )

    validate_error(response, ApiErrorId.ERR_EXAM_ATTEMPT_LIMIT_REACHED, 409)
    after = fixtures.read_credential(credential["id"])
    assert after["written_attempt_count"] == 3, (
        f"the refused sitting must not count, got {after['written_attempt_count']}"
    )
    assert after["written_best_score"] == 86, (
        f"expected written_best_score 86, got {after['written_best_score']}"
    )
    assert after["status"] == "PENDING_WRITTEN", (
        f"a passing third sitting leaves the credential viable, got {after['status']}"
    )
    rows, meta = validate_paginated(
        api.list_exam_attempts(credential["id"], CREDENTIALING,
                               params={"exam_type": "WRITTEN"})
    )
    assert meta["total_count"] == 3, (
        f"expected 3 written attempts on record, got {meta['total_count']}"
    )
    assert all(row["score"] != 92 for row in rows), (
        f"the refused 92 must not have been recorded: {[r['score'] for r in rows]}"
    )


def test_the_oral_counter_is_untouched_by_three_written_sittings(api):
    """PRD §3.3: "At most three attempts of each exam type are ever allowed against one credential, so a fourth attempt of the same type is refused with `ERR_EXAM_ATTEMPT_LIMIT_REACHED`."
    PRD §3.3: "Recording an attempt writes `credential_id` from the credential the attempt is filed under, derives `attempt_ordinal` as the 1-based index of this attempt among the credential's attempts of the *same* `exam_type` ordered by `taken_on` ascending and then `created_at` ascending, and derives `result` as `PASS` when the score reaches the passing floor for the credential's target tier and this exam type and `FAIL` otherwise."
    PRD §3.3: "Attempts may only be recorded while the credential's status is `PENDING_WRITTEN` or `PENDING_ORAL`, and otherwise the call is refused with `ERR_INVALID_CREDENTIAL_STATE`."

    Design: Corner/Errors/a_fourth_sitting_of_the_same_exam_is_rejected_even_after_the_third_one_passed
    """
    credential, _ = _three_written_sittings()

    response = api.create_exam_attempt(
        credential["id"],
        exam_attempt_payload(exam_type="ORAL", score=78, taken_on="2027-05-01"),
        CREDENTIALING,
    )

    attempt = validate_success(response, 201)
    assert attempt["attempt_ordinal"] == 1, (
        f"the ORAL ordinal counts only ORAL sittings, got {attempt['attempt_ordinal']}"
    )
    after = fixtures.read_credential(credential["id"])
    assert after["oral_attempt_count"] == 1, (
        f"expected oral_attempt_count 1, got {after['oral_attempt_count']}"
    )
    assert after["oral_best_score"] == 78, (
        f"expected oral_best_score 78, got {after['oral_best_score']}"
    )
    assert after["written_attempt_count"] == 3, (
        f"the written counter is unchanged, got {after['written_attempt_count']}"
    )


# ---------------------------------------------------------------------------
# Instance: renewal_rejects_short_credit_hours_and_still_rejects_them_after_the_grace_date_has_passed
# ---------------------------------------------------------------------------
def test_renewal_below_the_sixteen_hour_minimum_is_refused_on_an_active_credential(api):
    """PRD §3.4: "At least 16 hours are required; exactly 16 is accepted and 15.5 is refused with `ERR_INSUFFICIENT_CREDIT_HOURS` (HTTP 422)."
    PRD §3.4: "A successful renewal sets `expires_on` to 730 days after the later of the credential's current `expires_on` and the current logical-clock date — 365 days for a `PROVISIONAL` credential — recomputes `grace_through` as 90 days after the new `expires_on`, overwrites `cycle_credit_hours` with the submitted figure, adds 1 to `renewal_count`, and increments the credential's `version` by 1."
    PRD §3.3: "On success the credential's `status` becomes `ACTIVE` and `tier` is set to `target_tier`; `issued_on` records the logical-clock date of this first activation; `expires_on` is set 730 days — two full years — after that date for a `MASTER`, `CERTIFIED`, or `REGISTERED` credential, and 365 days after it for a `PROVISIONAL` one, whose shorter cycle reflects that it rests on no examination; and `grace_through` is set 90 days after `expires_on`."

    Design: Corner/Errors/renewal_rejects_short_credit_hours_and_still_rejects_them_after_the_grace_date_has_passed
    """
    fixtures.set_clock()
    language = fixtures.bootstrap_language()
    bundle = fixtures.setup_active_interpreter(language["id"], target_tier="CERTIFIED")
    credential = bundle["credential"]
    assert credential["status"] == "ACTIVE", (
        f"setup expected an ACTIVE credential, got {credential['status']}"
    )
    assert credential["expires_on"] == "2028-07-31", (
        f"expected expires_on 2028-07-31 (730 days), got {credential['expires_on']}"
    )
    assert credential["grace_through"] == "2028-10-29", (
        f"expected grace_through 2028-10-29 (expires_on + 90), "
        f"got {credential['grace_through']}"
    )

    response = api.renew_credential(
        credential["id"], renew_credential_payload(15.5), CREDENTIALING
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_CREDIT_HOURS, 422)
    after = fixtures.read_credential(credential["id"])
    assert after["cycle_credit_hours"] == 0, (
        f"a refused renewal must not overwrite cycle_credit_hours, "
        f"got {after['cycle_credit_hours']}"
    )
    assert after["renewal_count"] == 0, (
        f"a refused renewal must not add to renewal_count, got {after['renewal_count']}"
    )


def test_renewal_after_the_grace_date_is_refused_even_with_ample_hours(api):
    """PRD §3.4: "A `LAPSED` credential may be renewed only while the logical-clock date is on or before `grace_through`, which is to say within the 90 days following `expires_on`; the `grace_through` date itself is inside the window and the day after it is not, and a late attempt is refused with `ERR_RENEWAL_GRACE_EXPIRED`."

    Design: Corner/Errors/renewal_rejects_short_credit_hours_and_still_rejects_them_after_the_grace_date_has_passed
    """
    fixtures.set_clock()
    language = fixtures.bootstrap_language()
    lapsed = fixtures.setup_lapsed_credential(
        language["id"], "2028-08-01T00:00:00.000Z", target_tier="CERTIFIED"
    )
    credential = lapsed["credential"]
    assert credential["status"] == "LAPSED", (
        f"setup expected a LAPSED credential, got {credential['status']}"
    )
    assert credential["grace_through"] == "2028-10-29", (
        f"expected grace_through 2028-10-29, got {credential['grace_through']}"
    )
    fixtures.set_clock("2028-10-30T00:00:00.000Z")  # one day past grace_through

    response = api.renew_credential(
        credential["id"], renew_credential_payload(20.0), CREDENTIALING
    )

    validate_error(response, ApiErrorId.ERR_RENEWAL_GRACE_EXPIRED, 409)
    after = fixtures.read_credential(credential["id"])
    assert after["status"] == "LAPSED", (
        f"the refusal leaves the credential LAPSED, got {after['status']}"
    )
    assert after["renewal_count"] == 0, (
        f"expected renewal_count 0, got {after['renewal_count']}"
    )


def test_short_hours_still_outrank_the_closed_grace_window(api):
    """PRD §3.4: "At least 16 hours are required; exactly 16 is accepted and 15.5 is refused with `ERR_INSUFFICIENT_CREDIT_HOURS` (HTTP 422)."
    PRD §2.12: "24. Continuing-education hours meet the renewal minimum — otherwise `ERR_INSUFFICIENT_CREDIT_HOURS` (422). Applies to `POST /credentials/{id}/renew`."
    PRD §2.12: "25. A lapsed credential is still inside its renewal grace window — otherwise `ERR_RENEWAL_GRACE_EXPIRED` (409). Applies to `POST /credentials/{id}/renew`."
    PRD §2.12: "The ladder is global — a check at a lower number always masks a check at a higher number — and it is the reason a request that is both unauthorized and malformed reports only the authorization failure."

    Design: Corner/Errors/renewal_rejects_short_credit_hours_and_still_rejects_them_after_the_grace_date_has_passed
    """
    fixtures.set_clock()
    language = fixtures.bootstrap_language()
    lapsed = fixtures.setup_lapsed_credential(
        language["id"], "2028-08-01T00:00:00.000Z", target_tier="CERTIFIED"
    )
    credential = lapsed["credential"]
    fixtures.set_clock("2028-10-30T00:00:00.000Z")

    # The identical 15.5-hour body that was a 422 on a healthy ACTIVE credential
    # is still a 422 here: rung 24 is evaluated before rung 25.
    response = api.renew_credential(
        credential["id"], renew_credential_payload(15.5), CREDENTIALING
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_CREDIT_HOURS, 422)
    after = fixtures.read_credential(credential["id"])
    assert after["status"] == "LAPSED", (
        f"no refusal advances the credential to a terminal status, got {after['status']}"
    )
    assert after["grace_through"] == "2028-10-29", (
        f"grace_through is untouched by a refusal, got {after['grace_through']}"
    )


# ---------------------------------------------------------------------------
# Instance: assignment_create_rejects_an_applicant_a_foreign_language_credential_a_missing_telephonic_vendor_a_covered_hearing_and_a_started_hearing
# ---------------------------------------------------------------------------
def _matching_config():
    """spa (no telephonic vendor) + kor + the CAS courthouse + one open schedule."""
    fixtures.set_clock()
    config = fixtures.setup_program_config(
        courthouse_overrides={"vri_concurrent_capacity": 2}
    )
    assert config["language"]["telephonic_vendor_available"] is False, (
        "spa must default to telephonic_vendor_available false"
    )
    return config


def _plea_hearing(courthouse_id, language_id, case_number, day):
    return fixtures.schedule_hearing(
        courthouse_id,
        language_id,
        case_number=case_number,
        hearing_type="PLEA",
        in_custody=True,
        scheduled_start=f"{day}T09:00:00.000Z",
        scheduled_end=f"{day}T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )


def test_proposing_an_applicant_is_refused_on_roster_standing(api):
    """PRD §3.6: "Where a rostered interpreter is named, the roster gates of §2.12 apply in order — active roster standing, an active credential in the language, sufficient tier rank, completed ethics training, and the quality floor for a class `A` hearing — and on success the program pins `credential_id` and `credential_tier_snapshot` from the interpreter's best active credential in the hearing's language."
    PRD §2.12: "14. The named interpreter is on the active roster — otherwise `ERR_INTERPRETER_NOT_ON_ACTIVE_ROSTER` (409). Applies to `POST /assignments`."
    PRD §3.2: "Enrolment sets `roster_status` to `APPLICANT` and `ethics_training_status` to `NOT_STARTED`, and it initialises `complaint_points` to 0 with `rolling_12_month_score` and `lifetime_score` both at 100."

    Design: Corner/Errors/assignment_create_rejects_an_applicant_a_foreign_language_credential_a_missing_telephonic_vendor_a_covered_hearing_and_a_started_hearing
    """
    config = _matching_config()
    hearing = _plea_hearing(
        config["courthouse"]["id"], config["language"]["id"], "CR-2026-3001",
        "2026-09-15",
    )
    applicant = fixtures.enrol_interpreter(
        full_name="Dev Rao", email="dev.rao@courts.example.gov"
    )
    assert applicant["roster_status"] == "APPLICANT", (
        f"setup expected an APPLICANT, got {applicant['roster_status']}"
    )

    # The applicant fails the roster gate, the credential gate and the ethics
    # gate at once; rung 14 is the lowest of the three.
    response = api.create_assignment(
        create_assignment_payload(
            hearing["id"], hearing["version"], applicant["id"],
            delivery_mode="IN_PERSON",
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_INTERPRETER_NOT_ON_ACTIVE_ROSTER, 409)


def test_proposing_an_interpreter_with_no_credential_in_the_hearings_language_is_refused(api):
    """PRD §3.6: "Where a rostered interpreter is named, the roster gates of §2.12 apply in order — active roster standing, an active credential in the language, sufficient tier rank, completed ethics training, and the quality floor for a class `A` hearing — and on success the program pins `credential_id` and `credential_tier_snapshot` from the interpreter's best active credential in the hearing's language."
    PRD §2.12: "15. The named interpreter holds an active credential in the hearing's language — otherwise `ERR_CREDENTIAL_NOT_ACTIVE` (409). Applies to `POST /assignments`."

    Design: Corner/Errors/assignment_create_rejects_an_applicant_a_foreign_language_credential_a_missing_telephonic_vendor_a_covered_hearing_and_a_started_hearing
    """
    config = _matching_config()
    kor = fixtures.bootstrap_language(
        code="kor", name="Korean", tier_class="NON_DESIGNATED", oral_exam_available=True
    )
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    assert bundle["interpreter"]["roster_status"] == "ACTIVE", (
        f"setup expected an ACTIVE interpreter, "
        f"got {bundle['interpreter']['roster_status']}"
    )
    korean_hearing = _plea_hearing(
        config["courthouse"]["id"], kor["id"], "CR-2026-3002", "2026-09-16"
    )

    response = api.create_assignment(
        create_assignment_payload(
            korean_hearing["id"], korean_hearing["version"],
            bundle["interpreter"]["id"], delivery_mode="IN_PERSON",
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_CREDENTIAL_NOT_ACTIVE, 409)


def test_telephonic_delivery_in_a_language_with_no_vendor_is_refused(api):
    """PRD §3.6: "A `TELEPHONIC` assignment requires the hearing's language to have `telephonic_vendor_available` set to true, and when `vendor_served` is true it additionally requires the language's `tier_class` to be `RARE` and `interpreter_id` to be absent from the request; any of those failing is refused with `ERR_TELEPHONIC_NOT_PERMITTED` (HTTP 422)."
    PRD §3.1: "An optional `telephonic_vendor_available` flag, false when omitted, records whether a telephonic language-service vendor covers the language; only a language with that flag set may be served telephonically."

    Design: Corner/Errors/assignment_create_rejects_an_applicant_a_foreign_language_credential_a_missing_telephonic_vendor_a_covered_hearing_and_a_started_hearing
    """
    config = _matching_config()
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    hearing = _plea_hearing(
        config["courthouse"]["id"], config["language"]["id"], "CR-2026-3001",
        "2026-09-15",
    )

    # A perfectly eligible interpreter, vendor_served left at its false default.
    response = api.create_assignment(
        create_assignment_payload(
            hearing["id"], hearing["version"], bundle["interpreter"]["id"],
            delivery_mode="TELEPHONIC",
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_TELEPHONIC_NOT_PERMITTED, 422)


def test_a_second_proposal_onto_a_covered_hearing_is_refused(api):
    """PRD §3.6: "The hearing must be in `SCHEDULED` status: a hearing that is `SERVED`, `UNMET`, or `CONTINUED` is not schedulable at all and is refused with `ERR_HEARING_NOT_SCHEDULABLE`, while a hearing that is merely `COVERED` — which is to say one that already carries a `CONFIRMED`, `CHECKED_IN`, or `COMPLETED` assignment — is refused with the dedicated `ERR_HEARING_ALREADY_COVERED`."
    PRD §3.5: "`SCHEDULED → COVERED` fires when an assignment for the hearing reaches `CONFIRMED`; note that a merely proposed assignment leaves the hearing `SCHEDULED`, because coverage means acceptance, not intent."

    Design: Corner/Errors/assignment_create_rejects_an_applicant_a_foreign_language_credential_a_missing_telephonic_vendor_a_covered_hearing_and_a_started_hearing
    """
    config = _matching_config()
    first = fixtures.setup_active_interpreter(config["language"]["id"])
    second = fixtures.setup_active_interpreter(
        config["language"]["id"],
        interpreter_overrides={
            "full_name": "Beto Cruz", "email": "beto.cruz@courts.example.gov",
        },
    )
    hearing = _plea_hearing(
        config["courthouse"]["id"], config["language"]["id"], "CR-2026-3001",
        "2026-09-15",
    )
    assignment = fixtures.propose_assignment(
        hearing["id"], first["interpreter"]["id"], delivery_mode="IN_PERSON"
    )
    assert assignment["service_status"] == "PROPOSED", (
        f"setup expected PROPOSED, got {assignment['service_status']}"
    )
    confirmed = fixtures.confirm_assignment(
        assignment["id"], first["interpreter"]["id"]
    )
    assert confirmed["service_status"] == "CONFIRMED", (
        f"setup expected CONFIRMED, got {confirmed['service_status']}"
    )
    covered = fixtures.read_hearing(hearing["id"])
    assert covered["status"] == "COVERED", (
        f"confirmation must bubble the hearing to COVERED, got {covered['status']}"
    )

    # The version pin is current, so the concurrency rung passes and the
    # dedicated already-covered gate is the one that fires.
    response = api.create_assignment(
        create_assignment_payload(
            hearing["id"], covered["version"], second["interpreter"]["id"],
            delivery_mode="IN_PERSON",
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_HEARING_ALREADY_COVERED, 409)
    rows, meta = validate_paginated(
        api.list_assignments(COORDINATOR, params={"hearing_id": hearing["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the refused replacement must create no row, got {meta['total_count']}"
    )
    assert rows[0]["service_status"] == "CONFIRMED", (
        f"the accepted assignment stays CONFIRMED, got {rows[0]['service_status']}"
    )


def test_a_proposal_after_the_hearing_has_started_is_refused(api):
    """PRD §3.6: "The `scheduled_start` must also still lie strictly in the future on the logical clock, or the create is refused with `ERR_HEARING_WINDOW_CLOSED`."
    PRD §3.5: "`SCHEDULED → UNMET` is the clock-driven leg: a hearing still uncovered when its start time arrives is swept to unmet by the daily operations run."

    Design: Corner/Errors/assignment_create_rejects_an_applicant_a_foreign_language_credential_a_missing_telephonic_vendor_a_covered_hearing_and_a_started_hearing
    """
    config = _matching_config()
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    hearing = _plea_hearing(
        config["courthouse"]["id"], config["language"]["id"], "CR-2026-3003",
        "2026-09-20",
    )
    fixtures.set_clock("2026-09-20T09:30:00.000Z")  # 30 minutes past the start

    response = api.create_assignment(
        create_assignment_payload(
            hearing["id"], hearing["version"], bundle["interpreter"]["id"],
            delivery_mode="IN_PERSON",
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_HEARING_WINDOW_CLOSED, 409)
    after = fixtures.read_hearing(hearing["id"])
    assert after["status"] == "SCHEDULED", (
        f"the refused create leaves the hearing SCHEDULED, got {after['status']}"
    )


# ---------------------------------------------------------------------------
# Instance: confirm_with_no_schedule_in_effect_and_service_actions_out_of_order_are_rejected_then_a_new_schedule_unblocks_the_same_call
# ---------------------------------------------------------------------------
def _uncovered_hearing_date_setup():
    """One bounded schedule (2026-01-01..2026-09-30) and a PROPOSED assignment
    on a hearing dated 2026-11-10, which no published schedule governs."""
    fixtures.set_clock()
    config = fixtures.setup_program_config(
        courthouse_overrides={"vri_concurrent_capacity": 2},
        rate_overrides={"effective_through": "2026-09-30"},
    )
    bundle = fixtures.setup_active_interpreter(config["language"]["id"])
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-4001",
        hearing_type="PLEA",
        in_custody=True,
        scheduled_start="2026-11-10T09:00:00.000Z",
        scheduled_end="2026-11-10T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    assignment = fixtures.propose_assignment(
        hearing["id"], bundle["interpreter"]["id"], delivery_mode="IN_PERSON"
    )
    assert assignment["service_status"] == "PROPOSED", (
        f"the create does not consult the rate schedule, got "
        f"{assignment['service_status']}"
    )
    return config, bundle, hearing, assignment


def test_confirming_a_hearing_no_schedule_governs_is_refused(api):
    """PRD §3.7: "Exactly one rate schedule must be in effect for the date part of the hearing's `scheduled_start` — its `effective_from` at or before that date, and either a null `effective_through` or an `effective_through` at or on that date — and if none is, confirmation is refused with `ERR_RATE_SCHEDULE_NOT_EFFECTIVE`."
    PRD §3.7: "The claim is created in `ENCUMBERED` status with `variant` set to `PROVISIONAL` and its `provisional_total_cents` computed by the provisional arithmetic of §3.8; the courthouse's `encumbered_pay_cents` and `available_pay_cents` are recomputed; the hearing bubbles `SCHEDULED → COVERED`; and the assignment's `version` is incremented by 1."

    Design: Corner/Errors/confirm_with_no_schedule_in_effect_and_service_actions_out_of_order_are_rejected_then_a_new_schedule_unblocks_the_same_call
    """
    config, bundle, hearing, assignment = _uncovered_hearing_date_setup()

    response = api.confirm_assignment(
        assignment["id"], make_interpreter_headers(bundle["interpreter"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_RATE_SCHEDULE_NOT_EFFECTIVE, 409)
    after = fixtures.read_assignment(assignment["id"])
    assert after["service_status"] == "PROPOSED", (
        f"a refused confirm leaves the assignment PROPOSED, got {after['service_status']}"
    )
    _, meta = validate_paginated(api.list_pay_claims(FISCAL))
    assert meta["total_count"] == 0, (
        f"no claim may exist without a governing schedule, got {meta['total_count']}"
    )
    assert fixtures.read_hearing(hearing["id"])["status"] == "SCHEDULED", (
        "the hearing only bubbles to COVERED on a successful confirmation"
    )


def test_checking_in_a_proposed_assignment_is_refused_on_service_state(api):
    """PRD §3.7: "Checking in is the interpreter's own act and nobody else's, `CONFIRMED → CHECKED_IN`."
    PRD §2.12: "10. Assignment `service_status` admits the requested transition — otherwise `ERR_INVALID_ASSIGNMENT_STATE` (409). Applies to `POST /assignments/{id}/confirm`, `POST /assignments/{id}/decline`, `POST /assignments/{id}/check-in`, `POST /assignments/{id}/complete`, `POST /assignments/{id}/cancel`, and `POST /assignments/{id}/no-show`."

    Design: Corner/Errors/confirm_with_no_schedule_in_effect_and_service_actions_out_of_order_are_rejected_then_a_new_schedule_unblocks_the_same_call
    """
    config, bundle, hearing, assignment = _uncovered_hearing_date_setup()

    response = api.check_in_assignment(
        assignment["id"], make_interpreter_headers(bundle["interpreter"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE, 409)
    after = fixtures.read_assignment(assignment["id"])
    assert after["check_in_utc"] is None, (
        f"a refused check-in records no instant, got {after['check_in_utc']}"
    )


def test_completing_a_proposed_assignment_reports_state_not_the_pricing_error(api):
    """PRD §3.7: "For a rostered interpreter the path is `CHECKED_IN → COMPLETED` and `actual_end_utc` must be strictly after `check_in_utc`; for a vendor-served assignment the path is `CONFIRMED → COMPLETED` — there is no check-in for a vendor — and `actual_end_utc` must be strictly after the hearing's `scheduled_start`."
    PRD §2.12: "10. Assignment `service_status` admits the requested transition — otherwise `ERR_INVALID_ASSIGNMENT_STATE` (409). Applies to `POST /assignments/{id}/confirm`, `POST /assignments/{id}/decline`, `POST /assignments/{id}/check-in`, `POST /assignments/{id}/complete`, `POST /assignments/{id}/cancel`, and `POST /assignments/{id}/no-show`."
    PRD §2.12: "34. A rate schedule is in effect for the hearing's date — otherwise `ERR_RATE_SCHEDULE_NOT_EFFECTIVE` (409). Applies to `POST /assignments/{id}/confirm` and `POST /assignments/{id}/complete`."
    PRD §2.12: "The ladder is global — a check at a lower number always masks a check at a higher number — and it is the reason a request that is both unauthorized and malformed reports only the authorization failure."

    Design: Corner/Errors/confirm_with_no_schedule_in_effect_and_service_actions_out_of_order_are_rejected_then_a_new_schedule_unblocks_the_same_call
    """
    config, bundle, hearing, assignment = _uncovered_hearing_date_setup()

    # This call violates rung 10 and rung 34 at once; rung 10 owns the answer.
    response = api.complete_assignment(
        assignment["id"],
        complete_assignment_payload("2026-11-10T10:00:00.000Z"),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE, 409)


def test_publishing_a_schedule_that_covers_the_date_unblocks_the_same_confirm(api):
    """PRD §3.7: "Exactly one rate schedule must be in effect for the date part of the hearing's `scheduled_start` — its `effective_from` at or before that date, and either a null `effective_through` or an `effective_through` at or on that date — and if none is, confirmation is refused with `ERR_RATE_SCHEDULE_NOT_EFFECTIVE`."
    PRD §3.7: "That schedule's `id` is pinned onto a freshly created pay claim as `rate_schedule_id`, and a schedule published later never changes an existing claim."
    PRD §3.7: "The claim is created in `ENCUMBERED` status with `variant` set to `PROVISIONAL` and its `provisional_total_cents` computed by the provisional arithmetic of §3.8; the courthouse's `encumbered_pay_cents` and `available_pay_cents` are recomputed; the hearing bubbles `SCHEDULED → COVERED`; and the assignment's `version` is incremented by 1."
    PRD §3.8: "Then take the larger of that rounded figure and the rate schedule's `minimum_call_hours`; the result is `billable_hours`, always a multiple of 0.25 and always carried to two decimal places."
    PRD §3.8: "If the assignment's `delivery_mode` is anything other than `IN_PERSON`, or if the variant's one-way mileage is at or below the schedule's `travel_free_radius_miles`, the reimbursable mileage is 0."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less `obligated_pay_cents`."

    Design: Corner/Errors/confirm_with_no_schedule_in_effect_and_service_actions_out_of_order_are_rejected_then_a_new_schedule_unblocks_the_same_call
    """
    config, bundle, hearing, assignment = _uncovered_hearing_date_setup()
    refused = api.confirm_assignment(
        assignment["id"], make_interpreter_headers(bundle["interpreter"]["id"])
    )
    validate_error(refused, ApiErrorId.ERR_RATE_SCHEDULE_NOT_EFFECTIVE, 409)

    # 2026-10-01 onward abuts the 2026-01-01..2026-09-30 window without
    # overlapping it, so the second schedule is accepted.
    published = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(
                effective_from="2026-10-01",
                master_hourly_cents=11000,
                certified_hourly_cents=9000,
                registered_hourly_cents=6700,
                provisional_hourly_cents=5000,
                travel_mileage_rate_cents=70.0,
            ),
            ADMIN,
        ),
        201,
    )

    accepted = validate_success(
        api.confirm_assignment(
            assignment["id"], make_interpreter_headers(bundle["interpreter"]["id"])
        )
    )

    assert accepted["service_status"] == "CONFIRMED", (
        f"the identical confirm must now succeed, got {accepted['service_status']}"
    )
    claims, meta = validate_paginated(
        api.list_pay_claims(FISCAL, params={"assignment_id": assignment["id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected exactly 1 pay claim, got {meta['total_count']}"
    )
    claim = claims[0]
    assert claim["rate_schedule_id"] == published["id"], (
        f"the claim must pin the newly published schedule, "
        f"got {claim['rate_schedule_id']}"
    )
    assert claim["status"] == "ENCUMBERED", (
        f"expected ENCUMBERED, got {claim['status']}"
    )
    assert claim["variant"] == "PROVISIONAL", (
        f"expected variant PROVISIONAL, got {claim['variant']}"
    )
    assert claim["billable_hours"] == pytest.approx(2.0), (
        f"the 1-hour window lifts to the 2-hour minimum call, "
        f"got {claim['billable_hours']}"
    )
    assert claim["travel_cents"] == 0, (
        f"10 estimated miles sit inside the 30-mile free radius, "
        f"got {claim['travel_cents']}"
    )
    assert claim["provisional_total_cents"] == 18000, (
        f"expected 2.0 * 9000 == 18000, got {claim['provisional_total_cents']}"
    )
    courthouse = fixtures.read_courthouse(config["courthouse"]["id"])
    assert courthouse["encumbered_pay_cents"] == 18000, (
        f"expected encumbered_pay_cents 18000, "
        f"got {courthouse['encumbered_pay_cents']}"
    )
    assert courthouse["available_pay_cents"] == 4982000, (
        f"expected available_pay_cents 4982000, "
        f"got {courthouse['available_pay_cents']}"
    )


# ---------------------------------------------------------------------------
# Instance: an_appeal_filed_on_day_thirty_one_is_rejected_and_leaves_the_sanction_standing
# ---------------------------------------------------------------------------
APPEAL_GROUNDS = "The omitted admonitions were restated on the record by the court."


def _letter_sanction_setup():
    """Ana Reyes ACTIVE in spa, carrying one substantiated MINOR complaint that
    imposed a LETTER, adjudicated on the default clock date."""
    fixtures.set_clock()
    language = fixtures.bootstrap_language()
    bundle = fixtures.setup_active_interpreter(language["id"])
    sanction = fixtures.setup_sanction(
        bundle["interpreter"]["id"],
        "LETTER",
        severity="MINOR",
        category="ACCURACY",
        narrative="Party reports a materially inaccurate rendition of the plea colloquy.",
    )
    assert sanction["complaint"]["status"] == "SUBSTANTIATED", (
        f"setup expected SUBSTANTIATED, got {sanction['complaint']['status']}"
    )
    assert sanction["complaint"]["adjudicated_at"] == "2026-08-01T00:00:00.000Z", (
        f"expected adjudicated_at on the default clock, "
        f"got {sanction['complaint']['adjudicated_at']}"
    )
    return bundle, sanction


def test_an_appeal_filed_on_day_thirty_one_is_refused(api):
    """PRD §3.9: "The filing must fall within 30 days of `adjudicated_at`, measured on the logical clock, with day 30 exactly still inside the window and anything later refused as `ERR_APPEAL_WINDOW_EXPIRED`."
    PRD §3.9: "The interpreter supplies written `grounds`, and the complaint moves `SUBSTANTIATED → APPEALED` with `appeal_filed_at` recording the logical clock."

    Design: Corner/Errors/an_appeal_filed_on_day_thirty_one_is_rejected_and_leaves_the_sanction_standing
    """
    bundle, sanction = _letter_sanction_setup()
    complaint = sanction["complaint"]
    # Day 30 is 2026-08-31; this is day 31.
    fixtures.set_clock("2026-09-01T00:00:00.000Z")

    response = api.appeal_complaint(
        complaint["id"],
        appeal_complaint_payload(grounds=APPEAL_GROUNDS),
        make_interpreter_headers(bundle["interpreter"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, 409)
    after = fixtures.read_complaint(complaint["id"])
    assert after["status"] == "SUBSTANTIATED", (
        f"the refused appeal leaves the complaint SUBSTANTIATED, got {after['status']}"
    )
    assert after["appeal_filed_at"] is None, (
        f"no appeal instant may be recorded, got {after['appeal_filed_at']}"
    )
    assert after["remand_count"] == 0, (
        f"expected remand_count 0, got {after['remand_count']}"
    )


def test_a_refused_appeal_leaves_the_sanction_and_the_score_standing(api):
    """PRD §3.9: "The filing must fall within 30 days of `adjudicated_at`, measured on the logical clock, with day 30 exactly still inside the window and anything later refused as `ERR_APPEAL_WINDOW_EXPIRED`."
    PRD §3.9: "**Hop one** creates a single disciplinary action in `IN_EFFECT` status, recording `complaint_id` and copying `interpreter_id` from the complaint, with `action_type` set to the requested sanction and `points` taken from the sanction scale — 5 for a `LETTER`, 10 for `PROBATION`, 12 for a `SUSPENSION`, 20 for a `REVOCATION`."
    PRD §3.2: "Then `rolling_12_month_score` is 100 less four times the recent-points figure, floored at 0 so it never reports a negative number."

    Design: Corner/Errors/an_appeal_filed_on_day_thirty_one_is_rejected_and_leaves_the_sanction_standing
    """
    bundle, sanction = _letter_sanction_setup()
    complaint = sanction["complaint"]
    fixtures.set_clock("2026-09-01T00:00:00.000Z")

    refused = api.appeal_complaint(
        complaint["id"],
        appeal_complaint_payload(grounds=APPEAL_GROUNDS),
        make_interpreter_headers(bundle["interpreter"]["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, 409)

    actions, meta = validate_paginated(
        api.list_disciplinary_actions(REVIEWER, params={"complaint_id": complaint["id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected exactly 1 disciplinary action, got {meta['total_count']}"
    )
    action = actions[0]
    assert action["action_type"] == "LETTER", (
        f"expected action_type LETTER, got {action['action_type']}"
    )
    assert action["points"] == 5, f"expected 5 points for a LETTER, got {action['points']}"
    assert action["status"] == "IN_EFFECT", (
        f"a refused appeal reverses nothing, got {action['status']}"
    )
    assert action["effective_from"] == "2026-08-01", (
        f"expected effective_from 2026-08-01, got {action['effective_from']}"
    )
    score = fixtures.read_quality_score(bundle["interpreter"]["id"])
    assert score["complaint_points"] == 5, (
        f"expected complaint_points 5, got {score['complaint_points']}"
    )
    assert score["rolling_12_month_score"] == 80, (
        f"expected 100 - 4 * 5 == 80, got {score['rolling_12_month_score']}"
    )


def test_an_appeal_filed_on_day_thirty_is_accepted(api):
    """PRD §3.9: "The filing must fall within 30 days of `adjudicated_at`, measured on the logical clock, with day 30 exactly still inside the window and anything later refused as `ERR_APPEAL_WINDOW_EXPIRED`."
    PRD §3.9: "The interpreter supplies written `grounds`, and the complaint moves `SUBSTANTIATED → APPEALED` with `appeal_filed_at` recording the logical clock."
    PRD §3.9: "The disciplinary action stays `IN_EFFECT` while the appeal is pending, so an appealing interpreter remains suspended."

    Design: Corner/Errors/an_appeal_filed_on_day_thirty_one_is_rejected_and_leaves_the_sanction_standing
    """
    bundle, sanction = _letter_sanction_setup()
    complaint = sanction["complaint"]
    # Day 30 exactly, the last instant inside the window.
    fixtures.set_clock("2026-08-31T00:00:00.000Z")

    accepted = validate_success(
        api.appeal_complaint(
            complaint["id"],
            appeal_complaint_payload(grounds=APPEAL_GROUNDS),
            make_interpreter_headers(bundle["interpreter"]["id"]),
        )
    )

    assert accepted["status"] == "APPEALED", (
        f"day 30 is inside the window, got {accepted['status']}"
    )
    assert accepted["appeal_filed_at"] == "2026-08-31T00:00:00.000Z", (
        f"appeal_filed_at records the logical clock, got {accepted['appeal_filed_at']}"
    )
    action = fixtures.disciplinary_actions_for_complaint(complaint["id"])[0]
    assert action["status"] == "IN_EFFECT", (
        f"the action stays in effect while the appeal is pending, got {action['status']}"
    )
