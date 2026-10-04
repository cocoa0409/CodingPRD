"""Response envelope helpers and serialization of stored rows."""

from flask import jsonify

from db import iso_z, iso_z3, request_id


def envelope(data, response_type):
    return {"meta": {"api_request_id": request_id(),
                     "api_request_timestamp": iso_z3(_timestamp())},
            "response_type": response_type,
            "data": data}


def _timestamp():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def ok(data, response_type="object", status=200):
    return jsonify(envelope(data, response_type)), status


def ok_list(rows, limit, offset, total_count, serializer):
    page = rows[offset:offset + limit]
    body = envelope([serializer(r) for r in page], "array")
    body["meta"]["limit"] = limit
    body["meta"]["offset"] = offset
    body["meta"]["total_count"] = total_count
    body["meta"]["has_more"] = (offset + limit) < total_count
    return jsonify(body), 200


def error_body(error_id, message):
    return envelope({"error_id": error_id, "message": message}, "error")


# --- serializers ------------------------------------------------------------

def s_auditorium(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "seat_capacity": row["seat_capacity"],
        "screen_lead_time_minutes": row["screen_lead_time_minutes"],
        "kitchen_point_rate": row["kitchen_point_rate"],
        "alcove_point_rate": row["alcove_point_rate"],
        "status": row["status"],
        "service_posture": row["service_posture"],
        "build_phase": row["build_phase"],
        "last_showtime_cluster_start_utc": iso_z(row["last_showtime_cluster_start_utc"]),
        "version": row["version"],
        "created_at": iso_z3(row["created_at"]),
        "updated_at": iso_z3(row["updated_at"]),
    }


def _dt(value):
    return iso_z(value)


def s_showtime(row):
    return {
        "id": row["id"],
        "auditorium_id": row["auditorium_id"],
        "title": row["title"],
        "start_at_utc": _dt(row["start_at_utc"]),
        "runtime_minutes": row["runtime_minutes"],
        "content_type": row["content_type"],
        "pre_show_minutes": row["pre_show_minutes"],
        "status": row["status"],
        "mode": row["mode"],
        "service_mode": row["service_mode"],
        "dining_open_at_utc": _dt(row["dining_open_at_utc"]),
        "entree_ready_deadline_utc": _dt(row["entree_ready_deadline_utc"]),
        "dining_close_at_utc": _dt(row["dining_close_at_utc"]),
        "version": row["version"],
        "created_at": iso_z3(row["created_at"]),
        "updated_at": iso_z3(row["updated_at"]),
    }


def s_programming_event(row):
    return {
        "id": row["id"],
        "auditorium_id": row["auditorium_id"],
        "theme_name": row["theme_name"],
        "requires_themed_menu": row["requires_themed_menu"],
        "pre_show_content_status": row["pre_show_content_status"],
        "status": row["status"],
        "pre_show_content_version": row["pre_show_content_version"],
        "themed_menu_count": row["themed_menu_count"],
        "version": row["version"],
        "created_at": iso_z3(row["created_at"]),
        "updated_at": iso_z3(row["updated_at"]),
    }


def s_menu_item(row, availability=None):
    return {
        "id": row["id"],
        "catalog_name": row["catalog_name"],
        "channel": row["channel"],
        "price_cents": row["price_cents"],
        "prep_minutes": row["prep_minutes"],
        "is_alcoholic": row["is_alcoholic"],
        "availability_state": availability or row["availability_state"],
        "version": row["version"],
        "created_at": iso_z3(row["created_at"]),
        "updated_at": iso_z3(row["updated_at"]),
    }


def s_themed_menu_item(row):
    return {
        "id": row["id"],
        "programming_event_id": row["programming_event_id"],
        "menu_item_id": row["menu_item_id"],
        "theme_price_cents": row["theme_price_cents"],
        "is_signature": row["is_signature"],
        "created_at": iso_z3(row["created_at"]),
    }


def s_server(row):
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "home_auditorium_id": row["home_auditorium_id"],
        "ratings": [{"assignment_id": r["assignment_id"], "rating_grade": r["rating_grade"]}
                    for r in row["ratings"]],
        "lifetime_points": row["lifetime_points"],
        "in_rotation": row["in_rotation"],
        "shift_load_projected": row["shift_load_projected"],
        "shift_load_final": row["shift_load_final"],
        "rollup_provisional_cents": row["rollup_provisional_cents"],
        "status": row["status"],
        "version": row["version"],
        "created_at": iso_z3(row["created_at"]),
        "updated_at": iso_z3(row["updated_at"]),
    }


def s_section_assignment(row):
    return {
        "id": row["id"],
        "showtime_id": row["showtime_id"],
        "auditorium_id": row["auditorium_id"],
        "server_id": row["server_id"],
        "section_label": row["section_label"],
        "status": row["status"],
        "version": row["version"],
        "assignment_points": row["assignment_points"],
        "created_at": iso_z3(row["created_at"]),
        "updated_at": iso_z3(row["updated_at"]),
    }


def s_order_slip(row):
    return {
        "id": row["id"],
        "showtime_id": row["showtime_id"],
        "section_assignment_id": row["section_assignment_id"],
        "seat_number": row["seat_number"],
        "status": row["status"],
        "channel": row["channel"],
        "placement_mode": row["placement_mode"],
        "placed_at_utc": _dt(row["placed_at_utc"]),
        "in_kitchen_at_utc": _dt(row["in_kitchen_at_utc"]),
        "delivered_at_utc": _dt(row["delivered_at_utc"]),
        "lines": row["lines"],
        "resolved_lines": row["resolved_lines"],
        "subtotal_cents": row["subtotal_cents"],
        "id_check_required": row["id_check_required"],
        "id_check_status": row["id_check_status"],
        "version": row["version"],
        "created_at": iso_z3(row["created_at"]),
        "updated_at": iso_z3(row["updated_at"]),
    }


def s_kitchen_ticket(row):
    return {
        "id": row["id"],
        "showtime_id": row["showtime_id"],
        "order_slip_id": row["order_slip_id"],
        "station": row["station"],
        "point_cost": row["point_cost"],
        "fire_at_utc": _dt(row["fire_at_utc"]),
        "projected_delivery_at_utc": _dt(row["projected_delivery_at_utc"]),
        "status": row["status"],
        "sequence_position": row["sequence_position"],
        "overflow_reason": row["overflow_reason"],
        "allergen_substitution": row["allergen_substitution"],
        "void_reason": row["void_reason"],
        "version": row["version"],
        "created_at": iso_z3(row["created_at"]),
        "updated_at": iso_z3(row["updated_at"]),
    }


def s_check(row):
    return {
        "id": row["id"],
        "order_slip_id": row["order_slip_id"],
        "status": row["status"],
        "original_cents": row["original_cents"],
        "refunded_cents": row["refunded_cents"],
        "reason_code": row["reason_code"],
        "version": row["version"],
        "created_at": iso_z3(row["created_at"]),
        "updated_at": iso_z3(row["updated_at"]),
    }


def s_disturbance(row):
    return {
        "id": row["id"],
        "order_slip_id": row["order_slip_id"],
        "kind": row["kind"],
        "stage": row["stage"],
        "prior_stage": row["prior_stage"],
        "stage_version": row["stage_version"],
        "occurred_at_utc": _dt(row["occurred_at_utc"]),
        "ejected_occupant_id": row["ejected_occupant_id"],
        "created_at": iso_z3(row["created_at"]),
    }