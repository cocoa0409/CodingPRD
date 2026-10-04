"""Format retirement blocked by open runs (PRD §3.3, §3.5)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_scheduled_run, api_client, manager, scheduler,
)


class TestFormatRetireGate:
    def test_format_retire_blocked_while_run_scheduled(self, api):
        """PRD §3.3: "Retirement moves a `TOOLED` or `QUALIFIED` format to
        `RETIRED`, but only while no run of that format stands in `SCHEDULED`,
        `IN_PROGRESS`, or `HELD`; otherwise retirement is rejected with
        `ERR_FORMAT_HAS_OPEN_RUNS`."

        Design: Difficulty/cross_entity_state_dependency/format_retire_blocked_while_any_run_open
        """
        env = setup_scheduled_run()
        resp = api.retire_format(env["format"]["id"], manager())
        validate_error(resp, ApiErrorId.ERR_FORMAT_HAS_OPEN_RUNS, 409)
        fmt = validate_success(api.get_format(env["format"]["id"], manager()))
        assert fmt["status"] == "QUALIFIED"

    def test_format_retire_succeeds_after_run_cancelled(self, api):
        """PRD §3.5: "Cancelling moves a `SCHEDULED` or `HELD` run to
        `CANCELLED`"; PRD §3.3: with no run in `SCHEDULED`/`IN_PROGRESS`/`HELD`
        the same retire succeeds and "`RETIRED` is terminal."

        Design: Difficulty/cross_entity_state_dependency/format_retire_blocked_while_any_run_open
        """
        env = setup_scheduled_run()
        cancelled = validate_success(api.cancel_run(env["run"]["id"],
                                                    scheduler()))
        assert cancelled["status"] == "CANCELLED"
        retired = validate_success(api.retire_format(env["format"]["id"],
                                                     manager()))
        assert retired["status"] == "RETIRED"
