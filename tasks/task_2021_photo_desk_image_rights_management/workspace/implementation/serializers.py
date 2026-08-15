"""Entity serializers — convert internal dicts to API response shapes.

Handles lazy derivation for License (ACTIVE -> EXPIRED when valid_to <= now)
and ReleaseRecord (ACTIVE -> EXPIRED when expires_at <= now), plus computed
fields like Image.rights_reverted and Image.rights_reversion_at.
"""

from db import (
    logical_now, iso_now_str, photographers, images as images_store,
)


def serialize_photographer(p: dict) -> dict:
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "email": p["email"],
        "photographer_type": p["photographer_type"],
        "day_rate_cents": p["day_rate_cents"],
        "per_image_fee_cents": p["per_image_fee_cents"],
        "royalty_rate_per_use_cents": p["royalty_rate_per_use_cents"],
        "rights_reversion_months": p["rights_reversion_months"],
        "status": p["status"],
        "accrued_earnings_cents": p["accrued_earnings_cents"],
        "paid_out_cents": p["paid_out_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_story_request(sr: dict) -> dict:
    return {
        "id": sr["id"],
        "headline": sr["headline"],
        "slug": sr["slug"],
        "needed_by": sr["needed_by"],
        "budget_cents": sr["budget_cents"],
        "committed_cents": sr["committed_cents"],
        "decision": sr["decision"],
        "commissioned_assignment_id": sr["commissioned_assignment_id"],
        "sourced_image_id": sr["sourced_image_id"],
        "status": sr["status"],
        "created_at": sr["created_at"],
        "updated_at": sr["updated_at"],
        "version": sr["version"],
    }


def serialize_assignment(a: dict) -> dict:
    return {
        "id": a["id"],
        "story_request_id": a["story_request_id"],
        "photographer_id": a["photographer_id"],
        "brief": a["brief"],
        "shoot_start": a["shoot_start"],
        "shoot_end": a["shoot_end"],
        "min_image_count": a["min_image_count"],
        "max_image_count": a["max_image_count"],
        "day_count": a["day_count"],
        "revision_count": a["revision_count"],
        "accepted_at": a["accepted_at"],
        "kill_fee_cents": a["kill_fee_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def _image_rights_reversion_at(img: dict):
    """Return the rights_reversion_at ISO string or None."""
    if img["source_type"] != "ASSIGNMENT":
        return None
    return img.get("rights_reversion_at")


def _image_rights_reverted(img: dict) -> bool:
    rr = img.get("rights_reversion_at")
    if rr is None:
        return False
    from db import parse_iso
    rr_dt = parse_iso(rr)
    if rr_dt is None:
        return False
    return logical_now() >= rr_dt


def serialize_image(img: dict) -> dict:
    return {
        "id": img["id"],
        "photographer_id": img["photographer_id"],
        "assignment_id": img["assignment_id"],
        "source_type": img["source_type"],
        "agency_name": img["agency_name"],
        "base_license_fee_cents": img["base_license_fee_cents"],
        "caption": img["caption"],
        "credit_line": img["credit_line"],
        "keywords": img["keywords"],
        "has_identifiable_people": img["has_identifiable_people"],
        "has_private_property": img["has_private_property"],
        "embargo_until": img["embargo_until"],
        "status": img["status"],
        "restriction_status": img["restriction_status"],
        "times_used": img["times_used"],
        "first_published_at": img["first_published_at"],
        "rights_reversion_at": _image_rights_reversion_at(img),
        "rights_reverted": _image_rights_reverted(img),
        "created_at": img["created_at"],
        "updated_at": img["updated_at"],
        "version": img["version"],
    }


def _license_effective_status(lic: dict) -> str:
    """Lazy derivation: ACTIVE -> EXPIRED when valid_to <= logical now.

    Also performs the mutation + budget release side-effect on first observation.
    """
    from services.calculations import process_license_lazy_expiry
    process_license_lazy_expiry(lic)
    return lic["status"]


def serialize_license(lic: dict) -> dict:
    return {
        "id": lic["id"],
        "image_id": lic["image_id"],
        "story_request_id": lic["story_request_id"],
        "usage_scope": lic["usage_scope"],
        "territory": lic["territory"],
        "valid_from": lic["valid_from"],
        "valid_to": lic["valid_to"],
        "exclusive": lic["exclusive"],
        "pricing_variant": lic["pricing_variant"],
        "fee_cents": lic["fee_cents"],
        "superseded_by_id": lic["superseded_by_id"],
        "status": _license_effective_status(lic),
        "created_at": lic["created_at"],
        "updated_at": lic["updated_at"],
        "version": lic["version"],
    }


def _release_effective_status(rel: dict) -> str:
    """Lazy derivation: ACTIVE -> EXPIRED when expires_at non-null and <= now.

    Also performs the mutation on first observation.
    """
    from services.calculations import process_release_lazy_expiry
    process_release_lazy_expiry(rel)
    return rel["status"]


def serialize_release(rel: dict) -> dict:
    return {
        "id": rel["id"],
        "image_id": rel["image_id"],
        "subject_type": rel["subject_type"],
        "subject_name": rel["subject_name"],
        "document_ref": rel["document_ref"],
        "signed_at": rel["signed_at"],
        "expires_at": rel["expires_at"],
        "status": _release_effective_status(rel),
        "created_at": rel["created_at"],
        "updated_at": rel["updated_at"],
        "version": rel["version"],
    }


def serialize_usage_run(ur: dict) -> dict:
    return {
        "id": ur["id"],
        "image_id": ur["image_id"],
        "license_id": ur["license_id"],
        "channel": ur["channel"],
        "story_slug": ur["story_slug"],
        "published_at": ur["published_at"],
        "royalty_cents": ur["royalty_cents"],
        "created_at": ur["created_at"],
    }


def serialize_claim(c: dict) -> dict:
    return {
        "id": c["id"],
        "image_id": c["image_id"],
        "claimant_name": c["claimant_name"],
        "claim_type": c["claim_type"],
        "description": c["description"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "proposed_settlement_cents": c["proposed_settlement_cents"],
        "settlement_amount_cents": c["settlement_amount_cents"],
        "photographer_clawback_cents": c["photographer_clawback_cents"],
        "intaken_by_user_id": c["intaken_by_user_id"],
        "resolved_by_user_id": c["resolved_by_user_id"],
        "resolved_at": c["resolved_at"],
        "resolution_outcome": c["resolution_outcome"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_payment_run(pr: dict) -> dict:
    return {
        "id": pr["id"],
        "photographer_id": pr["photographer_id"],
        "period_start": pr["period_start"],
        "period_end": pr["period_end"],
        "method": pr["method"],
        "guarantee_amount_cents": pr["guarantee_amount_cents"],
        "royalty_amount_cents": pr["royalty_amount_cents"],
        "clawback_cents": pr["clawback_cents"],
        "total_cents": pr["total_cents"],
        "paid_at": pr["paid_at"],
        "status": pr["status"],
        "created_at": pr["created_at"],
        "updated_at": pr["updated_at"],
        "version": pr["version"],
    }
