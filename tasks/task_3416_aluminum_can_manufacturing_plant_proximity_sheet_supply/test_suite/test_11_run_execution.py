"""Run execution guards: invalid transitions and the settlement index gate
(PRD §2.7, §3.5, §3.6)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, publish_index, setup_run_env, setup_scheduled_run,
    setup_completed_run, create_run, start_run, complete_run, get_run,
    scheduler, manager, api_client,
)


class TestInvalidTransitions:
    def test_complete_before_start_returns_invalid_state(self, api):
        """PRD §3.5: "the run moves from `IN_PROGRESS` to `COMPLETED`" — a
        `SCHEDULED` run has no completion edge; §2.7 gate 6 rejects it with
        `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/complete_before_start_returns_invalid_state
        """
        env = setup_scheduled_run()
        resp = api.complete_run(env["run"]["id"],
                                {"produced_qty": 50000, "spoiled_qty": 0},
                                scheduler())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        run = get_run(env["run"]["id"])
        assert run["status"] == "SCHEDULED"
        assert run.get("produced_qty") is None, \
            "produced_qty is set at completion, not before"


class TestSettlementIndexGate:
    def test_settle_without_delivery_month_index_returns_index_not_published(self, api):
        """PRD §3.6: "Settlement requires the published index whose `period`
        equals the run's delivery month — the YYYY-MM of its `window_end` — and
        is rejected with `ERR_INDEX_NOT_PUBLISHED` when that row is missing."

        Design: Corner/validations/settle_without_delivery_month_index_returns_index_not_published
        """
        # Only the prior-month (2026-08) index exists: completion works.
        set_clock()
        publish_index("2026-08", 128.0)
        env = setup_run_env(pass_through_pct=1.0)
        run = create_run(env["agreement"]["id"], env["line"]["id"],
                         env["format"]["id"], scheduled_qty=250000,
                         window_start="2026-09-10T08:00:00Z",
                         window_end="2026-09-10T16:00:00Z")
        start_run(run["id"])
        complete_run(run["id"], 250000, 0)
        resp = api.settle_run(run["id"], manager())
        validate_error(resp, ApiErrorId.ERR_INDEX_NOT_PUBLISHED, 409)
        assert get_run(run["id"])["status"] == "COMPLETED"
        # Publish the delivery-month row: the identical settle now succeeds.
        publish_index("2026-09", 128.0)
        settled = validate_success(api.settle_run(run["id"], manager()))
        assert settled["status"] == "SETTLED"
        # 30.0 lbs x 128.0 x 1.0 + 1500 = 5340.00; x 250000 / 1000.
        assert settled["settled_amount_cents"] == 1335000.00
