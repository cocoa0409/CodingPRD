"""Corner probes over endpoint behaviors: schedule creation constraints, the
application window, duplicate coverage, and filtered claim listing."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import (
    make_carrier_admin_headers,
    make_claims_adjuster_headers,
    make_counselor_headers,
)


def test_duplicate_event_codes_within_one_schedule_are_rejected(client):
    """Uniqueness of event_code is within the benefit_items array, not across.

    "Within a schedule, `benefit_items` is an array of entries each carrying an
    `event_code`, a `benefit_amount_cents`, a `max_occurrences_per_year`, and a
    `lifetime_max_cents`; the `event_code` values must be unique within the
    array."

    Design: Corner/endpoints/schedule_create_with_duplicate_event_codes_rejected
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    series = fixtures.create_series(client)

    response = client.create_benefit_schedule(
        {
            "policy_series_id": series["id"],
            "schedule_version": 1,
            "effective_date": "2026-01-01T00:00:00Z",
            "benefit_items": [
                {"event_code": "DUP", "benefit_amount_cents": 100,
                 "max_occurrences_per_year": 1, "lifetime_max_cents": 1000},
                {"event_code": "DUP", "benefit_amount_cents": 200,
                 "max_occurrences_per_year": 2, "lifetime_max_cents": 2000},
            ],
            "monthly_premium_cents": 100,
            "wellness_benefit_cents": 50,
            "wellness_waiting_months": 0,
            "preexisting_exclusion_months": 0,
        },
        make_carrier_admin_headers(),
    )

    validate_error(response, api_errors.ERR_INVALID_REQUEST, 400)


def test_schedule_version_must_increase_within_a_series(client):
    """A repeated schedule_version conflicts; a strictly greater one succeeds.

    "Publishing is strictly serialized within a series: a new schedule's
    `schedule_version` must be greater than every existing `schedule_version` of
    the same series, and its `effective_date` must be strictly later than the
    effective date of every other schedule in the series — even a same-day
    collision is rejected with `ERR_SCHEDULE_VERSION_CONFLICT`."

    Design: Corner/endpoints/schedule_version_must_increase_within_series
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    series = fixtures.create_series(client)
    fixtures.create_schedule(
        client, series["id"],
        schedule_version=1,
        benefit_items=[benefit_item_payload(event_code="V1")],
    )

    conflict = client.create_benefit_schedule(
        {
            "policy_series_id": series["id"],
            "schedule_version": 1,
            "effective_date": "2026-06-01T00:00:00Z",
            "benefit_items": [benefit_item_payload(event_code="V1")],
            "monthly_premium_cents": 100,
            "wellness_benefit_cents": 50,
            "wellness_waiting_months": 0,
            "preexisting_exclusion_months": 0,
        },
        make_carrier_admin_headers(),
    )
    validate_error(conflict, api_errors.ERR_SCHEDULE_VERSION_CONFLICT, 409)

    accepted = fixtures.create_schedule(
        client, series["id"],
        schedule_version=2,
        effective_date="2026-06-01T00:00:00Z",
        benefit_items=[benefit_item_payload(event_code="V1")],
    )
    assert accepted["status"] == "DRAFT"


def test_applying_at_exactly_window_end_fails_the_half_open_window(client):
    """The window is half-open: at window_end exactly, the filing fails.

    "A benefit counselor files an application with a `campaign_id`, an
    `employee_id`, a `policy_series_id`, and an optional `premium_mode` of
    `PRE_TAX` or `POST_TAX` (default `POST_TAX`); the campaign must be `OPEN` and
    the clock within its window, otherwise the filing fails with
    `ERR_WINDOW_EXPIRED` or `ERR_INVALID_STATE` as appropriate."

    Design: Corner/endpoints/policy_application_outside_window_rejected
    """
    base = fixtures.setup_open_campaign(
        client,
        campaign_overrides={
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-05T00:00:00Z",
        },
    )
    employee = fixtures.create_employee(client, base.group["id"])
    fixtures.set_clock(client, "2026-09-05T00:00:00Z")

    response = client.create_policy(
        {
            "campaign_id": base.campaign["id"],
            "employee_id": employee["id"],
            "policy_series_id": base.series["id"],
        },
        make_counselor_headers(base.counselor["id"]),
    )

    validate_error(response, api_errors.ERR_WINDOW_EXPIRED, 422)
    policies = validate_success(
        client.list_campaign_policies(base.campaign["id"], make_carrier_admin_headers()),
        200,
    )
    assert policies == [], "no policy row was created; got %r" % policies


def test_a_second_application_blocks_issuance_with_duplicate_coverage(client):
    """Two APPLIED policies for the same employee+series: issuing either fails.

    "Issuance (`APPLIED` → `ISSUED`) happens either in bulk at a `MET` campaign
    close or individually through direct issuance, and the preconditions are
    identical either way: the series must be `ACTIVE` at issuance time
    (`ERR_SERIES_RETIRED`), the series must have a `PUBLISHED` schedule
    (`ERR_SERIES_WITHOUT_SCHEDULE`), and no other policy for the same
    `employee_id` and `policy_series_id` may exist in any of `APPLIED`, `ISSUED`,
    `ACTIVE`, `LAPSED`, or `PORTED` status (`ERR_DUPLICATE_COVERAGE`)."

    Design: Corner/endpoints/duplicate_coverage_same_employee_same_series_rejected
    """
    base = fixtures.setup_open_campaign(client)
    employee = fixtures.create_employee(client, base.group["id"])
    first = fixtures.apply_policy(
        client, base.campaign["id"], employee["id"], base.series["id"], base.counselor
    )
    fixtures.apply_policy(
        client, base.campaign["id"], employee["id"], base.series["id"], base.counselor
    )

    response = client.issue_policy(
        first["id"], make_counselor_headers(base.counselor["id"])
    )

    validate_error(response, api_errors.ERR_DUPLICATE_COVERAGE, 409)
    policy = fixtures.read_policy(client, first["id"])
    assert policy["status"] == "APPLIED"


def test_claims_listing_filters_by_policy_and_status(client):
    """policy_id + status=PAID returns only that policy's paid claims.

    "Paginated list responses include the following fields in the `meta` object of
    the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/claims_list_filtered_by_policy_and_status
    """
    base = fixtures.setup_open_campaign(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="J2",
                benefit_amount_cents=700,
                max_occurrences_per_year=5,
                lifetime_max_cents=50000,
            )
        ],
    )
    employees = [fixtures.create_employee(client, base.group["id"]) for _ in range(2)]
    policies = []
    for employee in employees:
        policy = fixtures.apply_policy(
            client, base.campaign["id"], employee["id"], base.series["id"], base.counselor
        )
        issued = fixtures.issue_policy(client, policy["id"], base.counselor)
        # Claims are reviewable only on ACTIVE/LAPSED/PORTED policies.
        policies.append(fixtures.activate_policy(client, issued["id"], base.counselor))

    # Policy 1: one SUBMITTED, one PAID, one DENIED. Policy 2: one PAID.
    fixtures.submit_claim(
        client, policies[0]["id"], "J2",
        service_date="2026-09-03T00:00:00Z", diagnosis_code="D-J",
        claimed_occurrences=1,
    )
    paid = fixtures.submit_claim(
        client, policies[0]["id"], "J2",
        service_date="2026-09-04T00:00:00Z", diagnosis_code="D-J",
        claimed_occurrences=1,
    )
    fixtures.pay_claim_full_cycle(client, paid["id"])
    denied = fixtures.submit_claim(
        client, policies[0]["id"], "J2",
        service_date="2026-09-05T00:00:00Z", diagnosis_code="D-J",
        claimed_occurrences=1,
    )
    fixtures.review_claim(client, denied["id"])
    fixtures.adjudicate_claim(client, denied["id"], "DENY")
    other = fixtures.submit_claim(
        client, policies[1]["id"], "J2",
        service_date="2026-09-06T00:00:00Z", diagnosis_code="D-J",
        claimed_occurrences=1,
    )
    fixtures.pay_claim_full_cycle(client, other["id"])

    rows, meta = validate_paginated(
        client.list_claims(
            make_claims_adjuster_headers(),
            filters={"policy_id": policies[0]["id"], "status": "PAID"},
        )
    )

    assert len(rows) == 1
    assert rows[0]["id"] == paid["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
