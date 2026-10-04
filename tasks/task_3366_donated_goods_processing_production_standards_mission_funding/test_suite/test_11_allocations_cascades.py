"""Mission-funding cascades and validation-priority conflicts (Difficulty):
disbursement crossing margin health, and the fixed evaluation order of §2.10."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_allocation,
    cancel_allocation,
    create_funding_allocation_payload,
    create_org,
    create_program,
    current_org_version,
    disburse_allocation,
    get_allocation,
    get_org,
    list_allocations,
    make_member_cfo_headers,
    make_program_director_headers,
    setup_pending_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _get_program(org_id, program_id) -> dict:
    rows, _meta = validate_paginated(
        api_client.list_mission_programs(org_id, ADMIN))
    return [r for r in rows if r["id"] == program_id][0]


def _setup_disbursed_1500():
    """Org (reserve floor 1000) with pool 1940 from two grade-A sales and an
    APPROVED allocation of 1500, then disbursed. Returns (org, prog, alloc)."""
    org, _site, _std, prog, alloc = setup_pending_allocation(
        "Org Margin", amount_cents=1500, reserve_floor_cents=1000, sales=2)
    assert org["retail_margin_pool_cents"] == 1940
    approve_allocation(alloc["id"])
    disburse_allocation(alloc["id"])
    return get_org(org["id"]), prog, alloc


class TestDisburseMarginHealthGate:
    def test_disburse_debits_pool_and_crosses_margin_health(self, api):
        """PRD 3.7: "Disbursement, again a `MemberCFO` act requiring the
        allocation `APPROVED` and the organization `ACTIVE`, settles the
        commitment with three linked movements: the amount leaves
        `reserved_cents`, the same amount leaves `retail_margin_pool_cents`,
        and the same amount is added to the program's
        `funding_disbursed_cents`."
        PRD 3.7: "The pool debit itself recomputes `margin_health`, and if the
        debit pulls the pool below the reserve floor the organization crosses
        to `LOW` — which immediately gates any further allocation creation
        with `ERR_MARGIN_RESERVE_BREACH`."

        Design: Difficulty/transitive_cascade/allocation_disburse_margin_health_gate
        """
        org, prog, alloc = _setup_disbursed_1500()
        assert org["retail_margin_pool_cents"] == 440, "1940 - 1500"
        assert org["reserved_cents"] == 0
        assert org["margin_health"] == "LOW", "440 < reserve floor 1000"
        assert _get_program(org["id"], prog["id"])["funding_disbursed_cents"] == 1500
        assert get_allocation(alloc["id"])["status"] == "DISBURSED"

    def test_low_margin_health_gates_next_allocation_create(self, api):
        """PRD 3.7: "Creation is gated twice more: the logical clock must fall
        within the program's funding window, both dates inclusive, or the
        request fails with `ERR_PROGRAM_WINDOW_CLOSED`; and the organization's
        `margin_health` must be `HEALTHY`, because a pool already at `LOW` may
        not take on new commitments — the refusal there is
        `ERR_MARGIN_RESERVE_BREACH`."

        Design: Difficulty/transitive_cascade/allocation_disburse_margin_health_gate
        """
        org, prog, _alloc = _setup_disbursed_1500()
        resp = api_client.create_funding_allocation(
            create_funding_allocation_payload(
                prog["id"], 100, current_org_version(org["id"])),
            make_program_director_headers("pd-1"))
        validate_error(resp, ApiErrorId.ERR_MARGIN_RESERVE_BREACH)


class TestDisburseStateBeatsFiscal:
    def _setup_cancelled_big_allocation(self):
        """PENDING allocation of 999999 on a zero-pool org, cancelled while
        PENDING; approving it violates both the state rule and affordability."""
        org, _site, _std, _prog, alloc = setup_pending_allocation(
            "Org Prio1", amount_cents=999999, sales=0)
        cancelled = cancel_allocation(
            alloc["id"], make_program_director_headers("pd-1"))
        assert cancelled["status"] == "CANCELLED"
        return org, alloc

    def test_approve_cancelled_allocation_reports_invalid_state(self, api):
        """PRD 2.10: "When several checks could reject the same request, the
        server evaluates them in a fixed order, and a request failing an
        earlier check is rejected with that check's error even if a later check
        would also have failed:"
        PRD 2.10: "8. State-machine preconditions for the requested transition:
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD 2.10: "15. Fiscal checks — approval affordability
        (`ERR_INSUFFICIENT_MARGIN`, HTTP 402) and the margin-reserve gate on
        allocation creation (`ERR_MARGIN_RESERVE_BREACH`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/disburse_state_beats_fiscal
        """
        _org, alloc = self._setup_cancelled_big_allocation()
        resp = api_client.approve_allocation(
            alloc["id"], make_member_cfo_headers("cfo-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_allocation(alloc["id"])["status"] == "CANCELLED"

    def test_rejected_approve_leaves_ledgers_untouched(self, api):
        """PRD 2.10: "When several checks could reject the same request, the
        server evaluates them in a fixed order, and a request failing an
        earlier check is rejected with that check's error even if a later check
        would also have failed:"
        PRD 3.7: "A successful approval moves the allocation to `APPROVED`,
        records the approver in `approved_by_user_id`, adds the amount to
        `reserved_cents`, and advances the org's `version`."

        Design: Difficulty/priority_pair_validation_conflict/disburse_state_beats_fiscal
        """
        org, alloc = self._setup_cancelled_big_allocation()
        resp = api_client.approve_allocation(
            alloc["id"], make_member_cfo_headers("cfo-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        org_after = get_org(org["id"])
        assert org_after["reserved_cents"] == 0
        assert org_after["retail_margin_pool_cents"] == 0
        assert get_allocation(alloc["id"]).get("approved_by_user_id") is None


class TestAllocationWindowBeatsMargin:
    def _setup_closed_window_low_margin_org(self):
        """Org with reserve floor 1000 driven to margin_health LOW by a real
        disbursement (pool 440 < floor 1000 per PRD 2.8/3.7 — PRD 3.1 starts
        every new org HEALTHY regardless of floor), plus a second program
        whose funding window already closed at the default clock."""
        org, _site, _std, _prog_open, alloc = setup_pending_allocation(
            "Org Prio2", amount_cents=1500, reserve_floor_cents=1000, sales=2)
        approve_allocation(alloc["id"])
        disburse_allocation(alloc["id"])
        org = get_org(org["id"])
        assert org["retail_margin_pool_cents"] == 440, "1940 - 1500"
        assert org["margin_health"] == "LOW", "440 < reserve floor 1000"
        prog = create_program(org["id"], name="Training",
                              start_date="2026-01-01T00:00:00Z",
                              end_date="2026-06-30T00:00:00Z")
        return org, prog

    def test_create_outside_window_reports_window_error(self, api):
        """PRD 2.10: "When several checks could reject the same request, the
        server evaluates them in a fixed order, and a request failing an
        earlier check is rejected with that check's error even if a later check
        would also have failed:"
        PRD 2.10: "13. Temporal windows — territory overlap
        (`ERR_TERRITORY_WINDOW_OVERLAP`), contract overlap
        (`ERR_CONTRACT_WINDOW_OVERLAP`), and the program funding window
        (`ERR_PROGRAM_WINDOW_CLOSED`), all HTTP 409."
        PRD 2.10: "15. Fiscal checks — approval affordability
        (`ERR_INSUFFICIENT_MARGIN`, HTTP 402) and the margin-reserve gate on
        allocation creation (`ERR_MARGIN_RESERVE_BREACH`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/allocation_window_beats_margin
        """
        org, prog = self._setup_closed_window_low_margin_org()
        resp = api_client.create_funding_allocation(
            create_funding_allocation_payload(
                prog["id"], 100, current_org_version(org["id"])),
            make_program_director_headers("pd-1"))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_WINDOW_CLOSED)

    def test_rejected_create_persists_no_allocation(self, api):
        """PRD 3.7: "Creation is gated twice more: the logical clock must fall
        within the program's funding window, both dates inclusive, or the
        request fails with `ERR_PROGRAM_WINDOW_CLOSED`; and the organization's
        `margin_health` must be `HEALTHY`, because a pool already at `LOW` may
        not take on new commitments — the refusal there is
        `ERR_MARGIN_RESERVE_BREACH`."
        PRD 3.7: "A created allocation is `PENDING`, records the requester's
        header value in `created_by_user_id`, and advances the org's `version`
        by one."

        Design: Difficulty/priority_pair_validation_conflict/allocation_window_beats_margin
        """
        org, prog = self._setup_closed_window_low_margin_org()
        resp = api_client.create_funding_allocation(
            create_funding_allocation_payload(
                prog["id"], 100, current_org_version(org["id"])),
            make_program_director_headers("pd-1"))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_WINDOW_CLOSED)
        assert list_allocations({"mission_program_id": prog["id"]}) == []


class TestApproveThenCancelConservesMargin:
    def test_approve_reserves_without_touching_pool(self, api):
        """PRD 3.7: "A successful approval moves the allocation to `APPROVED`,
        records the approver in `approved_by_user_id`, adds the amount to
        `reserved_cents`, and advances the org's `version`."
        PRD 2.8: "The `reserved_cents` field tracks the sum of allocation
        amounts that have been approved but not yet disbursed or cancelled, so
        the spendable margin at any moment is the pool minus the reservation."

        Design: Difficulty/compensating_invariant/approve_then_cancel_conserves_available_margin
        """
        org, _site, _std, _prog, alloc = setup_pending_allocation(
            "Org Inv", amount_cents=500, sales=1)
        assert org["retail_margin_pool_cents"] == 970
        approved = approve_allocation(alloc["id"])
        assert approved["status"] == "APPROVED"
        org_after = get_org(org["id"])
        assert org_after["reserved_cents"] == 500
        assert org_after["retail_margin_pool_cents"] == 970, (
            "approval reserves; the pool itself is untouched")

    def test_cancel_of_approved_releases_exact_reservation(self, api):
        """PRD 3.7: "From `APPROVED`, a `MemberCFO` cancels; the amount is
        subtracted back out of `reserved_cents`, restoring the available
        margin, and the org's `version` advances by one."
        PRD 3.7: "From `PENDING`, a `ProgramDirector` cancels; nothing was ever
        reserved, so no financial field changes."

        Design: Difficulty/compensating_invariant/approve_then_cancel_conserves_available_margin
        """
        org, _site, _std, _prog, alloc = setup_pending_allocation(
            "Org Inv2", amount_cents=500, sales=1)
        approve_allocation(alloc["id"])
        cancelled = cancel_allocation(
            alloc["id"], make_member_cfo_headers("cfo-1"))
        assert cancelled["status"] == "CANCELLED"
        org_after = get_org(org["id"])
        assert org_after["reserved_cents"] == 0
        assert org_after["retail_margin_pool_cents"] == 970, (
            "available margin identical to pre-approve")
