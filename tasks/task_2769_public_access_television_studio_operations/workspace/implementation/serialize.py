"""Row -> JSON serialisers.

Derived counters (PRD 2.9) are treated as invariants: they are recomputed from
their defining sums whenever a row is emitted, so no cascade can leave one
stale.
"""

import calc
import db
from util import iso_ms, iso_s


def _common(row, data):
    data["id"] = row["id"]
    data["created_at"] = iso_ms(row["created_at"])
    if "updated_at" in row:
        data["updated_at"] = iso_ms(row["updated_at"])
    if "version" in row:
        data["version"] = row["version"]
    return data


# --------------------------------------------------------------------------- #
# derived counters
# --------------------------------------------------------------------------- #
def producer_reservations(producer_id):
    return [r for r in db.all_rows("reservations") if r["producer_id"] == producer_id]


def deposit_held_cents(producer_id):
    return sum(
        r["deposit_hold_cents"]
        for r in producer_reservations(producer_id)
        if r["status"] in ("CONFIRMED", "CHECKED_OUT", "DAMAGE_REVIEW")
    )


def deposit_forfeited_total_cents(producer_id):
    return sum(
        r["deposit_forfeited_cents"]
        for r in producer_reservations(producer_id)
        if r["status"] == "SETTLED"
    )


def producer_assignments(producer_id):
    return [a for a in db.all_rows("crew_assignments") if a["volunteer_producer_id"] == producer_id]


def volunteer_hours_tenths(producer_id):
    return sum(
        a["credited_hours_tenths"]
        for a in producer_assignments(producer_id)
        if a["status"] == "COMPLETED"
    )


def confirmed_crew_commitments(producer_id):
    return len([a for a in producer_assignments(producer_id) if a["status"] == "CONFIRMED"])


def open_reservation_count(resource_id):
    return len(
        [
            r
            for r in db.all_rows("reservations")
            if r["resource_id"] == resource_id
            and r["status"] in ("CONFIRMED", "CHECKED_OUT", "DAMAGE_REVIEW")
        ]
    )


def channel_seconds(channel_id, status):
    return sum(
        s["occupied_seconds"]
        for s in db.all_rows("playback_slots")
        if s["channel_id"] == channel_id and s["status"] == status
    )


def course_counts(course_id):
    enrolled = 0
    passed = 0
    for row in db.all_rows("course_enrollments"):
        if row["course_id"] != course_id:
            continue
        if row["status"] in ("ENROLLED", "ATTENDED", "PASSED", "FAILED"):
            enrolled += 1
        if row["status"] == "PASSED":
            passed += 1
    return enrolled, passed


# --------------------------------------------------------------------------- #
# entity serialisers
# --------------------------------------------------------------------------- #
def producer(row):
    return _common(
        row,
        {
            "legal_name": row["legal_name"],
            "email": row["email"],
            "residency_verified": row["residency_verified"],
            "status": row["status"],
            "certification_level": calc.certification_level(row),
            "competency_codes": calc.competency_codes(row),
            "suspension_points": row["suspension_points"],
            "indemnification_expires_at": iso_s(row["indemnification_expires_at"]),
            "deposit_held_cents": deposit_held_cents(row["id"]),
            "deposit_forfeited_total_cents": deposit_forfeited_total_cents(row["id"]),
            "volunteer_hours_tenths": volunteer_hours_tenths(row["id"]),
            "confirmed_crew_commitments": confirmed_crew_commitments(row["id"]),
            "reinstated_count": row["reinstated_count"],
            "revocation_reason": row["revocation_reason"],
        },
    )


def training_course(row):
    enrolled, passed = course_counts(row["id"])
    return _common(
        row,
        {
            "course_code": row["course_code"],
            "title": row["title"],
            "tier": row["tier"],
            "grants_competency_codes": list(row["grants_competency_codes"]),
            "seat_capacity": row["seat_capacity"],
            "session_start_at": iso_s(row["session_start_at"]),
            "session_end_at": iso_s(row["session_end_at"]),
            "enrolled_count": enrolled,
            "passed_count": passed,
        },
    )


def course_enrollment(row):
    return _common(
        row,
        {
            "producer_id": row["producer_id"],
            "course_id": row["course_id"],
            "status": row["status"],
            "practical_score": row["practical_score"],
            "attended_at": iso_s(row["attended_at"]),
            "graded_at": iso_s(row["graded_at"]),
        },
    )


def series(row):
    return _common(
        row,
        {
            "producer_id": row["producer_id"],
            "title": row["title"],
            "cadence": row["cadence"],
            "first_air_date": iso_s(row["first_air_date"]),
            "predecessor_series_id": row["predecessor_series_id"],
            "sequence_number": row["sequence_number"],
            "seniority_at": iso_s(row["seniority_at"]),
            "status": row["status"],
            "hold_plan_slots_granted": row["hold_plan_slots_granted"],
            "remaining_hold_slots": row["remaining_hold_slots"],
            "missed_windows": row["missed_windows"],
        },
    )


def program(row):
    return _common(
        row,
        {
            "producer_id": row["producer_id"],
            "series_id": row["series_id"],
            "title": row["title"],
            "episode_number": row["episode_number"],
            "runtime_seconds": row["runtime_seconds"],
            "is_live": row["is_live"],
            "required_crew_roles": list(row["required_crew_roles"]),
            "review_status": row["review_status"],
            "clearance_status": row["clearance_status"],
            "reviewed_by_user_id": row["reviewed_by_user_id"],
            "finding_category": row["finding_category"],
            "finding_notes": row["finding_notes"],
            "revision_round": row["revision_round"],
            "attestation_sequence_high": row["attestation_sequence_high"],
            "withdrawn_reason": row["withdrawn_reason"],
        },
    )


def attestation(row):
    # PRD 2.4: an attestation carries only id and created_at -- no updated_at
    # and no version, and neither is ever emitted for it.
    return {
        "id": row["id"],
        "program_id": row["program_id"],
        "signed_by_producer_id": row["signed_by_producer_id"],
        "attestation_kind": row["attestation_kind"],
        "statement_version": row["statement_version"],
        "third_party_material": row["third_party_material"],
        "license_reference": row["license_reference"],
        "sequence_number": row["sequence_number"],
        "effective_from": iso_s(row["effective_from"]),
        "effective_until": iso_s(row["effective_until"]),
        "created_at": iso_ms(row["created_at"]),
    }


def channel(row):
    return _common(
        row,
        {
            "call_sign": row["call_sign"],
            "tier": row["tier"],
            "daily_window_start_minute": row["daily_window_start_minute"],
            "daily_window_end_minute": row["daily_window_end_minute"],
            "inter_program_buffer_seconds": row["inter_program_buffer_seconds"],
            "preemption_enabled": row["preemption_enabled"],
            "scheduled_seconds": channel_seconds(row["id"], "SCHEDULED"),
            "aired_seconds": channel_seconds(row["id"], "AIRED"),
            "slot_sequence_high": row["slot_sequence_high"],
        },
    )


def playback_slot(row):
    return _common(
        row,
        {
            "channel_id": row["channel_id"],
            "program_id": row["program_id"],
            "series_id": row["series_id"],
            "booking_type": row["booking_type"],
            "start_at": iso_s(row["start_at"]),
            "occupied_seconds": row["occupied_seconds"],
            "end_at": iso_s(row["end_at"]),
            "status": row["status"],
            "required_crew_roles": list(row["required_crew_roles"]),
            "staffing_status": calc.staffing_status(row),
            "preempted_by_slot_id": row["preempted_by_slot_id"],
            "measured_households": row["measured_households"],
            "aired_at": iso_s(row["aired_at"]),
            "sequence_number": row["sequence_number"],
            "cancellation_reason": row["cancellation_reason"],
        },
    )


def studio_resource(row):
    return _common(
        row,
        {
            "resource_code": row["resource_code"],
            "resource_class": row["resource_class"],
            "required_competency_code": row["required_competency_code"],
            "capacity_slots": row["capacity_slots"],
            "turnaround_minutes": row["turnaround_minutes"],
            "base_deposit_cents": row["base_deposit_cents"],
            "replacement_value_cents": row["replacement_value_cents"],
            "status": row["status"],
            "open_reservation_count": open_reservation_count(row["id"]),
            "status_reason": row["status_reason"],
        },
    )


def reservation(row):
    return _common(
        row,
        {
            "producer_id": row["producer_id"],
            "resource_id": row["resource_id"],
            "linked_slot_id": row["linked_slot_id"],
            "start_at": iso_s(row["start_at"]),
            "end_at": iso_s(row["end_at"]),
            "status": row["status"],
            "risk_bp": row["risk_bp"],
            "deposit_hold_cents": row["deposit_hold_cents"],
            "late_fee_cents": row["late_fee_cents"],
            "assessed_repair_cents": row["assessed_repair_cents"],
            "deposit_forfeited_cents": row["deposit_forfeited_cents"],
            "deposit_refunded_cents": row["deposit_refunded_cents"],
            "uncovered_liability_cents": row["uncovered_liability_cents"],
            "checked_out_at": iso_s(row["checked_out_at"]),
            "returned_at": iso_s(row["returned_at"]),
            "condition_notes": row["condition_notes"],
            "cancellation_reason": row["cancellation_reason"],
        },
    )


def damage_assessment(row):
    return _common(
        row,
        {
            "reservation_id": row["reservation_id"],
            "severity": row["severity"],
            "repair_estimate_cents": row["repair_estimate_cents"],
            "assessed_repair_cents": row["assessed_repair_cents"],
            "suspension_points_assessed": row["suspension_points_assessed"],
            "status": row["status"],
            "filed_by_user_id": row["filed_by_user_id"],
            "waived_by_user_id": row["waived_by_user_id"],
            "waiver_reason": row["waiver_reason"],
            "damage_notes": row["damage_notes"],
        },
    )


def crew_assignment(row):
    return _common(
        row,
        {
            "slot_id": row["slot_id"],
            "volunteer_producer_id": row["volunteer_producer_id"],
            "crew_role": row["crew_role"],
            "status": row["status"],
            "credited_hours_tenths": row["credited_hours_tenths"],
            "release_reason": row["release_reason"],
        },
    )


def funding_period(row):
    return _common(
        row,
        {
            "fiscal_year": row["fiscal_year"],
            "quarter": row["quarter"],
            "basis": row["basis"],
            "gross_franchise_fee_cents": row["gross_franchise_fee_cents"],
            "service_period_earned_cents": row["service_period_earned_cents"],
            "remittance_received_cents": row["remittance_received_cents"],
            "capital_grant_cents": row["capital_grant_cents"],
            "allocable_base_cents": row["allocable_base_cents"],
            "admin_reserve_cents": row["admin_reserve_cents"],
            "capital_allocation_cents": row["capital_allocation_cents"],
            "operating_allocation_cents": row["operating_allocation_cents"],
            "total_program_funds_cents": row["total_program_funds_cents"],
            "report_status": row["report_status"],
            "revision_round": row["revision_round"],
            "submitted_by_user_id": row["submitted_by_user_id"],
            "decided_by_user_id": row["decided_by_user_id"],
            "decision_reason": row["decision_reason"],
        },
    )


def archive_asset(row):
    return _common(
        row,
        {
            "program_id": row["program_id"],
            "source_slot_id": row["source_slot_id"],
            "retention_class": row["retention_class"],
            "retain_until": iso_s(row["retain_until"]),
            "on_demand_status": row["on_demand_status"],
            "on_demand_views": row["on_demand_views"],
            "measured_households": row["measured_households"],
            "volunteer_hours_tenths": row["volunteer_hours_tenths"],
            "community_impact_index": row["community_impact_index"],
            "impact_variant": row["impact_variant"],
            "published_at": iso_s(row["published_at"]),
            "purged_at": iso_s(row["purged_at"]),
        },
    )


SERIALIZERS = {
    "producers": producer,
    "training_courses": training_course,
    "course_enrollments": course_enrollment,
    "series": series,
    "programs": program,
    "attestations": attestation,
    "channels": channel,
    "playback_slots": playback_slot,
    "studio_resources": studio_resource,
    "reservations": reservation,
    "damage_assessments": damage_assessment,
    "crew_assignments": crew_assignment,
    "funding_periods": funding_period,
    "archive_assets": archive_asset,
}


def dump(collection, row):
    return SERIALIZERS[collection](row)


def dump_all(collection, rows):
    serializer = SERIALIZERS[collection]
    return [serializer(row) for row in rows]
