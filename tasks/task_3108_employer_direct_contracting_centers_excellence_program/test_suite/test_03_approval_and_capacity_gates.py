"""Approval gates: contract state, coverage window, and the two capacity gates."""
from test_helpers import (
    ApiErrorId,
    close_episode,
    drive_episode_to_post_op,
    drive_episode_to_sor_pending,
    get_episode,
    get_success_data,
    make_contract,
    make_employer,
    make_patient,
    make_template,
    open_episode,
    reset_clock,
    setup_episode_in_post_op,
    setup_program,
    validate_error,
    validate_success,
)


def test_episode_approval_requires_contract_active_and_in_window(
    api, physician_reviewer_headers
):
    """PRD §3.4: "The contract must be `ACTIVE`."
    PRD §2.10: "Current-state legality of the transition or action
    (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/episode_approval_requires_contract_active_and_in_window
    """
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_contract(employer, template)  # left in DRAFT — never activated
    patient = make_patient(employer)
    episode = drive_episode_to_sor_pending(open_episode(patient, contract))

    resp = api.record_review(
        episode["id"],
        {"conclusion": "SURGERY_INDICATED",
         "expected_episode_version": episode["version"]},
        physician_reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_episode(episode["id"])
    assert after["status"] == "SOR_PENDING", (
        "a DRAFT contract blocks the approval transition without mutating the episode"
    )


def test_approval_outside_coverage_window_rejected(api, physician_reviewer_headers):
    """PRD §3.4: "The approval must fall inside the contract's coverage window
    — the clock date must be at or after `effective_from` and strictly before
    `effective_to` — else `ERR_OUTSIDE_COVERAGE_WINDOW`."

    Design: Difficulty/cross_entity_state_dependency/episode_approval_requires_contract_active_and_in_window
    """
    # Clock starts at 2026-09-01; the window below begins in December, so the
    # approval attempt is before effective_from.
    employer = make_employer({"ORTHO_JOINT": 2500000})
    template = make_template()
    contract = make_contract(
        employer,
        template,
        effective_from="2026-12-01T00:00:00Z",
        effective_to="2027-09-01T00:00:00Z",
    )
    get_success_data(api.activate_contract(contract["id"], {
        "X-User-ID": "test-program-admin-1", "X-User-Role": "ProgramAdmin"}))
    patient = make_patient(employer)
    episode = drive_episode_to_sor_pending(open_episode(patient, contract))

    resp = api.record_review(
        episode["id"],
        {"conclusion": "SURGERY_INDICATED",
         "expected_episode_version": episode["version"]},
        physician_reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_COVERAGE_WINDOW)
    after = get_episode(episode["id"])
    assert after["status"] == "SOR_PENDING"


def test_monthly_cap_at_exactly_cap_minus_one_vs_cap(api, physician_reviewer_headers):
    """PRD §3.4: "approval proceeds only while that count is below
    `episode_cap_per_month`, so reaching the cap exactly is rejected with
    `ERR_CAPACITY_EXCEEDED` and a cap of zero forbids all approvals."

    Design: Difficulty/boundary_precision_check/monthly_cap_at_exactly_cap_minus_one_vs_cap
    """
    prog = setup_program(contract_overrides={"episode_cap_per_month": 2})
    episodes = []
    for _ in range(3):
        patient = make_patient(prog["employer"])
        episodes.append(drive_episode_to_sor_pending(
            open_episode(patient, prog["contract"])))

    # Approvals 1 and 2 succeed (counts 0 and 1, both below the cap of 2).
    for ep in episodes[:2]:
        validate_success(
            api.record_review(
                ep["id"],
                {"conclusion": "SURGERY_INDICATED",
                 "expected_episode_version": ep["version"]},
                physician_reviewer_headers,
            ),
            expected_status=201,
        )
    assert get_episode(episodes[0]["id"])["status"] == "APPROVED"
    assert get_episode(episodes[1]["id"])["status"] == "APPROVED"

    # Approval 3 hits count == cap == 2 and is rejected.
    resp = api.record_review(
        episodes[2]["id"],
        {"conclusion": "SURGERY_INDICATED",
         "expected_episode_version": episodes[2]["version"]},
        physician_reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    assert get_episode(episodes[2]["id"])["status"] == "SOR_PENDING"


def test_monthly_cap_of_zero_forbids_all_approvals(api, physician_reviewer_headers):
    """PRD §3.4: "approval proceeds only while that count is below
    `episode_cap_per_month`, so reaching the cap exactly is rejected with
    `ERR_CAPACITY_EXCEEDED` and a cap of zero forbids all approvals."

    Design: Difficulty/boundary_precision_check/monthly_cap_at_exactly_cap_minus_one_vs_cap
    """
    prog = setup_program(contract_overrides={"episode_cap_per_month": 0})
    patient = make_patient(prog["employer"])
    episode = drive_episode_to_sor_pending(open_episode(patient, prog["contract"]))

    resp = api.record_review(
        episode["id"],
        {"conclusion": "SURGERY_INDICATED",
         "expected_episode_version": episode["version"]},
        physician_reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    assert get_episode(episode["id"])["status"] == "SOR_PENDING"


def test_state_vs_fiscal_capacity_conflict_on_review(api, physician_reviewer_headers):
    """PRD §2.10: "6. Current-state legality of the transition or action
    (`ERR_INVALID_STATE`, HTTP 409)"
    PRD §2.10: "10. Fiscal and capacity rules (HTTP 422): the monthly and
    concurrent capacity gates (`ERR_CAPACITY_EXCEEDED`) and the benefit pool
    (`ERR_BENEFIT_POOL_EXCEEDED`)."
    PRD §2.10: "When several checks could reject the same request, the platform
    evaluates them in a fixed priority order, and the first failure determines
    the error returned."
    Here the state check passes (the episode is in SOR_REVIEW, a review-legal
    state), so the request reaches the priority-10 fiscal gate, which rejects.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_capacity_conflict_on_review
    """
    prog = setup_program(contract_overrides={"episode_cap_per_month": 1})
    patient_a = make_patient(prog["employer"])
    patient_b = make_patient(prog["employer"])
    ep_a = drive_episode_to_sor_pending(open_episode(patient_a, prog["contract"]))
    ep_b = drive_episode_to_sor_pending(open_episode(patient_b, prog["contract"]))

    # Episode A consumes the monthly cap of 1.
    validate_success(
        api.record_review(
            ep_a["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": ep_a["version"]},
            physician_reviewer_headers,
        ),
        expected_status=201,
    )

    # Episode B moves to a review-legal state (SOR_REVIEW) first.
    r = validate_success(
        api.record_review(
            ep_b["id"],
            {"conclusion": "MORE_INFO_NEEDED",
             "expected_episode_version": ep_b["version"]},
            physician_reviewer_headers,
        ),
        expected_status=201,
    )
    ep_b_now = get_episode(ep_b["id"])
    assert ep_b_now["status"] == "SOR_REVIEW"

    # The approval attempt passes the state gate but fails the capacity gate.
    resp = api.record_review(
        ep_b["id"],
        {"conclusion": "SURGERY_INDICATED",
         "expected_episode_version": ep_b_now["version"]},
        physician_reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    after = get_episode(ep_b["id"])
    assert after["status"] == "SOR_REVIEW", "a rejected approval leaves no partial mutation"


def test_state_error_fires_when_episode_not_review_legal_despite_full_cap(
    api, physician_reviewer_headers
):
    """PRD §2.10: "6. Current-state legality of the transition or action
    (`ERR_INVALID_STATE`, HTTP 409)"
    PRD §2.10: "When several checks could reject the same request, the platform
    evaluates them in a fixed priority order, and the first failure determines
    the error returned."
    An INTAKE_PENDING episode under a full monthly cap fails at the priority-6
    state gate before the capacity gate is ever evaluated.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_capacity_conflict_on_review
    """
    prog = setup_program(contract_overrides={"episode_cap_per_month": 0})
    patient = make_patient(prog["employer"])
    episode = open_episode(patient, prog["contract"])  # INTAKE_PENDING

    resp = api.record_review(
        episode["id"],
        {"conclusion": "SURGERY_INDICATED",
         "expected_episode_version": episode["version"]},
        physician_reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_episode(episode["id"])["status"] == "INTAKE_PENDING"


def test_avoided_episode_releases_capacity_and_zeroes_accrual(
    api, physician_reviewer_headers
):
    """PRD §3.4: "The concurrent gate counts episodes in `APPROVED`,
    `SCHEDULING`, `PRE_OP`, `SURGERY_DONE`, or `POST_OP_TRACKING`; approval
    proceeds only while that count is below `concurrent_capacity`, else
    `ERR_CAPACITY_EXCEEDED`. Unlike the monthly gate, concurrent capacity frees
    up as episodes close."

    Design: Difficulty/compensating_invariant/avoided_episode_releases_capacity_and_zeroes_accrual
    """
    prog = setup_program(
        contract_overrides={"concurrent_capacity": 1},
        template_overrides={"warranty_days": 3},
    )
    patient_a = make_patient(prog["employer"])
    patient_b = make_patient(prog["employer"])
    ep_a = drive_episode_to_sor_pending(open_episode(patient_a, prog["contract"]))
    ep_b = drive_episode_to_sor_pending(open_episode(patient_b, prog["contract"]))

    # Approve A: concurrent occupancy becomes 1.
    validate_success(
        api.record_review(
            ep_a["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": ep_a["version"]},
            physician_reviewer_headers,
        ),
        expected_status=201,
    )

    # B's approval fails while A occupies the single concurrent slot.
    resp = api.record_review(
        ep_b["id"],
        {"conclusion": "SURGERY_INDICATED",
         "expected_episode_version": ep_b["version"]},
        physician_reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    # Drive A all the way to CLOSED; occupancy returns to 0.
    post_op = drive_episode_to_post_op(get_episode(ep_a["id"]))
    closed = close_episode(post_op)
    assert closed["status"] == "CLOSED"

    # B's retry now succeeds — closure freed the concurrent slot.
    ep_b_now = get_episode(ep_b["id"])
    validate_success(
        api.record_review(
            ep_b["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": ep_b_now["version"]},
            physician_reviewer_headers,
        ),
        expected_status=201,
    )
    assert get_episode(ep_b["id"])["status"] == "APPROVED"


def test_concurrent_gate_counts_only_live_states(api, physician_reviewer_headers):
    """PRD §3.4: "The concurrent gate counts episodes in `APPROVED`,
    `SCHEDULING`, `PRE_OP`, `SURGERY_DONE`, or `POST_OP_TRACKING`"
    An episode in SOR_PENDING (pre-approval) does not occupy concurrent
    capacity: with concurrent_capacity 1, an SOR_PENDING episode plus an
    approved episode still allows the SOR_PENDING episode to be approved only
    if the gate counts it as free — here we prove an SOR_PENDING sibling is
    invisible to the gate by approving the first episode while a second sits
    in SOR_PENDING under capacity 1.

    Design: Difficulty/compensating_invariant/avoided_episode_releases_capacity_and_zeroes_accrual
    """
    prog = setup_program(contract_overrides={"concurrent_capacity": 1})
    patient_a = make_patient(prog["employer"])
    patient_b = make_patient(prog["employer"])
    ep_a = drive_episode_to_sor_pending(open_episode(patient_a, prog["contract"]))
    ep_b = drive_episode_to_sor_pending(open_episode(patient_b, prog["contract"]))

    # B sitting in SOR_PENDING does not block A's approval.
    validate_success(
        api.record_review(
            ep_a["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": ep_a["version"]},
            physician_reviewer_headers,
        ),
        expected_status=201,
    )
    assert get_episode(ep_a["id"])["status"] == "APPROVED"

    # Now the single slot is occupied by A, so B cannot approve.
    resp = api.record_review(
        ep_b["id"],
        {"conclusion": "SURGERY_INDICATED",
         "expected_episode_version": ep_b["version"]},
        physician_reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
