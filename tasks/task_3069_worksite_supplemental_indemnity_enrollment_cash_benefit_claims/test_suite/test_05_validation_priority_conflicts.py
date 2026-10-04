"""Deliberately conflicting failures resolve in the PRD's named validation order."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import (
    make_carrier_admin_headers,
    make_claims_adjuster_headers,
    make_counselor_headers,
)


def _locked_campaign(client):
    """An OPEN campaign advanced to LOCKED once its window has passed."""
    base = fixtures.setup_open_campaign(
        client,
        campaign_overrides={
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-10T00:00:00Z",
        },
    )
    fixtures.set_clock(client, "2026-09-10T00:00:00Z")
    fixtures.lock_campaign(client, base.campaign["id"], base.counselor)
    return base


def test_opening_a_locked_campaign_is_an_invalid_state_error(client):
    """The state machine has no LOCKED -> OPEN edge, so state failure is reported.

    "Every request is validated in a fixed priority order, and the first failing
    check determines the error returned."
    "Only then does the system evaluate state-transition legality
    (`ERR_INVALID_STATE`), regulatory and safety gates such as counselor activity,
    the pre-existing exclusion, and the appeal and reinstatement windows,
    structural constraints such as window overlaps, double-booking, duplicate
    coverage, duplicate wellness years, and schedule-version monotonicity,
    temporal gates such as window expiry and waiting periods, fiscal capacity
    gates such as occurrence caps, lifetime maxima, and claims-in-flight, the
    optimistic concurrency check of §2.9, and finally request-body schema
    well-formedness (`ERR_INVALID_REQUEST`)."

    Design: Difficulty/priority_pair_validation_conflict/campaign_open_wrong_state_vs_counselor_inactive
    """
    base = _locked_campaign(client)

    response = client.open_enrollment_campaign(
        base.campaign["id"], make_counselor_headers(base.counselor["id"])
    )

    validate_error(response, api_errors.ERR_INVALID_STATE, 409)


def test_the_rejected_open_leaves_the_campaign_locked(client):
    """A refused open mutates nothing; the campaign stays LOCKED.

    "When the window has run its course, the counselor locks it (`OPEN` →
    `LOCKED`), which requires the current clock time to be at or after
    `window_end` — locking early fails with `ERR_WINDOW_NOT_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/campaign_open_wrong_state_vs_counselor_inactive
    """
    base = _locked_campaign(client)

    client.open_enrollment_campaign(
        base.campaign["id"], make_counselor_headers(base.counselor["id"])
    )

    campaign = validate_success(
        client.get_enrollment_campaign(base.campaign["id"], make_carrier_admin_headers()),
        200,
    )
    assert campaign["status"] == "LOCKED"


def _cap_exhausted_with_pending_document(client):
    """A claim under review with a RECEIVED document outstanding while the yearly
    occurrence cap for its event is already fully paid."""
    base = fixtures.setup_active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="FRACTURE",
                benefit_amount_cents=10000,
                max_occurrences_per_year=1,
                lifetime_max_cents=500000,
            )
        ],
    )
    first = fixtures.submit_claim(
        client, base.policy["id"], "FRACTURE",
        service_date="2026-09-02T00:00:00Z", diagnosis_code="S82.001A",
        claimed_occurrences=1,
    )
    fixtures.pay_claim_full_cycle(client, first["id"])

    second = fixtures.submit_claim(
        client, base.policy["id"], "FRACTURE",
        service_date="2026-09-15T00:00:00Z", diagnosis_code="S82.001A",
        claimed_occurrences=1,
    )
    fixtures.review_claim(client, second["id"])
    fixtures.attach_document(client, second["id"], doc_type="ITEMIZED_BILL")
    return base, second


def test_outstanding_documents_are_reported_before_the_fiscal_cap(client):
    """Documentation gates run before the caps, so PENDING wins over CAP_EXHAUSTED.

    "An `APPROVE` runs a gauntlet whose checks have a fixed relative order, with
    documentation gates evaluated before clinical and fiscal gates — and between
    the two documentation checks, outstanding documents are reported before
    missing proof types."

    Design: Difficulty/priority_pair_validation_conflict/claim_adjudicate_documents_pending_vs_cap_exhausted
    """
    base, claim = _cap_exhausted_with_pending_document(client)

    response = client.adjudicate_claim(
        claim["id"], {"decision": "APPROVE"}, make_claims_adjuster_headers()
    )

    validate_error(response, api_errors.ERR_DOCUMENTS_PENDING, 422)


def test_a_documentation_rejection_never_reaches_the_cap_auto_deny(client):
    """The claim stays UNDER_REVIEW with no denial reason when documents block.

    "First, every document of the claim must be `ACCEPTED`; any document still
    `RECEIVED` or `REJECTED` rejects the approval with `ERR_DOCUMENTS_PENDING`."

    Design: Difficulty/priority_pair_validation_conflict/claim_adjudicate_documents_pending_vs_cap_exhausted
    """
    base, claim = _cap_exhausted_with_pending_document(client)

    client.adjudicate_claim(
        claim["id"], {"decision": "APPROVE"}, make_claims_adjuster_headers()
    )

    reloaded = fixtures.read_claim(client, claim["id"])
    assert reloaded["status"] == "UNDER_REVIEW", (
        "the fiscal gate is never evaluated while documents are pending; got %r"
        % reloaded.get("status")
    )
    assert reloaded["denial_reason"] is None
