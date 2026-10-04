"""Corner probes over role exclusivity in both directions."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.test_users import (
    make_carrier_admin_headers,
    make_claims_adjuster_headers,
    make_counselor_headers,
    make_group_admin_headers,
)


def test_a_counselor_cannot_publish_schedules_or_terminate_groups(client):
    """Carrier-side operations refuse a counselor even one that runs campaigns.

    "A request missing either header, or carrying a role the system does not
    declare, is rejected with `ERR_UNAUTHENTICATED`. When a properly identified
    caller attempts an operation outside their role's authorized set, the request
    is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/counselor_cannot_publish_schedules_or_terminate_groups
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    group = fixtures.create_active_group(client)
    counselor = fixtures.create_counselor(client)
    series = fixtures.create_series(client)
    schedule = fixtures.create_schedule(client, series["id"])
    counselor_headers = make_counselor_headers(counselor["id"])

    publish_response = client.publish_benefit_schedule(
        schedule["id"],
        {"expected_series_version": series["version"]},
        counselor_headers,
    )
    terminate_response = client.terminate_employer_group(group["id"], counselor_headers)

    validate_error(publish_response, api_errors.ERR_UNAUTHORIZED, 403)
    validate_error(terminate_response, api_errors.ERR_UNAUTHORIZED, 403)
    schedule_after = validate_success(
        client.get_benefit_schedule(schedule["id"], make_carrier_admin_headers()), 200
    )
    assert schedule_after["status"] == "DRAFT"
    group_after = fixtures.read_group(client, group["id"])
    assert group_after["status"] == "ACTIVE"


def test_role_isolation_runs_both_ways_between_group_admin_and_adjuster(client):
    """ClaimsAdjuster cannot finalize payroll; GroupAdmin cannot review claims.

    "When a properly identified caller attempts an operation outside their role's
    authorized set, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/group_admin_cannot_adjudicate_and_adjuster_cannot_finalize_payroll
    """
    base = fixtures.setup_issued_policy(client)
    claim = fixtures.submit_claim(
        client, base.policy["id"], base.schedule["benefit_items"][0]["event_code"],
        service_date="2026-09-03T00:00:00Z", diagnosis_code="D-P",
        claimed_occurrences=1,
    )
    cycle = fixtures.create_payroll_cycle(client, base.group["id"])

    finalize_response = client.finalize_payroll_cycle(
        cycle["id"], make_claims_adjuster_headers()
    )
    review_response = client.review_claim(claim["id"], make_group_admin_headers())

    validate_error(finalize_response, api_errors.ERR_UNAUTHORIZED, 403)
    validate_error(review_response, api_errors.ERR_UNAUTHORIZED, 403)
    cycle_after = validate_success(
        client.get_payroll_cycle(cycle["id"], make_group_admin_headers()), 200
    )
    assert cycle_after["status"] == "OPEN"
    claim_after = fixtures.read_claim(client, claim["id"])
    assert claim_after["status"] == "SUBMITTED"
