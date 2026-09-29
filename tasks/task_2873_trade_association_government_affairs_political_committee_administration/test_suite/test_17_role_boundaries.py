"""What each of the five roles may and may not do at the endpoint boundary."""
from test_helpers import (
    COMPLIANCE,
    COMPLIANCE_2,
    DEFAULT_CLOCK_STAMP,
    DIRECTOR,
    DUAL_HAT_USER_ID,
    TEST_USERS,
    TRUSTEE,
    api_client,
    assert_instant_equals,
    create_candidate_payload,
    create_committee_payload,
    create_contribution_payload,
    create_fund_payload,
    create_prior_approval_payload,
    create_registration_payload,
    create_seat_payload,
    draft_registration,
    enroll_member,
    make_member_delegate_headers,
    open_fund,
    propose_contribution,
    read_candidate,
    read_committee,
    read_contribution,
    read_registration,
    register_candidate,
    setup_position_in_balloting,
    validate_error,
    validate_paginated,
    validate_success,
)

DUAL_HAT_DIRECTOR = TEST_USERS["dual_hat_director_headers"]
DUAL_HAT_TRUSTEE = TEST_USERS["dual_hat_trustee_headers"]


def test_the_compliance_officer_walks_its_whole_regulatory_surface():
    """One role owns registrations, the amendment cycle, approvals and the fund.

    PRD 2.1: "**`ComplianceOfficer`** — owns the regulatory surface: lobbying registrations
    and their amendments, expenditure reports and their certification, PAC prior approvals,
    the separate segregated fund, its filing calendar, and contribution disbursement and
    voiding."
    PRD 3.5: "A compliance officer opens an amendment, moving `ACTIVE → AMENDMENT_PENDING`,
    and certifies it afterwards, moving `AMENDMENT_PENDING → ACTIVE` and incrementing
    `amendment_round` by one."

    Design: Corner/RBAC/compliance_officer_performs_its_exclusive_regulatory_operations
    """
    member = enroll_member(
        legal_name="Alpha Steel Co", membership_tier="PREMIER", restricted_class_size=25
    )

    created = validate_success(
        api_client.create_lobbying_registration(create_registration_payload(), COMPLIANCE),
        201,
    )
    filed = validate_success(
        api_client.file_registration(created["id"], COMPLIANCE), 200
    )
    assert filed["status"] == "ACTIVE"
    assert_instant_equals(filed["filed_at"], DEFAULT_CLOCK_STAMP, "filed_at")

    amending = validate_success(
        api_client.amend_registration(created["id"], COMPLIANCE), 200
    )
    assert amending["status"] == "AMENDMENT_PENDING"
    assert amending["amendment_round"] == 0

    amended = validate_success(
        api_client.certify_registration_amendment(created["id"], COMPLIANCE_2), 200
    )
    assert amended["status"] == "ACTIVE"
    assert amended["amendment_round"] == 1

    approval = validate_success(
        api_client.create_prior_approval(
            create_prior_approval_payload(
                member["id"],
                solicitable_class_size=5,
                effective_date="2026-01-01",
                expires_at_date="2026-12-31",
            ),
            COMPLIANCE,
        ),
        201,
    )
    assert approval["status"] == "REQUESTED"

    fund = validate_success(
        api_client.create_segregated_fund(
            create_fund_payload(name="NMA Federal PAC", min_reserve_cents=400_000), COMPLIANCE
        ),
        201,
    )
    assert fund["posture"] == "OPEN"
    assert fund["receipts_total_cents"] == 0
    assert fund["available_balance_cents"] == 0

    assert read_registration(created["id"])["version"] == 4


def test_the_director_may_read_a_registration_but_not_move_its_lifecycle():
    """The role check runs long before the state check, and reads stay open.

    PRD 2.11: "The role is authorised for the endpoint — otherwise `ERR_FORBIDDEN_ROLE`
    (403)."
    PRD 2.1: "When a caller's role is not listed among the roles authorised for the endpoint
    being addressed, the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."

    Design: Corner/RBAC/gov_affairs_director_cannot_file_a_registration_forbidden
    """
    registration = draft_registration()

    validate_error(
        api_client.file_registration(registration["id"], DIRECTOR), "ERR_FORBIDDEN_ROLE", 403
    )
    validate_error(
        api_client.terminate_registration(registration["id"], DIRECTOR),
        "ERR_FORBIDDEN_ROLE",
        403,
    )

    readable = validate_success(
        api_client.get_lobbying_registration(registration["id"], DIRECTOR), 200
    )
    assert readable["status"] == "DRAFT"
    assert readable["filed_at"] is None
    assert readable["terminated_at"] is None
    assert readable["version"] == 1


def test_a_trustee_may_ratify_but_may_neither_propose_nor_register():
    """The board holds no proposal power at all, which is the structural half of the rule.

    PRD 2.1: "**`BoardTrustee`** — board-level ratification only: adopting a committee
    position that reached consensus, and approving a proposed candidate contribution. A
    trustee holds no proposal power whatsoever, which is precisely what makes segregation of
    duties observable rather than aspirational."

    Design: Corner/RBAC/board_trustee_cannot_propose_a_contribution_forbidden
    """
    fund = open_fund(min_reserve_cents=0)
    candidate = register_candidate(voting_alignment_pct=90.00, committee_relevance_score=80)

    validate_error(
        api_client.create_pac_contribution(
            create_contribution_payload(fund["id"], candidate["id"], amount_cents=100_000),
            TRUSTEE,
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api_client.create_candidate(
            create_candidate_payload(
                name="Sen. Mark Ruiz", office="US_SENATE", district_code="CA-AL"
            ),
            TRUSTEE,
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )

    rows, meta = validate_paginated(
        api_client.list_fund_pac_contributions(fund["id"], COMPLIANCE)
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_candidate(candidate["id"])["pending_support_cents"] == 0


def test_a_seated_chair_still_cannot_run_the_committee_machinery():
    """The delegate's write surface is self-service only, even for the chair.

    PRD 2.1: "**`MemberDelegate`** — a member company acting for itself: casting committee
    ballots, filing and withdrawing formal dissent, and granting or revoking its own PAC
    prior approval."
    PRD 2.1: "This check is about the *endpoint*; it is distinct from the ownership check
    described next, which is about the *resource*."

    Design: Corner/RBAC/member_delegate_cannot_run_committee_machinery_forbidden
    """
    state = setup_position_in_balloting()
    committee_id = state["committee"]["id"]
    chair = state["members"][0]
    delegate = make_member_delegate_headers(chair["id"])

    validate_error(
        api_client.create_committee(
            create_committee_payload(
                name="Shadow Committee",
                quorum_threshold_pct=50.00,
                consensus_threshold_pct=50.00,
            ),
            delegate,
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api_client.create_committee_seat(
            committee_id, create_seat_payload(chair["id"], seat_role="MEMBER"), delegate
        ),
        "ERR_FORBIDDEN_ROLE",
        403,
    )
    validate_error(
        api_client.tally_position(state["position"]["id"], delegate),
        "ERR_FORBIDDEN_ROLE",
        403,
    )

    own_seats, own_meta = validate_paginated(
        api_client.list_member_committee_seats(
            chair["id"], delegate, params={"limit": 50, "offset": 0}
        )
    )
    assert [row["committee_id"] for row in own_seats] == [committee_id]
    assert own_meta["total_count"] == 1

    committee = read_committee(committee_id)
    assert committee["seat_count"] == 3
    assert committee["roster_state"] == "QUORATE"


def test_reusing_the_proposers_user_id_under_the_trustee_role_is_refused():
    """Roles are not identities, so the user-id comparison still runs.

    PRD 2.10: "A PAC contribution may not be board-approved by the operator who proposed it:
    board approval compares the caller's `X-User-ID` against the contribution's
    `proposed_by_user_id` and rejects identically."
    PRD 2.10: "Note that the second case is also protected structurally, since proposing is
    a `GovAffairsDirector` capability and approving is a `BoardTrustee` capability — the
    identity comparison is still performed, because an operator may hold more than one role."

    Design: Corner/RBAC/board_approval_by_the_proposing_user_id_forbidden
    """
    fund = open_fund(min_reserve_cents=0)
    candidate = register_candidate(voting_alignment_pct=90.00, committee_relevance_score=80)
    contribution = propose_contribution(
        fund["id"], candidate["id"], headers=DUAL_HAT_DIRECTOR, amount_cents=100_000
    )
    assert contribution["proposed_by_user_id"] == DUAL_HAT_USER_ID
    assert contribution["max_allowed_cents"] == 250_000

    validate_error(
        api_client.board_approve_contribution(contribution["id"], DUAL_HAT_TRUSTEE),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    stored = read_contribution(contribution["id"])
    assert stored["status"] == "PENDING_BOARD"
    assert stored["proposed_by_user_id"] == DUAL_HAT_USER_ID
    assert stored["board_approved_by_user_id"] is None

    validate_error(
        api_client.board_approve_contribution(contribution["id"], TRUSTEE),
        "ERR_INSUFFICIENT_FUND_BALANCE",
        422,
    )
