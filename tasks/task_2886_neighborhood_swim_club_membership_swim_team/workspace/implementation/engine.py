"""Derived fields, calculations and cascades.

Everything in this module is a faithful transcription of a PRD §3 narrative.
Cascades are executed depth-first and to completion inside the originating
request; every row a request actually changes advances its own version and
refreshes its own updated_at, and rows a cascade merely inspects do not
advance (PRD §2.4).
"""
from datetime import timedelta

import clock
import constants as C
from errors import fail
from money import (
    D,
    allocate_evenly,
    ceil_div,
    ceil_hours,
    duration_hours_2dp,
    round_half_up,
)
from store import DB, by_created


# ============================================================ lookup helpers
def need(kind, row_id):
    row = DB.get(kind, row_id)
    if row is None:
        from store import NOT_FOUND

        fail(NOT_FOUND[kind], "No such resource: %s" % row_id)
    return row


def rows_where(kind, **conditions):
    out = []
    for row in DB.all(kind):
        ok = True
        for key, value in conditions.items():
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out


def season_of_membership(membership):
    return DB.get("seasons", membership["season_id"])


def category_of_membership(membership):
    return DB.get("membership_categories", membership["membership_category_id"])


def household_of_membership(membership):
    return DB.get("households", membership["household_id"])


def memberships_of_household(household_id):
    return by_created(rows_where("memberships", household_id=household_id))


def registrations_of_membership(membership_id):
    return by_created(rows_where("swim_team_registrations", membership_id=membership_id))


def assignments_of_registration(registration_id):
    return by_created(
        rows_where("volunteer_assignments", swim_team_registration_id=registration_id)
    )


def assignments_of_meet(meet_id):
    return by_created(rows_where("volunteer_assignments", meet_id=meet_id))


def reservations_of_membership(membership_id):
    return by_created(rows_where("party_reservations", membership_id=membership_id))


def reservations_of_season(season_id):
    out = []
    for res in DB.all("party_reservations"):
        membership = DB.get("memberships", res["membership_id"])
        if membership is not None and membership["season_id"] == season_id:
            out.append(res)
    return out


def household_of_reservation(res):
    membership = DB.get("memberships", res["membership_id"])
    if membership is None:
        return None
    return DB.get("households", membership["household_id"])


def membership_of_registration(reg):
    return DB.get("memberships", reg["membership_id"])


def membership_of_assignment(assignment):
    reg = DB.get("swim_team_registrations", assignment["swim_team_registration_id"])
    if reg is None:
        return None
    return DB.get("memberships", reg["membership_id"])


# ================================================= lifeguard derived figures
def recompute_cert_flags(guard):
    """has_valid_lifeguard_cert / has_valid_cpr_cert, plus the INACTIVE -> ACTIVE
    return the moment a valid lifeguard certification exists again (PRD §3.8)."""
    certs = rows_where("certifications", lifeguard_id=guard["id"])
    has_lg = any(
        c["cert_type"] == "LIFEGUARD" and c["status"] == "VALID" for c in certs
    )
    has_cpr = any(
        c["cert_type"] == "CPR_AED" and c["status"] == "VALID" for c in certs
    )
    changed = False
    if guard["has_valid_lifeguard_cert"] != has_lg:
        guard["has_valid_lifeguard_cert"] = has_lg
        changed = True
    if guard["has_valid_cpr_cert"] != has_cpr:
        guard["has_valid_cpr_cert"] = has_cpr
        changed = True
    if has_lg and guard["employment_status"] == "INACTIVE":
        guard["employment_status"] = "ACTIVE"
        changed = True
    return changed


def recompute_scheduled_hours(guard):
    """The sum of duration_hours over shifts in SCHEDULED, CONFIRMED or
    COMPLETED (PRD §3.8)."""
    total = 0.0
    for shift in rows_where("guard_shifts", lifeguard_id=guard["id"]):
        if shift["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED"):
            total += float(shift["duration_hours"] or 0)
    total = round(total + 1e-9, 2)
    if guard["scheduled_hours"] != total:
        guard["scheduled_hours"] = total
        return True
    return False


def cert_wall_ok(lifeguard_id, end_iso):
    """The certification wall (PRD §3.8): a VALID LIFEGUARD and a VALID CPR_AED
    certification, each with expires_on at or after the date of the shift end."""
    end_dt = clock.parse_instant(end_iso)
    end_date = end_dt.date()
    certs = rows_where("certifications", lifeguard_id=lifeguard_id)

    def held(cert_type):
        for cert in certs:
            if cert["cert_type"] != cert_type or cert["status"] != "VALID":
                continue
            expires = clock.parse_date(cert["expires_on"])
            if expires is not None and expires >= end_date:
                return True
        return False

    return held("LIFEGUARD") and held("CPR_AED")


# ================================================ facility posture derivation
def open_findings(season_id):
    return [
        finding
        for finding in rows_where("inspection_findings", season_id=season_id)
        if finding["status"] in ("OPEN", "REMEDIATION_SUBMITTED", "REOPENED")
    ]


def derive_posture(season):
    """Facility posture is derived, never set by hand (PRD §3.1).

    Recomputed after every write to an inspection finding and on both
    season-lifecycle moves.  Returns True when the season row actually changed.
    """
    before = (
        season["open_critical_finding_count"],
        season["open_major_finding_count"],
        season["facility_posture"],
        season["closure_started_at"],
    )
    findings = open_findings(season["id"])
    critical = len([f for f in findings if f["severity"] == "CRITICAL"])
    major = len([f for f in findings if f["severity"] == "MAJOR"])
    season["open_critical_finding_count"] = critical
    season["open_major_finding_count"] = major

    previous_posture = season["facility_posture"]
    if season["status"] != "OPEN":
        posture = "CLOSED"
    elif critical >= 1:
        posture = "CLOSED"
    elif major >= C.MAJOR_FINDING_RESTRICT_THRESHOLD:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    season["facility_posture"] = posture

    if posture == "CLOSED" and previous_posture != "CLOSED":
        season["closure_started_at"] = clock.now_iso()
        closure_cascade(season)
    elif posture != "CLOSED":
        season["closure_started_at"] = None

    after = (
        season["open_critical_finding_count"],
        season["open_major_finding_count"],
        season["facility_posture"],
        season["closure_started_at"],
    )
    return before != after


def closure_cascade(season):
    """The two-hop closure cascade (PRD §3.1): every CONFIRMED reservation whose
    end_iso is still in the future is cancelled and refunded in full, then every
    SCHEDULED or CONFIRMED guard shift still in the future is cancelled."""
    now = clock.now()
    for res in by_created(reservations_of_season(season["id"])):
        if res["status"] != "CONFIRMED":
            continue
        if clock.parse_instant(res["end_iso"]) <= now:
            continue
        res["status"] = "CANCELLED_BY_CLOSURE"
        DB.touch(res)
        refund_reservation(res, res["total_charge_cents"], auto_apply=True)

    touched_guards = []
    for shift in by_created(rows_where("guard_shifts", season_id=season["id"])):
        if shift["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        if clock.parse_instant(shift["end_iso"]) <= now:
            continue
        shift["status"] = "CANCELLED_BY_CLOSURE"
        DB.touch(shift)
        guard = DB.get("lifeguards", shift["lifeguard_id"])
        if guard is not None and guard["id"] not in touched_guards:
            touched_guards.append(guard["id"])
    for guard_id in touched_guards:
        guard = DB.get("lifeguards", guard_id)
        if guard is not None and recompute_scheduled_hours(guard):
            DB.touch(guard)


# ================================================== the bather-load ratio §3.8
def staffing_ratio(season, at_dt, exclude_shift_ids=()):
    """Compliance is always evaluated at a single instant (PRD §3.8).

    Reservation windows are half-open [start, end); shift intervals are closed
    [start, end].  That asymmetry is deliberate.
    """
    overlapping = []
    for res in reservations_of_season(season["id"]):
        if res["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        start = clock.parse_instant(res["start_iso"])
        end = clock.parse_instant(res["end_iso"])
        if start <= at_dt < end:
            overlapping.append(res)
    bather_load = sum(r["guest_count"] + r["host_party_size"] for r in overlapping)
    ratio_guards = ceil_div(bather_load, C.GUARD_BATHER_RATIO)
    required = max(C.MIN_GUARDS_WHEN_OPEN, ratio_guards)
    if any(r["zone"] == "WHOLE_FACILITY" for r in overlapping):
        required += 1

    covering = set()
    for shift in rows_where("guard_shifts", season_id=season["id"]):
        if shift["id"] in exclude_shift_ids:
            continue
        if shift["status"] != "CONFIRMED" or not shift["counts_toward_ratio"]:
            continue
        start = clock.parse_instant(shift["start_iso"])
        end = clock.parse_instant(shift["end_iso"])
        if start <= at_dt <= end:
            covering.add(shift["lifeguard_id"])

    return {
        "season_id": season["id"],
        "at_iso": clock.iso(at_dt),
        "bather_load": bather_load,
        "required_guard_count": required,
        "scheduled_guard_count": len(covering),
        "compliant": len(covering) >= required,
    }


def ratio_compliant_over_window(season, start_iso, end_iso, exclude_shift_ids=()):
    """Two probes: at the window's start instant and at one minute before its
    end (PRD §3.7 confirmation rule)."""
    start = clock.parse_instant(start_iso)
    end = clock.parse_instant(end_iso) - timedelta(minutes=1)
    for probe in (start, end):
        if not staffing_ratio(season, probe, exclude_shift_ids)["compliant"]:
            return False
    return True


def cancellation_preserves_ratio(shift, season):
    """A cancellation that would strand a confirmed party without coverage is
    refused (PRD §3.8)."""
    shift_start = clock.parse_instant(shift["start_iso"])
    shift_end = clock.parse_instant(shift["end_iso"])
    for res in reservations_of_season(season["id"]):
        if res["status"] != "CONFIRMED":
            continue
        res_start = clock.parse_instant(res["start_iso"])
        res_end = clock.parse_instant(res["end_iso"])
        if not (res_start < shift_end and shift_start < res_end):
            continue
        probes = []
        for candidate in (res_start, res_end - timedelta(minutes=1)):
            probe = min(max(candidate, shift_start), shift_end)
            if res_start <= probe < res_end and probe not in probes:
                probes.append(probe)
        for probe in probes:
            verdict = staffing_ratio(season, probe, exclude_shift_ids=(shift["id"],))
            if not verdict["compliant"]:
                return False
    return True


# ============================================== membership derived money §3.4
def recompute_credits_required(membership):
    """category.volunteer_credits_required x count(CONFIRMED|COMPLETED regs),
    capped at ten credits (PRD §3.6)."""
    category = category_of_membership(membership)
    per = category["volunteer_credits_required"] if category else 0
    held = len(
        [
            r
            for r in registrations_of_membership(membership["id"])
            if r["status"] in ("CONFIRMED", "COMPLETED")
        ]
    )
    value = min(per * held, C.VOLUNTEER_CREDIT_CAP)
    if membership["volunteer_credits_required"] != value:
        membership["volunteer_credits_required"] = value
        return True
    return False


def recompute_credits_earned(membership):
    """Sum of credit_value over COMPLETED assignments beneath the membership,
    capped at ten before any shortfall is taken (PRD §3.6)."""
    total = 0
    for reg in registrations_of_membership(membership["id"]):
        for assignment in assignments_of_registration(reg["id"]):
            if assignment["status"] == "COMPLETED":
                total += assignment["credit_value"]
    value = min(total, C.VOLUNTEER_CREDIT_CAP)
    if membership["volunteer_credits_earned"] != value:
        membership["volunteer_credits_earned"] = value
        return True
    return False


def recompute_swim_fee(membership):
    """Line 4 of the invoice: the sum of the already-rounded per-swimmer
    assessed_fee_cents over PENDING, CONFIRMED and COMPLETED registrations."""
    total = 0
    for reg in registrations_of_membership(membership["id"]):
        if reg["status"] in ("PENDING", "CONFIRMED", "COMPLETED"):
            total += reg["assessed_fee_cents"]
    if membership["swim_team_fee_cents"] != total:
        membership["swim_team_fee_cents"] = total
        return True
    return False


def buyout_for(membership):
    shortfall = membership["volunteer_credits_required"] - membership["volunteer_credits_earned"]
    if shortfall < 0:
        shortfall = 0
    return shortfall * C.VOLUNTEER_BUYOUT_PER_CREDIT_CENTS


def book_reserve_contribution(membership):
    """Five thousand cents booked onto the season the first time a membership
    reaches PAID — exactly once per membership (PRD §3.4, §3.10)."""
    if membership.get("_reserve_booked"):
        return
    season = season_of_membership(membership)
    if season is None:
        return
    membership["_reserve_booked"] = True
    amount = C.RESERVE_CONTRIBUTION_PER_MEMBERSHIP_CENTS
    season["reserve_contributions_cents"] += amount
    season["reserve_unallocated_cents"] += amount
    DB.touch(season)


def settle_to_paid(membership):
    """The shared side effects of INVOICED -> PAID and DELINQUENT -> PAID."""
    membership["dues_status"] = "PAID"
    book_reserve_contribution(membership)


def apply_account_credit(household, season_id):
    """The all-or-nothing auto-apply rule of PRD §3.4."""
    if household["account_credit_cents"] <= 0:
        return
    for membership in memberships_of_household(household["id"]):
        if membership["season_id"] != season_id:
            continue
        if membership["dues_status"] not in ("INVOICED", "DELINQUENT"):
            continue
        balance = membership["balance_due_cents"]
        if household["account_credit_cents"] >= balance:
            membership["amount_paid_cents"] += balance
            membership["balance_due_cents"] = 0
            household["account_credit_cents"] -= balance
            settle_to_paid(membership)
            DB.touch(membership)
            DB.touch(household)
        return


def refund_reservation(res, amount, auto_apply):
    """Every refund moves the same pair of household counters (PRD §3.7).

    The reservation row itself is versioned by the caller, which owns the status
    change; this helper only stamps refunded_cents and moves the household.
    """
    res["refunded_cents"] = amount
    household = household_of_reservation(res)
    if household is None:
        return
    household["party_charges_owed_cents"] -= amount
    household["account_credit_cents"] += amount
    DB.touch(household)
    if auto_apply:
        membership = DB.get("memberships", res["membership_id"])
        if membership is not None:
            apply_account_credit(household, membership["season_id"])


# ============================================ swim team / meets cascades §3.6
def squad_count(season_id, squad):
    return len(
        [
            r
            for r in DB.all("swim_team_registrations")
            if r["season_id"] == season_id
            and r["squad"] == squad
            and r["status"] in ("PENDING", "CONFIRMED", "COMPLETED")
        ]
    )


def promote_from_waitlist(season_id, squad):
    """The freed slot promotes the earliest WAITLISTED sibling back to PENDING,
    and only while the squad count is strictly below capacity (PRD §3.6)."""
    capacity = C.SQUAD_CAPACITY.get(squad, 0)
    if squad_count(season_id, squad) >= capacity:
        return
    candidates = [
        r
        for r in DB.all("swim_team_registrations")
        if r["season_id"] == season_id
        and r["squad"] == squad
        and r["status"] == "WAITLISTED"
    ]
    if not candidates:
        return
    winner = by_created(candidates)[0]
    winner["status"] = "PENDING"
    DB.touch(winner)
    membership = membership_of_registration(winner)
    if membership is not None:
        changed = recompute_credits_required(membership)
        changed = recompute_swim_fee(membership) or changed
        if changed:
            DB.touch(membership)


def recompute_meet_filled(meet):
    """volunteer_slots_filled counts credits over ASSIGNED and COMPLETED
    assignments; a STAFFED meet slides back to UNDERSTAFFED (PRD §3.6)."""
    filled = 0
    for assignment in assignments_of_meet(meet["id"]):
        if assignment["status"] in ("ASSIGNED", "COMPLETED"):
            filled += assignment["credit_value"]
    changed = False
    if meet["volunteer_slots_filled"] != filled:
        meet["volunteer_slots_filled"] = filled
        changed = True
    if meet["status"] == "STAFFED" and filled < meet["volunteer_slots_required"]:
        meet["status"] = "UNDERSTAFFED"
        meet["understaffed_penalty_cents"] = (
            meet["volunteer_slots_required"] - filled
        ) * C.MEET_UNDERSTAFF_PENALTY_CENTS
        changed = True
    if changed:
        DB.touch(meet)
    return changed


def release_assignments_of(reg):
    """Withdrawal and revocation release every assignment still in ASSIGNED."""
    for assignment in assignments_of_registration(reg["id"]):
        if assignment["status"] != "ASSIGNED":
            continue
        assignment["status"] = "RELEASED"
        DB.touch(assignment)
        meet = DB.get("meets", assignment["meet_id"])
        if meet is not None:
            recompute_meet_filled(meet)


def revoke_registration(reg):
    """REVOKED is reached only by the suspension cascade and behaves like
    withdrawal in every respect (PRD §3.6)."""
    was = reg["status"]
    reg["status"] = "REVOKED"
    DB.touch(reg)
    release_assignments_of(reg)
    membership = membership_of_registration(reg)
    if membership is not None:
        changed = recompute_credits_required(membership)
        changed = recompute_swim_fee(membership) or changed
        if changed:
            DB.touch(membership)
    if was in ("PENDING", "CONFIRMED"):
        promote_from_waitlist(reg["season_id"], reg["squad"])


# ================================================ conduct and standing §3.9
def recompute_conduct_points(household):
    """Recomputed from scratch over a 730-day inclusive lookback (PRD §3.9)."""
    cutoff = clock.now() - timedelta(days=C.CONDUCT_LOOKBACK_DAYS)
    total = 0
    for case in rows_where("conduct_cases", household_id=household["id"]):
        if case["status"] not in ("SANCTIONED", "CLOSED"):
            continue
        if not case["sanctioned_at"]:
            continue
        if clock.parse_instant(case["sanctioned_at"]) >= cutoff:
            total += case["points_assessed"]
    if household["conduct_points"] != total:
        household["conduct_points"] = total
        return True
    return False


def standing_from_points(points):
    if points >= C.CONDUCT_EXPULSION_THRESHOLD:
        return "EXPELLED"
    if points >= C.CONDUCT_SUSPENSION_THRESHOLD:
        return "SUSPENDED"
    return "GOOD_STANDING"


def harden_standing(household, sanction_type):
    """Three candidates, most severe wins; the pipeline can only harden."""
    candidates = [
        C.SANCTION_TO_STANDING[sanction_type],
        standing_from_points(household["conduct_points"]),
        household["standing"],
    ]
    return max(candidates, key=lambda s: C.STANDING_RANK[s])


def membership_suspension_effects(membership):
    """Registrations revoked in created_at order, then future reservations
    cancelled in start_iso then created_at order (PRD §3.9)."""
    for reg in registrations_of_membership(membership["id"]):
        if reg["status"] in ("PENDING", "CONFIRMED", "WAITLISTED"):
            revoke_registration(reg)

    now = clock.now()
    doomed = [
        res
        for res in reservations_of_membership(membership["id"])
        if res["status"] in ("REQUESTED", "CONFIRMED")
        and clock.parse_instant(res["start_iso"]) > now
    ]
    doomed.sort(key=lambda r: (r["start_iso"], r["created_at"], r["_seq"]))
    for res in doomed:
        res["status"] = "CANCELLED_BY_SUSPENSION"
        DB.touch(res)
        refund = round_half_up(
            D(res["total_charge_cents"]) * C.PARTY_HALF_REFUND_RATE
        )
        refund_reservation(res, refund, auto_apply=False)


def suspend_household_cascade(household):
    for membership in memberships_of_household(household["id"]):
        if membership["access_status"] != "ACTIVE":
            continue
        membership["access_status"] = "SUSPENDED"
        DB.touch(membership)
        membership_suspension_effects(membership)


def expel_household_cascade(household):
    """Every ACTIVE or SUSPENDED membership terminates; an ACTIVE one runs the
    full suspension cascade on the way through (PRD §3.9)."""
    for membership in memberships_of_household(household["id"]):
        if membership["access_status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        was_active = membership["access_status"] == "ACTIVE"
        membership["access_status"] = "TERMINATED"
        DB.touch(membership)
        if was_active:
            membership_suspension_effects(membership)

    for entry in by_created(rows_where("waitlist_entries", household_id=household["id"])):
        if entry["status"] in ("WAITING", "OFFERED"):
            entry["status"] = "WITHDRAWN"
            DB.touch(entry)


def apply_standing(household, new_standing):
    """Move a household's standing and fire whatever cascade the move implies."""
    old = household["standing"]
    if new_standing == old:
        return False
    household["standing"] = new_standing
    if new_standing == "SUSPENDED":
        suspend_household_cascade(household)
    elif new_standing == "EXPELLED":
        expel_household_cascade(household)
    return True


# ============================================== fiscal gate helpers §3.2/§3.4
def household_is_delinquent(household, season_id):
    """Delinquency is contagious (PRD §3.4): any DELINQUENT or WRITTEN_OFF
    membership in the season, or any outstanding household charge at all."""
    for membership in memberships_of_household(household["id"]):
        if membership["season_id"] != season_id:
            continue
        if membership["dues_status"] in ("DELINQUENT", "WRITTEN_OFF"):
            return True
    owed = household["guest_fee_owed_cents"] + household["party_charges_owed_cents"]
    return owed > C.DELINQUENCY_TOLERANCE_CENTS


def latest_category_of_household(household):
    """The category of this household's membership, most recent first."""
    memberships = memberships_of_household(household["id"])
    if not memberships:
        return None
    return category_of_membership(memberships[-1])


def bond_is_settled(household, category):
    if household["bond_status"] in ("PAID", "TRANSFERRED"):
        return True
    if category is None:
        return False
    return household["bond_paid_cents"] >= category["bond_cents"]


# ================================================== dues assessment §3.3
def assess_dues(category, season, join_date):
    dues = category["seasonal_dues_cents"]
    if not category["proration_allowed"]:
        return dues
    open_date = clock.parse_date(season["open_date"])
    close_date = clock.parse_date(season["close_date"])
    total_days = (close_date - open_date).days + 1
    total_weeks = ceil_div(total_days, C.DAYS_PER_SWIM_WEEK)
    effective_start = join_date if join_date > open_date else open_date
    remaining_days = (close_date - effective_start).days + 1
    if remaining_days <= 0:
        return 0
    if effective_start <= open_date:
        return dues
    if season["proration_basis"] == "CALENDAR_DAY":
        return round_half_up(D(dues) * D(remaining_days) / D(total_days))
    remaining_weeks = ceil_div(remaining_days, C.DAYS_PER_SWIM_WEEK)
    if total_weeks == 0:
        return dues
    return round_half_up(D(dues) * D(remaining_weeks) / D(total_weeks))


# ============================================ swim-team fee and squad seq §3.6
def squad_seq_for(membership_id, swimmer_birthdate):
    """1-based rank within the membership, by birthdate then created_at."""
    rank = 1
    for reg in registrations_of_membership(membership_id):
        if reg["status"] not in ("PENDING", "CONFIRMED", "WAITLISTED", "COMPLETED"):
            continue
        if reg["swimmer_birthdate"] <= swimmer_birthdate:
            rank += 1
    return rank


def swim_fee_for_seq(squad_seq):
    rate = C.MULTI_SWIMMER_DISCOUNT_RATE * D(squad_seq - 1)
    if rate > C.MULTI_SWIMMER_DISCOUNT_CAP:
        rate = C.MULTI_SWIMMER_DISCOUNT_CAP
    return round_half_up(D(C.SWIM_TEAM_FEE_CENTS) * (D(1) - rate))


# ==================================================== party pricing §3.7
def zones_conflict(zone_a, zone_b):
    if zone_a == "WHOLE_FACILITY" or zone_b == "WHOLE_FACILITY":
        return True
    return zone_a == zone_b


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open intervals: parties that merely abut do not overlap."""
    return a_start < b_end and b_start < a_end


def price_party(zone, guest_count, host_party_size, start_dt, end_dt):
    """The nine pricing steps of PRD §3.7, in exactly that sequence."""
    load = guest_count + host_party_size
    guards = max(C.MIN_GUARDS_WHEN_OPEN, ceil_div(load, C.GUARD_BATHER_RATIO))
    if zone == "WHOLE_FACILITY":
        guards += 1
    hours = ceil_hours(start_dt, end_dt)
    surcharge = guards * hours * C.GUARD_HOURLY_CENTS
    base = C.ZONE_BASE_FEE_CENTS[zone]
    overage = 0
    if guest_count > C.INCLUDED_GUESTS:
        overage = (guest_count - C.INCLUDED_GUESTS) * C.GUEST_OVERAGE_CENTS
    subtotal = base + overage + surcharge
    if subtotal >= C.DISCOUNT_TIER_2_CENTS:
        rate = C.DISCOUNT_RATE_TIER_2
    elif subtotal >= C.DISCOUNT_TIER_1_CENTS:
        rate = C.DISCOUNT_RATE_TIER_1
    else:
        rate = D(0)
    discount = round_half_up(D(subtotal) * rate)
    return {
        "projected_bather_load": load,
        "required_guard_count": guards,
        "duration_hours_ceil": hours,
        "lifeguard_surcharge_cents": surcharge,
        "base_facility_fee_cents": base,
        "guest_overage_fee_cents": overage,
        "subtotal_cents": subtotal,
        "member_discount_cents": discount,
        "total_charge_cents": subtotal - discount,
    }


# ==================================================== waitlist selector §3.2
def select_offer_candidate(category_id):
    """The queue's total order: lowest priority_tier_rank, then earliest
    queue_key_at, then earliest created_at as the final tie-break."""
    candidates = []
    for entry in DB.all("waitlist_entries"):
        if entry["membership_category_id"] != category_id:
            continue
        if entry["status"] != "WAITING":
            continue
        household = DB.get("households", entry["household_id"])
        if household is None or household["standing"] != "GOOD_STANDING":
            continue
        candidates.append(entry)
    if not candidates:
        return None
    candidates.sort(
        key=lambda e: (
            e["priority_tier_rank"],
            e["queue_key_at"],
            e["created_at"],
            e["_seq"],
        )
    )
    return candidates[0]


def make_offer(entry):
    now = clock.now()
    entry["status"] = "OFFERED"
    entry["offered_at"] = clock.iso(now)
    entry["offer_expires_at"] = clock.iso(now + timedelta(days=C.OFFER_WINDOW_DAYS))
    DB.touch(entry)
    return entry


# =============================================== certification consequences
def apply_cert_change(guard, cert_type):
    """Recompute both flags, then apply the last-lifeguard-certification rule
    that drives a guard ACTIVE -> INACTIVE (PRD §3.8)."""
    changed = recompute_cert_flags(guard)
    if (
        cert_type == "LIFEGUARD"
        and not guard["has_valid_lifeguard_cert"]
        and guard["employment_status"] == "ACTIVE"
    ):
        guard["employment_status"] = "INACTIVE"
        changed = True
    return changed
