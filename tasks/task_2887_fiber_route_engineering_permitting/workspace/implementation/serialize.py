"""Resource payload shaping.

Versioned resources expose id/created_at/updated_at/version.  PoleObservation
and MakeReadyItem are append-only observations: updated_at and version are
absent from their payloads entirely rather than present-and-null.
"""


def _audit(rec, payload):
    payload["id"] = rec["id"]
    payload["created_at"] = rec["created_at"]
    if rec.get("_versioned"):
        payload["updated_at"] = rec["updated_at"]
        payload["version"] = rec["version"]
    return payload


def route(rec):
    return _audit(rec, {
        "name": rec["name"],
        "topology_objective": rec["topology_objective"],
        "target_in_service_date": rec["target_in_service_date"],
        "budget_authorized_cents": rec["budget_authorized_cents"],
        "budget_committed_cents": rec["budget_committed_cents"],
        "budget_available_cents": rec["budget_available_cents"],
        "status": rec["status"],
        "segment_count": rec["segment_count"],
        "planned_complexity_index": rec["planned_complexity_index"],
        "live_complexity_index": rec["live_complexity_index"],
        "total_preliminary_cost_cents": rec["total_preliminary_cost_cents"],
        "total_bid_ready_cost_cents": rec["total_bid_ready_cost_cents"],
        "design_total_length_feet": rec["design_total_length_feet"],
        "scope_locked_at": rec["scope_locked_at"],
    })


def segment(rec):
    return _audit(rec, {
        "route_id": rec["route_id"],
        "predecessor_segment_id": rec["predecessor_segment_id"],
        "sequence_index": rec["sequence_index"],
        "street_name": rec["street_name"],
        "municipality_code": rec["municipality_code"],
        "length_feet": rec["length_feet"],
        "terrain_class": rec["terrain_class"],
        "existing_conduit_available": rec["existing_conduit_available"],
        "planned_work_start_on": rec["planned_work_start_on"],
        "planned_work_end_on": rec["planned_work_end_on"],
        "construction_method": rec["construction_method"],
        "engineering_status": rec["engineering_status"],
        "permit_status": rec["permit_status"],
        "required_authority_type": rec["required_authority_type"],
        "accepted_obstruction_count": rec["accepted_obstruction_count"],
        "moratorium_class": rec["moratorium_class"],
        "restoration_cost_cents": rec["restoration_cost_cents"],
        "preliminary_cost_cents": rec["preliminary_cost_cents"],
        "bid_ready_cost_cents": rec["bid_ready_cost_cents"],
    })


def walkout(rec):
    return _audit(rec, {
        "segment_id": rec["segment_id"],
        "walked_on": rec["walked_on"],
        "obstruction_count": rec["obstruction_count"],
        "conduit_available_confirmed": rec["conduit_available_confirmed"],
        "surveyor_note": rec["surveyor_note"],
        "status": rec["status"],
        "worst_pole_condition_grade": rec["worst_pole_condition_grade"],
        "make_ready_flagged_pole_count": rec["make_ready_flagged_pole_count"],
        "review_round": rec["review_round"],
        "reviewed_by_user_id": rec["reviewed_by_user_id"],
        "rejection_reason": rec["rejection_reason"],
    })


def observation(rec):
    return _audit(rec, {
        "walkout_id": rec["walkout_id"],
        "pole_tag": rec["pole_tag"],
        "pole_owner": rec["pole_owner"],
        "condition_grade": rec["condition_grade"],
        "available_vertical_clearance_in": rec["available_vertical_clearance_in"],
        "existing_attachment_count": rec["existing_attachment_count"],
        "requires_make_ready": rec["requires_make_ready"],
    })


def pole_app(rec):
    return _audit(rec, {
        "segment_id": rec["segment_id"],
        "pole_owner": rec["pole_owner"],
        "pole_count": rec["pole_count"],
        "status": rec["status"],
        "submitted_at": rec["submitted_at"],
        "revision_round": rec["revision_round"],
        "make_ready_items_subtotal_cents": rec["make_ready_items_subtotal_cents"],
        "make_ready_admin_fee_bp": rec["make_ready_admin_fee_bp"],
        "make_ready_admin_fee_cents": rec["make_ready_admin_fee_cents"],
        "make_ready_cost_cents": rec["make_ready_cost_cents"],
        "make_ready_days": rec["make_ready_days"],
        "committed": rec["committed"],
        "owner_note": rec["owner_note"],
    })


def mr_item(rec):
    return _audit(rec, {
        "application_id": rec["application_id"],
        "pole_tag": rec["pole_tag"],
        "work_class": rec["work_class"],
        "quantity": rec["quantity"],
        "unit_cost_cents": rec["unit_cost_cents"],
        "extended_cost_cents": rec["extended_cost_cents"],
        "lead_days": rec["lead_days"],
    })


def permit(rec):
    return _audit(rec, {
        "segment_id": rec["segment_id"],
        "authority_type": rec["authority_type"],
        "authority_name": rec["authority_name"],
        "work_window_start_on": rec["work_window_start_on"],
        "work_window_end_on": rec["work_window_end_on"],
        "status": rec["status"],
        "submitted_at": rec["submitted_at"],
        "revision_round": rec["revision_round"],
        "review_days": rec["review_days"],
        "decision_due_at": rec["decision_due_at"],
        "decided_at": rec["decided_at"],
        "decided_by_user_id": rec["decided_by_user_id"],
        "deemed": rec["deemed"],
        "decision_note": rec["decision_note"],
    })


def moratorium(rec):
    return _audit(rec, {
        "municipality_code": rec["municipality_code"],
        "street_name": rec["street_name"],
        "resurfaced_on": rec["resurfaced_on"],
        "starts_on": rec["starts_on"],
        "ends_on": rec["ends_on"],
        "moratorium_class": rec["moratorium_class"],
        "ordinance_reference": rec["ordinance_reference"],
    })


def design(rec):
    return _audit(rec, {
        "route_id": rec["route_id"],
        "revision": rec["revision"],
        "status": rec["status"],
        "fiber_count_allocated": rec["fiber_count_allocated"],
        "express_fiber_count": rec["express_fiber_count"],
        "assigned_drop_fiber_count": rec["assigned_drop_fiber_count"],
        "reserve_fiber_count": rec["reserve_fiber_count"],
        "spare_ratio_bp": rec["spare_ratio_bp"],
        "splice_point_count": rec["splice_point_count"],
        "handhole_count": rec["handhole_count"],
        "submitted_by_user_id": rec["submitted_by_user_id"],
        "stamped_by_user_id": rec["stamped_by_user_id"],
        "stamped_at": rec["stamped_at"],
        "stamp_voided_at": rec["stamp_voided_at"],
        "return_note": rec["return_note"],
    })


def splice_point(rec):
    return _audit(rec, {
        "design_id": rec["design_id"],
        "segment_id": rec["segment_id"],
        "station_feet": rec["station_feet"],
        "enclosure_type": rec["enclosure_type"],
        "fiber_count_dropped": rec["fiber_count_dropped"],
        "status": rec["status"],
        "voided_at": rec["voided_at"],
    })


def as_built(rec):
    return _audit(rec, {
        "route_id": rec["route_id"],
        "design_revision": rec["design_revision"],
        "as_built_length_feet": rec["as_built_length_feet"],
        "splice_point_count_field_verified": rec["splice_point_count_field_verified"],
        "records_system_reference": rec["records_system_reference"],
        "status": rec["status"],
        "submitted_by_user_id": rec["submitted_by_user_id"],
        "certified_by_user_id": rec["certified_by_user_id"],
        "length_variance_bp": rec["length_variance_bp"],
        "certification_note": rec["certification_note"],
    })
