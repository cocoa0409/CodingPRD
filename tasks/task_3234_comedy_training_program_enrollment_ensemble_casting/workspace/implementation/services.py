"""Shared business logic: prerequisite DAG, refunds, seat allocation, scholarships, invoices."""
from decimal import Decimal, ROUND_HALF_UP
from store import store, parse_dt, logical_now, stamp, fresh, new_id, now_iso
from errors import (
    raise_err, ERR_PREREQUISITE_CYCLE, ERR_PREREQUISITE_NOT_MET, ERR_NOT_FOUND,
    ERR_SCHOLARSHIP_EXHAUSTED, ERR_SECTION_FULL, ERR_INVALID_STATE,
)


# ---------- Level DAG helpers ----------

def level_by_code(code):
    for lv in store.levels.values():
        if lv["code"] == code:
            return lv
    return None


def check_cycle(level_id, requires_code):
    """Walk requires_level_code chain from the level being written; revisit = cycle."""
    if not requires_code:
        return
    visited = {level_id}
    cur_code = requires_code
    while cur_code:
        cur = level_by_code(cur_code)
        if cur is None:
            # unknown codes are allowed (no dangling-FK error specified)
            return
        if cur["id"] in visited:
            raise_err(ERR_PREREQUISITE_CYCLE, "prerequisite chain forms a cycle")
        visited.add(cur["id"])
        cur_code = cur.get("requires_level_code")


def prereq_closure_codes(level):
    """Transitive closure of prerequisite codes within the same track, ACTIVE levels only."""
    codes = []
    seen = set()
    cur = level
    while cur and cur.get("requires_level_code"):
        nxt = level_by_code(cur["requires_level_code"])
        if nxt is None or nxt["id"] in seen:
            break
        seen.add(nxt["id"])
        if nxt.get("status") == "ACTIVE" and nxt.get("track") == level.get("track"):
            codes.append(nxt["code"])
        cur = nxt
    return codes


def check_prerequisites(student, level):
    satisfied = set(student.get("completed_level_codes") or []) | set(student.get("placement_credit_codes") or [])
    for code in prereq_closure_codes(level):
        if code not in satisfied:
            raise_err(ERR_PREREQUISITE_NOT_MET, f"prerequisite {code} not satisfied")


def granted_codes_for(target_level):
    """Target level plus every prerequisite below it in the same track."""
    codes = [target_level["code"]]
    codes.extend(prereq_closure_codes(target_level))
    # preserve order, dedupe
    out, seen = [], set()
    for c in codes:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


# ---------- Enrollment counters ----------

def recompute_section_counts(section):
    """Occupancy counters (§3.2): a seat is held only from confirmation onward —
    confirmation raises `enrolled_count` by 1 (§3.3) and the waterfall leaves it
    unchanged until the promoted student confirms (§3.3) — so `enrolled_count`
    counts CONFIRMED enrollments. `waitlist_count` counts WAITLISTED ones."""
    enrolled = 0
    waitlisted = 0
    for e in store.enrollments.values():
        if e["section_id"] != section["id"]:
            continue
        if e["status"] == "CONFIRMED":
            enrolled += 1
        elif e["status"] == "WAITLISTED":
            waitlisted += 1
    section["enrolled_count"] = enrolled
    section["waitlist_count"] = waitlisted


def seat_allocation(section):
    """Promote head of waitlist: RETURNING > NEW, then created_at ASC."""
    pool = [
        e for e in store.enrollments.values()
        if e["section_id"] == section["id"] and e["status"] == "WAITLISTED"
    ]
    if not pool:
        return
    pool.sort(key=lambda e: (0 if e["priority_tier"] == "RETURNING" else 1, e["created_at"]))
    head = pool[0]
    head["status"] = "REGISTERED"
    stamp(head)
    recompute_section_counts(section)


# ---------- Invoice / scholarship logic ----------

def round_half_up_int(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_invoice(inv):
    inv["amount_due_cents"] = (
        inv["base_amount_cents"] - inv["scholarship_applied_cents"] - inv["paid_cents"]
    )


def disburse_scholarships(inv):
    """On invoice issuance: apply student's AWARDED/DISBURSED awards FIFO by created_at.

    Note: the AWARDED->DISBURSED disbursement cascade applies to awards held by the
    invoice's student, per PRD §3.4.
    """
    student_id = inv["student_id"]
    awards = [
        a for a in store.scholarships.values()
        if a["student_id"] == student_id and a["status"] in ("AWARDED", "DISBURSED")
    ]
    awards.sort(key=lambda a: a["created_at"])
    applied = inv["scholarship_applied_cents"]
    for award in awards:
        remaining_award = award["amount_cents"] - award["disbursed_cents"]
        if remaining_award <= 0:
            continue
        # remaining invoice balance this award could cover
        balance = inv["base_amount_cents"] - applied
        if balance <= 0:
            break
        take = min(remaining_award, balance)
        if take <= 0:
            continue
        if award["disbursed_cents"] + take > award["amount_cents"]:
            raise_err(ERR_SCHOLARSHIP_EXHAUSTED, "scholarship disbursement exceeds award balance")
        award["disbursed_cents"] += take
        if award["disbursed_cents"] > 0 and award["status"] == "AWARDED":
            award["status"] = "DISBURSED"
        stamp(award)
        applied += take
    inv["scholarship_applied_cents"] = applied
    recompute_invoice(inv)


def issue_invoice(student_id, enrollment_id, base_amount_cents, carried_paid=0):
    inv = fresh({
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "base_amount_cents": base_amount_cents,
        "scholarship_applied_cents": 0,
        "amount_due_cents": 0,
        "paid_cents": carried_paid,
        "refunded_cents": 0,
        "status": "ISSUED",
    })
    store.invoices[inv["id"]] = inv
    disburse_scholarships(inv)
    recompute_invoice(inv)
    if carried_paid and inv["amount_due_cents"] <= 0:
        inv["status"] = "PAID"
    elif carried_paid:
        inv["status"] = "PARTIALLY_PAID"
    return inv


def invoice_for_enrollment(enrollment_id):
    for inv in store.invoices.values():
        if inv["enrollment_id"] == enrollment_id and inv["status"] not in ("VOID", "TRANSFERRED"):
            return inv
    # fall back to any invoice
    for inv in store.invoices.values():
        if inv["enrollment_id"] == enrollment_id:
            return inv
    return None


def clawback_scholarship(inv):
    """Return the scholarship_applied portion to originating awards (newest disbursement first
    is fine; PRD only requires clawback, not order)."""
    remaining = inv["scholarship_applied_cents"]
    if remaining <= 0:
        return
    awards = [
        a for a in store.scholarships.values()
        if a["student_id"] == inv["student_id"] and a["disbursed_cents"] > 0
    ]
    awards.sort(key=lambda a: a["created_at"], reverse=True)
    for award in awards:
        if remaining <= 0:
            break
        back = min(award["disbursed_cents"], remaining)
        award["disbursed_cents"] -= back
        remaining -= back
        stamp(award)


def refund_invoice_full(inv):
    """100% refund: covers paid_cents plus unwinds the scholarship portion."""
    clawback_scholarship(inv)
    inv["refunded_cents"] = inv["paid_cents"]
    inv["scholarship_applied_cents"] = 0
    inv["status"] = "REFUNDED"
    recompute_invoice(inv)
    stamp(inv)


def refund_invoice_tiered(inv, refund_pct):
    """Late-drop tiered refund of paid cash only; scholarship clawed back."""
    clawback_scholarship(inv)
    cash_refund = round_half_up_int(Decimal(inv["paid_cents"]) * Decimal(str(refund_pct)))
    inv["refunded_cents"] = cash_refund
    inv["scholarship_applied_cents"] = 0
    inv["status"] = "REFUNDED"
    recompute_invoice(inv)
    stamp(inv)


def refund_pct_for(term):
    """Chronological refund percentage per PRD §3.4 / scaffold tuition_refund."""
    now = logical_now()
    start = parse_dt(term["start_utc"])
    end = parse_dt(term["end_utc"])
    deadline = parse_dt(term["drop_deadline_utc"])
    if now <= deadline:
        return 1.0
    total = (end - start).total_seconds()
    if total <= 0:
        return 0.0
    elapsed = (now - start).total_seconds() / total
    if elapsed < 0.25:
        return 0.75
    if elapsed < 0.50:
        return 0.50
    if elapsed < 0.75:
        return 0.25
    return 0.0


def is_early(term):
    return logical_now() <= parse_dt(term["drop_deadline_utc"])


# ---------- Student derived fields ----------

def refresh_student_derived(student):
    completed = set()
    for e in store.enrollments.values():
        if e["student_id"] == student["id"] and e["status"] == "CREDITED":
            sec = store.sections.get(e["section_id"])
            if sec:
                lv = store.levels.get(sec["level_id"])
                if lv:
                    completed.add(lv["code"])
    student["completed_level_codes"] = sorted(completed)
    student["is_alumni"] = any(
        e["student_id"] == student["id"] and e["status"] == "CREDITED"
        for e in store.enrollments.values()
    )
    graduated = any(
        c.get("_admitted_ids") and student["id"] in c["_admitted_ids"] and c["status"] == "GRADUATED"
        for c in store.cohorts.values()
    )
    student["is_industry_showcase_eligible"] = bool(student["is_alumni"] and graduated)


def credit_enrollment(enrollment, showcase_id=None):
    """COMPLETED -> CREDITED cascade (§3.3)."""
    if enrollment["status"] != "COMPLETED":
        return
    enrollment["status"] = "CREDITED"
    if showcase_id:
        enrollment["graded_showcase_id"] = showcase_id
    stamp(enrollment)
    student = store.students.get(enrollment["student_id"])
    if student:
        refresh_student_derived(student)
        stamp(student)


# ---------- Section cascade helpers ----------

def cancel_section_cascade(section):
    """Drop all REGISTERED/WAITLISTED enrollments early and refund their invoices."""
    for e in list(store.enrollments.values()):
        if e["section_id"] == section["id"] and e["status"] in ("REGISTERED", "WAITLISTED"):
            e["status"] = "DROPPED_EARLY"
            stamp(e)
            inv = invoice_for_enrollment(e["id"])
            if inv and inv["status"] not in ("REFUNDED", "VOID", "TRANSFERRED"):
                refund_invoice_full(inv)
    recompute_section_counts(section)
    stamp(section)


# ---------- Venue conflict helpers ----------

MIN_TURNOVER_MINUTES = 30


def venue_conflict(new_start, new_end, venue_name, exclude_id=None):
    """Check overlap + turnover buffer vs RESERVED/BOOKED slots on the same venue."""
    for slot in store.venue_slots.values():
        if exclude_id and slot["id"] == exclude_id:
            continue
        if slot["venue_name"] != venue_name:
            continue
        if slot["status"] not in ("RESERVED", "BOOKED"):
            continue
        s = parse_dt(slot["start_utc"])
        e = parse_dt(slot["end_utc"])
        # overlap: half-open conflict
        if new_start < e and s < new_end:
            return True
        # turnover buffer: positive gap < 30 min on same venue
        gap1 = (new_start - e).total_seconds() / 60.0   # new after existing
        gap2 = (s - new_end).total_seconds() / 60.0     # new before existing
        if 0 < gap1 < MIN_TURNOVER_MINUTES:
            return True
        if 0 < gap2 < MIN_TURNOVER_MINUTES:
            return True
    return False
