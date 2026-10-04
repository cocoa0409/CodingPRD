"""Clinician selectors per PRD §2.9, §3.5, §3.6 and SCAFFOLD §1.3.

Both selectors rank by (active_daily_visit_count ASC, created_at ASC); the
clinician id is NEVER a tie-break. Empty pool → ERR_NO_AVAILABLE_CLINICIAN.
"""
from db import db
from errors import err_state, ERR_NO_AVAILABLE_CLINICIAN


def _sorted_candidates(candidates):
    return sorted(
        candidates,
        key=lambda c: (int(c.get("active_daily_visit_count") or 0),
                       c.get("created_at") or ""),
    )


def routine_selector(program, visit_type):
    """PRD §3.5: INITIAL_ASSESSMENT / ROUTINE_FOLLOWUP / POST_ED_FOLLOWUP all
    require NP discipline. URGENT is rejected before reaching this selector.
    """
    candidates = []
    for c in db.clinicians.values():
        if c.get("care_program_id") != program.get("id"):
            continue
        if c.get("status") != "ACTIVE":
            continue
        if c.get("home_zip") not in (program.get("service_geography_zips") or []):
            continue
        if c.get("discipline") != "NP":
            continue
        if int(c.get("active_daily_visit_count") or 0) >= int(c.get("max_daily_visits") or 0):
            continue
        candidates.append(c)
    pool = _sorted_candidates(candidates)
    if not pool:
        raise err_state(ERR_NO_AVAILABLE_CLINICIAN,
                        "No available clinician for this visit")
    return pool[0]


def urgent_selector(program):
    """PRD §3.6: stricter than routine — urgent_response_qualified required;
    discipline is not restricted at dispatch.
    """
    candidates = []
    for c in db.clinicians.values():
        if c.get("care_program_id") != program.get("id"):
            continue
        if c.get("status") != "ACTIVE":
            continue
        if not c.get("urgent_response_qualified"):
            continue
        if c.get("home_zip") not in (program.get("service_geography_zips") or []):
            continue
        if int(c.get("active_daily_visit_count") or 0) >= int(c.get("max_daily_visits") or 0):
            continue
        candidates.append(c)
    pool = _sorted_candidates(candidates)
    if not pool:
        raise err_state(ERR_NO_AVAILABLE_CLINICIAN,
                        "No available clinician for urgent dispatch")
    return pool[0]
