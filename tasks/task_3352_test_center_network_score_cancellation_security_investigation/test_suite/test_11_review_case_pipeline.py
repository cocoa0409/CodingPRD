"""Review cases: notify deadline, response window, adjudication gates, SoD, OCC."""
from test_helpers import (
    ADMIN_2_ID,
    ANALYST_1_ID,
    ApiErrorId,
    CLOCK_PAST_RESPONSE_DEADLINE,
    EXPECTED_RESPONSE_DEADLINE_ISO,
    adjudicate_case,
    adjudicate_case_payload,
    assert_iso_equal,
    fresh_case_version,
    get_only_review_case,
    get_score_record,
    list_review_cases,
    notify_case,
    respond_case_payload,
    respond_to_case,
    set_clock,
    setup_analyzed_session,
    setup_open_gain_case,
    validate_error,
    validate_success,
)
from test_helpers import (
    CLEAN_SCORE_SPEC,
    create_irregularity_payload,
    make_examinee_headers,
    make_proctor_headers,
    make_program_admin_headers,
    resolve_irregularity_payload,
)


def test_notify_sets_response_deadline_exactly(api):
    """PRD §3.6: "A `ScoreAnalyst` notifies the examinee, moving the case from
    `OPENED` to `NOTIFIED`; notification stamps the `response_deadline` as the
    current logical clock plus 30 days and increments the case's `version` by
    1."

    Design: Corner/state_machines/notify_sets_response_deadline_exactly
    """
    ctx = setup_open_gain_case(name="Center ND")
    # Clock is still 2026-10-10T12:30:00Z from the administer step.
    notified = notify_case(ctx["case"]["id"])
    assert notified["status"] == "NOTIFIED"
    assert_iso_equal(notified["response_deadline"], EXPECTED_RESPONSE_DEADLINE_ISO)


def test_respond_after_window_closed_rejected(api):
    """PRD §3.6: "The case must be in `NOTIFIED` or `WINDOW_EXPIRED` status at
    the state level, and the current clock must be no later than the case's
    `response_deadline`, or the submission fails with
    `ERR_RESPONSE_WINDOW_CLOSED`."
    PRD §3.6: "when the logical clock is advanced strictly past a `NOTIFIED`
    case's `response_deadline`, the set-clock sweep moves that case to
    `WINDOW_EXPIRED` (§2.5)."

    Design: Corner/validations/respond_after_window_closed_rejected
    """
    ctx = setup_open_gain_case(name="Center RW")
    notify_case(ctx["case"]["id"])
    set_clock(CLOCK_PAST_RESPONSE_DEADLINE)
    case = get_only_review_case(ctx["registration"]["id"])
    assert case["status"] == "WINDOW_EXPIRED", "the sweep fired"
    resp = api.respond_case(
        case["id"],
        respond_case_payload("Too late response."),
        make_examinee_headers(ctx["examinee"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESPONSE_WINDOW_CLOSED)
    case = get_only_review_case(ctx["registration"]["id"])
    assert case["examinee_response"] is None


def test_adjudicate_before_window_ready_rejected(api):
    """PRD §3.6: "the case must be `RESPONSE_RECEIVED` or `WINDOW_EXPIRED`,
    and an attempt while it is `OPENED`, or still `NOTIFIED` with the window
    open, fails with `ERR_ADJUDICATION_NOT_READY`."

    Design: Corner/validations/adjudicate_before_window_ready_rejected
    """
    ctx = setup_open_gain_case(name="Center AN")
    notify_case(ctx["case"]["id"])
    version = fresh_case_version(ctx["registration"]["id"])
    resp = api.adjudicate_case(
        ctx["case"]["id"],
        adjudicate_case_payload("UPHELD", "premature", version),
        make_program_admin_headers("admin-9"),
    )
    validate_error(resp, ApiErrorId.ERR_ADJUDICATION_NOT_READY)
    case = get_only_review_case(ctx["registration"]["id"])
    assert case["status"] == "NOTIFIED"


def test_sod_violation_same_user_flag_and_adjudicate(api):
    """PRD §3.6: "segregation of duties forbids the adjudicator from being the
    analyst who flagged the case, so a caller whose `X-User-ID` equals the
    case's `flagged_by_analyst_id` is rejected with `ERR_SOD_VIOLATION`"

    Design: Corner/validations/sod_violation_same_user_flag_and_adjudicate
    """
    ctx = setup_open_gain_case(name="Center SD")
    notify_case(ctx["case"]["id"])
    respond_to_case(ctx["case"]["id"], ctx["examinee"]["id"],
                    "My improvement is explained by study.")
    version = fresh_case_version(ctx["registration"]["id"])
    # The flagging analyst id, presented with the ProgramAdmin role.
    resp = api.adjudicate_case(
        ctx["case"]["id"],
        adjudicate_case_payload("UPHELD", "self-adjudication attempt", version),
        make_program_admin_headers(ANALYST_1_ID),
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
    case = get_only_review_case(ctx["registration"]["id"])
    assert case["status"] == "RESPONSE_RECEIVED", "no adjudication recorded"


def test_adjudicate_occ_stale_case_rejected(api):
    """PRD §2.7: "Adjudicating a score review case requires the request body
    to carry `expected_case_version`, holding the case `version` the
    adjudicator last observed. If the case's current `version` has advanced —
    for example because an examinee response was recorded after the
    adjudicator read the file — the adjudication is rejected with
    `ERR_STALE_VERSION` (HTTP 412), so no adjudicator ever decides on a
    superseded view of the case."

    Design: Corner/cross_cutting_complexity_layers/adjudicate_occ_stale_case_rejected
    """
    ctx = setup_open_gain_case(name="Center OA")
    notify_case(ctx["case"]["id"])
    stale_version = fresh_case_version(ctx["registration"]["id"])
    respond_to_case(ctx["case"]["id"], ctx["examinee"]["id"],
                    "Response submitted after the adjudicator read the file.")
    resp = api.adjudicate_case(
        ctx["case"]["id"],
        adjudicate_case_payload("UPHELD", "stale view", stale_version),
        make_program_admin_headers(ADMIN_2_ID),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    fresh_version = fresh_case_version(ctx["registration"]["id"])
    adjudicated = adjudicate_case(
        ctx["case"]["id"], "UPHELD", "reviewed the response", fresh_version,
        admin_id=ADMIN_2_ID,
    )
    assert adjudicated["status"] == "ADJUDICATED_UPHELD"
    score = get_score_record(ctx["score_record"]["id"])
    assert score["status"] == "RELEASED", "reached RELEASED via VALIDATED"


def test_irregularity_dismissed_opens_no_case(api):
    """PRD §3.4: "Dismissal simply closes the report as `DISMISSED`."
    PRD §3.4: "If no score record exists yet for the registration,
    substantiation opens no case."
    PRD §3.5: "Records with no firing signal transition straight from
    `PENDING_ANALYSIS` to `RELEASED`, their `scaled_score` now final."

    Design: Corner/state_machines/irregularity_dismissed_opens_no_case
    """
    ctx = setup_analyzed_session([dict(CLEAN_SCORE_SPEC)], name="Center DM",
                                 assign=True)
    irr = validate_success(
        api.create_irregularity_report(
            ctx["session"]["id"],
            create_irregularity_payload(
                registration_id=ctx["registrations"][0]["id"],
                category="SEATING_VIOLATION",
                severity="LOW",
                narrative="Sat two seats over",
            ),
            make_proctor_headers(ctx["proctor"]["id"]),
        ),
        201,
    )
    resolved = validate_success(
        api.resolve_irregularity_report(
            irr["id"],
            resolve_irregularity_payload("DISMISSED"),
            make_program_admin_headers("admin-1"),
        ),
        200,
    )
    assert resolved["status"] == "DISMISSED"
    assert list_review_cases(ctx["registrations"][0]["id"]) == [], (
        "no case opened"
    )
    score = get_score_record(ctx["score_records"][0]["id"])
    assert score["status"] == "RELEASED"
