"""Filing to run: the petition review loop, the signature ledger and the
three-hop cascade a voided signature sets off."""

from test_helpers import (
    ApiErrorId,
    PETITION_DEADLINE,
    TEST_USERS,
    adjudicate_signature,
    assert_candidacy,
    assert_petition_ledger_conserved,
    assert_petition_signature,
    create_candidacy_payload,
    create_petition_signature_payload,
    make_candidate_headers,
    make_student_voter_headers,
    read_candidacy,
    read_election,
    read_signature,
    read_student,
    register_student,
    set_clock,
    setup_deficient_candidacy_after_revision_cycle,
    setup_eligible_candidacy_with_verified_signature,
    setup_eligible_slate_with_one_signature_each,
    setup_petition_under_review,
    setup_petitioning_election,
    setup_single_candidate_election,
    setup_suspended_slate_member_awaiting_reapproval,
    submit_petition,
    validate_error,
    validate_paginated,
    validate_success,
)

COMMISSIONER = TEST_USERS["commissioner_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ─── The review loop ──────────────────────────────────────────────────────────

def test_withdrawing_an_already_withdrawn_candidacy_is_refused(api):
    """PRD §3.2: "Withdrawal is available to the candidate from any pre-ballot posture —
    `DRAFT`, `UNDER_REVIEW`, `RETURNED`, `ELIGIBLE`, `PETITION_DEFICIENT` or
    `SLATE_SUSPENDED` — and takes the candidacy to the terminal `WITHDRAWN`, optionally
    recording a `reason`."
    PRD §2.5: "The target row — or, for a child create, the parent row the new child hangs
    from — is in a state from which the requested operation is declared —
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/candidacy_withdraw_twice_returns_invalid_state
    """
    scenario = setup_single_candidate_election(approve=False)
    candidacy = scenario["candidacies"][0]
    headers = make_candidate_headers(candidacy["student_id"])

    withdrawn = validate_success(
        api.withdraw_candidacy(candidacy["id"], headers, {"reason": "Accepted a study-abroad place"})
    )
    assert withdrawn["status"] == "WITHDRAWN"
    version_after_first = withdrawn["version"]

    validate_error(
        api.withdraw_candidacy(candidacy["id"], headers, {"reason": "Duplicate submission"}),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    unchanged = read_candidacy(candidacy["id"])
    assert unchanged["status"] == "WITHDRAWN"
    assert unchanged["version"] == version_after_first, (
        "a refused withdrawal mutates nothing, so the version must not advance"
    )


def test_returning_a_petition_that_was_never_submitted_is_refused(api):
    """PRD §3.2: "A commissioner may push the petition back the other way,
    `UNDER_REVIEW → RETURNED`, supplying a `reason` for the correction, and this too
    requires the election to be `PETITIONING`."
    PRD §2.5: "The target row — or, for a child create, the parent row the new child hangs
    from — is in a state from which the requested operation is declared —
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/candidacy_return_from_draft_returns_invalid_state
    """
    scenario = setup_single_candidate_election(approve=False)
    candidacy = scenario["candidacies"][0]

    validate_error(
        api.return_petition(
            candidacy["id"], {"reason": "Nothing to return yet"}, COMMISSIONER
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    assert read_candidacy(candidacy["id"])["status"] == "DRAFT"


def test_approval_short_of_the_office_signature_requirement_is_refused(api):
    """PRD §3.2: "Three conditions apply: the election is `PETITIONING`, the logical clock
    is at or before `petition_deadline` — note that approval tolerates the deadline instant
    itself, while submission does not — and the candidacy's
    `petition_signature_valid_count` has reached the office's `required_signature_count`,
    compared as "at least", with a shortfall reported as `ERR_INSUFFICIENT_SIGNATURES`."

    Design: Corner/state_machines/candidacy_approve_without_required_signatures_returns_insufficient_signatures
    """
    scenario = setup_petition_under_review(required_signature_count=2, signer_count=1)
    candidacy = scenario["candidacy"]
    adjudicate_signature(scenario["signatures"][0], "VERIFIED")

    validate_error(
        api.approve_candidacy(candidacy["id"], COMMISSIONER),
        ApiErrorId.ERR_INSUFFICIENT_SIGNATURES.value,
        422,
    )

    refused = read_candidacy(candidacy["id"])
    assert refused["status"] == "UNDER_REVIEW"
    assert refused["petition_signature_valid_count"] == 1, (
        "one valid signature against a requirement of two"
    )


def test_submitting_a_petition_at_the_deadline_instant_is_refused(api):
    """PRD §3.2: "In all three cases the election must be `PETITIONING` and the logical
    clock must stand strictly before `petition_deadline`, or the request is refused with
    `ERR_PETITION_DEADLINE_PASSED`; a first submission out of `DRAFT` additionally
    re-runs the full candidate-eligibility check."

    Design: Corner/validations/submit_petition_after_deadline_returns_petition_deadline_passed
    """
    scenario = setup_single_candidate_election(approve=False)
    candidacy = scenario["candidacies"][0]
    set_clock(PETITION_DEADLINE)

    validate_error(
        api.submit_petition(candidacy["id"], make_candidate_headers(candidacy["student_id"])),
        ApiErrorId.ERR_PETITION_DEADLINE_PASSED.value,
        422,
    )

    assert read_candidacy(candidacy["id"])["status"] == "DRAFT"
    assert read_election(scenario["election"]["id"])["status"] == "PETITIONING", (
        "the phase gate passed; only the deadline refused the request"
    )


def test_a_student_may_hold_only_one_live_candidacy_per_election(api):
    """PRD §3.2: "The student must not already hold a candidacy in this same election
    whose `status` is anything other than `WITHDRAWN` or `VACATED`; a second live filing
    is `ERR_DUPLICATE_CANDIDACY`."

    Design: Corner/validations/second_candidacy_in_same_election_returns_duplicate_candidacy
    """
    scenario = setup_petitioning_election(
        offices=[
            {"name": "President", "eligible_class_years": ["SENIOR"]},
            {"name": "Treasurer", "eligible_class_years": ["SENIOR"]},
        ],
        candidates=[{"office": 0}],
        approve=False,
    )
    student = scenario["candidate_students"][0]
    treasurer = scenario["offices"][1]

    validate_error(
        api.create_candidacy(
            create_candidacy_payload(
                scenario["election"]["id"], treasurer["id"], student["id"]
            ),
            make_candidate_headers(student["id"]),
        ),
        ApiErrorId.ERR_DUPLICATE_CANDIDACY.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_candidacies(COMMISSIONER, params={"student_id": student["id"]})
    )
    assert meta["total_count"] == 1, "the second filing was refused outright"


def test_filing_below_the_office_grade_floor_is_refused(api):
    """PRD §3.2: "The student must clear every eligibility bar the office sets —
    `enrollment_status` equal to `ENROLLED`, `disciplinary_hold` false, `class_year`
    present in the office's `eligible_class_years`, `gpa` at least the office's `min_gpa`,
    and `credits_completed` at least the office's `min_credits` — with any failure
    reported as `ERR_CANDIDATE_INELIGIBLE`."

    Design: Corner/validations/candidate_below_office_min_gpa_returns_candidate_ineligible
    """
    scenario = setup_petitioning_election(
        offices=[{"eligible_class_years": ["SENIOR"], "min_gpa": 3.00, "min_credits": 60}],
        candidates=[],
        approve=False,
    )
    student = register_student(class_year="SENIOR", gpa=2.50, credits_completed=90)

    validate_error(
        api.create_candidacy(
            create_candidacy_payload(
                scenario["election"]["id"], scenario["office"]["id"], student["id"]
            ),
            make_candidate_headers(student["id"]),
        ),
        ApiErrorId.ERR_CANDIDATE_INELIGIBLE.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_candidacies(
            COMMISSIONER, params={"election_id": scenario["election"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "the ineligible filing mints no candidacy"


# ─── The signature ledger ─────────────────────────────────────────────────────

def test_a_candidate_may_not_sign_their_own_petition(api):
    """PRD §3.3: "and the signer must not be the candidate — `signer_student_id` differing
    from the candidacy's own `student_id` — with self-signature reported as
    `ERR_SELF_SIGNATURE`."

    Design: Corner/validations/candidate_signing_own_petition_returns_self_signature
    """
    scenario = setup_petition_under_review(required_signature_count=1, signer_count=0)
    candidacy = scenario["candidacy"]
    own_student_id = candidacy["student_id"]

    validate_error(
        api.create_petition_signature(
            create_petition_signature_payload(candidacy["id"], own_student_id),
            make_student_voter_headers(own_student_id),
        ),
        ApiErrorId.ERR_SELF_SIGNATURE.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_petition_signatures(
            COMMISSIONER, params={"candidacy_id": candidacy["id"]}
        )
    )
    assert meta["total_count"] == 0, "the refused signature was never written"
    assert read_candidacy(candidacy["id"])["petition_signature_total_count"] == 0


def test_a_second_signature_from_the_same_signer_is_refused(api):
    """PRD §3.3: "the signer must not already hold a signature on this same candidacy in
    any status other than `VOIDED` (`ERR_DUPLICATE_SIGNATURE`)"

    Design: Corner/validations/second_signature_from_same_signer_returns_duplicate_signature
    """
    scenario = setup_petition_under_review(required_signature_count=1, signer_count=1)
    candidacy = scenario["candidacy"]
    signer = scenario["signers"][0]

    validate_error(
        api.create_petition_signature(
            create_petition_signature_payload(
                candidacy["id"], signer["id"], "2026-08-07T00:00:00Z"
            ),
            make_student_voter_headers(signer["id"]),
        ),
        ApiErrorId.ERR_DUPLICATE_SIGNATURE.value,
        409,
    )

    counters = read_candidacy(candidacy["id"])
    assert counters["petition_signature_total_count"] == 1
    assert counters["petition_signature_pending_count"] == 1
    assert_petition_ledger_conserved(counters)


def test_verifying_a_second_signature_lifts_the_valid_count(api):
    """PRD §3.3: "an outcome of `VERIFIED` moves the signature `SUBMITTED → VERIFIED` and
    stamps both `verified_by_user_id` and the signature's `eligibility_result`"
    PRD §3.3: "`petition_signature_valid_count` is the number of verified rows whose
    verdict is `ELIGIBLE`, and `petition_signature_ineligible_count` is the number of
    verified rows minus that valid count."

    Design: Difficulty/compensating_invariant/signature_verify_then_void_restores_valid_count
    """
    scenario = setup_petition_under_review(required_signature_count=2, signer_count=2)
    candidacy = scenario["candidacy"]
    first, second = scenario["signatures"]
    adjudicate_signature(first, "VERIFIED")

    before = read_candidacy(candidacy["id"])
    assert before["petition_signature_valid_count"] == 1
    assert before["petition_signature_pending_count"] == 1

    verified = validate_success(
        api.adjudicate_signature(second["id"], {"outcome": "VERIFIED"}, COMMISSIONER)
    )
    assert_petition_signature(verified)
    assert verified["status"] == "VERIFIED"
    assert verified["eligibility_result"] == "ELIGIBLE"

    after = read_candidacy(candidacy["id"])
    assert after["petition_signature_valid_count"] == 2, (
        f"both verified signers are eligible, got {after['petition_signature_valid_count']}"
    )
    assert after["petition_signature_pending_count"] == 0
    assert after["petition_signature_total_count"] == 2
    assert_petition_ledger_conserved(after)


def test_voiding_a_verified_signature_restores_the_valid_count_and_conserves_the_rows(api):
    """PRD §2.9: "For every candidacy, the sum of `petition_signature_valid_count`,
    `petition_signature_ineligible_count`, `petition_signature_pending_count`,
    `petition_signature_rejected_count` and `petition_signature_voided_count` always
    equals `petition_signature_total_count`."
    PRD §2.9: "Voiding never deletes a row, so `petition_signature_total_count` is
    unchanged by any voiding; and if a signature is verified and then voided, the
    candidacy's `petition_signature_valid_count` returns to exactly the value it had
    before the verification."

    Design: Difficulty/compensating_invariant/signature_verify_then_void_restores_valid_count
    """
    scenario = setup_petition_under_review(required_signature_count=2, signer_count=2)
    candidacy = scenario["candidacy"]
    first, second = scenario["signatures"]
    adjudicate_signature(first, "VERIFIED")

    adjudicate_signature(second, "VERIFIED")
    intermediate = read_candidacy(candidacy["id"])
    assert intermediate["petition_signature_valid_count"] == 2

    voided = validate_success(
        api.void_signature(
            second["id"], COMMISSIONER,
            {"reason": "Signer was not enrolled on the signing date"},
        )
    )
    assert voided["status"] == "VOIDED"

    after = read_candidacy(candidacy["id"])
    assert after["petition_signature_valid_count"] == 1, (
        "the valid count returns to its value before the verification, got "
        f"{after['petition_signature_valid_count']}"
    )
    assert after["petition_signature_ineligible_count"] == 0
    assert after["petition_signature_pending_count"] == 0
    assert after["petition_signature_rejected_count"] == 0
    assert after["petition_signature_voided_count"] == 1
    assert after["petition_signature_total_count"] == 2, (
        "voiding never deletes a row"
    )
    assert_petition_ledger_conserved(after)
    assert after["status"] == "UNDER_REVIEW"


# ─── The three-hop petition-void cascade ──────────────────────────────────────

def test_voiding_the_leaders_signature_suspends_only_its_own_slate(api):
    """PRD §3.3: "The second hop fires when the recomputed
    `petition_signature_valid_count` has fallen strictly below the office's
    `required_signature_count` while the candidacy sits in `ELIGIBLE`: the candidacy drops
    `ELIGIBLE → PETITION_DEFICIENT`."
    PRD §3.3: "The third hop follows from the second: every candidacy whose
    `slate_leader_candidacy_id` names the newly deficient leader and which is itself
    `ELIGIBLE` drops `ELIGIBLE → SLATE_SUSPENDED`."

    Design: Corner/state_machines/petition_void_cascade_suspends_slate_members
    """
    scenario = setup_eligible_slate_with_one_signature_each()

    voided = validate_success(
        api.void_signature(
            scenario["signatures"]["leader"]["id"], COMMISSIONER,
            {"reason": "Signer never signed the sheet"},
        )
    )
    assert voided["status"] == "VOIDED"

    leader = read_candidacy(scenario["leader"]["id"])
    member = read_candidacy(scenario["member"]["id"])
    independent = read_candidacy(scenario["independent"]["id"])

    assert leader["petition_signature_valid_count"] == 0
    assert leader["status"] == "PETITION_DEFICIENT", (
        f"the leader falls below its requirement, got {leader['status']}"
    )
    assert member["status"] == "SLATE_SUSPENDED", (
        f"the slate member is suspended by the third hop, got {member['status']}"
    )
    assert member["petition_signature_valid_count"] == 1, (
        "suspension leaves the member's own signature ledger untouched"
    )
    assert independent["status"] == "ELIGIBLE", (
        "an unrelated candidacy outside the slate is not touched"
    )


def test_reapproving_the_leader_lifts_its_suspended_member(api):
    """PRD §3.2: "Approval also repairs a slate: every candidacy whose
    `slate_leader_candidacy_id` points at the newly approved leader and which currently
    sits in `SLATE_SUSPENDED` moves `SLATE_SUSPENDED → ELIGIBLE` in the same transaction."

    Design: Corner/state_machines/leader_reapproval_returns_suspended_slate_member_to_eligible
    """
    scenario = setup_suspended_slate_member_awaiting_reapproval()

    approved = validate_success(
        api.approve_candidacy(scenario["leader"]["id"], COMMISSIONER)
    )
    assert_candidacy(approved)
    assert approved["status"] == "ELIGIBLE"

    leader = read_candidacy(scenario["leader"]["id"])
    member = read_candidacy(scenario["member"]["id"])
    assert leader["petition_signature_valid_count"] == 1
    assert leader["petition_signature_total_count"] == 2, (
        "the voided row is still counted in the total"
    )
    assert leader["petition_signature_voided_count"] == 1
    assert_petition_ledger_conserved(leader)
    assert member["status"] == "ELIGIBLE", (
        f"the suspension is reversible, got {member['status']}"
    )


def test_registrar_hold_rescores_the_verified_signature_and_deficits_the_candidacy(api):
    """PRD §3.1: "Amending any of `class_year`, `enrollment_status`, `gpa`,
    `credits_completed` or `disciplinary_hold` on a student record re-evaluates the
    eligibility verdict on every petition signature that student has already given, and
    moves the affected candidacies' signature counters accordingly — the mechanism is
    described in Section 3.3."
    PRD §3.3: "Each verified row receives exactly one verdict in `eligibility_result`,
    decided by the first of these tests that matches: if the signer's `enrollment_status`
    is anything other than `ENROLLED` the verdict is `INELIGIBLE_NOT_ENROLLED`; otherwise,
    if the signer's `disciplinary_hold` is true the verdict is `INELIGIBLE_HOLD`;
    otherwise, if the signer's `class_year` is absent from the `eligible_class_years` of
    the office the candidacy seeks the verdict is `INELIGIBLE_CLASS_YEAR`; otherwise the
    verdict is `ELIGIBLE`."
    PRD §3.3: "`petition_signature_valid_count` is the number of verified rows whose
    verdict is `ELIGIBLE`, and `petition_signature_ineligible_count` is the number of
    verified rows minus that valid count."

    The instance also names the `ELIGIBLE → PETITION_DEFICIENT` drop, but the PRD binds
    that hop to the voiding cascade rather than to a registrar sync, so the state
    transition is not asserted here — only the re-scoring the PRD does state for this
    trigger.

    Design: Corner/calculations/registrar_hold_rescores_verified_signature_and_marks_candidacy_deficient
    """
    scenario = setup_eligible_candidacy_with_verified_signature()

    synced = validate_success(
        api.update_student(
            scenario["signer"]["id"], {"disciplinary_hold": True}, REGISTRAR
        )
    )
    assert synced["disciplinary_hold"] is True

    signature = read_signature(scenario["signature"]["id"])
    assert signature["status"] == "VERIFIED", (
        "the registrar sync re-scores the verdict without moving the signature's status"
    )
    assert signature["eligibility_result"] == "INELIGIBLE_HOLD"

    candidacy = read_candidacy(scenario["candidacy"]["id"])
    assert candidacy["petition_signature_valid_count"] == 0
    assert candidacy["petition_signature_ineligible_count"] == 1
    assert candidacy["petition_signature_total_count"] == 1
    assert_petition_ledger_conserved(candidacy)
    assert read_student(scenario["signer"]["id"])["disciplinary_hold"] is True


# ─── The revision cycle ───────────────────────────────────────────────────────

def test_a_deficient_candidacy_climbs_back_into_under_review(api):
    """PRD §3.2: "Submitting a petition advances the candidacy `DRAFT → UNDER_REVIEW`, and
    the same act also serves as the re-submission from `RETURNED → UNDER_REVIEW` and from
    `PETITION_DEFICIENT → UNDER_REVIEW`."
    PRD §3.3: "A deficient leader, for its part, climbs back by re-submitting its petition
    into `UNDER_REVIEW` and being approved again."

    Design: Difficulty/non_linear_state_machine/candidacy_status_revision_cycle_returns_to_under_review
    """
    scenario = setup_deficient_candidacy_after_revision_cycle()
    candidacy = scenario["candidacy"]

    before = read_candidacy(candidacy["id"])
    assert before["status"] == "PETITION_DEFICIENT", (
        f"the voided signature left the candidacy deficient, got {before['status']}"
    )

    resubmitted = validate_success(
        api.submit_petition(
            candidacy["id"], make_candidate_headers(candidacy["student_id"])
        )
    )

    assert_candidacy(resubmitted)
    assert resubmitted["status"] == "UNDER_REVIEW", (
        f"the third visit to UNDER_REVIEW, got {resubmitted['status']}"
    )
    assert resubmitted["version"] >= 6, (
        "the row has been mutated at least six times along the cycle, version is "
        f"{resubmitted['version']}"
    )


def test_the_revision_cycle_leaves_the_signature_ledger_conserved(api):
    """PRD §2.9: "For every candidacy, the sum of `petition_signature_valid_count`,
    `petition_signature_ineligible_count`, `petition_signature_pending_count`,
    `petition_signature_rejected_count` and `petition_signature_voided_count` always
    equals `petition_signature_total_count`."
    PRD §2.9: "Voiding never deletes a row, so `petition_signature_total_count` is
    unchanged by any voiding; and if a signature is verified and then voided, the
    candidacy's `petition_signature_valid_count` returns to exactly the value it had
    before the verification."

    Design: Difficulty/non_linear_state_machine/candidacy_status_revision_cycle_returns_to_under_review
    """
    scenario = setup_deficient_candidacy_after_revision_cycle()
    candidacy = scenario["candidacy"]
    submit_petition(candidacy)

    after = read_candidacy(candidacy["id"])
    assert after["status"] == "UNDER_REVIEW"
    assert after["petition_signature_valid_count"] == 0
    assert after["petition_signature_voided_count"] == 1
    assert after["petition_signature_total_count"] == 1
    assert after["petition_signature_pending_count"] == 0
    assert after["petition_signature_rejected_count"] == 0
    assert_petition_ledger_conserved(after)

    signature = read_signature(scenario["signature"]["id"])
    assert signature["status"] == "VOIDED"
