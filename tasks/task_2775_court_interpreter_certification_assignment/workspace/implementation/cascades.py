"""Multi-row cascades (PRD 2.11).

Every cancellation in the program — explicit, continuance-driven, suspension-
driven, lapse-driven or equipment-driven — runs through `cancel_assignment`, so
the lead-time branch that decides between voiding and compensating a claim is
written exactly once.
"""
import derive
import pay
from store import db, new_row, now, sort_created, touch
from util import fmt_dt, parse_dt


def new_sweep_log():
    return {
        "lapsed_credential_ids": [],
        "downgraded_interpreter_ids": [],
        "expired_action_ids": [],
        "reinstated_interpreter_ids": [],
        "unmet_hearing_ids": [],
        "cancelled_assignment_ids": [],
        "voided_pay_claim_ids": [],
    }


def _record(log, key, row_id):
    if log is not None and row_id not in log[key]:
        log[key].append(row_id)


# --------------------------------------------------------------------------
# pay claims
# --------------------------------------------------------------------------
def create_claim(assignment, schedule):
    """The ENCUMBERED provisional claim created when an assignment is accepted."""
    figures = pay.compute(assignment, "PROVISIONAL", schedule)
    claim = new_row()
    claim.update(
        {
            "assignment_id": assignment["id"],
            "rate_schedule_id": schedule["id"],
            "variant": "PROVISIONAL",
            "status": "ENCUMBERED",
            "billable_hours": figures["billable_hours"],
            "service_cents": figures["service_cents"],
            "rare_premium_cents": figures["rare_premium_cents"],
            "travel_cents": figures["travel_cents"],
            "provisional_total_cents": figures["total_cents"],
            "final_total_cents": None,
            "late_cancellation": False,
            "payment_reference": None,
        }
    )
    db.pay_claims[claim["id"]] = claim
    return claim


def finalize_claim(claim, variant, schedule):
    """ENCUMBERED -> FINALIZED on the FINAL or LATE_CANCELLATION variant."""
    assignment = db.assignments[claim["assignment_id"]]
    figures = pay.compute(assignment, variant, schedule)
    claim["variant"] = "FINAL"
    claim["billable_hours"] = figures["billable_hours"]
    claim["service_cents"] = figures["service_cents"]
    claim["rare_premium_cents"] = figures["rare_premium_cents"]
    claim["travel_cents"] = figures["travel_cents"]
    claim["final_total_cents"] = figures["total_cents"]
    claim["status"] = "FINALIZED"
    if variant == "LATE_CANCELLATION":
        claim["late_cancellation"] = True
    touch(claim)
    return claim


def void_claim(claim, log=None):
    claim["status"] = "VOIDED"
    touch(claim)
    _record(log, "voided_pay_claim_ids", claim["id"])
    return claim


# --------------------------------------------------------------------------
# the one cancellation path
# --------------------------------------------------------------------------
def lead_time_hours(hearing):
    return (parse_dt(hearing["scheduled_start"]) - now()).total_seconds() / 3600.0


def cancel_assignment(assignment, reason_code, log=None):
    """Cancel one assignment and run its pay, ledger and hearing consequences."""
    hearing = db.hearings[assignment["hearing_id"]]
    courthouse = db.courthouses[hearing["courthouse_id"]]
    previous = assignment["service_status"]

    assignment["service_status"] = "CANCELLED"
    assignment["cancel_reason_code"] = reason_code
    touch(assignment)
    _record(log, "cancelled_assignment_ids", assignment["id"])

    claim = derive.claim_for_assignment(assignment["id"])
    schedule = None
    if claim is not None:
        schedule = db.rate_schedules.get(claim["rate_schedule_id"])
    if schedule is None:
        schedule = derive.schedule_for_hearing(hearing)
    late = (
        schedule is not None
        and lead_time_hours(hearing) < schedule["late_cancellation_hours"]
    )

    if claim is not None and claim["status"] == "ENCUMBERED":
        if late:
            finalize_claim(claim, "LATE_CANCELLATION", schedule)
            if assignment["interpreter_id"]:
                touch(db.interpreters[assignment["interpreter_id"]])
        else:
            void_claim(claim, log)
        touch(courthouse)

    if previous == "CONFIRMED" and hearing["status"] == "COVERED":
        hearing["status"] = "UNMET" if late else "SCHEDULED"
        touch(hearing)
    return late


def cancel_live_assignments(assignments, reason_code, log=None):
    for assignment in sort_created(assignments):
        if assignment["service_status"] in derive.CANCELLABLE_SERVICE_STATUSES:
            cancel_assignment(assignment, reason_code, log)


# --------------------------------------------------------------------------
# credential-to-roster propagation
# --------------------------------------------------------------------------
def demote_if_no_active_credential(interpreter, reason_code, log=None):
    """ACTIVE -> INACTIVE once the holder's last activated credential is gone."""
    if interpreter["roster_status"] != "ACTIVE":
        return False
    if derive.active_credentials_of(interpreter["id"]):
        return False
    interpreter["roster_status"] = "INACTIVE"
    _record(log, "downgraded_interpreter_ids", interpreter["id"])
    cancel_live_assignments(
        derive.assignments_of_interpreter(interpreter["id"]), reason_code, log
    )
    return True


def lapse_credential(credential, log=None):
    """ACTIVE -> LAPSED, with the four-hop cascade the clock triggers."""
    interpreter = db.interpreters[credential["interpreter_id"]]
    language = db.languages[credential["language_id"]]
    credential["status"] = "LAPSED"
    credential["tier"] = None
    touch(credential)
    _record(log, "lapsed_credential_ids", credential["id"])
    touch(language)
    touch(interpreter)
    demote_if_no_active_credential(interpreter, "CREDENTIAL_LAPSED", log)


def revoke_credential(credential, log=None):
    """The widest cascade in the credentialing area (PRD 3.4)."""
    interpreter = db.interpreters[credential["interpreter_id"]]
    language = db.languages[credential["language_id"]]
    was_active = credential["status"] == "ACTIVE"
    credential["status"] = "REVOKED"
    credential["tier"] = None
    touch(credential)

    pinned = [
        a
        for a in db.assignments.values()
        if a["credential_id"] == credential["id"]
        and a["service_status"] in derive.CANCELLABLE_SERVICE_STATUSES
    ]
    cancel_live_assignments(pinned, "CREDENTIAL_REVOKED", log)

    if was_active:
        touch(language)
        touch(interpreter)
        demote_if_no_active_credential(interpreter, "CREDENTIAL_REVOKED", log)


# --------------------------------------------------------------------------
# discipline
# --------------------------------------------------------------------------
def create_disciplinary_action(complaint, action_type, suspension_days):
    from util import add_days, fmt_date

    effective_from = now().date()
    if action_type == "SUSPENSION":
        effective_through = add_days(effective_from, suspension_days)
    elif action_type == "REVOCATION":
        effective_through = None
    else:
        effective_through = add_days(effective_from, derive.SANCTION_DAYS[action_type])
    action = new_row()
    action.update(
        {
            "complaint_id": complaint["id"],
            "interpreter_id": complaint["interpreter_id"],
            "action_type": action_type,
            "points": derive.SANCTION_POINTS[action_type],
            "effective_from": fmt_date(effective_from),
            "effective_through": fmt_date(effective_through),
            "status": "IN_EFFECT",
        }
    )
    db.disciplinary_actions[action["id"]] = action
    return action


def apply_sanction(action, log=None):
    """Hops two and three of a substantiation."""
    interpreter = db.interpreters[action["interpreter_id"]]
    if action["action_type"] == "SUSPENSION":
        interpreter["suspension_through"] = action["effective_through"]
        if interpreter["roster_status"] == "ACTIVE":
            interpreter["roster_status"] = "SUSPENDED"
        touch(interpreter)
        through = parse_dt(action["effective_through"] + "T23:59:59.999Z")
        targets = []
        for assignment in derive.assignments_of_interpreter(interpreter["id"]):
            if assignment["service_status"] not in derive.CANCELLABLE_SERVICE_STATUSES:
                continue
            hearing = db.hearings[assignment["hearing_id"]]
            if parse_dt(hearing["scheduled_start"]) <= through:
                targets.append(assignment)
        cancel_live_assignments(targets, "INTERPRETER_SUSPENDED", log)
    elif action["action_type"] == "REVOCATION":
        interpreter["roster_status"] = "REVOKED"
        interpreter["suspension_through"] = None
        touch(interpreter)
        cancel_live_assignments(
            derive.assignments_of_interpreter(interpreter["id"]),
            "INTERPRETER_SUSPENDED",
            log,
        )
        for credential in derive.credentials_of(interpreter["id"]):
            if credential["status"] in derive.LIVE_CREDENTIAL_STATUSES:
                revoke_credential(credential, log)
    else:
        touch(interpreter)


def rescind_action(action):
    """The appeal-driven leg: IN_EFFECT -> RESCINDED, points dropping out."""
    interpreter = db.interpreters[action["interpreter_id"]]
    action["status"] = "RESCINDED"
    touch(action)
    if interpreter["roster_status"] == "SUSPENDED":
        remaining = [
            a
            for a in db.disciplinary_actions.values()
            if a["interpreter_id"] == interpreter["id"]
            and a["action_type"] == "SUSPENSION"
            and a["status"] == "IN_EFFECT"
        ]
        if not remaining:
            interpreter["suspension_through"] = None
            interpreter["roster_status"] = "ACTIVE"
    touch(interpreter)
