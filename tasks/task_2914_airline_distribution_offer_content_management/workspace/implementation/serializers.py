"""Entity -> response payload serialization.

Mutable resources carry id / created_at / updated_at / version (PRD 2.4).
SurchargeRule and OfferItem are immutable and carry ONLY id and created_at:
updated_at and version are absent from the payload entirely.
"""
from decimal import Decimal

from store import iso


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _mutable(entity):
    return {
        "id": entity["id"],
        "created_at": iso(entity["created_at"]),
        "updated_at": iso(entity["updated_at"]),
        "version": entity["version"],
    }


def _immutable(entity):
    return {"id": entity["id"], "created_at": iso(entity["created_at"])}


def channel_out(channel):
    out = _mutable(channel)
    out.update({
        "channel_code": channel["channel_code"],
        "channel_kind": channel["channel_kind"],
        "content_tier": channel["content_tier"],
        "content_tier_rank": channel["content_tier_rank"],
        "content_markup_pct": num(channel["content_markup_pct"]),
        "incentive_multiplier": num(channel["incentive_multiplier"]),
        "monthly_platform_fee_cents": channel["monthly_platform_fee_cents"],
        "per_message_cost_cents": channel["per_message_cost_cents"],
        "per_segment_fee_cents": channel["per_segment_fee_cents"],
        "servicing_parity_change": channel["servicing_parity_change"],
        "servicing_parity_refund": channel["servicing_parity_refund"],
        "required_disclosure_codes": list(channel["required_disclosure_codes"]),
        "booking_count": channel["booking_count"],
        "activity_cost_cents": channel["activity_cost_cents"],
        "cost_per_booking_flat_cents": channel["cost_per_booking_flat_cents"],
        "cost_per_booking_activity_cents": channel["cost_per_booking_activity_cents"],
    })
    return out


def surcharge_rule_out(rule):
    out = _immutable(rule)
    out.update({
        "channel_id": rule["channel_id"],
        "surcharge_code": rule["surcharge_code"],
        "item_scope": rule["item_scope"],
        "rate_pct": num(rule["rate_pct"]),
        "threshold_cents": rule["threshold_cents"],
        "min_cents": rule["min_cents"],
        "max_cents": rule["max_cents"],
    })
    return out


def partner_out(partner):
    out = _mutable(partner)
    out.update({
        "partner_name": partner["partner_name"],
        "partner_type": partner["partner_type"],
        "iata_code": partner["iata_code"],
        "home_country": partner["home_country"],
        "certification_status": partner["certification_status"],
    })
    return out


def fare_filing_out(filing):
    out = _mutable(filing)
    out.update({
        "fare_basis_code": filing["fare_basis_code"],
        "origin": filing["origin"],
        "destination": filing["destination"],
        "cabin": filing["cabin"],
        "base_amount_cents": filing["base_amount_cents"],
        "sale_from": iso(filing["sale_from"]),
        "sale_to": iso(filing["sale_to"]),
        "travel_from": iso(filing["travel_from"]),
        "travel_to": iso(filing["travel_to"]),
        "min_content_tier_rank": filing["min_content_tier_rank"],
        "refundable": filing["refundable"],
        "is_private": filing["is_private"],
        "base_filing_id": filing["base_filing_id"],
        "revision_number": filing["revision_number"],
        "filed_by_user_id": filing["filed_by_user_id"],
        "status": filing["status"],
    })
    return out


def ancillary_out(product):
    out = _mutable(product)
    out.update({
        "ancillary_code": product["ancillary_code"],
        "name": product["name"],
        "list_amount_cents": product["list_amount_cents"],
        "min_content_tier_rank": product["min_content_tier_rank"],
        "refundable": product["refundable"],
    })
    return out


def bundle_out(bundle):
    out = _mutable(bundle)
    out.update({
        "bundle_code": bundle["bundle_code"],
        "ancillary_codes": list(bundle["ancillary_codes"]),
        "bundle_discount_pct": num(bundle["bundle_discount_pct"]),
        "min_content_tier_rank": bundle["min_content_tier_rank"],
    })
    return out


def agreement_out(agreement):
    out = _mutable(agreement)
    out.update({
        "partner_id": agreement["partner_id"],
        "channel_id": agreement["channel_id"],
        "proposed_incentive_pct": num(agreement["proposed_incentive_pct"]),
        "agreed_incentive_pct": num(agreement["agreed_incentive_pct"]),
        "incentive_cap_cents": agreement["incentive_cap_cents"],
        "target_net_revenue_cents": agreement["target_net_revenue_cents"],
        "cumulative_net_revenue_cents": agreement["cumulative_net_revenue_cents"],
        "incentive_accrued_cents": agreement["incentive_accrued_cents"],
        "incentive_tier": agreement["incentive_tier"],
        "tier_downgrade_count": agreement["tier_downgrade_count"],
        "negotiation_round": agreement["negotiation_round"],
        "proposed_by_user_id": agreement["proposed_by_user_id"],
        "signed_by_user_id": agreement["signed_by_user_id"],
        "status": agreement["status"],
    })
    return out


def contract_out(contract, validity_state):
    out = _mutable(contract)
    out.update({
        "corporate_partner_id": contract["corporate_partner_id"],
        "negotiated_fare_filing_id": contract["negotiated_fare_filing_id"],
        "account_code": contract["account_code"],
        "max_offer_total_cents": contract["max_offer_total_cents"],
        "traceability_required": contract["traceability_required"],
        "tracking_ref_prefix": contract["tracking_ref_prefix"],
        "min_content_tier_rank": contract["min_content_tier_rank"],
        "effective_from": iso(contract["effective_from"]),
        "effective_to": iso(contract["effective_to"]),
        "validity_state": validity_state,
    })
    return out


def offer_out(offer):
    out = _mutable(offer)
    out.update({
        "channel_id": offer["channel_id"],
        "partner_id": offer["partner_id"],
        "fare_filing_id": offer["fare_filing_id"],
        "bundle_id": offer["bundle_id"],
        "corporate_contract_id": offer["corporate_contract_id"],
        "ancillary_codes": list(offer["ancillary_codes"]),
        "trip_origin": offer["trip_origin"],
        "trip_destination": offer["trip_destination"],
        "departure_date": iso(offer["departure_date"]),
        "cabin": offer["cabin"],
        "subtotal_cents": offer["subtotal_cents"],
        "surcharge_cents": offer["surcharge_cents"],
        "total_cents": offer["total_cents"],
        "item_count": offer["item_count"],
        "acknowledged_disclosure_codes": list(offer["acknowledged_disclosure_codes"]),
        "disclosure_complete": offer["disclosure_complete"],
        "expires_at": iso(offer["expires_at"]),
        "priced_channel_version": offer["priced_channel_version"],
        "status": offer["status"],
    })
    return out


def offer_item_out(item):
    out = _immutable(item)
    out.update({
        "offer_id": item["offer_id"],
        "item_type": item["item_type"],
        "item_code": item["item_code"],
        "sequence": item["sequence"],
        "list_amount_cents": item["list_amount_cents"],
        "net_amount_cents": item["net_amount_cents"],
        "refundable": item["refundable"],
    })
    return out


def order_out(order):
    out = _mutable(order)
    out.update({
        "offer_id": order["offer_id"],
        "channel_id": order["channel_id"],
        "partner_id": order["partner_id"],
        "agency_agreement_id": order["agency_agreement_id"],
        "corporate_tracking_ref": order["corporate_tracking_ref"],
        "disclosure_ack_codes": list(order["disclosure_ack_codes"]),
        "message_count": order["message_count"],
        "segment_count": order["segment_count"],
        "paid_amount_cents": order["paid_amount_cents"],
        "refunded_amount_cents": order["refunded_amount_cents"],
        "net_revenue_cents": order["net_revenue_cents"],
        "payment_status": order["payment_status"],
        "fulfillment_status": order["fulfillment_status"],
    })
    return out


def service_request_out(sr):
    out = _mutable(sr)
    out.update({
        "order_id": sr["order_id"],
        "request_type": sr["request_type"],
        "requested_change_note": sr["requested_change_note"],
        "refundable_base_cents": sr["refundable_base_cents"],
        "cancellation_fee_cents": sr["cancellation_fee_cents"],
        "refund_total_cents": sr["refund_total_cents"],
        "incentive_clawback_cents": sr["incentive_clawback_cents"],
        "submitted_by_user_id": sr["submitted_by_user_id"],
        "reviewed_by_user_id": sr["reviewed_by_user_id"],
        "status": sr["status"],
    })
    return out


def certification_out(cert):
    out = _mutable(cert)
    out.update({
        "partner_id": cert["partner_id"],
        "channel_id": cert["channel_id"],
        "env_code": cert["env_code"],
        "reserved_test_minutes": cert["reserved_test_minutes"],
        "readiness_score_strict": cert["readiness_score_strict"],
        "readiness_score_provisional": cert["readiness_score_provisional"],
        "mandatory_failed_count": cert["mandatory_failed_count"],
        "certified_variant": cert["certified_variant"],
        "tested_by_user_id": cert["tested_by_user_id"],
        "status": cert["status"],
    })
    return out


def connectivity_test_out(test):
    out = _mutable(test)
    out.update({
        "certification_id": test["certification_id"],
        "test_code": test["test_code"],
        "is_mandatory": test["is_mandatory"],
        "scheduled_start": iso(test["scheduled_start"]),
        "duration_minutes": test["duration_minutes"],
        "scheduled_end": iso(test["scheduled_end"]),
        "score": test["score"],
        "status": test["status"],
    })
    return out
