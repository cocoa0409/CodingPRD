"""Corner probes over state machines: invalid transitions, terminal lockdown,
initial states, and the reinstatement boundary."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import (
    make_carrier_admin_headers,
    make_claims_adjuster_headers,
    make_counselor_headers,
    make_group_admin_headers,
)


def _active_policy(client, **kwargs):
    """An ACTIVE policy, the reviewable floor for claim scenarios."""
    return fixtures.setup_active_policy(client, **kwargs)


def _issued_policy(client, **kwargs):
    return fixtures.setup_issued_policy(client, **kwargs)


def test_issuing_an_already_issued_policy_is_an_invalid_state(client):
    """ISSUED has no self-loop back through issue; the second attempt fails.

    "Issuance (`APPLIED` → `ISSUED`) happens either in bulk at a `MET` campaign
    close or individually through direct issuance, and the preconditions are
    identical either way: the series must be `ACTIVE` at issuance time
    (`ERR_SERIES_RETIRED`), the series must have a `PUBLISHED` schedule
    (`ERR_SERIES_WITHOUT_SCHEDULE`), and no other policy for the same
    `employee_id` and `policy_series_id` may exist in any of `APPLIED`, `ISSUED`,
    `ACTIVE`, `LAPSED`, or `PORTED` status (`ERR_DUPLICATE_COVERAGE`)."

    Design: Corner/state_machines/policy_issue_from_issued_rejected_invalid_state
    """
    base = _issued_policy(client)

    response = client.issue_policy(
        base.policy["id"], make_counselor_headers(base.counselor["id"])
    )

    validate_error(response, api_errors.ERR_INVALID_STATE, 409)
    policy = fixtures.read_policy(client, base.policy["id"])
    assert policy["status"] == "ISSUED"
    assert policy["benefit_schedule_id"] == base.schedule["id"]


def test_paid_is_terminal_for_adjudication_and_repayment(client):
    """A PAID claim rejects a second adjudication and a second payment.

    "Payment (`APPROVED` → `PAID`) requires the policy to be in `ACTIVE`,
    `LAPSED`, or `PORTED` (`ERR_POLICY_INACTIVE`) and syncs the ledger of §2.7:
    the claim's `payable_amount_cents` is added to the policy's
    `lifetime_paid_cents`, and the `adjudicated_occurrences` are added to the
    policy's `paid_occurrences_by_year` entry for the service date's calendar year
    and event code. `PAID` is terminal — except for voiding."

    Design: Corner/state_machines/claim_terminal_paid_rejects_further_adjudication
    """
    base = _active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="T",
                benefit_amount_cents=2000,
                max_occurrences_per_year=5,
                lifetime_max_cents=500000,
            )
        ],
        schedule_overrides={"monthly_premium_cents": 1000},
    )
    claim = fixtures.submit_claim(
        client, base.policy["id"], "T",
        service_date="2026-09-03T00:00:00Z", diagnosis_code="D-T",
        claimed_occurrences=1,
    )
    fixtures.pay_claim_full_cycle(client, claim["id"])

    adjudicate_response = client.adjudicate_claim(
        claim["id"], {"decision": "DENY"}, make_claims_adjuster_headers()
    )
    pay_response = client.pay_claim(claim["id"], make_claims_adjuster_headers())

    validate_error(adjudicate_response, api_errors.ERR_INVALID_STATE, 409)
    validate_error(pay_response, api_errors.ERR_INVALID_STATE, 409)
    reloaded = fixtures.read_claim(client, claim["id"])
    assert reloaded["status"] == "PAID"
    policy = fixtures.read_policy(client, base.policy["id"])
    assert policy["lifetime_paid_cents"] == 2000


def test_a_new_claim_starts_submitted_with_all_decision_fields_null(client):
    """Submission lands SUBMITTED with provisional, payable, occurrences, and
    denial reason all null.

    "A claim is a demand for a fixed cash benefit tied to a covered event. Filing
    one — a shared capability of `PolicyholderServices` and `ClaimsAdjuster` —
    takes the `policy_id`, the `event_code`, the `service_date`, a
    `diagnosis_code` linking the event to the schedule, an optional
    `procedure_code` (default null), and a `claimed_occurrences` that must be at
    least 1. The claim starts in `SUBMITTED`."

    Design: Corner/state_machines/claim_initial_state_is_submitted
    """
    base = _issued_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="U",
                benefit_amount_cents=100,
                max_occurrences_per_year=1,
                lifetime_max_cents=1000,
            )
        ],
        schedule_overrides={"monthly_premium_cents": 100, "wellness_benefit_cents": 50},
    )

    claim = fixtures.submit_claim(
        client, base.policy["id"], "U",
        service_date="2026-09-05T00:00:00Z", diagnosis_code="D-U",
        claimed_occurrences=1,
    )

    assert claim["status"] == "SUBMITTED"
    assert claim["provisional_payable_cents"] is None
    assert claim["payable_amount_cents"] is None
    assert claim["adjudicated_occurrences"] is None
    assert claim["denial_reason"] is None


def test_reinstatement_at_exactly_sixty_days_succeeds_then_beyond_it_fails(client):
    """The 60-day reinstatement window is inclusive at exactly 60 days, and the
    61st day is rejected.

    "Reinstatement (`LAPSED` → `ACTIVE`) is the grace-period path: it requires the
    policy to have lapsed within the last 60 days measured against the current
    clock (`ERR_REINSTATEMENT_WINDOW_EXPIRED`), the employee to be `ACTIVE`
    (`ERR_EMPLOYEE_INACTIVE`), and the employer group to be `ACTIVE`
    (`ERR_GROUP_INACTIVE`)."

    Design: Corner/state_machines/policy_reinstate_after_60_days_rejected
    """
    base = _issued_policy(client)
    policy_id = base.policy["id"]
    counselor_headers = make_counselor_headers(base.counselor["id"])

    fixtures.lapse_policy(client, policy_id, base.counselor)
    fixtures.set_clock(client, "2026-10-31T00:00:00Z")
    reinstated = validate_success(client.reinstate_policy(policy_id, counselor_headers), 200)
    assert reinstated["status"] == "ACTIVE"

    fixtures.lapse_policy(client, policy_id, base.counselor)
    fixtures.set_clock(client, "2026-12-31T00:00:00Z")
    response = client.reinstate_policy(policy_id, counselor_headers)

    validate_error(response, api_errors.ERR_REINSTATEMENT_WINDOW_EXPIRED, 422)
    policy = fixtures.read_policy(client, policy_id)
    assert policy["status"] == "LAPSED"


def test_finalizing_an_already_finalized_cycle_synthesizes_nothing(client):
    """A second finalize is refused and no duplicate deduction lines appear.

    "Finalization (`OPEN` → `FINALIZED`) is where billing happens, and it requires
    the group to be `ACTIVE` or `SUSPENDED` (`ERR_GROUP_TERMINATED`)."

    Design: Corner/state_machines/payroll_cycle_finalize_from_finalized_rejected
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    group = fixtures.create_active_group(client)
    cycle = fixtures.create_payroll_cycle(client, group["id"])
    fixtures.finalize_payroll_cycle(client, cycle["id"])

    response = client.finalize_payroll_cycle(cycle["id"], make_group_admin_headers())

    validate_error(response, api_errors.ERR_INVALID_STATE, 409)
    lines = validate_success(
        client.list_cycle_deduction_lines(cycle["id"], make_group_admin_headers()), 200
    )
    assert lines == [], "no duplicate synthesis; got %d lines" % len(lines)
    reloaded = validate_success(
        client.get_payroll_cycle(cycle["id"], make_group_admin_headers()), 200
    )
    assert reloaded["total_posted_cents"] == 0


def test_a_closed_campaign_accepts_no_further_lifecycle_calls(client):
    """After MET -> CLOSED a third close is refused with ERR_INVALID_STATE.

    "Either terminal verdict can subsequently be finalized (`MET` → `CLOSED` or
    `FAILED` → `CLOSED`), and each close call increments the campaign's
    `version`."

    Design: Corner/state_machines/campaign_close_met_to_closed_terminal_then_no_further_close
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

    first = fixtures.close_campaign(
        client, base.campaign["id"], base.group["id"], base.counselor
    )
    assert first["status"] == "MET", (
        "required = max(0, ceil(0.0*0)) = 0 and enrolled 0 >= 0; got %r"
        % first.get("status")
    )
    assert first["required_enrollments"] == 0

    second = fixtures.close_campaign(
        client, base.campaign["id"], base.group["id"], base.counselor
    )
    assert second["status"] == "CLOSED"

    response = client.close_enrollment_campaign(
        base.campaign["id"],
        {"expected_group_version": fixtures.group_version(client, base.group["id"])},
        make_counselor_headers(base.counselor["id"]),
    )

    validate_error(response, api_errors.ERR_INVALID_STATE, 409)
    campaign = validate_success(
        client.get_enrollment_campaign(base.campaign["id"], make_carrier_admin_headers()),
        200,
    )
    assert campaign["status"] == "CLOSED"


def test_publishing_a_newer_schedule_supersedes_the_published_one_and_repoints(client):
    """The v2 publish supersedes v1 and repoints the series; the issued policy
    keeps its v1 pin and 1000 premium.

    "A successful publish supersedes: any other schedule of the same series
    currently `PUBLISHED` is auto-transitioned to `SUPERSEDED`, the series'
    `current_schedule_id` is repointed to the new schedule, and the series'
    `version` increments by 1."
    "Later publications of the same series supersede the old schedule for
    *future* issuances only; existing policies are never repointed."

    Design: Corner/state_machines/benefit_schedule_publish_supersedes_prior_published
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    series = fixtures.create_series(client)
    schedule_v1 = fixtures.create_schedule(
        client, series["id"],
        schedule_version=1,
        effective_date="2026-01-01T00:00:00Z",
        benefit_items=[benefit_item_payload(event_code="Z1", benefit_amount_cents=111,
                                            max_occurrences_per_year=1,
                                            lifetime_max_cents=10000)],
        monthly_premium_cents=1000,
        wellness_benefit_cents=100,
    )
    fixtures.publish_schedule(client, schedule_v1["id"], series["id"])
    fixtures.activate_series(client, series["id"])
    schedule_v2 = fixtures.create_schedule(
        client, series["id"],
        schedule_version=2,
        effective_date="2026-10-01T00:00:00Z",
        benefit_items=[benefit_item_payload(event_code="Z1", benefit_amount_cents=111,
                                            max_occurrences_per_year=1,
                                            lifetime_max_cents=10000)],
        monthly_premium_cents=1200,
        wellness_benefit_cents=100,
    )
    group = fixtures.create_active_group(client)
    counselor = fixtures.create_counselor(client)
    campaign = fixtures.create_campaign(client, group["id"], counselor)
    fixtures.open_campaign(client, campaign["id"], counselor)
    employee = fixtures.create_employee(client, group["id"])
    policy = fixtures.apply_policy(client, campaign["id"], employee["id"], series["id"], counselor)
    fixtures.issue_policy(client, policy["id"], counselor)

    fixtures.publish_schedule(client, schedule_v2["id"], series["id"])

    reloaded_v1 = validate_success(
        client.get_benefit_schedule(schedule_v1["id"], make_carrier_admin_headers()), 200
    )
    reloaded_v2 = validate_success(
        client.get_benefit_schedule(schedule_v2["id"], make_carrier_admin_headers()), 200
    )
    assert reloaded_v1["status"] == "SUPERSEDED"
    assert reloaded_v2["status"] == "PUBLISHED"
    series_now = validate_success(
        client.get_policy_series(series["id"], make_carrier_admin_headers()), 200
    )
    assert series_now["current_schedule_id"] == schedule_v2["id"]
    pinned = fixtures.read_policy(client, policy["id"])
    assert pinned["benefit_schedule_id"] == schedule_v1["id"]
    assert pinned["monthly_premium_cents"] == 1000


def test_suspending_a_group_locks_its_open_campaign_but_spares_drafts(client):
    """The suspend cascade hits only OPEN campaigns; DRAFT ones are untouched.

    "Suspension (`ACTIVE` → `SUSPENDED`) immediately locks every open campaign of
    the group: each `OPEN` campaign is auto-transitioned to `LOCKED`."

    Design: Corner/state_machines/campaign_suspend_locks_open_campaign_via_group_cascade
    """
    fixtures.set_clock(client, "2026-09-01T00:00:00Z")
    group = fixtures.create_active_group(client)
    counselor_open = fixtures.create_counselor(client)
    counselor_draft = fixtures.create_counselor(client)
    open_campaign = fixtures.create_campaign(
        client, group["id"], counselor_open,
        window_start="2026-09-01T00:00:00Z", window_end="2026-09-15T00:00:00Z",
    )
    fixtures.open_campaign(client, open_campaign["id"], counselor_open)
    draft_campaign = fixtures.create_campaign(
        client, group["id"], counselor_draft,
        window_start="2026-09-15T00:00:00Z", window_end="2026-10-01T00:00:00Z",
    )

    suspended = validate_success(
        client.suspend_employer_group(group["id"], make_carrier_admin_headers()), 200
    )

    assert suspended["status"] == "SUSPENDED"
    open_after = validate_success(
        client.get_enrollment_campaign(open_campaign["id"], make_carrier_admin_headers()), 200
    )
    draft_after = validate_success(
        client.get_enrollment_campaign(draft_campaign["id"], make_carrier_admin_headers()), 200
    )
    assert open_after["status"] == "LOCKED"
    assert draft_after["status"] == "DRAFT"
