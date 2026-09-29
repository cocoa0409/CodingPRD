"""Payload factories — one per write endpoint.

Every factory emits only *input* fields; server-derived figures are never sent.
Money is always an integer number of cents sent as a JSON number (PRD §2.6:
"All money in this system is an integer number of cents"), dates are
``YYYY-MM-DD`` and instants are full ISO-8601 UTC instants (PRD §2.9 band 5:
"date fields formatted ``YYYY-MM-DD`` and instant fields formatted as ISO
8601 UTC").
"""

from typing import Any, Dict, Optional

from .types import (
    BondPaymentPlan,
    CaseSeverity,
    CategoryCode,
    CertType,
    FindingSeverity,
    GuestSettlementPolicy,
    HouseholdPaymentAllocation,
    JobCode,
    MembershipPaymentAllocation,
    PriorityTier,
    ProjectKind,
    ProrationBasis,
    Residency,
    ShiftRole,
    Squad,
    Zone,
)


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``...`` (meaning "omit")."""
    return {k: v for k, v in payload.items() if v is not Ellipsis}


# ─── Season (PRD §3.1) ────────────────────────────────

def season_payload(
    year: int = 2027,
    open_date: str = "2027-05-22",
    close_date: str = "2027-09-06",
    dues_due_date: str = "2027-04-15",
    baseline_bather_load: Any = 0,
    bather_load_capacity: Any = 120,
    proration_basis: Any = ProrationBasis.CALENDAR_DAY,
    guest_settlement_policy: Any = GuestSettlementPolicy.PASS_FIRST,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "year": year,
        "open_date": open_date,
        "close_date": close_date,
        "dues_due_date": dues_due_date,
        "baseline_bather_load": baseline_bather_load,
        "bather_load_capacity": bather_load_capacity,
        "proration_basis": proration_basis,
        "guest_settlement_policy": guest_settlement_policy,
    }
    payload.update(overrides)
    return _prune(payload)


def reserve_contribution_payload(amount_cents: int = 200000,
                                 note: Any = "Special assessment",
                                 **overrides: Any) -> Dict[str, Any]:
    payload = {"amount_cents": amount_cents, "note": note}
    payload.update(overrides)
    return _prune(payload)


def billing_run_payload(as_of_date: Any = Ellipsis,
                        **overrides: Any) -> Dict[str, Any]:
    payload = {"as_of_date": as_of_date}
    payload.update(overrides)
    return _prune(payload)


# ─── Membership category (PRD §3.2) ───────────────────

def membership_category_payload(
    code: Any = CategoryCode.FAMILY,
    label: Any = "Family Membership",
    bond_cents: Any = 120000,
    initiation_fee_cents: Any = 45000,
    seasonal_dues_cents: Any = 78000,
    guest_pass_allotment: Any = 4,
    max_household_size: Any = 6,
    volunteer_credits_required: Any = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "code": code,
        "label": label,
        "bond_cents": bond_cents,
        "initiation_fee_cents": initiation_fee_cents,
        "seasonal_dues_cents": seasonal_dues_cents,
        "guest_pass_allotment": guest_pass_allotment,
        "max_household_size": max_household_size,
        "volunteer_credits_required": volunteer_credits_required,
    }
    payload.update(overrides)
    return _prune(payload)


# ─── Household (PRD §3.2) ─────────────────────────────

def household_payload(
    primary_contact_name: Any = "Alice Nguyen",
    address_line: Any = "12 Poolside Lane",
    residency: Any = Residency.IN_DISTRICT,
    member_count: Any = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "primary_contact_name": primary_contact_name,
        "address_line": address_line,
        "residency": residency,
        "member_count": member_count,
    }
    payload.update(overrides)
    return _prune(payload)


def household_payment_payload(
    amount_cents: Any = 1000,
    allocation: Any = HouseholdPaymentAllocation.GUEST_FEES,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"amount_cents": amount_cents, "allocation": allocation}
    payload.update(overrides)
    return _prune(payload)


def standing_transition_payload(
    to_standing: Any = "GOOD_STANDING",
    reason: Any = "Board reinstatement after review",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"to_standing": to_standing, "reason": reason}
    payload.update(overrides)
    return _prune(payload)


# ─── Waitlist (PRD §3.2) ──────────────────────────────

def waitlist_entry_payload(
    household_id: str,
    membership_category_id: str,
    priority_tier: Any = PriorityTier.STANDARD,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "household_id": household_id,
        "membership_category_id": membership_category_id,
        "priority_tier": priority_tier,
    }
    payload.update(overrides)
    return _prune(payload)


def next_offer_payload(membership_category_id: str,
                       **overrides: Any) -> Dict[str, Any]:
    payload = {"membership_category_id": membership_category_id}
    payload.update(overrides)
    return _prune(payload)


def waitlist_respond_payload(decision: Any = "ACCEPT",
                             requeue: Any = Ellipsis,
                             **overrides: Any) -> Dict[str, Any]:
    payload = {"decision": decision, "requeue": requeue}
    payload.update(overrides)
    return _prune(payload)


# ─── Membership (PRD §3.3) ────────────────────────────

def membership_payload(
    household_id: str,
    membership_category_id: str,
    season_id: str,
    join_date: Any = "2027-05-22",
    bond_payment_plan: Any = BondPaymentPlan.FULL,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "household_id": household_id,
        "membership_category_id": membership_category_id,
        "season_id": season_id,
        "join_date": join_date,
        "bond_payment_plan": bond_payment_plan,
    }
    payload.update(overrides)
    return _prune(payload)


def membership_payment_payload(
    amount_cents: Any = 1000,
    allocation: Any = MembershipPaymentAllocation.DUES,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"amount_cents": amount_cents, "allocation": allocation}
    payload.update(overrides)
    return _prune(payload)


def write_off_payload(reason: Any = "Uncollectible after two notices",
                      **overrides: Any) -> Dict[str, Any]:
    payload = {"reason": reason}
    payload.update(overrides)
    return _prune(payload)


# ─── Guest visit (PRD §3.5, §2.7) ─────────────────────

def guest_visit_payload(
    membership_id: str,
    expected_household_version: int,
    sponsor_name: Any = "Alice Nguyen",
    guest_count: Any = 3,
    visit_start_iso: Any = "2027-06-25T12:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "membership_id": membership_id,
        "sponsor_name": sponsor_name,
        "guest_count": guest_count,
        "visit_start_iso": visit_start_iso,
        "expected_household_version": expected_household_version,
    }
    payload.update(overrides)
    return _prune(payload)


def void_visit_payload(reason: Any = "Recorded against the wrong household",
                       **overrides: Any) -> Dict[str, Any]:
    payload = {"reason": reason}
    payload.update(overrides)
    return _prune(payload)


# ─── Lifeguard / certification / shift (PRD §3.8) ─────

def lifeguard_payload(full_name: Any = "Dana Reyes",
                      hire_date: Any = "2027-05-01",
                      **overrides: Any) -> Dict[str, Any]:
    payload = {"full_name": full_name, "hire_date": hire_date}
    payload.update(overrides)
    return _prune(payload)


def certification_payload(
    lifeguard_id: str,
    cert_type: Any = CertType.LIFEGUARD,
    issued_on: Any = "2026-06-01",
    expires_on: Any = "2028-05-31",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "lifeguard_id": lifeguard_id,
        "cert_type": cert_type,
        "issued_on": issued_on,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return _prune(payload)


def revoke_certification_payload(
    revoked_reason: Any = "Failed the annual re-test",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"revoked_reason": revoked_reason}
    payload.update(overrides)
    return _prune(payload)


def guard_shift_payload(
    lifeguard_id: str,
    season_id: str,
    start_iso: Any = "2027-07-01T09:00:00Z",
    end_iso: Any = "2027-07-01T13:00:00Z",
    shift_role: Any = ShiftRole.PRIMARY,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "lifeguard_id": lifeguard_id,
        "season_id": season_id,
        "shift_role": shift_role,
        "start_iso": start_iso,
        "end_iso": end_iso,
    }
    payload.update(overrides)
    return _prune(payload)


# ─── Swim team (PRD §3.6) ─────────────────────────────

def registration_payload(
    membership_id: str,
    season_id: str,
    swimmer_name: Any = "Ben Nguyen",
    swimmer_birthdate: Any = "2014-03-11",
    squad: Any = Squad.JUNIOR,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "membership_id": membership_id,
        "season_id": season_id,
        "swimmer_name": swimmer_name,
        "swimmer_birthdate": swimmer_birthdate,
        "squad": squad,
    }
    payload.update(overrides)
    return _prune(payload)


def meet_payload(
    season_id: str,
    name: Any = "Home Invitational",
    start_iso: Any = "2027-07-10T08:00:00Z",
    end_iso: Any = "2027-07-10T14:00:00Z",
    expected_swimmers: Any = 20,
    volunteer_slots_required: Any = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "season_id": season_id,
        "name": name,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "expected_swimmers": expected_swimmers,
        "volunteer_slots_required": volunteer_slots_required,
    }
    payload.update(overrides)
    return _prune(payload)


def volunteer_assignment_payload(
    meet_id: str,
    swim_team_registration_id: str,
    job_code: Any = JobCode.TIMER,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "meet_id": meet_id,
        "swim_team_registration_id": swim_team_registration_id,
        "job_code": job_code,
    }
    payload.update(overrides)
    return _prune(payload)


# ─── Party reservation (PRD §3.7) ─────────────────────

def party_reservation_payload(
    membership_id: str,
    zone: Any = Zone.PAVILION,
    start_iso: Any = "2027-07-15T14:00:00Z",
    end_iso: Any = "2027-07-15T18:00:00Z",
    guest_count: Any = 8,
    host_party_size: Any = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "membership_id": membership_id,
        "zone": zone,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "guest_count": guest_count,
        "host_party_size": host_party_size,
    }
    payload.update(overrides)
    return _prune(payload)


# ─── Inspection finding (PRD §3.1) ────────────────────

def inspection_finding_payload(
    season_id: str,
    inspected_on: Any = "2027-07-01",
    inspector_name: Any = "Officer Marsh",
    finding_code: Any = "HC-410",
    severity: Any = FindingSeverity.MINOR,
    narrative: Any = "Chlorine log incomplete for two days.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "season_id": season_id,
        "inspected_on": inspected_on,
        "inspector_name": inspector_name,
        "finding_code": finding_code,
        "severity": severity,
        "narrative": narrative,
    }
    payload.update(overrides)
    return _prune(payload)


def finding_transition_payload(to_status: Any,
                              remediation_note: Any = Ellipsis,
                              **overrides: Any) -> Dict[str, Any]:
    payload = {"to_status": to_status, "remediation_note": remediation_note}
    payload.update(overrides)
    return _prune(payload)


# ─── Conduct case (PRD §3.9) ──────────────────────────

def conduct_case_payload(
    household_id: str,
    subject_name: Any = "Teen guest of the household",
    severity: Any = CaseSeverity.MAJOR,
    narrative: Any = "Repeated diving in the shallow end after two warnings.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "household_id": household_id,
        "subject_name": subject_name,
        "severity": severity,
        "narrative": narrative,
    }
    payload.update(overrides)
    return _prune(payload)


def case_transition_payload(to_status: Any,
                           sanction_type: Any = Ellipsis,
                           **overrides: Any) -> Dict[str, Any]:
    payload = {"to_status": to_status, "sanction_type": sanction_type}
    payload.update(overrides)
    return _prune(payload)


# ─── Capital project (PRD §3.10) ──────────────────────

def capital_project_payload(
    funding_season_id: str,
    project_kind: Any = ProjectKind.POOL_RESURFACING,
    title: Any = "Main pool resurfacing",
    budget_cents: Any = 180000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "funding_season_id": funding_season_id,
        "project_kind": project_kind,
        "title": title,
        "budget_cents": budget_cents,
    }
    payload.update(overrides)
    return _prune(payload)


def fund_project_payload(draw_amount_cents: int,
                         expected_capital_project_version: int,
                         **overrides: Any) -> Dict[str, Any]:
    payload = {
        "draw_amount_cents": draw_amount_cents,
        "expected_capital_project_version": expected_capital_project_version,
    }
    payload.update(overrides)
    return _prune(payload)


# ─── Generic transition payloads ──────────────────────

def transition_payload(to_status: Any, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return _prune(payload)


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ─── Category presets used across the suite ───────────
# The four categories below differ only in the figures PRD §3.2 declares, and
# each isolates a different rule: FAMILY carries a bond and an initiation fee,
# COUPLE carries dues only, SINGLE has no party privileges, and SENIOR carries
# a bond with no initiation fee.

def family_category_payload(**overrides: Any) -> Dict[str, Any]:
    return membership_category_payload(
        code=CategoryCode.FAMILY,
        label="Family Membership",
        bond_cents=120000,
        initiation_fee_cents=45000,
        seasonal_dues_cents=78000,
        guest_pass_allotment=4,
        max_household_size=6,
        volunteer_credits_required=4,
        **overrides,
    )


def couple_category_payload(**overrides: Any) -> Dict[str, Any]:
    return membership_category_payload(
        code=CategoryCode.COUPLE,
        label="Couple Membership",
        bond_cents=0,
        initiation_fee_cents=0,
        seasonal_dues_cents=30000,
        guest_pass_allotment=2,
        max_household_size=4,
        volunteer_credits_required=2,
        **overrides,
    )


def single_category_payload(**overrides: Any) -> Dict[str, Any]:
    return membership_category_payload(
        code=CategoryCode.SINGLE,
        label="Single Membership",
        bond_cents=0,
        initiation_fee_cents=0,
        seasonal_dues_cents=20000,
        guest_pass_allotment=0,
        max_household_size=2,
        volunteer_credits_required=0,
        **overrides,
    )


def senior_category_payload(**overrides: Any) -> Dict[str, Any]:
    return membership_category_payload(
        code=CategoryCode.SENIOR,
        label="Senior Membership",
        bond_cents=120000,
        initiation_fee_cents=0,
        seasonal_dues_cents=78000,
        guest_pass_allotment=4,
        max_household_size=6,
        volunteer_credits_required=0,
        **overrides,
    )
