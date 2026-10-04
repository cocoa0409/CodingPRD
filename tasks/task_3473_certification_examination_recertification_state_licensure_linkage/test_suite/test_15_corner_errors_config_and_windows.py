"""Queue B — errors (configuration, uniqueness, temporal windows, and
licensure-path triggers): one rejection per error code, each in an isolated
scenario.
"""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    DEFAULT_DELIVERY_CLOCK,
    DEFAULT_ISSUE_CLOCK,
    api_client,
    advance_clock,
    ce_entry_payload,
    clock_payload,
    create_approved_exam_application,
    create_candidate,
    create_level,
    create_license_application_payload,
    create_program,
    create_recert_application_payload,
    create_state_exam_record,
    create_state_policy,
    create_state_policy_payload,
    create_verified_completion,
    create_verified_psychomotor,
    deliver_attempt,
    get_success_data,
    make_candidate_headers,
    refresh_certification,
    schedule_attempt,
    setup_certified_candidate,
    setup_recert_draft_with_entries,
    setup_submitted_recert,
    validate_error,
)


def test_duplicate_state_policy_conflict(api):
    """PRD §3.1: "Each **state adoption policy** records how one state links
    national certification to licensure. Keyed by a unique two-letter
    `state_code` — a duplicate is rejected with `ERR_DUPLICATE_STATE_POLICY`".

    Design: Corner/errors/duplicate_state_policy_conflict
    """
    create_state_policy(state_code="OR", adoption_mode="NREMT_ACCEPTED",
                        accepted_level_codes=["EMT"], base_license_fee_cents=12000)
    resp = api_client.create_state_adoption_policy(
        create_state_policy_payload(
            state_code="OR", adoption_mode="STATE_EXAM",
            base_license_fee_cents=10000, state_exam_fee_cents=2500,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATE_POLICY)


def test_duplicate_course_in_cycle_conflict(api):
    """PRD §3.6: "a `delivery_method` of `DISTRIBUTED` or `IN_PERSON`; a
    `course_code` unique within the application — a repeat is rejected with
    `ERR_DUPLICATE_COURSE_IN_CYCLE`".

    The repeat is rejected even across components on the same application.

    Design: Corner/errors/duplicate_course_in_cycle_conflict
    """
    ctx = setup_recert_draft_with_entries(entry_specs=[
        dict(component="NATIONAL", hours=5, delivery_method="IN_PERSON",
             course_code="DUP", course_date="2027-10-01", provider_name="AlphaCE"),
    ])
    resp = api_client.add_ce_entry(
        ctx["recert_application"]["id"],
        ce_entry_payload("LOCAL", 5, "IN_PERSON", "2027-10-02", "BetaCE",
                         course_code="DUP"),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_COURSE_IN_CYCLE)


def test_ce_entry_outside_cycle_window(api):
    """PRD §3.6: "The course date must fall inside the pinned cycle window, from
    `cycle_window_start` through `cert_expires_on_at_creation` inclusive
    (`ERR_CE_ENTRY_OUTSIDE_CYCLE`)."

    The certification expires 2028-09-04, so the cycle window opens
    2027-09-04; a course dated 2027-08-01 precedes it.

    Design: Corner/errors/ce_entry_outside_cycle_window
    """
    ctx = setup_recert_draft_with_entries(entry_specs=[])
    resp = api_client.add_ce_entry(
        ctx["recert_application"]["id"],
        ce_entry_payload("NATIONAL", 10, "IN_PERSON", "2027-08-01", "AlphaCE"),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CE_ENTRY_OUTSIDE_CYCLE)


def test_jurisprudence_required_enforced(api):
    """PRD §3.8: "Where the policy requires the jurisprudence attestation,
    `jurisprudence_completed` must be true (`ERR_JURISPRUDENCE_REQUIRED`)."
    PRD §3.8: "The application is born `UNDER_REVIEW`, with
    `jurisprudence_completed` defaulting to false when not supplied."

    Design: Corner/errors/jurisprudence_required_enforced
    """
    create_state_policy(
        state_code="NM", adoption_mode="NREMT_ACCEPTED", accepted_level_codes=["EMT"],
        jurisprudence_exam_required=True, base_license_fee_cents=12000,
        national_verification_surcharge_cents=1000,
    )
    ctx = setup_certified_candidate()
    cert = refresh_certification(ctx["certification"]["id"])
    resp = api_client.create_license_application(
        create_license_application_payload(
            "NM", ctx["level"]["id"], certification_id=cert["id"],
            expected_certification_version=cert["version"],
        ),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_JURISPRUDENCE_REQUIRED)


def test_level_not_accepted_in_state(api):
    """PRD §3.8: "On the national (`NREMT`) path, the cited certification must
    stand `ACTIVE` (`ERR_CERTIFICATION_NOT_ACTIVE`), its level's code must
    appear in the policy's `accepted_level_codes`
    (`ERR_LEVEL_NOT_ACCEPTED_IN_STATE`)".

    An EMT certification into a policy accepting only PARAMEDIC fails.

    Design: Corner/errors/level_not_accepted_in_state
    """
    create_state_policy(
        state_code="OR", adoption_mode="NREMT_ACCEPTED",
        accepted_level_codes=["PARAMEDIC"], base_license_fee_cents=12000,
        national_verification_surcharge_cents=1000,
    )
    ctx = setup_certified_candidate()
    cert = refresh_certification(ctx["certification"]["id"])
    resp = api_client.create_license_application(
        create_license_application_payload(
            "OR", ctx["level"]["id"], certification_id=cert["id"],
            expected_certification_version=cert["version"],
        ),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEVEL_NOT_ACCEPTED_IN_STATE)


def test_issue_cross_reference_mismatch(api):
    """PRD §3.5: "All references must agree on the candidate and the level
    (`ERR_CROSS_REFERENCE_MISMATCH`)".

    Candidate A's application and psychomotor with candidate B's passing
    attempt cannot issue a certification.

    Design: Corner/errors/issue_cross_reference_mismatch
    """
    level = create_level()
    program = create_program(level["id"])

    def _through_attempt(name):
        candidate = create_candidate()
        record = create_verified_completion(candidate["id"], program)
        application = create_approved_exam_application(
            candidate["id"], level["id"], record["id"],
        )
        attempt = schedule_attempt(candidate["id"], application["att_id"])
        return candidate, record, application, attempt

    cand_a, rec_a, app_a, at_a = _through_attempt("A")
    cand_b, rec_b, app_b, at_b = _through_attempt("B")
    advance_clock(DEFAULT_DELIVERY_CLOCK)
    deliver_attempt(at_a["id"])
    deliver_attempt(at_b["id"])
    psy_a = create_verified_psychomotor(cand_a["id"], level["id"], rec_a["id"])
    advance_clock(DEFAULT_ISSUE_CLOCK)

    resp = api_client.issue_certification(
        {"candidate_id": cand_a["id"], "level_id": level["id"],
         "exam_application_id": app_a["id"], "attempt_id": at_b["id"],
         "psychomotor_id": psy_a["id"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)


def test_duplicate_active_certification_conflict(api):
    """PRD §3.5: "One active credential per candidate and level is the rule:
    issuing while an `ACTIVE` certification already exists for the pair is
    rejected with `ERR_DUPLICATE_ACTIVE_CERTIFICATION`."

    Design: Corner/errors/duplicate_active_certification_conflict
    """
    ctx = setup_certified_candidate()
    resp = api_client.issue_certification(
        {"candidate_id": ctx["candidate"]["id"], "level_id": ctx["level"]["id"],
         "exam_application_id": ctx["exam_application"]["id"],
         "attempt_id": ctx["attempt"]["id"],
         "psychomotor_id": ctx["psychomotor"]["id"]},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CERTIFICATION)


def test_recert_in_progress_conflict(api):
    """PRD §3.6: "Only one draft may exist for a certification: an existing
    `DRAFT` is automatically superseded to `SUPERSEDED` when a new draft opens,
    while another application for the same certification already `SUBMITTED` or
    `AUDIT_PENDING` blocks creation with `ERR_RECERT_IN_PROGRESS_CONFLICT`."

    Design: Corner/errors/recert_in_progress_conflict
    """
    ctx = setup_submitted_recert()
    assert ctx["recert_application"]["status"] == "SUBMITTED"
    cert = refresh_certification(ctx["certification"]["id"])
    resp = api_client.create_recert_application(
        create_recert_application_payload(cert["id"], "HOURLY", cert["version"]),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RECERT_IN_PROGRESS_CONFLICT)


def test_nremt_path_missing_certification_id(api):
    """PRD §3.8: "The resolved `path` follows the pinned mode: `NREMT_ACCEPTED`
    requires a `certification_id`; `STATE_EXAM` requires a
    `state_exam_record_id`; `HYBRID` validates the national path first when a
    `certification_id` is present. A missing path-required reference is a shape
    error (`ERR_INVALID_REQUEST`)."

    Design: Corner/errors/nremt_path_missing_certification_id
    """
    create_state_policy()
    level = create_level()
    candidate = create_candidate()
    resp = api_client.create_license_application(
        create_license_application_payload("WA", level["id"]),
        make_candidate_headers(candidate["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_state_exam_wrong_state_mismatch(api):
    """PRD §3.8: "On the state-exam (`STATE_EXAM`) path, the cited record must
    match the target state and level (`ERR_CROSS_REFERENCE_MISMATCH`)".

    A state exam record from NM cannot serve a TX application.

    Design: Corner/errors/state_exam_wrong_state_mismatch
    """
    level = create_level()
    create_state_policy(state_code="TX", adoption_mode="STATE_EXAM",
                        base_license_fee_cents=10000, state_exam_fee_cents=2500)
    candidate = create_candidate()
    record = create_state_exam_record(
        candidate["id"], "NM", level["id"], exam_date="2026-09-01",
    )
    resp = api_client.create_license_application(
        create_license_application_payload(
            "TX", level["id"], state_exam_record_id=record["id"],
        ),
        make_candidate_headers(candidate["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)


def test_hybrid_prefers_nremt_path(api):
    """PRD §3.8: "The resolved `path` follows the pinned mode: `NREMT_ACCEPTED`
    requires a `certification_id`; `STATE_EXAM` requires a
    `state_exam_record_id`; `HYBRID` validates the national path first when a
    `certification_id` is present."
    PRD §3.8: "On the national (`NREMT`) path, the cited certification must
    stand `ACTIVE` (`ERR_CERTIFICATION_NOT_ACTIVE`)".

    A HYBRID application naming both a LAPSED certification and a valid passing
    state exam record fails on the national path first — the state exam record
    does not rescue it.

    Design: Corner/errors/hybrid_prefers_nremt_path
    """
    create_state_policy(
        state_code="OH", adoption_mode="HYBRID", accepted_level_codes=["EMT"],
        base_license_fee_cents=11000, national_verification_surcharge_cents=500,
        state_exam_fee_cents=2000,
    )
    ctx = setup_certified_candidate()
    record = create_state_exam_record(
        ctx["candidate"]["id"], "OH", ctx["level"]["id"], exam_date="2026-09-04",
    )
    advance_clock("2028-09-05T00:00:00Z")
    cert = refresh_certification(ctx["certification"]["id"])
    assert cert["status"] == "LAPSED"

    resp = api_client.create_license_application(
        create_license_application_payload(
            "OH", ctx["level"]["id"], certification_id=cert["id"],
            state_exam_record_id=record["id"],
            expected_certification_version=cert["version"],
        ),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE)


def test_clock_regression_conflict(api):
    """PRD §2.5: "The clock is monotonic: a request whose target lies earlier
    than the current logical time is rejected with `ERR_CLOCK_REGRESSION`
    (HTTP 409)."

    Design: Corner/errors/clock_regression_conflict
    """
    advance_clock("2026-09-10T00:00:00Z")
    resp = api_client.set_clock(clock_payload("2026-09-05T00:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)
    confirm = get_success_data(api_client.set_clock(clock_payload("2026-09-10T00:00:00Z"), ADMIN))
    assert confirm["current_utc"].startswith("2026-09-10"), (
        f"the rejected regression left the clock unchanged, got {confirm['current_utc']}"
    )
