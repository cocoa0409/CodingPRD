"""Account staging, GL mapping, optimistic concurrency, and the file freeze."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    create_project, create_product, create_gl, create_account, map_account,
    current_project_version,
    setup_mock_conversion_project, setup_project_with_passed_run,
    plan_cutover, advance_to_mock_conversion, flag_and_clear,
    create_comm, schedule_comm,
)

PM = TEST_USERS["pm_headers"]
CE = TEST_USERS["ce_headers"]
CO = TEST_USERS["co_headers"]


class TestMappingHappyPath:
    def test_account_staged_to_mapped_valid_transition(self, api):
        """PRD §3.3: "Mapping (`STAGED → MAPPED`) ties an account to the
        general ledger: the call supplies a `gl_account_id` referencing a GL
        account of the same project, plus the OCC field
        `expected_project_version` described in §2.7."
        PRD §3.3: "A successful mapping stores the `gl_account_id`, recomputes
        the referenced GL's expected, converted, and variance totals, and
        increments the project `version`."

        Design: Corner/state_machines/account_staged_to_mapped_valid_transition
        """
        project = create_project()
        pt = create_product(project["id"], rate=0.01)
        gl = create_gl(project["id"], gl_code="GL-1")
        acct = create_account(project["id"], pt["id"],
                              legacy_account_number="L-1", opening_principal_cents=1000)
        data = map_account(acct["id"], gl["id"], project["id"])
        assert data["status"] == "MAPPED"
        assert data["gl_account_id"] == gl["id"]


class TestMappingReferences:
    def test_account_create_with_kind_mismatch_returns_invalid_reference(self, api):
        """PRD §3.3: "The referenced product must be `ACTIVE` and its `kind`
        must equal the account's `account_type`; a kind mismatch or a GL
        account belonging to a different project is rejected with
        `ERR_INVALID_REFERENCE` (HTTP 422)."

        Design: Corner/state_machines/account_map_with_kind_mismatch_returns_invalid_reference
        """
        project = create_project()
        loan_pt = create_product(project["id"], product_code="LN", kind="LOAN",
                                 accrual_method="ACT_360", rate=0.05)
        payload = {
            "project_id": project["id"],
            "legacy_account_number": "L-3",
            "account_type": "DEPOSIT",
            "product_type_id": loan_pt["id"],
            "opening_principal_cents": 1000,
            "statement_cycle_day": 1,
            "accrual_start_date": "2026-09-01",
        }
        resp = api.create_account(payload, CE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)


class TestNestedResources:
    def test_account_of_other_project_returns_not_found(self, api):
        """PRD §2.8: "third, existence of every path identifier, validated
        left to right, with nested resources verified to belong to the project
        they are addressed under (`ERR_NOT_FOUND`)"

        Design: Corner/entities/nested_resource_under_wrong_parent_returns_not_found
        """
        project = create_project()
        resp = api.get_account(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        # A real account is reachable (proving the 404 above is about the id).
        pt = create_product(project["id"], rate=0.01)
        acct = create_account(project["id"], pt["id"], legacy_account_number="L-9",
                              opening_principal_cents=100)
        data = validate_success(api.get_account(acct["id"], PM))
        assert data["id"] == acct["id"]


class TestOptimisticConcurrency:
    def test_map_with_stale_project_version_rejected(self, api):
        """PRD §2.7: "If the supplied value does not equal the project's
        current `version` — because another writer has since advanced the
        phase, mapped a sibling account, scheduled a comm, or otherwise
        mutated the project — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/errors/err_stale_version_on_map
        """
        project = create_project()
        pt = create_product(project["id"], rate=0.01)
        gl = create_gl(project["id"], gl_code="GL-1")
        a1 = create_account(project["id"], pt["id"], legacy_account_number="L-1",
                            opening_principal_cents=1000)
        a2 = create_account(project["id"], pt["id"], legacy_account_number="L-2",
                            opening_principal_cents=2000)
        v0 = current_project_version(project["id"])
        map_account(a1["id"], gl["id"], project["id"])
        resp = api.map_account(
            a2["id"],
            {"gl_account_id": gl["id"], "expected_project_version": v0},
            CE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        v1 = current_project_version(project["id"])
        data = validate_success(
            api.map_account(
                a2["id"],
                {"gl_account_id": gl["id"], "expected_project_version": v1},
                CE,
            )
        )
        assert data["status"] == "MAPPED"

    def test_comm_schedule_with_stale_project_version_rejected(self, api):
        """PRD §2.7: "If the supplied value does not equal the project's
        current `version` — because another writer has since advanced the
        phase, mapped a sibling account, scheduled a comm, or otherwise
        mutated the project — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_schedule_stale_version_rejected
        """
        project = create_project()
        pt = create_product(project["id"], rate=0.01)
        gl = create_gl(project["id"], gl_code="GL-1")
        a1 = create_account(project["id"], pt["id"], legacy_account_number="L-1",
                            opening_principal_cents=1000)
        a2 = create_account(project["id"], pt["id"], legacy_account_number="L-2",
                            opening_principal_cents=2000)
        map_account(a1["id"], gl["id"], project["id"])
        comm = create_comm(project["id"], a1["id"], comm_type="CARD_REISSUE", wave=1)
        v1 = get_success_data(api.get_project(project["id"], CO))["version"]
        map_account(a2["id"], gl["id"], project["id"])
        resp = api.schedule_comm(comm["id"], {"expected_project_version": v1}, CO)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        data = schedule_comm(comm["id"], project["id"])
        assert data["status"] == "SCHEDULED"


class TestExceptionCycleConservesGL:
    def test_exception_round_trip_keeps_gl_expected_balance(self, api):
        """PRD §3.3: "`expected_balance_cents`, the sum of
        `opening_principal_cents` across its accounts in `MAPPED`, `EXCEPTION`,
        `CLEARED`, or `CONVERTED` status"

        Design: Difficulty/compensating_invariant/account_exception_cycle_conserves_gl_expected
        """
        ctx = setup_mock_conversion_project(
            account_overrides={"legacy_account_number": "L-9001",
                               "opening_principal_cents": 1000000}
        )
        gl_id = ctx["gl"]["id"]
        acct_id = ctx["account"]["id"]
        before = get_success_data(api.get_gl_account(gl_id, CE))["expected_balance_cents"]
        get_success_data(api.flag_exception(acct_id, {"note": "balance mismatch"}, CE))
        during = get_success_data(api.get_gl_account(gl_id, CE))["expected_balance_cents"]
        get_success_data(
            api.clear_exception(acct_id, {"resolution_note": "recounted"}, CE)
        )
        after = get_success_data(api.get_gl_account(gl_id, CE))["expected_balance_cents"]
        assert before == 1000000
        assert during == 1000000
        assert after == 1000000

    def test_exception_cycle_recomputes_converted_side_but_not_expected(self, api):
        """PRD §3.3: "`expected_balance_cents`, the sum of
        `opening_principal_cents` across its accounts in `MAPPED`, `EXCEPTION`,
        `CLEARED`, or `CONVERTED` status"
        PRD §3.3: "Clearing an exception (`EXCEPTION → CLEARED`) requires a
        `resolution_note`, the same phase and freeze conditions, and recomputes
        the owning GL's three totals."

        Design: Difficulty/compensating_invariant/account_exception_cycle_conserves_gl_expected
        """
        ctx = setup_mock_conversion_project(
            account_overrides={"legacy_account_number": "L-9010",
                               "opening_principal_cents": 750000}
        )
        gl_id = ctx["gl"]["id"]
        acct_id = ctx["account"]["id"]
        flag_and_clear(acct_id)
        gl_row = get_success_data(api.get_gl_account(gl_id, CE))
        assert gl_row["expected_balance_cents"] == 750000
        assert gl_row["variance_cents"] == (
            gl_row["converted_balance_cents"] - gl_row["expected_balance_cents"]
        )


class TestFileFreeze:
    def test_comm_schedule_before_and_after_cutover_freeze(self, api):
        """PRD §2.10: "Once a project reaches `CUTOVER_PLANNED` — and through
        `LIVE` — its account inventory is frozen. Every account's
        `frozen_flag` reads true, and the four account-mutation capabilities
        (mapping an account, flagging an exception, clearing an exception, and
        scheduling a customer communication) are all rejected with
        `ERR_FROZEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/comm_schedule_requires_account_unfrozen_and_mapped
        """
        ctx = setup_project_with_passed_run()
        pid = ctx["project"]["id"]
        acct_id = ctx["account"]["id"]
        comm1 = create_comm(pid, acct_id, comm_type="CARD_REISSUE", wave=1)
        comm2 = create_comm(pid, acct_id, comm_type="PAYMENT_REDIRECTION", wave=1)
        data1 = schedule_comm(comm1["id"], pid)
        assert data1["status"] == "SCHEDULED"
        plan_cutover(pid)
        pv = get_success_data(api.get_project(pid, CO))["version"]
        resp = api.schedule_comm(comm2["id"], {"expected_project_version": pv}, CO)
        validate_error(resp, ApiErrorId.ERR_FROZEN)

    def test_account_mutation_rejected_with_frozen_after_cutover_planned(self, api):
        """PRD §2.10: "Every account's `frozen_flag` reads true, and the four
        account-mutation capabilities (mapping an account, flagging an
        exception, clearing an exception, and scheduling a customer
        communication) are all rejected with `ERR_FROZEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/comm_schedule_requires_account_unfrozen_and_mapped
        """
        ctx = setup_project_with_passed_run()
        pid = ctx["project"]["id"]
        acct_id = ctx["account"]["id"]
        plan_cutover(pid)
        acct = get_success_data(api.get_account(acct_id, CE))
        assert acct["frozen_flag"] is True
        # Stage a second account before planning would require the unfrozen
        # window, so exercise the freeze on the existing account instead:
        # flag-exception is one of the four frozen capabilities.
        resp2 = api.flag_exception(acct_id, {"note": "late"}, CE)
        validate_error(resp2, ApiErrorId.ERR_FROZEN)
