"""Validation-ladder ordering and the conditional scheduling gates.

PRD §2.12 declares one global, numbered validation ladder, so the ordering
between two checks that a single request violates at once is contractual rather
than incidental: these tests pin rung 1 against rung 3, rung 2 against rung 3,
rung 3 against rung 4, and then exercise the aggregate budget rung (36), the
interpreter-ownership rung (6), the retake-wait rung (20) and the conditional
quality-floor rung (18) on both sides of their boundaries.

The server is relaunched before every test, so each test builds its own world.
"""

from test_helpers import (
    ApiErrorId,
    assert_envelope_meta,
    create_assignment_payload,
    create_language_payload,
    exam_attempt_payload,
    make_interpreter_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
import test_helpers.fixtures as fixtures

# An id in the right shape that resolves to no credential row.
ABSENT_CREDENTIAL_ID = "00000000-0000-4000-8000-00000000c0de"

# An id in the right shape that matches no Interpreter row.
ABSENT_INTERPRETER_ID = "00000000-0000-4000-8000-0000000000ff"


# ---------------------------------------------------------------------------
# Rung 1 — authentication, before every other check (PRD §2.1, §2.12)
# ---------------------------------------------------------------------------
def test_a_missing_role_header_and_an_empty_user_id_are_both_unauthenticated(
    api, program_admin_headers
):
    """PRD §2.1: "If either header is absent, empty, or if `X-User-Role` names anything other than one of the six roles enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."
    PRD §2.12: "1. Authentication: both headers present, `X-User-ID` non-empty, and `X-User-Role` naming one of the six declared roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    Design: Corner/Validations/requests_with_no_role_or_no_user_header_are_unauthenticated_before_every_other_check
    """
    no_role = {"X-User-ID": "pa-001", "Content-Type": "application/json"}
    empty_user_id = {
        "X-User-ID": "",
        "X-User-Role": "ProgramAdmin",
        "Content-Type": "application/json",
    }

    missing_role_response = api.create_language(create_language_payload(), no_role)
    validate_error(missing_role_response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert_envelope_meta(missing_role_response.json())

    empty_id_response = api.list_interpreters(empty_user_id)
    validate_error(empty_id_response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert_envelope_meta(empty_id_response.json())

    _rows, meta = validate_paginated(api.list_languages(program_admin_headers))
    assert meta["total_count"] == 0, (
        f"expected no language created by an unauthenticated call, got "
        f"{meta['total_count']}"
    )


def test_an_unknown_role_reports_unauthenticated_rather_than_the_malformed_body(
    api, program_admin_headers
):
    """PRD §2.1: "If either header is absent, empty, or if `X-User-Role` names anything other than one of the six roles enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."
    PRD §2.12: "The ladder is global — a check at a lower number always masks a check at a higher number — and it is the reason a request that is both unauthorized and malformed reports only the authorization failure."
    PRD §2.12: "3. Request shape: unknown value types, malformed dates or datetimes, enum values outside the declared set, negative money or mileage, non-positive counts, a `limit` outside 1 through 100, a negative `offset`, a `scheduled_end` at or before `scheduled_start`, a `period_end` at or before `period_start`, and any missing required input field — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

    Design: Corner/Validations/requests_with_no_role_or_no_user_header_are_unauthenticated_before_every_other_check
    """
    unknown_role = {
        "X-User-ID": "pa-001",
        "X-User-Role": "NotADeclaredRole",
        "Content-Type": "application/json",
    }
    malformed_body = create_language_payload(tier_class="NOT_A_TIER_CLASS")

    response = api.create_language(malformed_body, unknown_role)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert_envelope_meta(response.json())

    _rows, meta = validate_paginated(api.list_languages(program_admin_headers))
    assert meta["total_count"] == 0, (
        f"expected no language created by an unauthenticated call, got "
        f"{meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Rung 2 masks rung 3 (PRD §2.1, §2.12)
# ---------------------------------------------------------------------------
def _malformed_hearing_body(courthouse_id, language_id):
    """An inverted scheduled window and no case_number at all."""
    return {
        "courthouse_id": courthouse_id,
        "language_id": language_id,
        "hearing_type": "MOTION",
        "in_custody": False,
        "scheduled_start": "2026-08-25T11:00:00.000Z",
        "scheduled_end": "2026-08-25T10:00:00.000Z",
        "requested_delivery_mode": "IN_PERSON",
    }


def test_a_wrong_role_with_a_malformed_body_never_reaches_the_shape_check(
    api, credentialing_officer_headers, scheduling_coordinator_headers
):
    """PRD §2.1: "When the headers are well formed but the named role is not among the roles authorized for the requested endpoint (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.12: "2. Authorization: the acting role appears in the endpoint's authorized-role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
    PRD §2.12: "The ladder is global — a check at a lower number always masks a check at a higher number — and it is the reason a request that is both unauthorized and malformed reports only the authorization failure."

    Design: Corner/Validations/wrong_role_with_a_malformed_body_cannot_reach_the_shape_check
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    body = _malformed_hearing_body(
        config["courthouse"]["id"], config["language"]["id"]
    )

    response = api.create_hearing(body, credentialing_officer_headers)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, 403)

    _rows, meta = validate_paginated(api.list_hearings(scheduling_coordinator_headers))
    assert meta["total_count"] == 0, (
        f"expected no hearing created by a refused call, got {meta['total_count']}"
    )


def test_the_same_malformed_body_reaches_the_shape_check_for_the_authorized_role(
    api, scheduling_coordinator_headers
):
    """PRD §2.12: "3. Request shape: unknown value types, malformed dates or datetimes, enum values outside the declared set, negative money or mileage, non-positive counts, a `limit` outside 1 through 100, a negative `offset`, a `scheduled_end` at or before `scheduled_start`, a `period_end` at or before `period_start`, and any missing required input field — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    PRD §2.12: "When a single request could fail several checks at once, exactly one error is returned: the first failure in the ordered ladder below."

    Design: Corner/Validations/wrong_role_with_a_malformed_body_cannot_reach_the_shape_check
    """
    config = fixtures.setup_program_config(with_rate_schedule=False)
    body = _malformed_hearing_body(
        config["courthouse"]["id"], config["language"]["id"]
    )

    response = api.create_hearing(body, scheduling_coordinator_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(api.list_hearings(scheduling_coordinator_headers))
    assert meta["total_count"] == 0, (
        f"expected no hearing created by a refused call, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Rung 3 masks rung 4 (PRD §2.6, §2.12)
# ---------------------------------------------------------------------------
def test_an_enum_outside_the_declared_set_outranks_an_unknown_credential_id(
    api, credentialing_officer_headers
):
    """PRD §2.12: "3. Request shape: unknown value types, malformed dates or datetimes, enum values outside the declared set, negative money or mileage, non-positive counts, a `limit` outside 1 through 100, a negative `offset`, a `scheduled_end` at or before `scheduled_start`, a `period_end` at or before `period_start`, and any missing required input field — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    PRD §2.12: "4. Path existence: every `id` path segment resolves, left to right, mapped to the not-found codes listed in §2.6. Applies to every endpoint carrying a path parameter."
    PRD §3.3: "A `CredentialingOfficer` records an attempt against a credential by supplying `exam_type` (`WRITTEN` or `ORAL`), a raw `score` between 0 and 100 inclusive, and `taken_on`, the date the examination was sat."

    Design: Corner/Validations/invalid_payload_outranks_an_unknown_path_id_on_the_ladder
    """
    response = api.create_exam_attempt(
        ABSENT_CREDENTIAL_ID,
        exam_attempt_payload(exam_type="SIGHT_TRANSLATION", score=84,
                             taken_on="2026-08-01"),
        credentialing_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_a_well_formed_body_then_reports_the_unknown_credential_id(
    api, credentialing_officer_headers
):
    """PRD §2.12: "4. Path existence: every `id` path segment resolves, left to right, mapped to the not-found codes listed in §2.6. Applies to every endpoint carrying a path parameter."
    PRD §2.6: "Path parameters are resolved strictly left to right, and the first segment that fails to resolve determines the error. An unresolvable interpreter segment yields `ERR_INTERPRETER_NOT_FOUND`; a credential segment, `ERR_CREDENTIAL_NOT_FOUND`; a hearing segment, `ERR_HEARING_NOT_FOUND`; an assignment segment, `ERR_ASSIGNMENT_NOT_FOUND`; a pay-claim segment, `ERR_PAY_CLAIM_NOT_FOUND`; a complaint segment, `ERR_COMPLAINT_NOT_FOUND`; a disciplinary-action segment, `ERR_DISCIPLINARY_ACTION_NOT_FOUND`; and a courthouse segment, `ERR_CONFIG_RESOURCE_NOT_FOUND`. All eight are HTTP 404."

    Design: Corner/Validations/invalid_payload_outranks_an_unknown_path_id_on_the_ladder
    """
    response = api.create_exam_attempt(
        ABSENT_CREDENTIAL_ID,
        exam_attempt_payload(exam_type="WRITTEN", score=84, taken_on="2026-08-01"),
        credentialing_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_CREDENTIAL_NOT_FOUND, 404)


def test_a_score_outside_the_declared_range_is_caught_before_path_existence(
    api, credentialing_officer_headers
):
    """PRD §3.3: "A `CredentialingOfficer` records an attempt against a credential by supplying `exam_type` (`WRITTEN` or `ORAL`), a raw `score` between 0 and 100 inclusive, and `taken_on`, the date the examination was sat."
    PRD §2.12: "3. Request shape: unknown value types, malformed dates or datetimes, enum values outside the declared set, negative money or mileage, non-positive counts, a `limit` outside 1 through 100, a negative `offset`, a `scheduled_end` at or before `scheduled_start`, a `period_end` at or before `period_start`, and any missing required input field — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."
    PRD §2.12: "The ladder is global — a check at a lower number always masks a check at a higher number — and it is the reason a request that is both unauthorized and malformed reports only the authorization failure."

    Design: Corner/Validations/invalid_payload_outranks_an_unknown_path_id_on_the_ladder
    """
    response = api.create_exam_attempt(
        ABSENT_CREDENTIAL_ID,
        exam_attempt_payload(exam_type="WRITTEN", score=140, taken_on="2026-08-01"),
        credentialing_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


# ---------------------------------------------------------------------------
# Rung 36 — aggregate budget headroom (PRD §2.9, §3.7)
# ---------------------------------------------------------------------------
def _tight_budget_world():
    """One courthouse whose budget covers exactly two minimum-call CERTIFIED
    assignments, and three individually affordable proposals against it."""
    config = fixtures.setup_program_config(
        courthouse_overrides={
            "name": "Rural Branch Courthouse",
            "county_code": "RUR",
            "courtroom_count": 2,
            "remote_equipment_tier": "BASIC",
            "vri_concurrent_capacity": 1,
            "pay_budget_cents": 35000,
        }
    )
    active = fixtures.setup_active_interpreter(
        config["language"]["id"],
        target_tier="CERTIFIED",
        interpreter_overrides={"home_county_code": "RUR"},
    )
    assignments = []
    for index, day in enumerate(("25", "26", "27"), start=1):
        hearing = fixtures.schedule_hearing(
            config["courthouse"]["id"],
            config["language"]["id"],
            case_number=f"CR-2026-150{index}",
            hearing_type="MOTION",
            in_custody=False,
            scheduled_start=f"2026-08-{day}T09:00:00.000Z",
            scheduled_end=f"2026-08-{day}T10:00:00.000Z",
            requested_delivery_mode="IN_PERSON",
        )
        assignments.append(
            fixtures.propose_assignment(
                hearing["id"],
                interpreter_id=active["interpreter"]["id"],
                delivery_mode="IN_PERSON",
                estimated_one_way_miles=5.0,
            )
        )
    return config, active, assignments


def test_a_provisional_total_exactly_equal_to_the_remainder_is_confirmed(api):
    """PRD §2.9: "Budget checks are inclusive at the boundary. A confirmation whose provisional total is exactly equal to the courthouse's `available_pay_cents` is accepted; only an amount strictly greater than the remainder is refused, with `ERR_COURTHOUSE_BUDGET_EXCEEDED` (HTTP 409)."
    PRD §2.9: "`available_pay_cents` is `pay_budget_cents` less `encumbered_pay_cents` less `obligated_pay_cents`."

    Design: Corner/Validations/aggregate_budget_accepts_the_exact_remainder_then_rejects_the_next_confirm
    """
    config, active, assignments = _tight_budget_world()
    interpreter_headers = make_interpreter_headers(active["interpreter"]["id"])

    first = validate_success(
        api.confirm_assignment(assignments[0]["id"], interpreter_headers)
    )
    assert first["service_status"] == "CONFIRMED", (
        f"expected CONFIRMED, got {first['service_status']} on the first confirm"
    )

    after_first = fixtures.read_courthouse(config["courthouse"]["id"])
    assert after_first["encumbered_pay_cents"] == 17500, (
        f"expected 17500 encumbered, got {after_first['encumbered_pay_cents']}"
    )
    assert after_first["available_pay_cents"] == 17500, (
        f"expected 17500 available, got {after_first['available_pay_cents']}"
    )

    second = validate_success(
        api.confirm_assignment(assignments[1]["id"], interpreter_headers)
    )
    assert second["service_status"] == "CONFIRMED", (
        f"expected the exact-remainder confirm to be accepted, got "
        f"{second['service_status']}"
    )

    after_second = fixtures.read_courthouse(config["courthouse"]["id"])
    assert after_second["encumbered_pay_cents"] == 35000, (
        f"expected 35000 encumbered, got {after_second['encumbered_pay_cents']}"
    )
    assert after_second["obligated_pay_cents"] == 0, (
        f"expected 0 obligated, got {after_second['obligated_pay_cents']}"
    )
    assert after_second["available_pay_cents"] == 0, (
        f"expected the remainder to be spent to 0, got "
        f"{after_second['available_pay_cents']}"
    )


def test_the_next_confirm_past_an_exhausted_budget_is_refused_and_creates_nothing(
    api, fiscal_officer_headers
):
    """PRD §3.7: "If the provisional total exceeds `available_pay_cents` the confirmation is refused with `ERR_COURTHOUSE_BUDGET_EXCEEDED` and nothing is created."
    PRD §2.12: "36. The courthouse has budget headroom — otherwise `ERR_COURTHOUSE_BUDGET_EXCEEDED` (409). Applies to `POST /assignments/{id}/confirm` and `POST /assignments/{id}/complete`."
    PRD §2.9: "`encumbered_pay_cents` is the sum of `provisional_total_cents` over every pay claim whose `status` is `ENCUMBERED` and whose assignment's hearing sits at this courthouse."

    Design: Corner/Validations/aggregate_budget_accepts_the_exact_remainder_then_rejects_the_next_confirm
    """
    config, active, assignments = _tight_budget_world()
    interpreter_headers = make_interpreter_headers(active["interpreter"]["id"])

    validate_success(api.confirm_assignment(assignments[0]["id"], interpreter_headers))
    validate_success(api.confirm_assignment(assignments[1]["id"], interpreter_headers))

    refused = api.confirm_assignment(assignments[2]["id"], interpreter_headers)
    validate_error(refused, ApiErrorId.ERR_COURTHOUSE_BUDGET_EXCEEDED, 409)

    third = fixtures.read_assignment(assignments[2]["id"])
    assert third["service_status"] == "PROPOSED", (
        f"expected the refused assignment to stay PROPOSED, got "
        f"{third['service_status']}"
    )

    _rows, unclaimed = validate_paginated(
        api.list_pay_claims(
            fiscal_officer_headers, {"assignment_id": assignments[2]["id"]}
        )
    )
    assert unclaimed["total_count"] == 0, (
        f"expected no claim for the refused confirm, got {unclaimed['total_count']}"
    )

    _rows, encumbered = validate_paginated(
        api.list_pay_claims(fiscal_officer_headers, {"status": "ENCUMBERED"})
    )
    assert encumbered["total_count"] == 2, (
        f"expected exactly 2 encumbered claims, got {encumbered['total_count']}"
    )

    ledger = fixtures.read_courthouse(config["courthouse"]["id"])
    assert ledger["encumbered_pay_cents"] == 35000, (
        f"expected 35000 encumbered, got {ledger['encumbered_pay_cents']}"
    )
    assert ledger["available_pay_cents"] == 0, (
        f"expected 0 available, got {ledger['available_pay_cents']}"
    )


# ---------------------------------------------------------------------------
# Rung 6 — interpreter-role ownership (PRD §2.1, §2.12)
# ---------------------------------------------------------------------------
def _one_proposed_assignment_and_a_bystander():
    """A1 is PROPOSED to i1; i2 is a rostered interpreter who is not the assignee."""
    config = fixtures.setup_program_config()
    active = fixtures.setup_active_interpreter(
        config["language"]["id"], target_tier="CERTIFIED"
    )
    bystander = fixtures.enrol_interpreter(
        full_name="Bo Lim", email="bo.lim@courts.example.gov", home_county_code="CAS"
    )
    hearing = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-1601",
        hearing_type="MOTION",
        in_custody=False,
        scheduled_start="2026-08-25T09:00:00.000Z",
        scheduled_end="2026-08-25T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    assignment = fixtures.propose_assignment(
        hearing["id"],
        interpreter_id=active["interpreter"]["id"],
        delivery_mode="IN_PERSON",
        estimated_one_way_miles=5.0,
    )
    return active, bystander, assignment


def test_a_rostered_bystander_interpreter_cannot_confirm_the_assignees_work(
    api, fiscal_officer_headers
):
    """PRD §2.1: "Concretely, an `Interpreter` caller acting on an assignment must be that assignment's `interpreter_id`; acting on a pay claim, the claim's assignment's `interpreter_id`; acting on a complaint, the complaint's `interpreter_id`. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.12: "6. Interpreter-role ownership: an `Interpreter` caller's `X-User-ID` matches the target resource's interpreter — otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to `POST /assignments/{id}/confirm`, `POST /assignments/{id}/decline`, `POST /assignments/{id}/check-in`, `POST /assignments/{id}/complete`, `POST /pay-claims/{id}/submit`, and `POST /complaints/{id}/appeal`."

    Design: Corner/Validations/another_interpreter_cannot_confirm_someone_elses_assignment
    """
    _active, bystander, assignment = _one_proposed_assignment_and_a_bystander()

    refused = api.confirm_assignment(
        assignment["id"], make_interpreter_headers(bystander["id"])
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    unchanged = fixtures.read_assignment(assignment["id"])
    assert unchanged["service_status"] == "PROPOSED", (
        f"expected the assignment to stay PROPOSED, got "
        f"{unchanged['service_status']}"
    )

    _rows, meta = validate_paginated(
        api.list_pay_claims(fiscal_officer_headers, {"assignment_id": assignment["id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected no claim after a refused confirm, got {meta['total_count']}"
    )


def test_an_x_user_id_matching_no_interpreter_row_is_not_the_owner_either(
    api, fiscal_officer_headers
):
    """PRD §2.1: "When `X-User-Role` is `Interpreter`, `X-User-ID` is the `id` of the acting `Interpreter` row; ownership checks on any resource that references an `Interpreter` compare that resource's interpreter foreign-key field to `X-User-ID`."
    PRD §2.12: "6. Interpreter-role ownership: an `Interpreter` caller's `X-User-ID` matches the target resource's interpreter — otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to `POST /assignments/{id}/confirm`, `POST /assignments/{id}/decline`, `POST /assignments/{id}/check-in`, `POST /assignments/{id}/complete`, `POST /pay-claims/{id}/submit`, and `POST /complaints/{id}/appeal`."
    PRD §3.7: "The claim is created in `ENCUMBERED` status with `variant` set to `PROVISIONAL` and its `provisional_total_cents` computed by the provisional arithmetic of §3.8; the courthouse's `encumbered_pay_cents` and `available_pay_cents` are recomputed; the hearing bubbles `SCHEDULED → COVERED`; and the assignment's `version` is incremented by 1."

    Design: Corner/Validations/another_interpreter_cannot_confirm_someone_elses_assignment
    """
    active, _bystander, assignment = _one_proposed_assignment_and_a_bystander()

    refused = api.confirm_assignment(
        assignment["id"], make_interpreter_headers(ABSENT_INTERPRETER_ID)
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    accepted = validate_success(
        api.confirm_assignment(
            assignment["id"],
            make_interpreter_headers(active["interpreter"]["id"]),
        )
    )
    assert accepted["service_status"] == "CONFIRMED", (
        f"expected the true owner's confirm to succeed, got "
        f"{accepted['service_status']}"
    )

    rows, meta = validate_paginated(
        api.list_pay_claims(fiscal_officer_headers, {"assignment_id": assignment["id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected exactly one claim after the owner's confirm, got "
        f"{meta['total_count']}"
    )
    assert rows[0]["provisional_total_cents"] == 17500, (
        f"expected 17500 provisional cents, got {rows[0]['provisional_total_cents']}"
    )


# ---------------------------------------------------------------------------
# Rung 20 — the retake waiting period (PRD §3.3, §2.12)
# ---------------------------------------------------------------------------
def _credential_with_one_failed_written_attempt():
    """A CERTIFIED spa credential in PENDING_WRITTEN whose only WRITTEN attempt
    scored 72 on 2026-08-01 — below the CERTIFIED written floor of 80."""
    language = fixtures.bootstrap_language()
    interpreter = fixtures.enrol_interpreter(home_county_code="CAS")
    credential = fixtures.open_credential(
        interpreter["id"], language["id"], target_tier="CERTIFIED"
    )
    first = fixtures.record_exam_attempt(
        credential["id"], exam_type="WRITTEN", score=72, taken_on="2026-08-01"
    )
    assert first["result"] == "FAIL", (
        f"expected 72 to FAIL the CERTIFIED written floor of 80, got "
        f"{first['result']}"
    )
    assert first["attempt_ordinal"] == 1, (
        f"expected attempt_ordinal 1, got {first['attempt_ordinal']}"
    )
    after = fixtures.read_credential(credential["id"])
    assert after["written_attempt_count"] == 1, (
        f"expected written_attempt_count 1, got {after['written_attempt_count']}"
    )
    assert after["written_best_score"] == 72, (
        f"expected written_best_score 72, got {after['written_best_score']}"
    )
    assert after["status"] == "PENDING_WRITTEN", (
        f"expected the credential to stay PENDING_WRITTEN, got {after['status']}"
    )
    return language, credential


def test_a_retake_eighty_nine_days_after_the_failure_is_refused(
    api, credentialing_officer_headers
):
    """PRD §3.3: "And a candidate who has failed must wait: the supplied `taken_on` must be at least 90 days after the `taken_on` of the most recent failed attempt of the same exam type on this credential, with a gap of exactly 90 days accepted and anything shorter refused as `ERR_EXAM_RETAKE_TOO_SOON`."
    PRD §2.12: "20. The retake waiting period has elapsed — otherwise `ERR_EXAM_RETAKE_TOO_SOON` (409). Applies to `POST /credentials/{id}/exam-attempts`."

    Design: Corner/Validations/exam_retake_wait_refuses_day_eighty_nine_and_accepts_day_ninety
    """
    _language, credential = _credential_with_one_failed_written_attempt()
    fixtures.set_clock(to_iso8601="2026-10-29T00:00:00Z")

    refused = api.create_exam_attempt(
        credential["id"],
        exam_attempt_payload(exam_type="WRITTEN", score=84, taken_on="2026-10-29"),
        credentialing_officer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_EXAM_RETAKE_TOO_SOON, 409)

    unchanged = fixtures.read_credential(credential["id"])
    assert unchanged["written_attempt_count"] == 1, (
        f"expected the refused attempt not to count, got "
        f"{unchanged['written_attempt_count']}"
    )
    assert unchanged["written_best_score"] == 72, (
        f"expected written_best_score to stay 72, got "
        f"{unchanged['written_best_score']}"
    )
    assert unchanged["status"] == "PENDING_WRITTEN", (
        f"expected PENDING_WRITTEN, got {unchanged['status']}"
    )


def test_a_retake_exactly_ninety_days_after_the_failure_is_accepted(
    api, credentialing_officer_headers
):
    """PRD §3.3: "And a candidate who has failed must wait: the supplied `taken_on` must be at least 90 days after the `taken_on` of the most recent failed attempt of the same exam type on this credential, with a gap of exactly 90 days accepted and anything shorter refused as `ERR_EXAM_RETAKE_TOO_SOON`."
    PRD §3.3: "Recording an attempt writes `credential_id` from the credential the attempt is filed under, derives `attempt_ordinal` as the 1-based index of this attempt among the credential's attempts of the *same* `exam_type` ordered by `taken_on` ascending and then `created_at` ascending, and derives `result` as `PASS` when the score reaches the passing floor for the credential's target tier and this exam type and `FAIL` otherwise."
    PRD §3.3: "The written floor is 90 for a `MASTER` target and 80 for every other target."

    Design: Corner/Validations/exam_retake_wait_refuses_day_eighty_nine_and_accepts_day_ninety
    """
    _language, credential = _credential_with_one_failed_written_attempt()
    fixtures.set_clock(to_iso8601="2026-10-30T00:00:00Z")

    accepted = validate_success(
        api.create_exam_attempt(
            credential["id"],
            exam_attempt_payload(exam_type="WRITTEN", score=84, taken_on="2026-10-30"),
            credentialing_officer_headers,
        ),
        expected_status=201,
    )
    assert accepted["result"] == "PASS", (
        f"expected 84 to PASS the written floor of 80, got {accepted['result']}"
    )
    assert accepted["attempt_ordinal"] == 2, (
        f"expected attempt_ordinal 2, got {accepted['attempt_ordinal']}"
    )

    refreshed = fixtures.read_credential(credential["id"])
    assert refreshed["written_attempt_count"] == 2, (
        f"expected written_attempt_count 2, got {refreshed['written_attempt_count']}"
    )
    assert refreshed["written_best_score"] == 84, (
        f"expected written_best_score 84, got {refreshed['written_best_score']}"
    )

    _rows, meta = validate_paginated(
        api.list_exam_attempts(
            credential["id"], credentialing_officer_headers, {"exam_type": "WRITTEN"}
        )
    )
    assert meta["total_count"] == 2, (
        f"expected 2 persisted WRITTEN attempts, got {meta['total_count']}"
    )


def test_a_written_failure_never_gates_an_oral_attempt(
    api, credentialing_officer_headers
):
    """PRD §3.3: "And a candidate who has failed must wait: the supplied `taken_on` must be at least 90 days after the `taken_on` of the most recent failed attempt of the same exam type on this credential, with a gap of exactly 90 days accepted and anything shorter refused as `ERR_EXAM_RETAKE_TOO_SOON`."
    PRD §3.3: "The oral floor is 85 for a `MASTER` target and 70 for a `CERTIFIED` target."
    PRD §3.3: "Each recorded attempt refreshes the credential's best score for that exam type — `written_best_score` and `oral_best_score` each hold the highest `score` seen across that type's attempts, remaining null while no attempt of that type exists — increments the matching `written_attempt_count` or `oral_attempt_count`, and increments the credential's `version` by 1."

    Design: Corner/Validations/exam_retake_wait_refuses_day_eighty_nine_and_accepts_day_ninety
    """
    _language, credential = _credential_with_one_failed_written_attempt()
    fixtures.set_clock(to_iso8601="2026-10-29T00:00:00Z")

    oral = validate_success(
        api.create_exam_attempt(
            credential["id"],
            exam_attempt_payload(exam_type="ORAL", score=71, taken_on="2026-10-29"),
            credentialing_officer_headers,
        ),
        expected_status=201,
    )
    assert oral["result"] == "PASS", (
        f"expected 71 to PASS the CERTIFIED oral floor of 70, got {oral['result']}"
    )
    assert oral["attempt_ordinal"] == 1, (
        f"expected the first ORAL attempt to be ordinal 1, got "
        f"{oral['attempt_ordinal']}"
    )

    refreshed = fixtures.read_credential(credential["id"])
    assert refreshed["oral_attempt_count"] == 1, (
        f"expected oral_attempt_count 1, got {refreshed['oral_attempt_count']}"
    )
    assert refreshed["oral_best_score"] == 71, (
        f"expected oral_best_score 71, got {refreshed['oral_best_score']}"
    )
    assert refreshed["written_attempt_count"] == 1, (
        f"expected the WRITTEN counters untouched, got "
        f"{refreshed['written_attempt_count']}"
    )


# ---------------------------------------------------------------------------
# Rung 18 — the class-A-only quality floor (PRD §3.6, §2.12)
# ---------------------------------------------------------------------------
def _sanctioned_interpreter_at_forty():
    """One ACTIVE CERTIFIED interpreter whose two substantiated complaints
    (PROBATION 10 + LETTER 5) put rolling_12_month_score at 100 - 4 x 15 == 40."""
    config = fixtures.setup_program_config()
    active = fixtures.setup_active_interpreter(
        config["language"]["id"], target_tier="CERTIFIED"
    )
    interpreter_id = active["interpreter"]["id"]
    fixtures.setup_sanction(
        interpreter_id,
        "PROBATION",
        severity="MAJOR",
        category="ACCURACY",
        narrative="Material omission in a plea colloquy.",
    )
    fixtures.setup_sanction(
        interpreter_id,
        "LETTER",
        severity="MINOR",
        category="PROFESSIONALISM",
        narrative="Arrived without the glossary agreed with counsel.",
    )
    scored = fixtures.read_interpreter(interpreter_id)
    assert scored["roster_status"] == "ACTIVE", (
        f"expected the interpreter to stay ACTIVE, got {scored['roster_status']}"
    )
    assert scored["complaint_points"] == 15, (
        f"expected complaint_points 15, got {scored['complaint_points']}"
    )
    assert scored["rolling_12_month_score"] == 40, (
        f"expected rolling_12_month_score 40, got "
        f"{scored['rolling_12_month_score']}"
    )
    return config, active


def test_a_class_c_hearing_consults_no_quality_floor_at_all(api):
    """PRD §3.6: "If the hearing's `priority_class` is `A`, their `rolling_12_month_score` must be at least 60; for class `B` and class `C` hearings no quality threshold applies."
    PRD §3.5: "From it the program derives `priority_class`: `A` when `priority_score` is 80 or more, `B` when it is 55 or more but below 80, and `C` otherwise."
    PRD §3.2: "Then `rolling_12_month_score` is 100 less four times the recent-points figure, floored at 0 so it never reports a negative number."

    Design: Corner/Validations/quality_floor_applies_only_to_class_a_hearings_and_leaves_class_c_open
    """
    config, active = _sanctioned_interpreter_at_forty()

    class_c = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-1701",
        hearing_type="MOTION",
        in_custody=False,
        scheduled_start="2026-08-25T09:00:00.000Z",
        scheduled_end="2026-08-25T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    assert class_c["priority_class"] == "C", (
        f"expected a class C hearing, got {class_c['priority_class']}"
    )

    proposed = fixtures.propose_assignment(
        class_c["id"],
        interpreter_id=active["interpreter"]["id"],
        delivery_mode="IN_PERSON",
        estimated_one_way_miles=5.0,
    )
    assert proposed["service_status"] == "PROPOSED", (
        f"expected PROPOSED on a class C hearing, got {proposed['service_status']}"
    )


def test_the_same_interpreter_is_refused_on_a_class_a_hearing(
    api, scheduling_coordinator_headers
):
    """PRD §3.6: "If the hearing's `priority_class` is `A`, their `rolling_12_month_score` must be at least 60; for class `B` and class `C` hearings no quality threshold applies."
    PRD §2.12: "18. The interpreter's rolling quality score clears the assignment floor for a top-priority hearing — otherwise `ERR_QUALITY_SCORE_BELOW_ASSIGNMENT_FLOOR` (409). Applies to `POST /assignments`."
    PRD §3.6: "When no interpreter qualifies the read succeeds with HTTP 200 and an empty array rather than an error — the rare-language unmet-need case the program exists to measure — and the hearing simply stays `SCHEDULED` until the daily run marks it unmet."

    Design: Corner/Validations/quality_floor_applies_only_to_class_a_hearings_and_leaves_class_c_open
    """
    config, active = _sanctioned_interpreter_at_forty()

    class_a = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-1702",
        hearing_type="ARRAIGNMENT",
        in_custody=True,
        scheduled_start="2026-08-01T09:00:00.000Z",
        scheduled_end="2026-08-01T10:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    assert class_a["priority_score"] == 95, (
        f"expected priority_score 95, got {class_a['priority_score']}"
    )
    assert class_a["priority_class"] == "A", (
        f"expected a class A hearing, got {class_a['priority_class']}"
    )

    refused = api.create_assignment(
        create_assignment_payload(
            class_a["id"],
            class_a["version"],
            active["interpreter"]["id"],
            delivery_mode="IN_PERSON",
            estimated_one_way_miles=5.0,
        ),
        scheduling_coordinator_headers,
    )
    validate_error(
        refused, ApiErrorId.ERR_QUALITY_SCORE_BELOW_ASSIGNMENT_FLOOR, 409
    )

    unchanged = fixtures.read_hearing(class_a["id"])
    assert unchanged["status"] == "SCHEDULED", (
        f"expected the hearing to stay SCHEDULED, got {unchanged['status']}"
    )

    _rows, meta = validate_paginated(
        api.list_assignments(
            scheduling_coordinator_headers, {"hearing_id": class_a["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"expected no assignment on the refused class A hearing, got "
        f"{meta['total_count']}"
    )

    pool, pool_meta = validate_paginated(
        api.list_eligible_interpreters(class_a["id"], scheduling_coordinator_headers)
    )
    assert pool == [], (
        f"expected the ranking filter to drop the interpreter too, got {pool}"
    )
    assert pool_meta["total_count"] == 0, (
        f"expected an empty eligible pool, got {pool_meta['total_count']}"
    )
