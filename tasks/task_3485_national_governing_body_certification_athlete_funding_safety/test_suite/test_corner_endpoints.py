"""Corner tests: endpoints section — atomic bulk results finalization and
the fixed success/error response envelope shape."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    hold_trials,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_ngb_admin_headers,
    read_procedure,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
    setup_procedure_with_entries,
    validate_error,
)


def test_results_finalization_atomic(api, committee_admin_headers):
    """PRD §3.6: "Finalization is atomic: the array must cover every entry
    still `REGISTERED`, and any unknown `athlete_id` or duplicated athlete
    rejects the whole request unchanged."
    PRD §2.6: "3. **Existence.** Path parameters resolve to existing entities,
    validated left to right (§2.10), and body-supplied foreign-key references
    such as `athlete_id` and `governing_body_id` exist; otherwise
    `ERR_NOT_FOUND` (404). Applies to every endpoint."
    PRD §3.6: "An accepted entry appends to the procedure's `entries` as a
    record of `athlete_id`, `entry_status` of `REGISTERED`, `score` null, and
    `result_recorded_at` null."

    Design: Corner/endpoints/results_finalization_atomic
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Atomic Test", date_of_birth="2000-01-01"
    )
    proc = setup_procedure_with_entries(
        body["id"], [athlete["id"]], api=api, quota_slots=1
    )
    proc = hold_trials(proc, body["id"], api=api)

    set_logical_clock("2026-12-17T00:00:00Z", api=api)
    resp = api.transition_selection_procedure(
        proc["id"],
        {
            "to_state": "RESULTS_FINALIZED",
            "results": [
                {"athlete_id": athlete["id"], "score": 90},
                {"athlete_id": NON_EXISTENT_UUID, "score": 50},
            ],
        },
        make_ngb_admin_headers(body["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    after = read_procedure(body["id"], proc["id"], api=api)
    assert after["trials_status"] == "HELD", (
        "atomic rejection leaves the trials dimension untouched"
    )
    entry = next(e for e in after["entries"] if e["athlete_id"] == athlete["id"])
    assert entry["entry_status"] == "REGISTERED", (
        "no partial write: the valid athlete's entry is unchanged"
    )
    assert entry["score"] is None
    assert entry["result_recorded_at"] is None


def test_response_envelope_shape(api, committee_admin_headers):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body:"
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format:"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error. The `message` provides a human-readable
    explanation of what went wrong."

    Design: Corner/endpoints/response_envelope_shape
    """
    create_resp = api.create_governing_body(
        {
            "name": "US Track",
            "sport_code": "ATHL",
            "funding_budget_cents": 5_000_000,
            "sport_science_pool_hours": 100,
        },
        committee_admin_headers,
    )
    assert create_resp.status_code == 201
    success = create_resp.json()
    assert success["response_type"] == "object"
    meta = success["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
    assert isinstance(success["data"], dict)
    assert is_valid_uuid(success["data"].get("id", "")), (
        "data carries the created entity"
    )

    err_resp = api.get_governing_body(NON_EXISTENT_UUID, committee_admin_headers)
    assert err_resp.status_code == 404
    error = err_resp.json()
    assert error["response_type"] == "error"
    err_meta = error["meta"]
    assert isinstance(err_meta.get("api_request_id"), str)
    assert err_meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(err_meta.get("api_request_timestamp", ""))
    assert set(err_meta) == {"api_request_id", "api_request_timestamp"}, (
        "error meta carries only the request id and timestamp"
    )
    assert error["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(error["data"].get("message"), str)
    assert error["data"]["message"].strip(), "error message must be present"
