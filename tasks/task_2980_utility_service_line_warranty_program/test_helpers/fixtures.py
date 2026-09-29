"""Composite setup helpers.

The harness restarts the API server before every individual test, so each test
begins against an empty store and every precondition below is built from
scratch.

Each helper is *phased*: a single step never performs work that would invalidate
a precondition an earlier step established, and every step that bumps a version
returns the fresh version so a later caller never has to guess. Where a step
does invalidate an earlier snapshot — creating an enrollment and running a mail
drop both touch the sourcing premises — the helper re-reads the record and
updates the returned world, so callers can compose the phases in any order the
PRD permits.

Every helper accepts an ``ApiClient`` and returns either a resource dict or a
``World`` of accumulated ids and versions.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import (
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_ENROLLMENT_DAY,
    CLOCK_START,
)
from .test_users import (
    APPEALS_OFFICER,
    BILLING_OPS,
    CLAIMS_ADJUSTER,
    CUSTOMER_SERVICE_REP,
    MARKETING_OPS,
    OPERATIONS_ADMIN,
    PLATFORM_ADMIN,
    REGULATORY_AFFAIRS,
    make_network_contractor_headers,
    make_partner_brand_reviewer_headers,
    make_policyholder_headers,
)
from .types import Headers, Payload, Resource, World

# ── Phase 0: the logical clock (PRD §2.5) ──


def set_clock(api, to_iso8601: str, headers: Headers = PLATFORM_ADMIN) -> Resource:
    """Move the logical clock. Setting the clock mutates no entity."""
    return get_success_data(api.set_clock(to_iso8601, headers))


def current_clock(api, headers: Headers = PLATFORM_ADMIN) -> str:
    """Read the clock back by setting it to the value it already reports."""
    data = get_success_data(api.set_clock(CLOCK_START, headers))
    return data["current_utc"]


def run_nightly(api, headers: Headers = OPERATIONS_ADMIN) -> Resource:
    """Run the nightly batch. The run takes no inputs (PRD §3.9)."""
    return get_success_data(api.run_nightly(headers))


# ── Phase 1: partner, product, activation (PRD §3.1) ──


def create_partner(api, headers: Headers = PLATFORM_ADMIN, **overrides) -> Resource:
    return get_success_data(api.create_partner(factories.partner_payload(**overrides), headers), 201)


def file_product(api, partner_id: str, headers: Headers = PLATFORM_ADMIN, **overrides) -> Resource:
    return get_success_data(
        api.create_product(factories.product_payload(partner_id, **overrides), headers), 201
    )


def file_tight_cap_product(api, partner_id: str, headers: Headers = PLATFORM_ADMIN, **overrides) -> Resource:
    """File Sewer Guard Basic, whose per-occurrence cap equals its annual cap."""
    return get_success_data(
        api.create_product(factories.tight_cap_product_payload(partner_id, **overrides), headers),
        201,
    )


def change_partner_status(
    api,
    partner_id: str,
    target_status: str,
    expected_partner_version: int,
    headers: Headers = PLATFORM_ADMIN,
    **overrides,
) -> Resource:
    payload = factories.partner_status_change_payload(
        target_status, expected_partner_version, **overrides
    )
    return get_success_data(api.change_partner_status(partner_id, payload, headers))


def activate_partner(api, partner_id: str, expected_partner_version: int, headers: Headers = PLATFORM_ADMIN) -> Resource:
    """Take a partner from ONBOARDING to ACTIVE once a product is on file."""
    return change_partner_status(api, partner_id, "ACTIVE", expected_partner_version, headers)


def refresh_partner_version(api, partner_id: str, headers: Headers = PLATFORM_ADMIN) -> int:
    return get_success_data(api.get_partner(partner_id, headers))["version"]


def active_partner_with_product(api, partner_overrides: Optional[Payload] = None,
                                product_overrides: Optional[Payload] = None) -> World:
    """Clock at the epoch, an ACTIVE partner and one AVAILABLE product.

    This is the smallest state in which anything downstream may be created; it
    performs no premises or enrollment work, so a caller that only needs a
    partner never pays for the rest.
    """
    set_clock(api, CLOCK_START)
    partner = create_partner(api, **(partner_overrides or {}))
    product = file_product(api, partner["id"], **(product_overrides or {}))
    # Filing a product advances the partner's version, so the activation guard
    # must carry the version observed after the filing, not the one at creation.
    activated = activate_partner(api, partner["id"], refresh_partner_version(api, partner["id"]))
    return {
        "partner_id": partner["id"],
        "partner_version": activated["version"],
        "partner": activated,
        "product_id": product["id"],
        "product": product,
    }


# ── Phase 2: premises (PRD §3.1) ──


def create_premises(api, partner_id: str, headers: Headers = MARKETING_OPS, **overrides) -> Resource:
    return get_success_data(
        api.create_premises(factories.premises_payload(partner_id, **overrides), headers), 201
    )


def create_unique_premises(api, partner_id: str, headers: Headers = MARKETING_OPS, **overrides) -> Resource:
    """A premises whose street_address is fresh within the partner's file."""
    return get_success_data(
        api.create_premises(factories.unique_premises_payload(partner_id, **overrides), headers), 201
    )


def refresh_premises_version(api, premises_id: str, headers: Headers = MARKETING_OPS) -> int:
    """Re-read the premises version.

    Both enrollment creation and a mail drop touch the premises, so any caller
    holding an older snapshot must refresh before an optimistic-concurrency
    guard will accept it.
    """
    return get_success_data(api.get_premises(premises_id, headers))["version"]


def partner_product_premises(api, partner_overrides: Optional[Payload] = None,
                             product_overrides: Optional[Payload] = None,
                             premises_overrides: Optional[Payload] = None) -> World:
    """Phase 1 plus one mailable premises owning the insured segment."""
    world = active_partner_with_product(api, partner_overrides, product_overrides)
    premises = create_premises(api, world["partner_id"], **(premises_overrides or {}))
    world.update(
        premises_id=premises["id"],
        premises_version=premises["version"],
        premises=premises,
    )
    return world


# ── Phase 3: marketing campaign lifecycle (PRD §3.2) ──


def create_campaign(api, partner_id: str, product_id: str, headers: Headers = MARKETING_OPS,
                    **overrides) -> Resource:
    payload = factories.campaign_payload(partner_id, product_id, **overrides)
    return get_success_data(api.create_campaign(payload, headers), 201)


def submit_campaign(api, campaign_id: str, headers: Headers = MARKETING_OPS, **overrides) -> Resource:
    payload = factories.campaign_submission_payload(**overrides)
    return get_success_data(api.submit_campaign(campaign_id, payload, headers))


def approve_campaign(api, campaign_id: str, partner_id: str, **overrides) -> Resource:
    """Approve as the reviewer of the campaign's own partner."""
    payload = factories.campaign_approval_payload(**overrides)
    headers = make_partner_brand_reviewer_headers(partner_id)
    return get_success_data(api.decide_campaign(campaign_id, payload, headers))


def reject_campaign(api, campaign_id: str, partner_id: str, **overrides) -> Resource:
    payload = factories.campaign_rejection_payload(**overrides)
    headers = make_partner_brand_reviewer_headers(partner_id)
    return get_success_data(api.decide_campaign(campaign_id, payload, headers))


def mail_drop(api, campaign_id: str, headers: Headers = MARKETING_OPS) -> Resource:
    return get_success_data(api.mail_drop(campaign_id, headers))


def approved_campaign(api, world: World, **campaign_overrides) -> World:
    """Take one campaign from DRAFT through PARTNER_REVIEW to APPROVED.

    Stops short of the drop, because the drop is what consumes the partner's
    spacing window and touches every premises on file; a caller that only needs
    an APPROVED campaign must not pay that cost.
    """
    campaign = create_campaign(api, world["partner_id"], world["product_id"], **campaign_overrides)
    submit_campaign(api, campaign["id"])
    approved = approve_campaign(api, campaign["id"], world["partner_id"])
    world.update(campaign_id=campaign["id"], campaign=approved,
                 campaign_version=approved["version"])
    return world


def mailed_campaign(api, world: World, **campaign_overrides) -> World:
    """The approved campaign above, then dropped.

    The drop stamps every evaluated premises, so the premises version in the
    world is refreshed afterwards.
    """
    world = approved_campaign(api, world, **campaign_overrides)
    summary = mail_drop(api, world["campaign_id"])
    world["drop_summary"] = summary
    if world.get("premises_id"):
        world["premises_version"] = refresh_premises_version(api, world["premises_id"])
    return world


# ── Phase 4: enrollment (PRD §3.3) ──


def create_enrollment(api, premises_id: str, product_id: str, expected_premises_version: int,
                      headers: Headers = CUSTOMER_SERVICE_REP, **overrides) -> Resource:
    payload = factories.enrollment_payload(
        premises_id, product_id, expected_premises_version, **overrides
    )
    return get_success_data(api.create_enrollment(payload, headers), 201)


def create_bill_insert_enrollment(api, premises_id: str, product_id: str,
                                  expected_premises_version: int,
                                  headers: Headers = CUSTOMER_SERVICE_REP, **overrides) -> Resource:
    payload = factories.bill_insert_enrollment_payload(
        premises_id, product_id, expected_premises_version, **overrides
    )
    return get_success_data(api.create_enrollment(payload, headers), 201)


def refresh_enrollment(api, enrollment_id: str, headers: Headers = CUSTOMER_SERVICE_REP) -> Resource:
    return get_success_data(api.get_enrollment(enrollment_id, headers))


def enrolled_premises(api, world: Optional[World] = None, clock: str = CLOCK_ENROLLMENT_DAY,
                      **enrollment_overrides) -> World:
    """A DIRECT_BILL enrollment written on the enrollment day.

    Coverage is still PENDING_WAITING_PERIOD when this returns: activation is a
    separate phase because it needs the clock moved past the waiting period and
    a nightly run, both of which a caller testing the pending state must avoid.
    """
    if world is None:
        world = partner_product_premises(api)
    set_clock(api, clock)
    enrollment = create_enrollment(
        api, world["premises_id"], world["product_id"], world["premises_version"],
        **enrollment_overrides
    )
    world.update(
        enrollment_id=enrollment["id"],
        enrollment_version=enrollment["version"],
        enrollment=enrollment,
        premises_version=refresh_premises_version(api, world["premises_id"]),
    )
    return world


def activate_coverage(api, world: World, clock: str = CLOCK_COVERAGE_ACTIVE) -> World:
    """Move past the waiting period and let the nightly run activate coverage."""
    set_clock(api, clock)
    report = run_nightly(api)
    world["nightly_report"] = report
    world["enrollment"] = refresh_enrollment(api, world["enrollment_id"])
    world["enrollment_version"] = world["enrollment"]["version"]
    return world


def active_coverage(api, world: Optional[World] = None, clock: str = CLOCK_COVERAGE_ACTIVE,
                    **enrollment_overrides) -> World:
    """An enrollment whose coverage_status has reached ACTIVE."""
    world = enrolled_premises(api, world, **enrollment_overrides)
    return activate_coverage(api, world, clock)


# ── Phase 5: contractors (PRD §3.6) ──


def create_contractor(api, headers: Headers = OPERATIONS_ADMIN, **overrides) -> Resource:
    return get_success_data(
        api.create_contractor(factories.contractor_payload(**overrides), headers), 201
    )


def create_cheap_contractor(api, headers: Headers = OPERATIONS_ADMIN, **overrides) -> Resource:
    """A cheaper contractor with a weaker SLA record, for selection contests."""
    return get_success_data(
        api.create_contractor(factories.cheap_contractor_payload(**overrides), headers), 201
    )


def create_unique_contractor(api, headers: Headers = OPERATIONS_ADMIN, **overrides) -> Resource:
    return get_success_data(
        api.create_contractor(factories.unique_contractor_payload(**overrides), headers), 201
    )


def refresh_contractor(api, contractor_id: str, headers: Headers = OPERATIONS_ADMIN) -> Resource:
    return get_success_data(api.get_contractor(contractor_id, headers))


def active_coverage_with_contractor(api, world: Optional[World] = None,
                                    contractor_overrides: Optional[Payload] = None,
                                    **enrollment_overrides) -> World:
    """Active coverage plus one eligible contractor in the pool."""
    world = active_coverage(api, world, **enrollment_overrides)
    contractor = create_contractor(api, **(contractor_overrides or {}))
    world.update(contractor_id=contractor["id"], contractor=contractor)
    return world


# ── Phase 6: claims (PRD §3.5) ──


def file_claim(api, enrollment_id: str, headers: Headers = CUSTOMER_SERVICE_REP, **overrides) -> Resource:
    payload = factories.claim_payload(enrollment_id, **overrides)
    return get_success_data(api.create_claim(payload, headers), 201)


def approve_claim(api, claim_id: str, headers: Headers = CLAIMS_ADJUSTER, **overrides) -> Resource:
    payload = factories.triage_approval_payload(**overrides)
    return get_success_data(api.triage_claim(claim_id, payload, headers))


def deny_claim(api, claim_id: str, denial_reason: str = "NOT_COVERED_SEGMENT",
               headers: Headers = CLAIMS_ADJUSTER, **overrides) -> Resource:
    payload = factories.triage_denial_payload(denial_reason, **overrides)
    return get_success_data(api.triage_claim(claim_id, payload, headers))


def refresh_claim(api, claim_id: str, headers: Headers = CLAIMS_ADJUSTER) -> Resource:
    return get_success_data(api.get_claim(claim_id, headers))


def open_appeal(api, claim_id: str, premises_id: str, **overrides) -> Resource:
    """Appeal as the policyholder of the premises behind the claim."""
    payload = factories.appeal_payload(**overrides)
    headers = make_policyholder_headers(premises_id)
    return get_success_data(api.create_appeal(claim_id, payload, headers))


def decide_appeal(api, claim_id: str, decision: str, headers: Headers = APPEALS_OFFICER,
                  **overrides) -> Resource:
    payload = factories.appeal_decision_payload(decision, **overrides)
    return get_success_data(api.decide_appeal(claim_id, payload, headers))


def filed_claim(api, world: Optional[World] = None, **claim_overrides) -> World:
    """Active coverage plus one claim sitting in TRIAGE.

    Triage is deliberately not performed here: the derived intake assessment is
    only observable before a decision is taken.
    """
    if world is None or not world.get("enrollment_id"):
        world = active_coverage_with_contractor(api, world)
    claim = file_claim(api, world["enrollment_id"], **claim_overrides)
    world.update(claim_id=claim["id"], claim_version=claim["version"], claim=claim)
    return world


def approved_claim(api, world: Optional[World] = None, **claim_overrides) -> World:
    """A claim carried through triage approval, ready to dispatch."""
    world = filed_claim(api, world, **claim_overrides)
    approved = approve_claim(api, world["claim_id"])
    world.update(claim=approved, claim_version=approved["version"])
    return world


def denied_claim(api, world: Optional[World] = None,
                 denial_reason: str = "NOT_COVERED_SEGMENT", **claim_overrides) -> World:
    """A claim carried through triage denial, ready to appeal."""
    world = filed_claim(api, world, **claim_overrides)
    denied = deny_claim(api, world["claim_id"], denial_reason)
    world.update(claim=denied, claim_version=denied["version"])
    return world


# ── Phase 7: dispatch and field events (PRD §3.6, §3.7) ──

# A visit window comfortably after the clock used by ``active_coverage``.
DEFAULT_WINDOW_START = "2026-09-11T09:00:00.000Z"


def dispatch_claim(api, claim_id: str, expected_claim_version: int,
                   window_start: str = DEFAULT_WINDOW_START,
                   headers: Headers = OPERATIONS_ADMIN, **overrides) -> Resource:
    """Automatic dispatch: the selection score chooses from the eligible pool."""
    payload = factories.dispatch_payload(expected_claim_version, window_start, **overrides)
    return get_success_data(api.create_dispatch(claim_id, payload, headers), 201)


def dispatch_claim_to(api, claim_id: str, expected_claim_version: int, contractor_id: str,
                      window_start: str = DEFAULT_WINDOW_START,
                      headers: Headers = OPERATIONS_ADMIN, **overrides) -> Resource:
    """Manual dispatch: the named contractor still passes every gate."""
    payload = factories.manual_dispatch_payload(
        expected_claim_version, window_start, contractor_id, **overrides
    )
    return get_success_data(api.create_dispatch(claim_id, payload, headers), 201)


def refresh_dispatch(api, dispatch_id: str, headers: Headers = OPERATIONS_ADMIN) -> Resource:
    return get_success_data(api.get_dispatch(dispatch_id, headers))


def accept_dispatch(api, dispatch_id: str, contractor_id: str, **overrides) -> Resource:
    payload = factories.accept_event_payload(**overrides)
    return get_success_data(
        api.create_dispatch_event(dispatch_id, payload, make_network_contractor_headers(contractor_id))
    )


def arrive_dispatch(api, dispatch_id: str, contractor_id: str, **overrides) -> Resource:
    payload = factories.arrive_event_payload(**overrides)
    return get_success_data(
        api.create_dispatch_event(dispatch_id, payload, make_network_contractor_headers(contractor_id))
    )


def complete_dispatch(api, dispatch_id: str, contractor_id: str,
                      labor_cents: int = 260000, materials_cents: int = 175000,
                      **overrides) -> Resource:
    payload = factories.complete_event_payload(labor_cents, materials_cents, **overrides)
    return get_success_data(
        api.create_dispatch_event(dispatch_id, payload, make_network_contractor_headers(contractor_id))
    )


def dispatched_claim(api, world: Optional[World] = None,
                     window_start: str = DEFAULT_WINDOW_START, **claim_overrides) -> World:
    """An approved claim with an ASSIGNED dispatch on it.

    The ACCEPT event is a separate phase because the response time is only
    stampable once, and a caller testing the un-accepted SLA state needs the
    dispatch left alone.
    """
    world = approved_claim(api, world, **claim_overrides)
    dispatch = dispatch_claim(api, world["claim_id"], world["claim_version"], window_start)
    world.update(dispatch_id=dispatch["id"], dispatch=dispatch,
                 claim_version=refresh_claim(api, world["claim_id"])["version"])
    if not world.get("contractor_id"):
        world["contractor_id"] = dispatch["contractor_id"]
    return world


def accepted_dispatch(api, world: Optional[World] = None,
                      window_start: str = DEFAULT_WINDOW_START, **claim_overrides) -> World:
    """A dispatch the assigned contractor has accepted."""
    world = dispatched_claim(api, world, window_start, **claim_overrides)
    accepted = accept_dispatch(api, world["dispatch_id"], world["dispatch"]["contractor_id"])
    world["dispatch"] = accepted
    return world


def completed_dispatch(api, world: Optional[World] = None,
                       window_start: str = DEFAULT_WINDOW_START,
                       labor_cents: int = 260000, materials_cents: int = 175000,
                       complete_overrides: Optional[Payload] = None,
                       **claim_overrides) -> World:
    """A dispatch settled through the completion waterfall."""
    world = accepted_dispatch(api, world, window_start, **claim_overrides)
    completed = complete_dispatch(
        api, world["dispatch_id"], world["dispatch"]["contractor_id"],
        labor_cents, materials_cents, **(complete_overrides or {})
    )
    world["dispatch"] = completed
    world["claim"] = refresh_claim(api, world["claim_id"])
    world["claim_version"] = world["claim"]["version"]
    world["enrollment"] = refresh_enrollment(api, world["enrollment_id"])
    world["enrollment_version"] = world["enrollment"]["version"]
    return world


# ── Phase 8: regulator complaints (PRD §3.8) ──


def create_complaint(api, partner_id: str, headers: Headers = REGULATORY_AFFAIRS, **overrides) -> Resource:
    payload = factories.complaint_payload(partner_id, **overrides)
    return get_success_data(api.create_complaint(payload, headers), 201)


def respond_to_complaint(api, complaint_id: str, disposition: str, remedy_type: str,
                         expected_complaint_version: int,
                         headers: Headers = REGULATORY_AFFAIRS, **overrides) -> Resource:
    payload = factories.complaint_response_payload(
        disposition, remedy_type, expected_complaint_version, **overrides
    )
    return get_success_data(api.respond_to_complaint(complaint_id, payload, headers))


def escalate_complaint(api, complaint_id: str, headers: Headers = REGULATORY_AFFAIRS, **overrides) -> Resource:
    payload = factories.escalation_payload(**overrides)
    return get_success_data(api.escalate_complaint(complaint_id, payload, headers))


def refresh_complaint(api, complaint_id: str, headers: Headers = REGULATORY_AFFAIRS) -> Resource:
    return get_success_data(api.get_complaint(complaint_id, headers))


def open_complaint(api, world: World, **overrides) -> World:
    """One OPEN complaint against the partner already in the world."""
    complaint = create_complaint(api, world["partner_id"], **overrides)
    world.update(complaint_id=complaint["id"], complaint=complaint,
                 complaint_version=complaint["version"])
    return world


# ── Ledger reads (PRD §2.10) ──


def ledger_entries(api, headers: Headers = PLATFORM_ADMIN, **params) -> List[Resource]:
    """Every ledger row matching the supplied filters, in append order."""
    return get_success_data(api.list_ledger_entries(headers, params=params or None))


def billing_event(api, enrollment_id: str, event_type: str, effective_date: str,
                  headers: Headers = BILLING_OPS, **overrides) -> Resource:
    payload = factories.billing_event_payload(event_type, effective_date, **overrides)
    return get_success_data(api.create_billing_event(enrollment_id, payload, headers))


def cancel_enrollment(api, enrollment_id: str, requested_effective_date: str,
                      headers: Headers = CUSTOMER_SERVICE_REP, **overrides) -> Resource:
    payload = factories.cancellation_payload(requested_effective_date, **overrides)
    return get_success_data(api.cancel_enrollment(enrollment_id, payload, headers))


def issue_renewal_notice(api, enrollment_id: str, new_price_cents: int,
                         renewal_effective_date: str, expected_enrollment_version: int,
                         headers: Headers = BILLING_OPS, **overrides) -> Resource:
    payload = factories.renewal_notice_payload(
        new_price_cents, renewal_effective_date, expected_enrollment_version, **overrides
    )
    return get_success_data(api.create_renewal_notice(enrollment_id, payload, headers))
