"""Submission intake gates: consent, residency, content, quota, supersede (PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_integration,
    create_assignment,
    create_institution,
    create_instructor,
    create_student,
    grant_consent,
    make_instructor_headers,
    make_student_headers,
    process,
    setup_basic_scenario,
    submit,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_consent,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INST_ADMIN = TEST_USERS["institutional_admin_headers"]


def test_intake_strict_consent_missing_rejected(api):
    """PRD §3.4: "The consent gate — when the integration's
    `consent_enforcement` is `STRICT`, the student's `consent_status` must be
    `GRANTED`; when it is `LENIENT`, `NOT_GIVEN` is tolerated but `WITHDRAWN` is
    not. Failure is `ERR_CONSENT_MISSING` (HTTP 422)."

    Design: Corner/validations/intake_strict_consent_missing_rejected
    """
    # STRICT is the integration default; the student's consent stays NOT_GIVEN.
    inst, integ, instr, student, asg = setup_basic_scenario("US", consent=False)
    resp = api.create_submission(
        asg["id"],
        {"student_id": student["id"], "content_text": "no consent given"},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_MISSING, expected_status=422)
    data, meta = validate_paginated(api.list_submissions_of_assignment(asg["id"], INST_ADMIN))
    assert data == [], "no submission may be persisted when the consent gate fails"


def test_intake_lenient_allows_not_given_but_rejects_withdrawn(api):
    """PRD §3.4: "The consent gate — when the integration's
    `consent_enforcement` is `STRICT`, the student's `consent_status` must be
    `GRANTED`; when it is `LENIENT`, `NOT_GIVEN` is tolerated but `WITHDRAWN` is
    not. Failure is `ERR_CONSENT_MISSING` (HTTP 422)."

    Design: Corner/validations/intake_lenient_allows_not_given_but_rejects_withdrawn
    """
    inst = create_institution(name="Len U", residency_region="US")
    integ = create_active_integration(inst["id"], external_key="c12", consent_enforcement="LENIENT")
    instr = create_instructor(inst["id"])
    stu_ng = create_student(inst["id"], external_lms_id="sng")
    stu_wd = create_student(inst["id"], external_lms_id="swd")
    updated = grant_consent(stu_wd["id"], stu_wd["version"])
    withdraw_consent(stu_wd["id"], updated["version"])
    asg = create_assignment(integ["id"], instr["id"], title="Len")

    ok = api.create_submission(
        asg["id"],
        {"student_id": stu_ng["id"], "content_text": "lenient not given"},
        make_student_headers(stu_ng["id"]),
    )
    validate_success(ok, expected_status=201)

    bad = api.create_submission(
        asg["id"],
        {"student_id": stu_wd["id"], "content_text": "lenient withdrawn"},
        make_student_headers(stu_wd["id"]),
    )
    validate_error(bad, ApiErrorId.ERR_CONSENT_MISSING, expected_status=422)


def test_residency_violation_when_locked(api):
    """PRD §3.4: "Data residency — when the institution's
    `data_residency_locked` is true, the student's `home_region` must equal the
    institution's `residency_region`, else `ERR_RESIDENCY_VIOLATION` (HTTP 422)."

    Design: Corner/validations/residency_violation_when_locked
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "EU", inst_overrides={"data_residency_locked": True}, student_overrides={"home_region": "US"}
    )
    resp = api.create_submission(
        asg["id"],
        {"student_id": student["id"], "content_text": "cross region student"},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESIDENCY_VIOLATION, expected_status=422)


def test_submission_quota_limit_reached(api):
    """PRD §3.4: "Quota — the count of this student's submissions on this
    assignment whose `pipeline_state` is anything other than `SUPERSEDED` must
    be below `max_submissions_per_student`, else `ERR_SUBMISSION_LIMIT_REACHED`
    (HTTP 422)."

    Design: Corner/validations/submission_quota_limit_reached
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US", assignment_overrides={"max_submissions_per_student": 2, "title": "Quota"}
    )
    submit(asg["id"], student["id"], "quota one")
    submit(asg["id"], student["id"], "quota two")
    resp = api.create_submission(
        asg["id"],
        {"student_id": student["id"], "content_text": "quota three"},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_LIMIT_REACHED, expected_status=422)


def test_intake_closed_and_consent_missing_state_wins(api):
    """PRD §3.4: "The assignment's gate state — after lazy auto-close has been
    applied, intake against a `CLOSED` assignment is rejected with
    `ERR_ASSIGNMENT_CLOSED` (HTTP 409)." PRD §2.6: "When several checks could
    reject the same request, they are evaluated in this fixed order: ... then
    state preconditions of the target resources, then business-safety rules
    (consent, residency)"

    Design: Difficulty/priority_pair_validation_conflict/intake_closed_and_consent_missing_state_wins
    """
    from test_helpers import reset_clock

    # STRICT integration (default); the student's consent stays NOT_GIVEN.
    inst, integ, instr, student, asg = setup_basic_scenario("US", consent=False)
    reset_clock("2027-02-01T00:00:00Z")  # past due_at 2027-01-01
    resp = api.create_submission(
        asg["id"],
        {"student_id": student["id"], "content_text": "too late"},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_CLOSED, expected_status=409)
    fetched = validate_success(api.get_assignment(asg["id"], make_instructor_headers(instr["id"])))
    assert fetched["accepting_state"] == "CLOSED", "the lazy auto-close must have fired"


def test_intake_closed_assignment_with_consent_granted_also_rejected(api):
    """PRD §3.4: "The assignment's gate state — after lazy auto-close has been
    applied, intake against a `CLOSED` assignment is rejected with
    `ERR_ASSIGNMENT_CLOSED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/intake_closed_and_consent_missing_state_wins
    """
    from test_helpers import reset_clock

    # Isolated single-failure variant: consent GRANTED, only the gate state fails.
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    reset_clock("2027-02-01T00:00:00Z")
    resp = api.create_submission(
        asg["id"],
        {"student_id": student["id"], "content_text": "too late"},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_CLOSED, expected_status=409)
    fetched = validate_success(api.get_assignment(asg["id"], make_instructor_headers(instr["id"])))
    assert fetched["accepting_state"] == "CLOSED"


def test_content_invalid_and_bad_supersede_constraint_wins(api):
    """PRD §3.4: "Content — `content_text` must be non-empty and must tokenize
    to at least one whitespace-separated word; empty or all-whitespace content
    is `ERR_CONTENT_INVALID` (HTTP 422)." PRD §2.6: "then business constraints
    (content, thresholds, quotas), then referential rules (supersede targets,
    report prerequisites)"

    Design: Difficulty/priority_pair_validation_conflict/content_invalid_and_bad_supersede_constraint_wins
    """
    inst, integ, instr, student_a, asg = setup_basic_scenario("US")
    sub_a = submit(asg["id"], student_a["id"], "student a original")
    process(sub_a["id"], instr["id"])
    student_b = create_student(inst["id"], external_lms_id="sb", home_region="US")
    grant_consent(student_b["id"], student_b["version"])

    resp = api.create_submission(
        asg["id"],
        {"student_id": student_b["id"], "content_text": "", "supersedes_submission_id": sub_a["id"]},
        make_student_headers(student_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONTENT_INVALID, expected_status=422)
    data, meta = validate_paginated(api.list_submissions(INST_ADMIN, params={"student_id": student_b["id"]}))
    assert data == [], "no submission may be persisted for student B"


def test_content_invalid_isolated_rejected(api):
    """PRD §3.4: "Content — `content_text` must be non-empty and must tokenize
    to at least one whitespace-separated word; empty or all-whitespace content
    is `ERR_CONTENT_INVALID` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/content_invalid_and_bad_supersede_constraint_wins
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    resp = api.create_submission(
        asg["id"],
        {"student_id": student["id"], "content_text": ""},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONTENT_INVALID, expected_status=422)


def test_consent_cycle_regrant_enables_intake(api):
    """PRD §3.2: "From `NOT_GIVEN`, a `GRANT` moves the student to `GRANTED`;
    from `WITHDRAWN`, a `GRANT` likewise returns the student to `GRANTED`."
    PRD §3.4: "The consent gate — when the integration's `consent_enforcement`
    is `STRICT`, the student's `consent_status` must be `GRANTED`"

    Design: Difficulty/non_linear_state_machine/consent_cycle_regrant_enables_intake
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US", consent=False)
    v1 = student["version"]
    st2 = grant_consent(student["id"], v1)                     # NOT_GIVEN -> GRANTED
    assert st2["consent_status"] == "GRANTED"
    st3 = withdraw_consent(student["id"], st2["version"])      # GRANTED -> WITHDRAWN
    assert st3["consent_status"] == "WITHDRAWN"
    st4 = grant_consent(student["id"], st3["version"])         # WITHDRAWN -> GRANTED
    assert st4["consent_status"] == "GRANTED", "the re-grant edge must be taken"

    sub = validate_success(
        api.create_submission(
            asg["id"],
            {"student_id": student["id"], "content_text": "regrant works"},
            make_student_headers(student["id"]),
        ),
        expected_status=201,
    )
    assert sub["pipeline_state"] == "RECEIVED"
    assert sub["word_count"] == 2


def test_consent_cycle_granted_to_withdrawn_edge(api):
    """PRD §3.2: "From `GRANTED`, a `WITHDRAW` moves the student to `WITHDRAWN`
    — and only from `GRANTED`: withdrawing when consent was never given, or
    granting when consent is already granted, does not match any transition.
    Every successful consent write stamps `consent_recorded_at` with the current
    logical-clock instant and increments the student's `version` by one."

    Design: Difficulty/non_linear_state_machine/consent_cycle_regrant_enables_intake
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US", consent=False)
    v1 = student["version"]
    st2 = grant_consent(student["id"], v1)
    assert st2["consent_status"] == "GRANTED"
    assert st2["version"] == v1 + 1
    assert st2["consent_recorded_at"] is not None
    st3 = withdraw_consent(student["id"], st2["version"])
    assert st3["consent_status"] == "WITHDRAWN"
    assert st3["version"] == st2["version"] + 1
