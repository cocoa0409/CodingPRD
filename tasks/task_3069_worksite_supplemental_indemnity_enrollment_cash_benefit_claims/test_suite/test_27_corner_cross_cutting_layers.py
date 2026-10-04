"""Corner probes over the optimistic concurrency rules, derived read-time
counters, and immediate finalize consistency."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import (
    make_carrier_admin_headers,
    make_counselor_headers,
    make_group_admin_headers,
    make_policyholder_services_headers,
)


def test_a_stale_series_version_rejects_a_second_publish(client):
    """The publish that follows another writer's publish must re-observe.

    "Publishing a benefit schedule requires the request body to carry
    `expected_series_version`, the `version` of the parent policy series as the
    client last observed it. Because a successful publish itself supersedes the
    previously published schedule and advances the series' `version` by 1, a
    publish attempted against a stale series view — for instance, after another
    writer has published a different schedule of the same series — is rejected
    with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_layers/occ_stale_series_version_on_publish_rejected_412
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    series = fixtures.create_series(client)
    schedule_one = fixtures.create_schedule(
        client, series["id"],
        schedule_version=1,
        benefit_items=[benefit_item_payload(event_code="Q2")],
    )
    schedule_two = fixtures.create_schedule(
        client, series["id"],
        schedule_version=2,
        effective_date="2026-06-01T00:00:00Z",
        benefit_items=[benefit_item_payload(event_code="Q2")],
    )
    stale_version = series["version"]

    first = validate_success(
        client.publish_benefit_schedule(
            schedule_one["id"], {"expected_series_version": stale_version},
            make_carrier_admin_headers(),
        ),
        200,
    )
    assert first["status"] == "PUBLISHED"

    stale = client.publish_benefit_schedule(
        schedule_two["id"], {"expected_series_version": stale_version},
        make_carrier_admin_headers(),
    )
    validate_error(stale, api_errors.ERR_STALE_VERSION, 412)

    current_version = validate_success(
        client.get_policy_series(series["id"], make_carrier_admin_headers()), 200
    )["version"]
    second = validate_success(
        client.publish_benefit_schedule(
            schedule_two["id"], {"expected_series_version": current_version},
            make_carrier_admin_headers(),
        ),
        200,
    )
    assert second["status"] == "PUBLISHED"
    superseded = validate_success(
        client.get_benefit_schedule(schedule_one["id"], make_carrier_admin_headers()), 200
    )
    assert superseded["status"] == "SUPERSEDED"


def test_a_stale_group_version_rejects_a_campaign_close(client):
    """Suspend+reactivate bumps the group version past the client's observation.

    "Closing an enrollment campaign requires the request body to carry
    `expected_group_version`, the `version` of the campaign's employer group as
    the client last observed it. Bulk issuance at close mutates the group-visible
    enrolled population, so a close issued against a stale group view is rejected
    with `ERR_STALE_VERSION` rather than applied."

    Design: Corner/cross_cutting_layers/occ_stale_group_version_on_campaign_close_rejected_412
    """
    base = fixtures.setup_open_campaign(
        client,
        campaign_overrides={
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-10T00:00:00Z",
        },
    )
    fixtures.set_clock(client, "2026-09-10T00:00:00Z")
    fixtures.lock_campaign(client, base.campaign["id"], base.counselor)
    observed_version = fixtures.group_version(client, base.group["id"])
    validate_success(
        client.suspend_employer_group(base.group["id"], make_carrier_admin_headers()), 200
    )
    validate_success(
        client.activate_employer_group(base.group["id"], make_carrier_admin_headers()), 200
    )

    response = client.close_enrollment_campaign(
        base.campaign["id"],
        {"expected_group_version": observed_version},
        make_counselor_headers(base.counselor["id"]),
    )

    validate_error(response, api_errors.ERR_STALE_VERSION, 412)
    campaign = validate_success(
        client.get_enrollment_campaign(base.campaign["id"], make_carrier_admin_headers()), 200
    )
    assert campaign["status"] == "LOCKED"


def test_group_counters_reconcile_immediately_with_membership_changes(client):
    """Terminating an employee drops eligible count; porting their policy drops
    enrolled count, both visible on the very next read.

    "Two counters are always derivable at read time: `eligible_employee_count`
    counts the group's employees whose status is `ACTIVE` at read time, and
    `enrolled_count` counts policies filed under campaigns of this group whose
    status is one of `APPLIED`, `ISSUED`, `ACTIVE`, `LAPSED`, or `PORTED` —
    declined and cancelled policies do not count."
    "A ported policy drops out of the group's `enrolled_count` and must never be
    billed by the group's future payroll cycles — its `coverage_days` in any such
    cycle is zero."

    Design: Corner/cross_cutting_layers/derived_group_counters_reconcile_with_membership_changes
    """
    base = fixtures.setup_open_campaign(client)
    employees = [fixtures.create_employee(client, base.group["id"]) for _ in range(2)]
    policies = []
    for employee in employees:
        policy = fixtures.apply_policy(
            client, base.campaign["id"], employee["id"], base.series["id"], base.counselor
        )
        policies.append(fixtures.issue_policy(client, policy["id"], base.counselor))

    before = fixtures.read_group(client, base.group["id"])
    assert before["eligible_employee_count"] == 2
    assert before["enrolled_count"] == 2

    validate_success(
        client.terminate_employee(employees[0]["id"], make_group_admin_headers()), 200
    )
    validate_success(
        client.port_policy(
            policies[0]["id"], {"new_premium_mode": "POST_TAX"},
            make_policyholder_services_headers(),
        ),
        200,
    )

    after = fixtures.read_group(client, base.group["id"])
    assert after["eligible_employee_count"] == 1
    assert after["enrolled_count"] == 1


def test_finalize_reflects_its_lines_and_total_in_the_same_read(client):
    """LAPSED policies bill zero days and get no line; the ISSUED one bills fully.

    "At the finalize instant, the system examines every policy of the group's
    employees: those in `ISSUED` or `ACTIVE` status at that instant are billable,
    while `LAPSED`, `PORTED`, `DECLINED`, `CANCELLED`, and `APPLIED` policies are
    excluded entirely. Billability is all-or-nothing per cycle — the policy's
    status at the finalize instant decides the whole period, with no mid-period
    proration of status changes: a policy billable at finalize bills the full
    period's `coverage_days`, which is the number of whole days in the half-open
    period (end excluded); a non-billable policy contributes zero days."

    Design: Corner/cross_cutting_layers/finalize_synthesizes_lines_and_total_immediately
    """
    base = fixtures.setup_open_campaign(
        client,
        group_overrides={"proration_convention": "DAILY"},
        schedule_overrides={"monthly_premium_cents": 4500},
        benefit_items=[
            benefit_item_payload(
                event_code="T3",
                benefit_amount_cents=100,
                max_occurrences_per_year=1,
                lifetime_max_cents=1000,
            )
        ],
    )
    billable_employee = fixtures.create_employee(client, base.group["id"])
    billable = fixtures.apply_policy(
        client, base.campaign["id"], billable_employee["id"], base.series["id"], base.counselor
    )
    fixtures.issue_policy(client, billable["id"], base.counselor)
    lapsed_employee = fixtures.create_employee(client, base.group["id"])
    lapsed = fixtures.apply_policy(
        client, base.campaign["id"], lapsed_employee["id"], base.series["id"], base.counselor
    )
    fixtures.issue_policy(client, lapsed["id"], base.counselor)
    fixtures.lapse_policy(client, lapsed["id"], base.counselor)
    cycle = fixtures.create_payroll_cycle(client, base.group["id"])

    finalized = validate_success(
        client.finalize_payroll_cycle(cycle["id"], make_group_admin_headers()), 200
    )
    lines = validate_success(
        client.list_cycle_deduction_lines(cycle["id"], make_group_admin_headers()), 200
    )

    assert len(lines) == 1, "the lapsed policy contributes no line; got %d" % len(lines)
    line = lines[0]
    assert line["amount_cents"] == 4500
    assert line["coverage_days"] == 30
    assert line["tax_treatment"] == "POST_TAX"
    assert line["status"] == "POSTED"
    assert finalized["status"] == "FINALIZED"
    assert finalized["total_posted_cents"] == 4500
