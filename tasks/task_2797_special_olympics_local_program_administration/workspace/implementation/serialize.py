"""Response serialisers: one per entity, exposing exactly the declared fields."""
import db
from core import ADULT_AGE_YEARS, clock_date, ratio_out, whole_years, parse_date


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_program(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "region_code": row["region_code"],
        "compliance_posture": row["compliance_posture"],
        "certified_coach_count": row["certified_coach_count"],
        "credential_denominator_count": row["credential_denominator_count"],
        "expired_credential_count": row["expired_credential_count"],
        "expired_credential_ratio": ratio_out(row["expired_credential_ratio"]),
        "unresolved_urgent_referral_count": row["unresolved_urgent_referral_count"],
        "active_athlete_count": row["active_athlete_count"],
        "program_practice_minutes": row["program_practice_minutes"],
        "recognized_support_cents": row["recognized_support_cents"],
        "pledged_support_cents": row["pledged_support_cents"],
        "family_engagement_credit_cents": row["family_engagement_credit_cents"],
        "sweep_epoch": row["sweep_epoch"],
        "last_sweep_at": row["last_sweep_at"],
    })
    return out


def ser_athlete(row):
    out = _common(row)
    out.update({
        "program_id": row["program_id"],
        "legal_name": row["legal_name"],
        "birth_date": row["birth_date"],
        "sport": row["sport"],
        "down_syndrome_flag": row["down_syndrome_flag"],
        "registration_status": row["registration_status"],
        "medical_status": row["medical_status"],
        "registration_expires_on": row["registration_expires_on"],
        "current_medical_form_id": row["current_medical_form_id"],
        "cumulative_practice_minutes": row["cumulative_practice_minutes"],
        "counted_session_count": row["counted_session_count"],
        "withdrawal_reason_code": row["withdrawal_reason_code"],
    })
    return out


def ser_medical_form(row):
    out = _common(row)
    out.update({
        "athlete_id": row["athlete_id"],
        "exam_date": row["exam_date"],
        "physician_name": row["physician_name"],
        "physician_license_id": row["physician_license_id"],
        "attestation_cardiac_clearance": row["attestation_cardiac_clearance"],
        "attestation_seizure_history": row["attestation_seizure_history"],
        "attestation_atlantoaxial_screen": row["attestation_atlantoaxial_screen"],
        "restrictions": row["restrictions"],
        "status": row["status"],
        "revision_count": row["revision_count"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "rejection_reason_code": row["rejection_reason_code"],
        "expires_on": row["expires_on"],
        "approved_at": row["approved_at"],
    })
    return out


def volunteer_is_minor(row):
    born = parse_date(row["date_of_birth"])
    return whole_years(born, clock_date()) < ADULT_AGE_YEARS


def volunteer_status(row):
    creds = [c for c in db.credentials.values() if c["volunteer_id"] == row["id"]]
    today = clock_date()
    for cred in creds:
        if cred["status"] == "CERTIFIED":
            expires = parse_date(cred.get("expires_on"))
            if expires is not None and expires >= today:
                return "CREDENTIALED"
    if creds and all(c["status"] in ("DENIED", "EXPIRED", "RENEWAL_IN_PROGRESS")
                     for c in creds):
        return "INACTIVE"
    return "PROSPECT"


def ser_volunteer(row):
    out = _common(row)
    out.update({
        "program_id": row["program_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "date_of_birth": row["date_of_birth"],
        "volunteer_class": row["volunteer_class"],
        "status": volunteer_status(row),
        "is_minor": volunteer_is_minor(row),
    })
    return out


def ser_credential(row):
    out = _common(row)
    out.update({
        "volunteer_id": row["volunteer_id"],
        "role_class": row["role_class"],
        "status": row["status"],
        "screening_result": row["screening_result"],
        "screening_completed_on": row["screening_completed_on"],
        "screening_expires_on": row["screening_expires_on"],
        "screening_recorded_by_user_id": row["screening_recorded_by_user_id"],
        "screening_vendor_reference": row["screening_vendor_reference"],
        "training_completed_on": row["training_completed_on"],
        "training_expires_on": row["training_expires_on"],
        "training_recorded_by_user_id": row["training_recorded_by_user_id"],
        "training_curriculum_code": row["training_curriculum_code"],
        "certified_by_user_id": row["certified_by_user_id"],
        "certified_at": row["certified_at"],
        "flag_override_reason": row["flag_override_reason"],
        "expires_on": row["expires_on"],
        "denial_reason_code": row["denial_reason_code"],
    })
    return out


def ser_season(row):
    out = _common(row)
    out.update({
        "program_id": row["program_id"],
        "sport": row["sport"],
        "season_name": row["season_name"],
        "practice_minimum_sessions": row["practice_minimum_sessions"],
        "practice_minimum_minutes": row["practice_minimum_minutes"],
        "registration_deadline": row["registration_deadline"],
        "divisioning_date": row["divisioning_date"],
        "competition_date": row["competition_date"],
        "games_level": row["games_level"],
        "entry_slot_budget": row["entry_slot_budget"],
        "advancement_slots_per_division": row["advancement_slots_per_division"],
        "status": row["status"],
        "divisioning_run_count": row["divisioning_run_count"],
        "entry_count": row["entry_count"],
        "divisioned_entry_count": row["divisioned_entry_count"],
    })
    return out


def ser_session(row):
    out = _common(row)
    out.update({
        "season_id": row["season_id"],
        "coach_credential_id": row["coach_credential_id"],
        "scheduled_start": row["scheduled_start"],
        "duration_minutes": row["duration_minutes"],
        "capacity_slots": row["capacity_slots"],
        "scheduled_end": row["scheduled_end"],
        "counts_toward_minimum": row["counts_toward_minimum"],
        "recorded_attendance_count": row["recorded_attendance_count"],
        "status": row["status"],
        "void_reason_code": row["void_reason_code"],
    })
    return out


def ser_attendance(row):
    out = _common(row)
    out.update({
        "session_id": row["session_id"],
        "athlete_id": row["athlete_id"],
        "minutes_present": row["minutes_present"],
        "required_minutes": row["required_minutes"],
        "status": row["status"],
        "counted_minutes": row["counted_minutes"],
        "season_id": row["season_id"],
    })
    return out


def ser_division(row):
    out = _common(row)
    out.update({
        "season_id": row["season_id"],
        "merged_into_division_id": row["merged_into_division_id"],
        "event_code": row["event_code"],
        "participant_type": row["participant_type"],
        "age_group": row["age_group"],
        "ability_band_high": row["ability_band_high"],
        "ability_band_low": row["ability_band_low"],
        "ability_spread_ratio": ratio_out(row["ability_spread_ratio"]),
        "entry_count": row["entry_count"],
        "merged_source_count": row["merged_source_count"],
        "status": row["status"],
    })
    return out


def ser_entry(row):
    out = _common(row)
    out.update({
        "season_id": row["season_id"],
        "division_id": row["division_id"],
        "participant_type": row["participant_type"],
        "participant_id": row["participant_id"],
        "event_code": row["event_code"],
        "skill_score": row["skill_score"],
        "age_on_competition_date": row["age_on_competition_date"],
        "age_group": row["age_group"],
        "seed_rank": row["seed_rank"],
        "result_value": row["result_value"],
        "performance_ratio": ratio_out(row["performance_ratio"]),
        "placement": row["placement"],
        "advancement_status": row["advancement_status"],
        "status": row["status"],
        "disqualification_reason_code": row["disqualification_reason_code"],
        "void_reason_code": row["void_reason_code"],
    })
    return out


def ser_team(row):
    out = _common(row)
    out.update({
        "season_id": row["season_id"],
        "team_name": row["team_name"],
        "athlete_ids": list(row["athlete_ids"]),
        "partner_volunteer_ids": list(row["partner_volunteer_ids"]),
        "athlete_count": row["athlete_count"],
        "partner_count": row["partner_count"],
        "age_span_years": row["age_span_years"],
        "roster_status": row["roster_status"],
    })
    return out


def ser_screening(row):
    out = _common(row)
    out.update({
        "athlete_id": row["athlete_id"],
        "event_name": row["event_name"],
        "discipline": row["discipline"],
        "screened_on": row["screened_on"],
        "finding_severity": row["finding_severity"],
        "finding_note": row["finding_note"],
        "referral_status": row["referral_status"],
        "referral_due_on": row["referral_due_on"],
        "followup_count": row["followup_count"],
        "last_followup_note": row["last_followup_note"],
    })
    return out


def ser_contribution(row):
    out = _common(row)
    out.update({
        "program_id": row["program_id"],
        "donor_name": row["donor_name"],
        "contribution_type": row["contribution_type"],
        "designation": row["designation"],
        "stated_value_cents": row["stated_value_cents"],
        "volunteer_hours": row["volunteer_hours"],
        "recognized_value_cents": row["recognized_value_cents"],
        "match_credit_cents": row["match_credit_cents"],
        "received_on": row["received_on"],
        "status": row["status"],
        "void_reason_code": row["void_reason_code"],
    })
    return out
