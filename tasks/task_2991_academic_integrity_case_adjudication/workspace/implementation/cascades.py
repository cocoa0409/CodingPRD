"""Multi-row side effects: the five-hop imposition cascade, the four-hop
appeal-overturn cascade, remand unwinding, supersession and the notice side
effects that reset advisor engagements (PRD 2.10, 3.8, 3.9).

No cascade is ever partially applied: every guard of PRD 2.9 is evaluated by
the calling route before any of these functions is entered.
"""

import calc
from db import S, new_row, touch
from util import add_days

CLOSED_STATES = ("CLOSED", "DISMISSED")


def create_notice(case_id, kind, response_window_days=None):
    """Create a notification and run its own side effect.

    A REHEARING_NOTICE returns every APPROVED advisor engagement of the case to
    REQUESTED with reconfirmation_required true (PRD 3.5).
    """
    days = calc.RESPONSE_WINDOW_DEFAULT_DAYS if response_window_days is None \
        else response_window_days
    notice = new_row(
        case_id=case_id,
        kind=kind,
        response_window_days=days,
        sent_at=S.clock,
        response_deadline_at=add_days(S.clock, days),
        acknowledged_at=None,
    )
    S.notifications[notice["id"]] = notice
    if kind == "REHEARING_NOTICE":
        for engagement in calc.engagements_of_case(case_id):
            if engagement["status"] == "APPROVED":
                engagement["status"] = "REQUESTED"
                engagement["reconfirmation_required"] = True
                touch(engagement)
    return notice


def vacate_sanctions(case_id, statuses, reason):
    """Move every sanction of the case in `statuses` to VACATED."""
    vacated = []
    for sanction in calc.sanctions_of_case(case_id):
        if sanction["status"] in statuses:
            sanction["status"] = "VACATED"
            sanction["vacated_reason"] = reason
            touch(sanction)
            vacated.append(sanction)
    return vacated


def supersede_proposed(case_id):
    """Any sanction still in PROPOSED becomes SUPERSEDED; returns its id."""
    superseded_id = None
    for sanction in calc.sanctions_of_case(case_id):
        if sanction["status"] == "PROPOSED":
            sanction["status"] = "SUPERSEDED"
            sanction["vacated_reason"] = "SUPERSEDED_BY_NEWER_PROPOSAL"
            touch(sanction)
            superseded_id = sanction["id"]
    return superseded_id


def write_grade_figures(sanction, case):
    """Snapshot the grade arithmetic onto a grade-penalty sanction."""
    if sanction["kind"] not in calc.GRADE_PENALTY_KINDS:
        return
    baseline, adjusted, delta = calc.grade_penalty_figures(
        case, sanction["kind"], sanction["grade_component_code"])
    sanction["baseline_course_grade_pct"] = baseline
    sanction["adjusted_course_grade_pct"] = adjusted
    sanction["grade_penalty_delta_pct"] = delta


def reassess_siblings(student_id, exclude_case_id, notify=True):
    """Hops four and five: re-assess every other open case of the student in
    that case's created_at ascending order, then vacate any proposal that has
    fallen outside its recomputed office band."""
    for case in calc.cases_of_student(student_id):
        if case["id"] == exclude_case_id:
            continue
        if case["adjudication_status"] in CLOSED_STATES:
            continue
        calc.apply_assessment(case)
        touch(case)
        low, high = calc.office_band(case["recommended_ladder_rank"])
        recomputed = False
        for sanction in calc.sanctions_of_case(case["id"]):
            if sanction["status"] != "PROPOSED":
                continue
            if sanction["ladder_rank"] < low or sanction["ladder_rank"] > high:
                sanction["status"] = "VACATED"
                sanction["vacated_reason"] = "LADDER_RECOMPUTE"
                touch(sanction)
                recomputed = True
        if recomputed and notify:
            create_notice(case["id"], "SANCTION_RECOMPUTE_NOTICE")


def impose_cascade(sanction, case):
    """The five hops of PRD 3.8, all of which complete before the response."""
    # Hop one -- the sanction itself.
    sanction["status"] = "IMPOSED"
    sanction["imposed_at"] = S.clock
    write_grade_figures(sanction, case)
    touch(sanction)

    # Hop two -- the case's two dimensions, one version bump.
    case["adjudication_status"] = "SANCTION_IMPOSED"
    if sanction["ladder_rank"] >= calc.NOTATION_MIN_RANK:
        case["notation_status"] = "PENDING_POSTING"
    touch(case)

    # Hop three -- the student's roll-up is derived from the sanction ledger,
    # so imposing the sanction has already moved prior_upheld_count,
    # active_sanction_points and standing.

    # Hops four and five -- the student's other open cases and their proposals.
    reassess_siblings(case["student_id"], case["id"], notify=True)


def recompute_department_of_case(case):
    department = calc.department_of_case(case)
    if department is None:
        return
    if calc.recompute_department_metrics(department):
        touch(department)


def recompute_department(department):
    if department is not None and calc.recompute_department_metrics(department):
        touch(department)
