"""Production-run list filters (PRD §2.3)."""
from test_helpers import (
    validate_success, validate_paginated, setup_run_env, create_run,
    manager, scheduler, api_client,
)


class TestRunListing:
    def test_production_runs_list_filters_by_status(self, api):
        """PRD §2.3: "the production-run list accepts `line_id`,
        `agreement_id`, `format_id`, and `status`".

        Design: Corner/endpoints/production_runs_list_filters_by_status
        """
        env = setup_run_env()
        agr, line, fmt = (env["agreement"]["id"], env["line"]["id"],
                          env["format"]["id"])
        r1 = create_run(agr, line, fmt, scheduled_qty=50000,
                        window_start="2026-09-10T08:00:00Z",
                        window_end="2026-09-10T16:00:00Z")
        r2 = create_run(agr, line, fmt, scheduled_qty=60000,
                        window_start="2026-09-11T08:00:00Z",
                        window_end="2026-09-11T16:00:00Z")
        validate_success(api.cancel_run(r2["id"], scheduler()))
        cancelled, _ = validate_paginated(api.list_runs(
            manager(), params={"agreement_id": agr, "status": "CANCELLED"}))
        assert [r["id"] for r in cancelled] == [r2["id"]]
        scheduled, _ = validate_paginated(api.list_runs(
            manager(), params={"agreement_id": agr, "status": "SCHEDULED"}))
        assert [r["id"] for r in scheduled] == [r1["id"]]
        all_runs, meta = validate_paginated(
            api.list_runs(manager(), params={"agreement_id": agr}))
        assert len(all_runs) == 2 and meta["total_count"] == 2
        multi_fk, _ = validate_paginated(api.list_runs(
            manager(), params={"line_id": line, "format_id": fmt}))
        assert len(multi_fk) == 2
