"""Derived counters and the shared re-tiering / cadence helpers.

Counters are recomputed as part of the same write that changes them, never
lazily, so the conserved-pool identities always hold in the response that
caused the change.
"""

from core import calc
from core.store import store, add_days
from core.shape import iso_date

OCCASION_OFFSETS = [
    ("ONE_MONTH", 30),
    ("THREE_MONTH", 90),
    ("SIX_MONTH", 180),
    ("FIRST_ANNIVERSARY", 365),
]
ACK_WINDOW_DAYS = 21
HOLD_HOURS = 72


# --------------------------------------------------------------- seat pool
def cohort_enrollments(cohort_id):
    return store.find("Enrollment", cohort_id=cohort_id)


def recompute_seats(cohort):
    """seats_held / seats_filled / seats_open from the enrollment statuses."""
    held = 0
    filled = 0
    for enr in cohort_enrollments(cohort["id"]):
        if enr["status"] == "HELD":
            held += 1
        elif enr["status"] in ("CONFIRMED", "ATTENDING"):
            filled += 1
    cohort["seats_held"] = held
    cohort["seats_filled"] = filled
    cohort["seats_open"] = cohort["seats_total"] - held - filled


# -------------------------------------------------------------- money pool
def recompute_award(award):
    committed = 0
    spent = 0
    for alloc in store.find("FundingAllocation", grant_award_id=award["id"]):
        if alloc["status"] == "COMMITTED":
            committed += alloc["provisional_cents"] or 0
        elif alloc["status"] == "SETTLED":
            spent += alloc["settled_cents"] or 0
    award["committed_cents"] = committed
    award["spent_cents"] = spent
    award["available_cents"] = award["awarded_cents"] - committed - spent


# ------------------------------------------------------------- counsellors
def recompute_counselor(counselor):
    caseload = 0
    minutes = 0
    for ref in store.find("CounselingReferral", counselor_id=counselor["id"]):
        if ref["status"] == "ASSIGNED":
            caseload += 1
            minutes += ref["requested_minutes_per_week"]
    counselor["active_caseload"] = caseload
    counselor["committed_minutes"] = minutes


# -------------------------------------------------------------- volunteers
def recompute_volunteer(volunteer):
    count = 0
    for match in store.find("CompanionMatch", companion_id=volunteer["id"]):
        if match["status"] == "ACTIVE":
            count += 1
    volunteer["active_match_count"] = count


def recompute_has_active_companion(participant):
    active = False
    for match in store.find("CompanionMatch", participant_id=participant["id"]):
        if match["status"] == "ACTIVE":
            active = True
            break
    participant["has_active_companion"] = active


# ------------------------------------------------------------ re-tiering
def rechannel_outreaches(participant):
    """A HIGH tier re-channels SCHEDULED / DUE touchpoints to PHONE."""
    for row in store.find("AnniversaryOutreach", participant_id=participant["id"]):
        if row["status"] in ("SCHEDULED", "DUE"):
            row["channel"] = "PHONE"
            row["escalated"] = True
            store.touch(row)


def apply_tier(participant, tier):
    participant["risk_tier"] = tier
    participant["outreach_cadence_days"] = calc.cadence_days(tier)
    if tier == "HIGH":
        rechannel_outreaches(participant)


# ------------------------------------------------------------ cadence plan
def create_cadence_plan(participant):
    from datetime import datetime
    dod = datetime.strptime(participant["date_of_death"], "%Y-%m-%d").date()
    channel = "PHONE" if participant["risk_tier"] == "HIGH" else "EMAIL"
    rows = []
    for occasion, offset in OCCASION_OFFSETS:
        rows.append(store.create("AnniversaryOutreach", {
            "participant_id": participant["id"],
            "occasion": occasion,
            "due_on": iso_date(add_days(dod, offset)),
            "status": "SCHEDULED",
            "channel": channel,
            "escalated": False,
            "sent_at": None,
            "acknowledged_at": None,
        }))
    return rows


def occasion_rank(row):
    for index, (occasion, _) in enumerate(OCCASION_OFFSETS):
        if row["occasion"] == occasion:
            return index
    return len(OCCASION_OFFSETS)


# ------------------------------------------------------------ queue priority
def wait_days(referral):
    from core.store import parse_ts
    waitlisted = parse_ts(referral.get("waitlisted_at"))
    if waitlisted is None:
        return 0
    delta = store.now() - waitlisted
    days = int(delta.total_seconds() // 86400)
    return max(0, days)


def recompute_queue_priority(referral):
    participant = store.get("Participant", referral["participant_id"])
    composite = participant["composite_need_index"] if participant else 0
    reentry = participant["waitlist_reentry_count"] if participant else 0
    referral["queue_priority"] = calc.queue_priority(
        referral["urgency"], composite, wait_days(referral), reentry)
