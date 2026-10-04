"""Composite setup helpers for the biometric identity lane domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z). All helpers use the
lenient get_success_data validator so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import DEFAULT_CLOCK
from .factories import (
    create_agreement_payload,
    create_agreement_settlement_payload,
    create_airport_payload,
    create_ambassador_payload,
    create_check_in_payload,
    create_discount_payload,
    create_dispute_payload,
    create_enrollment_center_payload,
    create_enrollment_payload,
    create_kiosk_payload,
    create_lane_payload,
    create_member_payload,
    create_subscription_payload,
    create_venue_event_payload,
    create_venue_payout_payload,
    create_venue_payload,
)
from .test_users import (
    TEST_USERS,
    make_ambassador_headers,
    make_compliance_officer_headers,
    make_member_headers,
)

OPS = TEST_USERS["ops_admin_headers"]
PM = TEST_USERS["partner_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
VENUE = TEST_USERS["venue_ops_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic entity setup
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, OPS))


def create_airport(iata_code=None, **overrides):
    return get_success_data(
        api.create_airport(create_airport_payload(iata_code, **overrides), OPS)
    )


def create_agreement(airport_id, **overrides):
    return get_success_data(
        api.create_agreement(create_agreement_payload(airport_id, **overrides), PM)
    )


def create_active_agreement(airport_id, **overrides):
    """Draft an agreement and activate it (cascades the airport to ACTIVE)."""
    agreement = create_agreement(airport_id, **overrides)
    activated = get_success_data(api.activate_agreement(agreement["id"], PM))
    return activated


def setup_airport_with_active_agreement(iata_code=None, **agreement_overrides):
    """Airport + ACTIVE agreement. Returns (airport, agreement)."""
    airport = create_airport(iata_code)
    agreement = create_active_agreement(airport["id"], **agreement_overrides)
    return airport, agreement


def create_enrollment_center(airport_id, **overrides):
    return get_success_data(
        api.create_enrollment_center(
            create_enrollment_center_payload(airport_id, **overrides), OPS
        )
    )


def create_kiosk(airport_id, **overrides):
    return get_success_data(
        api.create_kiosk(create_kiosk_payload(airport_id, **overrides), OPS)
    )


def create_active_kiosk(airport_id, **overrides):
    """Register a kiosk and activate it (requires an ACTIVE agreement)."""
    kiosk = create_kiosk(airport_id, **overrides)
    return get_success_data(api.activate_kiosk(kiosk["id"], OPS))


def create_lane(airport_id, agreement_id, **overrides):
    return get_success_data(
        api.create_lane(create_lane_payload(airport_id, agreement_id, **overrides), OPS)
    )


def create_open_lane(airport_id, agreement_id, **overrides):
    lane = create_lane(airport_id, agreement_id, **overrides)
    return get_success_data(api.open_lane(lane["id"], OPS))


def create_ambassador(airport_id, **overrides):
    return get_success_data(
        api.create_ambassador(create_ambassador_payload(airport_id, **overrides), OPS)
    )


def create_venue(**overrides):
    return get_success_data(api.create_venue(create_venue_payload(**overrides), VENUE))


def create_venue_event(venue_id, **overrides):
    return get_success_data(
        api.create_venue_event(create_venue_event_payload(venue_id, **overrides), VENUE)
    )


def create_discount(airport_id, **overrides):
    return get_success_data(
        api.create_discount(create_discount_payload(airport_id, **overrides), PM)
    )


# ---------------------------------------------------------------------------
# Tier 2: members and the enrollment pipeline
# ---------------------------------------------------------------------------

def register_member(**overrides):
    payload = create_member_payload(**overrides)
    # Self-registration: the caller role is Member; the server binds the new id.
    return get_success_data(
        api.register_member(payload, TEST_USERS["member_headers"])
    )


def open_enrollment(member, site_type, site_id, **overrides):
    """Open a DRAFT enrollment for an already-registered member (ownership-gated)."""
    payload = create_enrollment_payload(member["id"], site_type, site_id, **overrides)
    return get_success_data(
        api.create_enrollment(payload, make_member_headers(member["id"]))
    )


def submit_document(enrollment, member):
    return get_success_data(
        api.submit_document(enrollment["id"], make_member_headers(member["id"]))
    )


def capture_biometric(enrollment, member):
    return get_success_data(
        api.capture_biometric(enrollment["id"], make_member_headers(member["id"]))
    )


def complete_enrollment(enrollment, member):
    return get_success_data(
        api.complete_enrollment(enrollment["id"], make_member_headers(member["id"]))
    )


def review_enrollment(enrollment, decision, officer_headers=None):
    return get_success_data(
        api.review_enrollment(
            enrollment["id"], decision, officer_headers or CO
        )
    )


def enroll_member_at_center(center, **overrides):
    """Register a member and drive a clean enrollment-center enrollment all the
    way to COMPLETED (member ends ACTIVE). Returns (member, enrollment)."""
    member_kwargs = {
        k: v for k, v in overrides.items()
        if k in ("email", "full_name", "date_of_birth")
    }
    member = register_member(**member_kwargs)
    enrollment_kwargs = {
        "document_type": overrides.get("document_type", "PASSPORT"),
        "document_expiry": overrides.get("document_expiry", "2030-01-01"),
        "biometric_capture_ok": overrides.get("biometric_capture_ok", True),
    }
    if overrides.get("document_number"):
        enrollment_kwargs["document_number"] = overrides["document_number"]
    enrollment = open_enrollment(
        member, "ENROLLMENT_CENTER", center["id"], **enrollment_kwargs
    )
    enrollment = submit_document(enrollment, member)
    assert enrollment["status"] == "DOCUMENT_VERIFIED", (
        f"setup expected DOCUMENT_VERIFIED, got {enrollment['status']}"
    )
    enrollment = capture_biometric(enrollment, member)
    assert enrollment["status"] == "BIOMETRIC_CAPTURED"
    enrollment = complete_enrollment(enrollment, member)
    assert enrollment["status"] == "COMPLETED"
    member = get_success_data(api.get_member(member["id"], OPS))
    assert member["status"] == "ACTIVE"
    return member, enrollment


def create_active_member(center, **overrides):
    """Register + fully enroll at an enrollment center. Returns the ACTIVE member."""
    member, _ = enroll_member_at_center(center, **overrides)
    return member


def create_active_member_with_subscription(center, plan="INDIVIDUAL", **overrides):
    """ACTIVE member plus their subscription. Returns (member, subscription)."""
    member = create_active_member(center, **overrides)
    subscription = get_success_data(
        api.create_subscription(
            create_subscription_payload(member["id"], plan=plan),
            make_member_headers(member["id"]),
        )
    )
    return member, subscription


def watchlist_add(document_number, date_of_birth):
    return get_success_data(
        api.update_watchlist(document_number, date_of_birth, "ADD", OPS)
    )


def watchlist_remove(document_number, date_of_birth):
    return get_success_data(
        api.update_watchlist(document_number, date_of_birth, "REMOVE", OPS)
    )


def mod7_failing_document_number(prefix="D"):
    """Return a document number whose numeric-portion digit sum is NOT
    divisible by 7 (fires the DOC_FORMAT risk rule)."""
    return f"{prefix}1000001"  # digit sum 2


def mod7_passing_document_number(prefix="D"):
    """Return a document number whose numeric-portion digit sum IS divisible
    by 7 (does not fire the DOC_FORMAT risk rule)."""
    return f"{prefix}1000006"  # digit sum 7


# ---------------------------------------------------------------------------
# Tier 3: full lane environment
# ---------------------------------------------------------------------------

def setup_lane_environment(iata_code=None, federal_integration=False, **overrides):
    """Airport + ACTIVE agreement + OPEN lane + ACTIVE ambassador + enrollment
    center. Returns a dict with airport, agreement, lane, ambassador, center."""
    airport, agreement = setup_airport_with_active_agreement(
        iata_code, federal_integration=federal_integration,
        **overrides,
    )
    lane = create_open_lane(
        airport["id"], agreement["id"],
        open_time="00:00", close_time="23:59", capacity_hours=8,
    )
    ambassador = create_ambassador(airport["id"])
    center = create_enrollment_center(airport["id"])
    return {
        "airport": airport,
        "agreement": agreement,
        "lane": lane,
        "ambassador": ambassador,
        "center": center,
    }


def check_in_member(member, lane, ambassador):
    """Member checks in at a lane (ownership-gated). Returns LaneVerification."""
    return get_success_data(
        api.check_in(
            create_check_in_payload(member["id"], lane["id"], ambassador["id"]),
            make_member_headers(member["id"]),
        )
    )


def escort_member(verification, ambassador, expected_member_version=None):
    if expected_member_version is None:
        expected_member_version = verification["version_confirmed"]
    return get_success_data(
        api.escort(
            verification["id"], expected_member_version,
            make_ambassador_headers(ambassador["id"]),
        )
    )


# ---------------------------------------------------------------------------
# Tier 4: subscriptions, family groups, discounts, billing
# ---------------------------------------------------------------------------

def create_subscription(member, plan="INDIVIDUAL", **overrides):
    return get_success_data(
        api.create_subscription(
            create_subscription_payload(member["id"], plan=plan, **overrides),
            make_member_headers(member["id"]),
        )
    )


def get_family_group_for_subscription(subscription, member):
    """Fetch the FamilyGroup belonging to a FAMILY subscription."""
    from prd_bench_local_runner.testing import validate_paginated

    data, _meta = validate_paginated(
        api.list_family_groups(
            make_member_headers(member["id"]),
            params={"primary_subscription_id": subscription["id"]},
        )
    )
    assert len(data) == 1, "expected exactly one family group for the subscription"
    return data[0]


def add_family_member(group, dependant_member, primary_member):
    return get_success_data(
        api.add_family_member(
            group["id"], dependant_member["id"],
            make_member_headers(primary_member["id"]),
        )
    )


def attach_discount(subscription, code, member):
    return get_success_data(
        api.attach_discount(subscription["id"], code, make_member_headers(member["id"]))
    )


def detach_discount(subscription, member):
    return get_success_data(
        api.detach_discount(subscription["id"], make_member_headers(member["id"]))
    )


def change_plan(subscription, new_plan, expected_version, member):
    return get_success_data(
        api.change_plan(
            subscription["id"], new_plan, expected_version,
            make_member_headers(member["id"]),
        )
    )


def cancel_subscription(subscription, member):
    return get_success_data(
        api.cancel_subscription(subscription["id"], make_member_headers(member["id"]))
    )


def run_invoice_cycle(subscription):
    return get_success_data(api.run_invoice_cycle(subscription["id"], OPS))


def record_payment(invoice, outcome):
    return get_success_data(api.record_payment(invoice["id"], outcome, OPS))


# ---------------------------------------------------------------------------
# Tier 4b: risk-score driving helpers
# ---------------------------------------------------------------------------

def submit_enrollment_expecting_fraud_review(member, center, document_number,
                                             biometric_capture_ok=True):
    """Open + submit an enrollment crafted to land in FRAUD_REVIEW. The caller
    is responsible for arranging risk facts (watchlist entries, MOD-7-failing
    document numbers, prior rejections) so the score falls in [15, 20)."""
    enrollment = open_enrollment(
        member, "ENROLLMENT_CENTER", center["id"],
        document_number=document_number,
        biometric_capture_ok=biometric_capture_ok,
    )
    enrollment = submit_document(enrollment, member)
    assert enrollment["status"] == "FRAUD_REVIEW", (
        f"setup expected FRAUD_REVIEW, got {enrollment['status']} "
        f"(risk_flags={enrollment.get('risk_flags')})"
    )
    return enrollment


def drive_member_to_three_rejections(member, center, doc_prefix="R"):
    """Create three FRAUD_REVIEW enrollments for the member and review-REJECT
    each, driving document_reject_count_90d to exactly 3.

    Each enrollment is watchlisted (WATCHLIST +8), uses a MOD-7-failing
    document number (DOC_FORMAT +4), and declares biometric_capture_ok=false
    (SELFIE_MISMATCH +5): score 17 routes to FRAUD_REVIEW per PRD §3.3.
    Document numbers like 'R1000011' have digit sum 3 — not divisible by 7.
    """
    enrollments = []
    for i in range(1, 4):
        doc = f"{doc_prefix}10000{i}1"  # digit sum 3 + i-1; for i in 1..3 -> 3,4,5 (all fail MOD-7)
        watchlist_add(doc, member["date_of_birth"])
        enrollment = open_enrollment(
            member, "ENROLLMENT_CENTER", center["id"],
            document_type="DRIVERS_LICENSE",
            document_number=doc,
            biometric_capture_ok=False,
        )
        enrollment = submit_document(enrollment, member)
        assert enrollment["status"] == "FRAUD_REVIEW", (
            f"rejection-driver enrollment must land FRAUD_REVIEW, got {enrollment['status']}"
        )
        enrollment = review_enrollment(enrollment, "REJECT")
        assert enrollment["status"] == "REJECTED"
        enrollments.append(enrollment)
    member = get_success_data(api.get_member(member["id"], OPS))
    assert member["document_reject_count_90d"] == 3, (
        f"expected 3 rejections, got {member['document_reject_count_90d']}"
    )
    return member, enrollments


# ---------------------------------------------------------------------------
# Tier 5: disputes and retention
# ---------------------------------------------------------------------------

def open_dispute(member, enrollment, officer_user_id="co-opener", reason="IDENTITY_TAKEOVER"):
    return get_success_data(
        api.open_dispute(
            create_dispute_payload(member["id"], enrollment["id"], reason=reason),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def create_agreement_settlement(agreement, **overrides):
    return get_success_data(
        api.create_agreement_settlement(
            agreement["id"], create_agreement_settlement_payload(**overrides), PM
        )
    )


def create_venue_payout_settlement(venue, **overrides):
    return get_success_data(
        api.create_venue_payout_settlement(
            venue["id"], create_venue_payout_payload(**overrides), VENUE
        )
    )
