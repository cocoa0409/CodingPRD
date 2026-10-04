"""Rate case lifecycle, OCC on program version, listing (PRD §2.3, §2.7, §3.2)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    api_client,
    create_rate_case_payload,
    create_program, get_program, get_program_version,
    create_rate_case, create_rate_case_in_state,
    assert_rate_case,
)


def test_rate_case_initial_state_is_draft(api, planner_headers):
    """PRD §3.2: "Creating the case — it lands in `DRAFT` — itself increments the program's
    `version` by one, so a second create against the version a client just read is already
    stale."
    PRD §3.2: "The same review sets `gating_verdict` — null until this point — to `PASS`
    when the frozen readiness index is at least 85.0 and the program's `open_escape_count`
    is zero at review time, and to `FAIL` otherwise."

    Design: Corner/state_machines/rate_case_initial_state_is_draft
    """
    program = create_program()
    case = create_rate_case(program["id"], proposed_rate=8)
    assert_rate_case(case)
    assert case["status"] == "DRAFT"
    assert case["gating_verdict"] is None, "verdict stays null until the gating review"


def test_rate_case_commit_from_draft_rejected(api, planner_headers):
    """PRD §3.2: "Committing (`GATED_REVIEW` → `COMMITTED`) is gated on a `PASS` verdict;
    any other verdict draws `ERR_GATING_CRITERIA_UNMET` (HTTP 422)."
    PRD §2.8: "the requested transition must exist from the resource's current state,
    including terminal-state lockdown and the delivery-pipeline stage gates
    (`ERR_INVALID_TRANSITION`, 409)".

    Design: Corner/state_machines/rate_case_commit_from_draft_rejected
    """
    program = create_program()
    case = create_rate_case(program["id"], proposed_rate=8)
    assert case["status"] == "DRAFT"
    resp = api_client.commit_rate_case(case["id"], planner_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_rate_case_announce_from_shelved_rejected(api, planner_headers):
    """PRD §3.2: "`COMMITTED` and `SHELVED` are terminal — any further action on such a
    case is `ERR_INVALID_TRANSITION` (HTTP 409)."
    PRD §3.2: "the announced target always reflects the `proposed_rate` of the most recently
    created case currently in `ANNOUNCED` or `GATED_REVIEW` — the latest by `created_at`
    wins — and falls back to `current_rate_per_month` when no such case exists."

    Design: Corner/state_machines/rate_case_announce_from_shelved_rejected
    """
    program = create_program()
    case = create_rate_case(program["id"], proposed_rate=8)
    validate_success(api_client.shelve_rate_case(case["id"], planner_headers))
    resp = api_client.announce_rate_case(case["id"], planner_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
    program = get_program(program["id"])
    assert program["announced_target_rate"] == 5, (
        "shelved case contributes nothing: fallback to the committed current rate"
    )


def test_rate_case_with_unchanged_rate_rejected(api, planner_headers):
    """PRD §3.2: "then a `proposed_rate` equal to the program's `current_rate_per_month` is
    rejected `ERR_RATE_UNCHANGED` (422), because a rate case must propose a change."

    Design: Corner/validations/rate_case_with_unchanged_rate_rejected
    """
    program = create_program()
    resp = api_client.create_rate_case(
        program["id"],
        create_rate_case_payload(get_program_version(program["id"]), proposed_rate=5),
        planner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RATE_UNCHANGED)


def test_rate_case_effective_month_in_past_rejected(api, planner_headers):
    """PRD §3.2: "an `effective_month` earlier than the current logical month is rejected
    `ERR_WINDOW_INVALID` (422)".
    PRD §2.4: "At startup the clock reads exactly `2026-09-01T00:00:00Z`, and it holds that
    reading until a `ProgramAdmin` moves it."

    Design: Corner/validations/rate_case_effective_month_in_past_rejected
    """
    program = create_program()
    resp = api_client.create_rate_case(
        program["id"],
        create_rate_case_payload(
            get_program_version(program["id"]),
            proposed_rate=8,
            effective_month="2026-08",
        ),
        planner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID)


def test_occ_rate_case_create_with_stale_program_version(api, planner_headers):
    """PRD §2.7: "Creating a rate case against a program requires the request body to carry
    `expected_program_version`, holding the program `version` the client last observed. If
    it does not equal the program's current `version`, the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412): another writer's rate activity — creating, announcing,
    or committing a case all advance the program's `version` — has legitimately superseded
    the client's baseline, and the client's view of the program is stale."
    PRD §3.2: "Creating the case — it lands in `DRAFT` — itself increments the program's
    `version` by one, so a second create against the version a client just read is already
    stale."

    Design: Corner/cross_cutting_complexity_layers/occ_rate_case_create_with_stale_program_version
    """
    program = create_program()
    stale_version = program["version"]
    first = create_rate_case(
        program["id"], proposed_rate=8, effective_month="2027-01", demand_backlog_units=100
    )
    assert first["status"] == "DRAFT"
    assert get_program_version(program["id"]) == stale_version + 1, (
        "the first create increments the program version by one"
    )
    resp = api_client.create_rate_case(
        program["id"],
        create_rate_case_payload(
            stale_version, proposed_rate=9,
            effective_month="2027-01", demand_backlog_units=90,
        ),
        planner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_announced_target_rate_reconciles_after_shelve(api, planner_headers):
    """PRD §3.2: "the announced target always reflects the `proposed_rate` of the most
    recently created case currently in `ANNOUNCED` or `GATED_REVIEW` — the latest by
    `created_at` wins — and falls back to `current_rate_per_month` when no such case
    exists."
    PRD §3.2: "Shelving an announced or gated case recomputes the announced target from the
    remaining `ANNOUNCED` or `GATED_REVIEW` cases, with the committed rate as the fallback
    when none remain; shelving a draft touches nothing downstream."

    Design: Corner/cross_cutting_complexity_layers/announced_target_rate_reconciles_after_shelve
    """
    program = create_program()
    case = create_rate_case(program["id"], proposed_rate=8)
    validate_success(api_client.announce_rate_case(case["id"], planner_headers))
    assert get_program(program["id"])["announced_target_rate"] == 8
    validate_success(api_client.shelve_rate_case(case["id"], planner_headers))
    assert get_program(program["id"])["announced_target_rate"] == 5, (
        "no ANNOUNCED or GATED_REVIEW case remains: fallback to current_rate_per_month"
    )


def test_rate_cases_list_paginates_with_envelope(api, planner_headers):
    """PRD §2.3: "`limit` caps the number of returned items: it defaults to 10, with a
    minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the
    result set and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries four pagination fields: `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for
    a list of resources."

    Design: Corner/endpoints/rate_cases_list_paginates_with_envelope
    """
    program = create_program()
    case_a = create_rate_case(program["id"], proposed_rate=8)
    case_b = create_rate_case(program["id"], proposed_rate=9)

    resp1 = api_client.list_rate_cases(
        program["id"], planner_headers, params={"limit": 1, "offset": 0}
    )
    page1, meta1 = validate_paginated(resp1)
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0
    assert meta1["has_more"] is True
    assert resp1.json()["response_type"] == "array"
    assert meta1["api_request_id"].startswith("req_")

    resp2 = api_client.list_rate_cases(
        program["id"], planner_headers, params={"limit": 1, "offset": 1}
    )
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False

    paged_ids = {page1[0]["id"], page2[0]["id"]}
    assert paged_ids == {case_a["id"], case_b["id"]}, (
        "the two pages together cover exactly the two cases"
    )


def test_rate_cases_list_filters_by_status(api, planner_headers):
    """PRD §3.2: "A program's case list can be filtered by `status`."

    Design: Corner/endpoints/rate_cases_list_filters_by_status
    """
    program = create_program()
    case_a = create_rate_case(program["id"], proposed_rate=8)
    case_b = create_rate_case(program["id"], proposed_rate=9)
    validate_success(api_client.shelve_rate_case(case_b["id"], planner_headers))

    shelved, meta_s = validate_paginated(
        api_client.list_rate_cases(
            program["id"], planner_headers, params={"status": "SHELVED"}
        )
    )
    assert meta_s["total_count"] == 1
    assert [c["id"] for c in shelved] == [case_b["id"]]

    drafts, meta_d = validate_paginated(
        api_client.list_rate_cases(
            program["id"], planner_headers, params={"status": "DRAFT"}
        )
    )
    assert meta_d["total_count"] == 1
    assert [c["id"] for c in drafts] == [case_a["id"]]


def test_rate_case_walks_draft_to_gated_review(api, planner_headers):
    """PRD §3.2: "Announcing moves a case `DRAFT` → `ANNOUNCED`, copies its `proposed_rate`
    into the program's `announced_target_rate`, and advances the program's `version`
    again."
    PRD §3.2: "Requesting a gating review (`ANNOUNCED` → `GATED_REVIEW`) freezes the
    evidence."

    Design: Corner/state_machines/rate_case_initial_state_is_draft
    """
    program = create_program()
    case = create_rate_case(program["id"], proposed_rate=8)
    assert case["status"] == "DRAFT"
    case = validate_success(api_client.announce_rate_case(case["id"], planner_headers))
    assert case["status"] == "ANNOUNCED"
    assert get_program(program["id"])["announced_target_rate"] == 8
    case = validate_success(api_client.request_gating_review(case["id"], planner_headers))
    assert case["status"] == "GATED_REVIEW"
    # No commitments and no hires: supply 0/1 -> 0.0, workforce 100.0, index 0.0 < 85.0.
    assert case["readiness_index_snapshot"] == 0.0
    assert case["gating_verdict"] == "FAIL"
