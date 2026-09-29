"""Entity serialisers."""
import db
from money import num
from services import calc, derive


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = db.iso(row["created_at"])
    out["updated_at"] = db.iso(row["updated_at"])
    out["version"] = row["version"]
    return out


def property_out(row):
    return _common(row, {
        "name": row["name"],
        "room_count_total": row["room_count_total"],
        "standard_room_rate_amount": num(row["standard_room_rate_amount"]),
        "occupancy_tax_rate_pct": num(row["occupancy_tax_rate_pct"]),
        "fb_tax_rate_pct": num(row["fb_tax_rate_pct"]),
        "service_charge_pct": num(row["service_charge_pct"]),
        "large_ticket_threshold_amount": num(row["large_ticket_threshold_amount"]),
        "large_party_discount_pct": num(row["large_party_discount_pct"]),
        "late_checkout_grace_minutes": row["late_checkout_grace_minutes"],
        "allowance_manager_threshold_amount": num(row["allowance_manager_threshold_amount"]),
        "allowance_controller_threshold_amount": num(row["allowance_controller_threshold_amount"]),
        "rate_variance_tolerance_pct": num(row["rate_variance_tolerance_pct"]),
        "settlement_variance_tolerance_amount": num(row["settlement_variance_tolerance_amount"]),
        "card_authorization_valid_days": row["card_authorization_valid_days"],
        "city_ledger_fee_pct": num(row["city_ledger_fee_pct"]),
        "no_show_charge_policy": row["no_show_charge_policy"],
    })


def outlet_out(row):
    return _common(row, {
        "property_id": row["property_id"],
        "outlet_code": row["outlet_code"],
        "outlet_name": row["outlet_name"],
        "outlet_type": row["outlet_type"],
        "requires_shift_settlement": row["requires_shift_settlement"],
        "status": row["status"],
    })


def period_out(row):
    subsystem = derive.period_subsystem_total(row)
    gl_total = row["gl_control_total_amount"]
    variance = None
    if gl_total is not None:
        variance = derive.q2(gl_total - subsystem)
    return _common(row, {
        "property_id": row["property_id"],
        "period_month": row["period_month"],
        "status": row["status"],
        "gl_control_total_amount": num(gl_total),
        "subsystem_total_amount": num(subsystem),
        "tie_out_variance_amount": num(variance),
        "tie_out_attempt_count": row["tie_out_attempt_count"],
        "tied_out_by_user_id": row["tied_out_by_user_id"],
        "tied_out_at": db.iso(row["tied_out_at"]),
        "audit_trail_retention_until_date": row["audit_trail_retention_until_date"],
    })


def business_date_out(row):
    out = {
        "property_id": row["property_id"],
        "accounting_period_id": row["accounting_period_id"],
        "business_date": row["business_date"],
        "status": row["status"],
        "out_of_order_room_count": row["out_of_order_room_count"],
        "benchmark_calendar_room_revenue_amount": num(row["benchmark_calendar_room_revenue_amount"]),
        "benchmark_weekday_room_revenue_amount": num(row["benchmark_weekday_room_revenue_amount"]),
        "reopen_count": row["reopen_count"],
        "city_ledger_swept_folio_count": row["city_ledger_swept_folio_count"],
        "city_ledger_transferred_balance_total_amount": num(row["city_ledger_transferred_balance_total_amount"]),
        "city_ledger_fee_total_amount": num(row["city_ledger_fee_total_amount"]),
    }
    for key, value in derive.date_aggregates(row).items():
        out[key] = num(value) if not isinstance(value, int) else value
    return _common(row, out)


def folio_out(row):
    prop = db.store.properties.get(row["property_id"])
    figures = derive.folio_figures(row)
    variance = calc.rate_variance_pct(
        row["contracted_rate_amount"], prop["standard_room_rate_amount"]
    ) if prop else None
    return _common(row, {
        "property_id": row["property_id"],
        "arrival_business_date_id": row["arrival_business_date_id"],
        "confirmation_code": row["confirmation_code"],
        "guest_name": row["guest_name"],
        "room_number": row["room_number"],
        "nights_count": row["nights_count"],
        "contracted_rate_amount": num(row["contracted_rate_amount"]),
        "rate_plan_code": row["rate_plan_code"],
        "market_segment": row["market_segment"],
        "settlement_method": row["settlement_method"],
        "scheduled_checkout_at": db.iso(row["scheduled_checkout_at"]),
        "actual_checkout_at": db.iso(row["actual_checkout_at"]),
        "is_comp": row["is_comp"],
        "credit_limit_amount": num(row["credit_limit_amount"]),
        "stay_status": row["stay_status"],
        # PRD 3.2: the account *begins* UNSETTLED with all three totals at 0.00.
        # PRD 3.7: the dimension is re-derived "after every line that touches it",
        # so a folio no line has touched yet keeps its declared initial value.
        # `rederive_folio` maintains the stored field on the single append path.
        "settlement_status": row["settlement_status"],
        "rate_variance_pct": num(variance),
        "charges_total_amount": num(figures["charges_total_amount"]),
        "credits_total_amount": num(figures["credits_total_amount"]),
        "balance_amount": num(figures["balance_amount"]),
        "settlement_hold": derive.folio_hold(row),
    })


def posting_out(row):
    return {
        "id": row["id"],
        "folio_id": row["folio_id"],
        "ledger_account_id": row["ledger_account_id"],
        "business_date_id": row["business_date_id"],
        "outlet_ticket_id": row["outlet_ticket_id"],
        "allowance_id": row["allowance_id"],
        "reverses_posting_id": row["reverses_posting_id"],
        "charge_type": row["charge_type"],
        "amount": num(row["amount"]),
        "night_index": row["night_index"],
        "source_channel": row["source_channel"],
        "reason_code": row["reason_code"],
        "posted_by_user_id": row["posted_by_user_id"],
        "memo": row["memo"],
        "created_at": db.iso(row["created_at"]),
    }


def ticket_out(row):
    return _common(row, {
        "outlet_id": row["outlet_id"],
        "business_date_id": row["business_date_id"],
        "room_charge_folio_id": row["room_charge_folio_id"],
        "ticket_number": row["ticket_number"],
        "gross_amount": num(row["gross_amount"]),
        "settlement_type": row["settlement_type"],
        "opened_at": db.iso(row["opened_at"]),
        "transmitted_at": db.iso(row["transmitted_at"]),
        "status": row["status"],
        "service_charge_amount": num(row["service_charge_amount"]),
        "taxable_base_amount": num(row["taxable_base_amount"]),
        "tax_amount": num(row["tax_amount"]),
        "large_party_discount_amount": num(row["large_party_discount_amount"]),
        "total_amount": num(row["total_amount"]),
        "closed_by_user_id": row["closed_by_user_id"],
        "closed_at": db.iso(row["closed_at"]),
        "voided_at": db.iso(row["voided_at"]),
    })


def batch_out(row):
    return _common(row, {
        "business_date_id": row["business_date_id"],
        "outlet_id": row["outlet_id"],
        "tender_type": row["tender_type"],
        "shift_start_at": db.iso(row["shift_start_at"]),
        "shift_end_at": db.iso(row["shift_end_at"]),
        "declared_amount": num(row["declared_amount"]),
        "system_amount": num(row["system_amount"]),
        "variance_amount": num(row["variance_amount"]),
        "status": row["status"],
        "recount_round": row["recount_round"],
        "declared_by_user_id": row["declared_by_user_id"],
        "accepted_by_user_id": row["accepted_by_user_id"],
    })


def ledger_out(row):
    return _common(row, {
        "property_id": row["property_id"],
        "ledger_type": row["ledger_type"],
        "account_code": row["account_code"],
        "gl_account_code": row["gl_account_code"],
        "opening_balance_amount": num(row["opening_balance_amount"]),
        "credit_limit_amount": num(row["credit_limit_amount"]),
        "current_balance_amount": num(derive.ledger_balance(row)),
    })


def allowance_out(row):
    return _common(row, {
        "folio_id": row["folio_id"],
        "business_date_id": row["business_date_id"],
        "reverses_allowance_id": row["reverses_allowance_id"],
        "reason_code": row["reason_code"],
        "requested_amount": num(row["requested_amount"]),
        "approved_amount": num(row["approved_amount"]),
        "narrative": row["narrative"],
        "supporting_document_reference": row["supporting_document_reference"],
        "status": row["status"],
        "required_approval_role": row["required_approval_role"],
        "revision_round": row["revision_round"],
        "requested_by_user_id": row["requested_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "submitted_at": db.iso(row["submitted_at"]),
        "approved_at": db.iso(row["approved_at"]),
    })


def document_out(row):
    return _common(row, {
        "property_id": row["property_id"],
        "folio_id": row["folio_id"],
        "allowance_id": row["allowance_id"],
        "doc_type": row["doc_type"],
        "authorized_by_name": row["authorized_by_name"],
        "document_reference": row["document_reference"],
        "authorized_rate_amount": num(row["authorized_rate_amount"]),
        "valid_from_date": row["valid_from_date"],
        "valid_to_date": row["valid_to_date"],
        "status": row["status"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "filed_by_user_id": row["filed_by_user_id"],
        "reviewed_at": db.iso(row["reviewed_at"]),
    })


def auth_out(row):
    return _common(row, {
        "folio_id": row["folio_id"],
        "obtained_at": db.iso(row["obtained_at"]),
        "authorized_amount": num(row["authorized_amount"]),
        "status": row["status"],
        "follow_up_status": row["follow_up_status"],
        "decline_code": row["decline_code"],
        "aging_days": derive.auth_aging_days(row),
        "captured_amount": num(row["captured_amount"]),
        "resolved_by_user_id": row["resolved_by_user_id"],
        "follow_up_note": row["follow_up_note"],
    })


def report_out(row):
    return _common(row, {
        "business_date_id": row["business_date_id"],
        "pace_basis": row["pace_basis"],
        "rooms_available_count": row["rooms_available_count"],
        "rooms_occupied_count": row["rooms_occupied_count"],
        "occupancy_pct": num(row["occupancy_pct"]),
        "adr_amount": num(row["adr_amount"]),
        "revpar_amount": num(row["revpar_amount"]),
        "room_revenue_amount": num(row["room_revenue_amount"]),
        "tax_revenue_amount": num(row["tax_revenue_amount"]),
        "outlet_revenue_amount": num(row["outlet_revenue_amount"]),
        "total_revenue_amount": num(row["total_revenue_amount"]),
        "benchmark_room_revenue_amount": num(row["benchmark_room_revenue_amount"]),
        "pace_index_pct": num(row["pace_index_pct"]),
        "status": row["status"],
        "recipient_role_list": row["recipient_role_list"],
        "distributed_at": db.iso(row["distributed_at"]),
        "generated_by_user_id": row["generated_by_user_id"],
    })
