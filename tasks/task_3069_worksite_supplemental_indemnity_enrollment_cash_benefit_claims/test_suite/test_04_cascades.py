"""Multi-hop cascades: campaign close bulk issuance and group termination."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import make_carrier_admin_headers


def _locked_campaign_with_two_applications(client):
    """A group with minimum_count=1, an OPEN campaign carrying two APPLIED
    policies, locked once the window has closed."""
    base = fixtures.setup_open_campaign(
        client,
        group_overrides={
            "participation_minimum_count": 1,
            "participation_minimum_pct": 0.0,
        },
        campaign_overrides={
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-20T00:00:00Z",
        },
        schedule_overrides={"monthly_premium_cents": 2500},
        benefit_items=[
            benefit_item_payload(
                event_code="Z",
                benefit_amount_cents=700,
                max_occurrences_per_year=1,
                lifetime_max_cents=70000,
            )
        ],
    )
    employees = [fixtures.create_employee(client, base.group["id"]) for _ in range(2)]
    policies = [
        fixtures.apply_policy(
            client, base.campaign["id"], employee["id"], base.series["id"],
            base.counselor,
        )
        for employee in employees
    ]
    versions_at_apply = [policy["version"] for policy in policies]
    fixtures.set_clock(client, "2026-09-20T00:00:00Z")
    fixtures.lock_campaign(client, base.campaign["id"], base.counselor)
    base.employees = employees
    base.policies = policies
    base.versions_at_apply = versions_at_apply
    return base


def test_met_close_bulk_issues_every_applied_policy(client):
    """The close verdict itself issues both applications under a MET campaign.

    "If the group's `enrolled_count` at that instant is at least
    `required_enrollments` — exactly at the threshold counts, the comparison is
    inclusive — the campaign transitions `LOCKED` → `MET`, records
    `participation_met` as true, and bulk-issues every `APPLIED` policy under it
    (see §3.3 for what issuance pins)."

    Design: Difficulty/transitive_cascade/campaign_close_met_bulk_issuance_chain
    """
    base = _locked_campaign_with_two_applications(client)

    closed = fixtures.close_campaign(
        client, base.campaign["id"], base.group["id"], base.counselor
    )
    assert closed["status"] == "MET"
    assert closed["participation_met"] is True
    assert closed["required_enrollments"] == 1

    for applied, version_at_apply in zip(base.policies, base.versions_at_apply):
        policy = fixtures.read_policy(client, applied["id"])
        assert policy["status"] == "ISSUED"
        assert policy["benefit_schedule_id"] == base.schedule["id"]
        assert policy["monthly_premium_cents"] == 2500
        assert policy["version"] > version_at_apply, (
            "the mutation is caused by the campaign close, not a direct policy call"
        )


def test_bulk_issuance_pins_coverage_start_to_the_first_of_the_issue_month(client):
    """Issued through a close, policies anchor coverage at the issue month's start.

    "A successful issuance pins the version snapshot of §2.6:
    `benefit_schedule_id` is set to the series' `current_schedule_id` and never
    changes afterwards, `monthly_premium_cents` is copied from the pinned schedule
    and is likewise immune to later schedule publishes, `issue_date` is set to the
    current clock time, `coverage_start_date` is set to the first day of the
    calendar month containing the issue date at 00:00:00Z, and a
    `certificate_number` is minted from the series code followed by a dash and an
    eight-character deterministic sequence unique within the series."

    Design: Difficulty/transitive_cascade/campaign_close_met_bulk_issuance_chain
    """
    base = _locked_campaign_with_two_applications(client)

    fixtures.close_campaign(client, base.campaign["id"], base.group["id"], base.counselor)

    for applied in base.policies:
        policy = fixtures.read_policy(client, applied["id"])
        # PRD pins the instant (the current clock time) but not its string
        # rendering; assert the semantic value, not the exact format.
        assert policy["issue_date"][:19] == "2026-09-20T00:00:00"
        assert policy["issue_date"].endswith("Z")
        assert policy["coverage_start_date"][:19] == "2026-09-01T00:00:00"
        assert policy["coverage_start_date"].endswith("Z")


def _group_with_locked_campaign(client):
    """Group with one ISSUED+ACTIVE policy, one LOCKED campaign whose remaining
    APPLIED policy never issued, ready for a group termination."""
    base = fixtures.setup_open_campaign(
        client,
        campaign_overrides={
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-30T00:00:00Z",
        },
        schedule_overrides={"monthly_premium_cents": 2000},
        benefit_items=[
            benefit_item_payload(
                event_code="Y",
                benefit_amount_cents=900,
                max_occurrences_per_year=1,
                lifetime_max_cents=90000,
            )
        ],
    )
    employee_old = fixtures.create_employee(client, base.group["id"])
    employee_new = fixtures.create_employee(client, base.group["id"])
    issued = fixtures.apply_policy(
        client, base.campaign["id"], employee_old["id"], base.series["id"],
        base.counselor,
    )
    fixtures.issue_policy(client, issued["id"], base.counselor)
    issued = fixtures.activate_policy(client, issued["id"], base.counselor)
    pending = fixtures.apply_policy(
        client, base.campaign["id"], employee_new["id"], base.series["id"],
        base.counselor,
    )
    fixtures.set_clock(client, "2026-09-30T00:00:00Z")
    fixtures.lock_campaign(client, base.campaign["id"], base.counselor)
    base.issued_policy = issued
    base.pending_policy = pending
    return base


def test_group_termination_cascades_to_policies_and_campaigns(client):
    """One terminate lapses issued coverage and closes the locked campaign.

    "Either way, termination (`→ TERMINATED`) fires a cascade in the same
    transaction: every policy of the group's employees in `ISSUED` or `ACTIVE`
    status lapses to `LAPSED`; every campaign of the group in `DRAFT`, `LOCKED`,
    `MET`, or `FAILED` closes to `CLOSED`; and when the forced closure sweeps up a
    `LOCKED` campaign, that closure itself declines every `APPLIED` policy under
    it — a three-hop chain from group to campaign to policies."

    Design: Difficulty/transitive_cascade/group_terminate_forced_campaign_close_declines_applied_policies
    """
    base = _group_with_locked_campaign(client)

    terminated = validate_success(
        client.terminate_employer_group(base.group["id"], make_carrier_admin_headers()),
        200,
    )
    assert terminated["status"] == "TERMINATED"

    issued = fixtures.read_policy(client, base.issued_policy["id"])
    assert issued["status"] == "LAPSED", (
        "hop 1: issued/active policies lapse; got %r" % issued.get("status")
    )
    campaign = validate_success(
        client.get_enrollment_campaign(base.campaign["id"], make_carrier_admin_headers()),
        200,
    )
    assert campaign["status"] == "CLOSED", (
        "hop 2: the locked campaign is force-closed; got %r" % campaign.get("status")
    )
    pending = fixtures.read_policy(client, base.pending_policy["id"])
    assert pending["status"] == "DECLINED", (
        "hop 3: the forced closure declines its applied policies; got %r"
        % pending.get("status")
    )


def test_the_forced_closure_declines_applied_policies_without_issuing_them(client):
    """The in-flight application is declined, never issued, by the cascade.

    "applications are also declined by the system itself when a campaign closes
    `FAILED`, when the non-guaranteed-issue pre-existing screen trips, or when
    issuance finds no published schedule."

    Design: Difficulty/transitive_cascade/group_terminate_forced_campaign_close_declines_applied_policies
    """
    base = _group_with_locked_campaign(client)

    validate_success(
        client.terminate_employer_group(base.group["id"], make_carrier_admin_headers()),
        200,
    )

    pending = fixtures.read_policy(client, base.pending_policy["id"])
    assert pending["status"] == "DECLINED"
    assert pending["benefit_schedule_id"] is None, (
        "a declined application never pins a schedule; got %r"
        % pending.get("benefit_schedule_id")
    )
    issued = fixtures.read_policy(client, base.issued_policy["id"])
    assert issued["status"] == "LAPSED"
