"""Run-create body-shape and existence gates (PRD §2.6, §2.7, §3.4)."""
from test_helpers import (
    validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    setup_run_env, setup_active_network, create_qualified_format, create_line,
    get_agreement_version, scheduler, manager, api_client,
)

RUN_BODY = {
    "scheduled_qty": 50_000,
    "graphics_code": "G1",
    "window_start": "2026-09-10T08:00:00Z",
    "window_end": "2026-09-10T16:00:00Z",
}


class TestRunCreateBodyShape:
    def test_run_create_missing_graphics_code_returns_validation(self, api):
        """PRD §2.7 gate 3: "required fields present, types valid, enum
        membership respected ... Violations are rejected with `ERR_VALIDATION`
        (HTTP 400)." PRD §3.4 names `graphics_code` among the supplied fields.

        Design: Corner/entities/run_create_missing_graphics_code_returns_validation
        """
        env = setup_run_env()
        payload = dict(RUN_BODY, line_id=env["line"]["id"],
                       format_id=env["format"]["id"],
                       expected_agreement_version=env["agreement"]["version"])
        del payload["graphics_code"]
        resp = api.create_run(env["agreement"]["id"], payload, scheduler())
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        rows, _ = validate_paginated(api.list_runs(
            manager(), params={"agreement_id": env["agreement"]["id"]}))
        assert len(rows) == 0

    def test_run_create_bad_qty_beats_unknown_line_fk(self, api):
        """PRD §2.7: "Every request passes through nine ordered validation
        gates, and a request that would fail several gates is always rejected
        with the error from the earliest failing gate", with gate 3 body shape
        ("a `scheduled_qty` below 5,000") before gate 4 existence.

        Design: Corner/validations/run_create_bad_qty_beats_unknown_line_fk
        """
        env = setup_active_network()
        fmt = create_qualified_format(env[0]["id"], env[1]["id"])
        payload = dict(RUN_BODY, line_id=NON_EXISTENT_UUID,
                       format_id=fmt["id"], scheduled_qty=100,
                       expected_agreement_version=env[2]["version"])
        resp = api.create_run(env[2]["id"], payload, scheduler())
        err = validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert err["error_id"] != ApiErrorId.ERR_LINE_NOT_FOUND


class TestRunCreateFkOrder:
    def test_run_create_body_foreign_keys_checked_in_input_order(self, api):
        """PRD §2.6: "foreign keys carried in the request body are checked in
        the endpoint's declared input order ... a `line_id` with
        `ERR_LINE_NOT_FOUND`, and a `format_id` with `ERR_FORMAT_NOT_FOUND`".

        Design: Corner/validations/run_create_body_foreign_keys_checked_in_input_order
        """
        env = setup_active_network()
        line = create_line(env[0]["id"])
        bogus_line = "00000000-0000-4000-8000-000000000001"
        bogus_fmt = "00000000-0000-4000-8000-000000000002"
        version = env[2]["version"]
        resp_both = api.create_run(
            env[2]["id"], dict(RUN_BODY, line_id=bogus_line,
                               format_id=bogus_fmt,
                               expected_agreement_version=version), scheduler())
        err_both = validate_error(resp_both, ApiErrorId.ERR_LINE_NOT_FOUND)
        assert err_both["error_id"] != ApiErrorId.ERR_FORMAT_NOT_FOUND
        resp_fmt = api.create_run(
            env[2]["id"], dict(RUN_BODY, line_id=line["id"],
                               format_id=bogus_fmt,
                               expected_agreement_version=version), scheduler())
        validate_error(resp_fmt, ApiErrorId.ERR_FORMAT_NOT_FOUND)
        rows, _ = validate_paginated(
            api.list_runs(manager(), params={"agreement_id": env[2]["id"]}))
        assert len(rows) == 0
