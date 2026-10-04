"""Queue B — calculations: CAT adaptive scoring, the CE credit waterfall and
its HOURLY variant, the audit sampling selector, education validity, reentry
tiers, licensure fees, and the retake wait.
"""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    advance_clock,
    cat_fail_responses,
    cat_responses_payload,
    create_approved_exam_application,
    create_candidate,
    create_exam_application,
    create_level,
    create_program,
    create_recert_draft,
    create_reentry_application,
    create_reentry_application_payload,
    create_verified_completion,
    create_verified_psychomotor,
    decide_license,
    decision_payload,
    deliver_attempt,
    issue_certification,
    make_candidate_headers,
    schedule_attempt,
    setup_approved_application,
    setup_candidate_with_verified_completion,
    setup_certified_candidate,
    setup_license_context_state_exam,
    setup_recert_draft_with_entries,
    setup_scored_attempt,
    schedule_attempt_payload,
    submit_recert,
    validate_error,
    add_ce_entries,
    get_success_data,
)

_EMR_LEVEL = dict(
    code="EMR", display_name="Emergency Medical Responder",
    scope_summary="First-response basics", cognitive_cut_score=0.5,
    ce_total_hours=16, ce_national_min_hours=8, ce_local_min_hours=4,
    ce_individual_min_hours=4, hourly_model_total_hours=16,
    remedial_hours_required=8, refresher_hours_required=8,
    initial_application_fee_cents=5000, recert_application_fee_cents=2500,
)


def test_cat_theta_exactly_at_cut_passes(api):
    """PRD §3.4: "When neither bound ever fires and at least six items were
    delivered, `final_outcome` is `PASS` exactly when the final weighted
    accuracy meets or exceeds the cut score, and `items_delivered_count` is the
    full response count."
    PRD §3.4: "Every comparison uses the unrounded accuracy; the stored
    `theta_final` is the final weighted accuracy rounded half up to four decimal
    places."

    Three of six correct at uniform difficulty 0.5 against a 0.50 cut lands
    theta exactly on the cut — an inclusive PASS.

    Design: Corner/calculations/cat_theta_exactly_at_cut_passes
    """
    ctx = setup_scored_attempt(
        level_overrides=_EMR_LEVEL,
        responses_payload=cat_responses_payload(3, 6),
    )
    attempt = ctx["attempt"]
    assert attempt["final_outcome"] == "PASS", "theta_6 == 0.5 meets the 0.50 cut exactly"
    assert attempt["theta_final"] == 0.5
    assert attempt["items_delivered_count"] == 6
    assert attempt["status"] == "SCORED_PASS"


def test_cat_early_stop_pass_at_min_items(api):
    """PRD §3.4: "The moment the lower bound meets or exceeds the cut score, the
    attempt stops and `final_outcome` is `PASS`; the moment the upper bound
    falls strictly below the cut score, the attempt stops and `final_outcome` is
    `FAIL`; in either case `items_delivered_count` records the prefix length at
    which the stop fired."

    Eight perfect responses give theta 1.0 with standard error zero at k == 6,
    so the lower bound meets the cut at the sixth item and the exam stops there
    although eight responses were posted.

    Design: Corner/calculations/cat_early_stop_pass_at_min_items
    """
    ctx = setup_scored_attempt()
    attempt = ctx["attempt"]
    assert attempt["status"] == "SCORED_PASS"
    assert attempt["final_outcome"] == "PASS"
    assert attempt["provisional_outcome"] == "PASS"
    assert attempt["items_delivered_count"] == 6
    assert attempt["theta_final"] == 1.0


def test_audit_selector_seq_mod_third_submission_selected(api):
    """PRD §3.6: "The application's `recert_seq` is one plus the number of prior
    applications for the same certification that ever reached `SUBMITTED`,
    counting applications that stand in or passed through `SUBMITTED`,
    `AUDIT_PENDING`, `APPROVED`, `DENIED`, or `AUDIT_FAILED`, and never counting
    ones that stayed `DRAFT` or ended `SUPERSEDED`."
    PRD §3.6: "`SEQ_MOD` fires when `recert_seq` is an exact multiple of three".
    PRD §3.6: "A selected application enters `AUDIT_PENDING`; an unselected one
    enters `SUBMITTED`".

    Submissions one and two go straight to SUBMITTED; the third lands in
    AUDIT_PENDING with SEQ_MOD among its recorded reasons.

    Design: Corner/calculations/audit_selector_seq_mod_third_submission_selected
    """
    ctx = setup_certified_candidate()
    advance_clock("2027-10-15T00:00:00Z")
    candidate_id = ctx["candidate"]["id"]
    cert_id = ctx["certification"]["id"]

    seq_seen = []
    for round_no in (1, 2, 3):
        draft = create_recert_draft(candidate_id, cert_id, model="NCCP")
        add_ce_entries(draft["id"], candidate_id, [
            dict(component="NATIONAL", hours=10, delivery_method="IN_PERSON",
                 course_code=f"R{round_no}-N1", course_date="2027-10-01", provider_name="AlphaCE"),
            dict(component="NATIONAL", hours=10, delivery_method="IN_PERSON",
                 course_code=f"R{round_no}-N2", course_date="2027-10-01", provider_name="BetaCE"),
            dict(component="LOCAL", hours=10, delivery_method="IN_PERSON",
                 course_code=f"R{round_no}-L1", course_date="2027-10-02", provider_name="GammaCE"),
            dict(component="INDIVIDUAL", hours=10, delivery_method="IN_PERSON",
                 course_code=f"R{round_no}-I1", course_date="2027-10-03", provider_name="DeltaCE"),
        ])
        submitted = submit_recert(draft["id"], candidate_id)
        seq_seen.append(submitted)
        if round_no < 3:
            get_success_data(api_client.decide_recert_application(
                draft["id"], decision_payload("DENIED", reason="paperwork"), ADMIN,
            ))

    assert seq_seen[0]["recert_seq"] == 1 and seq_seen[0]["status"] == "SUBMITTED"
    assert seq_seen[1]["recert_seq"] == 2 and seq_seen[1]["status"] == "SUBMITTED"
    third = seq_seen[2]
    assert third["recert_seq"] == 3
    assert third["audit_selected"] is True
    assert "SEQ_MOD" in third["audit_reasons"]
    assert third["status"] == "AUDIT_PENDING"
    assert "SINGLE_PROVIDER_CONCENTRATION" not in third["audit_reasons"], (
        "each provider contributes at most 10 hours, below the 20-hour flag"
    )


def test_education_validity_last_day_inclusive(api):
    """PRD §3.3: "Its `within_validity_window` flag reports the date half of
    educational validity: the completion date is on or before the current
    instant, and the current instant is on or before the date twenty-four
    calendar months after the completion date — both ends inclusive."
    PRD §3.4: "The cited record must belong to this candidate and teach this
    level (`ERR_CROSS_REFERENCE_MISMATCH`), and it must be `VERIFIED` and inside
    its twenty-four-month validity window at decision time
    (`ERR_EDUCATION_VALIDITY_EXPIRED`)."

    Approval at exactly completion_date + 24 months succeeds; one day later
    fails.

    Design: Corner/calculations/education_validity_last_day_inclusive
    """
    ctx = setup_candidate_with_verified_completion()
    app_in = create_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    app_out = create_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )

    advance_clock("2028-09-01T00:00:00Z")
    approved = get_success_data(api_client.decide_exam_application(
        app_in["id"], decision_payload("APPROVED"), ADMIN,
    ))
    assert approved["status"] == "APPROVED"
    assert approved["att_id"], "the boundary day is inclusive"

    advance_clock("2028-09-02T00:00:00Z")
    resp = api_client.decide_exam_application(
        app_out["id"], decision_payload("APPROVED"), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_EDUCATION_VALIDITY_EXPIRED)
    assert get_success_data(api_client.get_exam_application(app_out["id"], ADMIN))["status"] == "SUBMITTED"


def test_reentry_tier_boundaries(api):
    """PRD §3.7: "a submission on or before the date twelve calendar months
    after expiry receives `TIER_CE_ONLY`; one after that date but on or before
    the date twenty-four calendar months after expiry receives
    `TIER_REFRESHER`, with boundary equality always belonging to the lower
    tier. A submission later than twenty-four months after expiry is rejected
    with `ERR_REENTRY_NOT_AVAILABLE` — the pathway is closed and full
    re-examination is required instead."

    Three certifications lapsed by one sweep: exactly 12 months lapsed takes
    TIER_CE_ONLY, 13 months takes TIER_REFRESHER, and 25 months is rejected at
    creation.

    Design: Corner/calculations/reentry_tier_boundaries
    """
    advance_clock("2026-09-01T00:00:00Z")
    level = create_level()
    program = create_program(level["id"])

    def _certify(completion_date, window_day):
        candidate = create_candidate()
        record = create_verified_completion(candidate["id"], program, completion_date)
        application = create_approved_exam_application(
            candidate["id"], level["id"], record["id"],
        )
        attempt = schedule_attempt(
            candidate["id"], application["att_id"],
            f"{window_day}T00:00:00Z", f"{window_day}T23:59:59Z",
        )
        deliver_attempt(attempt["id"])  # delivered at the current clock
        psychomotor = create_verified_psychomotor(
            candidate["id"], level["id"], record["id"], exam_date=window_day,
        )
        certification = issue_certification(
            candidate["id"], level["id"], application["id"],
            attempt["id"], psychomotor["id"],
        )
        return candidate, certification

    # Cert A expires 2028-09-01 (25 months lapsed at the final sweep).
    cand_a, cert_a = _certify("2026-09-01", "2026-09-01")
    # Cert B expires 2029-09-01 (13 months lapsed).
    advance_clock("2027-09-01T00:00:00Z")
    cand_b, cert_b = _certify("2027-08-15", "2027-09-01")
    # Cert C expires 2029-10-01 (exactly 12 months lapsed).
    advance_clock("2027-10-01T00:00:00Z")
    cand_c, cert_c = _certify("2027-09-15", "2027-10-01")

    sweep = advance_clock("2030-10-01T00:00:00Z")
    assert sweep["certifications_lapsed_count"] == 3

    reentry_c = create_reentry_application(cand_c["id"], cert_c["id"], ce_makeup_hours_claimed=40)
    assert reentry_c["tier"] == "TIER_CE_ONLY", "equality belongs to the lower tier"
    reentry_b = create_reentry_application(cand_b["id"], cert_b["id"], refresher_hours_claimed=24)
    assert reentry_b["tier"] == "TIER_REFRESHER"
    resp_a = api_client.create_reentry_application(
        create_reentry_application_payload(cert_a["id"], refresher_hours_claimed=24),
        make_candidate_headers(cand_a["id"]),
    )
    validate_error(resp_a, ApiErrorId.ERR_REENTRY_NOT_AVAILABLE)


def test_fee_state_exam_path_lines(api):
    """PRD §3.8: "the applicable lines are always the `base_license_fee_cents`,
    plus the `national_verification_surcharge_cents` on the national path or
    the `state_exam_fee_cents` on the state-exam path; `assessed_fee_cents` is
    their sum."
    PRD §3.8: "The `registry_share_cents` is computed line by line — each
    applicable line multiplied by `registry_share_bps_snapshot`, divided by ten
    thousand, and rounded half up to a whole cent — and then summed from those
    per-line amounts."

    The state-exam path swaps the surcharge line for the state-exam fee line:
    base 10000 + state-exam 2500 assesses 12500 with a per-line share of
    1500 + 375 == 1875.

    Design: Corner/calculations/fee_state_exam_path_lines
    """
    ctx = setup_license_context_state_exam(
        policy_overrides={"state_code": "TX", "adoption_mode": "STATE_EXAM",
                          "base_license_fee_cents": 10000, "state_exam_fee_cents": 2500},
        state_exam_overrides={"exam_date": "2026-09-01"},
    )
    assert ctx["license_application"]["path"] == "STATE_EXAM"
    granted = decide_license(ctx["license_application"]["id"], "GRANTED")
    assert granted["assessed_fee_cents"] == 12500
    assert granted["registry_share_cents"] == 1875


def test_hourly_distributed_cap_applied(api):
    """PRD §3.6: "Under the `HOURLY` model the components and the spill are
    ignored: the credited total is the sum of all `IN_PERSON` hours on eligible
    entries plus the smaller of the total `DISTRIBUTED` hours and the level's
    `hourly_model_total_hours` halved and rounded up to a whole hour, and the
    portfolio is sufficient exactly when that total meets
    `hourly_model_total_hours`, otherwise `ERR_CE_TOTAL_SHORTFALL`."

    30 distributed hours cap at ceil(40 * 0.5) == 20 against the total, so
    20 + 15 in-person == 35 < 40.

    Design: Corner/calculations/hourly_distributed_cap_applied
    """
    entries = [
        dict(component="NATIONAL", hours=15, delivery_method="DISTRIBUTED",
             course_code="D1", course_date="2027-10-01", provider_name="AlphaCE"),
        dict(component="NATIONAL", hours=15, delivery_method="DISTRIBUTED",
             course_code="D2", course_date="2027-10-02", provider_name="BetaCE"),
        dict(component="LOCAL", hours=15, delivery_method="IN_PERSON",
             course_code="D3", course_date="2027-10-03", provider_name="GammaCE"),
    ]
    ctx = setup_recert_draft_with_entries(
        setup_certified_candidate(), model="HOURLY", entry_specs=entries,
    )
    resp = api_client.submit_recert_application(
        ctx["recert_application"]["id"], make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CE_TOTAL_SHORTFALL)


def test_distributed_cap_per_component(api):
    """PRD §3.6: "Per component, distance learning is capped: the
    distributed-hours cap for a component is the level's minimum for that
    component multiplied by one half and rounded up to the next whole hour, and
    the credited distributed hours are the smaller of the summed `DISTRIBUTED`
    hours in the component and that cap."

    Twenty DISTRIBUTED national hours credit only ceil(20 * 0.5) == 10, below
    the 20-hour national minimum — the distributed excess is discarded, not
    spilled.

    Design: Corner/calculations/distributed_cap_per_component
    """
    entries = [
        dict(component="NATIONAL", hours=20, delivery_method="DISTRIBUTED",
             course_code="N1", course_date="2027-10-01", provider_name="MegaCE"),
        dict(component="LOCAL", hours=10, delivery_method="IN_PERSON",
             course_code="L1", course_date="2027-10-02", provider_name="GammaCE"),
        dict(component="INDIVIDUAL", hours=10, delivery_method="IN_PERSON",
             course_code="I1", course_date="2027-10-03", provider_name="DeltaCE"),
    ]
    ctx = setup_recert_draft_with_entries(
        setup_certified_candidate(), model="NCCP", entry_specs=entries,
    )
    resp = api_client.submit_recert_application(
        ctx["recert_application"]["id"], make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CE_COMPONENT_SHORTFALL)


def test_retake_wait_one_second_early_fails(api):
    """PRD §3.4: "If at least one attempt has already been consumed on the
    basis, the new window's start must fall at least fifteen days after the
    most recent scored attempt's `delivered_at` — equality allowed — otherwise
    `ERR_RETAKE_WAIT_ACTIVE`."

    The last delivery was at 2026-09-03T12:00:00Z; a new window opening one
    second before 2026-09-18T12:00:00Z is rejected.

    Design: Corner/calculations/retake_wait_one_second_early_fails
    """
    ctx = setup_scored_attempt(responses_payload=cat_fail_responses())
    application = create_approved_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    resp = api_client.schedule_cognitive_exam_attempt(
        schedule_attempt_payload(
            application["att_id"], "2026-09-18T11:59:59Z", "2026-09-19T00:00:00Z",
        ),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RETAKE_WAIT_ACTIVE)
