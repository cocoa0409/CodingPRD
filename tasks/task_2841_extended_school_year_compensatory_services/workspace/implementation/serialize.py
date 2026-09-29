"""Output shaping. Internal bookkeeping keys are prefixed with '_' and hidden."""
from calcs import refresh_available


def public(record):
    if record is None:
        return None
    return {key: value for key, value in record.items() if not key.startswith("_")}


def many(records):
    return [public(r) for r in records]


def allocation_public(allocation):
    refresh_available(allocation)
    return public(allocation)


def allocations_public(allocations):
    return [allocation_public(a) for a in allocations]


def due_process_packet(award, open_record_count):
    """PRD 3.9: a flat, purpose-built summary rather than the stored award."""
    return {
        "award_id": award["id"],
        "student_id": award["student_id"],
        "calculation_variant": award["calculation_variant"],
        "severity_factor": award["severity_factor"],
        "computed_minutes": award["computed_minutes"],
        "proposed_minutes": award["proposed_minutes"],
        "agreed_minutes": award["agreed_minutes"],
        "delivered_minutes": award["delivered_minutes"],
        "scheduled_minutes": award["scheduled_minutes"],
        "forfeited_minutes": award["forfeited_minutes"],
        "remaining_owed_minutes": award["remaining_owed_minutes"],
        "verified_missed_log_count": award["verified_missed_log_count"],
        "excluded_log_count": award["excluded_log_count"],
        "dispute_round_count": award["dispute_round_count"],
        "parent_no_show_count": award["parent_no_show_count"],
        "negotiation_status": award["negotiation_status"],
        "delivery_status": award["delivery_status"],
        "delivery_deadline_date": award["delivery_deadline_date"],
        "open_due_process_record_count": open_record_count,
    }
