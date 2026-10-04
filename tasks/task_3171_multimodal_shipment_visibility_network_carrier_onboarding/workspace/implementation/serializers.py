"""Serializers: convert internal entity dicts to API representations."""

from helpers import to_iso


def _maybe_iso(v):
    """Format a datetime or pass through None."""
    if v is None:
        return None
    return to_iso(v)


def serialize_carrier(c):
    return {
        "id": c["id"],
        "carrier_name": c["carrier_name"],
        "scac_code": c["scac_code"],
        "created_at": to_iso(c["created_at"]),
        "updated_at": to_iso(c["updated_at"]),
        "version": c["version"],
    }


def serialize_shipper(s):
    return {
        "id": s["id"],
        "company_name": s["company_name"],
        "created_at": to_iso(s["created_at"]),
        "updated_at": to_iso(s["updated_at"]),
        "version": s["version"],
    }


def serialize_consignee(c):
    return {
        "id": c["id"],
        "shipper_id": c["shipper_id"],
        "company_name": c["company_name"],
        "destination_code": c["destination_code"],
        "created_at": to_iso(c["created_at"]),
        "updated_at": to_iso(c["updated_at"]),
        "version": c["version"],
    }


def serialize_connection(c):
    return {
        "id": c["id"],
        "carrier_id": c["carrier_id"],
        "channel": c["channel"],
        "supported_modes": list(c["supported_modes"]),
        "status": c["status"],
        "credential_ref": c["credential_ref"],
        "testing_window_start": _maybe_iso(c["testing_window_start"]),
        "testing_window_end": _maybe_iso(c["testing_window_end"]),
        "cadence_minutes": c["cadence_minutes"],
        "data_quality_score": c["data_quality_score"],
        "instantaneous_quality_score": c["instantaneous_quality_score"],
        "health_status": c["health_status"],
        "missed_heartbeat_streak": c["missed_heartbeat_streak"],
        "last_heartbeat_at": _maybe_iso(c["last_heartbeat_at"]),
        "suspended_at": _maybe_iso(c["suspended_at"]),
        "created_at": to_iso(c["created_at"]),
        "updated_at": to_iso(c["updated_at"]),
        "version": c["version"],
    }


def serialize_purchase_order(p):
    return {
        "id": p["id"],
        "shipper_id": p["shipper_id"],
        "po_number": p["po_number"],
        "destination_code": p["destination_code"],
        "booking_reference": p["booking_reference"],
        "confirmed_link_count": p["confirmed_link_count"],
        "created_at": to_iso(p["created_at"]),
        "updated_at": to_iso(p["updated_at"]),
        "version": p["version"],
    }


def serialize_facility(f):
    return {
        "id": f["id"],
        "facility_name": f["facility_name"],
        "facility_type": f["facility_type"],
        "status": f["status"],
        "total_dwell_minutes": f["total_dwell_minutes"],
        "detention_exposure_minutes": f["detention_exposure_minutes"],
        "appointment_adherence_pct": f["appointment_adherence_pct"],
        "created_at": to_iso(f["created_at"]),
        "updated_at": to_iso(f["updated_at"]),
        "version": f["version"],
    }


def serialize_shipment(s):
    return {
        "id": s["id"],
        "shipper_id": s["shipper_id"],
        "carrier_id": s["carrier_id"],
        "connection_id": s["connection_id"],
        "mode": s["mode"],
        "tracking_reference": s["tracking_reference"],
        "mode_reference": s["mode_reference"],
        "destination_code": s["destination_code"],
        "po_reference_claim": s["po_reference_claim"],
        "planned_departure_at": to_iso(s["planned_departure_at"]),
        "planned_arrival_at": to_iso(s["planned_arrival_at"]),
        "tracking_status": s["tracking_status"],
        "identity_state": s["identity_state"],
        "data_freshness": s["data_freshness"],
        "eta_at": _maybe_iso(s["eta_at"]),
        "eta_variant": s["eta_variant"],
        "eta_confidence_halfwidth_minutes": s["eta_confidence_halfwidth_minutes"],
        "actual_delay_minutes": s["actual_delay_minutes"],
        "created_at": to_iso(s["created_at"]),
        "updated_at": to_iso(s["updated_at"]),
        "version": s["version"],
    }


def serialize_tracking_event(e):
    return {
        "id": e["id"],
        "shipment_id": e["shipment_id"],
        "event_time": to_iso(e["event_time"]),
        "event_type": e["event_type"],
        "delay_minutes": e["delay_minutes"],
        "is_late": e["is_late"],
        "voided": e["voided"],
        "created_at": to_iso(e["created_at"]),
    }


def serialize_identity_link(l):
    return {
        "id": l["id"],
        "shipment_id": l["shipment_id"],
        "purchase_order_id": l["purchase_order_id"],
        # Two-decimal float (e.g. 1.0, 0.9) — JSON has no fixed decimal precision,
        # but tests comparing numerically will see the correct value.
        "match_score": float(l["match_score"]),
        "status": l["status"],
        "created_at": to_iso(l["created_at"]),
        "updated_at": to_iso(l["updated_at"]),
        "version": l["version"],
    }


def serialize_alert(a):
    return {
        "id": a["id"],
        "shipment_id": a["shipment_id"],
        "alert_type": a["alert_type"],
        "severity": a["severity"],
        "assigned_queue": a["assigned_queue"],
        "status": a["status"],
        "opened_at": to_iso(a["opened_at"]),
        "resolution": a["resolution"],
        "resolved_at": _maybe_iso(a["resolved_at"]),
        "created_at": to_iso(a["created_at"]),
        "updated_at": to_iso(a["updated_at"]),
        "version": a["version"],
    }


def serialize_appointment(a):
    return {
        "id": a["id"],
        "facility_id": a["facility_id"],
        "shipment_id": a["shipment_id"],
        "window_start": to_iso(a["window_start"]),
        "window_end": to_iso(a["window_end"]),
        "status": a["status"],
        "actual_arrival_at": _maybe_iso(a["actual_arrival_at"]),
        "actual_departure_at": _maybe_iso(a["actual_departure_at"]),
        "dwell_minutes": a["dwell_minutes"],
        "adherent": a["adherent"],
        "exposure_minutes": a["exposure_minutes"],
        "created_at": to_iso(a["created_at"]),
        "updated_at": to_iso(a["updated_at"]),
        "version": a["version"],
    }


def serialize_data_share_grant(g):
    return {
        "id": g["id"],
        "shipper_id": g["shipper_id"],
        "grantee_type": g["grantee_type"],
        "grantee_id": g["grantee_id"],
        "scope": g["scope"],
        "effective_from": to_iso(g["effective_from"]),
        "expires_at": to_iso(g["expires_at"]),
        "status": g["status"],
        "created_at": to_iso(g["created_at"]),
        "updated_at": to_iso(g["updated_at"]),
        "version": g["version"],
    }


def serialize_heartbeat_record(h):
    return {
        "id": h["id"],
        "connection_id": h["connection_id"],
        "reported_at": to_iso(h["reported_at"]),
        "recorded_at": to_iso(h["recorded_at"]),
        "payload_completeness_pct": h["payload_completeness_pct"],
        "on_time": h["on_time"],
        "created_at": to_iso(h["created_at"]),
    }


def serialize_ops_run(r):
    return {
        "id": r["id"],
        "run_index": r["run_index"],
        "executed_at": to_iso(r["executed_at"]),
        "connections_degraded": r["connections_degraded"],
        "testing_connections_reset": r["testing_connections_reset"],
        "etas_recomputed": r["etas_recomputed"],
        "alerts_created": r["alerts_created"],
        "alerts_escalated": r["alerts_escalated"],
        "created_at": to_iso(r["created_at"]),
    }
