"""Entity serializers: public representation including computed fields.

Derived fields (hours, eligibility, tiers, counters) are pure functions of
current state and are computed at read time; stored snapshots (required_kits,
sequence_no, kits_consumed, assigned_student_count) are emitted as stored.
"""
import calc
import db


def _common(r):
    return {
        'id': r['id'],
        'created_at': r['created_at'],
        'updated_at': r['updated_at'],
        'version': r['version'],
    }


def area_office(r):
    out = _common(r)
    out.update({
        'name': r['name'],
        'region_code': r['region_code'],
        'max_districts': r['max_districts'],
    })
    return out


def district(r):
    out = _common(r)
    out.update({
        'area_office_id': r['area_office_id'],
        'name': r['name'],
        'relationship_status': r['relationship_status'],
    })
    return out


def school(r):
    out = _common(r)
    out.update({
        'district_id': r['district_id'],
        'name': r['name'],
        'grade_band_low': r['grade_band_low'],
        'grade_band_high': r['grade_band_high'],
        'instructional_days': list(r['instructional_days']),
    })
    return out


def partner(r):
    out = _common(r)
    out.update({
        'name': r['name'],
        'industry': r['industry'],
        'status': r['status'],
    })
    return out


def volunteer(r):
    out = _common(r)
    out.update({
        'corporate_partner_id': r['corporate_partner_id'],
        'full_name': r['full_name'],
        'email': r['email'],
        'screening_status': r['screening_status'],
        'screening_expires_on': (db.render_dt(r['screening_expires_on'])
                                 if r['screening_expires_on'] is not None else None),
        'training_status': r['training_status'],
        'training_expires_on': (db.render_dt(r['training_expires_on'])
                                if r['training_expires_on'] is not None else None),
        'engagement_status': r['engagement_status'],
        'hours_contributed': float(calc.volunteer_hours(r['id'])),
        'eligible': calc.is_eligible(r),
    })
    return out


def program(r):
    out = _common(r)
    out.update({
        'code': r['code'],
        'title': r['title'],
        'grade_band_low': r['grade_band_low'],
        'grade_band_high': r['grade_band_high'],
        'session_count': r['session_count'],
        'minutes_per_session': r['minutes_per_session'],
        'capstone_required': r['capstone_required'],
        'capstone_facility': r['capstone_facility'],
        'min_students': r['min_students'],
        'max_students': r['max_students'],
    })
    return out


def agreement(r):
    out = _common(r)
    out.update({
        'school_id': r['school_id'],
        'program_catalog_id': r['program_catalog_id'],
        'sponsor_partner_id': r['sponsor_partner_id'],
        'school_year': r['school_year'],
        'funding_pledged_cents': r['funding_pledged_cents'],
        'funding_received_cents': r['funding_received_cents'],
        'pending_program_catalog_id': r['pending_program_catalog_id'],
        'pending_funding_pledged_cents': r['pending_funding_pledged_cents'],
        'status': r['status'],
        'sponsor_volunteer_hours': float(calc.sponsor_hours_for(r, ('DELIVERED',))),
        'recognition_tier': calc.agreement_recognition_tier(r),
        'deliveries_completed_count': calc.deliveries_completed_count(r['id']),
    })
    return out


def delivery(r):
    out = _common(r)
    out.update({
        'agreement_id': r['agreement_id'],
        'program_catalog_id': r['program_catalog_id'],
        'lead_volunteer_id': r['lead_volunteer_id'],
        'classroom_label': r['classroom_label'],
        'teacher_email': r['teacher_email'],
        'teacher_confirmed': r['teacher_confirmed'],
        'enrolled_count': r['enrolled_count'],
        'required_kits': r['required_kits'],
        'status': r['status'],
        'kit_status': r['kit_status'],
        'kits_consumed': r['kits_consumed'],
        'sessions_delivered_count': calc.sessions_delivered_count(r['id']),
        'sessions_blocked_count': calc.sessions_blocked_count(r['id']),
    })
    return out


def session(r):
    out = _common(r)
    out.update({
        'delivery_id': r['delivery_id'],
        'volunteer_id': r['volunteer_id'],
        'sequence_no': r['sequence_no'],
        'scheduled_date': r['scheduled_date'].isoformat(),
        'start_minutes': r['start_minutes'],
        'end_minutes': r['end_minutes'],
        'duration_minutes': r['duration_minutes'],
        'status': r['status'],
    })
    return out


def inventory(r):
    out = _common(r)
    out.update({
        'area_office_id': r['area_office_id'],
        'program_catalog_id': r['program_catalog_id'],
        'assembled_count': r['assembled_count'],
        'available_count': r['available_count'],
        'reserved_count': r['reserved_count'],
        'distributed_count': r['distributed_count'],
        'written_off_count': r['written_off_count'],
        'consumed_count': r['consumed_count'],
    })
    return out


def capstone(r):
    out = _common(r)
    out.update({
        'delivery_id': r['delivery_id'],
        'facility': r['facility'],
        'event_date': r['event_date'].isoformat(),
        'start_minutes': r['start_minutes'],
        'end_minutes': r['end_minutes'],
        'rotation_slot_count': r['rotation_slot_count'],
        'status': r['status'],
        'assigned_student_count': r['assigned_student_count'],
    })
    return out


def student(r):
    out = _common(r)
    out.update({
        'delivery_id': r['delivery_id'],
        'capstone_event_id': r['capstone_event_id'],
        'full_name': r['full_name'],
        'external_ref': r['external_ref'],
        'rotation_group': r['rotation_group'],
        'capstone_role': r['capstone_role'],
        'pre_score': r['pre_score'],
        'post_score': r['post_score'],
        'survey_status': r['survey_status'],
    })
    return out
