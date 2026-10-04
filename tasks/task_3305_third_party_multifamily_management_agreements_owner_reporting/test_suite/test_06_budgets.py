"""Budgets: posture gate, SoD, reforecast cycle, OCC on the base (PRD §3.4, §2.8)."""
from test_helpers import (
    ApiErrorId,
    create_budget_payload,
    get_success_data,
    make_acct_headers,
    make_owner_rep_headers,
    setup_managed_property,
    setup_owner,
    setup_property,
    start_onboarding,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["pm_headers"]
ACCT = TEST_USERS["acct_headers"]


class TestBudgetPostureGate:
    def test_budget_submit_requires_managed_property_posture(self, api, acct_headers):
        """PRD §3.4: "From `DRAFT`, a `PropertyAccountant` submits the budget,
        which requires the property's `management_posture` to be `MANAGED`
        (otherwise `ERR_INVALID_STATE_TRANSITION`)".

        Design: Difficulty/cross_entity_state_dependency/budget_submit_requires_managed_property_posture
        """
        owner = setup_owner(legal_name="Cross Two LP")
        prop = setup_property(owner, name="Cross Two Property", unit_count=45)
        start_onboarding(prop, takeover_date="2026-09-15T00:00:00Z")  # posture ONBOARDING
        b = get_success_data(
            api.create_budget(
                {
                    "property_id": prop["id"],
                    "fiscal_year": 2027,
                    "kind": "ANNUAL",
                    "operating_revenue_cents": 5000000,
                    "operating_expense_cents": 3000000,
                    "capex_total_cents": 200000,
                },
                acct_headers,
            )
        )
        resp = api.submit_budget(b["id"], acct_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_budget(b["id"], acct_headers))
        assert after["status"] == "DRAFT"

    def test_budget_submit_succeeds_once_property_managed(self, api, acct_headers):
        """PRD §3.4: "From `DRAFT`, a `PropertyAccountant` submits the budget,
        which requires the property's `management_posture` to be `MANAGED`
        (otherwise `ERR_INVALID_STATE_TRANSITION`) and, for a reforecast, that
        `supersedes_budget_id` reference an `APPROVED` budget for the same
        property and fiscal year".

        Design: Difficulty/cross_entity_state_dependency/budget_submit_requires_managed_property_posture
        """
        fx = setup_managed_property(legal_name="Cross Two B LP",
                                    property_name="Cross Two B Property", unit_count=45)
        b = get_success_data(
            api.create_budget(
                create_budget_payload(property_id=fx["prop"]["id"], fiscal_year=2027),
                acct_headers,
            )
        )
        submitted = validate_success(api.submit_budget(b["id"], acct_headers))
        assert submitted["status"] == "SUBMITTED"


class TestSegregationOfDuties:
    def test_sod_violation_when_submitter_approves_own_budget(self, api, acct_headers):
        """PRD §3.4: "Both decisions enforce segregation of duties: the
        deciding `OwnerRep` must not be the same user who submitted the
        budget, and a violation is rejected with `ERR_SOD_VIOLATION`."

        Design: Corner/validations/sod_violation_when_submitter_approves_own_budget
        """
        fx = setup_managed_property(legal_name="SoD Owner LP",
                                    property_name="SoD Property", unit_count=20)
        owner, prop = fx["owner"], fx["prop"]
        submitter = make_acct_headers("acct-sod-1")
        b = get_success_data(
            api.create_budget(
                create_budget_payload(property_id=prop["id"], fiscal_year=2027),
                submitter,
            )
        )
        get_success_data(api.submit_budget(b["id"], submitter))

        # Same user id attempting the decision is rejected.
        same_user_as_owner = make_owner_rep_headers("acct-sod-1")
        resp = api.approve_budget(b["id"], same_user_as_owner)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        # The genuine owner (distinct user id) approves cleanly.
        approved = validate_success(
            api.approve_budget(b["id"], make_owner_rep_headers(owner["id"]))
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_by"] == owner["id"]
        assert approved["decided_by"] != "acct-sod-1"


class TestReforecastCycle:
    def test_budget_reforecast_cycle_replaces_approved_base(self, api, acct_headers):
        """PRD §3.4: "Approval moves the budget to `APPROVED`, increments its
        `version`, and records the deciding user in `decided_by`; when the
        approved budget is a reforecast, the base budget named in
        `supersedes_budget_id` flips to `SUPERSEDED` in the same request."

        Design: Difficulty/non_linear_state_machine/budget_reforecast_cycle_replaces_approved_base
        """
        fx = setup_managed_property(legal_name="Cycle Owner LP",
                                    property_name="Cycle Property", unit_count=80)
        owner, prop = fx["owner"], fx["prop"]
        hdrs = make_owner_rep_headers(owner["id"])

        base = get_success_data(
            api.create_budget(
                {
                    "property_id": prop["id"], "fiscal_year": 2026, "kind": "ANNUAL",
                    "operating_revenue_cents": 9000000,
                    "operating_expense_cents": 5000000, "capex_total_cents": 500000,
                },
                acct_headers,
            )
        )
        get_success_data(api.submit_budget(base["id"], acct_headers))
        base = get_success_data(api.approve_budget(base["id"], hdrs))
        assert base["status"] == "APPROVED"

        rf = get_success_data(
            api.create_budget(
                {
                    "property_id": prop["id"], "fiscal_year": 2026, "kind": "REFORECAST",
                    "operating_revenue_cents": 9500000,
                    "operating_expense_cents": 5200000, "capex_total_cents": 700000,
                    "supersedes_budget_id": base["id"],
                    "expected_base_budget_version": base["version"],
                },
                acct_headers,
            )
        )
        get_success_data(api.submit_budget(rf["id"], acct_headers))
        rf = get_success_data(api.approve_budget(rf["id"], hdrs))
        assert rf["status"] == "APPROVED"

        base_after = validate_success(api.get_budget(base["id"], acct_headers))
        assert base_after["status"] == "SUPERSEDED", (
            f"base must flip to SUPERSEDED in the same approve request, got {base_after['status']}"
        )

    def test_reforecast_second_cycle_supersedes_first_reforecast(self, api, acct_headers):
        """PRD §3.4: "A reforecast is a create-with-supersede: its
        `supersedes_budget_id` must reference an `APPROVED` budget for the
        same property and fiscal year, and its create must carry
        `expected_base_budget_version` matching that base budget's current
        `version`, per the OCC rule in §2.8."

        Design: Difficulty/non_linear_state_machine/budget_reforecast_cycle_replaces_approved_base
        """
        fx = setup_managed_property(legal_name="Cycle2 Owner LP",
                                    property_name="Cycle2 Property", unit_count=80)
        owner, prop = fx["owner"], fx["prop"]
        hdrs = make_owner_rep_headers(owner["id"])

        def approve_annual(fy, rev, exp, cap):
            b = get_success_data(
                api.create_budget(
                    {"property_id": prop["id"], "fiscal_year": fy, "kind": "ANNUAL",
                     "operating_revenue_cents": rev, "operating_expense_cents": exp,
                     "capex_total_cents": cap},
                    acct_headers,
                )
            )
            get_success_data(api.submit_budget(b["id"], acct_headers))
            return get_success_data(api.approve_budget(b["id"], hdrs))

        def approve_reforecast(base, rev, exp, cap):
            r = get_success_data(
                api.create_budget(
                    {"property_id": prop["id"], "fiscal_year": base["fiscal_year"],
                     "kind": "REFORECAST", "operating_revenue_cents": rev,
                     "operating_expense_cents": exp, "capex_total_cents": cap,
                     "supersedes_budget_id": base["id"],
                     "expected_base_budget_version": base["version"]},
                    acct_headers,
                )
            )
            get_success_data(api.submit_budget(r["id"], acct_headers))
            return get_success_data(api.approve_budget(r["id"], hdrs))

        base = approve_annual(2026, 9000000, 5000000, 500000)
        rf1 = approve_reforecast(base, 9500000, 5200000, 700000)
        # A second reforecast may legitimately supersede the first (now APPROVED).
        rf2 = approve_reforecast(rf1, 9700000, 5300000, 750000)
        assert rf2["status"] == "APPROVED"

        rf1_after = validate_success(api.get_budget(rf1["id"], acct_headers))
        assert rf1_after["status"] == "SUPERSEDED"


class TestReforecastOcc:
    def test_occ_stale_base_version_on_reforecast_create(self, api, acct_headers):
        """PRD §2.8: "Creating a reforecast budget requires
        `expected_base_budget_version`, carrying the `version` of the APPROVED
        base `Budget` the client last read and named in
        `supersedes_budget_id`. A stale value means the base was amended or
        already superseded by another reforecast, and the create is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/occ_stale_base_version_on_reforecast_create
        """
        fx = setup_managed_property(legal_name="OCR Owner LP",
                                    property_name="OCR Property", unit_count=10)
        owner, prop = fx["owner"], fx["prop"]
        base = get_success_data(
            api.create_budget(
                create_budget_payload(property_id=prop["id"], fiscal_year=2027),
                acct_headers,
            )
        )
        get_success_data(api.submit_budget(base["id"], acct_headers))
        base = get_success_data(
            api.approve_budget(base["id"], make_owner_rep_headers(owner["id"]))
        )
        base_v = base["version"]

        stale = api.create_budget(
            {
                "property_id": prop["id"], "fiscal_year": 2027, "kind": "REFORECAST",
                "operating_revenue_cents": 3200000, "operating_expense_cents": 2100000,
                "capex_total_cents": 120000, "supersedes_budget_id": base["id"],
                "expected_base_budget_version": base_v - 1,
            },
            acct_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(
            api.create_budget(
                {
                    "property_id": prop["id"], "fiscal_year": 2027, "kind": "REFORECAST",
                    "operating_revenue_cents": 3200000, "operating_expense_cents": 2100000,
                    "capex_total_cents": 120000, "supersedes_budget_id": base["id"],
                    "expected_base_budget_version": base_v,
                },
                acct_headers,
            ),
            expected_status=201,
        )
        assert fresh["status"] == "DRAFT"


class TestBudgetApprovalChainRoles:
    def test_ownerrep_approval_chain_role_order_enforced(self, api, acct_headers):
        """PRD §3.4: "Submission is the accountant's act and approval is the
        owner's, and the two must never be the same hand."; PRD §2.1: "An
        attempt to perform an operation outside the caller's role is rejected
        with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/ownerrep_approval_chain_role_order_enforced
        """
        fx = setup_managed_property(legal_name="A2 Owner LP",
                                    property_name="A2 Property", unit_count=20)
        owner, prop = fx["owner"], fx["prop"]
        hdrs = make_owner_rep_headers(owner["id"])
        b = get_success_data(
            api.create_budget(
                create_budget_payload(property_id=prop["id"], fiscal_year=2027),
                acct_headers,
            )
        )

        r_submit = api.submit_budget(b["id"], hdrs)
        validate_error(r_submit, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        get_success_data(api.submit_budget(b["id"], acct_headers))
        r_approve = api.approve_budget(b["id"], acct_headers)
        validate_error(r_approve, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        after = validate_success(api.get_budget(b["id"], acct_headers))
        assert after["status"] == "SUBMITTED"


class TestBudgetIdempotency:
    def test_double_submit_of_budget_is_not_idempotent(self, api, acct_headers):
        """PRD §3.4: "From `DRAFT`, a `PropertyAccountant` submits the budget";
        PRD §2.10: "then state-machine legality
        (`ERR_INVALID_STATE_TRANSITION`)" — submit is defined only from DRAFT.

        Design: Corner/state_machines/double_submit_of_budget_is_not_idempotent
        """
        fx = setup_managed_property(legal_name="Idem Owner LP",
                                    property_name="Idem Property", unit_count=25)
        b = get_success_data(
            api.create_budget(
                create_budget_payload(property_id=fx["prop"]["id"], fiscal_year=2027,
                                      operating_revenue_cents=4000000,
                                      operating_expense_cents=2500000),
                acct_headers,
            )
        )
        get_success_data(api.submit_budget(b["id"], acct_headers))

        resp = api.submit_budget(b["id"], acct_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(api.get_budget(b["id"], acct_headers))
        assert after["status"] == "SUBMITTED"
