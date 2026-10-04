"""Calculation rules per SCAFFOLD §1.3 / PRD §3."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, now, _parse_iso
from errors import raise_err, ERR_NO_FINE_SCHEDULE, ERR_PANEL_POOL_EXHAUSTED

LATE_TIER1_MAX_DAYS = 30
STRIKE_WINDOW_DAYS = 365
REVERT_WINDOW_DAYS = 30
ESCALATION_THRESHOLD = 3
CLEAR_COOP_WINDOW_HOURS = 24
STATUS_CHANGE_GRACE_HOURS = 48
PANEL_SIZE = 3

FACTOR_KEYS = [
    "F1_FIRST_CONTACT",
    "F2_CONTINUOUS_EFFORT",
    "F3_AGENCY_DISCLOSURE",
    "F4_CONTRACT_ROLE",
    "F5_ABANDONMENT",
]
FACTOR_WEIGHTS = {
    "F1_FIRST_CONTACT": Decimal("0.30"),
    "F2_CONTINUOUS_EFFORT": Decimal("0.25"),
    "F3_AGENCY_DISCLOSURE": Decimal("0.15"),
    "F4_CONTRACT_ROLE": Decimal("0.20"),
    "F5_ABANDONMENT": Decimal("0.10"),
}
TIER_FULL = Decimal("7.00")
TIER_HIGH = Decimal("5.00")
TIER_LOW = Decimal("3.00")

SANCTION_TIERS_CENTS = [50000, 100000, 250000, 500000]


# ---------------------------------------------------------------------------
# dues_invoice_amounts
# ---------------------------------------------------------------------------

def compute_invoice_amounts(assoc, period, member, issued_at):
    """Compute (base_amount_cents, days_overdue_at_issue, late_fee_cents,
    credit_applied_cents, amount_due_cents) for a member billed under a period.

    Evaluation order pinned: late-fee tier -> credit cap -> amount due.
    Proration variant: member.created_at within [period_start_date, due_date]
    prorates the base by remaining days / 365, floor toward zero, BEFORE
    late-fee and credit steps.
    """
    amount_cents = period["amount_cents"]
    period_start = _parse_iso(period["period_start_date"])
    due_date = _parse_iso(period["due_date"])
    member_created = _parse_iso(member["created_at"])

    base_amount_cents = amount_cents
    if period_start <= member_created <= due_date:
        remaining_days = (due_date - member_created).days + 1
        if remaining_days < 0:
            remaining_days = 0
        base_amount_cents = (amount_cents * remaining_days) // 365

    delta_seconds = (issued_at - due_date).total_seconds()
    days_overdue = int(delta_seconds // 86400)
    if days_overdue < 0:
        days_overdue = 0

    if days_overdue == 0:
        late_fee_cents = 0
    elif days_overdue <= LATE_TIER1_MAX_DAYS:
        late_fee_cents = assoc["late_fee_tier1_cents"]
    else:
        late_fee_cents = assoc["late_fee_tier2_cents"]  # tier2 replaces tier1

    credit_applied_cents = min(member["sanction_credit_balance_cents"],
                               base_amount_cents + late_fee_cents)
    amount_due_cents = base_amount_cents + late_fee_cents - credit_applied_cents
    return (base_amount_cents, days_overdue, late_fee_cents,
            credit_applied_cents, amount_due_cents)


# ---------------------------------------------------------------------------
# member_strikes_12m
# ---------------------------------------------------------------------------

def recompute_strikes(member):
    """Count of PAID citations in (now-365d, now] whose FIRST reinstatement
    R >= assessed_at satisfies R - assessed_at <= 30 days; citations with no
    later reinstatement still count (never-suspended member)."""
    current = now()
    window_start = current - timedelta(days=STRIKE_WINDOW_DAYS)
    reinstatements = sorted(store.reinstatements.get(member["id"], []))
    count = 0
    for c in store.citations.values():
        if c["member_id"] != member["id"]:
            continue
        if c["status"] != "PAID":
            continue
        assessed = _parse_iso(c["assessed_at"])
        # half-open: older boundary EXCLUSIVE, now INCLUSIVE
        if not (window_start < assessed <= current):
            continue
        first_r = None
        for r in reinstatements:
            if r >= assessed:
                first_r = r
                break
        if first_r is None:
            count += 1
        elif (first_r - assessed) <= timedelta(days=REVERT_WINDOW_DAYS):
            count += 1
    member["strikes_12m"] = count
    return count


# ---------------------------------------------------------------------------
# hearing_panel_exclusions (computed member field)
# ---------------------------------------------------------------------------

def compute_panel_exclusions(member):
    """Member ids excluded from this member's hearing-panel candidate pool.

    The entity note lists: the member themself, their own association's
    members, and respondents of any OPEN/DECIDED ArbitrationCase where this
    member is complainant or respondent. Read literally, 'their own
    association's members' would make every same-association panel impossible
    (the selector also requires association_id == panel.association_id), so
    the functional reading is used: the member themself plus their dispute
    set — counterparties of any arbitration or ethics case naming them, and
    respondents of arbitration cases where they are complainant or
    respondent ('arbitration counterparties exclude each other's whole
    dispute set' per §3.8)."""
    excluded = set()
    excluded.add(member["id"])
    mid = member["id"]
    for case in store.arbitration_cases.values():
        if case["complainant_member_id"] == mid or \
           case["respondent_member_id"] == mid:
            excluded.add(case["complainant_member_id"])
            excluded.add(case["respondent_member_id"])
    for case in store.ethics_cases.values():
        if case["complainant_member_id"] == mid or \
           case["respondent_member_id"] == mid:
            excluded.add(case["complainant_member_id"])
            excluded.add(case["respondent_member_id"])
    return sorted(excluded)


def refresh_exclusions_for_association(association_id):
    for m in store.members.values():
        if m["association_id"] == association_id:
            m["hearing_panel_exclusions"] = compute_panel_exclusions(m)


# ---------------------------------------------------------------------------
# clear_coop_late_check — activation late when activated_at > marketing + 24h
# (boundary inclusive: activation AT deadline is timely)
# ---------------------------------------------------------------------------

def clear_coop_is_late(public_marketing_at, activated_at):
    deadline = _parse_iso(public_marketing_at) + timedelta(hours=CLEAR_COOP_WINDOW_HOURS)
    return activated_at > deadline


# ---------------------------------------------------------------------------
# status_change_lateness
# ---------------------------------------------------------------------------

def compute_late_by_hours(recorded_at, business_effective_at):
    elapsed_seconds = (recorded_at - _parse_iso(business_effective_at)).total_seconds()
    elapsed_hours = int(elapsed_seconds // 3600)
    late = elapsed_hours - STATUS_CHANGE_GRACE_HOURS
    return late if late > 0 else 0


# ---------------------------------------------------------------------------
# citation_fine_lookup — half-open [effective_from, effective_to)
# ---------------------------------------------------------------------------

def lookup_fine(association_id, rule_code, assessed_at):
    for row in store.fine_schedules.values():
        if row["association_id"] != association_id:
            continue
        if row["rule_code"] != rule_code:
            continue
        if row["status"] != "ACTIVE":
            continue
        eff_from = _parse_iso(row["effective_from"])
        eff_to = _parse_iso(row["effective_to"]) if row.get("effective_to") else None
        if eff_from <= assessed_at and (eff_to is None or assessed_at < eff_to):
            return row
    raise_err(ERR_NO_FINE_SCHEDULE,
              "No ACTIVE FineSchedule row covers assessed_at for rule %s" % rule_code)


def fine_schedule_key(rule_code, assessed_at):
    return "%s@%s" % (rule_code, assessed_at.strftime("%Y-%m-%d"))


# ---------------------------------------------------------------------------
# procuring_cause_award — round score half-up to 2dp, then tier, then
# round_half_up(claim * pct). F5_ABANDONMENT >= 8 forces pct = 0.
# ---------------------------------------------------------------------------

def procuring_cause_award(claim_amount_cents, factor_scores):
    score = Decimal("0")
    for key in FACTOR_KEYS:
        score += FACTOR_WEIGHTS[key] * Decimal(int(factor_scores[key]))
    score = score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # abandonment override runs AFTER score rounding, BEFORE tier selection
    if int(factor_scores["F5_ABANDONMENT"]) >= 8:
        pct = Decimal("0.00")
    elif score >= TIER_FULL:
        pct = Decimal("1.00")
    elif score >= TIER_HIGH:
        pct = Decimal("0.60")
    elif score >= TIER_LOW:
        pct = Decimal("0.30")
    else:
        pct = Decimal("0.00")
    award = (Decimal(claim_amount_cents) * pct).quantize(Decimal("1"),
                                                         rounding=ROUND_HALF_UP)
    award = int(award)
    if award < 0:
        award = 0
    if award > claim_amount_cents:
        award = claim_amount_cents
    return award


# ---------------------------------------------------------------------------
# ethics_sanction_amount — tiered on respondent's LIVE strikes_12m
# ---------------------------------------------------------------------------

def ethics_sanction_amount(strikes):
    if strikes <= 0:
        return SANCTION_TIERS_CENTS[0]
    if strikes == 1:
        return SANCTION_TIERS_CENTS[1]
    if strikes == 2:
        return SANCTION_TIERS_CENTS[2]
    return SANCTION_TIERS_CENTS[3]


# ---------------------------------------------------------------------------
# hearing_panel_selection — selector policy
# ---------------------------------------------------------------------------

def select_panel_members(association_id, case_type, case):
    if case_type == "CITATION":
        subject_ids = {case["member_id"]}
    else:  # ETHICS or ARBITRATION
        subject_ids = {case["complainant_member_id"], case["respondent_member_id"]}

    excluded = set(subject_ids)
    for sid in subject_ids:
        subj = store.members.get(sid)
        if subj is not None:
            excluded.update(subj.get("hearing_panel_exclusions") or [])

    prior_panelists = set()
    for p in store.hearing_panels.values():
        if p["case_id"] == case["id"] and p["status"] == "DECIDED":
            prior_panelists.update(p.get("selected_member_ids") or [])

    eligible = []
    for m in store.members.values():
        if m["association_id"] != association_id:
            continue
        if m["membership_state"] != "ACTIVE" or m["mls_access_state"] != "ENABLED":
            continue
        if m["id"] in excluded:
            continue
        if m["id"] in prior_panelists:
            continue
        eligible.append(m)

    eligible.sort(key=lambda m: (m["strikes_12m"], m["created_at"]))
    if len(eligible) < PANEL_SIZE:
        raise_err(ERR_PANEL_POOL_EXHAUSTED,
                  "Fewer than 3 eligible panelists after exclusions")
    return [m["id"] for m in eligible[:PANEL_SIZE]]


# ---------------------------------------------------------------------------
# association_ruleset_version
# ---------------------------------------------------------------------------

def ruleset_version(association_id):
    return sum(1 for r in store.policy_revisions.values()
               if r["association_id"] == association_id
               and r["status"] in ("ACTIVE", "SUPERSEDED"))


def governing_revision(association_id):
    """The ACTIVE PolicyRevision with max effective_at (the one that was
    activated most recently)."""
    actives = [r for r in store.policy_revisions.values()
               if r["association_id"] == association_id and r["status"] == "ACTIVE"]
    if not actives:
        return None
    return max(actives, key=lambda r: _parse_iso(r["effective_at"]))


def license_is_compliant(license_row):
    assoc_id = license_row["association_id"]
    if license_row["display_ruleset_version"] != ruleset_version(assoc_id):
        return False
    gov = governing_revision(assoc_id)
    if gov is not None and gov["comp_display_mode"] == "COMP_DISPLAY_OFF":
        if "offer_comp_cents" in (license_row.get("listing_field_allowlist") or []):
            return False
    return True


# ---------------------------------------------------------------------------
# feed_sync_projection
# ---------------------------------------------------------------------------

ALL_LISTING_FIELDS = [
    "id", "office_id", "listing_member_id", "mls_number", "property_address",
    "list_price_cents", "public_marketing_at", "status", "accuracy_flag",
    "policy_revision_id", "offer_comp_cents", "activated_at",
    "status_changed_at", "created_at", "updated_at", "version",
]


def project_feed(license_row):
    """Returns (projected_listings, projected_count, comp_fields_stripped)."""
    assoc_id = license_row["association_id"]
    scope = license_row["scope"]
    gov = governing_revision(assoc_id)
    comp_off = gov is not None and gov["comp_display_mode"] == "COMP_DISPLAY_OFF"

    office_ids = {o["id"] for o in store.offices.values()
                  if o["association_id"] == assoc_id}
    listings = [l for l in store.listings.values() if l["office_id"] in office_ids]

    if scope == "BACKOFFICE":
        wanted_status = {"ACTIVE", "PENDING", "SOLD", "WITHDRAWN", "EXPIRED",
                         "CANCELLED"}
        rows = []
        for l in listings:
            if l["status"] not in wanted_status:
                continue
            row = {f: l.get(f) for f in ALL_LISTING_FIELDS}
            rows.append(row)
    else:  # IDX / VOW
        wanted_status = {"ACTIVE", "PENDING"}
        allowlist = list(license_row.get("listing_field_allowlist") or [])
        if scope == "VOW" and "office_id" not in allowlist:
            allowlist.append("office_id")
        rows = []
        for l in listings:
            if l["status"] not in wanted_status:
                continue
            rows.append({f: l.get(f) for f in allowlist})

    comp_fields_stripped = False
    if comp_off:
        for row in rows:
            if "offer_comp_cents" in row:
                del row["offer_comp_cents"]
                comp_fields_stripped = True
        # even when no row carried the field, stripping occurred conceptually
        # only if the field was in the projection source
        if not comp_fields_stripped:
            if scope == "BACKOFFICE":
                comp_fields_stripped = True
            elif "offer_comp_cents" in (license_row.get("listing_field_allowlist") or []):
                comp_fields_stripped = True

    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    return rows, len(rows), comp_fields_stripped
