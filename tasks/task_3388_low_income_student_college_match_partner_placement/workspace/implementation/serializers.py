"""Entity serializers.

Common fields (PRD section 2.5): id, created_at, updated_at, version on every
primary resource except RankingEntry (id and created_at only). Computed
PartnerCollege fields are derived at read time: slots_committed counts the
college's Matches in BINDING or ENROLLED; enrolled_count counts OutcomeRecords
ever created with the college.
"""
import clock
import store


def _dt(value):
    return None if value is None else clock.fmt(value)


def slots_committed(college_id):
    return sum(
        1 for m in store.matches.values()
        if m["college_id"] == college_id and m["status"] in ("BINDING", "ENROLLED")
    )


def enrolled_count(college_id):
    return sum(1 for o in store.outcomes.values() if o["college_id"] == college_id)


def cycle(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "app_opens_at": _dt(c["app_opens_at"]),
        "app_closes_at": _dt(c["app_closes_at"]),
        "ranking_opens_at": _dt(c["ranking_opens_at"]),
        "ranking_closes_at": _dt(c["ranking_closes_at"]),
        "phase": c["phase"],
        "match_run_completed": c["match_run_completed"],
        "created_at": _dt(c["created_at"]),
        "updated_at": _dt(c["updated_at"]),
        "version": c["version"],
    }


def college(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "aid_policy": c["aid_policy"],
        "min_academic_index": c["min_academic_index"],
        "match_slots": c["match_slots"],
        "coa_cents": c["coa_cents"],
        "status": c["status"],
        "slots_committed": slots_committed(c["id"]),
        "enrolled_count": enrolled_count(c["id"]),
        "created_at": _dt(c["created_at"]),
        "updated_at": _dt(c["updated_at"]),
        "version": c["version"],
    }


def student(s):
    return {
        "id": s["id"],
        "email": s["email"],
        "full_name": s["full_name"],
        "state_code": s["state_code"],
        "source": s["source"],
        "student_stage": s["student_stage"],
        "created_at": _dt(s["created_at"]),
        "updated_at": _dt(s["updated_at"]),
        "version": s["version"],
    }


def counselor(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "school_name": c["school_name"],
        "state_code": c["state_code"],
        "created_at": _dt(c["created_at"]),
        "updated_at": _dt(c["updated_at"]),
        "version": c["version"],
    }


def partner(p):
    return {
        "id": p["id"],
        "org_name": p["org_name"],
        "state_code": p["state_code"],
        "contact_email": p["contact_email"],
        "created_at": _dt(p["created_at"]),
        "updated_at": _dt(p["updated_at"]),
        "version": p["version"],
    }


def referral(r):
    return {
        "id": r["id"],
        "student_id": r["student_id"],
        "cycle_id": r["cycle_id"],
        "counselor_id": r["counselor_id"],
        "partner_id": r["partner_id"],
        "note": r["note"],
        "status": r["status"],
        "created_at": _dt(r["created_at"]),
        "updated_at": _dt(r["updated_at"]),
        "version": r["version"],
    }


def prep_program(p):
    return {
        "id": p["id"],
        "student_id": p["student_id"],
        "program_type": p["program_type"],
        "cohort_label": p["cohort_label"],
        "starts_on": _dt(p["starts_on"]),
        "ends_on": _dt(p["ends_on"]),
        "status": p["status"],
        "created_at": _dt(p["created_at"]),
        "updated_at": _dt(p["updated_at"]),
        "version": p["version"],
    }


def application(a):
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "cycle_id": a["cycle_id"],
        "referral_id": a["referral_id"],
        "household_income_cents": a["household_income_cents"],
        "household_size": a["household_size"],
        "self_reported_assets_cents": a["self_reported_assets_cents"],
        "gpa_scaled": a["gpa_scaled"],
        "test_score": a["test_score"],
        "essay_text": a["essay_text"],
        "status": a["status"],
        "academic_index": a["academic_index"],
        "prep_alum": a["prep_alum"],
        "need_tier": a["need_tier"],
        "verification_flag": a["verification_flag"],
        "matched_college_id": a["matched_college_id"],
        "submitted_at": _dt(a["submitted_at"]),
        "created_at": _dt(a["created_at"]),
        "updated_at": _dt(a["updated_at"]),
        "version": a["version"],
    }


def ranking_entry(e):
    # RankingEntry is the single exception to common fields: id and
    # created_at only (PRD section 2.5).
    return {
        "id": e["id"],
        "application_id": e["application_id"],
        "college_id": e["college_id"],
        "rank_position": e["rank_position"],
        "list_seq": e["list_seq"],
        "created_at": _dt(e["created_at"]),
    }


def match(m):
    return {
        "id": m["id"],
        "application_id": m["application_id"],
        "college_id": m["college_id"],
        "cycle_id": m["cycle_id"],
        "rank_position_awarded": m["rank_position_awarded"],
        "status": m["status"],
        "matched_at": _dt(m["matched_at"]),
        "created_at": _dt(m["created_at"]),
        "updated_at": _dt(m["updated_at"]),
        "version": m["version"],
    }


def aid_package(p):
    return {
        "id": p["id"],
        "match_id": p["match_id"],
        "application_id": p["application_id"],
        "college_id": p["college_id"],
        "coa_cents": p["coa_cents"],
        "efc_cents": p["efc_cents"],
        "need_cents": p["need_cents"],
        "work_study_cents": p["work_study_cents"],
        "loan_cents": p["loan_cents"],
        "grant_cents": p["grant_cents"],
        "aid_variant": p["aid_variant"],
        "guaranteed_full_need": p["guaranteed_full_need"],
        "status": p["status"],
        "created_at": _dt(p["created_at"]),
        "updated_at": _dt(p["updated_at"]),
        "version": p["version"],
    }


def verification(v):
    return {
        "id": v["id"],
        "application_id": v["application_id"],
        "submitted_by_counselor_id": v["submitted_by_counselor_id"],
        "submitted_by_partner_id": v["submitted_by_partner_id"],
        "verified_income_cents": v["verified_income_cents"],
        "verified_assets_cents": v["verified_assets_cents"],
        "verified_household_size": v["verified_household_size"],
        "outcome": v["outcome"],
        "decided_by_partner_id": v["decided_by_partner_id"],
        "created_at": _dt(v["created_at"]),
        "updated_at": _dt(v["updated_at"]),
        "version": v["version"],
    }


def outcome(o):
    return {
        "id": o["id"],
        "application_id": o["application_id"],
        "college_id": o["college_id"],
        "cycle_id": o["cycle_id"],
        "match_id": o["match_id"],
        "status": o["status"],
        "credits_completed": o["credits_completed"],
        "last_checkpoint_at": _dt(o["last_checkpoint_at"]),
        "created_at": _dt(o["created_at"]),
        "updated_at": _dt(o["updated_at"]),
        "version": o["version"],
    }
