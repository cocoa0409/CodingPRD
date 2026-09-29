"""Setup builders: each one drives the real API and returns the created resource.

Setup calls use ``get_success_data`` so a setup failure surfaces as a readable
error rather than a status-code assertion inside a helper. Tests then make their
own assertions against the resource the builder returns.

Every builder accepts ``**overrides`` which are forwarded to the matching payload
factory, so a test can tune exactly the one dial it cares about.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient, shift_instant
from .constants import (
    CABIN_ECONOMY,
    CHANNEL_KIND_NDC_AGGREGATOR,
    CLOCK_STARTUP_UTC,
    CONTENT_TIER_STANDARD,
    DECISION_CERTIFY,
    FILING_ACTIVE,
    FILING_FILED,
    ITEM_SCOPE_ALL,
    ITEM_SCOPE_ANCILLARY,
    FULFILLMENT_ACTION_TICKET,
    NEGOTIATION_ACCEPT,
    PARTNER_TYPE_CORPORATE,
    PARTNER_TYPE_TECH_PROVIDER,
    PARTNER_TYPE_TRAVEL_AGENCY,
    PAYMENT_ACTION_CAPTURE,
    READINESS_STRICT,
    REVIEW_APPROVE,
    REVIEW_START_REVIEW,
    TEST_PASSED,
)
from .test_users import (
    ADMIN_HEADERS,
    DISTRIBUTION_MANAGER_HEADERS,
    OTHER_DISTRIBUTION_MANAGER_HEADERS,
    PRICING_ANALYST_HEADERS,
    agency_headers,
    technology_partner_headers,
)

Resource = Dict[str, Any]


# --- clock ----------------------------------------------------------------
def set_clock(api: ApiClient, current_utc: str) -> Resource:
    return get_success_data(api.set_clock(current_utc, headers=ADMIN_HEADERS))


def advance_clock(api: ApiClient, *, minutes: int = 0, days: int = 0) -> Resource:
    return set_clock(api, shift_instant(CLOCK_STARTUP_UTC, minutes=minutes, days=days))


# --- channels -------------------------------------------------------------
def create_channel(api: ApiClient, **overrides: Any) -> Resource:
    payload = f.channel_payload(**overrides)
    return get_success_data(api.create_channel(payload, headers=ADMIN_HEADERS))


def create_full_channel(api: ApiClient, **overrides: Any) -> Resource:
    payload = f.full_channel_payload(**overrides)
    return get_success_data(api.create_channel(payload, headers=ADMIN_HEADERS))


def revise_content_policy(api: ApiClient, channel_id: str, **overrides: Any) -> Resource:
    payload = f.content_policy_payload(**overrides)
    return get_success_data(
        api.patch_channel_content_policy(channel_id, payload, headers=DISTRIBUTION_MANAGER_HEADERS)
    )


def add_surcharge_rule(api: ApiClient, channel_id: str, **overrides: Any) -> Resource:
    payload = f.surcharge_rule_payload(**overrides)
    return get_success_data(api.create_surcharge_rule(channel_id, payload, headers=ADMIN_HEADERS))


def read_channel(api: ApiClient, channel_id: str, headers: Optional[Dict[str, str]] = None) -> Resource:
    return get_success_data(api.get_channel(channel_id, headers=headers or ADMIN_HEADERS))


# --- partners -------------------------------------------------------------
def create_partner(api: ApiClient, **overrides: Any) -> Resource:
    payload = f.partner_payload(**overrides)
    return get_success_data(api.create_partner(payload, headers=ADMIN_HEADERS))


def create_agency_partner(api: ApiClient, **overrides: Any) -> Resource:
    overrides.setdefault("partner_type", PARTNER_TYPE_TRAVEL_AGENCY)
    return create_partner(api, **overrides)


def create_tech_partner(api: ApiClient, **overrides: Any) -> Resource:
    overrides.setdefault("partner_type", PARTNER_TYPE_TECH_PROVIDER)
    overrides.setdefault("partner_name", "Tango Systems")
    return create_partner(api, **overrides)


def create_corporate_partner(api: ApiClient, **overrides: Any) -> Resource:
    overrides.setdefault("partner_type", PARTNER_TYPE_CORPORATE)
    overrides.setdefault("partner_name", "Acme Industries")
    return create_partner(api, **overrides)


def read_partner(api: ApiClient, partner_id: str) -> Resource:
    return get_success_data(api.get_partner(partner_id, headers=ADMIN_HEADERS))


# --- fare filings ---------------------------------------------------------
def create_fare_filing(api: ApiClient, **overrides: Any) -> Resource:
    payload = f.fare_filing_payload(**overrides)
    return get_success_data(api.create_fare_filing(payload, headers=PRICING_ANALYST_HEADERS))


def drive_filing(
    api: ApiClient,
    filing_id: str,
    to_state: str,
    headers: Optional[Dict[str, str]] = None,
    reason: Optional[str] = None,
) -> Resource:
    payload = f.filing_state_payload(to_state, reason=reason)
    return get_success_data(
        api.set_fare_filing_state(filing_id, payload, headers=headers or PRICING_ANALYST_HEADERS)
    )


def create_filed_filing(api: ApiClient, **overrides: Any) -> Resource:
    filing = create_fare_filing(api, **overrides)
    return drive_filing(api, filing["id"], FILING_FILED)


def create_active_filing(api: ApiClient, **overrides: Any) -> Resource:
    filing = create_filed_filing(api, **overrides)
    return drive_filing(api, filing["id"], FILING_ACTIVE)


def read_filing(api: ApiClient, filing_id: str) -> Resource:
    return get_success_data(api.get_fare_filing(filing_id, headers=PRICING_ANALYST_HEADERS))


def file_revision(api: ApiClient, filing_id: str, expected_version: int, **overrides: Any) -> Resource:
    payload = f.revision_payload(expected_version, **overrides)
    return get_success_data(
        api.create_fare_filing_revision(filing_id, payload, headers=PRICING_ANALYST_HEADERS)
    )


# --- ancillaries and bundles ---------------------------------------------
def create_ancillary(api: ApiClient, **overrides: Any) -> Resource:
    payload = f.ancillary_payload(**overrides)
    return get_success_data(api.create_ancillary_product(payload, headers=PRICING_ANALYST_HEADERS))


def create_bundle(api: ApiClient, **overrides: Any) -> Resource:
    payload = f.bundle_payload(**overrides)
    return get_success_data(api.create_bundle_definition(payload, headers=PRICING_ANALYST_HEADERS))


# --- agency agreements ---------------------------------------------------
def open_agreement(
    api: ApiClient,
    partner_id: str,
    channel_id: str,
    expected_partner_version: int,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Resource:
    payload = f.agreement_payload(partner_id, channel_id, expected_partner_version, **overrides)
    return get_success_data(
        api.create_agency_agreement(payload, headers=headers or DISTRIBUTION_MANAGER_HEADERS)
    )


def negotiate(
    api: ApiClient,
    agreement_id: str,
    action: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Resource:
    payload = f.negotiation_payload(action, **overrides)
    return get_success_data(
        api.create_negotiation_round(
            agreement_id, payload, headers=headers or DISTRIBUTION_MANAGER_HEADERS
        )
    )


def sign_agreement(api: ApiClient, agreement_id: str) -> Resource:
    """ACCEPT by a manager other than the proposer, as segregation of duties demands."""
    return negotiate(
        api, agreement_id, NEGOTIATION_ACCEPT, headers=OTHER_DISTRIBUTION_MANAGER_HEADERS
    )


def create_signed_agreement(
    api: ApiClient,
    partner_id: str,
    channel_id: str,
    expected_partner_version: int,
    **overrides: Any,
) -> Resource:
    agreement = open_agreement(
        api, partner_id, channel_id, expected_partner_version, **overrides
    )
    return sign_agreement(api, agreement["id"])


def read_agreement(api: ApiClient, agreement_id: str) -> Resource:
    return get_success_data(api.get_agency_agreement(agreement_id, headers=ADMIN_HEADERS))


# --- corporate contracts -------------------------------------------------
def create_contract(
    api: ApiClient,
    corporate_partner_id: str,
    negotiated_fare_filing_id: str,
    effective_from: str = "2026-07-01T00:00:00.000Z",
    effective_to: str = "2027-01-01T00:00:00.000Z",
    **overrides: Any,
) -> Resource:
    payload = f.contract_payload(
        corporate_partner_id,
        negotiated_fare_filing_id,
        effective_from,
        effective_to,
        **overrides,
    )
    return get_success_data(
        api.create_corporate_contract(payload, headers=DISTRIBUTION_MANAGER_HEADERS)
    )


def read_contract(api: ApiClient, contract_id: str, headers: Optional[Dict[str, str]] = None) -> Resource:
    return get_success_data(
        api.get_corporate_contract(contract_id, headers=headers or DISTRIBUTION_MANAGER_HEADERS)
    )


# --- offers ---------------------------------------------------------------
def construct_offer(
    api: ApiClient,
    channel_id: str,
    partner_id: str,
    fare_filing_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Resource:
    payload = f.offer_payload(channel_id, partner_id, fare_filing_id, **overrides)
    return get_success_data(
        api.create_offer(payload, headers=headers or DISTRIBUTION_MANAGER_HEADERS)
    )


def publish_offer(
    api: ApiClient,
    offer_id: str,
    disclosure_ack_codes: Optional[Sequence[str]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Resource:
    payload = f.publish_payload(disclosure_ack_codes)
    return get_success_data(
        api.publish_offer(offer_id, payload, headers=headers or DISTRIBUTION_MANAGER_HEADERS)
    )


def read_offer(api: ApiClient, offer_id: str, headers: Optional[Dict[str, str]] = None) -> Resource:
    return get_success_data(api.get_offer(offer_id, headers=headers or DISTRIBUTION_MANAGER_HEADERS))


def read_offer_items(
    api: ApiClient, offer_id: str, headers: Optional[Dict[str, str]] = None
) -> List[Resource]:
    response = api.list_offer_items(
        offer_id, headers=headers or DISTRIBUTION_MANAGER_HEADERS, params={"limit": 100}
    )
    return get_success_data(response)


# --- orders ---------------------------------------------------------------
def create_order(
    api: ApiClient,
    offer_id: str,
    disclosure_ack_codes: Optional[Sequence[str]] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Resource:
    payload = f.order_payload(offer_id, disclosure_ack_codes=disclosure_ack_codes, **overrides)
    return get_success_data(
        api.create_order(payload, headers=headers or DISTRIBUTION_MANAGER_HEADERS)
    )


def capture_payment(
    api: ApiClient,
    order_id: str,
    payment_amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Resource:
    payload = f.payment_payload(PAYMENT_ACTION_CAPTURE, payment_amount_cents)
    return get_success_data(
        api.post_order_payment(order_id, payload, headers=headers or DISTRIBUTION_MANAGER_HEADERS)
    )


def advance_payment(
    api: ApiClient, order_id: str, action: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Resource:
    payload = f.payment_payload(action, **overrides)
    return get_success_data(
        api.post_order_payment(order_id, payload, headers=headers or DISTRIBUTION_MANAGER_HEADERS)
    )


def advance_fulfillment(
    api: ApiClient, order_id: str, action: str, headers: Optional[Dict[str, str]] = None
) -> Resource:
    payload = f.fulfillment_payload(action)
    return get_success_data(
        api.post_order_fulfillment(
            order_id, payload, headers=headers or DISTRIBUTION_MANAGER_HEADERS
        )
    )


def ticket_order(api: ApiClient, order_id: str) -> Resource:
    return advance_fulfillment(api, order_id, FULFILLMENT_ACTION_TICKET)


def read_order(api: ApiClient, order_id: str, headers: Optional[Dict[str, str]] = None) -> Resource:
    return get_success_data(api.get_order(order_id, headers=headers or DISTRIBUTION_MANAGER_HEADERS))


# --- service requests ----------------------------------------------------
def open_service_request(
    api: ApiClient,
    order_id: str,
    request_type: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Resource:
    payload = f.service_request_payload(request_type, **overrides)
    return get_success_data(
        api.create_service_request(
            order_id, payload, headers=headers or DISTRIBUTION_MANAGER_HEADERS
        )
    )


def review_service_request(
    api: ApiClient, request_id: str, action: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Resource:
    payload = f.review_payload(action, **overrides)
    return get_success_data(
        api.review_service_request(
            request_id, payload, headers=headers or DISTRIBUTION_MANAGER_HEADERS
        )
    )


def approve_service_request(api: ApiClient, request_id: str) -> Resource:
    review_service_request(api, request_id, REVIEW_START_REVIEW)
    return review_service_request(api, request_id, REVIEW_APPROVE)


def apply_service_request(
    api: ApiClient, request_id: str, headers: Optional[Dict[str, str]] = None
) -> Resource:
    return get_success_data(
        api.apply_service_request(request_id, {}, headers=headers or DISTRIBUTION_MANAGER_HEADERS)
    )


def read_service_request(api: ApiClient, request_id: str, order_id: str) -> Resource:
    rows = get_success_data(
        api.list_service_requests(order_id, headers=DISTRIBUTION_MANAGER_HEADERS, params={"limit": 100})
    )
    matches = [row for row in rows if row["id"] == request_id]
    assert matches, f"service request {request_id} not listed under order {order_id}"
    return matches[0]


# --- certifications ------------------------------------------------------
def open_certification(
    api: ApiClient,
    partner_id: str,
    channel_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Resource:
    payload = f.certification_payload(partner_id, channel_id, **overrides)
    return get_success_data(
        api.create_certification(payload, headers=headers or technology_partner_headers(partner_id))
    )


def schedule_test(
    api: ApiClient,
    certification_id: str,
    partner_id: str,
    test_code: str,
    scheduled_start: str,
    duration_minutes: int = 60,
    is_mandatory: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Resource:
    payload = f.connectivity_test_payload(
        test_code, scheduled_start, duration_minutes, is_mandatory, **overrides
    )
    return get_success_data(
        api.create_connectivity_test(
            certification_id, payload, headers=headers or technology_partner_headers(partner_id)
        )
    )


def report_outcome(
    api: ApiClient,
    test_id: str,
    partner_id: str,
    outcome: str = TEST_PASSED,
    score: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Resource:
    payload = f.outcome_payload(outcome, score)
    return get_success_data(
        api.post_test_outcome(
            test_id, payload, headers=headers or technology_partner_headers(partner_id)
        )
    )


def record_decision(
    api: ApiClient,
    certification_id: str,
    decision: str = DECISION_CERTIFY,
    readiness_variant: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Resource:
    payload = f.decision_payload(decision, readiness_variant)
    return get_success_data(
        api.post_certification_decision(certification_id, payload, headers=headers or ADMIN_HEADERS)
    )


def read_certification(
    api: ApiClient, certification_id: str, headers: Optional[Dict[str, str]] = None
) -> Resource:
    return get_success_data(api.get_certification(certification_id, headers=headers or ADMIN_HEADERS))


def read_connectivity_tests(
    api: ApiClient, certification_id: str, headers: Optional[Dict[str, str]] = None
) -> List[Resource]:
    return get_success_data(
        api.list_connectivity_tests(
            certification_id, headers=headers or ADMIN_HEADERS, params={"limit": 100}
        )
    )


def certify_partner(
    api: ApiClient,
    partner_id: str,
    channel_id: str,
    score: int = 100,
    readiness_variant: str = READINESS_STRICT,
    env_code: Optional[str] = None,
    test_code: str = "SHOP_SEARCH",
    scheduled_start: str = "2026-08-03T09:00:00.000Z",
) -> Resource:
    """Open a certification, pass one mandatory test and record a CERTIFY decision."""
    kwargs: Dict[str, Any] = {}
    if env_code is not None:
        kwargs["env_code"] = env_code
    certification = open_certification(api, partner_id, channel_id, **kwargs)
    test = schedule_test(
        api,
        certification["id"],
        partner_id,
        test_code,
        scheduled_start,
        60,
        True,
    )
    report_outcome(api, test["id"], partner_id, TEST_PASSED, score)
    return record_decision(api, certification["id"], DECISION_CERTIFY, readiness_variant)


# =============================================================================
# Shared scenario builders
#
# Several tests price content through the same aggregator channel configuration,
# so the channel, its two surcharge rules and its catalogue are built by the
# helpers below rather than repeated inline.
# =============================================================================

NDC_CHANNEL_CODE = "NDC_AGG"
NDC_DISCLOSURE_CODES = ["DOT-FARE-INCL"]
NDC_FARE_BASIS = "YNDC01"
NDC_FARE_BASE_CENTS = 45010
BIG_FARE_BASIS = "YNDC02"
BIG_FARE_BASE_CENTS = 5000000

ANCILLARY_BAG = "BAG20"
ANCILLARY_SEAT = "SEAT_STD"
ANCILLARY_WIFI = "WIFI_FULL"
BUNDLE_FLEX = "BND_FLEX"

SURCHARGE_ANCILLARY_CODE = "ANC_DISTR"
SURCHARGE_ALL_CODE = "DISTR_FEE"


def create_ndc_channel(api: ApiClient, with_surcharge_rules: bool = True, **overrides: Any) -> Resource:
    """The aggregator channel: markup 0.035, incentive multiplier 1.25, one disclosure code."""
    defaults: Dict[str, Any] = {
        "channel_code": NDC_CHANNEL_CODE,
        "channel_kind": CHANNEL_KIND_NDC_AGGREGATOR,
        "content_tier": CONTENT_TIER_STANDARD,
        "content_markup_pct": 0.035,
        "incentive_multiplier": 1.25,
        "monthly_platform_fee_cents": 400000,
        "per_message_cost_cents": 12,
        "per_segment_fee_cents": 40,
        "servicing_parity_change": True,
        "servicing_parity_refund": True,
        "required_disclosure_codes": list(NDC_DISCLOSURE_CODES),
    }
    defaults.update(overrides)
    channel = create_full_channel(api, **defaults)
    if with_surcharge_rules:
        add_surcharge_rule(
            api,
            channel["id"],
            surcharge_code=SURCHARGE_ANCILLARY_CODE,
            item_scope=ITEM_SCOPE_ANCILLARY,
            rate_pct=0.05,
            threshold_cents=10000,
            min_cents=0,
            max_cents=400,
        )
        add_surcharge_rule(
            api,
            channel["id"],
            surcharge_code=SURCHARGE_ALL_CODE,
            item_scope=ITEM_SCOPE_ALL,
            rate_pct=0.02,
            threshold_cents=50000,
            min_cents=500,
            max_cents=1200,
        )
    return channel


def create_ndc_catalogue(api: ApiClient) -> Dict[str, Resource]:
    """Three ancillaries and the bundle that groups the first two at a 10% discount."""
    bag = create_ancillary(
        api,
        ancillary_code=ANCILLARY_BAG,
        name="Checked bag 20kg",
        list_amount_cents=7010,
        min_content_tier_rank=1,
        refundable=True,
    )
    seat = create_ancillary(
        api,
        ancillary_code=ANCILLARY_SEAT,
        name="Standard seat",
        list_amount_cents=3010,
        min_content_tier_rank=1,
        refundable=False,
    )
    wifi = create_ancillary(
        api,
        ancillary_code=ANCILLARY_WIFI,
        name="Full-flight wifi",
        list_amount_cents=1010,
        min_content_tier_rank=1,
        refundable=False,
    )
    bundle = create_bundle(
        api,
        bundle_code=BUNDLE_FLEX,
        ancillary_codes=[ANCILLARY_BAG, ANCILLARY_SEAT],
        bundle_discount_pct=0.10,
        min_content_tier_rank=1,
    )
    return {"bag": bag, "seat": seat, "wifi": wifi, "bundle": bundle}


def create_ndc_filing(api: ApiClient, **overrides: Any) -> Resource:
    """The economy fare filing driven all the way to ACTIVE."""
    defaults: Dict[str, Any] = {
        "fare_basis_code": NDC_FARE_BASIS,
        "cabin": CABIN_ECONOMY,
        "base_amount_cents": NDC_FARE_BASE_CENTS,
        "min_content_tier_rank": 1,
        "refundable": True,
        "is_private": False,
    }
    defaults.update(overrides)
    return create_active_filing(api, **defaults)


def create_alpha_agency(api: ApiClient, **overrides: Any) -> Resource:
    defaults: Dict[str, Any] = {
        "partner_name": "Alpha Travel GmbH",
        "iata_code": "12345675",
        "home_country": "DE",
    }
    defaults.update(overrides)
    return create_agency_partner(api, **defaults)
