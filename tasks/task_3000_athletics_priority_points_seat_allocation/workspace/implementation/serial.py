"""JSON serialisers: one per entity, exposing exactly the scaffold's field names."""
import clock
import num


def _common(row):
    return {
        "id": row["id"],
        "created_at": clock.iso3(row["created_at"]),
        "updated_at": clock.iso3(row["updated_at"]),
        "version": int(row["version"]),
    }


def donor(row):
    body = _common(row)
    body.update({
        "full_name": row["full_name"],
        "email": row["email"],
        "alumni_status": row["alumni_status"],
        "entity_type": row["entity_type"],
        "donor_status": row["donor_status"],
        "status_effective_date": clock.iso3(row["status_effective_date"]),
        "household_partner_donor_id": row["household_partner_donor_id"],
        "season_ticket_first_cycle_year": row["season_ticket_first_cycle_year"],
        "season_ticket_seasons_purchased": int(row["season_ticket_seasons_purchased"]),
        "cumulative_giving_cents": int(row["cumulative_giving_cents"]),
        "consecutive_giving_years": int(row["consecutive_giving_years"]),
        "provisional_points": num.points_out(row["provisional_points"]),
        "certified_base_points": num.points_out(row["certified_base_points"]),
        "certified_points": num.points_out(row["certified_points"]),
        "transferred_points_in": num.points_out(row["transferred_points_in"]),
        "transferred_points_out": num.points_out(row["transferred_points_out"]),
        "dispute_adjustment_points": num.points_out(row["dispute_adjustment_points"]),
        "rank_position": row["rank_position"],
        "pending_request_count": int(row["pending_request_count"]),
    })
    return body


def gift(row):
    body = _common(row)
    body.update({
        "donor_id": row["donor_id"],
        "gift_date": clock.iso3(row["gift_date"]),
        "cycle_year": int(row["cycle_year"]),
        "amount_cents": int(row["amount_cents"]),
        "designation": row["designation"],
        "gift_status": row["gift_status"],
        "counts_toward_points": bool(row["counts_toward_points"]),
        "settled_at": clock.iso3(row["settled_at"]),
    })
    return body


def ledger_entry(row):
    """Append-only: id and created_at only, with no updated_at and no version."""
    return {
        "id": row["id"],
        "created_at": clock.iso3(row["created_at"]),
        "donor_id": row["donor_id"],
        "recalculation_id": row["recalculation_id"],
        "entry_type": row["entry_type"],
        "variant": row["variant"],
        "points": num.points_out(row["points"]),
        "basis_note": row["basis_note"],
        "computed_at": clock.iso3(row["computed_at"]),
    }


def recalculation(row):
    body = _common(row)
    body.update({
        "cycle_year": int(row["cycle_year"]),
        "cutoff_date": clock.iso3(row["cutoff_date"]),
        "dispute_window_end": clock.iso3(row["dispute_window_end"]),
        "status": row["status"],
        "initiated_by_user_id": row["initiated_by_user_id"],
        "certified_by_user_id": row["certified_by_user_id"],
        "donors_processed_count": int(row["donors_processed_count"]),
        "communication_sent_count": int(row["communication_sent_count"]),
        "certified_points_sum": num.points_out(row["certified_points_sum"]),
        "certified_at": clock.iso3(row["certified_at"]),
    })
    return body


def dispute(row):
    body = _common(row)
    body.update({
        "donor_id": row["donor_id"],
        "recalculation_id": row["recalculation_id"],
        "claimed_points_delta": num.points_out(row["claimed_points_delta"]),
        "basis_note": row["basis_note"],
        "status": row["status"],
        "info_request_rounds": int(row["info_request_rounds"]),
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "granted_points_delta": num.points_out(row["granted_points_delta"]),
        "decided_at": clock.iso3(row["decided_at"]),
        "info_note": row.get("info_note"),
    })
    return body


def transfer(row):
    body = _common(row)
    body.update({
        "source_donor_id": row["source_donor_id"],
        "recipient_donor_id": row["recipient_donor_id"],
        "basis": row["basis"],
        "points_amount": num.points_out(row["points_amount"]),
        "status": row["status"],
        "transfer_pct_cap": num.points_out(row["transfer_pct_cap"]),
        "max_transferable_points": num.points_out(row["max_transferable_points"]),
        "exception_required": bool(row["exception_required"]),
        "exception_granted_by_user_id": row["exception_granted_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "decision_note": row["decision_note"],
        "reversed_at": clock.iso3(row["reversed_at"]),
    })
    return body


def section(row):
    body = _common(row)
    body.update({
        "section_code": row["section_code"],
        "venue_code": row["venue_code"],
        "seat_capacity": int(row["seat_capacity"]),
        "per_seat_requirement_cents": int(row["per_seat_requirement_cents"]),
        "required_points_per_seat": num.points_out(row["required_points_per_seat"]),
        "requirement_history": [
            {"cycle_year": int(e["cycle_year"]),
             "per_seat_requirement_cents": int(e["per_seat_requirement_cents"])}
            for e in row["requirement_history"]
        ],
        "status": row["status"],
        "renovation_status": row["renovation_status"],
        "post_renovation_capacity": row["post_renovation_capacity"],
        "post_renovation_requirement_cents": row["post_renovation_requirement_cents"],
        "reseating_recalculation_id": row["reseating_recalculation_id"],
        "reseated_donor_count": int(row["reseated_donor_count"]),
        "reseating_invoice_total_cents": int(row["reseating_invoice_total_cents"]),
        "seat_row_count": int(row["seat_row_count"]),
        "seats_available": int(row["seats_available"]),
        "seats_committed_count": int(row["seats_committed_count"]),
        "decommissioned_seat_count": int(row["decommissioned_seat_count"]),
        "assigned_seat_count": int(row["assigned_seat_count"]),
        "underwater_seat_count": int(row["underwater_seat_count"]),
        "pricing_posture": row["pricing_posture"],
    })
    return body


def seat(row):
    body = _common(row)
    body.update({
        "section_id": row["section_id"],
        "row_label": row["row_label"],
        "seat_number": int(row["seat_number"]),
        "seat_status": row["seat_status"],
        "max_concurrent_holds": int(row["max_concurrent_holds"]),
    })
    return body


def assignment(row):
    body = _common(row)
    body.update({
        "seat_id": row["seat_id"],
        "donor_id": row["donor_id"],
        "selection_slot_id": row["selection_slot_id"],
        "occupancy_status": row["occupancy_status"],
        "payment_status": row["payment_status"],
        "hold_start": clock.iso3(row["hold_start"]),
        "hold_end": clock.iso3(row["hold_end"]),
        "first_occupied_cycle_year": int(row["first_occupied_cycle_year"]),
        "pricing_mode": row["pricing_mode"],
        "grandfathered_requirement_cents": int(row["grandfathered_requirement_cents"]),
        "requirement_cents": int(row["requirement_cents"]),
        "handling_fee_cents": int(row["handling_fee_cents"]),
        "total_due_cents": int(row["total_due_cents"]),
        "amount_paid_cents": int(row["amount_paid_cents"]),
        "required_points": num.points_out(row["required_points"]),
        "points_at_pick": num.points_out(row["points_at_pick"]),
        "eligibility_status": row["eligibility_status"],
        "release_reason": row["release_reason"],
    })
    return body


def event(row):
    body = _common(row)
    body.update({
        "recalculation_id": row["recalculation_id"],
        "event_type": row["event_type"],
        "status": row["status"],
        "window_start": clock.iso3(row["window_start"]),
        "window_end": clock.iso3(row["window_end"]),
        "slot_minutes": int(row["slot_minutes"]),
        "slot_buffer_minutes": int(row["slot_buffer_minutes"]),
        "eligible_donor_min_points": num.points_out(row["eligible_donor_min_points"]),
        "published_slot_count": int(row["published_slot_count"]),
        "scheduled_slot_count": int(row["scheduled_slot_count"]),
    })
    return body


def slot(row):
    body = _common(row)
    body.update({
        "selection_event_id": row["selection_event_id"],
        "donor_id": row["donor_id"],
        "rank_at_publish": row["rank_at_publish"],
        "slot_index": int(row["slot_index"]),
        "slot_start": clock.iso3(row["slot_start"]),
        "slot_end": clock.iso3(row["slot_end"]),
        "slot_status": row["slot_status"],
    })
    return body


def relocation_request(row):
    body = _common(row)
    body.update({
        "donor_id": row["donor_id"],
        "current_seat_assignment_id": row["current_seat_assignment_id"],
        "target_section_id": row["target_section_id"],
        "selection_event_id": row["selection_event_id"],
        "request_type": row["request_type"],
        "status": row["status"],
        "granted_seat_assignment_id": row["granted_seat_assignment_id"],
        "decision_note": row["decision_note"],
    })
    return body
