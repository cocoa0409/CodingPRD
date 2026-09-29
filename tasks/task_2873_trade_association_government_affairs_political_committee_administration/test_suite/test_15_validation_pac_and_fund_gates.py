"""Prior-approval, scoring, fund-balance and contribution-state gates."""
from test_helpers import (
    ADMIN,
    api_client,
    COMPLIANCE,
    COMPLIANCE_2,
    create_activity_payload,
    create_committee,
    create_contribution_payload,
    create_policy_position_payload,
    create_prior_approval_payload,
    create_receipt_payload,
    DIRECTOR,
    draft_position,
    enroll_member,
    grant_prior_approval_payload,
    make_member_delegate_headers,
    open_fund,
    read_candidate,
    read_contribution,
    read_fund,
    read_member,
    read_position,
    register_candidate,
    request_prior_approval,
    setup_granted_prior_approval,
    setup_pending_contribution,
    setup_suspended_contribution,
    TRUSTEE_2,
    validate_error,
    validate_paginated,
    validate_success,
    void_payload,
)


def _approvals_of(member_id):
    rows, meta = validate_paginated(
        api_client.list_member_prior_approvals(member_id, COMPLIANCE)
    )
    return rows, meta


def test_a_suspended_member_cannot_grant_its_own_prior_approval():
    """Standing is checked on the grant even though the window is current.

    PRD 3.8: "The delegate's own member record must be `ACTIVE`, or the grant is refused
    with `ERR_MEMBER_NOT_ACTIVE`; and the logical clock's date must not have passed
    `expires_at_date`, or it is refused with `ERR_PRIOR_APPROVAL_EXPIRED` — an approval
    whose window has already elapsed cannot be resurrected by signing it late."

    Design: Corner/Validations/granting_a_prior_approval_for_a_suspended_member_rejected
    """
    member = enroll_member(
        legal_name="Alpha Steel Co",
        membership_tier="PREMIER",
        restricted_class_size=25,
        status="SUSPENDED",
    )
    approval = request_prior_approval(
        member["id"],
        solicitable_class_size=5,
        effective_date="2026-01-01",
        expires_at_date="2026-12-31",
    )
    assert approval["status"] == "REQUESTED"

    validate_error(
        api_client.grant_prior_approval(
            approval["id"],
            grant_prior_approval_payload(authorized_by_name="A. Steel, CFO"),
            make_member_delegate_headers(member["id"]),
        ),
        "ERR_MEMBER_NOT_ACTIVE",
        409,
    )

    rows, _meta = _approvals_of(member["id"])
    stored = next(row for row in rows if row["id"] == approval["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["granted_at"] is None
    assert stored["granted_by_user_id"] is None
    assert stored["authorized_by_name"] is None
    assert read_member(member["id"])["pac_solicitable"] is False


def test_a_malformed_window_and_an_oversized_class_are_refused_by_their_own_errors():
    """The shape test and the class-size test are separate gates on one create.

    PRD 3.8: "The shape test then requires that `effective_date` is not after
    `expires_at_date`, that both dates fall inside the stated `calendar_year`, and that the
    window spans no more than 365 days; a violation is refused with
    `ERR_PRIOR_APPROVAL_WINDOW_INVALID`."
    PRD 3.8: "The request is refused with `ERR_CLASS_SIZE_EXCEEDED` when
    `solicitable_class_size` is greater than the member's own `restricted_class_size`."

    Design: Corner/Validations/prior_approval_window_shape_and_class_size_gates_rejected
    """
    member = enroll_member(
        legal_name="Alpha Steel Co", membership_tier="PREMIER", restricted_class_size=25
    )

    validate_error(
        api_client.create_prior_approval(
            create_prior_approval_payload(
                member["id"],
                solicitable_class_size=5,
                effective_date="2026-07-01",
                expires_at_date="2026-06-01",
            ),
            COMPLIANCE,
        ),
        "ERR_PRIOR_APPROVAL_WINDOW_INVALID",
        422,
    )
    validate_error(
        api_client.create_prior_approval(
            create_prior_approval_payload(
                member["id"],
                solicitable_class_size=5,
                effective_date="2026-07-01",
                expires_at_date="2027-01-15",
            ),
            COMPLIANCE,
        ),
        "ERR_PRIOR_APPROVAL_WINDOW_INVALID",
        422,
    )
    validate_error(
        api_client.create_prior_approval(
            create_prior_approval_payload(
                member["id"],
                solicitable_class_size=30,
                effective_date="2026-07-01",
                expires_at_date="2026-12-31",
            ),
            COMPLIANCE,
        ),
        "ERR_CLASS_SIZE_EXCEEDED",
        422,
    )

    rows, meta = _approvals_of(member["id"])
    assert rows == []
    assert meta["total_count"] == 0

    accepted = validate_success(
        api_client.create_prior_approval(
            create_prior_approval_payload(
                member["id"],
                solicitable_class_size=25,
                effective_date="2026-07-01",
                expires_at_date="2026-12-31",
            ),
            COMPLIANCE,
        ),
        201,
    )
    assert accepted["solicitable_class_size"] == 25


def test_a_proposal_below_the_score_floor_is_refused_for_any_amount():
    """The floor is evaluated before any ceiling arithmetic, so even one cent fails.

    PRD 3.9: "A score below 55.00 earns nothing and the proposal is refused outright with
    `ERR_SCORE_BELOW_FLOOR`; that floor check happens before any ceiling arithmetic."

    Design: Corner/Validations/contribution_proposal_below_the_score_floor_rejected
    """
    fund = open_fund(min_reserve_cents=0)
    candidate = register_candidate(
        incumbency="CHALLENGER", voting_alignment_pct=20.00, committee_relevance_score=20
    )

    validate_error(
        api_client.create_pac_contribution(
            create_contribution_payload(fund["id"], candidate["id"], amount_cents=1),
            DIRECTOR,
        ),
        "ERR_SCORE_BELOW_FLOOR",
        422,
    )

    rows, meta = validate_paginated(
        api_client.list_fund_pac_contributions(fund["id"], COMPLIANCE)
    )
    assert rows == []
    assert meta["total_count"] == 0

    stored = read_candidate(candidate["id"])
    assert float(stored["latest_support_score"]) == 0.00
    assert stored["pending_support_cents"] == 0


def test_one_coherence_error_covers_the_position_scope_and_the_receipt_year():
    """A federal position under a state committee and a stale receipt share an error.

    PRD 3.3: "The jurisdiction must sit inside the committee's scope: a committee scoped
    `MULTI` accepts any of the three, while a single-jurisdiction committee accepts only
    its own, and a mismatch is refused with `ERR_JURISDICTION_SCOPE_MISMATCH`."
    PRD 3.8: "The receipt must also belong to the fund's accounting year: a `received_date`
    whose calendar year differs from the fund's `fund_year` is refused with
    `ERR_JURISDICTION_SCOPE_MISMATCH`."

    Design: Corner/Validations/position_scope_and_receipt_year_coherence_gates_rejected
    """
    committee = create_committee(jurisdiction_scope="STATE_CA")
    approved = setup_granted_prior_approval()
    fund = open_fund(fund_year=2026, jurisdiction_code="FEDERAL", min_reserve_cents=0)

    validate_error(
        api_client.create_policy_position(
            create_policy_position_payload(
                committee["id"],
                title="Oppose Section 232 Expansion",
                jurisdiction_code="FEDERAL",
                summary="Federal scope under a state committee.",
            ),
            DIRECTOR,
        ),
        "ERR_JURISDICTION_SCOPE_MISMATCH",
        422,
    )
    validate_error(
        api_client.create_fund_receipt(
            fund["id"],
            create_receipt_payload(
                approved["member"]["id"], amount_cents=100_000, received_date="2025-12-31"
            ),
            COMPLIANCE,
        ),
        "ERR_JURISDICTION_SCOPE_MISMATCH",
        422,
    )

    rows, meta = validate_paginated(
        api_client.list_committee_policy_positions(committee["id"], DIRECTOR)
    )
    assert rows == []
    assert meta["total_count"] == 0

    stored_fund = read_fund(fund["id"])
    assert stored_fund["receipts_total_cents"] == 0
    assert stored_fund["available_balance_cents"] == 0

    in_scope = validate_success(
        api_client.create_policy_position(
            create_policy_position_payload(
                committee["id"],
                title="Oppose Section 232 Expansion",
                jurisdiction_code="STATE_CA",
                summary="State scope under a state committee.",
            ),
            DIRECTOR,
        ),
        201,
    )
    assert in_scope["jurisdiction_code"] == "STATE_CA"


def test_the_balance_test_is_re_run_at_board_approval_not_at_proposal():
    """A legal proposal is refused later because the fund cannot cover it.

    PRD 3.8: "And the amount must fit the fund: `amount_cents` must not exceed the fund's
    current `available_balance_cents`, with equality accepted, and an amount larger than
    the balance is refused with `ERR_INSUFFICIENT_FUND_BALANCE`."

    Design: Corner/Validations/board_approving_more_than_the_available_balance_rejected
    """
    state = setup_pending_contribution(
        amount_cents=250_000, min_reserve_cents=0, receipt_amount_cents=100_000
    )
    contribution = state["contribution"]
    assert contribution["max_allowed_cents"] == 250_000
    assert state["fund"]["posture"] == "OPEN"

    validate_error(
        api_client.board_approve_contribution(contribution["id"], TRUSTEE_2),
        "ERR_INSUFFICIENT_FUND_BALANCE",
        422,
    )

    stored = read_contribution(contribution["id"])
    assert stored["status"] == "PENDING_BOARD"
    assert stored["board_approved_by_user_id"] is None

    fund = read_fund(state["fund"]["id"])
    assert fund["committed_balance_cents"] == 0
    assert fund["available_balance_cents"] == 100_000
    assert fund["posture"] == "OPEN"

    candidate = read_candidate(state["candidate"]["id"])
    assert candidate["pending_support_cents"] == 250_000
    assert candidate["committed_support_cents"] == 0


def test_a_pending_contribution_cannot_be_disbursed():
    """Disbursement is declared only from BOARD_APPROVED, so nothing moves.

    PRD 3.8: "A contribution in any other status is refused with
    `ERR_CONTRIBUTION_NOT_APPROVED`."

    Design: Corner/Validations/disbursing_a_contribution_that_was_never_approved_rejected
    """
    state = setup_pending_contribution(
        amount_cents=100_000, min_reserve_cents=0, receipt_amount_cents=100_000
    )
    contribution = state["contribution"]

    validate_error(
        api_client.disburse_contribution(contribution["id"], COMPLIANCE),
        "ERR_CONTRIBUTION_NOT_APPROVED",
        409,
    )

    stored = read_contribution(contribution["id"])
    assert stored["status"] == "PENDING_BOARD"
    assert stored["disbursed_at"] is None

    fund = read_fund(state["fund"]["id"])
    assert fund["disbursed_total_cents"] == 0
    assert fund["committed_balance_cents"] == 0

    candidate = read_candidate(state["candidate"]["id"])
    assert candidate["pending_support_cents"] == 100_000
    assert candidate["committed_support_cents"] == 0
    assert candidate["disbursed_support_cents"] == 0


def test_a_requested_approval_cannot_be_short_circuited_to_revoked():
    """Revocation only leaves GRANTED, and the refusal leaves the row usable.

    PRD 3.8: "Granting anything that is not `REQUESTED`, or revoking anything that is not
    `GRANTED` — including one already expired — is refused with
    `ERR_INVALID_PRIOR_APPROVAL_STATE`."

    Design: Corner/Validations/revoking_a_prior_approval_that_was_never_granted_rejected
    """
    member = enroll_member(
        legal_name="Alpha Steel Co", membership_tier="PREMIER", restricted_class_size=25
    )
    approval = request_prior_approval(
        member["id"], effective_date="2026-01-01", expires_at_date="2026-12-31"
    )
    delegate = make_member_delegate_headers(member["id"])

    validate_error(
        api_client.revoke_prior_approval(approval["id"], delegate),
        "ERR_INVALID_PRIOR_APPROVAL_STATE",
        409,
    )

    rows, _meta = _approvals_of(member["id"])
    stored = next(row for row in rows if row["id"] == approval["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["revoked_at"] is None

    granted = validate_success(
        api_client.grant_prior_approval(
            approval["id"], grant_prior_approval_payload(), delegate
        ),
        200,
    )
    assert granted["status"] == "GRANTED"


def test_a_suspended_row_reports_its_own_error_ahead_of_the_fund_posture():
    """Two gates are live at once and the contribution-state gate wins.

    PRD 3.8: "The contribution must be `PENDING_BOARD`: a row the fund's restricted
    posture pushed to `SUSPENDED` is refused specifically with `ERR_CONTRIBUTION_SUSPENDED`,
    while a row that is `BOARD_APPROVED`, `DISBURSED` or `VOIDED` is refused with
    `ERR_CONTRIBUTION_NOT_PENDING`."

    Design: Corner/Validations/board_approving_a_suspended_contribution_rejected
    """
    state = setup_suspended_contribution(second_amount_cents=200_000)
    suspended = state["contribution_y"]
    assert suspended["status"] == "SUSPENDED"
    assert state["fund"]["posture"] == "RESTRICTED"

    validate_error(
        api_client.board_approve_contribution(suspended["id"], TRUSTEE_2),
        "ERR_CONTRIBUTION_SUSPENDED",
        409,
    )

    stored = read_contribution(suspended["id"])
    assert stored["status"] == "SUSPENDED"
    assert stored["board_approved_by_user_id"] is None

    fund = read_fund(state["fund"]["id"])
    assert fund["posture"] == "RESTRICTED"
    assert fund["committed_balance_cents"] == 250_000
    assert fund["available_balance_cents"] == 350_000

    candidate_b = read_candidate(state["candidate_b"]["id"])
    assert candidate_b["pending_support_cents"] == 0
    assert candidate_b["committed_support_cents"] == 0


def _unused_uuid(index: int) -> str:
    """A well-formed UUID that matches no row in any table."""
    return f"00000000-0000-0000-0000-{index:012d}"


def test_every_unknown_identifier_reports_its_own_entity_not_found():
    """Path ids are checked left to right and body foreign keys name their entity.

    PRD 2.11: "Every path-templated resource exists, checked left to right — otherwise the
    matching not-found error (404)."
    PRD 2.11: "Every foreign key supplied in the body resolves — otherwise the matching
    not-found error (404). This gate governs seating a member, drafting a position, logging
    an activity, opening a report, launching a campaign, requesting a prior approval,
    crediting a fund receipt, and proposing a contribution."

    Design: Corner/Validations/unknown_path_and_body_identifiers_return_their_entity_not_found
    """
    committee = create_committee()
    position = draft_position(committee["id"])
    fund = open_fund()
    ghost_member = _unused_uuid(1)
    ghost_registration = _unused_uuid(5)
    ghost_candidate = _unused_uuid(10)
    ghost_delegate = make_member_delegate_headers(ghost_member)

    path_cases = [
        (api_client.get_member(ghost_member, ADMIN), "ERR_MEMBER_NOT_FOUND"),
        (api_client.get_committee(_unused_uuid(2), DIRECTOR), "ERR_COMMITTEE_NOT_FOUND"),
        (
            api_client.get_policy_position(_unused_uuid(3), DIRECTOR),
            "ERR_POSITION_NOT_FOUND",
        ),
        (
            api_client.withdraw_dissent(position["id"], _unused_uuid(4), ghost_delegate),
            "ERR_VOTE_NOT_FOUND",
        ),
        (
            api_client.get_lobbying_registration(ghost_registration, COMPLIANCE),
            "ERR_REGISTRATION_NOT_FOUND",
        ),
        (
            api_client.void_lobbying_activity(
                _unused_uuid(6), void_payload(void_reason="no such activity"), DIRECTOR
            ),
            "ERR_ACTIVITY_NOT_FOUND",
        ),
        (
            api_client.certify_expenditure_report(_unused_uuid(7), COMPLIANCE_2),
            "ERR_REPORT_NOT_FOUND",
        ),
        (
            api_client.get_grassroots_campaign(_unused_uuid(8), DIRECTOR),
            "ERR_CAMPAIGN_NOT_FOUND",
        ),
        (
            api_client.grant_prior_approval(
                _unused_uuid(9), grant_prior_approval_payload(), ghost_delegate
            ),
            "ERR_PRIOR_APPROVAL_NOT_FOUND",
        ),
        (api_client.get_candidate(ghost_candidate, DIRECTOR), "ERR_CANDIDATE_NOT_FOUND"),
        (
            api_client.get_segregated_fund(_unused_uuid(11), COMPLIANCE),
            "ERR_FUND_NOT_FOUND",
        ),
        (
            api_client.get_pac_contribution(_unused_uuid(12), DIRECTOR),
            "ERR_CONTRIBUTION_NOT_FOUND",
        ),
    ]
    for response, error_id in path_cases:
        validate_error(response, error_id, 404)

    body_cases = [
        (
            api_client.create_pac_contribution(
                create_contribution_payload(fund["id"], ghost_candidate), DIRECTOR
            ),
            "ERR_CANDIDATE_NOT_FOUND",
        ),
        (
            api_client.create_prior_approval(
                create_prior_approval_payload(ghost_member), COMPLIANCE
            ),
            "ERR_MEMBER_NOT_FOUND",
        ),
        (
            api_client.create_lobbying_activity(
                create_activity_payload(
                    ghost_registration,
                    position["id"],
                    activity_date="2026-08-01",
                    hours=1.500,
                    expenditure_cents=100_000,
                ),
                DIRECTOR,
            ),
            "ERR_REGISTRATION_NOT_FOUND",
        ),
    ]
    for response, error_id in body_cases:
        validate_error(response, error_id, 404)

    unchanged_fund = read_fund(fund["id"])
    assert unchanged_fund["receipts_total_cents"] == 0
    assert unchanged_fund["available_balance_cents"] == 0
    assert read_position(position["id"])["status"] == "DRAFT"

    seat_rows, seat_meta = validate_paginated(
        api_client.list_committee_seats(committee["id"], DIRECTOR)
    )
    assert seat_rows == []
    assert seat_meta["total_count"] == 0
