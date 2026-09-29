"""Response serializers — every declared field of every entity, always present."""

from util import fmt_instant, num


def _common(record):
    return {
        "id": record["id"],
        "created_at": fmt_instant(record["created_at"]),
        "updated_at": fmt_instant(record["updated_at"]),
        "version": record["version"],
    }


def _lean(record):
    """AddressHygieneRun and VerificationFinding carry only id + created_at."""
    return {
        "id": record["id"],
        "created_at": fmt_instant(record["created_at"]),
    }


def client(record):
    out = _common(record)
    out.update(
        {
            "name": record["name"],
            "client_code": record["client_code"],
            "service_fee_rate_per_thousand_cents": record[
                "service_fee_rate_per_thousand_cents"
            ],
            "billing_terms": record["billing_terms"],
            "commingle_opt_in": record["commingle_opt_in"],
            "status": record["status"],
            "suspension_reason": record["suspension_reason"],
            "unbilled_postage_cents": record["unbilled_postage_cents"],
            "lifetime_pieces_mailed": record["lifetime_pieces_mailed"],
        }
    )
    return out


def permit_account(record):
    out = _common(record)
    out.update(
        {
            "client_id": record["client_id"],
            "permit_number": record["permit_number"],
            "payment_method": record["payment_method"],
            "annual_fee_paid_through_utc": fmt_instant(
                record["annual_fee_paid_through_utc"]
            ),
            "balance_cents": record["balance_cents"],
            "reserved_cents": record["reserved_cents"],
            "status": record["status"],
        }
    )
    return out


def mail_job(record):
    out = _common(record)
    out.update(
        {
            "client_id": record["client_id"],
            "permit_account_id": record["permit_account_id"],
            "commingle_batch_id": record["commingle_batch_id"],
            "mail_class": record["mail_class"],
            "processing_category": record["processing_category"],
            "declared_piece_count": record["declared_piece_count"],
            "declared_weight_oz_per_piece": num(record["declared_weight_oz_per_piece"]),
            "status": record["status"],
            "accepted_piece_count": record["accepted_piece_count"],
            "hygiene_run_count": record["hygiene_run_count"],
            "rework_count": record["rework_count"],
            "address_quality_pct": num(record["address_quality_pct"]),
            "move_update_compliant": record["move_update_compliant"],
            "postage_due_cents": record["postage_due_cents"],
            "mailed_at_utc": fmt_instant(record["mailed_at_utc"]),
            "cancel_reason": record["cancel_reason"],
        }
    )
    return out


def hygiene_run(record):
    out = _lean(record)
    out.update(
        {
            "mail_job_id": record["mail_job_id"],
            "submitted_piece_count": record["submitted_piece_count"],
            "cass_matched_count": record["cass_matched_count"],
            "ncoa_move_updated_count": record["ncoa_move_updated_count"],
            "undeliverable_removed_count": record["undeliverable_removed_count"],
            "move_update_age_days": record["move_update_age_days"],
            "run_index": record["run_index"],
            "net_piece_count": record["net_piece_count"],
            "address_quality_pct": num(record["address_quality_pct"]),
            "move_update_compliant": record["move_update_compliant"],
        }
    )
    return out


def entry_facility(record):
    out = _common(record)
    out.update(
        {
            "facility_code": record["facility_code"],
            "facility_type": record["facility_type"],
            "zip3": record["zip3"],
            "dock_capacity_pallets_per_slot": record["dock_capacity_pallets_per_slot"],
            "drop_ship_discount_bp": record["drop_ship_discount_bp"],
            "served_zip3_list": list(record["served_zip3_list"]),
            "status": record["status"],
        }
    )
    return out


def commingle_batch(record):
    out = _common(record)
    out.update(
        {
            "entry_facility_id": record["entry_facility_id"],
            "mail_class": record["mail_class"],
            "processing_category": record["processing_category"],
            "status": record["status"],
            "member_job_count": record["member_job_count"],
            "total_piece_count": record["total_piece_count"],
            "container_count": record["container_count"],
            "achieved_tier": record["achieved_tier"],
            "rate_mills_per_piece": record["rate_mills_per_piece"],
            "batch_postage_cents": record["batch_postage_cents"],
        }
    )
    return out


def batch_member(record):
    out = _common(record)
    out.update(
        {
            "commingle_batch_id": record["commingle_batch_id"],
            "mail_job_id": record["mail_job_id"],
            "contributed_piece_count": record["contributed_piece_count"],
            "share_basis_pct": num(record["share_basis_pct"]),
            "allocated_postage_cents": record["allocated_postage_cents"],
            "allocated_adjustment_cents": record["allocated_adjustment_cents"],
        }
    )
    return out


def sort_container(record):
    out = _common(record)
    out.update(
        {
            "commingle_batch_id": record["commingle_batch_id"],
            "container_type": record["container_type"],
            "destination_zip3": record["destination_zip3"],
            "sort_level": record["sort_level"],
            "piece_count": record["piece_count"],
            "qualifies": record["qualifies"],
            "placard_id": record["placard_id"],
            "sequence_index": record["sequence_index"],
            "zone": record["zone"],
            "committed_days": record["committed_days"],
            "status": record["status"],
        }
    )
    return out


def drop_shipment(record):
    out = _common(record)
    out.update(
        {
            "commingle_batch_id": record["commingle_batch_id"],
            "entry_facility_id": record["entry_facility_id"],
            "window_start_utc": fmt_instant(record["window_start_utc"]),
            "window_end_utc": fmt_instant(record["window_end_utc"]),
            "pallet_count": record["pallet_count"],
            "status": record["status"],
            "deposited_at_utc": fmt_instant(record["deposited_at_utc"]),
            "cancel_reason": record["cancel_reason"],
        }
    )
    return out


def postage_statement(record):
    out = _common(record)
    out.update(
        {
            "commingle_batch_id": record["commingle_batch_id"],
            "permit_account_id": record["permit_account_id"],
            "prepared_by_user_id": record["prepared_by_user_id"],
            "submitted_by_user_id": record["submitted_by_user_id"],
            "verified_by_user_id": record["verified_by_user_id"],
            "statement_piece_count": record["statement_piece_count"],
            "rate_mills_per_piece": record["rate_mills_per_piece"],
            "declared_postage_cents": record["declared_postage_cents"],
            "adjustment_cents": record["adjustment_cents"],
            "verified_postage_cents": record["verified_postage_cents"],
            "verification_error_count": record["verification_error_count"],
            "revision_index": record["revision_index"],
            "status": record["status"],
            "void_reason": record["void_reason"],
        }
    )
    return out


def verification_finding(record):
    out = _lean(record)
    out.update(
        {
            "postage_statement_id": record["postage_statement_id"],
            "finding_type": record["finding_type"],
            "affected_piece_count": record["affected_piece_count"],
            "assessed_by_user_id": record["assessed_by_user_id"],
            "severity": record["severity"],
            "surcharge_cents": record["surcharge_cents"],
        }
    )
    return out


def service_level_record(record):
    out = _common(record)
    out.update(
        {
            "sort_container_id": record["sort_container_id"],
            "zone": record["zone"],
            "committed_days": record["committed_days"],
            "piece_count": record["piece_count"],
            "deposited_at_utc": fmt_instant(record["deposited_at_utc"]),
            "actual_delivery_days": record["actual_delivery_days"],
            "scanned_at_utc": fmt_instant(record["scanned_at_utc"]),
            "on_time": record["on_time"],
        }
    )
    return out


def client_invoice(record):
    out = _common(record)
    out.update(
        {
            "client_id": record["client_id"],
            "period_start_utc": fmt_instant(record["period_start_utc"]),
            "period_end_utc": fmt_instant(record["period_end_utc"]),
            "postage_cents": record["postage_cents"],
            "adjustment_cents": record["adjustment_cents"],
            "service_fee_cents": record["service_fee_cents"],
            "total_cents": record["total_cents"],
            "included_job_count": record["included_job_count"],
            "billed_piece_count": record["billed_piece_count"],
            "status": record["status"],
            "paid_amount_cents": record["paid_amount_cents"],
        }
    )
    return out
