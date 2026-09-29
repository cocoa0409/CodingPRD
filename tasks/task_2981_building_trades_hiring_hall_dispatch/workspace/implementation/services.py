"""Shared side effects: the append-only dispatch record, the withdrawal
cascade, job-request status derivation and the three-strike cascade."""

from core import (
    REFUSALS_BEFORE_REMOVAL, REREGISTRATION_COOLDOWN_DAYS, RETENTION_DAYS,
    db, days, iso, new_id, now, touch,
)
import domain


# --------------------------------------------------------------------------
# §2.10 the append-only dispatch record
# --------------------------------------------------------------------------
def append_ledger(event_code, member_id, referral_id=None, snapshot=None,
                  hours_delta=0, recorded_at=None, retention_from=None):
    recorded = recorded_at if recorded_at is not None else now()
    base = retention_from if retention_from is not None else recorded
    entry = {
        "id": new_id(),
        "event_code": event_code,
        "referral_id": referral_id,
        "member_id": member_id,
        "recorded_at": recorded,
        "retention_until": base + days(RETENTION_DAYS),
        "purge_state": "RETAINED",
        "snapshot_json": snapshot,
        "hours_delta": hours_delta,
        "created_at": now(),
        "_seq": db.seq(),
    }
    db.ledger[entry["id"]] = entry
    return entry


# --------------------------------------------------------------------------
# JobRequest status derivation (§3.5)
# --------------------------------------------------------------------------
def total_requested(job_request):
    return job_request["journeyworkers_requested"] + job_request["apprentices_requested"]


def accepted_total(job_request):
    return (domain.accepted_journeyworker_count(job_request)
            + domain.accepted_apprentice_count(job_request))


def rederive_job_request_status(job_request):
    """status is derived from accepted referrals only; SUSPENDED, CLOSED and
    CANCELLED are never re-derived here."""
    if job_request["status"] not in ("OPEN", "PARTIALLY_FILLED"):
        return
    accepted = accepted_total(job_request)
    requested = total_requested(job_request)
    if accepted >= requested:
        job_request["status"] = "FILLED"
    elif accepted > 0:
        job_request["status"] = "PARTIALLY_FILLED"
    else:
        job_request["status"] = "OPEN"


def maybe_close_job_request(job_request):
    """Compound bubble-up: FILLED -> CLOSED once every dispatch on the request
    has left WORKING."""
    if job_request["status"] != "FILLED":
        return
    dispatches = [d for d in db.dispatches.values()
                  if d["job_request_id"] == job_request["id"]]
    if not dispatches:
        return
    if any(d["status"] == "WORKING" for d in dispatches):
        return
    job_request["status"] = "CLOSED"
    touch(job_request)


# --------------------------------------------------------------------------
# Withdrawal (§3.7) — also the contractor-delinquency, member-delinquency and
# job-request-cancel cascades.
# --------------------------------------------------------------------------
def withdraw_referral(referral, reason=None, bump_job_request_version=True):
    referral["status"] = "WITHDRAWN"
    touch(referral)
    registration = db.registrations.get(referral["registration_id"])
    if registration is not None and registration["status"] == "REFERRED":
        # registered_at, credited_seniority_hours, demotion_count and
        # priority_flag all stay untouched: the registration reoccupies its
        # pre-referral ordinal and no strike is charged.
        registration["status"] = "REGISTERED"
        touch(registration)
    job_request = db.job_requests.get(referral["job_request_id"])
    if job_request is not None and bump_job_request_version:
        touch(job_request)
    snapshot = {"reason": reason, "referral_kind": referral["referral_kind"]}
    append_ledger("REFERRAL_WITHDRAWN", referral["member_id"], referral["id"],
                  snapshot=snapshot)
    append_ledger("POSITION_RESTORED", referral["member_id"], referral["id"],
                  snapshot={"registration_id": referral["registration_id"]})


def withdraw_issued_referrals_of_job_request(job_request, reason=None,
                                             bump_job_request_version=True):
    outstanding = [r for r in db.referrals.values()
                   if r["job_request_id"] == job_request["id"] and r["status"] == "ISSUED"]
    outstanding.sort(key=lambda r: (r["acceptance_deadline"], r["created_at"], r["_seq"]))
    for referral in outstanding:
        withdraw_referral(referral, reason=reason,
                          bump_job_request_version=bump_job_request_version)
    return outstanding


# --------------------------------------------------------------------------
# Removal / renumbering (§3.4)
# --------------------------------------------------------------------------
def remove_registration(registration, removal_reason, terminal_status="REMOVED"):
    registration["status"] = terminal_status
    registration["removal_reason"] = removal_reason
    touch(registration)


# --------------------------------------------------------------------------
# The three-strike cascade shared by refusal and sweep expiry (§3.7)
# --------------------------------------------------------------------------
def apply_no_cause_consequence(referral, registration, expired_event=False):
    """Charge a bare turn-down (or an unanswered referral). Returns
    'REMOVED' or 'DEMOTED'.

    The caller must already have written the terminal referral status so that
    effective_refusal_strikes counts this answer.
    """
    member = db.members.get(referral["member_id"])
    strikes = domain.refusal_strike_count(referral["member_id"])
    recorded_at = now()
    first_event = "REFERRAL_EXPIRED" if expired_event else "REFERRAL_REFUSED"
    append_ledger(first_event, referral["member_id"], referral["id"],
                  snapshot={"good_cause": False, "strike_count": strikes},
                  recorded_at=recorded_at)
    if registration is None:
        return "DEMOTED"
    if strikes >= REFUSALS_BEFORE_REMOVAL:
        registration["demotion_count"] = registration["demotion_count"] + 1
        registration["status"] = "REMOVED"
        registration["removal_reason"] = "THREE_REFUSALS"
        touch(registration)
        if member is not None:
            member["re_registration_eligible_at"] = (
                recorded_at + days(REREGISTRATION_COOLDOWN_DAYS))
            touch(member)
        append_ledger("REGISTRATION_REMOVED", referral["member_id"], referral["id"],
                      snapshot={"removal_reason": "THREE_REFUSALS",
                                "registration_id": registration["id"]},
                      recorded_at=recorded_at)
        return "REMOVED"
    registration["demotion_count"] = registration["demotion_count"] + 1
    registration["status"] = "REGISTERED"
    touch(registration)
    return "DEMOTED"


def dispatch_order_payload(job_request, pool):
    top = pool[0]
    group = db.lists.get(top["list_id"])
    return {
        "variant": domain.variant_for(job_request),
        "candidate_count": len(pool),
        "top_registration_id": top["id"],
        "top_member_id": top["member_id"],
        "top_list_group_code": group["group_code"] if group else None,
        "top_position_number": domain.position_number(top),
        "top_credited_seniority_hours": top["credited_seniority_hours"],
    }


def sort_default(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def iso_or_none(value):
    return iso(value)
