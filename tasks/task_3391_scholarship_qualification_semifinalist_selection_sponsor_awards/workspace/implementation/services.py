"""Business logic: apportionment, selection, matching waterfall, waitlist
promotion, pool accounting, award lifecycle cascades, disbursement schedule,
renewal decisions, notification creation, clock sweep, cycle completion.

All formulas follow the SCAFFOLD calculations table and PRD section 3
verbatim: quota_raw to 4 decimals round-half-up; provisional slots are
round-half-up of the stored quota; final slots use largest-remainder
apportionment with the MIN_STATE_SLOTS=1 guarantee and population-then-
state_code tie-breaks; disbursement terms round non-final terms first with
the final term absorbing the remainder.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants as C
from store import (
    base_record,
    clock_now,
    db,
    iso_z,
    next_seq,
    new_id,
    parse_dt,
    iso_ts,
    touch,
    wall_now,
)


def round_half_up_int(value):
    """Round a Decimal to the nearest integer, halves away from zero."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------

def create_notification(cycle, student_id, notice_type):
    rec = base_record()
    rec.update(
        {
            "student_id": student_id,
            "cycle_id": cycle["id"],
            "notice_type": notice_type,
            "sequence_number": C.NOTIFICATION_SEQUENCE[notice_type],
            "embargo_until": cycle[C.NOTIFICATION_EMBARGO_FIELD[notice_type]],
            "status": "EMBARGOED",
            "released_logical_at": None,
        }
    )
    db["notifications"][rec["id"]] = rec
    return rec


# --------------------------------------------------------------------------
# Apportionment (calculation: state_slot_allocation)
# --------------------------------------------------------------------------

def cycle_allocations(cycle_id):
    return sorted(
        (a for a in db["allocations"].values() if a["cycle_id"] == cycle_id),
        key=lambda a: a["state_code"],
    )


def close_entries(cycle):
    """ENTRY_OPEN -> ENTRY_CLOSED: provisional variant per state."""
    allocs = cycle_allocations(cycle["id"])
    total = cycle["total_semifinalist_slots"]
    pop = sum(a["graduating_population"] for a in allocs)
    for a in allocs:
        if pop > 0:
            quota = Decimal(total) * Decimal(a["graduating_population"]) / Decimal(pop)
        else:
            quota = Decimal(0)
        quota = quota.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        a["quota_raw"] = quota
        a["slots_provisional"] = round_half_up_int(quota)
        a["status"] = "PROVISIONAL"
        touch(a)
    cycle["status"] = "ENTRY_CLOSED"
    touch(cycle)


def _compute_final_slots(cycle, allocs):
    """Largest-remainder apportionment with MIN_STATE_SLOTS guarantee."""
    total = cycle["total_semifinalist_slots"]
    floors = {}
    remainders = {}
    bases = {}
    for a in allocs:
        quota = a["quota_raw"] if a["quota_raw"] is not None else Decimal(0)
        floor_q = int(quota)  # Decimal int() truncates toward zero; quotas >= 0
        floors[a["id"]] = floor_q
        remainders[a["id"]] = quota - Decimal(floor_q)
        if a["graduating_population"] > 0:
            bases[a["id"]] = max(C.MIN_STATE_SLOTS, floor_q)
        else:
            bases[a["id"]] = 0
    remainder_seats = total - sum(bases.values())
    extras = {a["id"]: 0 for a in allocs}
    # One seat at a time to the largest fractional remainder; ties break to
    # the larger graduating_population first, then state_code ascending.
    order = sorted(
        allocs,
        key=lambda a: (-remainders[a["id"]], -a["graduating_population"], a["state_code"]),
    )
    i = 0
    while remainder_seats > 0 and order:
        seat_for = order[i % len(order)]
        extras[seat_for["id"]] += 1
        remainder_seats -= 1
        i += 1
    # Defensive only: spec guarantees R >= 0 via the creation invariant; if a
    # degenerate population mix ever violates it, trim from the smallest
    # remainders (never below zero) so the sum still lands on T.
    while remainder_seats < 0:
        candidates = [a for a in allocs if bases[a["id"]] + extras[a["id"]] > 0]
        if not candidates:
            break
        candidates.sort(
            key=lambda a: (remainders[a["id"]], a["graduating_population"], a["state_code"])
        )
        bases[candidates[0]["id"]] -= 1
        remainder_seats += 1
    for a in allocs:
        a["slots_final"] = bases[a["id"]] + extras[a["id"]]


def run_semifinalist_selection(cycle):
    """ENTRY_CLOSED -> SEMIFINALISTS_SELECTED: final apportionment, per-state
    thresholds, entry flips, SEMIFINALIST_NOTICE notifications."""
    allocs = cycle_allocations(cycle["id"])
    _compute_final_slots(cycle, allocs)
    selected_total = 0
    for a in allocs:
        a["status"] = "FINAL"
        candidates = [
            e
            for e in db["entries"].values()
            if e["cycle_id"] == cycle["id"]
            and e["status"] == "SCORED"
            and db["students"][e["student_id"]]["state_code"] == a["state_code"]
        ]
        candidates.sort(
            key=lambda e: (
                -e["selection_index"],
                -e["math_score"],
                -e["reading_score"],
                e["created_at"],
                e["_seq"],
            )
        )
        n = len(candidates)
        k = min(a["slots_final"], n)
        if n == 0 or k == 0:
            threshold = None
        else:
            threshold = candidates[k - 1]["selection_index"]
        selected_count = 0
        for e in candidates:
            if threshold is not None and e["selection_index"] >= threshold:
                e["status"] = "SELECTED_SEMIFINALIST"
                selected_count += 1
                create_notification(cycle, e["student_id"], "SEMIFINALIST_NOTICE")
            else:
                e["status"] = "NOT_SELECTED"
            touch(e)
        a["threshold_selection_index"] = threshold
        a["selected_count"] = selected_count
        selected_total += selected_count
        touch(a)
    cycle["status"] = "SEMIFINALISTS_SELECTED"
    touch(cycle)
    return {"selected_total": selected_total, "states_finalized": len(allocs)}


def publish_finalists(cycle):
    """SEMIFINALISTS_SELECTED -> FINALISTS_SELECTED: auto-deny IN_PROGRESS
    applications, queue FINALIST_NOTICE for confirmed finalists."""
    for app in db["applications"].values():
        entry = db["entries"][app["entry_id"]]
        if entry["cycle_id"] != cycle["id"]:
            continue
        if app["status"] == "IN_PROGRESS":
            app["status"] = "DENIED"
            touch(app)
        elif app["status"] == "FINALIST_CONFIRMED":
            create_notification(cycle, app["student_id"], "FINALIST_NOTICE")
    cycle["status"] = "FINALISTS_SELECTED"
    touch(cycle)


# --------------------------------------------------------------------------
# Pool accounting (calculation: sponsor_pool_availability)
# --------------------------------------------------------------------------

def _pool_awards(pool, kind):
    key = "agreement_id" if kind == "agreement" else "college_id"
    return [a for a in db["awards"].values() if a[key] == pool["id"]]


def recompute_pool(pool, kind):
    """Recompute both ledgers from scratch on every pool mutation."""
    committed = 0
    paid = 0
    for award in _pool_awards(pool, kind):
        released = sum(
            d["amount_cents"]
            for d in db["disbursements"].values()
            if d["award_id"] == award["id"] and d["status"] == "RELEASED"
        )
        paid += released
        if award["recipient_status"] in C.LIVE_RECIPIENT_STATES:
            committed += award["amount_cents"] - released
    pool["pool_committed_cents"] = committed
    pool["pool_paid_cents"] = paid
    pool["pool_available_reserved_cents"] = pool["pool_total_cents"] - committed - paid
    pool["pool_available_cash_cents"] = pool["pool_total_cents"] - paid


def pool_unit(pool, kind):
    if kind == "agreement":
        return pool["award_amount_cents"]
    return pool["award_amount_cents"] * pool["renewable_years_total"]


def pool_live_count(pool, kind):
    return sum(
        1 for a in _pool_awards(pool, kind) if a["recipient_status"] in C.LIVE_RECIPIENT_STATES
    )


def reeval_pool_status(pool, kind):
    """Automatic EXHAUSTED/ACTIVE loop. Returns True on an EXHAUSTED->ACTIVE
    recovery flip (which triggers waitlist promotion)."""
    if pool["status"] not in ("ACTIVE", "EXHAUSTED"):
        return False
    unit = pool_unit(pool, kind)
    live = pool_live_count(pool, kind)
    if pool["status"] == "ACTIVE":
        if pool["pool_available_reserved_cents"] < unit or live >= pool["max_awards"]:
            pool["status"] = "EXHAUSTED"
            touch(pool)
    elif pool["pool_available_reserved_cents"] >= unit and live < pool["max_awards"]:
        pool["status"] = "ACTIVE"
        touch(pool)
        return True
    return False


def national_live_count(cycle):
    return sum(
        1
        for a in db["awards"].values()
        if a["cycle_id"] == cycle["id"]
        and a["category"] == "NATIONAL_SINGLE"
        and a["recipient_status"] in C.LIVE_RECIPIENT_STATES
    )


# --------------------------------------------------------------------------
# Award creation + selector (calculation: award_matching_waterfall /
# waitlist_promotion)
# --------------------------------------------------------------------------

def award_for_application(application_id):
    for a in db["awards"].values():
        if a["application_id"] == application_id:
            return a
    return None


def selector_rank_key(app):
    """selection_index_snapshot DESC, confirming_selection_index DESC,
    submitted_at ASC; never id."""
    entry = db["entries"][app["entry_id"]]
    return (
        -entry["selection_index"],
        -app["confirming_selection_index"],
        parse_dt(app["submitted_at"]),
        app["_seq"],
    )


def create_award(cycle, app, category, amount_cents, terms_total, renewable_years,
                 agreement_id=None, college_id=None):
    entry = db["entries"][app["entry_id"]]
    now = clock_now()
    rec = base_record()
    rec.update(
        {
            "cycle_id": cycle["id"],
            "application_id": app["id"],
            "student_id": app["student_id"],
            "agreement_id": agreement_id,
            "college_id": college_id,
            "category": category,
            "amount_cents": amount_cents,
            "terms_total": terms_total,
            "renewable_years_total": renewable_years,
            "years_renewed": 0,
            "recipient_status": "OFFERED",
            "funding_status": "PLEDGED",
            "selection_index_snapshot": entry["selection_index"],
            "offered_logical_at": iso_z(now),
            "acceptance_deadline": iso_z(now + timedelta(days=C.ACCEPTANCE_WINDOW_DAYS)),
        }
    )
    db["awards"][rec["id"]] = rec
    if agreement_id is not None:
        pool = db["agreements"][agreement_id]
        recompute_pool(pool, "agreement")
        reeval_pool_status(pool, "agreement")
    elif college_id is not None:
        pool = db["colleges"][college_id]
        recompute_pool(pool, "college")
        reeval_pool_status(pool, "college")
    create_notification(cycle, app["student_id"], "AWARD_OFFER")
    create_notification(cycle, app["student_id"], "PUBLIC_ANNOUNCEMENT")
    return rec


def corporate_eligible(app, agreement):
    student = db["students"][app["student_id"]]
    entry = db["entries"][app["entry_id"]]
    if agreement["employee_children_only"] and student["parent_sponsor_id"] != agreement["sponsor_id"]:
        return False
    if agreement["min_selection_index"] is not None and entry["selection_index"] < agreement["min_selection_index"]:
        return False
    return True


def confirmed_unawarded(cycle):
    return [
        app
        for app in db["applications"].values()
        if db["entries"][app["entry_id"]]["cycle_id"] == cycle["id"]
        and app["status"] == "FINALIST_CONFIRMED"
        and award_for_application(app["id"]) is None
    ]


def run_award_matching(cycle):
    """The waterfall: national bucket, then corporate agreements in
    created_at ASC, then college institutions in created_at ASC."""
    remaining = sorted(confirmed_unawarded(cycle), key=selector_rank_key)
    national_granted = 0
    corporate_granted = 0
    college_granted = 0

    # (1) National bucket: top national_award_slots candidates; 0 disables it.
    slots = cycle["national_award_slots"]
    if slots > 0 and remaining:
        for app in remaining[:slots]:
            create_award(
                cycle, app, "NATIONAL_SINGLE", cycle["national_award_amount_cents"], 1, 1
            )
            national_granted += 1
        remaining = remaining[slots:] if len(remaining) >= slots else []

    # (2) Corporate bucket: per ACTIVE agreement of the cycle, created_at ASC.
    agreements = sorted(
        (
            a
            for a in db["agreements"].values()
            if a["cycle_id"] == cycle["id"] and a["status"] == "ACTIVE"
        ),
        key=lambda a: (a["created_at"], a["_seq"]),
    )
    for ag in agreements:
        while True:
            recompute_pool(ag, "agreement")
            headroom = ag["max_awards"] - pool_live_count(ag, "agreement")
            capacity = ag["pool_available_reserved_cents"] // ag["award_amount_cents"]
            if min(headroom, capacity) <= 0:
                break
            eligible = [app for app in remaining if corporate_eligible(app, ag)]
            if not eligible:
                break
            chosen = eligible[0]
            create_award(
                cycle, chosen, "CORPORATE_SPONSORED", ag["award_amount_cents"], 1, 1,
                agreement_id=ag["id"],
            )
            corporate_granted += 1
            remaining.remove(chosen)
        recompute_pool(ag, "agreement")
        reeval_pool_status(ag, "agreement")

    # (3) College bucket: per ACTIVE institution, created_at ASC.
    colleges = sorted(
        (c for c in db["colleges"].values() if c["status"] == "ACTIVE"),
        key=lambda c: (c["created_at"], c["_seq"]),
    )
    for col in colleges:
        unit = col["award_amount_cents"] * col["renewable_years_total"]
        while True:
            recompute_pool(col, "college")
            headroom = col["max_awards"] - pool_live_count(col, "college")
            capacity = col["pool_available_reserved_cents"] // unit
            if min(headroom, capacity) <= 0:
                break
            eligible = [
                app for app in remaining if app["first_choice_college_id"] == col["id"]
            ]
            if not eligible:
                break
            chosen = eligible[0]
            create_award(
                cycle, chosen, "COLLEGE_SPONSORED", unit,
                col["renewable_years_total"] * col["terms_per_year"],
                col["renewable_years_total"], college_id=col["id"],
            )
            college_granted += 1
            remaining.remove(chosen)
        recompute_pool(col, "college")
        reeval_pool_status(col, "college")

    cycle["matching_run"] = True
    touch(cycle)
    return {
        "awards_created": national_granted + corporate_granted + college_granted,
        "national_granted": national_granted,
        "corporate_granted": corporate_granted,
        "college_granted": college_granted,
    }


def promote_pool(kind, pool, cycle):
    """Waitlist promotion for one freed pool: grant one award per iteration
    to the top-ranked eligible un-awarded confirmed finalist while capacity
    and candidates remain."""
    while True:
        candidates = confirmed_unawarded(cycle)
        if kind == "agreement":
            candidates = [a for a in candidates if corporate_eligible(a, pool)]
        elif kind == "college":
            candidates = [a for a in candidates if a["first_choice_college_id"] == pool["id"]]
        candidates.sort(key=selector_rank_key)
        if not candidates:
            return
        if kind == "national":
            if cycle["national_award_slots"] <= 0 or national_live_count(cycle) >= cycle["national_award_slots"]:
                return
            chosen = candidates[0]
            create_award(cycle, chosen, "NATIONAL_SINGLE",
                         cycle["national_award_amount_cents"], 1, 1)
        else:
            recompute_pool(pool, kind)
            unit = pool_unit(pool, kind)
            if pool["pool_available_reserved_cents"] // unit < 1:
                return
            if pool_live_count(pool, kind) >= pool["max_awards"]:
                return
            chosen = candidates[0]
            if kind == "agreement":
                create_award(cycle, chosen, "CORPORATE_SPONSORED",
                             pool["award_amount_cents"], 1, 1, agreement_id=pool["id"])
            else:
                create_award(cycle, chosen, "COLLEGE_SPONSORED", unit,
                             pool["renewable_years_total"] * pool["terms_per_year"],
                             pool["renewable_years_total"], college_id=pool["id"])


# --------------------------------------------------------------------------
# Cycle completion bubble-up (PRD 3.8)
# --------------------------------------------------------------------------

def maybe_complete_cycle(cycle):
    if not cycle["matching_run"] or cycle["status"] != "FINALISTS_SELECTED":
        return
    award_ids = [
        a["id"] for a in db["awards"].values() if a["cycle_id"] == cycle["id"]
    ]
    for a in db["awards"].values():
        if a["cycle_id"] == cycle["id"] and a["recipient_status"] in C.LIVE_RECIPIENT_STATES:
            return
    for d in db["disbursements"].values():
        if d["award_id"] in award_ids and d["status"] in ("SCHEDULED", "HELD"):
            return
    cycle["status"] = "AWARDS_COMPLETED"
    touch(cycle)
    for ag in db["agreements"].values():
        if ag["cycle_id"] == cycle["id"] and ag["status"] in ("ACTIVE", "EXHAUSTED"):
            ag["status"] = "CLOSED"
            touch(ag)


def check_all_cycles():
    for cycle in db["cycles"].values():
        maybe_complete_cycle(cycle)


# --------------------------------------------------------------------------
# Award lifecycle cascades (PRD 3.8)
# --------------------------------------------------------------------------

def _supersede_unreleased_offer_notifications(award):
    for n in db["notifications"].values():
        if (
            n["student_id"] == award["student_id"]
            and n["cycle_id"] == award["cycle_id"]
            and n["notice_type"] in ("AWARD_OFFER", "PUBLIC_ANNOUNCEMENT")
            and n["status"] == "EMBARGOED"
        ):
            n["status"] = "SUPERSEDED"
            touch(n)


def _release_pool_capacity(award):
    """Release the award's reservation, re-evaluate the freed pool, and run
    waitlist promotion for it. Returns nothing."""
    cycle = db["cycles"][award["cycle_id"]]
    if award["agreement_id"] is not None:
        pool = db["agreements"][award["agreement_id"]]
        recompute_pool(pool, "agreement")
        if reeval_pool_status(pool, "agreement"):
            promote_pool("agreement", pool, cycle)
    elif award["college_id"] is not None:
        pool = db["colleges"][award["college_id"]]
        recompute_pool(pool, "college")
        if reeval_pool_status(pool, "college"):
            promote_pool("college", pool, cycle)
    else:
        if (
            cycle["national_award_slots"] > 0
            and national_live_count(cycle) < cycle["national_award_slots"]
        ):
            promote_pool("national", None, cycle)


def release_cascade(award, new_recipient_status):
    """Decline / expiry share this four-link cascade: pool release, pool
    status re-evaluation, waitlist promotion, notification supersede/queue."""
    award["recipient_status"] = new_recipient_status
    award["funding_status"] = "RELEASED_BACK"
    touch(award)
    _supersede_unreleased_offer_notifications(award)
    _release_pool_capacity(award)
    check_all_cycles()


def accept_award(award):
    """OFFERED -> ACCEPTED; PLEDGED -> COMMITTED; generate the schedule."""
    award["recipient_status"] = "ACCEPTED"
    award["funding_status"] = "COMMITTED"
    touch(award)
    _generate_schedule(award)
    check_all_cycles()


def _generate_schedule(award):
    """Per-term split: non-final terms round_half_up(amount/terms_total);
    the final term absorbs the remainder so the schedule sums exactly."""
    terms_total = award["terms_total"]
    if award["college_id"] is not None:
        terms_per_year = db["colleges"][award["college_id"]]["terms_per_year"]
    else:
        terms_per_year = 1
    amount = award["amount_cents"]
    per_term = 0
    if terms_total > 1:
        per_term = round_half_up_int(Decimal(amount) / Decimal(terms_total))
    t0 = clock_now()
    running = 0
    for i in range(1, terms_total + 1):
        if i < terms_total:
            term_amount = per_term
            running += per_term
        else:
            term_amount = amount - running
        year = math.ceil(i / terms_per_year)
        rec = base_record()
        rec.update(
            {
                "award_id": award["id"],
                "term_index": i,
                "academic_year_index": year,
                "scheduled_date": iso_z(t0 + timedelta(days=(i - 1) * C.TERM_INTERVAL_DAYS)),
                "amount_cents": term_amount,
                "status": "SCHEDULED" if year == 1 else "HELD",
                "released_logical_at": None,
            }
        )
        db["disbursements"][rec["id"]] = rec


def release_disbursement(disb):
    """SCHEDULED -> RELEASED; move money committed -> paid; re-evaluate the
    award's funding and recipient dimensions."""
    award = db["awards"][disb["award_id"]]
    disb["status"] = "RELEASED"
    disb["released_logical_at"] = iso_z(clock_now())
    touch(disb)
    if award["agreement_id"] is not None:
        recompute_pool(db["agreements"][award["agreement_id"]], "agreement")
    elif award["college_id"] is not None:
        recompute_pool(db["colleges"][award["college_id"]], "college")
    if award["recipient_status"] == "ACCEPTED":
        award["recipient_status"] = "ENROLLED"
    award_disbs = [d for d in db["disbursements"].values() if d["award_id"] == award["id"]]
    non_cancelled = [d for d in award_disbs if d["status"] != "CANCELLED"]
    if non_cancelled and all(d["status"] == "RELEASED" for d in non_cancelled):
        award["funding_status"] = "FULLY_DISBURSED"
        if award["recipient_status"] in ("ACCEPTED", "ENROLLED", "RENEWED"):
            award["recipient_status"] = "COMPLETED"
    else:
        award["funding_status"] = "PARTIALLY_DISBURSED"
    touch(award)
    check_all_cycles()


def lapse_award(award):
    """Renewal REJECTED: award lapses; remaining terms CANCELLED; pool
    released; pool re-evaluated; promotion on an EXHAUSTED->ACTIVE flip."""
    award["recipient_status"] = "LAPSED"
    award["funding_status"] = "RELEASED_BACK"
    touch(award)
    for d in db["disbursements"].values():
        if d["award_id"] == award["id"] and d["status"] in ("SCHEDULED", "HELD"):
            d["status"] = "CANCELLED"
            touch(d)
    _release_pool_capacity(award)
    check_all_cycles()


def decide_renewal(verification, approve):
    award = db["awards"][verification["award_id"]]
    verification["status"] = "APPROVED" if approve else "REJECTED"
    verification["decided_logical_at"] = iso_z(clock_now())
    touch(verification)
    if approve:
        if award["recipient_status"] == "ENROLLED":
            award["recipient_status"] = "RENEWED"
        award["years_renewed"] += 1
        for d in db["disbursements"].values():
            if (
                d["award_id"] == award["id"]
                and d["academic_year_index"] == verification["academic_year_index"]
                and d["status"] == "HELD"
            ):
                d["status"] = "SCHEDULED"
                touch(d)
        touch(award)
    else:
        lapse_award(award)
    check_all_cycles()


# --------------------------------------------------------------------------
# Logical clock sweep (PRD 2.5)
# --------------------------------------------------------------------------

def sweep_expired_offers(new_now):
    """Every still-OFFERED award whose acceptance_deadline has been advanced
    past is swept to EXPIRED with the full release cascade."""
    expired_ids = []
    due = sorted(
        (
            a
            for a in db["awards"].values()
            if a["recipient_status"] == "OFFERED"
            and parse_dt(a["acceptance_deadline"]) < new_now
        ),
        key=lambda a: (a["created_at"], a["_seq"]),
    )
    for award in due:
        release_cascade(award, "EXPIRED")
        expired_ids.append(award["id"])
    return expired_ids
