"""Entity serializers. Each serializer whitelists exactly the fields declared
in the scaffold entity table (plus common fields), so internal bookkeeping
keys (_seq, _collection, _tmi_id, _slot_count, _reserved_slots) never leak.

Record types (TMIRevision, SlotTransaction, CompressionRun, RerouteAssignment)
carry only id + created_at per PRD 2.4 — no updated_at / version.
"""

from util import fmt_dt, fmt_ts


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def _record(rec):
    return {"id": rec["id"], "created_at": fmt_ts(rec["created_at"])}


def serialize_facility(rec):
    out = _common(rec)
    out.update(
        {
            "ident": rec["ident"],
            "facility_type": rec["facility_type"],
            "base_acceptance_rate": rec["base_acceptance_rate"],
            "status": rec["status"],
        }
    )
    return out


def serialize_operator(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "operator_type": rec["operator_type"],
            "cdm_member": rec["cdm_member"],
            "cumulative_delay_minutes": rec["cumulative_delay_minutes"],
        }
    )
    return out


def serialize_constraint_event(rec):
    out = _common(rec)
    out.update(
        {
            "facility_id": rec["facility_id"],
            "event_type": rec["event_type"],
            "severity": rec["severity"],
            "window_start": fmt_dt(rec["window_start"]),
            "window_end": fmt_dt(rec["window_end"]),
            "extension_count": rec["extension_count"],
            "status": rec["status"],
        }
    )
    return out


def serialize_forecast(rec):
    out = _common(rec)
    out.update(
        {
            "facility_id": rec["facility_id"],
            "variant": rec["variant"],
            "window_start": fmt_dt(rec["window_start"]),
            "window_end": fmt_dt(rec["window_end"]),
            "included_event_ids": list(rec["included_event_ids"]),
            "predicted_acceptance_rate": rec["predicted_acceptance_rate"],
            "status": rec["status"],
            "published_at": fmt_dt(rec["published_at"]),
        }
    )
    return out


def serialize_tmi(rec):
    out = _common(rec)
    out.update(
        {
            "facility_id": rec["facility_id"],
            "tmi_type": rec["tmi_type"],
            "program_start": fmt_dt(rec["program_start"]),
            "program_end": fmt_dt(rec["program_end"]),
            "controlled_rate": rec["controlled_rate"],
            "status": rec["status"],
            "proposed_by_user_id": rec["proposed_by_user_id"],
            "published_by_user_id": rec["published_by_user_id"],
            "revision_count": rec["revision_count"],
            "activated_at": fmt_dt(rec["activated_at"]),
        }
    )
    return out


def serialize_revision(rec):
    out = _record(rec)
    out.update(
        {
            "tmi_id": rec["tmi_id"],
            "revision_index": rec["revision_index"],
            "previous_controlled_rate": rec["previous_controlled_rate"],
            "new_controlled_rate": rec["new_controlled_rate"],
            "previous_program_end": fmt_dt(rec["previous_program_end"]),
            "new_program_end": fmt_dt(rec["new_program_end"]),
            "origin": rec["origin"],
            "reason": rec["reason"],
            "applied": rec["applied"],
            "applied_at": fmt_dt(rec["applied_at"]),
        }
    )
    return out


def serialize_flight(rec):
    out = _common(rec)
    out.update(
        {
            "operator_id": rec["operator_id"],
            "designator": rec["designator"],
            "origin": rec["origin"],
            "arrival_facility_id": rec["arrival_facility_id"],
            "scheduled_arrival": fmt_dt(rec["scheduled_arrival"]),
            "estimated_arrival": fmt_dt(rec["estimated_arrival"]),
            "controlled_arrival": fmt_dt(rec["controlled_arrival"]),
            "last_eta_reported_at": fmt_dt(rec["last_eta_reported_at"]),
            "ops_status": rec["ops_status"],
            "control_status": rec["control_status"],
            "is_overflow": rec["is_overflow"],
            "provisional_delay_minutes": rec["provisional_delay_minutes"],
            "final_delay_minutes": rec["final_delay_minutes"],
        }
    )
    return out


def serialize_slot(rec):
    out = _common(rec)
    out.update(
        {
            "tmi_id": rec["tmi_id"],
            "slot_index": rec["slot_index"],
            "slot_time": fmt_dt(rec["slot_time"]),
            "is_ga_reserved": rec["is_ga_reserved"],
            "assigned_flight_id": rec["assigned_flight_id"],
            "original_flight_id": rec["original_flight_id"],
            "status": rec["status"],
        }
    )
    return out


def serialize_transaction(rec):
    out = _record(rec)
    out.update(
        {
            "tmi_id": rec["tmi_id"],
            "slot_id": rec["slot_id"],
            "flight_id": rec["flight_id"],
            "operator_id": rec["operator_id"],
            "transaction_type": rec["transaction_type"],
            "from_slot_time": fmt_dt(rec["from_slot_time"]),
            "to_slot_time": fmt_dt(rec["to_slot_time"]),
            "delay_delta_minutes": rec["delay_delta_minutes"],
            "note": rec["note"],
        }
    )
    return out


def serialize_compression_run(rec):
    out = _record(rec)
    out.update(
        {
            "tmi_id": rec["tmi_id"],
            "released_slot_count": rec["released_slot_count"],
            "moves_made": rec["moves_made"],
            "passes_executed": rec["passes_executed"],
            "promoted_ga_request_ids": list(rec["promoted_ga_request_ids"]),
            "remaining_open_slots": rec["remaining_open_slots"],
        }
    )
    return out


def serialize_ga_request(rec):
    out = _common(rec)
    out.update(
        {
            "operator_id": rec["operator_id"],
            "tmi_id": rec["tmi_id"],
            "requested_window_start": fmt_dt(rec["requested_window_start"]),
            "requested_window_end": fmt_dt(rec["requested_window_end"]),
            "priority_class": rec["priority_class"],
            "status": rec["status"],
            "accommodated_flight_id": rec["accommodated_flight_id"],
            "accommodated_slot_time": fmt_dt(rec["accommodated_slot_time"]),
        }
    )
    return out


def serialize_reroute(rec):
    out = _record(rec)
    out.update(
        {
            "tmi_id": rec["tmi_id"],
            "flight_id": rec["flight_id"],
            "via_sector_id": rec["via_sector_id"],
            "assigned_route": rec["assigned_route"],
            "hourly_bucket": fmt_dt(rec["hourly_bucket"]),
        }
    )
    return out


def serialize_ledger(rec):
    out = _common(rec)
    out.update(
        {
            "operator_id": rec["operator_id"],
            "tmi_id": rec["tmi_id"],
            "flight_count": rec["flight_count"],
            "attributed_delay_minutes": rec["attributed_delay_minutes"],
            "reversed_delay_minutes": rec["reversed_delay_minutes"],
            "fair_share_minutes": rec["fair_share_minutes"],
            "deviation_minutes": rec["deviation_minutes"],
        }
    )
    return out
