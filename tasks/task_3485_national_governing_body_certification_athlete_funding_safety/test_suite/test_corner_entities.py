"""Corner tests: entities section — creation success shape, not-found
behavior, athlete defaults, required-field rejection, foreign-key existence,
list filtering with pagination, and system-field handling on create."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_athlete,
    assert_governing_body,
    assert_pagination_meta,
    assert_performance_result,
    create_athlete,
    create_governing_body,
    is_valid_uuid,
    make_athlete_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_governing_body_success(api, committee_admin_headers):
    """PRD §3.1: "The new body starts in `APPLIED` status — one of five
    lifecycle states, `APPLIED`, `CERTIFIED`, `PROBATION`, `INTERIM_MANAGED`,
    and the terminal `DECERTIFIED` — with `certified_at` null until the body
    first certifies, `interim_manager_id` null, and the computed trio
    `committed_monthly_stipend_cents`, `allocated_science_hours`, and
    `substantiated_complaint_count` all at zero with `complaint_posture` of
    `NORMAL`."
    PRD §2.4: "`version` (integer):** starts at 1 on creation and increments
    by exactly 1 on every mutation, including mutations caused by system
    cascades rather than direct client writes."
    PRD §4: "Operations that create a new resource return `201 Created`;
    operations that modify an existing resource — including every state
    transition, the nomination selector, and the clock set — return `200 OK`."

    Design: Corner/entities/create_governing_body_success
    """
    resp = api.create_governing_body(
        {
            "name": "US Swim Federation",
            "sport_code": "SWIM",
            "funding_budget_cents": 5_000_000,
            "sport_science_pool_hours": 100,
        },
        committee_admin_headers,
    )
    body = validate_success(resp, 201)
    assert_governing_body(body)
    assert body["status"] == "APPLIED"
    assert body["version"] == 1
    assert body["committed_monthly_stipend_cents"] == 0
    assert body["allocated_science_hours"] == 0
    assert body["substantiated_complaint_count"] == 0
    assert body["complaint_posture"] == "NORMAL"
    assert body["certified_at"] is None
    assert body["interim_manager_id"] is None
    assert is_valid_uuid(body["id"]), "id must be a server-minted UUID"


def test_governing_body_not_found_returns_404(api, committee_admin_headers):
    """PRD §2.6: "3. **Existence.** Path parameters resolve to existing
    entities, validated left to right (§2.10), and body-supplied foreign-key
    references such as `athlete_id` and `governing_body_id` exist; otherwise
    `ERR_NOT_FOUND` (404). Applies to every endpoint."

    Design: Corner/entities/governing_body_not_found_returns_404
    """
    resp = api.get_governing_body(NON_EXISTENT_UUID, committee_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_athlete_creation_defaults_applied(api, committee_admin_headers):
    """PRD §3.3: "A `CommitteeAdmin`, or an `NGBAdmin` acting for their own
    body, registers an athlete by supplying the `governing_body_id` of the
    registering body, the athlete's `full_name`, a `date_of_birth` as an
    ISO 8601 date in `YYYY-MM-DD` form, and optionally `team_sport`, a boolean
    defaulting to false for individual-sport athletes."
    PRD §3.3: "The eligibility dimension, `eligibility_status`, runs
    `REGISTERED` to `ELIGIBLE`, may drop to `SUSPENDED` and return, and ends
    at the terminal `RETIRED`. The screening dimension, `screening_status`,
    cycles through `SCREENING_PENDING`, `SCREENING_CLEARED`,
    `SCREENING_FLAGGED`, and `SCREENING_EXPIRED`."
    PRD §3.3: "Two timestamps complete the safe-sport picture:
    `screening_expires_at`, null until the first clearance, and
    `training_completed_at`, null until the first recorded training
    completion."

    Design: Corner/entities/athlete_creation_defaults_applied
    """
    body = create_governing_body(
        api=api,
        name="US Swim Federation",
        sport_code="SWIM",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    # team_sport deliberately omitted so the server-side default applies.
    resp = api.create_athlete(
        {
            "governing_body_id": body["id"],
            "full_name": "Sam Blue",
            "date_of_birth": "2002-02-02",
        },
        committee_admin_headers,
    )
    athlete = validate_success(resp, 201)
    assert_athlete(athlete)
    assert athlete["team_sport"] is False, "omitted team_sport defaults to false"
    assert athlete["eligibility_status"] == "REGISTERED"
    assert athlete["screening_status"] == "SCREENING_PENDING"
    assert athlete["training_completed_at"] is None
    assert athlete["screening_expires_at"] is None


def test_create_athlete_missing_required_field(api, committee_admin_headers):
    """PRD §2.6: "7. **Constraint checks.** Component scores within 0 to 100
    and placings within 1 to 8 (`ERR_SCORE_OUT_OF_RANGE`, 422); malformed
    bodies — missing required fields, wrong types, unknown enum members, empty
    required strings (`ERR_INVALID_REQUEST`, 400, on every endpoint);
    segregation-of-duties pairs (`ERR_SEGREGATION_OF_DUTIES`, 403); duplicate
    trials entries (`ERR_DUPLICATE_ENTRY`, 409); roster submission blocked by
    pending appeals (`ERR_PENDING_APPEALS`, 409) or by unanswered primary
    slots (`ERR_PENDING_SLOT_DECISIONS`, 409); nomination attempted before
    trials results are final (`ERR_RESULTS_NOT_FINAL`, 409)."
    PRD §3.3: "A `CommitteeAdmin`, or an `NGBAdmin` acting for their own body,
    registers an athlete by supplying the `governing_body_id` of the
    registering body, the athlete's `full_name`, a `date_of_birth` as an
    ISO 8601 date in `YYYY-MM-DD` form, and optionally `team_sport`, a boolean
    defaulting to false for individual-sport athletes."

    Design: Corner/entities/create_athlete_missing_required_field
    """
    # governing_body_id omitted — a required field per the registration rule.
    resp = api.create_athlete(
        {"full_name": "No Body", "date_of_birth": "2000-01-01"},
        committee_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_athlete_creation_with_unknown_body_returns_not_found(
    api, committee_admin_headers
):
    """PRD §2.10: "Foreign keys supplied in a request body (for example
    `athlete_id` on a trials entry or `governing_body_id` on athlete
    registration) are validated for existence at the same tier, immediately
    after path resolution."
    PRD §2.6: "3. **Existence.** Path parameters resolve to existing entities,
    validated left to right (§2.10), and body-supplied foreign-key references
    such as `athlete_id` and `governing_body_id` exist; otherwise
    `ERR_NOT_FOUND` (404). Applies to every endpoint."

    Design: Corner/entities/athlete_creation_with_unknown_body_returns_not_found
    """
    resp = api.create_athlete(
        {
            "governing_body_id": NON_EXISTENT_UUID,
            "full_name": "Ghost",
            "date_of_birth": "2000-01-01",
        },
        committee_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_athletes_filter_and_pagination(api, committee_admin_headers):
    """PRD §4: "GET `/api/athletes` — List athletes, filterable by
    `governing_body_id` and `eligibility_status`."
    PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1, and rejects values
    above 100. The `offset` parameter skips a number of items from the front
    of the result set and defaults to 0."
    PRD §2.3: "Paginated list responses carry four fields in the `meta` object
    of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_athletes_filter_and_pagination
    """
    gb1 = create_governing_body(
        api=api,
        name="US Swim Federation",
        sport_code="SWIM",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    gb2 = create_governing_body(
        api=api,
        name="US Judo",
        sport_code="JUDO",
        funding_budget_cents=3_000_000,
        sport_science_pool_hours=40,
    )
    create_athlete(gb1["id"], api=api, full_name="A One", date_of_birth="1998-01-01")
    create_athlete(gb1["id"], api=api, full_name="A Two", date_of_birth="1998-01-02")
    create_athlete(gb2["id"], api=api, full_name="B One", date_of_birth="1998-02-01")

    resp = api.list_athletes(
        committee_admin_headers,
        params={"governing_body_id": gb1["id"], "limit": 1, "offset": 0},
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must cap the page, got {len(data)}"
    assert_pagination_meta(meta, limit=1, offset=0, total_count=2, returned_count=1)
    assert meta["has_more"] is True
    assert all(a["governing_body_id"] == gb1["id"] for a in data), (
        "governing_body_id filter must narrow the list to body 1"
    )


def test_create_result_with_system_fields_input_ignored(
    api, committee_admin_headers
):
    """PRD §2.4: "`id` (string):** a server-minted UUID with no type prefix."
    PRD §2.4: "`version` (integer):** starts at 1 on creation and increments
    by exactly 1 on every mutation, including mutations caused by system
    cascades rather than direct client writes."
    PRD §3.4: "The result starts `SUBMITTED`."

    Design: Corner/entities/create_result_with_system_fields_input_ignored
    """
    body = create_governing_body(
        api=api,
        name="US Swim Federation",
        sport_code="SWIM",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = create_athlete(
        body["id"], api=api, full_name="Sys Field", date_of_birth="2000-01-01"
    )
    resp = api.create_result(
        athlete["id"],
        {
            "event_name": "Spring Open",
            "event_grade": "B",
            "placing": 5,
            "event_date": "2026-10-01T00:00:00Z",
            # System-managed fields a client must not control.
            "id": "11111111-1111-1111-1111-111111111111",
            "status": "VERIFIED",
            "version": 9,
        },
        make_athlete_headers(athlete["id"]),
    )
    result = validate_success(resp, 201)
    assert_performance_result(result)
    assert result["id"] != "11111111-1111-1111-1111-111111111111", (
        "id is server-minted; the supplied value must be ignored"
    )
    assert is_valid_uuid(result["id"])
    assert result["status"] == "SUBMITTED", "supplied status VERIFIED ignored"
    assert result["version"] == 1, "supplied version 9 ignored; starts at 1"
