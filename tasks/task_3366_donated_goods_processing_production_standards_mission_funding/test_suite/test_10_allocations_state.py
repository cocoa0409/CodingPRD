"""Funding allocations: pipeline state rules, segregation, affordability,
funding-window re-checks, and OCC on creation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_allocation,
    create_allocation,
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
    set_clock,
    setup_pending_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _get_program(org_id, program_id) -> dict:
    rows, _meta = validate_paginated(
        api_client.list_mission_programs(org_id, ADMIN))
    match = [r for r in rows if r["id"] == program_id]
    assert match, f"program {program_id} not found"
    return match[0]


class TestAllocationStateMachine:
    def test_allocation_second_approve_returns_invalid_state(self, api):
        """PRD 3.7: "A successful approval moves the allocation to `APPROVED`,
        records the approver in `approved_by_user_id`, adds the amount to
        `reserved_cents`, and advances the org's `version`."
        PRD 2.10: "State-machine preconditions for the requested transition:
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/allocation_second_approve_returns_invalid_state
        """
        org, _site, _std, _prog, alloc = setup_pending_allocation(
            "Org DA", amount_cents=500, sales=1)
        approved = approve_allocation(alloc["id"])
        assert approved["status"] == "APPROVED"
        resp = api_client.approve_allocation(
            alloc["id"], make_member_cfo_headers("cfo-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_org(org["id"])["reserved_cents"] == 500, "no double reserve"

    def test_disburse_pending_allocation_returns_invalid_state(self, api):
        """PRD 3.7: "Disbursement, again a `MemberCFO` act requiring the
        allocation `APPROVED` and the organization `ACTIVE`, settles the
        commitment with three linked movements: the amount leaves
        `reserved_cents`, the same amount leaves `retail_margin_pool_cents`,
        and the same amount is added to the program's
        `funding_disbursed_cents`."
        PRD 3.7: "The program's `funding_disbursed_cents` starts at zero and
        accumulates as allocations pay out."

        Design: Corner/state_machines/disburse_pending_allocation_returns_invalid_state
        """
        org, _site, _std, prog, alloc = setup_pending_allocation(
            "Org DP", amount_cents=500, sales=0)
        resp = api_client.disburse_allocation(
            alloc["id"], make_member_cfo_headers("cfo-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        org_after = get_org(org["id"])
        assert org_after["retail_margin_pool_cents"] == 0
        assert org_after["reserved_cents"] == 0
        assert _get_program(org["id"], prog["id"])["funding_disbursed_cents"] == 0

    def test_cancel_disbursed_allocation_returns_invalid_state(self, api):
        """PRD 3.7: "An allocation in any other state cannot be cancelled
        (`ERR_INVALID_STATE`)."
        PRD 3.7: "Disbursement, again a `MemberCFO` act requiring the
        allocation `APPROVED` and the organization `ACTIVE`, settles the
        commitment with three linked movements: the amount leaves
        `reserved_cents`, the same amount leaves `retail_margin_pool_cents`,
        and the same amount is added to the program's
        `funding_disbursed_cents`."

        Design: Corner/state_machines/cancel_disbursed_allocation_returns_invalid_state
        """
        org, _site, _std, prog, alloc = setup_pending_allocation(
            "Org CD", amount_cents=500, sales=1)
        approve_allocation(alloc["id"])
        disbursed = disburse_allocation(alloc["id"])
        assert disbursed["status"] == "DISBURSED"
        resp = api_client.cancel_allocation(
            alloc["id"], make_member_cfo_headers("cfo-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        org_after = get_org(org["id"])
        assert org_after["retail_margin_pool_cents"] == 470
        assert org_after["reserved_cents"] == 0
        assert _get_program(org["id"], prog["id"])["funding_disbursed_cents"] == 500


class TestAllocationGates:
    def test_allocation_creator_cannot_approve(self, api):
        """PRD 3.7: "Approval belongs exclusively to a `MemberCFO`, and the
        duties are segregated: the approver's `X-User-ID` must differ from the
        allocation's `created_by_user_id`, or the attempt fails with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/allocation_creator_cannot_approve
        """
        org, _site, _std, _prog, alloc = setup_pending_allocation(
            "Org SoD", amount_cents=500, sales=0, creator_id="pd-1")
        # A MemberCFO presenting the creator's X-User-ID.
        resp = api_client.approve_allocation(
            alloc["id"], make_member_cfo_headers("pd-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_allocation(alloc["id"])["status"] == "PENDING"
        assert get_org(org["id"])["reserved_cents"] == 0

    def test_program_director_cannot_approve_allocation(self, api):
        """PRD 3.7: "Approval belongs exclusively to a `MemberCFO`, and the
        duties are segregated: the approver's `X-User-ID` must differ from the
        allocation's `created_by_user_id`, or the attempt fails with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD 2.1: "A request whose role is not permitted for the target endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/program_director_cannot_approve_allocation
        """
        _org, _site, _std, _prog, alloc = setup_pending_allocation(
            "Org RBAC", amount_cents=500, sales=0, creator_id="pd-1")
        resp = api_client.approve_allocation(
            alloc["id"], make_program_director_headers("pd-9"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_allocation(alloc["id"])["status"] == "PENDING"

    def test_approve_beyond_available_margin_rejected(self, api):
        """PRD 3.7: "Approval re-checks the program window
        (`ERR_PROGRAM_WINDOW_CLOSED` again if the clock has moved outside it)
        and applies the affordability test — the `amount_cents` must not exceed
        the pool minus what is already reserved, that is
        `retail_margin_pool_cents` minus `reserved_cents`; a failing allocation
        is rejected with `ERR_INSUFFICIENT_MARGIN` (HTTP 402)."

        Design: Corner/validations/approve_beyond_available_margin_rejected
        """
        org, _site, _std, _prog, alloc = setup_pending_allocation(
            "Org IM", amount_cents=2000, sales=1)
        assert org["retail_margin_pool_cents"] == 970
        resp = api_client.approve_allocation(
            alloc["id"], make_member_cfo_headers("cfo-1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MARGIN)
        assert get_allocation(alloc["id"])["status"] == "PENDING"
        org_after = get_org(org["id"])
        assert org_after["reserved_cents"] == 0
        assert org_after["retail_margin_pool_cents"] == 970

    def test_approve_after_program_window_closed_rejected(self, api):
        """PRD 3.7: "Approval re-checks the program window
        (`ERR_PROGRAM_WINDOW_CLOSED` again if the clock has moved outside it)
        and applies the affordability test — the `amount_cents` must not exceed
        the pool minus what is already reserved, that is
        `retail_margin_pool_cents` minus `reserved_cents`; a failing allocation
        is rejected with `ERR_INSUFFICIENT_MARGIN` (HTTP 402)."

        Design: Corner/validations/approve_after_program_window_closed_rejected
        """
        set_clock("2026-03-01T00:00:00Z")
        org = create_org("Org Win")
        prog = create_program(org["id"], name="Prog Win",
                              program_type="PLACEMENT",
                              start_date="2026-01-01T00:00:00Z",
                              end_date="2026-06-30T00:00:00Z")
        alloc = create_allocation(org["id"], prog["id"], 100)
        set_clock("2026-09-01T00:00:00Z")  # past the funding window
        resp = api_client.approve_allocation(
            alloc["id"], make_member_cfo_headers("cfo-1"))
        validate_error(resp, ApiErrorId.ERR_PROGRAM_WINDOW_CLOSED)
        assert get_allocation(alloc["id"])["status"] == "PENDING"
        assert get_org(org["id"])["reserved_cents"] == 0

    def test_stale_org_version_rejected_on_allocation_create(self, api):
        """PRD 2.11: "If the supplied value does not match the member
        organization's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on an
        organization state it has not observed."
        PRD 2.11: "Both creations legitimately advance the organization's
        `version` themselves — creating a standard supersedes the prior active
        standard for the same category, and creating an allocation draws
        against the margin-pool view encoded in that version — so a replayed
        request carrying the previously observed version is correctly
        recognized as stale."

        Design: Corner/validations/stale_org_version_rejected_on_allocation_create
        """
        org = create_org("Org OCC2")
        prog = create_program(org["id"], name="Prog OCC", program_type="SUPPORT")
        observed_v = org["version"]
        first = validate_success(api_client.create_funding_allocation(
            create_funding_allocation_payload(prog["id"], 100, observed_v),
            make_program_director_headers("pd-1")), 201)
        assert current_org_version(org["id"]) == observed_v + 1
        replay = api_client.create_funding_allocation(
            create_funding_allocation_payload(prog["id"], 200, observed_v),
            make_program_director_headers("pd-1"))
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
        rows = list_allocations({"mission_program_id": prog["id"]})
        assert len(rows) == 1
        assert rows[0]["id"] == first["id"]
