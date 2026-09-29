"""Computed fields, the dispatch-order ranking, the apprentice ratio cap and
the effective-refusal-strike arithmetic (§1.3 / PRD §3.2, §3.6, §3.7)."""

from core import (
    APPRENTICE_RATE_FACTOR_BP, JOURNEYWORKER_RATE_FACTOR_BP,
    NAMED_CALL_DIVISOR, NAMED_CALL_HARD_CAP, REFUSAL_WINDOW_DAYS,
    SHORT_CALL_MAX_DAYS, SPECIAL_SKILL_SHARE_BP, BASIS_POINT_SCALE,
    db, days, now,
)


# --------------------------------------------------------------------------
# Member computed attributes (§3.1)
# --------------------------------------------------------------------------
def member_is_traveler(member):
    home = db.locals.get(member["home_local_id"])
    return bool(home is not None and home["kind"] == "SISTER")


def member_dispatch_eligible(member):
    if member["standing"] != "GOOD_STANDING":
        return False
    eligible_at = member["re_registration_eligible_at"]
    return eligible_at is None or now() >= eligible_at


def refusal_strike_count(member_id):
    """effective_refusal_strikes: rolling 365-day window, closed at the left edge,
    LONG_CALL referrals only, no-cause refusals plus expiries, across every
    registration of the member."""
    clock = now()
    floor = clock - days(REFUSAL_WINDOW_DAYS)
    count = 0
    for ref in db.referrals.values():
        if ref["member_id"] != member_id:
            continue
        if ref["status"] == "REFUSED":
            if ref["refusal_good_cause_code"] is not None:
                continue
        elif ref["status"] != "EXPIRED":
            continue
        job = db.job_requests.get(ref["job_request_id"])
        if job is None or job["duration_type"] != "LONG_CALL":
            continue
        if ref["issued_at"] < floor:
            continue
        count += 1
    return count


# --------------------------------------------------------------------------
# List / registration computed attributes (§3.2, §3.3)
# --------------------------------------------------------------------------
def registered_registrations(list_id):
    return [r for r in db.registrations.values()
            if r["list_id"] == list_id and r["status"] == "REGISTERED"]


def registered_count(list_id):
    return len(registered_registrations(list_id))


def _ordering_component(reg):
    """The list group's own ordering_policy key, expressed as a float so the
    component stays sortable when candidates come from differently-policied
    groups that share a priority_rank."""
    group = db.lists.get(reg["list_id"])
    if group is not None and group["ordering_policy"] == "SENIORITY":
        return float(-reg["credited_seniority_hours"])
    return reg["registered_at"].timestamp()


def strict_group_order_key(reg):
    group = db.lists.get(reg["list_id"])
    rank = group["priority_rank"] if group is not None else 0
    return (
        rank,
        0 if reg["priority_flag"] else 1,
        reg["demotion_count"],
        _ordering_component(reg),
        reg["registered_at"],
        reg["created_at"],
        reg["_seq"],
    )


def intra_list_key(reg):
    """The strict-group-order key restricted to one list (priority_rank constant)."""
    return strict_group_order_key(reg)


def short_call_interfiled_key(reg):
    return (
        0 if reg["priority_flag"] else 1,
        reg["demotion_count"],
        reg["registered_at"],
        reg["created_at"],
        reg["_seq"],
    )


def position_number(reg):
    """1-based rank inside the registration's own list among REGISTERED rows,
    under the strict-group-order intra-list key. Null in any other status."""
    if reg["status"] != "REGISTERED":
        return None
    peers = sorted(registered_registrations(reg["list_id"]), key=intra_list_key)
    for index, peer in enumerate(peers):
        if peer["id"] == reg["id"]:
            return index + 1
    return None


# --------------------------------------------------------------------------
# dispatch_order_ranking (§3.2)
# --------------------------------------------------------------------------
def variant_for(job_request):
    if job_request["duration_type"] == "LONG_CALL":
        return "STRICT_GROUP_ORDER"
    return "SHORT_CALL_INTERFILED"


def has_outstanding_referral_for_registration(registration_id):
    clock = now()
    for ref in db.referrals.values():
        if (ref["registration_id"] == registration_id
                and ref["status"] == "ISSUED"
                and ref["acceptance_deadline"] >= clock):
            return True
    return False


def member_has_outstanding_referral(member_id):
    """§3.6 — no referral of any of that member's registrations may be ISSUED
    with an acceptance_deadline at or after the clock."""
    clock = now()
    for ref in db.referrals.values():
        if (ref["member_id"] == member_id
                and ref["status"] == "ISSUED"
                and ref["acceptance_deadline"] >= clock):
            return True
    return False


def member_has_working_dispatch(member_id):
    for dispatch in db.dispatches.values():
        if dispatch["member_id"] == member_id and dispatch["status"] == "WORKING":
            return True
    return False


def has_valid_endorsement(member_id, skill_code):
    if skill_code is None:
        return False
    clock = now()
    for endorsement in db.endorsements.values():
        if (endorsement["member_id"] == member_id
                and endorsement["skill_code"] == skill_code
                and endorsement["verified"] is True
                and endorsement["certified_until"] > clock):
            return True
    return False


def candidate_pool(job_request, slot_kind, referral_kind):
    """The ranked candidate pool: the eligibility filter, then the
    variant-dependent sort key."""
    clock = now()
    wanted_classification = "JOURNEYWORKER" if slot_kind == "JOURNEYWORKER" else "APPRENTICE"
    pool = []
    for reg in db.registrations.values():
        if reg["status"] != "REGISTERED":
            continue
        member = db.members.get(reg["member_id"])
        if member is None:
            continue
        if member["classification"] != wanted_classification:
            continue
        if member["standing"] != "GOOD_STANDING":
            continue
        eligible_at = member["re_registration_eligible_at"]
        if eligible_at is not None and clock < eligible_at:
            continue
        if has_outstanding_referral_for_registration(reg["id"]):
            continue
        if member_has_working_dispatch(reg["member_id"]):
            continue
        if referral_kind == "SPECIAL_SKILL":
            if not has_valid_endorsement(reg["member_id"], job_request["required_skill_code"]):
                continue
        pool.append(reg)
    if job_request["duration_type"] == "LONG_CALL":
        pool.sort(key=strict_group_order_key)
    else:
        pool.sort(key=short_call_interfiled_key)
    return pool


def candidate_snapshot(pool):
    rows = []
    for index, reg in enumerate(pool):
        group = db.lists.get(reg["list_id"])
        rows.append({
            "rank": index + 1,
            "registration_id": reg["id"],
            "member_id": reg["member_id"],
            "list_id": reg["list_id"],
            "list_group_code": group["group_code"] if group else None,
            "list_priority_rank": group["priority_rank"] if group else None,
            "priority_flag": reg["priority_flag"],
            "demotion_count": reg["demotion_count"],
            "credited_seniority_hours": reg["credited_seniority_hours"],
            "position_number": position_number(reg),
        })
    return rows


# --------------------------------------------------------------------------
# JobRequest computed counters (§3.5)
# --------------------------------------------------------------------------
def referrals_of(job_request_id):
    return [r for r in db.referrals.values() if r["job_request_id"] == job_request_id]


def count_referrals(job_request_id, slot_kind, statuses):
    total = 0
    for ref in db.referrals.values():
        if (ref["job_request_id"] == job_request_id
                and ref["slot_kind"] == slot_kind
                and ref["status"] in statuses):
            total += 1
    return total


def open_journeyworker_slots(job_request):
    return job_request["journeyworkers_requested"] - count_referrals(
        job_request["id"], "JOURNEYWORKER", ("ISSUED", "ACCEPTED"))


def open_apprentice_slots(job_request):
    return job_request["apprentices_requested"] - count_referrals(
        job_request["id"], "APPRENTICE", ("ISSUED", "ACCEPTED"))


def accepted_journeyworker_count(job_request):
    return count_referrals(job_request["id"], "JOURNEYWORKER", ("ACCEPTED",))


def accepted_apprentice_count(job_request):
    return count_referrals(job_request["id"], "APPRENTICE", ("ACCEPTED",))


def open_slots_for(job_request, slot_kind):
    if slot_kind == "JOURNEYWORKER":
        return open_journeyworker_slots(job_request)
    return open_apprentice_slots(job_request)


def duration_type_for(expected_duration_days):
    return "SHORT_CALL" if expected_duration_days <= SHORT_CALL_MAX_DAYS else "LONG_CALL"


def compute_allowances(journeyworkers, apprentices, duration_type, required_skill_code):
    total_requested = journeyworkers + apprentices
    if duration_type == "SHORT_CALL":
        named_call_allowance = 0
    else:
        named_call_allowance = min(
            NAMED_CALL_HARD_CAP,
            max(1, total_requested // NAMED_CALL_DIVISOR),
        )
    if required_skill_code is None:
        special_skill_allowance = 0
    else:
        half = (journeyworkers * SPECIAL_SKILL_SHARE_BP) // BASIS_POINT_SCALE
        special_skill_allowance = min(journeyworkers, half + (journeyworkers % 2))
    return named_call_allowance, special_skill_allowance


# --------------------------------------------------------------------------
# apprentice_ratio_cap (§3.6)
# --------------------------------------------------------------------------
def governing_ratio_policy():
    """Step one: the ACTIVE policy with effective_from <= clock, ranked
    effective_from DESC with created_at ASC as the tie-break."""
    clock = now()
    eligible = [p for p in db.ratio_policies.values()
                if p["status"] == "ACTIVE" and p["effective_from"] <= clock]
    if not eligible:
        return None
    eligible.sort(key=lambda p: (-p["effective_from"].timestamp(), p["created_at"], p["_seq"]))
    return eligible[0]


def apprentice_cap(job_request, policy=None):
    """Step two: the cap, from ACCEPTED journeyworker referrals only."""
    jw_accepted = accepted_journeyworker_count(job_request)
    if jw_accepted == 0:
        return 0
    if policy is None:
        policy = governing_ratio_policy()
    if policy is None:
        return 0
    surplus = max(0, jw_accepted - policy["first_apprentice_at_jw_count"])
    return 1 + surplus // policy["then_every_n_jw"]


def max_apprentices_allowed(job_request):
    return apprentice_cap(job_request)


# --------------------------------------------------------------------------
# back_pay_make_whole factor (§3.9)
# --------------------------------------------------------------------------
def classification_factor_bp(member):
    if member is None:
        return JOURNEYWORKER_RATE_FACTOR_BP
    if member["classification"] == "JOURNEYWORKER":
        return JOURNEYWORKER_RATE_FACTOR_BP
    period = member.get("apprentice_period")
    return APPRENTICE_RATE_FACTOR_BP.get(period, JOURNEYWORKER_RATE_FACTOR_BP)
