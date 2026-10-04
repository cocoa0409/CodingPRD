"""Cross-entity cascades: product deactivation and cutover rollback."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_project, create_product, create_gl, create_account, map_account,
    setup_plan_scheduled, setup_project_with_passed_run,
)

PM = TEST_USERS["pm_headers"]
CE = TEST_USERS["ce_headers"]


class TestProductDeactivateCascade:
    def test_deactivate_flips_mapped_account_and_recomputes_gl(self, api):
        """PRD §3.2: "Deactivation (`ACTIVE → DRAFT`), likewise restricted to
        those two phases, carries an important cascade: every account governed
        by that product which is currently `MAPPED` flips to `EXCEPTION` with
        the exception note \"product deactivated\"."
        PRD §3.3: "`expected_balance_cents`, the sum of
        `opening_principal_cents` across its accounts in `MAPPED`, `EXCEPTION`,
        `CLEARED`, or `CONVERTED` status"

        Design: Difficulty/transitive_cascade/product_deactivate_cascades_account_then_gl_variance
        """
        project = create_project()
        pt = create_product(project["id"], product_code="DDA-STD", rate=0.03)
        gl = create_gl(project["id"])
        acct = create_account(
            project["id"], pt["id"], legacy_account_number="L-6001",
            opening_principal_cents=1000000,
        )
        mapped = map_account(acct["id"], gl["id"], project["id"])
        assert mapped["status"] == "MAPPED"
        pre = get_success_data(api.get_gl_account(gl["id"], CE))
        assert pre["expected_balance_cents"] == 1000000
        get_success_data(api.deactivate_product_type(pt["id"], CE))
        post_acct = get_success_data(api.get_account(acct["id"], CE))
        assert post_acct["status"] == "EXCEPTION"
        assert post_acct["exception_note"] == "product deactivated"
        post = get_success_data(api.get_gl_account(gl["id"], CE))
        # EXCEPTION accounts remain in the expected-balance input set.
        assert post["expected_balance_cents"] == 1000000
        assert post["variance_cents"] == pre["variance_cents"]

    def test_deactivate_note_and_gl_input_set_preserved(self, api):
        """PRD §3.2: "every account governed by that product which is currently
        `MAPPED` flips to `EXCEPTION` with the exception note \"product
        deactivated\"."
        PRD §3.3: "`expected_balance_cents`, the sum of
        `opening_principal_cents` across its accounts in `MAPPED`, `EXCEPTION`,
        `CLEARED`, or `CONVERTED` status"

        Design: Difficulty/transitive_cascade/product_deactivate_cascades_account_then_gl_variance
        """
        project = create_project()
        pt = create_product(project["id"], product_code="CHK-1", rate=0.0)
        gl = create_gl(project["id"])
        a1 = create_account(project["id"], pt["id"], legacy_account_number="D-1",
                            opening_principal_cents=250000)
        a2 = create_account(project["id"], pt["id"], legacy_account_number="D-2",
                            opening_principal_cents=250000)
        map_account(a1["id"], gl["id"], project["id"])
        map_account(a2["id"], gl["id"], project["id"])
        get_success_data(api.deactivate_product_type(pt["id"], CE))
        for aid in (a1["id"], a2["id"]):
            row = get_success_data(api.get_account(aid, CE))
            assert row["status"] == "EXCEPTION"
            assert row["exception_note"] == "product deactivated"
        gl_row = get_success_data(api.get_gl_account(gl["id"], CE))
        assert gl_row["expected_balance_cents"] == 500000


class TestRollbackCascade:
    def test_rollback_cascade_end_to_end(self, api):
        """PRD §3.6: "Rollback (`SCHEDULED → ROLLED_BACK` or `GO →
        ROLLED_BACK`) is the escape hatch and cascades broadly: every `PENDING`
        or `RUNNING` task becomes `SKIPPED` while `COMPLETE` tasks keep their
        status; every account in `MAPPED`, `CLEARED`, or `EXCEPTION` becomes
        `BLOCKED` with `frozen_flag` left true; the project returns to
        `MOCK_CONVERSION` with `cutover_scheduled_date` cleared to null; and
        the baseline run's `is_cutover_baseline` returns to false, freeing a
        future passed run to serve as the new baseline."

        Design: Corner/cross_cutting_layers/rollback_cascade_end_to_end
        """
        ctx = setup_plan_scheduled(
            tasks=[
                {"task_name": "extract", "sequence": 1,
                 "conversion_window_start": "2026-09-19T19:00:00Z",
                 "conversion_window_end": "2026-09-19T21:00:00Z",
                 "owner_role": "CONVERSION_ENGINEER"},
                {"task_name": "load", "sequence": 2,
                 "conversion_window_start": "2026-09-19T21:00:00Z",
                 "conversion_window_end": "2026-09-19T23:00:00Z",
                 "owner_role": "OPERATIONS_LEAD"},
            ],
        )
        pid = ctx["project"]["id"]
        plan = ctx["plan"]
        acct_id = ctx["account"]["id"]
        rolled = get_success_data(api.rollback_plan(plan["id"], PM))
        assert rolled["status"] == "ROLLED_BACK"
        rows, _meta = validate_paginated(
            api.list_tasks(PM, params={"plan_id": plan["id"]})
        )
        assert sorted(r["status"] for r in rows) == ["SKIPPED", "SKIPPED"]
        acct = get_success_data(api.get_account(acct_id, PM))
        assert acct["status"] == "BLOCKED"
        assert acct["frozen_flag"] is True
        run = get_success_data(api.get_mock_run(ctx["run"]["id"], PM))
        assert run["is_cutover_baseline"] is False
        proj = get_success_data(api.get_project(pid, PM))
        assert proj["status"] == "MOCK_CONVERSION"
        assert proj["cutover_scheduled_date"] is None
