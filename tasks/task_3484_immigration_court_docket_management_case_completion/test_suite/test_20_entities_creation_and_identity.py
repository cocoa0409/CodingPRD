"""Entity probes: creation echoes, server-managed defaults, computed fields,
and the two uniqueness scopes.

A created court reports its computed backlog counters at zero; a created case
pins the FILED posture, the logical-clock filing instant, and the
custody-driven completion horizon; computed or undeclared body fields are
ignored rather than rejected; enum and required-field violations are the 400
input error; and case numbers are unique per venue court while court codes
are unique globally.
"""

from test_helpers import (
    ApiErrorId,
    add_days,
    assert_case,
    assert_court,
    create_court,
    make_case_payload,
    make_court_payload,
    read_court,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
    CLOCK_DEFAULT_ISO,
    TARGET_DAYS_NON_DETAINED,
)


def test_court_create_returns_computed_backlog_fields(api, admin_headers):
    """PRD §3.1: "A newly created court starts with `pending_case_count` 0, `completions_ytd` 0, and `is_backlog_critical` false, and reading the court back always returns those backlog fields freshly computed."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by 1 with every modification of the resource; this is the field the optimistic concurrency control of §2.7 reads."

    Design: Corner/entities/court_create_returns_computed_backlog_fields
    """
    payload = make_court_payload(
        court_code="CT-STD",
        name="Standard Court",
        city="Omaha",
        annual_completion_goal=100,
        detained_daily_hearing_capacity=2,
    )
    resp = api.create_court(payload, headers=admin_headers)
    court = validate_success(resp, 201)
    assert_court(court)
    assert court["court_code"] == "CT-STD"
    assert court["name"] == "Standard Court"
    assert court["city"] == "Omaha"
    assert court["annual_completion_goal"] == 100
    assert court["detained_daily_hearing_capacity"] == 2
    assert court["pending_case_count"] == 0
    assert court["completions_ytd"] == 0
    assert court["is_backlog_critical"] is False
    assert court["version"] == 1
    meta = resp.json()["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
    assert isinstance(meta["api_request_timestamp"], str)
    assert meta["api_request_timestamp"]

    reread = read_court(court["id"])
    assert reread["pending_case_count"] == 0
    assert reread["completions_ytd"] == 0
    assert reread["is_backlog_critical"] is False


def test_case_create_applies_defaults_and_system_fields(api, admin_headers):
    """PRD §3.2: "An optional `interpreter_required` flag defaults to true; English-proceeding cases set it to false, and their hearings are then created with `interpreter_id` null, skipping interpreter selection entirely."
    PRD §3.2: "A new case is `FILED`, with `filed_at` set to the current logical clock — the charging-document filing instant — and `assigned_judge_id` null, and the venue court's `pending_case_count` and `is_backlog_critical` recompute immediately."
    PRD §3.2: "Custody status fixes the case's completion horizon: `target_completion_date` is `filed_at` plus 60 days for a `DETAINED` case and plus 365 days for a `NON_DETAINED` case."
    PRD §3.2: "The official variant, `days_pending_calendar`, counts every calendar day including weekends: the whole number of 86,400-second days from `filed_at` to the current clock, rounded down."
    PRD §3.2: "The calendar variant alone drives the case's past-goal posture: `is_past_goal` is true only when `days_pending_calendar` strictly exceeds the custody-specific target."

    Design: Corner/entities/case_create_applies_defaults_and_system_fields
    """
    court = create_court()
    payload = make_case_payload(
        court["id"], case_number="S-1", respondent_full_name="R Std"
    )
    # Omit the flag entirely so the server-side default is observable.
    del payload["interpreter_required"]
    resp = api.create_case(payload, headers=admin_headers)
    case = validate_success(resp, 201)
    assert_case(case)
    assert case["interpreter_required"] is True, "omitted flag takes the default true"
    assert case["status"] == "FILED"
    assert case["assigned_judge_id"] is None
    assert case["completed_at"] is None
    assert same_instant(case["filed_at"], CLOCK_DEFAULT_ISO), (
        "filed_at is the logical clock, not wall-clock time"
    )
    assert same_instant(
        case["target_completion_date"],
        add_days(CLOCK_DEFAULT_ISO, TARGET_DAYS_NON_DETAINED),
    ), "the NON_DETAINED horizon is filed_at plus 365 days"
    assert case["continuance_count"] == 0
    assert case["days_pending_calendar"] == 0
    assert case["is_past_goal"] is False


def test_case_create_with_computed_field_input_ignored(api, admin_headers):
    """PRD §2.6: "Unknown body fields are ignored rather than rejected, here and at every tier."
    PRD §3.2: "A new case is `FILED`, with `filed_at` set to the current logical clock — the charging-document filing instant — and `assigned_judge_id` null, and the venue court's `pending_case_count` and `is_backlog_critical` recompute immediately."
    PRD §3.2: "The score starts from a base of 1000 points for a `DETAINED` case and 0 otherwise; it adds 2 points per calendar day of age as measured by `days_pending_calendar`, with the age term capped at 720 days; and it subtracts a drag of 25 points per granted continuance as measured by `continuance_count`, with the drag capped at 4 continuances — so a case with five granted continuances sheds the same 100 points as one with four. The total is floored at 0: a score never goes negative."

    Design: Corner/entities/case_create_with_computed_field_input_ignored
    """
    court = create_court()
    # priority_score and status are not among the filing operation's declared
    # inputs, so the supplied values must be ignored, not honored or rejected.
    payload = make_case_payload(
        court["id"],
        case_number="S-2",
        respondent_full_name="R Rig",
        priority_score=9999,
        status="COMPLETED",
    )
    resp = api.create_case(payload, headers=admin_headers)
    case = validate_success(resp, 201)
    assert_case(case)
    assert case["priority_score"] == 0, (
        "the formula output for a fresh NON_DETAINED case, not the supplied 9999"
    )
    assert case["status"] == "FILED", "not the supplied COMPLETED"


def test_case_create_with_invalid_enum_returns_invalid_request(api, admin_headers):
    """PRD §2.6: "At this same tier, `ERR_INVALID_REQUEST` (HTTP 400) covers malformed bodies, missing required fields, wrong value types, and enum values outside the declared membership."
    PRD §3.2: "the respondent's `custody_status` of `DETAINED` or `NON_DETAINED`"

    Design: Corner/entities/case_create_with_invalid_enum_returns_invalid_request
    """
    court = create_court()
    resp = api.create_case(
        make_case_payload(court["id"], case_number="S-9", custody_status="MAYBE"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    rows, _meta = validate_paginated(
        api.list_cases(headers=admin_headers, params={"court_id": court["id"]})
    )
    assert rows == [], "the rejected filing persisted nothing"


def test_case_create_missing_required_field_returns_invalid_request(
    api, admin_headers
):
    """PRD §2.6: "At this same tier, `ERR_INVALID_REQUEST` (HTTP 400) covers malformed bodies, missing required fields, wrong value types, and enum values outside the declared membership."
    PRD §3.2: "A case enters the system when a `CourtAdministrator` files a charging document, supplying the venue `court_id` (the initial venue assignment), the charging-document `case_number`, the `respondent_full_name`, the respondent's `custody_status` of `DETAINED` or `NON_DETAINED`, a `primary_language_code` given as an ISO 639-2/T lowercase three-letter code, and a `representation_status` of `PRO_SE`, `COUNSEL_RETAINED`, or `PRO_BONO`."

    Design: Corner/entities/case_create_missing_required_field_returns_invalid_request
    """
    court = create_court()
    payload = make_case_payload(court["id"], respondent_full_name="R Missing")
    del payload["case_number"]  # a declared required input, omitted entirely
    resp = api.create_case(payload, headers=admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    rows, _meta = validate_paginated(
        api.list_cases(headers=admin_headers, params={"court_id": court["id"]})
    )
    assert rows == [], "the rejected filing persisted nothing"


def test_case_number_unique_within_court_only(api, admin_headers):
    """PRD §3.2: "The `case_number` must be unique within the venue court: a second filing carrying the same `case_number` at the same court is rejected with `ERR_CASE_NUMBER_NOT_UNIQUE`, while the same number at a different court is unremarkable."

    Design: Corner/entities/case_number_unique_within_court_only
    """
    court_a = create_court()
    court_b = create_court()
    first = validate_success(
        api.create_case(
            make_case_payload(court_a["id"], case_number="S-1"),
            headers=admin_headers,
        ),
        201,
    )
    assert first["court_id"] == court_a["id"]

    # The duplicate inside the same venue court is the 409 uniqueness failure.
    resp = api.create_case(
        make_case_payload(
            court_a["id"], case_number="S-1", respondent_full_name="R Dup"
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NUMBER_NOT_UNIQUE)

    # The same case_number under a different court is unremarkable.
    second = validate_success(
        api.create_case(
            make_case_payload(
                court_b["id"], case_number="S-1", respondent_full_name="R Ok"
            ),
            headers=admin_headers,
        ),
        201,
    )
    assert second["court_id"] == court_b["id"]
    assert second["case_number"] == "S-1"


def test_court_code_globally_unique(api, admin_headers):
    """PRD §3.1: "The `court_code` must be unique across all courts; a duplicate is rejected with `ERR_COURT_CODE_NOT_UNIQUE`."

    Design: Corner/entities/court_code_globally_unique
    """
    court = create_court(court_code="CT-STD", name="Standard Court", city="Omaha")
    resp = api.create_court(
        make_court_payload(
            court_code="CT-STD",
            name="Duplicate Code Court",
            city="Nowhere",
            annual_completion_goal=5,
            detained_daily_hearing_capacity=0,
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_COURT_CODE_NOT_UNIQUE)

    # The rejected duplicate leaves the original court untouched.
    reread = read_court(court["id"])
    assert reread["court_code"] == "CT-STD"
    assert reread["name"] == "Standard Court"
    assert reread["city"] == "Omaha"
    assert reread["pending_case_count"] == 0
