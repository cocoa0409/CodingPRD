"""Cyclic state machines: the claim appeal loop and the campaign fail/reopen loop."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import (
    make_counselor_headers,
    make_policyholder_services_headers,
)


def _denied_claim(client):
    """A documented claim, manually denied, with the clock inside the appeal window."""
    base = fixtures.setup_active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="BROKEN_BONE",
                benefit_amount_cents=15000,
                max_occurrences_per_year=2,
                lifetime_max_cents=500000,
            )
        ],
    )
    claim = fixtures.submit_claim(
        client, base.policy["id"], "BROKEN_BONE",
        service_date="2026-09-03T00:00:00Z", diagnosis_code="S52.501A",
        claimed_occurrences=1,
    )
    fixtures.review_claim(client, claim["id"])
    fixtures.adjudicate_claim(client, claim["id"], "DENY")
    return base, claim


def test_appeal_restarts_review_and_recomputes_the_provisional_estimate(client):
    """The second pass through review recomputes the estimate from scratch.

    "An appealed claim re-enters review (`APPEALED` → `UNDER_REVIEW`), which
    recomputes the provisional estimate and restarts adjudication — the loop from
    review to denial to appeal and back to review can repeat."

    Design: Difficulty/non_linear_state_machine/claim_appeal_cycle_under_review_denied_appealed_under_review
    """
    base, claim = _denied_claim(client)
    denied = fixtures.read_claim(client, claim["id"])
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "NOT_COVERED", (
        "an explicit DENY records NOT_COVERED; got %r" % denied.get("denial_reason")
    )

    fixtures.set_clock(client, "2026-09-10T00:00:00Z")
    appealed = validate_success(
        client.appeal_claim(claim["id"], make_policyholder_services_headers()),
        200,
    )
    assert appealed["status"] == "APPEALED"

    re_reviewed = fixtures.review_claim(client, claim["id"])
    assert re_reviewed["status"] == "UNDER_REVIEW"
    assert re_reviewed["provisional_payable_cents"] == 15000, (
        "the second pass recomputes the estimate; got %r"
        % re_reviewed.get("provisional_payable_cents")
    )
    assert re_reviewed["denial_reason"] == "NOT_COVERED", (
        "the denial reason is retained until superseded; got %r"
        % re_reviewed.get("denial_reason")
    )


def test_reappealed_claim_approves_once_documented(client):
    """The loop resolves to a normal approval once documentation is complete.

    "Otherwise the approval stands as a partial-or-full credit: the final variant
    of the payable calculation above determines `payable_amount_cents` and
    `adjudicated_occurrences` — both null until this moment — and the claim moves
    to `APPROVED`."

    Design: Difficulty/non_linear_state_machine/claim_appeal_cycle_under_review_denied_appealed_under_review
    """
    base, claim = _denied_claim(client)
    fixtures.set_clock(client, "2026-09-10T00:00:00Z")
    validate_success(
        client.appeal_claim(claim["id"], make_policyholder_services_headers()),
        200,
    )
    fixtures.review_claim(client, claim["id"])

    approved = fixtures.approve_claim_with_document(client, claim["id"])
    assert approved["status"] == "APPROVED"
    assert approved["payable_amount_cents"] == 15000
    assert approved["adjudicated_occurrences"] == 1


def _failed_then_reopened_campaign(client):
    """A campaign that fails once with zero applications, is reopened with an
    extended window, gains one application, and is locked a second time."""
    base = fixtures.setup_open_campaign(
        client,
        group_overrides={
            "participation_minimum_count": 1,
            "participation_minimum_pct": 0.0,
        },
        campaign_overrides={
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-15T00:00:00Z",
        },
        schedule_overrides={"monthly_premium_cents": 2000},
        benefit_items=[
            benefit_item_payload(
                event_code="X",
                benefit_amount_cents=1000,
                max_occurrences_per_year=1,
                lifetime_max_cents=100000,
            )
        ],
    )
    fixtures.set_clock(client, "2026-09-15T00:00:00Z")
    fixtures.lock_campaign(client, base.campaign["id"], base.counselor)
    first_close = fixtures.close_campaign(
        client, base.campaign["id"], base.group["id"], base.counselor
    )

    reopened = validate_success(
        client.reopen_enrollment_campaign(
            base.campaign["id"],
            {"new_window_end": "2026-10-01T00:00:00Z"},
            make_counselor_headers(base.counselor["id"]),
        ),
        200,
    )
    employee = fixtures.create_employee(client, base.group["id"])
    policy = fixtures.apply_policy(
        client, base.campaign["id"], employee["id"], base.series["id"], base.counselor
    )
    fixtures.set_clock(client, "2026-10-01T00:00:00Z")
    fixtures.lock_campaign(client, base.campaign["id"], base.counselor)
    base.first_close = first_close
    base.reopened = reopened
    base.policy = policy
    return base


def test_failed_campaign_reopens_and_resets_its_verdict_fields(client):
    """Reopen writes the new window end and clears both participation fields.

    "Reopening writes the new `window_end`, resets `participation_met` and
    `required_enrollments` to null, and reverses the earlier verdict on the
    applications: every policy under the campaign in `DECLINED` status returns to
    `APPLIED`."

    Design: Difficulty/non_linear_state_machine/campaign_failed_reopen_open_close_cycle
    """
    base = _failed_then_reopened_campaign(client)

    assert base.first_close["status"] == "FAILED"
    assert base.first_close["participation_met"] is False
    assert base.first_close["required_enrollments"] == 1

    assert base.reopened["status"] == "OPEN"
    # PRD pins the written instant (the new window_end) but not its string
    # rendering; assert the semantic value, not the exact format.
    assert base.reopened["window_end"][:19] == "2026-10-01T00:00:00"
    assert base.reopened["window_end"].endswith("Z")
    assert base.reopened["participation_met"] is None
    assert base.reopened["required_enrollments"] is None


def test_second_close_bulk_issues_the_reinstated_application(client):
    """The second pass through lock/close lands MET and issues the application.

    "The campaign can then run the cycle again — lock, close, verdict — as many
    times as the business allows."

    Design: Difficulty/non_linear_state_machine/campaign_failed_reopen_open_close_cycle
    """
    base = _failed_then_reopened_campaign(client)

    second_close = fixtures.close_campaign(
        client, base.campaign["id"], base.group["id"], base.counselor
    )
    assert second_close["status"] == "MET"
    assert second_close["participation_met"] is True
    assert second_close["required_enrollments"] == 1, (
        "required = max(1, ceil(0.0*1)) = 1; got %r"
        % second_close.get("required_enrollments")
    )

    policy = fixtures.read_policy(client, base.policy["id"])
    assert policy["status"] == "ISSUED"
    assert policy["benefit_schedule_id"] == base.schedule["id"]
    assert policy["monthly_premium_cents"] == 2000
