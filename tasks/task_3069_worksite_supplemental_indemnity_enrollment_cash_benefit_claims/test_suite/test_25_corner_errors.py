"""Corner probes over error triggers: wellness duplicates, the waiting period, the
appeal window, and claims-in-flight on cancel."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import (
    make_claims_adjuster_headers,
    make_policyholder_services_headers,
)


def _wellness_ready_policy(client, wellness_benefit_cents=2500, wellness_waiting_months=0):
    base = fixtures.setup_active_policy(
        client,
        schedule_overrides={
            "wellness_benefit_cents": wellness_benefit_cents,
            "wellness_waiting_months": wellness_waiting_months,
        },
        benefit_items=[
            benefit_item_payload(
                event_code="K2",
                benefit_amount_cents=100,
                max_occurrences_per_year=1,
                lifetime_max_cents=1000,
            )
        ],
    )
    return base


def test_a_second_wellness_claim_in_the_same_year_is_a_duplicate(client):
    """Approving the first wellness claim blocks the second for that year.

    "Approval (`SUBMITTED` → `APPROVED`) enforces four gates: the policy must be
    in `ACTIVE`, `LAPSED`, or `PORTED` (`ERR_POLICY_INACTIVE`); the `service_date`
    must be on or after the policy's `coverage_start_date` plus the pinned
    schedule's `wellness_waiting_months` whole months
    (`ERR_WELLNESS_WAITING_PERIOD`); the calendar year of the `service_date` must
    equal the claimed `calendar_year` (`ERR_INVALID_REQUEST`); and no other
    wellness benefit of the same policy may exist for the same `calendar_year` in
    `SUBMITTED`, `APPROVED`, or `PAID` status — denied rows do not block a
    refiling — else `ERR_WELLNESS_DUPLICATE_YEAR`."

    Design: Corner/errors/wellness_duplicate_year_blocked_but_denied_resubmission_allowed
    """
    base = _wellness_ready_policy(client)
    first = fixtures.submit_wellness(
        client, base.policy["id"], calendar_year=2026,
        service_date="2026-09-10T00:00:00Z",
    )

    approved = validate_success(
        client.approve_wellness_benefit(first["id"], make_claims_adjuster_headers()), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["amount_cents"] == 2500

    # File the second only after the first is APPROVED: a pending same-year row
    # would already block the first approval under the duplicate-year gate.
    second = fixtures.submit_wellness(
        client, base.policy["id"], calendar_year=2026,
        service_date="2026-09-11T00:00:00Z",
    )
    response = client.approve_wellness_benefit(second["id"], make_claims_adjuster_headers())
    validate_error(response, api_errors.ERR_WELLNESS_DUPLICATE_YEAR, 422)

    denied = validate_success(
        client.deny_wellness_benefit(second["id"], make_claims_adjuster_headers()), 200
    )
    assert denied["status"] == "DENIED"


def test_the_waiting_period_boundary_is_inclusive_at_the_month_mark(client):
    """Service before coverage_start + waiting months fails; exactly at it passes.

    "Approval (`SUBMITTED` → `APPROVED`) enforces four gates: the policy must be
    in `ACTIVE`, `LAPSED`, or `PORTED` (`ERR_POLICY_INACTIVE`); the `service_date`
    must be on or after the policy's `coverage_start_date` plus the pinned
    schedule's `wellness_waiting_months` whole months
    (`ERR_WELLNESS_WAITING_PERIOD`); the calendar year of the `service_date` must
    equal the claimed `calendar_year` (`ERR_INVALID_REQUEST`); and no other
    wellness benefit of the same policy may exist for the same `calendar_year` in
    `SUBMITTED`, `APPROVED`, or `PAID` status — denied rows do not block a
    refiling — else `ERR_WELLNESS_DUPLICATE_YEAR`."

    Design: Corner/errors/wellness_waiting_period_enforced_against_pinned_schedule
    """
    base = _wellness_ready_policy(client, wellness_benefit_cents=1500, wellness_waiting_months=3)
    early = fixtures.submit_wellness(
        client, base.policy["id"], calendar_year=2026,
        service_date="2026-11-15T00:00:00Z",
    )
    boundary = fixtures.submit_wellness(
        client, base.policy["id"], calendar_year=2026,
        service_date="2026-12-01T00:00:00Z",
    )

    early_response = client.approve_wellness_benefit(early["id"], make_claims_adjuster_headers())
    validate_error(early_response, api_errors.ERR_WELLNESS_WAITING_PERIOD, 422)

    # Denied rows do not block a refiling, so resolve the early row before the
    # boundary row is approved (a still-pending sibling would trip the
    # duplicate-year gate instead).
    denied_early = validate_success(
        client.deny_wellness_benefit(early["id"], make_claims_adjuster_headers()), 200
    )
    assert denied_early["status"] == "DENIED"

    approved = validate_success(
        client.approve_wellness_benefit(boundary["id"], make_claims_adjuster_headers()), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["amount_cents"] == 1500


def _denied_claim_pair(client):
    """Two claims both denied at 2026-09-05 for the appeal-window probe."""
    base = fixtures.setup_active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="M2",
                benefit_amount_cents=900,
                max_occurrences_per_year=2,
                lifetime_max_cents=50000,
            )
        ],
    )
    claims = []
    for service_date in ("2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z"):
        claim = fixtures.submit_claim(
            client, base.policy["id"], "M2",
            service_date=service_date, diagnosis_code="D-M",
            claimed_occurrences=1,
        )
        fixtures.review_claim(client, claim["id"])
        claims.append(claim)
    fixtures.set_clock(client, "2026-09-05T00:00:00Z")
    for claim in claims:
        fixtures.adjudicate_claim(client, claim["id"], "DENY")
    return base, claims


def test_the_appeal_window_is_inclusive_at_one_hundred_eighty_days(client):
    """Appeal at exactly 180 days after denial succeeds; 181 days fails.

    "`PolicyholderServices` may appeal (`DENIED` → `APPEALED`) within 180 days of
    the denial measured against the current clock; a later appeal fails with
    `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Corner/errors/appeal_after_180_days_rejected
    """
    base, claims = _denied_claim_pair(client)

    fixtures.set_clock(client, "2027-03-04T00:00:00Z")
    appealed = validate_success(
        client.appeal_claim(claims[0]["id"], make_policyholder_services_headers()), 200
    )
    assert appealed["status"] == "APPEALED"

    fixtures.set_clock(client, "2027-03-05T00:00:00Z")
    response = client.appeal_claim(claims[1]["id"], make_policyholder_services_headers())
    validate_error(response, api_errors.ERR_APPEAL_WINDOW_EXPIRED, 422)
    reloaded = fixtures.read_claim(client, claims[1]["id"])
    assert reloaded["status"] == "DENIED"


def test_a_policy_with_a_claim_in_flight_cannot_be_cancelled(client):
    """A SUBMITTED claim blocks cancellation; once denied, cancel succeeds.

    "Cancellation is the terminal path for discontinued coverage, available from
    `LAPSED` or `PORTED` (`→ CANCELLED`). It is blocked while the policy has any
    claim in flight — that is, any claim in `SUBMITTED`, `UNDER_REVIEW`,
    `APPEALED`, or `APPROVED` status — with `ERR_CLAIMS_IN_FLIGHT`."

    Design: Corner/errors/policy_cancel_blocked_by_in_flight_claims
    """
    base = fixtures.setup_issued_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="N2",
                benefit_amount_cents=300,
                max_occurrences_per_year=2,
                lifetime_max_cents=50000,
            )
        ],
    )
    fixtures.lapse_policy(client, base.policy["id"], base.counselor)
    claim = fixtures.submit_claim(
        client, base.policy["id"], "N2",
        service_date="2026-09-03T00:00:00Z", diagnosis_code="D-N",
        claimed_occurrences=1,
    )

    blocked = client.cancel_policy(base.policy["id"], make_policyholder_services_headers())
    validate_error(blocked, api_errors.ERR_CLAIMS_IN_FLIGHT, 422)

    fixtures.review_claim(client, claim["id"])
    fixtures.adjudicate_claim(client, claim["id"], "DENY")

    cancelled = validate_success(
        client.cancel_policy(base.policy["id"], make_policyholder_services_headers()), 200
    )
    assert cancelled["status"] == "CANCELLED"
