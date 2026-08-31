"""Serializers, derived-counter maintenance, cascades and the shared
state-transition helpers."""
from decimal import Decimal

import calc
from core import (DB, D, fail, fmt_dt, now, num, ordered, touch, base_record,
                  new_id)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(rec, out):
    out["id"] = rec["id"]
    out["created_at"] = fmt_dt(rec["created_at"])
    if "updated_at" in rec:
        out["updated_at"] = fmt_dt(rec["updated_at"])
    if "version" in rec:
        out["version"] = rec["version"]
    return out


def ser_course(rec):
    return _common(rec, {
        "course_code": rec["course_code"],
        "title": rec["title"],
        "ceu_units": num(rec["ceu_units"], 1),
        "contact_hours": float(rec["contact_hours"]),
        "list_price_cents": rec["list_price_cents"],
        "delivery_mode": rec["delivery_mode"],
        "prerequisite_course_id": rec["prerequisite_course_id"],
        "cpl_credit_units": num(rec["cpl_credit_units"], 1),
        "status": rec["status"],
        "active_offering_count": rec["active_offering_count"],
    })


def ser_offering(rec):
    return _common(rec, {
        "course_id": rec["course_id"],
        "scheduling_mode": rec["scheduling_mode"],
        "term_code": rec["term_code"],
        "start_date": fmt_dt(rec["start_date"]),
        "end_date": fmt_dt(rec["end_date"]),
        "census_at": fmt_dt(rec["census_at"]),
        "session_count": rec["session_count"],
        "min_enrollment": rec["min_enrollment"],
        "max_enrollment": rec["max_enrollment"],
        "tuition_cents": rec["tuition_cents"],
        "status": rec["status"],
        "cancellation_reason": rec["cancellation_reason"],
        "confirmed_enrollment_count": rec["confirmed_enrollment_count"],
        "paid_enrollment_count": rec["paid_enrollment_count"],
        "waitlist_count": rec["waitlist_count"],
        "net_program_revenue_cents": rec["net_program_revenue_cents"],
    })


def ser_learner(rec):
    return _common(rec, {
        "email": rec["email"],
        "full_name": rec["full_name"],
        "marketing_opt_in": rec["marketing_opt_in"],
        "marketing_status": rec["marketing_status"],
        "lifetime_completed_count": rec["lifetime_completed_count"],
        "lifetime_ceu_total": num(rec["lifetime_ceu_total"], 1),
        "loyalty_tier": rec["loyalty_tier"],
    })


def ser_instructor(rec):
    return _common(rec, {
        "email": rec["email"],
        "full_name": rec["full_name"],
        "credential_level": rec["credential_level"],
        "active_contract_count": rec["active_contract_count"],
    })


def ser_account(rec):
    return _common(rec, {
        "org_name": rec["org_name"],
        "billing_email": rec["billing_email"],
        "status": rec["status"],
        "funded_cents": rec["funded_cents"],
        "available_cents": rec["available_cents"],
        "unallocated_voucher_cents": rec["unallocated_voucher_cents"],
        "committed_cents": rec["committed_cents"],
        "consumed_cents": rec["consumed_cents"],
    })


def ser_voucher(rec):
    return _common(rec, {
        "corporate_account_id": rec["corporate_account_id"],
        "assigned_learner_id": rec["assigned_learner_id"],
        "face_value_cents": rec["face_value_cents"],
        "remaining_cents": rec["remaining_cents"],
        "committed_cents": rec["committed_cents"],
        "consumed_cents": rec["consumed_cents"],
        "expires_at": fmt_dt(rec["expires_at"]),
        "status": rec["status"],
    })


def ser_registration(rec):
    return _common(rec, {
        "offering_id": rec["offering_id"],
        "learner_id": rec["learner_id"],
        "voucher_id": rec["voucher_id"],
        "transferred_to_registration_id": rec["transferred_to_registration_id"],
        "enrollment_status": rec["enrollment_status"],
        "payment_status": rec["payment_status"],
        "list_tuition_cents": rec["list_tuition_cents"],
        "loyalty_discount_cents": rec["loyalty_discount_cents"],
        "processing_fee_cents": rec["processing_fee_cents"],
        "total_due_cents": rec["total_due_cents"],
        "amount_paid_cents": rec["amount_paid_cents"],
        "amount_refunded_cents": rec["amount_refunded_cents"],
        "sessions_attended": rec["sessions_attended"],
        "total_sessions": rec["total_sessions"],
        "enrolled_at": fmt_dt(rec["enrolled_at"]),
    })


def ser_contract(rec):
    return _common(rec, {
        "offering_id": rec["offering_id"],
        "instructor_id": rec["instructor_id"],
        "base_stipend_cents": rec["base_stipend_cents"],
        "per_enrollment_cents": rec["per_enrollment_cents"],
        "enrollment_cap_for_pay": rec["enrollment_cap_for_pay"],
        "pay_basis": rec["pay_basis"],
        "status": rec["status"],
        "census_headcount": rec["census_headcount"],
        "final_headcount": rec["final_headcount"],
        "settled_pay_cents": rec["settled_pay_cents"],
        "kill_fee_cents": rec["kill_fee_cents"],
    })


def ser_completion(rec):
    return _common(rec, {
        "registration_id": rec["registration_id"],
        "learner_id": rec["learner_id"],
        "ceu_awarded": num(rec["ceu_awarded"], 1),
        "attendance_ratio": num(rec["attendance_ratio"], 4),
        "certificate_number": rec["certificate_number"],
        "issued_at": fmt_dt(rec["issued_at"]),
        "status": rec["status"],
    })


def ser_petition(rec):
    return _common(rec, {
        "learner_id": rec["learner_id"],
        "target_course_id": rec["target_course_id"],
        "status": rec["status"],
        "revision_round": rec["revision_round"],
        "assessed_by_user_id": rec["assessed_by_user_id"],
        "claimed_ceu_total": num(rec["claimed_ceu_total"], 2),
        "awarded_credit_units": num(rec["awarded_credit_units"], 1),
        "decision_note": rec["decision_note"],
    })


def ser_citation(rec):
    return {
        "id": rec["id"],
        "petition_id": rec["petition_id"],
        "completion_record_id": rec["completion_record_id"],
        "weight": float(rec["weight"]),
        "created_at": fmt_dt(rec["created_at"]),
    }


def ser_request(rec):
    return _common(rec, {
        "registration_id": rec["registration_id"],
        "target_offering_id": rec["target_offering_id"],
        "request_type": rec["request_type"],
        "refund_basis": rec["refund_basis"],
        "days_before_start": rec["days_before_start"],
        "computed_refund_cents": rec["computed_refund_cents"],
        "status": rec["status"],
        "settled_at": fmt_dt(rec["settled_at"]),
    })


def ser_membership(rec):
    return _common(rec, {
        "learner_id": rec["learner_id"],
        "segment": rec["segment"],
        "state": rec["state"],
        "recomputed_at": fmt_dt(rec["recomputed_at"]),
    })


# ---------------------------------------------------------------------------
# Simple collection helpers
# ---------------------------------------------------------------------------

def regs_of_offering(offering_id):
    return ordered([r for r in DB.registrations.values()
                    if r["offering_id"] == offering_id])


def regs_of_learner(learner_id):
    return ordered([r for r in DB.registrations.values()
                    if r["learner_id"] == learner_id])


def contracts_of_offering(offering_id):
    return ordered([c for c in DB.instructor_contracts.values()
                    if c["offering_id"] == offering_id])


def citations_of_petition(petition_id):
    return ordered([c for c in DB.cpl_citations.values()
                    if c["petition_id"] == petition_id])


def citations_of_record(record_id):
    return ordered([c for c in DB.cpl_citations.values()
                    if c["completion_record_id"] == record_id])


def memberships_of_learner(learner_id):
    return ordered([m for m in DB.marketing_memberships.values()
                    if m["learner_id"] == learner_id])


# ---------------------------------------------------------------------------
# Derived counters
# ---------------------------------------------------------------------------

LIVE_OFFERING_STATES = ("DRAFT", "OPEN", "WAITLIST_ONLY", "CENSUS_LOCKED")


def recompute_active_offering_count(course):
    value = len([o for o in DB.offerings.values()
                 if o["course_id"] == course["id"]
                 and o["status"] in LIVE_OFFERING_STATES])
    if value != course["active_offering_count"]:
        course["active_offering_count"] = value
        touch(course)


def recompute_active_contract_count(instructor):
    value = len([c for c in DB.instructor_contracts.values()
                 if c["instructor_id"] == instructor["id"]
                 and c["status"] in ("SIGNED", "ACTIVE")])
    instructor["active_contract_count"] = value


def recompute_offering_revenue(offering):
    offering["net_program_revenue_cents"] = calc.offering_net_program_revenue(
        offering, list(DB.registrations.values()))


def recompute_account_ledger(account):
    live = [v for v in DB.vouchers.values()
            if v["corporate_account_id"] == account["id"] and v["status"] != "VOIDED"]
    account["available_cents"] = account["funded_cents"] - sum(
        v["face_value_cents"] for v in live)
    account["unallocated_voucher_cents"] = sum(v["remaining_cents"] for v in live)
    account["committed_cents"] = sum(v["committed_cents"] for v in live)
    account["consumed_cents"] = sum(v["consumed_cents"] for v in live)


def derive_voucher_status(voucher):
    if voucher["status"] == "VOIDED":
        return
    if voucher["committed_cents"] == 0 and voucher["consumed_cents"] == 0:
        voucher["status"] = "ASSIGNED" if voucher["assigned_learner_id"] else "ISSUED"
    elif voucher["remaining_cents"] > 0:
        voucher["status"] = "PARTIALLY_REDEEMED"
    else:
        voucher["status"] = "EXHAUSTED"


# ---------------------------------------------------------------------------
# Learner lifetime totals + marketing segmentation
# ---------------------------------------------------------------------------

EXCLUSIVE_SEGMENTS = ("PROSPECT", "FIRST_TIME", "REPEAT")


def recompute_learner_totals(learner):
    count, ceu_total, tier = calc.learner_loyalty_and_ceu(
        learner, list(DB.completion_records.values()))
    learner["lifetime_completed_count"] = count
    learner["lifetime_ceu_total"] = ceu_total
    learner["loyalty_tier"] = tier


def _membership(learner_id, segment):
    for m in memberships_of_learner(learner_id):
        if m["segment"] == segment:
            return m
    return None


def _create_membership(learner_id, segment, state):
    rec = base_record()
    rec.update({
        "learner_id": learner_id,
        "segment": segment,
        "state": state,
        "recomputed_at": now(),
    })
    DB.marketing_memberships[rec["id"]] = rec
    return rec


def _set_membership(learner_id, segment, state):
    existing = _membership(learner_id, segment)
    if existing is None:
        if state == "REMOVED":
            return
        _create_membership(learner_id, segment, state)
        return
    if existing["state"] != state:
        existing["state"] = state
        existing["recomputed_at"] = now()
        touch(existing)
    else:
        existing["recomputed_at"] = now()
        touch(existing)


def marketing_segment_recompute(learner):
    learner_id = learner["id"]
    count = learner["lifetime_completed_count"]
    if count == 0:
        exclusive = "PROSPECT"
    elif count == 1:
        exclusive = "FIRST_TIME"
    else:
        exclusive = "REPEAT"

    corporate_active = False
    for r in DB.registrations.values():
        if (r["learner_id"] == learner_id and r["voucher_id"] is not None
                and r["enrollment_status"] not in ("WITHDRAWN", "TRANSFERRED_OUT")):
            corporate_active = True
            break
    if not corporate_active:
        for v in DB.vouchers.values():
            if v["assigned_learner_id"] == learner_id and v["status"] != "VOIDED":
                corporate_active = True
                break

    if learner["marketing_status"] == "UNSUBSCRIBED":
        for m in memberships_of_learner(learner_id):
            if m["segment"] != "LAPSED":
                _set_membership(learner_id, m["segment"], "REMOVED")
        _set_membership(learner_id, "LAPSED", "ACTIVE")
        return

    _set_membership(learner_id, "LAPSED", "REMOVED")
    for segment in EXCLUSIVE_SEGMENTS:
        _set_membership(learner_id, segment,
                        "ACTIVE" if segment == exclusive else "REMOVED")
    _set_membership(learner_id, "CORPORATE_SPONSORED",
                    "ACTIVE" if corporate_active else "REMOVED")


# ---------------------------------------------------------------------------
# Voucher / sponsor value movement
# ---------------------------------------------------------------------------

def voucher_commit(voucher, amount):
    voucher["remaining_cents"] -= amount
    voucher["committed_cents"] += amount
    voucher["status"] = "PARTIALLY_REDEEMED" if voucher["remaining_cents"] > 0 \
        else "EXHAUSTED"
    touch(voucher)
    account = DB.corporate_accounts[voucher["corporate_account_id"]]
    recompute_account_ledger(account)
    touch(account)


def voucher_consume(voucher, amount):
    voucher["committed_cents"] -= amount
    voucher["consumed_cents"] += amount
    touch(voucher)
    account = DB.corporate_accounts[voucher["corporate_account_id"]]
    recompute_account_ledger(account)
    touch(account)


def voucher_release(voucher, amount):
    """Return `amount` from whichever of committed/consumed is holding it."""
    take_committed = min(voucher["committed_cents"], amount)
    voucher["committed_cents"] -= take_committed
    rest = amount - take_committed
    if rest > 0:
        take_consumed = min(voucher["consumed_cents"], rest)
        voucher["consumed_cents"] -= take_consumed
        rest -= take_consumed
    voucher["remaining_cents"] += (amount - rest)
    derive_voucher_status(voucher)
    touch(voucher)
    account = DB.corporate_accounts[voucher["corporate_account_id"]]
    recompute_account_ledger(account)
    touch(account)


# ---------------------------------------------------------------------------
# Seat resolution / waitlist mechanics
# ---------------------------------------------------------------------------

def seat_resolution(registration, offering):
    """Runs immediately after payment. Returns True when the offering closed
    OPEN -> WAITLIST_ONLY as a consequence (a further version bump)."""
    closed = False
    if offering["confirmed_enrollment_count"] < offering["max_enrollment"]:
        registration["enrollment_status"] = "ENROLLED"
        registration["enrolled_at"] = now()
        offering["confirmed_enrollment_count"] += 1
        offering["paid_enrollment_count"] += 1
        if (offering["confirmed_enrollment_count"] == offering["max_enrollment"]
                and offering["status"] == "OPEN"):
            offering["status"] = "WAITLIST_ONLY"
            closed = True
    else:
        registration["enrollment_status"] = "WAITLISTED"
        offering["waitlist_count"] += 1
    learner = DB.learners[registration["learner_id"]]
    marketing_segment_recompute(learner)
    return closed


def seat_release(offering):
    """Waitlist promotion first; only failing that does WAITLIST_ONLY fall back
    to OPEN. Returns True when the offering reverted (extra version bump)."""
    if offering["confirmed_enrollment_count"] < offering["max_enrollment"]:
        candidates = [r for r in regs_of_offering(offering["id"])
                      if r["enrollment_status"] == "WAITLISTED"
                      and r["payment_status"] in ("PAID", "VOUCHER_COMMITTED")]
        if candidates:
            head = candidates[0]
            head["enrollment_status"] = "ENROLLED"
            head["enrolled_at"] = now()
            touch(head)
            offering["waitlist_count"] -= 1
            offering["confirmed_enrollment_count"] += 1
            offering["paid_enrollment_count"] += 1
            return False
    if (offering["status"] == "WAITLIST_ONLY"
            and offering["confirmed_enrollment_count"] < offering["max_enrollment"]):
        offering["status"] = "OPEN"
        return True
    return False


# ---------------------------------------------------------------------------
# Registration creation (shared by the create endpoint and transfer settle)
# ---------------------------------------------------------------------------

def create_registration(offering, learner):
    price = calc.registration_price_resolution(offering, learner)
    rec = base_record()
    rec.update({
        "offering_id": offering["id"],
        "learner_id": learner["id"],
        "voucher_id": None,
        "transferred_to_registration_id": None,
        "enrollment_status": "PENDING",
        "payment_status": "UNPAID",
        "list_tuition_cents": price["list_tuition_cents"],
        "loyalty_discount_cents": price["loyalty_discount_cents"],
        "processing_fee_cents": price["processing_fee_cents"],
        "total_due_cents": price["total_due_cents"],
        "amount_paid_cents": 0,
        "amount_refunded_cents": 0,
        "sessions_attended": 0,
        "total_sessions": offering["session_count"],
        "enrolled_at": None,
    })
    DB.registrations[rec["id"]] = rec
    return rec
