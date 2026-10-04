"""Corner probes over entity creation, defaults, retrieval, and list pagination."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_benefit_schedule,
    assert_employee,
    assert_employer_group,
    assert_enrollment_campaign,
)
from test_helpers.test_users import make_carrier_admin_headers


def test_creating_a_group_with_only_its_required_fields_applies_the_defaults(client):
    """A bare create lands PROSPECT with the documented defaults and counters at 0.

    "A `CarrierAdmin` registers a group with its legal `name` and a globally
    unique `group_code`, optionally tuning the participation rules that will later
    decide whether campaigns at this group succeed: `participation_minimum_pct` is
    the fraction of eligible employees that must enroll (a number from 0 to 1
    inclusive, defaulting to 0.10), `participation_minimum_count` is an absolute
    floor on enrolled policies (defaulting to 3), and `proration_convention`
    selects the group's payroll proration variant — `DAILY` or `HALF_MONTH`,
    defaulting to `DAILY`. A new group is born in `PROSPECT` status."

    Design: Corner/entities/employer_group_create_returns_defaults_and_version_1
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")

    response = client.create_employer_group(
        {"name": "Corner Group", "group_code": "CG-1"}, make_carrier_admin_headers()
    )
    data = validate_success(response, 201)

    assert_employer_group(data)
    assert data["status"] == "PROSPECT"
    assert data["version"] == 1
    assert data["participation_minimum_pct"] == 0.10
    assert data["participation_minimum_count"] == 3
    assert data["proration_convention"] == "DAILY"
    assert data["eligible_employee_count"] == 0
    assert data["enrolled_count"] == 0


def test_reusing_a_group_code_is_rejected_even_when_everything_else_differs(client):
    """group_code is globally unique; a second create with the same code fails.

    "A `CarrierAdmin` registers a group with its legal `name` and a globally
    unique `group_code`, optionally tuning the participation rules that will later
    decide whether campaigns at this group succeed: `participation_minimum_pct` is
    the fraction of eligible employees that must enroll (a number from 0 to 1
    inclusive, defaulting to 0.10), `participation_minimum_count` is an absolute
    floor on enrolled policies (defaulting to 3), and `proration_convention`
    selects the group's payroll proration variant — `DAILY` or `HALF_MONTH`,
    defaulting to `DAILY`. A new group is born in `PROSPECT` status."

    Design: Corner/entities/employer_group_duplicate_group_code_rejected
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    fixtures.create_group(client, name="First", group_code="CG-DUP")

    response = client.create_employer_group(
        {"name": "Second", "group_code": "CG-DUP"}, make_carrier_admin_headers()
    )

    validate_error(response, api_errors.ERR_INVALID_REQUEST, 400)


def test_getting_a_group_that_does_not_exist_returns_a_404_error_envelope(client):
    """A well-formed but unknown group id resolves to ERR_NOT_FOUND.

    "Every request is validated in a fixed priority order, and the first failing
    check determines the error returned. Authentication comes first
    (`ERR_UNAUTHENTICATED`, then the role check `ERR_UNAUTHORIZED`), followed by
    existence of every identifier referenced in the path and body, evaluated
    left-to-right (`ERR_NOT_FOUND`), and then referential integrity of
    body-supplied foreign keys (`ERR_REFERENTIAL_INTEGRITY`)."

    Design: Corner/entities/employer_group_get_not_found_returns_404
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")

    response = client.get_employer_group(NON_EXISTENT_UUID, make_carrier_admin_headers())

    validate_error(response, api_errors.ERR_NOT_FOUND, 404)


def test_a_new_schedule_is_draft_and_echoes_its_version_and_effective_date(client):
    """Schedule creation lands DRAFT with the inputs round-tripping exactly.

    "Schedules carry the actual money: each schedule belongs to a series via
    `policy_series_id` and is created in `DRAFT` with a `schedule_version`, an
    `effective_date`, the `benefit_items` array, a `monthly_premium_cents`, a
    `wellness_benefit_cents` (the annual wellness amount), a
    `wellness_waiting_months` (whole months after coverage start before the
    wellness benefit is payable), and a `preexisting_exclusion_months` (whole
    months after coverage start during which pre-existing diagnoses are
    excluded)."

    Design: Corner/entities/benefit_schedule_defaults_and_system_fields
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    series = fixtures.create_series(client, product_line="HOSPITAL")

    schedule = fixtures.create_schedule(
        client,
        series["id"],
        schedule_version=1,
        effective_date="2026-01-01T00:00:00Z",
        benefit_items=[factories.benefit_item_payload(event_code="E1", benefit_amount_cents=100,
                                                      max_occurrences_per_year=1,
                                                      lifetime_max_cents=1000)],
        monthly_premium_cents=100,
        wellness_benefit_cents=50,
        wellness_waiting_months=0,
        preexisting_exclusion_months=0,
    )

    assert_benefit_schedule(schedule)
    assert schedule["status"] == "DRAFT"
    assert schedule["version"] == 1
    assert schedule["schedule_version"] == 1
    assert schedule["effective_date"][:19] == "2026-01-01T00:00:00"
    assert schedule["effective_date"].endswith("Z")


def test_an_employee_created_without_preexisting_codes_stores_an_empty_list(client):
    """The omitted pre-existing list defaults to an empty array, and ACTIVE.

    "A `CarrierAdmin` or `GroupAdmin` creates an employee with the
    `employer_group_id`, an `employee_ref` unique within that employer group, a
    `full_name`, a `hire_date`, and optionally `preexisting_diagnosis_codes`
    (defaulting to an empty list); employees start `ACTIVE`."

    Design: Corner/entities/employee_preexisting_codes_default_empty
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    group = fixtures.create_active_group(client)

    employee = fixtures.create_employee(
        client, group["id"], employee_ref="CE-1", full_name="Corner Emp"
    )

    assert_employee(employee)
    assert employee["preexisting_diagnosis_codes"] == [], (
        "default is an empty list, not null; got %r"
        % employee.get("preexisting_diagnosis_codes")
    )
    assert employee["status"] == "ACTIVE"


def test_a_draft_campaign_round_trips_its_window_and_null_verdict_fields(client):
    """GET returns the stored window and guaranteed-issue flag with null verdicts.

    "Creating one requires the `employer_group_id`, the `counselor_id`, a
    `window_start`, and a `window_end` strictly after the start; both instants are
    ISO 8601 UTC, and the window is a half-open interval — `window_start`
    inclusive, `window_end` exclusive. The optional `guaranteed_issue` flag
    (default false) determines whether applications in this campaign skip the
    pre-existing-condition screen. The designated counselor must be `ACTIVE` at
    creation, and a new campaign starts in `DRAFT`."

    Design: Corner/entities/campaign_get_returns_stored_window_fields
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    group = fixtures.create_active_group(client)
    counselor = fixtures.create_counselor(client)
    created = fixtures.create_campaign(
        client, group["id"], counselor, guaranteed_issue=False
    )

    campaign = validate_success(
        client.get_enrollment_campaign(created["id"], make_carrier_admin_headers()), 200
    )

    assert_enrollment_campaign(campaign)
    assert campaign["window_start"][:19] == "2026-09-01T00:00:00"
    assert campaign["window_start"].endswith("Z")
    assert campaign["window_end"][:19] == "2026-10-01T00:00:00"
    assert campaign["window_end"].endswith("Z")
    assert campaign["guaranteed_issue"] is False
    assert campaign["status"] == "DRAFT"
    assert campaign["required_enrollments"] is None
    assert campaign["participation_met"] is None


def test_campaign_listing_pages_with_limit_offset_total_count_and_has_more(client):
    """limit=2 over three campaigns yields 2+1 with the pagination fields pinned.

    "The `limit` parameter specifies the maximum number of items to return. If not
    provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter specifies the number of items to skip and defaults to 0."
    "Paginated list responses include the following fields in the `meta` object of
    the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/enrollment_campaign_list_pagination_envelope
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    group = fixtures.create_active_group(client)
    counselors = [fixtures.create_counselor(client) for _ in range(3)]
    windows = [
        ("2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z"),
        ("2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z"),
        ("2026-09-20T00:00:00Z", "2026-10-01T00:00:00Z"),
    ]
    for counselor, (start, end) in zip(counselors, windows):
        fixtures.create_campaign(
            client, group["id"], counselor, window_start=start, window_end=end
        )

    page1, meta1 = validate_paginated(
        client.list_enrollment_campaigns(
            make_carrier_admin_headers(),
            filters={"employer_group_id": group["id"], "limit": 2, "offset": 0},
        )
    )
    page2, meta2 = validate_paginated(
        client.list_enrollment_campaigns(
            make_carrier_admin_headers(),
            filters={"employer_group_id": group["id"], "limit": 2, "offset": 2},
        )
    )

    assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True
    assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False
