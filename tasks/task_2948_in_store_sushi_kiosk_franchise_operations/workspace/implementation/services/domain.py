"""Domain services: navigation, derived aggregates, postures and cascades.

PRD 2.10 -- cascade discipline (the four-link chain).
PRD 3.1 to 3.9 -- the workflows.
"""

from decimal import Decimal

import db
from core import (dec, logical_now_iso, parse_instant, round_half_up,
                  whole_minutes_between)
from middleware import current_user_id
from services import calc

# ==========================================================================
# Navigation helpers
# ==========================================================================


def agreement_of(kiosk):
    return db.license_agreements.get(kiosk["license_agreement_id"])


def store_of_agreement(agreement):
    return db.host_stores.get(agreement["host_store_id"])


def store_of_kiosk(kiosk):
    agreement = agreement_of(kiosk)
    if agreement is None:
        return None
    return store_of_agreement(agreement)


def kiosk_of_plan(plan):
    return db.kiosks.get(plan["kiosk_id"])


def plan_of_batch(batch):
    return db.production_plans.get(batch["production_plan_id"])


def kiosk_of_batch(batch):
    plan = plan_of_batch(batch)
    if plan is None:
        return None
    return kiosk_of_plan(plan)


def batch_of_pack_lot(lot):
    return db.rice_batches.get(lot["rice_batch_id"])


def plan_of_pack_lot(lot):
    batch = batch_of_pack_lot(lot)
    if batch is None:
        return None
    return plan_of_batch(batch)


def kiosk_of_pack_lot(lot):
    plan = plan_of_pack_lot(lot)
    if plan is None:
        return None
    return kiosk_of_plan(plan)


def agreement_of_pack_lot(lot):
    kiosk = kiosk_of_pack_lot(lot)
    if kiosk is None:
        return None
    return agreement_of(kiosk)


def plans_of_kiosk(kiosk_id):
    return db.ordered([p for p in db.production_plans.values()
                       if p["kiosk_id"] == kiosk_id])


def batches_of_plan(plan_id):
    return db.ordered([b for b in db.rice_batches.values()
                       if b["production_plan_id"] == plan_id])


def batches_of_kiosk(kiosk_id):
    out = []
    for batch in db.rice_batches.values():
        plan = plan_of_batch(batch)
        if plan is not None and plan["kiosk_id"] == kiosk_id:
            out.append(batch)
    return db.ordered(out)


def pack_lots_of_batch(batch_id):
    return db.ordered([l for l in db.pack_lots.values()
                       if l["rice_batch_id"] == batch_id])


def pack_lots_of_fish_lot(fish_lot_id):
    return db.ordered([l for l in db.pack_lots.values()
                       if l["fish_lot_id"] == fish_lot_id])


def pack_lots_of_kiosk(kiosk_id):
    out = []
    for lot in db.pack_lots.values():
        kiosk = kiosk_of_pack_lot(lot)
        if kiosk is not None and kiosk["id"] == kiosk_id:
            out.append(lot)
    return db.ordered(out)


def kiosks_of_agreement(agreement_id):
    return db.ordered([k for k in db.kiosks.values()
                       if k["license_agreement_id"] == agreement_id])


def audits_of_kiosk(kiosk_id):
    return db.ordered([a for a in db.food_safety_audits.values()
                       if a["kiosk_id"] == kiosk_id])


def findings_of_audit(audit_id):
    return db.ordered([f for f in db.audit_findings.values()
                       if f["audit_id"] == audit_id])


def findings_of_kiosk(kiosk_id):
    out = []
    for finding in db.audit_findings.values():
        audit = db.food_safety_audits.get(finding["audit_id"])
        if audit is not None and audit["kiosk_id"] == kiosk_id:
            out.append(finding)
    return out


# A finding's risk points join the kiosk's risk inputs at submit (PRD 3.9), so
# findings entered against a still-open audit do not yet weigh on the kiosk.
SUBMITTED_AUDIT_STATES = ("CORRECTIVE_ACTION_PENDING", "REVERIFICATION",
                          "CLOSED", "ESCALATED_CLOSURE")


def scored_findings_of_kiosk(kiosk_id):
    out = []
    for finding in db.audit_findings.values():
        audit = db.food_safety_audits.get(finding["audit_id"])
        if (audit is not None and audit["kiosk_id"] == kiosk_id
                and audit["status"] in SUBMITTED_AUDIT_STATES):
            out.append(finding)
    return out


def certifications_of_chef(chef_id):
    return db.ordered([c for c in db.certifications.values()
                       if c["chef_id"] == chef_id])


def readings_of_fish_lot(fish_lot_id):
    return db.ordered([r for r in db.cold_chain_readings.values()
                       if r["fish_lot_id"] == fish_lot_id])


LIVE_PACK_STATES = ("ON_SHELF", "MARKED_DOWN")
COUNTED_PACK_STATES = ("ON_SHELF", "MARKED_DOWN", "SOLD_OUT")


def live_packs_of_plan(plan_id):
    total = 0
    for lot in db.pack_lots.values():
        if lot["status"] not in LIVE_PACK_STATES:
            continue
        batch = batch_of_pack_lot(lot)
        if batch is not None and batch["production_plan_id"] == plan_id:
            total += lot["pack_count"]
    return total


def live_packs_of_kiosk(kiosk_id):
    total = 0
    for lot in pack_lots_of_kiosk(kiosk_id):
        if lot["status"] in LIVE_PACK_STATES:
            total += lot["pack_count"]
    return total


def live_packs_of_store(host_store_id):
    total = 0
    for lot in db.pack_lots.values():
        if lot["status"] not in LIVE_PACK_STATES:
            continue
        kiosk = kiosk_of_pack_lot(lot)
        if kiosk is None:
            continue
        agreement = agreement_of(kiosk)
        if agreement is not None and agreement["host_store_id"] == host_store_id:
            total += lot["pack_count"]
    return total


# ==========================================================================
# Chef derived state (PRD 3.2)
# ==========================================================================


def refresh_chef(chef):
    """Recompute valid_cert_count, both expiry fields and certification readiness."""
    certs = certifications_of_chef(chef["id"])
    valid = [c for c in certs if c["status"] == "VALID"]
    food_handler = [c["expires_at"] for c in valid if c["cert_type"] == "FOOD_HANDLER"]
    haccp = [c["expires_at"] for c in valid
             if c["cert_type"] == "HACCP_RICE_ACIDIFICATION"]
    fh_expiry = max(food_handler) if food_handler else None
    haccp_expiry = max(haccp) if haccp else None

    now = logical_now_iso()
    hours = dec(chef["training_hours_logged"])
    ready = (hours >= calc.MIN_TRAINING_HOURS
             and fh_expiry is not None and fh_expiry > now
             and haccp_expiry is not None and haccp_expiry > now)

    previous = chef["status"]
    if ready:
        status = "CERTIFIED"
    elif previous == "CERTIFIED":
        # Losing a mandatory certification is the one path out of CERTIFIED and
        # it does not walk back down the training ladder.
        status = "SUSPENDED"
    elif previous == "SUSPENDED":
        status = "SUSPENDED"
    elif hours > 0:
        status = "TRAINEE"
    else:
        status = "CANDIDATE"

    db.apply_changes(chef, {
        "status": status,
        "valid_cert_count": len(valid),
        "food_handler_cert_expires_at": fh_expiry,
        "haccp_cert_expires_at": haccp_expiry,
    })

    if chef["assigned_kiosk_id"]:
        kiosk = db.kiosks.get(chef["assigned_kiosk_id"])
        if kiosk is not None:
            refresh_certified_chef_count(kiosk)
            rederive_kiosk(kiosk)
    return chef


def refresh_certified_chef_count(kiosk):
    count = 0
    for chef in db.chefs.values():
        if chef["assigned_kiosk_id"] == kiosk["id"] and chef["status"] == "CERTIFIED":
            count += 1
    db.apply_changes(kiosk, {"certified_chef_count": count})
    return count


# ==========================================================================
# Kiosk risk and sanitation posture (PRD 3.3)
# ==========================================================================


def risk_breakdown(kiosk):
    minor = major = critical = 0
    for finding in scored_findings_of_kiosk(kiosk["id"]):
        if finding["status"] not in ("OPEN", "CORRECTED"):
            continue
        if finding["severity"] == "MINOR":
            minor += 1
        elif finding["severity"] == "MAJOR":
            major += 1
        else:
            critical += 1
    unresolved_critical = unresolved_critical_findings(kiosk["id"])

    variance_count = 0
    for batch in batches_of_kiosk(kiosk["id"]):
        if batch["status"] == "VARIANCE_APPROVED":
            variance_count += 1
        elif batch["status"] == "CONSUMED" and batch.get("_variance_approved"):
            variance_count += 1

    quarantined = 0
    for lot in db.fish_lots.values():
        if (lot["kiosk_id"] == kiosk["id"] and lot["status"] == "QUARANTINED"
                and lot["quarantine_reason"] == "COLD_CHAIN_BREACH"):
            quarantined += 1

    credit = calc.CLEAN_AUDIT_CREDIT_PER_AUDIT * int(kiosk["consecutive_clean_audits"])
    raw = (minor * calc.FINDING_RISK_POINTS["MINOR"]
           + major * calc.FINDING_RISK_POINTS["MAJOR"]
           + critical * calc.FINDING_RISK_POINTS["CRITICAL"]
           + variance_count * calc.VARIANCE_RISK_POINTS
           + quarantined * calc.QUARANTINE_RISK_POINTS
           - credit)
    clamped = calc.clamp_risk(raw)
    return {
        "kiosk_id": kiosk["id"],
        "minor_open": minor,
        "major_open": major,
        "critical_open": critical,
        "approved_variance_count": variance_count,
        "quarantined_lot_count": quarantined,
        "clean_audit_credit": credit,
        "raw_risk_points": raw,
        "risk_points": clamped,
        "unresolved_critical_count": unresolved_critical,
    }


def unresolved_critical_findings(kiosk_id):
    """open_critical_finding_count: CRITICAL findings still OPEN or CORRECTED.

    A CORRECTED critical still counts, because PRD 3.9 only decrements the
    count when a reverification actually passes.
    """
    count = 0
    for finding in findings_of_kiosk(kiosk_id):
        if finding["severity"] == "CRITICAL" \
                and finding["status"] in ("OPEN", "CORRECTED"):
            count += 1
    return count


_lockdown_guard = set()


def rederive_kiosk(kiosk, force_lockdown=False):
    """Recompute risk_points / open_critical_finding_count and re-derive posture.

    Entering LOCKDOWN voids the kiosk's DRAFT and RELEASED plans (PRD 3.3).
    """
    breakdown = risk_breakdown(kiosk)
    previous = kiosk["sanitation_posture"]
    posture = "LOCKDOWN" if force_lockdown else calc.posture_band(
        breakdown["risk_points"], breakdown["unresolved_critical_count"])
    db.apply_changes(kiosk, {
        "risk_points": breakdown["risk_points"],
        "open_critical_finding_count": breakdown["unresolved_critical_count"],
        "sanitation_posture": posture,
    })

    if posture == "LOCKDOWN" and previous != "LOCKDOWN" \
            and kiosk["id"] not in _lockdown_guard:
        _lockdown_guard.add(kiosk["id"])
        try:
            for plan in plans_of_kiosk(kiosk["id"]):
                if plan["status"] in ("DRAFT", "RELEASED"):
                    void_plan(plan, "POSTURE_LOCKDOWN")
        finally:
            _lockdown_guard.discard(kiosk["id"])
        breakdown = risk_breakdown(kiosk)
        posture = "LOCKDOWN" if force_lockdown else calc.posture_band(
            breakdown["risk_points"], breakdown["unresolved_critical_count"])
        db.apply_changes(kiosk, {
            "risk_points": breakdown["risk_points"],
            "open_critical_finding_count":
                breakdown["unresolved_critical_count"],
            "sanitation_posture": posture,
        })
    return kiosk


def refresh_open_critical_count(kiosk):
    """Recount unresolved CRITICAL findings without re-deriving the posture.

    Appending a finding is not one of the posture-re-derivation triggers of
    PRD 3.3, but the count itself is a live derived field.
    """
    count = unresolved_critical_findings(kiosk["id"])
    db.apply_changes(kiosk, {"open_critical_finding_count": count})
    return count


def refresh_active_kiosk_count(agreement):
    count = 0
    for kiosk in db.kiosks.values():
        if kiosk["license_agreement_id"] == agreement["id"] \
                and kiosk["operational_state"] == "OPERATING":
            count += 1
    db.apply_changes(agreement, {"active_kiosk_count": count})
    return count


# ==========================================================================
# Space obligation compliance (PRD 3.1)
# ==========================================================================


def space_derivation(store):
    """Returns (space_compliance_state, {agreement_id: space_shortfall_sqft})."""
    attested_sqft = store["attested_sushi_space_sqft"]
    if attested_sqft is None:
        attested_sqft = store["sushi_space_sqft"]
    active = [a for a in db.license_agreements.values()
              if a["host_store_id"] == store["id"] and a["status"] == "ACTIVE"]
    shortfalls = {}
    for agreement in active:
        shortfalls[agreement["id"]] = calc.space_shortfall(
            agreement["min_space_sqft_obligation"], attested_sqft)

    if store["last_attested_on"] is None:
        return "UNVERIFIED", shortfalls

    frontage = store["attested_case_linear_ft"]
    frontage = dec(frontage) if frontage is not None else Decimal("0")
    compliant = True
    for agreement in active:
        if shortfalls[agreement["id"]] != 0:
            compliant = False
            break
        if frontage < dec(agreement["min_case_linear_ft_obligation"]):
            compliant = False
            break
    return ("COMPLIANT" if compliant else "DEFICIENT"), shortfalls


def apply_space_derivation(store, skip_agreement_id=None):
    """Write the derivation back to the store and to each active agreement."""
    state, shortfalls = space_derivation(store)
    for agreement_id, shortfall in shortfalls.items():
        if agreement_id == skip_agreement_id:
            continue
        agreement = db.license_agreements.get(agreement_id)
        if agreement is not None:
            db.apply_changes(agreement, {"space_shortfall_sqft": shortfall})
    return state, shortfalls


# ==========================================================================
# Plan aggregates (PRD 3.4)
# ==========================================================================


def refresh_plan_actual(plan):
    """actual_pack_count: sum of pack_count over the plan's lots that are
    ON_SHELF, MARKED_DOWN or SOLD_OUT -- DISCARDED and VOIDED excluded.
    Maintained live; forecast_variance_pct stays null until reconciliation."""
    total = 0
    for batch in batches_of_plan(plan["id"]):
        for lot in pack_lots_of_batch(batch["id"]):
            if lot["status"] in COUNTED_PACK_STATES:
                total += lot["pack_count"]
    db.apply_changes(plan, {"actual_pack_count": total})
    return plan


# ==========================================================================
# Fish lot mass conservation and cold chain (PRD 3.6)
# ==========================================================================


def refresh_fish_mass(lot):
    """allocated_kg / remaining_kg from the lot's non-voided pack lots."""
    if lot["status"] == "DESTROYED":
        return lot
    allocated = Decimal("0")
    for pack in pack_lots_of_fish_lot(lot["id"]):
        if pack["status"] == "VOIDED":
            continue
        allocated += dec(pack["consumed_fish_kg"] or 0)
    allocated = round_half_up(allocated, 3)
    remaining = round_half_up(dec(lot["net_weight_kg"]) - allocated, 3)
    changes = {
        "allocated_kg": float(allocated),
        "remaining_kg": float(remaining),
    }
    if lot["status"] == "RELEASED" and remaining <= Decimal("0"):
        changes["status"] = "CONSUMED"
    elif lot["status"] == "CONSUMED" and remaining > Decimal("0"):
        changes["status"] = "RELEASED"
    db.apply_changes(lot, changes)
    return lot


def recompute_cold_chain(lot):
    """Re-derive the whole reading series and the lot's breach total.

    PRD 3.6: "Readings are processed in `recorded_at` ascending order with ties
    broken by `created_at` ascending, and the lot's own `received_at` with
    `receiving_temp_c` is the origin of the series", and "For each consecutive
    pair of points the system computes the gap in whole minutes". The receiving
    point is a point of the series -- "That receiving temperature is not merely
    descriptive: together with `received_at` it is the implicit first point of the
    lot's cold-chain series" -- so the (origin, earliest reading) interval is
    attributed to that earliest reading, while its
    `interval_minutes_from_previous` stays null because there is no previous
    *reading*. Per-interval attribution is rounded to a whole minute before the
    intervals are summed (PRD 3.6), so the series is replayed in recorded_at
    order.
    """
    readings = sorted(readings_of_fish_lot(lot["id"]),
                      key=lambda r: (r["recorded_at"], r["created_at"], r["id"]))
    total = 0
    previous_at = parse_instant(lot["received_at"])
    previous_temp = lot["receiving_temp_c"]
    first = True
    for reading in readings:
        current_at = parse_instant(reading["recorded_at"])
        gap = whole_minutes_between(previous_at, current_at)
        attributed = calc.interval_breach_minutes(gap, previous_temp,
                                                  reading["temp_c"])
        total += attributed
        reading["interval_minutes_from_previous"] = None if first else gap
        reading["breach_minutes_attributed"] = attributed
        reading["lot_breach_minutes_after"] = total
        previous_at = current_at
        previous_temp = reading["temp_c"]
        first = False
    return total


# ==========================================================================
# Pack lot discard (PRD 3.7)
# ==========================================================================


def discard_pack_lot(lot, reason, recorded_by=None):
    """Discard every unsold pack in the lot and write the append-only event."""
    if recorded_by is None:
        recorded_by = current_user_id()
    count = int(lot["unsold_count"])
    if lot["status"] == "MARKED_DOWN" and lot["markdown_price_cents"] is not None:
        unit_value = lot["markdown_price_cents"]
    else:
        unit_value = lot["list_price_cents"]
    valuation = calc.discard_valuation(count, unit_value, reason)

    event = db.new_row(db.discard_events, {
        "pack_lot_id": lot["id"],
        "reason": reason,
        "discarded_count": valuation["discarded_count"],
        "unit_value_cents": valuation["unit_value_cents"],
        "discard_value_cents": valuation["discard_value_cents"],
        "settlement_credit_eligible": valuation["settlement_credit_eligible"],
        "recorded_by_user_id": recorded_by,
    }, versioned=False)

    lot["status"] = "DISCARDED"
    lot["discarded_count"] = count
    lot["unsold_count"] = 0
    db.touch(lot)

    plan = plan_of_pack_lot(lot)
    if plan is not None:
        refresh_plan_actual(plan)
    cascade_discard_into_drafts(lot, event)
    return event


def void_pack_lot(lot, reason):
    """Void a pack lot and return its fish mass to the source lot.

    The decomposition is left untouched: PRD 3.7 -- "Throughout every one of these
    paths the conservation invariant holds without exception: `pack_count` always
    equals `sold_count` plus `discarded_count` plus `unsold_count`." A void is
    only reachable while `sold_count` is zero and it discards nothing, so every
    pack of the lot stays counted as unsold.
    """
    lot["status"] = "VOIDED"
    lot["void_reason"] = reason
    db.touch(lot)
    fish = db.fish_lots.get(lot["fish_lot_id"])
    if fish is not None:
        refresh_fish_mass(fish)
    plan = plan_of_pack_lot(lot)
    if plan is not None:
        refresh_plan_actual(plan)
    return lot


# ==========================================================================
# Plan void -- the four-link cascade (PRD 2.10 / 3.4)
# ==========================================================================


def void_plan(plan, void_reason, recorded_by=None):
    """plan -> rice batches -> pack lots -> discard events."""
    if recorded_by is None:
        recorded_by = current_user_id()
    plan["status"] = "VOIDED"
    plan["void_reason"] = void_reason
    db.touch(plan)

    batches = batches_of_plan(plan["id"])
    for batch in batches:
        if batch["status"] not in ("REJECTED", "CONSUMED"):
            batch["status"] = "REJECTED"
            batch["rejection_reason"] = "PLAN_VOIDED"
            db.touch(batch)
    for batch in batches:
        for lot in pack_lots_of_batch(batch["id"]):
            if lot["status"] in LIVE_PACK_STATES:
                discard_pack_lot(lot, "AUDIT_LOCKDOWN", recorded_by)
    refresh_plan_actual(plan)
    return plan


def void_kiosk_plans(kiosk, reason, statuses=("DRAFT", "RELEASED", "LOCKED"),
                     recorded_by=None):
    for plan in plans_of_kiosk(kiosk["id"]):
        if plan["status"] in statuses:
            void_plan(plan, reason, recorded_by)


# ==========================================================================
# Settlement money (PRD 3.8) and the fourth cascade link (PRD 2.10)
# ==========================================================================


def agreement_of_discard_event(event):
    lot = db.pack_lots.get(event["pack_lot_id"])
    if lot is None:
        return None
    return agreement_of_pack_lot(lot)


def period_discards(agreement_id, period_start, period_end):
    """(total discard value, credit-eligible discard value) inside the closed
    period, over the discard events of the agreement's own product."""
    total = 0
    eligible = 0
    for event in db.discard_events.values():
        agreement = agreement_of_discard_event(event)
        if agreement is None or agreement["id"] != agreement_id:
            continue
        date = event["created_at"][:10]
        if date < period_start or date > period_end:
            continue
        total += event["discard_value_cents"]
        if event["settlement_credit_eligible"]:
            eligible += event["discard_value_cents"]
    return total, eligible


def reconciled_feeds(host_store_id, period_start, period_end):
    out = []
    for feed in db.pos_sales_feeds.values():
        if feed["host_store_id"] != host_store_id:
            continue
        if feed["status"] != "RECONCILED":
            continue
        if feed["business_date"] < period_start or feed["business_date"] > period_end:
            continue
        out.append(feed)
    return db.ordered(out)


def compute_statement_money(statement, agreement):
    """The six pinned derivation steps of PRD 3.8. Returns the field changes."""
    feeds = reconciled_feeds(agreement["host_store_id"],
                             statement["period_start"], statement["period_end"])
    gross = sum(f["gross_sales_cents"] for f in feeds)
    markdown = sum(f["markdown_sales_cents"] for f in feeds)

    binding_base, advisory_base = calc.settlement_bases(
        gross, markdown, agreement["revenue_share_model"])
    binding_share = calc.tier_ladder(binding_base)
    advisory_share = calc.tier_ladder(advisory_base)

    space_credit = calc.space_shortfall_credit(
        agreement["space_shortfall_sqft"], agreement["space_credit_cents_per_sqft"],
        binding_share)
    total_discard, eligible_discard = period_discards(
        agreement["id"], statement["period_start"], statement["period_end"])
    credit = calc.discard_credit(eligible_discard, binding_share)

    return {
        "gross_sales_cents": gross,
        "markdown_sales_cents": markdown,
        "settlement_base_cents": binding_base,
        "binding_share_cents": binding_share,
        "advisory_share_cents": advisory_share,
        "variance_cents": binding_share - advisory_share,
        "space_shortfall_credit_cents": space_credit,
        "period_discard_value_cents": total_discard,
        "discard_credit_cents": credit,
        "net_due_cents": calc.net_due(binding_share, space_credit, credit),
        "binding_variant": agreement["revenue_share_model"],
    }


def cascade_discard_into_drafts(lot, event):
    """Fourth link: every DRAFT statement of the lot's agreement whose closed
    period covers the discard date recomputes its discard figures."""
    agreement = agreement_of_pack_lot(lot)
    if agreement is None:
        return
    date = event["created_at"][:10]
    for statement in db.ordered(list(db.settlement_statements.values())):
        if statement["status"] != "DRAFT":
            continue
        if statement["license_agreement_id"] != agreement["id"]:
            continue
        if date < statement["period_start"] or date > statement["period_end"]:
            continue
        recompute_discard_figures(statement, agreement,
                                  event["settlement_credit_eligible"])


def recompute_discard_figures(statement, agreement, credit_eligible):
    """period_discard_value_cents always; the two money fields only when the
    triggering event was itself credit-eligible."""
    total, eligible = period_discards(
        agreement["id"], statement["period_start"], statement["period_end"])
    changes = {"period_discard_value_cents": total}
    if credit_eligible:
        credit = calc.discard_credit(eligible, statement["binding_share_cents"])
        changes["discard_credit_cents"] = credit
        changes["net_due_cents"] = calc.net_due(
            statement["binding_share_cents"],
            statement["space_shortfall_credit_cents"], credit)
    db.apply_changes(statement, changes)


def refresh_lifetime_accrual(agreement):
    """PRD 3.1: the conserved ledger equals the sum of binding_share_cents over
    the agreement's ISSUED, ACKNOWLEDGED and PAID statements."""
    total = 0
    for statement in db.settlement_statements.values():
        if statement["license_agreement_id"] != agreement["id"]:
            continue
        if statement["status"] in ("ISSUED", "ACKNOWLEDGED", "PAID"):
            total += statement["binding_share_cents"]
    db.apply_changes(agreement, {"lifetime_share_accrued_cents": total})
    return total


# ==========================================================================
# Audit aggregates (PRD 3.9)
# ==========================================================================


def refresh_audit_counts(audit):
    findings = findings_of_audit(audit["id"])
    db.apply_changes(audit, {
        "critical_finding_count": len([f for f in findings
                                       if f["severity"] == "CRITICAL"]),
        "open_finding_count": len([f for f in findings if f["status"] == "OPEN"]),
    })
    return audit


def kiosk_has_live_audit(kiosk_id):
    live = ("IN_PROGRESS", "CORRECTIVE_ACTION_PENDING", "REVERIFICATION")
    for audit in db.food_safety_audits.values():
        if audit["kiosk_id"] == kiosk_id and audit["status"] in live:
            return True
    return False


# ==========================================================================
# Kiosk suspension / decommission cascade (PRD 2.10, 3.3)
# ==========================================================================


def suspend_kiosk(kiosk, suspension_reason, force_lockdown=False,
                  refresh_agreement=True):
    """The four-link chain. Suspension never touches sanitation_posture unless
    the caller is the audit escalation path, which forces LOCKDOWN.

    ``refresh_agreement`` is False when the agreement itself is the record being
    written: PRD 3.1 says a licence suspension sets the agreement's
    `active_kiosk_count` to 0 and "the agreement's `version` increments" -- once
    for the whole request, not once per cascaded kiosk.
    """
    kiosk["operational_state"] = "SUSPENDED"
    kiosk["suspension_reason"] = suspension_reason
    if force_lockdown:
        kiosk["sanitation_posture"] = "LOCKDOWN"
    db.touch(kiosk)
    void_kiosk_plans(kiosk, "KIOSK_SUSPENDED")
    if refresh_agreement:
        agreement = agreement_of(kiosk)
        if agreement is not None:
            refresh_active_kiosk_count(agreement)
    rederive_kiosk(kiosk, force_lockdown=force_lockdown)
    return kiosk


def decommission_kiosk(kiosk, decommission_reason, refresh_agreement=True):
    previous_state = kiosk["operational_state"]
    kiosk["operational_state"] = "DECOMMISSIONED"
    kiosk["suspension_reason"] = decommission_reason
    kiosk["lead_chef_id"] = None
    db.touch(kiosk)
    if previous_state != "PROVISIONING":
        void_kiosk_plans(kiosk, "KIOSK_SUSPENDED")
    for chef in db.ordered(list(db.chefs.values())):
        if chef["assigned_kiosk_id"] == kiosk["id"]:
            db.apply_changes(chef, {"assigned_kiosk_id": None})
    db.apply_changes(kiosk, {"certified_chef_count": 0})
    if refresh_agreement:
        agreement = agreement_of(kiosk)
        if agreement is not None:
            refresh_active_kiosk_count(agreement)
    return kiosk


# ==========================================================================
# Logical clock sweeps (PRD 2.5)
# ==========================================================================


def run_clock_sweeps():
    """Run after the clock has been moved: shelf-life discards first, then
    certification expiry, then re-derive every affected kiosk."""
    now = logical_now_iso()
    touched = {}

    expired_lots = 0
    for lot in db.ordered(list(db.pack_lots.values())):
        if lot["status"] not in LIVE_PACK_STATES:
            continue
        if lot["shelf_expiry_at"] is None or lot["shelf_expiry_at"] > now:
            continue
        kiosk = kiosk_of_pack_lot(lot)
        discard_pack_lot(lot, "SHELF_LIFE_EXPIRED")
        expired_lots += 1
        if kiosk is not None:
            touched[kiosk["id"]] = kiosk

    expired_certs = 0
    affected_chefs = {}
    for cert in db.ordered(list(db.certifications.values())):
        if cert["status"] != "VALID":
            continue
        if cert["expires_at"] > now:
            continue
        cert["status"] = "EXPIRED"
        db.touch(cert)
        expired_certs += 1
        chef = db.chefs.get(cert["chef_id"])
        if chef is not None:
            affected_chefs[chef["id"]] = chef
    for chef in db.ordered(list(affected_chefs.values())):
        refresh_chef(chef)
        if chef["assigned_kiosk_id"]:
            kiosk = db.kiosks.get(chef["assigned_kiosk_id"])
            if kiosk is not None:
                touched[kiosk["id"]] = kiosk

    for kiosk in db.ordered(list(touched.values())):
        refresh_certified_chef_count(kiosk)
        rederive_kiosk(kiosk)
    return {"expired_pack_lots": expired_lots, "expired_certifications": expired_certs}
