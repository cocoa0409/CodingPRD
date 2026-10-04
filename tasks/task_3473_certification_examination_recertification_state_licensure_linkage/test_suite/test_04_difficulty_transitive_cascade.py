"""Queue A — transitive_cascade: multi-hop cascades from two different
triggers (appeal AFFIRMED -> FINAL; accreditation REVOKED), each hop's target
set computed after the previous hop lands.
"""
from test_helpers import (
    advance_clock,
    api_client,
    appeal_case,
    create_approved_exam_application,
    create_candidate,
    create_completion_record_payload,
    create_level,
    create_license_application,
    create_program,
    create_state_policy,
    create_verified_completion,
    create_verified_psychomotor,
    decide_appeal,
    deliver_attempt,
    get_success_data,
    issue_certification,
    make_candidate_headers,
    make_program_director_headers,
    open_case,
    record_accreditation_event,
    refresh_certification,
    refresh_completion_record,
    refresh_license_application,
    schedule_attempt,
    setup_license_context_nremt,
    walk_case_to_decided,
)


def _create_pending_completion(candidate_id: str, program: dict, completion_date: str) -> dict:
    """Director attests a completion record and leaves it PENDING_VERIFICATION."""
    return get_success_data(api_client.create_program_completion_record(
        create_completion_record_payload(candidate_id, program["id"], completion_date=completion_date),
        make_program_director_headers(program["director_user_id"]),
    ))


def test_falsified_education_final_cascade(api):
    """PRD §3.9: "The case becomes `DECIDED`, `decided_at` is stamped, an
    `appeal_deadline` opens thirty calendar days later with the boundary
    inclusive, and the case's `version` increments by one — but no sanction is
    applied yet."
    PRD §3.9: "A case whose violation is `FALSIFIED_EDUCATION`, finalized at
    severity `SUSPENSION_12M` or higher, moves each implicated completion record
    that stands `VERIFIED` to `INVALIDATED` with `invalidated_by_case_id` set,
    and then per record: citing exam applications still `SUBMITTED` are
    `DENIED`; certifications whose `basis_completion_record_id` names the record
    and that stand `ACTIVE`, `SUSPENDED`, or `LAPSED` are `REVOKED`; license
    applications in `UNDER_REVIEW` or `MORE_INFO_REQUIRED` citing those
    certifications are `DENIED`."
    PRD §3.9: "`PERMANENT_BAR` additionally moves the candidate to `BARRED`."

    Depth-3 chain: appeal AFFIRMED finalizes the case -> the implicated
    completion record is invalidated -> the certification based on it is
    revoked -> the in-flight license application citing that certification is
    denied. A REVOCATION sanction does not bar the candidate.

    Design: Difficulty/transitive_cascade/falsified_education_final_cascade
    """
    ctx = setup_license_context_nremt()
    case = open_case(
        ctx["candidate"]["id"], violation_type="FALSIFIED_EDUCATION",
        description="Completion hours fabricated by program",
        implicated_completion_record_ids=[ctx["completion_record"]["id"]],
    )
    walk_case_to_decided(
        case["id"], ctx["candidate"]["id"],
        sanction_type="REVOCATION", findings="Education record falsified",
    )
    appeal_case(case["id"], ctx["candidate"]["id"])
    assert refresh_certification(ctx["certification"]["id"])["status"] == "ACTIVE", (
        "sanctions are deferred while the appeal pends"
    )

    decide_appeal(case["id"], "AFFIRMED", rationale="Findings upheld")

    record = refresh_completion_record(ctx["completion_record"]["id"])
    assert record["status"] == "INVALIDATED"
    assert record["invalidated_by_case_id"] == case["id"]
    cert = refresh_certification(ctx["certification"]["id"])
    assert cert["status"] == "REVOKED"
    assert cert["revoked_by_case_id"] == case["id"]
    assert refresh_license_application(ctx["license_application"]["id"])["status"] == "DENIED", (
        "the license denial is credential-mediated: it cites the revoked certification"
    )
    candidate = get_success_data(
        api_client.get_candidate(ctx["candidate"]["id"], ctx["candidate_headers"])
    )
    assert candidate["status"] == "REGISTERED", "REVOCATION does not bar; only PERMANENT_BAR does"


def test_program_revocation_cascade(api):
    """PRD §3.2: "Revoking a program's accreditation fires the program-revocation
    cascade in five ordered hops, each computing its targets after the previous
    hop lands. First, the program's completion records still
    `PENDING_VERIFICATION` move to `REJECTED`. Second, its `VERIFIED` completion
    records whose `completion_date` falls strictly after the revocation's
    `effective_date` become `INVALIDATED`. Third, exam applications still
    `SUBMITTED` that cite a record invalidated in the second hop are `DENIED`,
    with the denial reason recording the program revocation. Fourth,
    certifications whose `basis_completion_record_id` was invalidated in the
    second hop and that stand `ACTIVE`, `SUSPENDED`, or `LAPSED` become
    `REVOKED`, each preserving its prior status in `pre_sanction_status`. Fifth,
    license applications in `UNDER_REVIEW` or `MORE_INFO_REQUIRED` that cite a
    certification revoked in the fourth hop are `DENIED`."

    A revocation backdated to 2027-02-01 invalidates only the post-effective
    records; a pre-effective VERIFIED record survives.

    Design: Difficulty/transitive_cascade/program_revocation_cascade
    """
    advance_clock("2026-09-01T00:00:00Z")
    level = create_level()
    create_state_policy()
    program = create_program(level["id"])

    # Candidate A: full chain to an ACTIVE certification + UNDER_REVIEW license.
    advance_clock("2027-03-01T00:00:00Z")
    cand_a = create_candidate()
    rec_a = create_verified_completion(cand_a["id"], program, "2027-03-01")
    app_a = create_approved_exam_application(cand_a["id"], level["id"], rec_a["id"])
    attempt_a = schedule_attempt(
        cand_a["id"], app_a["att_id"], "2027-03-05T00:00:00Z", "2027-03-07T00:00:00Z",
    )
    advance_clock("2027-03-06T00:00:00Z")
    deliver_attempt(attempt_a["id"])
    psy_a = create_verified_psychomotor(
        cand_a["id"], level["id"], rec_a["id"], exam_date="2027-03-05",
    )
    advance_clock("2027-03-08T00:00:00Z")
    cert_a = issue_certification(
        cand_a["id"], level["id"], app_a["id"], attempt_a["id"], psy_a["id"],
    )
    license_a = create_license_application(
        cand_a["id"], "WA", level["id"], certification_id=cert_a["id"],
    )

    # Candidate B: VERIFIED completion pre-dating the coming effective date.
    cand_b = create_candidate()
    rec_b = create_verified_completion(cand_b["id"], program, "2027-01-15")
    # Candidate C: completion still PENDING_VERIFICATION.
    cand_c = create_candidate()
    rec_c = _create_pending_completion(cand_c["id"], program, "2027-03-10")
    # Candidate D: VERIFIED completion + a still-SUBMITTED exam application.
    cand_d = create_candidate()
    rec_d = create_verified_completion(cand_d["id"], program, "2027-03-05")
    app_d = get_success_data(api_client.create_exam_application(
        {"level_id": level["id"], "completion_record_id": rec_d["id"]},
        make_candidate_headers(cand_d["id"]),
    ))

    record_accreditation_event(
        program["id"], "REVOKED", "2027-02-01",
        reason="Falsified clinical rotation logs discovered",
    )

    assert refresh_completion_record(rec_a["id"])["status"] == "INVALIDATED", (
        "completion 2027-03-01 is strictly after the 2027-02-01 effective date"
    )
    revoked_cert = refresh_certification(cert_a["id"])
    assert revoked_cert["status"] == "REVOKED"
    assert revoked_cert["pre_sanction_status"] == "ACTIVE"
    assert refresh_license_application(license_a["id"])["status"] == "DENIED"
    denied_app = get_success_data(api_client.get_exam_application(
        app_d["id"], make_candidate_headers(cand_d["id"]),
    ))
    assert denied_app["status"] == "DENIED", (
        "the third hop denies SUBMITTED applications citing an invalidated record"
    )
    assert refresh_completion_record(rec_b["id"])["status"] == "VERIFIED", (
        "completion 2027-01-15 predates the effective date and survives"
    )
    assert refresh_completion_record(rec_c["id"])["status"] == "REJECTED", (
        "the first hop rejects records still PENDING_VERIFICATION"
    )
