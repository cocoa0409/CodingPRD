"""Queue A — priority_pair_validation_conflict: when two tiers of the §2.8
validation order could both reject a request, the earlier tier's error wins.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_candidate,
    create_level,
    create_program,
    create_psychomotor_payload,
    create_verified_completion,
    make_candidate_headers,
    make_program_director_headers,
    schedule_attempt_payload,
    setup_scored_attempt,
    validate_error,
)


def test_att_state_error_beats_retake_wait_temporal(api):
    """PRD §2.8: "When several checks could reject the same request, the system
    evaluates them in a fixed tier order and reports the first failure:"
    PRD §2.8: "6. **State preconditions.** The target resource's current state
    must allow the requested transition: the generic `ERR_INVALID_STATE`, or
    the specific state error for the endpoint — `ERR_COMPLETION_NOT_PENDING`,
    `ERR_APPLICATION_NOT_SUBMITTED`, `ERR_APPLICATION_NOT_DENIED`,
    `ERR_ATT_NOT_ISSUABLE`, `ERR_ATTEMPT_NOT_SCHEDULED`, `ERR_RECERT_NOT_DRAFT`,
    `ERR_RECERT_NOT_SUBMITTED`, `ERR_RECERT_NOT_AUDIT_PENDING`,
    `ERR_RECERT_NOT_REOPENABLE`, `ERR_CERTIFICATION_NOT_ACTIVE`,
    `ERR_CERTIFICATION_NOT_LAPSED`, `ERR_LICENSE_NOT_ACTIONABLE`,
    `ERR_LICENSE_NOT_AWAITING_RESPONSE`, `ERR_PSYCHOMOTOR_NOT_SUBMITTED`,
    `ERR_CASE_STAGE_MISMATCH`, or `ERR_REENTRY_NOT_SUBMITTED`."
    PRD §2.8: "9. **Temporal windows**, evaluated in the order these identifiers
    are listed: education validity (`ERR_EDUCATION_VALIDITY_EXPIRED`), delivery
    window (`ERR_DELIVERY_WINDOW_NOT_OPEN`), retake wait
    (`ERR_RETAKE_WAIT_ACTIVE`), recertification window
    (`ERR_RECERT_WINDOW_NOT_OPEN`), credential freshness (`ERR_CREDENTIAL_STALE`),
    CE entry inside the cycle (`ERR_CE_ENTRY_OUTSIDE_CYCLE`), reentry
    availability (`ERR_REENTRY_NOT_AVAILABLE`), clock monotonicity
    (`ERR_CLOCK_REGRESSION`)."
    PRD §3.4: "Scheduling is allowed only while the authorization is `ISSUED`
    and the scheduling instant is on or before its `expires_on`, and only while
    no prior attempt already references it — one attempt per authorization —
    with violations rejected as `ERR_ATT_NOT_ISSUABLE`."

    Scheduling against a CONSUMED authorization while also inside the 15-day
    retake wait violates both rules; the tier-6 state error is reported, not
    the tier-9 temporal one.

    Design: Difficulty/priority_pair_validation_conflict/att_state_error_beats_retake_wait_temporal
    """
    ctx = setup_scored_attempt()  # attempt delivered 2026-09-03T12:00Z; ATT now CONSUMED
    resp = api_client.schedule_cognitive_exam_attempt(
        schedule_attempt_payload(
            ctx["att_id"], "2026-09-10T00:00:00Z", "2026-09-12T00:00:00Z",
        ),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ATT_NOT_ISSUABLE)


def test_segregation_beats_cross_reference_mismatch(api):
    """PRD §2.8: "When several checks could reject the same request, the system
    evaluates them in a fixed tier order and reports the first failure:"
    PRD §2.8: "7. **Compliance gates**, evaluated in this order: the candidate
    is not `BARRED` (`ERR_PERMANENTLY_BARRED`); no disciplinary hold blocks new
    applications (`ERR_DISCIPLINARY_HOLD`); the education program's
    accreditation at the completion date was acceptable
    (`ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION`); segregation of duties is
    respected (`ERR_SEGREGATION_OF_DUTIES`)."
    PRD §2.8: "8. **Cross-record consistency.** All referenced records agree on
    candidate and level; a certification's level is accepted by the target
    state; a cited state examination is usable (`ERR_CROSS_REFERENCE_MISMATCH`,
    `ERR_LEVEL_NOT_ACCEPTED_IN_STATE`, `ERR_STATE_EXAM_NOT_PASSING`)."
    PRD §3.5: "Segregation of duties applies on the program path: the evaluator
    may not be the same user who attested the cited completion record
    (`ERR_SEGREGATION_OF_DUTIES`)."

    A PROGRAM psychomotor submission whose evaluator attested the cited
    completion record AND whose cited record belongs to a different candidate
    violates both rules; the tier-7 segregation error is reported.

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_cross_reference_mismatch
    """
    level = create_level()
    program = create_program(level["id"])  # directed by dir-1
    cand_a = create_candidate()
    cand_b = create_candidate()
    # dir-1 attests candidate B's completion record.
    rec_b = create_verified_completion(cand_b["id"], program)

    resp = api_client.create_psychomotor_verification(
        create_psychomotor_payload(
            cand_a["id"], level["id"], rec_b["id"],
            administered_by="PROGRAM", program_id=program["id"],
            exam_date="2026-09-01",
        ),
        make_program_director_headers("dir-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
