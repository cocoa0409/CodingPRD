"""Cascade discipline and server-initiated transitions (PRD 2.8).

"The server performs these cascades itself, in a fixed order, within the same
request, and each touched record independently refreshes its updated_at and
increments its version."
"""

import calc
import store


# --------------------------------------------------------------- program state
def refresh_program(program):
    """Recount the four counters, recompute utilization and posture, and bump the
    program's version when any derived field actually moved (PRD 2.6 / 2.8)."""
    if program is None:
        return False
    occupied, waitlisted, overdue, utilization_bp = calc.program_counters(program)
    posture = calc.posture_for(
        occupied, overdue, utilization_bp, program["licensed_bed_capacity"]
    )
    changed = (
        program["occupied_beds"] != occupied
        or program["waitlisted_count"] != waitlisted
        or program["overdue_notification_count"] != overdue
        or program["utilization_bp"] != utilization_bp
        or program["posture"] != posture
    )
    program["occupied_beds"] = occupied
    program["waitlisted_count"] = waitlisted
    program["overdue_notification_count"] = overdue
    program["utilization_bp"] = utilization_bp
    program["posture"] = posture
    if changed:
        store.touch(program)
    return changed


def refresh_program_of(admission):
    return refresh_program(store.programs.get(admission["program_id"]))


# ----------------------------------------------------------------- youth state
def apply_youth_derived(youth):
    """Recompute the youth's derived gates in place. Returns True when something
    moved; the caller decides whether that is its own version bump or part of a
    larger single-bump mutation."""
    risk_posture = calc.risk_posture_for(youth)
    eligible = calc.vote_eligible(youth)
    changed = youth["risk_posture"] != risk_posture or youth["governance_vote_eligible"] != eligible
    youth["risk_posture"] = risk_posture
    youth["governance_vote_eligible"] = eligible
    return changed


def refresh_youth(youth):
    """Recompute the youth's derived gates and bump the version only when a derived
    field actually changed."""
    if youth is None:
        return False
    if apply_youth_derived(youth):
        store.touch(youth)
        return True
    return False


def refresh_youth_of(admission):
    return refresh_youth(store.youths.get(admission["youth_id"]))


def apply_trafficking_history(youth):
    """Re-decay the youth's standing trafficking figure against the clock."""
    score = calc.outreach_history_score(youth["id"])
    tier = calc.tier_for(score)
    changed = youth["trafficking_risk_score"] != score or youth["trafficking_risk_tier"] != tier
    youth["trafficking_risk_score"] = score
    youth["trafficking_risk_tier"] = tier
    return changed


# --------------------------------------------------- guardian notification rows
def create_notification(admission):
    """PRD 3.4: the server itself creates the obligation whenever an admission
    reaches its active stay; no client can create one directly."""
    notification = {
        "admission_id": admission["id"],
        "status": "PENDING",
        "due_at": admission["admitted_at"] + store.hours(calc.NOTIFICATION_DUE_HOURS),
        "attempt_count": 0,
        "last_attempt_at": None,
        "attempt_channel": None,
        "waiver_reason": None,
        "runaway_report_filed_at": None,
        "resolved_at": None,
        "resolving_user_id": None,
    }
    store.stamp_new(notification)
    store.guardian_notifications[notification["id"]] = notification
    return notification


def admission_notifications(admission_id):
    return store.ordered(
        [
            n
            for n in store.guardian_notifications.values()
            if n["admission_id"] == admission_id
        ]
    )


# ------------------------------------------------------------ admission active
def activate_admission(admission, at_instant):
    """The shared five-record cascade of PRD 3.3: stamp admitted_at, project the
    billable nights, consume a bed, create the parental-notification obligation and
    move the youth to SHELTERED.

    The admission row itself is left for the caller to touch (a brand-new ACTIVE
    admission stays at version 1, while an activation of an existing row is a
    mutation of that row).
    """
    admission["admitted_at"] = at_instant
    admission["status"] = "ACTIVE"
    admission["capacity_blocked"] = False
    admission["projected_billable_nights"] = calc.projected_billable_nights(
        at_instant, admission["planned_discharge_at"]
    )
    create_notification(admission)
    refresh_program_of(admission)
    youth = store.youths.get(admission["youth_id"])
    if youth is not None:
        if youth["status"] in ("PROSPECT", "ENGAGED"):
            youth["status"] = "SHELTERED"
        apply_youth_derived(youth)
        # PRD 3.3: "the youth's status becomes SHELTERED with the youth's version
        # incremented by one" - exactly one bump for the whole activation.
        store.touch(youth)
    return admission


# ------------------------------------------------------------ waitlist selector
def promote_one(program):
    """The pinned waitlist policy of PRD 3.3.

    Candidates are every WAITLISTED admission of the program, ranked by
    priority_score descending with the earlier created_at breaking a tie. Exactly one
    candidate is promoted per freeing event; an empty candidate set is a no-op.
    """
    if program is None or program["posture"] == "FROZEN":
        return None
    candidates = [
        a
        for a in store.admissions.values()
        if a["program_id"] == program["id"] and a["status"] == "WAITLISTED"
    ]
    if not candidates:
        return None
    candidates = store.ordered(candidates)
    winner = sorted(candidates, key=lambda a: -a["priority_score"])[0]
    youth = store.youths.get(winner["youth_id"])
    if youth is None:
        return None
    # "a youth who aged out while waiting is not promoted"
    age = calc.age_years(youth)
    if age < program["min_age_years"] or age > program["max_age_years"]:
        return None
    activate_admission(winner, store.now())
    store.touch(winner)
    return winner


# ---------------------------------------------------------- discharge cascade
POSITIVE_DESTINATIONS = ("FAMILY_REUNIFIED", "TRANSITIONAL_LIVING", "INDEPENDENT_HOUSING")


def discharge_admission(admission, exit_destination):
    """The five-hop discharge cascade of PRD 3.5; every hop must fire."""
    clock = store.now()
    admission["discharged_at"] = clock
    admission["exit_destination"] = exit_destination
    admission["final_billable_nights"] = calc.final_billable_nights(
        admission["admitted_at"], clock
    )
    admission["outcome_positive"] = exit_destination in POSITIVE_DESTINATIONS
    admission["status"] = "DISCHARGED"
    store.touch(admission)

    youth = store.youths.get(admission["youth_id"])
    if youth is not None:
        youth["cumulative_shelter_nights"] += admission["final_billable_nights"]
        if youth["status"] == "REUNIFIED_PENDING" and exit_destination == "FAMILY_REUNIFIED":
            youth["status"] = "REUNIFIED"
        else:
            youth["status"] = "EXITED"
        apply_youth_derived(youth)
        store.touch(youth)

    program = store.programs.get(admission["program_id"])
    refresh_program(program)
    promoted = promote_one(program)
    return promoted


# ------------------------------------------------------- reunification cascades
def waive_open_notifications(admission, actor_user_id):
    """PRD 3.4: the non-client path into WAIVED, fired by an approved case."""
    clock = store.now()
    touched_program = False
    for notification in admission_notifications(admission["id"]):
        if notification["status"] not in calc.OPEN_NOTIFICATION_STATUSES:
            continue
        notification["status"] = "WAIVED"
        notification["waiver_reason"] = "COURT_ORDER"
        notification["resolved_at"] = clock
        notification["resolving_user_id"] = actor_user_id
        store.touch(notification)
        touched_program = True
    if touched_program:
        refresh_program_of(admission)
    return touched_program


def approve_case(case, youth, actor_user_id):
    """The four-hop approval cascade of PRD 3.6."""
    clock = store.now()
    case["aftercare_plan_due_at"] = clock + store.hours(calc.AFTERCARE_PLAN_HOURS)
    case["status"] = "APPROVED"
    case["decision_user_id"] = actor_user_id
    store.touch(case)

    if youth["status"] == "SHELTERED":
        youth["status"] = "REUNIFIED_PENDING"

    for admission in store.ordered(
        [a for a in store.admissions.values() if a["youth_id"] == youth["id"]]
    ):
        if admission["status"] not in ("ACTIVE", "EXTENDED"):
            continue
        admission["status"] = "DISCHARGE_SCHEDULED"
        store.touch(admission)
        waive_open_notifications(admission, actor_user_id)
        # The bed is still held, so occupied_beds is deliberately unchanged; only the
        # overdue counter can move here.
        refresh_program_of(admission)

    # PRD 3.6: "the youth's risk_posture is recomputed and the youth's version
    # increments by one" - one bump covering the whole approval.
    apply_youth_derived(youth)
    store.touch(youth)


def supersede_cases(youth, new_case_id=None):
    """PRD 3.6: opening a case supersedes every earlier non-terminal case of the
    youth, and a superseded APPROVED/AFTERCARE case reverts the youth and its
    scheduled discharges."""
    clock = store.now()
    reverted = False
    for case in store.ordered(
        [c for c in store.reunification_cases.values() if c["youth_id"] == youth["id"]]
    ):
        if case["id"] == new_case_id:
            continue
        if case["status"] in ("CLOSED", "SUPERSEDED"):
            continue
        was_approved = case["status"] in ("APPROVED", "AFTERCARE")
        case["status"] = "SUPERSEDED"
        case["closed_at"] = clock
        store.touch(case)
        if was_approved:
            reverted = True
    if reverted:
        if youth["status"] == "REUNIFIED_PENDING":
            youth["status"] = "SHELTERED"
        for admission in store.ordered(
            [a for a in store.admissions.values() if a["youth_id"] == youth["id"]]
        ):
            if admission["status"] != "DISCHARGE_SCHEDULED":
                continue
            # No bed accounting change; extension_count and admitted_at untouched and
            # the waived notification is NOT reopened.
            admission["status"] = "ACTIVE"
            store.touch(admission)
    return reverted


# ------------------------------------------------------- placement derivations
def apply_placement_derived(placement):
    """Recompute every derived figure of a placement (PRD 3.7 / 3.8).

    These are pure reads of other rows, so they are refreshed on every read of the
    placement without counting as a mutation of the row.
    """
    program = store.programs.get(placement["program_id"])
    elapsed = calc.days_elapsed(placement)
    placement["days_elapsed"] = elapsed
    consumed_ratio_bp, earned_bonus_days, allowance_days = calc.duration_allowance(
        placement, elapsed
    )
    placement["consumed_ratio_bp"] = consumed_ratio_bp
    placement["earned_bonus_days"] = earned_bonus_days
    placement["allowance_days"] = allowance_days
    match_awarded, balance = calc.savings_totals(placement["id"])
    placement["match_awarded_cents"] = match_awarded
    placement["savings_balance_cents"] = balance
    if program is not None:
        placement["required_savings_cents"] = calc.required_savings_cents(
            placement, program, elapsed
        )
    return placement


# ------------------------------------------------------------- census epoch
def run_census():
    """One census epoch (PRD 3.10), performing every deadline-driven transition in
    the documented order and answering with a count of the work it did."""
    clock = store.now()
    counts = {
        "overdue_marked": 0,
        "admissions_denied": 0,
        "admissions_promoted": 0,
        "placements_noticed": 0,
        "placements_exited": 0,
        "cases_closed": 0,
        "postures_recomputed": 0,
    }

    # 1. Guardian notifications in PENDING or ATTEMPTED whose due_at has passed.
    affected_programs = []
    for notification in store.ordered(list(store.guardian_notifications.values())):
        if notification["status"] not in ("PENDING", "ATTEMPTED"):
            continue
        if not notification["due_at"] < clock:
            continue
        notification["status"] = "OVERDUE"
        store.touch(notification)
        counts["overdue_marked"] += 1
        admission = store.admissions.get(notification["admission_id"])
        if admission is not None:
            affected_programs.append(admission["program_id"])
    for program_id in affected_programs:
        refresh_program(store.programs.get(program_id))

    # 2. Admissions abandoned in PENDING_SCREENING for more than 72 hours.
    for admission in store.ordered(list(store.admissions.values())):
        if admission["status"] != "PENDING_SCREENING":
            continue
        if clock - admission["requested_at"] > store.hours(calc.PENDING_SCREENING_TTL_HOURS):
            admission["status"] = "DENIED"
            store.touch(admission)
            counts["admissions_denied"] += 1

    # 3. The waitlist selector runs for every program whose posture is not FROZEN,
    #    promoting one admission per program per epoch.
    for program in store.ordered(list(store.programs.values())):
        refresh_program(program)
        if program["posture"] == "FROZEN":
            continue
        if promote_one(program) is not None:
            counts["admissions_promoted"] += 1

    # 4. Placement notice, then placement exit - two sequential passes, so one
    #    placement can be noticed and exited inside the same epoch.
    for placement in store.ordered(list(store.tlp_placements.values())):
        if placement["tenancy_status"] != "PLACED":
            continue
        apply_placement_derived(placement)
        if placement["days_elapsed"] >= placement["allowance_days"] - calc.NOTICE_LEAD_DAYS:
            placement["tenancy_status"] = "NOTICE_GIVEN"
            store.touch(placement)
            counts["placements_noticed"] += 1
    for placement in store.ordered(list(store.tlp_placements.values())):
        if placement["tenancy_status"] != "NOTICE_GIVEN":
            continue
        apply_placement_derived(placement)
        if placement["days_elapsed"] >= placement["allowance_days"]:
            placement["tenancy_status"] = "EXITED"
            placement["exit_reason"] = "DURATION_LIMIT"
            placement["exited_at"] = clock
            store.touch(placement)
            counts["placements_exited"] += 1

    # 5. Declined cases close a full week after they were last updated.
    for case in store.ordered(list(store.reunification_cases.values())):
        if case["status"] != "DECLINED":
            continue
        if clock - case["updated_at"] >= store.hours(calc.CASE_CLOSE_LAG_HOURS):
            case["status"] = "CLOSED"
            case["closed_at"] = clock
            store.touch(case)
            counts["cases_closed"] += 1

    # 6. Every youth's trafficking figure is re-decayed against the new clock, then
    #    every program posture and youth posture is recomputed.
    for youth in store.ordered(list(store.youths.values())):
        changed = apply_trafficking_history(youth)
        if apply_youth_derived(youth):
            changed = True
        if changed:
            store.touch(youth)
    for program in store.ordered(list(store.programs.values())):
        refresh_program(program)

    counts["postures_recomputed"] = len(store.programs) + len(store.youths)
    return counts
