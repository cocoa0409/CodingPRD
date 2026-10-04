"""Difficulty queue — transitive_cascade: the record-repayment ->
audit-close -> authorization-deobligation -> apportionment-recompute chain
(depth 3), and project-nomination -> STIP-reopen -> authorization-blocked
(depth 2) (PRD §3.9, §3.3)."""
from test_helpers import (
    TEST_USERS,
    add_stip_comment,
    api_client,
    clear_project,
    create_apportionment,
    create_audit,
    create_funding_program,
    create_line_item,
    create_project,
    create_stip,
    decide_stip,
    determine_project_eligible,
    finalize_audit,
    get_success_data,
    issue_audit_findings,
    record_repayment,
    set_clock,
    setup_project_complete,
    submit_stip,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestTransitiveCascade:
    def test_record_repayment_cascades_through_authorization_to_apportionment(self, api):
        """PRD §3.9: "Each recording adds to `repaid_cents`, and the recording
        that brings `repaid_cents` to exactly `repayment_due_cents` moves the
        Audit from `FINAL` to the terminal `CLOSED` status."
        PRD §3.9: "the deobligation is `obligated_cents` minus that net;
        `obligated_cents` is set to the net (satisfying the §2.10 net-share
        invariant), `closed_at` is stamped from the logical clock, and the
        Authorization moves from `OBLIGATED` or `FULLY_DRAWN` to `CLOSED`.
        Second, the drawn apportionment cell's `obligated_cents` is reduced by
        the deobligation and `available_cents` is recomputed. Third, the
        Project moves from `COMPLETE` to the terminal `CLOSED_OUT` status,
        closing the program lifecycle that began with its nomination."

        Repaying the exact 80,000 due (reimbursed 800,000 - final eligible
        720,000) closes the audit, deobligates 280,000 (= 1,000,000 -
        720,000 net) on the authorization, and drops the cell to 720,000
        obligated / 1,280,000 available.

        Design: Difficulty/transitive_cascade/record_repayment_cascades_through_authorization_to_apportionment
        """
        ctx = setup_project_complete(
            project_cost_cents=1_500_000,
            apportioned_cents=2_000_000,
            initial_obligated_cents=1_000_000,
            agreement_number="FA-X-001",
            final_voucher_kwargs={
                "line_items": [create_line_item("all work", 1_000_000)],
                "period_start_date": "2027-01-01T00:00:00Z",
                "period_end_date": "2027-04-01T00:00:00Z",
            },
        )
        auth_id = ctx["authorization"]["id"]
        apportionment_id = ctx["authorization"]["apportionment_id"]
        assert ctx["project"]["status"] == "COMPLETE"

        audit = create_audit(ctx["project"]["id"])
        issue_audit_findings(audit["id"], "Ineligible stripping work", 100_000)
        set_clock("2026-12-07T00:00:00Z")
        finalized = finalize_audit(audit["id"])
        assert finalized["status"] == "FINAL"
        assert finalized["final_eligible_federal_share_cents"] == 720_000
        assert finalized["repayment_due_cents"] == 80_000

        closed = record_repayment(audit["id"], 80_000)
        assert closed["status"] == "CLOSED", (
            "repayment of exactly repayment_due_cents must close the audit, "
            f"got {closed['status']}"
        )

        authorization = get_success_data(api.get_authorization(auth_id, H["fhwa_reviewer"]))
        assert authorization["status"] == "CLOSED"
        assert authorization["obligated_cents"] == 720_000, (
            "deobligation 280,000 posts because the audit closed: obligated "
            f"1,000,000 -> 720,000, got {authorization['obligated_cents']}"
        )
        assert authorization["reimbursed_cents"] == 800_000
        assert authorization["repaid_cents"] == 80_000

        apportionment = get_success_data(
            api.get_apportionment(apportionment_id, H["fhwa_reviewer"])
        )
        assert apportionment["obligated_cents"] == 720_000
        assert apportionment["available_cents"] == 1_280_000

        project = get_success_data(api.get_project(ctx["project"]["id"], H["fhwa_reviewer"]))
        assert project["status"] == "CLOSED_OUT"

    def test_project_creation_into_approved_stip_cascades_reopening(self, api):
        """PRD §3.3: "Nomination is accepted regardless of STIP status;
        however, when the target STIP is `APPROVED`, the nomination cascades
        the amendment reopening of §3.2 — the STIP returns to
        `PUBLIC_INVOLVEMENT` with a fresh comment window and an incremented
        `amendment_count`."
        PRD §3.2: "While the STIP sits in `PUBLIC_INVOLVEMENT`, eligibility
        determination and authorization on its projects fail with
        `ERR_STIP_NOT_APPROVED` until the loop closes again."

        Creating project P2 into the APPROVED STIP lands NOMINATED (link 1)
        and itself reopens the STIP (link 2) — which then blocks authorization
        of the pre-existing, fully cleared, ELIGIBLE project P1.

        Design: Difficulty/transitive_cascade/project_creation_into_approved_stip_cascades_reopening
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        create_apportionment(
            program["id"], state_code="CA", federal_fiscal_year=2027,
            apportioned_cents=5_000_000,
        )
        stip = create_stip(state_code="CA", land_pct=0.0, start_ffy=2027)
        add_stip_comment(stip["id"])
        project_p1 = create_project(
            stip["id"], program["id"], route_name="I-5", description="P1",
            activity_code="ROAD_RESURFACING", is_interstate_system=False,
            dbe_goal_pct=0.10, total_estimated_cost_cents=1_000_000,
        )
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])
        decide_stip(stip["id"], "APPROVE")
        determine_project_eligible(project_p1["id"])
        clear_project(project_p1["id"])

        created = api.create_project(
            {
                "stip_id": stip["id"],
                "funding_program_id": program["id"],
                "route_name": "SR-99",
                "description": "P2 amendment project",
                "activity_code": "ROAD_RESURFACING",
                "is_interstate_system": False,
                "dbe_goal_pct": 0.10,
                "total_estimated_cost_cents": 500_000,
            },
            H["state_dot_planner"],
        )
        project_p2 = validate_success(created, expected_status=201)
        assert project_p2["status"] == "NOMINATED"

        stip_after = get_success_data(api.get_stip(stip["id"], H["state_dot_planner"]))
        assert stip_after["status"] == "PUBLIC_INVOLVEMENT", (
            "the nomination itself must cascade the APPROVED STIP back to "
            f"PUBLIC_INVOLVEMENT, got {stip_after['status']}"
        )
        assert stip_after["amendment_count"] == 1

        set_clock("2026-10-15T00:00:00Z")
        resp = api.create_authorization(
            {
                "project_id": project_p1["id"],
                "agreement_number": "FA-BLOCKED",
                "initial_obligated_cents": 100_000,
            },
            H["fhwa_division_admin"],
        )
        validate_error(resp, ApiErrorId.ERR_STIP_NOT_APPROVED)
