"""The match selector (PRD 3.5) and the turnaround gate (PRD 3.6)."""

from datetime import timedelta

import calc
import derive
import store
from errors import ApiError

BLOCKING_PLACEMENT = ("PROPOSED", "ACTIVE", "REMOVAL_PENDING", "COMPLETED")


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def agreement_scope(request_row):
    if request_row.get("preferred_district_id"):
        rows = store.agreements_of_district(request_row["preferred_district_id"])
    else:
        rows = store.all_of(store.AGREEMENTS)
    for agreement in rows:
        derive.expire_agreement(agreement)
        derive.derive_agreement_ledger(agreement)
    return rows


def routing_envelope_check(request_row, scope=None):
    """Ladder rungs 29 and 30 as they apply to routing."""
    if scope is None:
        scope = agreement_scope(request_row)
    active = [a for a in scope if a["status"] == "ACTIVE"]
    if not active:
        return
    envelope_ok = [
        a for a in active
        if request_row["requested_subject"] in a["allowed_subjects"]
        and request_row["requested_grade_band"] in a["allowed_grade_bands"]
    ]
    if not envelope_ok:
        raise ApiError(
            "ERR_SUBJECT_BAND_NOT_ALLOWED",
            "The requested subject and grade band are outside the agreement "
            "envelope.")
    window_ok = [
        a for a in envelope_ok
        if a["window_start"] <= request_row["term_start_date"]
        and request_row["term_end_date"] <= a["window_end"]
    ]
    if not window_ok:
        raise ApiError(
            "ERR_TERM_OUTSIDE_AGREEMENT_WINDOW",
            "The request's term interval is not inside the agreement window.")


def qualifying_agreement(request_row, teacher):
    """Earliest-created ACTIVE agreement of the teacher's district that can
    back this request, or None."""
    for agreement in store.agreements_of_district(teacher["district_id"]):
        derive.expire_agreement(agreement)
        derive.derive_agreement_ledger(agreement)
        if agreement["status"] != "ACTIVE":
            continue
        if request_row["requested_subject"] not in agreement["allowed_subjects"]:
            continue
        if (request_row["requested_grade_band"]
                not in agreement["allowed_grade_bands"]):
            continue
        if not (agreement["window_start"] <= request_row["term_start_date"]
                and request_row["term_end_date"] <= agreement["window_end"]):
            continue
        if agreement["seats_committed"] >= agreement["placement_cap"]:
            continue
        return agreement
    return None


def teacher_raw_conflict(teacher, term_start, term_end, ignore_placement_id=None):
    for placement in store.placements_of_teacher(teacher["id"]):
        if placement["placement_status"] not in BLOCKING_PLACEMENT:
            continue
        if ignore_placement_id and placement["id"] == ignore_placement_id:
            continue
        if _overlaps(placement["start_date"], placement["end_date"],
                     term_start, term_end):
            return True
    return False


def teacher_turnaround_conflict(teacher, term_start, term_end,
                                ignore_placement_id=None):
    pad = timedelta(days=calc.TURNAROUND_PAD_DAYS)
    for placement in store.placements_of_teacher(teacher["id"]):
        if placement["placement_status"] not in BLOCKING_PLACEMENT:
            continue
        if ignore_placement_id and placement["id"] == ignore_placement_id:
            continue
        if _overlaps(placement["start_date"] - pad, placement["end_date"] + pad,
                     term_start, term_end):
            return True
    return False


def eligible_teachers(request_row, candidate):
    commute_ceiling = min(int(request_row["max_commute_miles"]),
                          calc.COMMUTE_CEILING_MILES)
    excluded = set(request_row["excluded_cooperating_teacher_ids"])
    results = []
    for teacher in store.all_of(store.TEACHERS):
        derive.expire_teacher_training(teacher)
        if teacher["qualification_status"] != "QUALIFIED":
            continue
        if teacher["subject_endorsement"] != request_row["requested_subject"]:
            continue
        if teacher["grade_band"] != request_row["requested_grade_band"]:
            continue
        preferred = request_row.get("preferred_district_id")
        if preferred and teacher["district_id"] != preferred:
            continue
        if teacher["id"] in excluded:
            continue
        derive.derive_teacher_counters(teacher)
        if (teacher["active_placement_count"]
                >= teacher["max_concurrent_candidates"]):
            continue
        commute = calc.manhattan(candidate["home_grid_x"],
                                 candidate["home_grid_y"],
                                 teacher["site_grid_x"], teacher["site_grid_y"])
        if commute > commute_ceiling:
            continue
        agreement = qualifying_agreement(request_row, teacher)
        if agreement is None:
            continue
        if teacher_raw_conflict(teacher, request_row["term_start_date"],
                                request_row["term_end_date"]):
            continue
        results.append((teacher, agreement, commute))
    return results


def eligible_supervisors(request_row, teacher):
    results = []
    for supervisor in store.all_of(store.SUPERVISORS):
        derive.derive_supervisor(supervisor)
        if not supervisor["accepting_new_placements"]:
            continue
        if supervisor["primary_subject"] != request_row["requested_subject"]:
            continue
        if (request_row["requested_grade_band"]
                not in supervisor["covered_grade_bands"]):
            continue
        travel = calc.manhattan(supervisor["home_grid_x"],
                                supervisor["home_grid_y"],
                                teacher["site_grid_x"], teacher["site_grid_y"])
        if travel > supervisor["max_travel_miles"]:
            continue
        added = calc.stage_points("PROPOSED", travel)
        if (supervisor["caseload_points"] + added
                > supervisor["max_caseload_points"]):
            continue
        results.append((supervisor, travel))
    return results


def select_pair(request_row, candidate):
    """Return (teacher, agreement, supervisor, commute, travel) or None."""
    pairs = []
    for teacher, agreement, commute in eligible_teachers(request_row, candidate):
        for supervisor, travel in eligible_supervisors(request_row, teacher):
            pairs.append((teacher, agreement, supervisor, commute, travel))
    if not pairs:
        return None
    pairs.sort(key=lambda p: (
        p[3],                                  # commute ascending
        -int(p[0]["years_experience"]),        # teacher experience descending
        p[4],                                  # supervisor travel ascending
        p[0]["created_at"], p[0]["_seq"],     # teacher created_at ascending
        p[2]["created_at"], p[2]["_seq"],     # supervisor created_at ascending
    ))
    return pairs[0]
