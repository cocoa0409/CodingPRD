"""Representation: agent capacity boundary, half-open window overlap, POA
drafting/supersession, OCC on execute, and lazy expiry.
"""
from test_helpers import (
    TEST_USERS,
    assign_agent,
    create_agent,
    create_notice,
    create_poa_payload,
    draft_and_execute_poa,
    get_success_data,
    open_claim,
    scope_claim_in_scope,
    set_clock,
    setup_claim_in_triage,
    validate_error,
    validate_success,
    create_return,
    create_client,
    create_preparer,
    create_office,
    create_product,
    file_return,
)

ADMIN = TEST_USERS["program_admin_headers"]
OM = TEST_USERS["office_manager_headers"]
CM = TEST_USERS["case_manager_headers"]


def _two_scope_confirmed_claims(api):
    """Office + preparer + two clients; two FILED [1040_SIMPLE] returns each
    with a STANDARD product, each with an OPEN notice and a claim scoped
    IN_SCOPE PREPARER_ERROR (SCOPE_CONFIRMED). Returns (claim1, claim2)."""
    office = create_office()
    preparer = create_preparer(office["id"])
    claims = []
    for i, delta in enumerate((1000, 2000)):
        client = create_client()
        ret = file_return(create_return(client["id"], office["id"], preparer["id"],
                                        components=["1040_SIMPLE"])["id"])
        create_product(ret["id"], tier="STANDARD")
        notice = create_notice(ret["id"], tax_delta_cents=delta, penalty_cents=0,
                               issued_at="2026-09-10T00:00:00Z", due_at="2026-10-01T00:00:00Z")
        claim = open_claim(ret["id"], notice["id"])
        scope_claim_in_scope(claim["id"], "PREPARER_ERROR")
        claims.append(claim)
    return claims[0], claims[1]


class TestAgentCapacityBoundary:
    def test_capacity_at_max_rejects_next_assignment(self, api):
        """PRD §3.6: "The agent's parallel capacity must have room: the count
        of claims currently in `REPRESENTING` under that agent must be below
        their `max_parallel`, or the assignment is rejected with
        `ERR_AGENT_CAPACITY` (HTTP 409)."

        With max_parallel 1, the first claim reaches REPRESENTING and the very
        next assignment to the same agent fails; the second claim stays
        SCOPE_CONFIRMED.

        Design: Difficulty/boundary_precision_check/agent_capacity_boundary
        """
        cl1, cl2 = _two_scope_confirmed_claims(api)
        agent = create_agent(max_parallel=1)
        assign_agent(cl1["id"], agent["id"],
                     window_start="2026-09-12T00:00:00Z", window_end="2026-12-12T00:00:00Z")
        _, claim1 = draft_and_execute_poa(cl1["id"], agent["id"])
        assert claim1["status"] == "REPRESENTING"
        res = api.assign_claim(cl2["id"], {"agent_id": agent["id"],
                                           "window_start": "2026-09-12T00:00:00Z",
                                           "window_end": "2026-12-12T00:00:00Z"}, CM)
        validate_error(res, "ERR_AGENT_CAPACITY")
        claim2 = validate_success(api.get_claim(cl2["id"], CM), 200)
        assert claim2["status"] == "SCOPE_CONFIRMED"

    def test_assigned_but_not_representing_does_not_consume_capacity(self, api):
        """PRD §3.6: "The agent's parallel capacity must have room: the count
        of claims currently in `REPRESENTING` under that agent must be below
        their `max_parallel`, or the assignment is rejected with
        `ERR_AGENT_CAPACITY` (HTTP 409)."

        Only REPRESENTING claims count: with max_parallel 1, a merely-ASSIGNED
        claim does not block a second assignment (windows are disjoint so no
        overlap interferes).

        Design: Difficulty/boundary_precision_check/agent_capacity_boundary
        """
        cl1, cl2 = _two_scope_confirmed_claims(api)
        agent = create_agent(max_parallel=1)
        assign_agent(cl1["id"], agent["id"],
                     window_start="2026-09-12T00:00:00Z", window_end="2026-10-12T00:00:00Z")
        # cl1 is ASSIGNED, not REPRESENTING: capacity (1 REPRESENTING) is free.
        asg2 = validate_success(
            api.assign_claim(cl2["id"], {"agent_id": agent["id"],
                                         "window_start": "2026-10-12T00:00:00Z",
                                         "window_end": "2026-11-12T00:00:00Z"}, CM), 201)
        assert asg2["status"] == "ACTIVE"


class TestAssignmentWindowHalfOpenAdjacency:
    def test_touching_windows_do_not_overlap(self, api):
        """PRD §3.6: "And the half-open window — covering the start instant up
        to but not including the end instant — must not overlap any other
        `ACTIVE` assignment window for the same agent; two windows that merely
        touch, one's end equal to the other's start, do not overlap, but any
        true intersection is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409)."

        A window starting exactly at the previous window's end is accepted.

        Design: Difficulty/resource_temporal_overlap/assignment_window_half_open_adjacency
        """
        cl1, cl2 = _two_scope_confirmed_claims(api)
        agent = create_agent(max_parallel=5)
        assign_agent(cl1["id"], agent["id"],
                     window_start="2026-10-01T00:00:00Z", window_end="2026-11-01T00:00:00Z")
        asg2 = validate_success(
            api.assign_claim(cl2["id"], {"agent_id": agent["id"],
                                         "window_start": "2026-11-01T00:00:00Z",
                                         "window_end": "2026-12-01T00:00:00Z"}, CM), 201)
        assert asg2["status"] == "ACTIVE"

    def test_interior_overlap_rejected(self, api):
        """PRD §3.6: "two windows that merely touch, one's end equal to the
        other's start, do not overlap, but any true intersection is rejected
        with `ERR_WINDOW_OVERLAP` (HTTP 409)."

        A window starting inside an existing ACTIVE window for the same agent
        is rejected.

        Design: Difficulty/resource_temporal_overlap/assignment_window_half_open_adjacency
        """
        cl1, cl2 = _two_scope_confirmed_claims(api)
        agent = create_agent(max_parallel=5)
        assign_agent(cl1["id"], agent["id"],
                     window_start="2026-10-01T00:00:00Z", window_end="2026-11-01T00:00:00Z")
        res = api.assign_claim(cl2["id"], {"agent_id": agent["id"],
                                           "window_start": "2026-10-15T00:00:00Z",
                                           "window_end": "2026-11-15T00:00:00Z"}, CM)
        validate_error(res, "ERR_WINDOW_OVERLAP")


class TestOptimisticConcurrencyPoaHappyPath:
    def test_execute_with_fresh_version_succeeds(self, api):
        """PRD §3.6: "Execution stamps `executed_at` with the logical clock,
        moves the POA from `DRAFT` to `EXECUTED`, advances the claim from
        `ASSIGNED` to `REPRESENTING`, and increments both resources'
        versions."
        PRD §2.7: "Before any clock-setting call is made, the logical clock
        reads exactly `2026-09-01T00:00:00Z`".

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_poa_happy_path
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        scope_claim_in_scope(ctx["claim"]["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=3)
        assign_agent(ctx["claim"]["id"], agent["id"])
        poa = get_success_data(api.create_poa(
            ctx["claim"]["id"], create_poa_payload(agent["id"]), CM))
        res = api.execute_poa(ctx["claim"]["id"], {"expected_poa_version": poa["version"]}, CM)
        validate_success(res, 200)
        claim = validate_success(api.get_claim(ctx["claim"]["id"], CM), 200)
        assert claim["status"] == "REPRESENTING"
        poa_after = validate_success(api.get_poa(poa["id"], CM), 200)
        assert poa_after["status"] == "EXECUTED"
        assert poa_after["version"] == poa["version"] + 1
        assert poa_after["executed_at"] is not None


class TestStalePoaVersionOnExecute:
    def test_superseded_draft_revoked_and_stale_execute_rejected(self, api):
        """PRD §3.6: "the new draft supersedes any existing `DRAFT` POA on the
        same claim, which is automatically moved to `REVOKED`."
        PRD §2.6: "A power-of-attorney execution request must carry
        `expected_poa_version`, matching the current `version` of the claim's
        draft POA; a newer draft created for the same claim supersedes the
        prior one, so executing against a stale draft view is likewise
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_poa_version_on_execute
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        scope_claim_in_scope(ctx["claim"]["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=3)
        assign_agent(ctx["claim"]["id"], agent["id"])
        poa1 = get_success_data(api.create_poa(
            ctx["claim"]["id"], create_poa_payload(agent["id"], expires_at="2027-06-01T00:00:00Z"), CM))
        get_success_data(api.create_poa(
            ctx["claim"]["id"], create_poa_payload(agent["id"], expires_at="2027-07-01T00:00:00Z"), CM))
        poa1_after = validate_success(api.get_poa(poa1["id"], CM), 200)
        assert poa1_after["status"] == "REVOKED", "second draft supersedes the first"
        res = api.execute_poa(ctx["claim"]["id"], {"expected_poa_version": poa1["version"]}, CM)
        validate_error(res, "ERR_STALE_VERSION")
        claim = validate_success(api.get_claim(ctx["claim"]["id"], CM), 200)
        assert claim["status"] == "ASSIGNED"


class TestPoaLazyExpiryBlocksExecute:
    def test_expired_draft_cannot_execute(self, api):
        """PRD §3.6: "the draft's `expires_at` must be strictly later than the
        logical clock, or execution fails with `ERR_POA_EXPIRED` (HTTP 422)".

        The clock advanced past the draft's expiry; execution fails and the
        claim stays ASSIGNED.

        Design: Corner/state_machines/poa_lazy_expiry_blocks_execute
        """
        ctx = setup_claim_in_triage(components=["1040_SIMPLE"], product_tier="STANDARD")
        scope_claim_in_scope(ctx["claim"]["id"], "PREPARER_ERROR")
        agent = create_agent(max_parallel=3)
        assign_agent(ctx["claim"]["id"], agent["id"],
                     window_start="2026-09-12T00:00:00Z", window_end="2026-12-12T00:00:00Z")
        poa = get_success_data(api.create_poa(
            ctx["claim"]["id"], create_poa_payload(agent["id"], expires_at="2026-09-20T00:00:00Z"), CM))
        set_clock("2026-09-25T00:00:00Z")
        res = api.execute_poa(ctx["claim"]["id"], {"expected_poa_version": poa["version"]}, CM)
        validate_error(res, "ERR_POA_EXPIRED")
        claim = validate_success(api.get_claim(ctx["claim"]["id"], CM), 200)
        assert claim["status"] == "ASSIGNED"
