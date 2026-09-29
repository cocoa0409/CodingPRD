"""Composite setup helpers.

The harness restarts the server before every test, so each test begins with an
empty database and every fixture below builds the state it needs from scratch
through the PRD's own endpoints.  Fixtures use the lenient
`get_success_data` accessor so that a setup failure surfaces as a readable
error rather than as an opaque assertion inside a test body.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import api_client
from .test_users import (
    make_admin_headers, make_employee_headers, make_employer_admin_headers,
    make_merchant_headers, make_partner_manager_headers,
)
from .types import DecisionValue, PerkCategory, RegionCode, ReviewDecision

# ── Control plane ───────────────────────────────────────────────────────────


def set_clock(to_iso8601, headers=None):
    """Set the logical clock (PRD §2.4) and return the echoed `current_utc`."""
    response = api_client.set_clock(
        F.clock_payload(to_iso8601), headers or make_admin_headers()
    )
    return get_success_data(response)["current_utc"]


def run_epoch(headers=None):
    """Run the five-pass epoch sweep and return its report."""
    response = api_client.run_epoch(headers or make_admin_headers())
    return get_success_data(response)


# ── Merchants and agreements (PRD §3.1, §3.2) ───────────────────────────────


def create_merchant(**overrides):
    """Register a `PROSPECT` merchant partner."""
    response = api_client.create_merchant(
        F.merchant_payload(**overrides), make_partner_manager_headers()
    )
    return get_success_data(response, 201)


def get_merchant(merchant_id, headers=None):
    response = api_client.get_merchant(merchant_id, headers or make_partner_manager_headers())
    return get_success_data(response)


def create_agreement(merchant_id, **overrides):
    """Open a `DRAFT` agreement against a merchant."""
    response = api_client.create_agreement(
        F.agreement_payload(merchant_id, **overrides), make_partner_manager_headers()
    )
    return get_success_data(response, 201)


def get_agreement(agreement_id, headers=None):
    response = api_client.get_agreement(
        agreement_id, headers or make_partner_manager_headers()
    )
    return get_success_data(response)


def propose_round(agreement, **overrides):
    """File a provider round, echoing the agreement's current `version`.

    `/propose` is a verb-path action endpoint that drives the agreement
    `DRAFT → PROVIDER_PROPOSED` (PRD §3.1) while also appending a round, so PRD
    §4 does not pin its success status to either 201 or 200.  The status is left
    unasserted here and the round's own facts are read back from
    `GET /perks/agreements/{id}/negotiation-rounds`, which PRD §2.3 does pin.
    """
    response = api_client.propose_round(
        agreement["id"],
        F.round_payload(agreement["version"], **overrides),
        make_partner_manager_headers(),
    )
    return get_success_data(response)


def counter_round(agreement, merchant_id, **overrides):
    """File a merchant counter-round, echoing the agreement's `version`.

    The success status is left unasserted for the same reason as
    `propose_round` above.
    """
    response = api_client.counter_round(
        agreement["id"],
        F.round_payload(agreement["version"], **overrides),
        make_merchant_headers(merchant_id),
    )
    return get_success_data(response)


def accept_agreement(agreement_id, merchant_id):
    """The merchant accepts a `PROVIDER_PROPOSED` agreement."""
    response = api_client.decide_agreement(
        agreement_id,
        F.decide_payload(DecisionValue.ACCEPT),
        make_merchant_headers(merchant_id),
    )
    return get_success_data(response)


def activate_agreement(agreement_id):
    response = api_client.activate_agreement(
        agreement_id, make_partner_manager_headers()
    )
    return get_success_data(response)


def active_agreement(merchant_id, commission_rate_bps=1200,
                     placement_fee_base_cents=36000,
                     employer_revenue_share_bps=2500,
                     category=PerkCategory.DINING, region_code=RegionCode.CA,
                     exclusivity_requested=False,
                     exclusivity_window_start=None, exclusivity_window_end=None):
    """Drive one agreement `DRAFT → PROVIDER_PROPOSED → ACCEPTED → ACTIVE`."""
    agreement = create_agreement(
        merchant_id, category=category, region_code=region_code,
        exclusivity_requested=exclusivity_requested,
    )
    round_overrides = {
        "commission_rate_bps": commission_rate_bps,
        "placement_fee_base_cents": placement_fee_base_cents,
        "employer_revenue_share_bps": employer_revenue_share_bps,
    }
    if exclusivity_window_start is not None:
        round_overrides["exclusivity_window_start"] = exclusivity_window_start
    if exclusivity_window_end is not None:
        round_overrides["exclusivity_window_end"] = exclusivity_window_end
    propose_round(agreement, **round_overrides)
    agreement = get_agreement(agreement["id"])
    accept_agreement(agreement["id"], merchant_id)
    return activate_agreement(agreement["id"])


def active_partner(merchant_overrides=None, **agreement_kwargs):
    """A merchant plus one `ACTIVE` agreement.

    Returns ``{"merchant": ..., "agreement": ...}`` where the merchant row is
    re-read after activation so its `status` and `active_agreement_count`
    reflect the cascade.
    """
    merchant = create_merchant(**(merchant_overrides or {}))
    agreement = active_agreement(merchant["id"], **agreement_kwargs)
    return {"merchant": get_merchant(merchant["id"]), "agreement": agreement}


# ── Employers, storefronts and eligibility (PRD §3.3, §3.4) ─────────────────


def create_employer(**overrides):
    """Register an employer client in `SETUP` posture."""
    response = api_client.create_employer(
        F.employer_payload(**overrides), make_admin_headers()
    )
    return get_success_data(response, 201)


def get_employer(employer_id, headers=None):
    response = api_client.get_employer(employer_id, headers or make_admin_headers())
    return get_success_data(response)


def brand_storefront(employer_id, **overrides):
    response = api_client.brand_storefront(
        employer_id, F.storefront_payload(**overrides),
        make_employer_admin_headers(employer_id),
    )
    return get_success_data(response)


def publish_storefront(employer_id):
    response = api_client.publish_storefront(
        employer_id, make_employer_admin_headers(employer_id)
    )
    return get_success_data(response)


def suspend_storefront(employer_id, **overrides):
    response = api_client.suspend_storefront(
        employer_id, F.storefront_suspend_payload(**overrides), make_admin_headers()
    )
    return get_success_data(response)


def load_eligibility_file(employer_id, records=None, **overrides):
    """Load a batch, reading the employer's current `version` for the echo."""
    employer = get_employer(employer_id)
    response = api_client.create_eligibility_file(
        employer_id,
        F.eligibility_file_payload(employer["version"], records=records, **overrides),
        make_employer_admin_headers(employer_id),
    )
    return get_success_data(response, 201)


def get_eligibility_file(file_id, headers=None):
    response = api_client.get_eligibility_file(file_id, headers or make_admin_headers())
    return get_success_data(response)


def validate_eligibility_file(file_id, employer_id):
    response = api_client.validate_eligibility_file(
        file_id, make_employer_admin_headers(employer_id)
    )
    return get_success_data(response)


def apply_eligibility_file(file_id, employer_id):
    response = api_client.apply_eligibility_file(
        file_id, make_employer_admin_headers(employer_id)
    )
    return get_success_data(response)


def sync_eligibility(employer_id, records=None):
    """Load, validate and apply one batch, driving integration to `SYNCED`."""
    batch = load_eligibility_file(employer_id, records=records)
    validate_eligibility_file(batch["id"], employer_id)
    return apply_eligibility_file(batch["id"], employer_id)


def list_memberships(employer_id, headers=None, **params):
    query = {"employer_id": employer_id, "limit": C.MAX_PAGE_LIMIT}
    query.update(params)
    response = api_client.list_memberships(
        headers or make_employer_admin_headers(employer_id), params=query
    )
    return get_success_data(response)


def get_membership(membership_id, employer_id=None, headers=None):
    response = api_client.get_membership(
        membership_id,
        headers or (make_employer_admin_headers(employer_id) if employer_id
                    else make_admin_headers()),
    )
    return get_success_data(response)


def set_employment_status(membership_id, employer_id, employment_status):
    response = api_client.set_employment_status(
        membership_id, F.employment_status_payload(employment_status),
        make_employer_admin_headers(employer_id),
    )
    return get_success_data(response)


def live_employer(record_count=1, records=None, revenue_share_enabled=True,
                  privacy_min_cohort_size=3,
                  featured_categories=(PerkCategory.DINING.value,),
                  region_code=RegionCode.CA, **employer_overrides):
    """An employer whose `program_posture` is `LIVE`, with its roster applied.

    Brands and publishes the storefront and applies one eligibility batch, so
    `storefront_status` is `PUBLISHED` and `integration_status` is `SYNCED`.
    Returns ``{"employer": ..., "file": ..., "memberships": [...]}``.
    """
    employer = create_employer(
        region_code=region_code,
        revenue_share_enabled=revenue_share_enabled,
        privacy_min_cohort_size=privacy_min_cohort_size,
        **employer_overrides,
    )
    employer_id = employer["id"]
    brand_storefront(employer_id, featured_categories=list(featured_categories))
    if records is None:
        records = F.eligibility_records(record_count, region_code=region_code)
    batch = sync_eligibility(employer_id, records=records)
    publish_storefront(employer_id)
    return {
        "employer": get_employer(employer_id),
        "file": batch,
        "memberships": list_memberships(employer_id),
    }


# ── Offers (PRD §3.5) ───────────────────────────────────────────────────────


def create_offer(agreement_id, merchant_id, **overrides):
    """Draft an offer against an `ACTIVE` agreement."""
    response = api_client.create_offer(
        F.offer_payload(agreement_id, **overrides), make_merchant_headers(merchant_id)
    )
    return get_success_data(response, 201)


def get_offer(offer_id, headers=None, merchant_id=None):
    if headers is None:
        headers = (make_merchant_headers(merchant_id) if merchant_id
                   else make_admin_headers())
    response = api_client.get_offer(offer_id, headers)
    return get_success_data(response)


def submit_offer(offer_id, merchant_id):
    response = api_client.submit_offer(offer_id, make_merchant_headers(merchant_id))
    return get_success_data(response)


def review_offer(offer_id, decision=ReviewDecision.APPROVE, **overrides):
    response = api_client.review_offer(
        offer_id, F.review_payload(decision, **overrides), make_admin_headers()
    )
    return get_success_data(response)


def approved_offer(agreement_id, merchant_id, **overrides):
    """Drive one offer `DRAFT → PENDING_REVIEW → ACTIVE`."""
    offer = create_offer(agreement_id, merchant_id, **overrides)
    submit_offer(offer["id"], merchant_id)
    return review_offer(offer["id"], ReviewDecision.APPROVE)


def pause_offer(offer_id, merchant_id, **overrides):
    response = api_client.pause_offer(
        offer_id, F.pause_payload(**overrides), make_merchant_headers(merchant_id)
    )
    return get_success_data(response)


# ── Placement slots (PRD §3.6) ──────────────────────────────────────────────


def reserve_slot(offer, employer_id, merchant_id, **overrides):
    """Reserve and price a slot, echoing the offer's current `version`."""
    response = api_client.reserve_placement_slot(
        offer["id"],
        F.slot_payload(offer["version"], employer_id, **overrides),
        make_merchant_headers(merchant_id),
    )
    return get_success_data(response, 201)


def get_slot(slot_id, headers=None):
    response = api_client.get_placement_slot(slot_id, headers or make_admin_headers())
    return get_success_data(response)


def confirm_slot(slot_id):
    response = api_client.confirm_placement_slot(
        slot_id, make_partner_manager_headers()
    )
    return get_success_data(response)


def release_slot(slot_id, **overrides):
    response = api_client.release_placement_slot(
        slot_id, F.release_payload(**overrides), make_partner_manager_headers()
    )
    return get_success_data(response)


# ── Redemptions (PRD §3.7) ──────────────────────────────────────────────────


def create_redemption(offer_id, membership_id, **overrides):
    """Reserve a redemption; the response is the only place the token appears."""
    response = api_client.create_redemption(
        F.redemption_payload(offer_id, membership_id, **overrides),
        make_employee_headers(membership_id),
    )
    return get_success_data(response, 201)


def get_redemption(redemption_id, headers=None, membership_id=None, merchant_id=None):
    if headers is None:
        if membership_id:
            headers = make_employee_headers(membership_id)
        elif merchant_id:
            headers = make_merchant_headers(merchant_id)
        else:
            headers = make_admin_headers()
    response = api_client.get_redemption(redemption_id, headers)
    return get_success_data(response)


def verify_redemption(redemption, merchant_id, gross_amount_cents=None,
                      verification_token=None):
    """Verify at the till with the token minted at creation."""
    token = verification_token or redemption["verification_token"]
    gross = (gross_amount_cents if gross_amount_cents is not None
             else redemption["intended_gross_amount_cents"])
    response = api_client.verify_redemption(
        redemption["id"], F.verify_payload(token, gross),
        make_merchant_headers(merchant_id),
    )
    return get_success_data(response)


def fulfill_redemption(redemption_id, merchant_id):
    response = api_client.fulfill_redemption(
        redemption_id, make_merchant_headers(merchant_id)
    )
    return get_success_data(response)


def void_redemption(redemption_id, membership_id=None):
    headers = (make_employee_headers(membership_id) if membership_id
               else make_admin_headers())
    response = api_client.void_redemption(redemption_id, headers)
    return get_success_data(response)


def verified_redemption(offer_id, membership_id, merchant_id,
                        gross_amount_cents=None, **overrides):
    """Reserve then verify one redemption, returning the verified row.

    The creation response is kept on the returned dict under
    ``verification_token`` so callers that need the secret still have it.
    """
    created = create_redemption(offer_id, membership_id, **overrides)
    verified = verify_redemption(created, merchant_id, gross_amount_cents)
    verified["verification_token"] = created.get("verification_token")
    return verified


# ── Disputes (PRD §3.8) ─────────────────────────────────────────────────────


def file_dispute(redemption_id, membership_id, **overrides):
    response = api_client.create_dispute(
        redemption_id, F.dispute_payload(**overrides),
        make_employee_headers(membership_id),
    )
    return get_success_data(response, 201)


def respond_dispute(dispute_id, merchant_id, **overrides):
    response = api_client.respond_dispute(
        dispute_id, F.dispute_response_payload(**overrides),
        make_merchant_headers(merchant_id),
    )
    return get_success_data(response)


def request_dispute_info(dispute_id):
    response = api_client.request_dispute_info(dispute_id, make_admin_headers())
    return get_success_data(response)


def resolve_dispute(dispute_id, outcome, **overrides):
    response = api_client.resolve_dispute(
        dispute_id, F.resolve_payload(outcome, **overrides), make_admin_headers()
    )
    return get_success_data(response)


def get_dispute(dispute_id, headers=None):
    response = api_client.get_dispute(dispute_id, headers or make_admin_headers())
    return get_success_data(response)


# ── Statements and ledger (PRD §3.9) ────────────────────────────────────────


def create_statement(employer_id, **overrides):
    response = api_client.create_statement(
        F.statement_payload(employer_id, **overrides), make_partner_manager_headers()
    )
    return get_success_data(response, 201)


def finalize_statement(statement_id):
    response = api_client.finalize_statement(
        statement_id, make_partner_manager_headers()
    )
    return get_success_data(response)


def pay_statement(statement_id, **overrides):
    response = api_client.pay_statement(
        statement_id, F.pay_payload(**overrides), make_admin_headers()
    )
    return get_success_data(response)


def redemption_ledger_entries(redemption_id, headers=None, **params):
    """The redemption's ledger rows, ordered by `created_at` ASC."""
    query = {"limit": C.MAX_PAGE_LIMIT}
    query.update(params)
    response = api_client.list_redemption_ledger_entries(
        redemption_id, headers or make_admin_headers(), params=query
    )
    return get_success_data(response)


def ledger_entries(headers=None, **params):
    query = {"limit": C.MAX_PAGE_LIMIT}
    query.update(params)
    response = api_client.list_ledger_entries(
        headers or make_admin_headers(), params=query
    )
    return get_success_data(response)


# ── The whole spine in one call ─────────────────────────────────────────────


def live_program(record_count=1, commission_rate_bps=1200,
                 placement_fee_base_cents=36000, employer_revenue_share_bps=2500,
                 revenue_share_enabled=True, privacy_min_cohort_size=3,
                 category=PerkCategory.DINING, region_code=RegionCode.CA,
                 merchant_overrides=None, employer_overrides=None,
                 offer_overrides=None, records=None):
    """An `ACTIVE` partner, a `LIVE` employer and one `ACTIVE` offer.

    Returns ``{"merchant", "agreement", "employer", "file", "memberships",
    "offer"}``.  This is the state almost every redemption-side scenario needs,
    and every row is re-read after the last mutation so versions are current.
    """
    partner = active_partner(
        merchant_overrides=merchant_overrides,
        commission_rate_bps=commission_rate_bps,
        placement_fee_base_cents=placement_fee_base_cents,
        employer_revenue_share_bps=employer_revenue_share_bps,
        category=category, region_code=region_code,
    )
    program = live_employer(
        record_count=record_count, records=records,
        revenue_share_enabled=revenue_share_enabled,
        privacy_min_cohort_size=privacy_min_cohort_size,
        featured_categories=[category], region_code=region_code,
        **(employer_overrides or {}),
    )
    offer = approved_offer(
        partner["agreement"]["id"], partner["merchant"]["id"],
        region_codes=[region_code],
        **(offer_overrides or {}),
    )
    return {
        "merchant": get_merchant(partner["merchant"]["id"]),
        "agreement": get_agreement(partner["agreement"]["id"]),
        "employer": program["employer"],
        "file": program["file"],
        "memberships": program["memberships"],
        "offer": offer,
    }
