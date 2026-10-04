"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API —
the runner restarts the server before every test, so nothing is shared.
Ownership-gated calls always thread the entity-backed id into the headers.
"""
from typing import Any, Dict, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_buyer_payload,
    create_certification_program_payload,
    create_dispute_payload,
    create_guarantee_payload,
    create_inspection_report_payload,
    create_lease_payload,
    create_listing_payload,
    create_offer_payload,
    create_payment_record_payload,
    create_property_manager_payload,
    create_seller_payload,
)
from .test_users import (
    CLAIMS_ADJUSTER_HEADERS,
    ESCROW_OFFICER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REVIEWER_HEADERS,
    make_buyer_headers,
    make_claims_adjuster_headers,
    make_property_manager_headers,
    make_reviewer_headers,
    make_seller_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: single-entity registration
# ---------------------------------------------------------------------------

def setup_seller(**overrides) -> Dict[str, Any]:
    resp = api_client.create_seller(create_seller_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    return get_success_data(resp)


def setup_buyer(**overrides) -> Dict[str, Any]:
    resp = api_client.create_buyer(create_buyer_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    return get_success_data(resp)


def setup_program(**overrides) -> Dict[str, Any]:
    resp = api_client.create_certification_program(
        create_certification_program_payload(**overrides), PLATFORM_ADMIN_HEADERS
    )
    return get_success_data(resp)


def setup_property_manager(**overrides) -> Dict[str, Any]:
    resp = api_client.create_property_manager(
        create_property_manager_payload(**overrides), PLATFORM_ADMIN_HEADERS
    )
    return get_success_data(resp)


def setup_draft_listing(seller: Dict[str, Any], **overrides) -> Dict[str, Any]:
    headers = make_seller_headers(seller["id"])
    resp = api_client.create_listing(create_listing_payload(seller["id"], **overrides), headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: inspection and lease attachments
# ---------------------------------------------------------------------------

def attach_verified_inspection(
    seller: Dict[str, Any],
    listing: Dict[str, Any],
    reviewer_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """Attach a report, SUBMIT as the seller, VERIFY as a distinct reviewer."""
    seller_h = make_seller_headers(seller["id"])
    resp = api_client.create_inspection_report(
        listing["id"], create_inspection_report_payload(**overrides), seller_h
    )
    report = get_success_data(resp)
    api_client.transition_inspection_report(report["id"], {"action": "SUBMIT"}, seller_h)
    reviewer_h = make_reviewer_headers(reviewer_id) if reviewer_id else REVIEWER_HEADERS
    resp = api_client.transition_inspection_report(report["id"], {"action": "VERIFY"}, reviewer_h)
    return get_success_data(resp)


def attach_lease(seller: Dict[str, Any], listing: Dict[str, Any], **overrides) -> Dict[str, Any]:
    seller_h = make_seller_headers(seller["id"])
    resp = api_client.create_lease(listing["id"], create_lease_payload(**overrides), seller_h)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: listing lifecycle
# ---------------------------------------------------------------------------

def certify_listing(seller: Dict[str, Any], listing: Dict[str, Any]) -> Dict[str, Any]:
    seller_h = make_seller_headers(seller["id"])
    api_client.transition_listing(listing["id"], {"action": "SUBMIT"}, seller_h)
    api_client.transition_listing(listing["id"], {"action": "BEGIN_REVIEW"}, REVIEWER_HEADERS)
    resp = api_client.transition_listing(listing["id"], {"action": "CERTIFY"}, REVIEWER_HEADERS)
    return get_success_data(resp)


def publish_listing(seller: Dict[str, Any], listing: Dict[str, Any]) -> Dict[str, Any]:
    seller_h = make_seller_headers(seller["id"])
    resp = api_client.transition_listing(listing["id"], {"action": "PUBLISH"}, seller_h)
    return get_success_data(resp)


def setup_certified_listing(
    with_lease: bool = False,
    program_overrides: Optional[Dict[str, Any]] = None,
    listing_overrides: Optional[Dict[str, Any]] = None,
    inspection_overrides: Optional[Dict[str, Any]] = None,
    lease_overrides: Optional[Dict[str, Any]] = None,
    disclose_lease: bool = False,
) -> Dict[str, Any]:
    """Seller + program + listing carried to CERTIFIED.

    Returns {seller, program, listing, inspection, lease?}. The returned
    ``listing`` is re-read at the end so its ``version`` is current.
    """
    seller = setup_seller()
    program = setup_program(**(program_overrides or {}))
    l_over = {"certification_program_id": program["id"]}
    l_over.update(listing_overrides or {})
    listing = setup_draft_listing(seller, **l_over)
    inspection = attach_verified_inspection(seller, listing, **(inspection_overrides or {}))
    lease = None
    if with_lease:
        lease = attach_lease(seller, listing, **(lease_overrides or {}))
        if disclose_lease:
            seller_h = make_seller_headers(seller["id"])
            resp = api_client.transition_lease(lease["id"], {"action": "DISCLOSE"}, seller_h)
            lease = get_success_data(resp)
    listing = certify_listing(seller, listing)
    listing = get_success_data(
        api_client.get_listing(listing["id"], make_seller_headers(seller["id"]))
    )
    result = {"seller": seller, "program": program, "listing": listing, "inspection": inspection}
    if lease is not None:
        result["lease"] = lease
    return result


def setup_listed_listing(**kwargs) -> Dict[str, Any]:
    """setup_certified_listing carried through PUBLISH to LISTED."""
    ctx = setup_certified_listing(**kwargs)
    seller_h = make_seller_headers(ctx["seller"]["id"])
    ctx["listing"] = publish_listing(ctx["seller"], ctx["listing"])
    ctx["listing"] = get_success_data(api_client.get_listing(ctx["listing"]["id"], seller_h))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: offer / escrow lifecycle
# ---------------------------------------------------------------------------

def create_offer_for(
    buyer: Dict[str, Any], listing_id: str, listing_version: int, **overrides
) -> Dict[str, Any]:
    buyer_h = make_buyer_headers(buyer["id"])
    resp = api_client.create_offer(
        listing_id,
        create_offer_payload(buyer["id"], listing_version, **overrides),
        buyer_h,
    )
    return get_success_data(resp)


def submit_offer(buyer: Dict[str, Any], offer: Dict[str, Any]) -> Dict[str, Any]:
    buyer_h = make_buyer_headers(buyer["id"])
    resp = api_client.transition_offer(offer["id"], {"action": "SUBMIT"}, buyer_h)
    return get_success_data(resp)


def get_offer_escrow(buyer: Dict[str, Any], offer: Dict[str, Any]) -> Dict[str, Any]:
    """Read the single escrow attached to an accepted offer."""
    buyer_h = make_buyer_headers(buyer["id"])
    resp = api_client.get_offer_escrow(offer["id"], buyer_h)
    arr = get_success_data(resp)
    assert isinstance(arr, list) and len(arr) == 1, "accepted offer must have exactly one escrow"
    return arr[0]


def setup_accepted_offer(
    buyer_overrides: Optional[Dict[str, Any]] = None,
    offer_overrides: Optional[Dict[str, Any]] = None,
    listing_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """LISTED listing + buyer + submitted + accepted offer; escrow OPENED.

    Returns {seller, program, listing, buyer, offer, escrow, lease?, ...}.
    """
    ctx = setup_listed_listing(**(listing_kwargs or {}))
    buyer = setup_buyer(**(buyer_overrides or {}))
    offer = create_offer_for(buyer, ctx["listing"]["id"], ctx["listing"]["version"], **(offer_overrides or {}))
    offer = submit_offer(buyer, offer)
    seller_h = make_seller_headers(ctx["seller"]["id"])
    resp = api_client.transition_offer(offer["id"], {"action": "ACCEPT"}, seller_h)
    offer = get_success_data(resp)
    escrow = get_offer_escrow(buyer, offer)
    ctx.update({"buyer": buyer, "offer": offer, "escrow": escrow})
    return ctx


def send_docs(escrow: Dict[str, Any], officer_name: str = "Officer One") -> Dict[str, Any]:
    resp = api_client.transition_escrow(
        escrow["id"], {"action": "SEND_DOCS", "escrow_officer_name": officer_name}, ESCROW_OFFICER_HEADERS
    )
    return get_success_data(resp)


def sign_escrow(
    buyer: Dict[str, Any],
    offer: Dict[str, Any],
    remote_notarization_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-read the escrow for its current version, then sign (OCC-guarded)."""
    escrow = get_offer_escrow(buyer, offer)
    payload: Dict[str, Any] = {"expected_escrow_version": escrow["version"]}
    if remote_notarization_ref is not None:
        payload["remote_notarization_ref"] = remote_notarization_ref
    buyer_h = make_buyer_headers(buyer["id"])
    resp = api_client.sign_escrow(escrow["id"], payload, buyer_h)
    return get_success_data(resp)


def fund_escrow(buyer: Dict[str, Any], offer: Dict[str, Any], amount_cents: int) -> Dict[str, Any]:
    escrow = get_offer_escrow(buyer, offer)
    buyer_h = make_buyer_headers(buyer["id"])
    resp = api_client.fund_escrow(escrow["id"], {"funded_amount_cents": amount_cents}, buyer_h)
    return get_success_data(resp)


def close_escrow(escrow_id: str) -> Dict[str, Any]:
    resp = api_client.transition_escrow(escrow_id, {"action": "CLOSE"}, ESCROW_OFFICER_HEADERS)
    return get_success_data(resp)


def setup_signed_escrow(ctx: Dict[str, Any], remote_notarization_ref: Optional[str] = None) -> Dict[str, Any]:
    """Advance an accepted-offer context to Escrow SIGNED."""
    ctx["escrow"] = send_docs(ctx["escrow"])
    ctx["escrow"] = sign_escrow(ctx["buyer"], ctx["offer"], remote_notarization_ref)
    return ctx


def setup_funded_escrow(ctx: Dict[str, Any], remote_notarization_ref: Optional[str] = None) -> Dict[str, Any]:
    """Advance an accepted-offer context to Escrow FUNDED."""
    ctx = setup_signed_escrow(ctx, remote_notarization_ref)
    ctx["escrow"] = fund_escrow(ctx["buyer"], ctx["offer"], ctx["offer"]["amount_cents"])
    return ctx


def setup_closed_sale(
    with_lease: bool = True,
    with_referral: bool = False,
    guarantee: Optional[Dict[str, Any]] = None,
    pm_overrides: Optional[Dict[str, Any]] = None,
    lease_overrides: Optional[Dict[str, Any]] = None,
    buyer_overrides: Optional[Dict[str, Any]] = None,
    offer_overrides: Optional[Dict[str, Any]] = None,
    listing_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full pipeline through Escrow CLOSED -> Listing SOLD.

    Guarantees must exist (ISSUED) before the close so the cascade activates
    them; referrals likewise must be REFERRED/ACCEPTED before the close.
    """
    lkw = dict(listing_kwargs or {})
    if with_lease:
        lkw.setdefault("with_lease", True)
        if lease_overrides:
            lkw["lease_overrides"] = lease_overrides

    # Build to LISTED first so the guarantee can be issued while the listing is
    # CERTIFIED/LISTED (PRD §3.9 forbids issuance once UNDER_CONTRACT).
    ctx = setup_listed_listing(**lkw)

    if guarantee is not None:
        resp = api_client.create_guarantee(
            ctx["listing"]["id"], create_guarantee_payload(**guarantee), PLATFORM_ADMIN_HEADERS
        )
        ctx["guarantee"] = get_success_data(resp)

    buyer = setup_buyer(**(buyer_overrides or {}))
    offer = create_offer_for(buyer, ctx["listing"]["id"], ctx["listing"]["version"], **(offer_overrides or {}))
    offer = submit_offer(buyer, offer)
    seller_h = make_seller_headers(ctx["seller"]["id"])
    resp = api_client.transition_offer(offer["id"], {"action": "ACCEPT"}, seller_h)
    offer = get_success_data(resp)
    escrow = get_offer_escrow(buyer, offer)
    ctx.update({"buyer": buyer, "offer": offer, "escrow": escrow})

    if with_referral:
        pm = setup_property_manager(**(pm_overrides or {}))
        resp = api_client.create_management_referral(
            ctx["listing"]["id"], {"property_manager_id": pm["id"]}, PLATFORM_ADMIN_HEADERS
        )
        referral = get_success_data(resp)
        resp = api_client.transition_management_referral(
            referral["id"], {"action": "ACCEPT"}, make_property_manager_headers(pm["id"])
        )
        referral = get_success_data(resp)
        ctx.update({"pm": pm, "referral": referral})

    # setup_funded_escrow already advances through SIGNED; do not sign twice.
    ctx = setup_funded_escrow(ctx)
    ctx["escrow"] = close_escrow(ctx["escrow"]["id"])
    seller_h = make_seller_headers(ctx["seller"]["id"])
    ctx["listing"] = get_success_data(api_client.get_listing(ctx["listing"]["id"], seller_h))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: claims / disputes
# ---------------------------------------------------------------------------

def claim_guarantee(buyer: Dict[str, Any], guarantee: Dict[str, Any]) -> Dict[str, Any]:
    buyer_h = make_buyer_headers(buyer["id"])
    resp = api_client.transition_guarantee(guarantee["id"], {"action": "CLAIM"}, buyer_h)
    return get_success_data(resp)


def open_dispute(
    listing_id: str,
    opener_headers: Dict[str, str],
    **overrides,
) -> Dict[str, Any]:
    resp = api_client.create_dispute(listing_id, create_dispute_payload(**overrides), opener_headers)
    return get_success_data(resp)


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, PLATFORM_ADMIN_HEADERS)
    return get_success_data(resp)
