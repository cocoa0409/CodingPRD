"""Approval step gating, segregation of duties, and delegation windows."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, build_user_headers,
    create_open_requisition, create_candidate_recruited, create_standard_peers,
    create_peer_snapshots, create_draft_offer, create_submitted_offer,
    create_policy, setup_exception_policy_rows, approve_chain,
)

HM = TEST_USERS["hm_headers"]
HM2 = TEST_USERS["hm2_headers"]
REC = TEST_USERS["recruiter_headers"]
CA = TEST_USERS["comp_analyst_headers"]
DIR = TEST_USERS["director_headers"]
ADMIN = TEST_USERS["hr_admin_headers"]


def _exception_offer_with_step0_approved(api):
    """EXCEPTION offer submitted; 4-step chain; step 0 APPROVED by HM."""
    setup_exception_policy_rows(ADMIN)
    req = create_open_requisition(HM, title="Staff Eng", annual_budget_cents=80000000)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand SG")
    offer, steps = create_submitted_offer(req, cand, REC, base_cents=24000000)
    assert len(steps) == 4
    get_success_data(api.decide_approval_step(steps[0]["id"], {"decision": "APPROVED"}, HM))
    return req, offer, steps


def test_step_sequential_gating_blocks_waiting_step(api):
    """PRD §3.5: "A step becomes `ACTIONABLE` when every step with a smaller
    `sequence` is `APPROVED`, so the chain ratchets forward one decision at a
    time." and "Deciding a step that is not `ACTIONABLE` fails with
    `ERR_STEP_NOT_ACTIONABLE`."

    Design: Corner/state_machines/step_sequential_gating
    """
    setup_exception_policy_rows(ADMIN)
    req = create_open_requisition(HM, title="Staff Eng", annual_budget_cents=80000000)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand SG")
    offer, steps = create_submitted_offer(req, cand, REC, base_cents=24000000)
    s0, s1 = steps[0], steps[1]
    # step 1 is WAITING while step 0 is ACTIONABLE
    resp = api.decide_approval_step(s1["id"], {"decision": "APPROVED"}, CA)
    validate_error(resp, ApiErrorId.ERR_STEP_NOT_ACTIONABLE)
    # after step 0 approves, step 1 becomes decidable
    validate_success(api.decide_approval_step(s0["id"], {"decision": "APPROVED"}, HM))
    decided = validate_success(api.decide_approval_step(s1["id"], {"decision": "APPROVED"}, CA))
    assert decided["status"] == "APPROVED"


def test_step_sequential_gating_rejection_path(api):
    """PRD §3.5: "Deciding a step that is not `ACTIONABLE` fails with
    `ERR_STEP_NOT_ACTIONABLE`." — a REJECTED decision against a WAITING step is
    equally blocked; the gate is on step status, not on the decision value.

    Design: Corner/state_machines/step_sequential_gating
    """
    setup_exception_policy_rows(ADMIN)
    req = create_open_requisition(HM, title="Staff Eng", annual_budget_cents=80000000)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand SG2")
    offer, steps = create_submitted_offer(req, cand, REC, base_cents=24000000)
    resp = api.decide_approval_step(steps[1]["id"], {"decision": "REJECTED"}, CA)
    validate_error(resp, ApiErrorId.ERR_STEP_NOT_ACTIONABLE)
    after = validate_success(api.get_offer(offer["id"], REC))
    assert after["status"] == "PENDING_APPROVAL"


def test_self_approval_forbidden(api):
    """PRD §3.5: "Segregation of duties is absolute: the offer's creator may
    never decide any step of its chain, and an attempt is rejected with
    `ERR_SELF_APPROVAL_FORBIDDEN`."

    Design: Corner/validations/self_approval_forbidden
    """
    req = create_open_requisition(HM)
    create_peer_snapshots("L5", "T1", [17000000, 18000000, 19000000])
    cand = create_candidate_recruited(REC, full_name="Cand SA")
    # offer created BY hm-1 (HiringManager is an offer-creating role)
    offer, steps = create_submitted_offer(req, cand, HM, base_cents=18000000)
    step0 = steps[0]
    resp = api.decide_approval_step(step0["id"], {"decision": "APPROVED"}, HM)
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
    step_after = [s for s in validate_success(api.list_approval_steps(offer["id"], REC))
                  if s["id"] == step0["id"]][0]
    assert step_after["status"] == "ACTIONABLE"
    # a different HiringManager (not the creator) succeeds
    decided = validate_success(api.decide_approval_step(step0["id"], {"decision": "APPROVED"}, HM2))
    assert decided["status"] == "APPROVED"
    offer_after = validate_success(api.get_offer(offer["id"], REC))
    assert offer_after["status"] == "APPROVED"


def _delegation_setup(api):
    """ABOVE_BAND offer submitted; HM step approved; CompAnalyst step ACTIONABLE."""
    create_policy("ABOVE_BAND", "CompAnalyst", 1, ADMIN)
    req = create_open_requisition(HM, annual_budget_cents=80000000)
    create_peer_snapshots("L5", "T1", [19000000, 20000000, 21500000])
    cand = create_candidate_recruited(REC, full_name="Cand DG")
    offer, steps = create_submitted_offer(req, cand, REC, base_cents=22000000)
    step0, step1 = steps[0], steps[1]
    get_success_data(api.decide_approval_step(step0["id"], {"decision": "APPROVED"}, HM))
    mk_grant = lambda delegate, vf, vu: get_success_data(api.create_delegation_grant(
        {"grantor_user_id": "ca-1", "delegate_user_id": delegate, "scope_role": "CompAnalyst",
         "valid_from": vf, "valid_until": vu}, ADMIN))
    g1 = mk_grant("d-1", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")  # not yet valid
    g2 = mk_grant("d-2", "2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z")  # past valid_until
    g3 = mk_grant("d-3", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")  # will be revoked
    get_success_data(api.revoke_delegation_grant(g3["id"], ADMIN))
    g4 = mk_grant("d-4", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")  # currently valid
    return offer, step1, (g1, g2, g3, g4)


def test_delegation_window_variants_block_decide(api):
    """PRD §3.5: "A delegated decision is honored only while the grant is
    `ACTIVE` with the delegate's `X-User-ID`, the `scope_role` equal to the
    step's `required_role`, and the clock inside the window; otherwise the
    attempt is rejected with `ERR_DELEGATION_NOT_ACTIVE`."

    Design: Corner/validations/delegation_window_variants_block_decide
    """
    offer, step1, (g1, g2, g3, g4) = _delegation_setup(api)
    # not-yet-valid grant
    e1 = api.decide_approval_step(step1["id"], {"decision": "APPROVED"}, build_user_headers("d-1", "DepartmentDirector"))
    validate_error(e1, ApiErrorId.ERR_DELEGATION_NOT_ACTIVE)
    # past-valid_until grant
    e2 = api.decide_approval_step(step1["id"], {"decision": "APPROVED"}, build_user_headers("d-2", "DepartmentDirector"))
    validate_error(e2, ApiErrorId.ERR_DELEGATION_NOT_ACTIVE)
    # revoked grant
    e3 = api.decide_approval_step(step1["id"], {"decision": "APPROVED"}, build_user_headers("d-3", "DepartmentDirector"))
    validate_error(e3, ApiErrorId.ERR_DELEGATION_NOT_ACTIVE)


def test_delegation_lazy_expiry_and_valid_delegate_success(api):
    """PRD §3.5: "a grant consulted at decision time once the clock has reached
    its `valid_until` is lazily marked `EXPIRED`" and "Every decision stamps
    `decided_by_user_id`, sets `decided_via_delegation` and
    `delegation_grant_id` when a grant was used".

    Design: Corner/validations/delegation_window_variants_block_decide
    """
    offer, step1, (g1, g2, g3, g4) = _delegation_setup(api)
    # consult the past-window grant -> lazily marked EXPIRED
    e2 = api.decide_approval_step(step1["id"], {"decision": "APPROVED"}, build_user_headers("d-2", "DepartmentDirector"))
    validate_error(e2, ApiErrorId.ERR_DELEGATION_NOT_ACTIVE)
    g2_after = validate_success(api.get_delegation_grant(g2["id"], ADMIN))
    assert g2_after["status"] == "EXPIRED"
    # currently-valid grant decides successfully
    decided = validate_success(
        api.decide_approval_step(step1["id"], {"decision": "APPROVED"}, build_user_headers("d-4", "DepartmentDirector"))
    )
    assert decided["status"] == "APPROVED"
    assert decided["decided_via_delegation"] is True
    assert decided["delegation_grant_id"] == g4["id"]
    offer_after = validate_success(api.get_offer(offer["id"], REC))
    assert offer_after["status"] == "APPROVED"


def test_grant_self_delegation_rejected(api):
    """PRD §3.5: "A grant whose grantor equals its delegate, or whose
    `valid_until` does not fall after `valid_from`, is rejected with
    `ERR_GRANT_SELF_DELEGATION`."

    Design: Corner/validations/grant_self_delegation_rejected
    """
    resp = api.create_delegation_grant(
        {"grantor_user_id": "vp-1", "delegate_user_id": "vp-1", "scope_role": "VPPeople",
         "valid_from": "2026-08-01T00:00:00Z", "valid_until": "2026-09-01T00:00:00Z"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_SELF_DELEGATION)


def test_grant_half_open_overlap(api):
    """PRD §3.5: "Two grants for the same delegate and scope role may not
    overlap in time — though adjacency, one grant's `valid_from` landing exactly
    on another's `valid_until`, is allowed — and an overlapping creation is
    rejected with `ERR_GRANT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/delegation_grant_half_open_overlap
    """
    grant_a = get_success_data(api.create_delegation_grant(
        {"grantor_user_id": "vp-1", "delegate_user_id": "dir-9", "scope_role": "VPPeople",
         "valid_from": "2026-08-01T00:00:00Z", "valid_until": "2026-09-01T00:00:00Z"}, ADMIN))
    # interior overlap -> rejected
    resp = api.create_delegation_grant(
        {"grantor_user_id": "vp-1", "delegate_user_id": "dir-9", "scope_role": "VPPeople",
         "valid_from": "2026-08-15T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_GRANT_OVERLAP)
    # exact adjacency (valid_from == prior valid_until) -> allowed
    grant_c = validate_success(api.create_delegation_grant(
        {"grantor_user_id": "vp-1", "delegate_user_id": "dir-9", "scope_role": "VPPeople",
         "valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, ADMIN), expected_status=201)
    assert grant_c["status"] == "ACTIVE"


def test_grant_overlap_partitioned_by_scope_role(api):
    """PRD §3.5: "Two grants for the same delegate and scope role may not
    overlap in time" — the partition key includes the scope role, so the same
    window under a different scope_role is allowed.

    Design: Difficulty/resource_temporal_overlap/delegation_grant_half_open_overlap
    """
    get_success_data(api.create_delegation_grant(
        {"grantor_user_id": "vp-1", "delegate_user_id": "dir-9", "scope_role": "VPPeople",
         "valid_from": "2026-08-01T00:00:00Z", "valid_until": "2026-09-01T00:00:00Z"}, ADMIN))
    grant_d = validate_success(api.create_delegation_grant(
        {"grantor_user_id": "dir-1", "delegate_user_id": "dir-9", "scope_role": "DepartmentDirector",
         "valid_from": "2026-08-15T00:00:00Z", "valid_until": "2026-10-01T00:00:00Z"}, ADMIN), expected_status=201)
    assert grant_d["status"] == "ACTIVE"
