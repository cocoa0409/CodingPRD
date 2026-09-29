"""Composite setup helpers.

Five tiers, each building on the one before:

* Tier 1 — clock and single-entity creates.
* Tier 2 — the entity hierarchy: category, season, household, membership.
* Tier 3 — full-lifecycle shortcuts: invoiced, active, paid, delinquent
  memberships; certified guards with confirmed shifts; meets with rosters.
* Tier 4 — accumulation and threshold targeting: guest visits against a freshly
  read household version, reserve contributions, conduct points.
* Tier 5 — terminal and finalisation states: written-off memberships, suspended
  households, closed seasons, closed findings.

Every helper uses ``get_success_data`` (the lenient setup validator) so a failed
setup step reports the server's own error identifier rather than a bare status
code. ``data`` is unwrapped exactly once, inside ``get_success_data``.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    BOARD_PRESIDENT,
    BOARD_PRESIDENT_2,
    HEALTH_INSPECTOR,
    HEALTH_INSPECTOR_2,
    MEMBERSHIP_CHAIR,
    POOL_MANAGER,
    SWIM_TEAM_COACH,
    SYSTEM_OPERATOR,
    TREASURER,
    TREASURER_2,
    make_member_headers,
)
from .types import (
    BondPaymentPlan,
    CertType,
    FindingSeverity,
    ShiftRole,
    Squad,
    Zone,
)

# ─────────────────────────────────────────────────────
# Tier 1 — the logical clock and single-entity creates
# ─────────────────────────────────────────────────────


def set_clock(api: ApiClient, to_iso8601: str) -> None:
    """Move the server's logical clock (PRD §2.5)."""
    get_success_data(api.set_clock(to_iso8601, SYSTEM_OPERATOR), 200)


def create_category(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(
        api.create_membership_category(payload, MEMBERSHIP_CHAIR), 201
    )


def create_family_category(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return create_category(api, f.family_category_payload(**overrides))


def create_couple_category(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return create_category(api, f.couple_category_payload(**overrides))


def create_single_category(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return create_category(api, f.single_category_payload(**overrides))


def create_senior_category(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return create_category(api, f.senior_category_payload(**overrides))


def create_season(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_season(f.season_payload(**overrides), BOARD_PRESIDENT), 201
    )


def open_season(api: ApiClient, season_id: str) -> Dict[str, Any]:
    return get_success_data(api.open_season(season_id, POOL_MANAGER), 200)


def create_household(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_household(f.household_payload(**overrides), MEMBERSHIP_CHAIR),
        201,
    )


def create_lifeguard(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_lifeguard(f.lifeguard_payload(**overrides), POOL_MANAGER), 201
    )


def read_household(api: ApiClient, household_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_household(household_id, MEMBERSHIP_CHAIR), 200)


def read_membership(api: ApiClient, membership_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_membership(membership_id, TREASURER), 200)


def read_season(api: ApiClient, season_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_season(season_id, TREASURER), 200)


def read_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_capital_project(project_id, TREASURER), 200)


def read_meet(api: ApiClient, meet_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_meet(meet_id, SWIM_TEAM_COACH), 200)


def read_registration(api: ApiClient, registration_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_registration(registration_id, SWIM_TEAM_COACH), 200
    )


def read_reservation(api: ApiClient, reservation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_party_reservation(reservation_id, POOL_MANAGER), 200
    )


def read_lifeguard(api: ApiClient, lifeguard_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_lifeguard(lifeguard_id, POOL_MANAGER), 200)


def read_shift(api: ApiClient, shift_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_guard_shift(shift_id, POOL_MANAGER), 200)


def read_finding(api: ApiClient, finding_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_inspection_finding(finding_id, HEALTH_INSPECTOR), 200
    )


def read_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_conduct_case(case_id, BOARD_PRESIDENT), 200)


def read_waitlist_entry(api: ApiClient, entry_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_waitlist_entry(entry_id, MEMBERSHIP_CHAIR), 200
    )


def read_visit(api: ApiClient, visit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_guest_visit(visit_id, POOL_MANAGER), 200)


def read_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_volunteer_assignment(assignment_id, SWIM_TEAM_COACH), 200
    )


def read_certification(api: ApiClient, certification_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_certification(certification_id, POOL_MANAGER), 200
    )


# ─────────────────────────────────────────────────────
# Tier 2 — the entity hierarchy
# ─────────────────────────────────────────────────────

# The 2027 season window used across the suite: open 2027-05-22, close
# 2027-09-06, dues due 2027-04-15 (already in the past at the fixture clock, so
# an invoice cut inside the season carries the PRD §3.4 late penalty).
SEASON_2027 = {
    "year": 2027,
    "open_date": "2027-05-22",
    "close_date": "2027-09-06",
    "dues_due_date": "2027-04-15",
}
SEASON_2028 = {
    "year": 2028,
    "open_date": "2028-05-20",
    "close_date": "2028-09-04",
    "dues_due_date": "2028-04-15",
}


def setup_open_season(api: ApiClient, clock_iso: Optional[str] = None,
                      **overrides: Any) -> Dict[str, Any]:
    """Create a 2027 season and open it (PRD §3.1).

    Returns the season as read back after opening, so ``facility_posture`` is
    the re-derived value rather than the born-``CLOSED`` one.
    """
    if clock_iso is not None:
        set_clock(api, clock_iso)
    params = dict(SEASON_2027)
    params.update(overrides)
    season = create_season(api, **params)
    return open_season(api, season["id"])


def setup_planned_season(api: ApiClient, clock_iso: Optional[str] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """Create a season and leave it in PLANNED."""
    if clock_iso is not None:
        set_clock(api, clock_iso)
    params = dict(SEASON_2027)
    params.update(overrides)
    return create_season(api, **params)


def setup_membership(api: ApiClient, household_id: str, category_id: str,
                     season_id: str, join_date: str = "2027-05-22",
                     bond_payment_plan: Any = BondPaymentPlan.FULL,
                     **overrides: Any) -> Dict[str, Any]:
    """Sell a household its season membership (PRD §3.3)."""
    payload = f.membership_payload(
        household_id=household_id,
        membership_category_id=category_id,
        season_id=season_id,
        join_date=join_date,
        bond_payment_plan=bond_payment_plan,
        **overrides,
    )
    return get_success_data(api.create_membership(payload, MEMBERSHIP_CHAIR), 201)


def setup_club(api: ApiClient, clock_iso: str = "2027-07-01T09:00:00Z",
               category: str = "FAMILY", member_count: int = 4,
               season_overrides: Optional[Dict[str, Any]] = None,
               category_overrides: Optional[Dict[str, Any]] = None,
               household_overrides: Optional[Dict[str, Any]] = None,
               join_date: str = "2027-05-22",
               bond_payment_plan: Any = BondPaymentPlan.FULL) -> Dict[str, Any]:
    """Clock, category, open season, household and an UNBILLED membership.

    This is the prefix nearly every scenario in the suite starts from. The
    returned dict carries the four rows plus the Member headers for the
    household, which PRD §2.1 ties to the household's own ``id``.
    """
    set_clock(api, clock_iso)
    builders = {
        "FAMILY": create_family_category,
        "COUPLE": create_couple_category,
        "SINGLE": create_single_category,
        "SENIOR": create_senior_category,
    }
    cat = builders[category](api, **(category_overrides or {}))
    season = setup_open_season(api, **(season_overrides or {}))
    household = create_household(api, member_count=member_count,
                                 **(household_overrides or {}))
    membership = setup_membership(
        api, household["id"], cat["id"], season["id"],
        join_date=join_date, bond_payment_plan=bond_payment_plan,
    )
    return {
        "category": cat,
        "season": season,
        "household": household,
        "membership": membership,
        "member_headers": make_member_headers(household["id"]),
    }


def add_household(api: ApiClient, ctx: Dict[str, Any], name: str,
                  member_count: int = 4, join_date: str = "2027-05-22",
                  bond_payment_plan: Any = BondPaymentPlan.FULL,
                  category_id: Optional[str] = None,
                  **household_overrides: Any) -> Dict[str, Any]:
    """Register a second (third, fourth...) household with its own membership.

    Each household is a distinct resource owner, so each gets its own
    ``X-User-ID`` in the returned ``member_headers``.
    """
    household = create_household(
        api, primary_contact_name=name, member_count=member_count,
        **household_overrides,
    )
    membership = setup_membership(
        api, household["id"], category_id or ctx["category"]["id"],
        ctx["season"]["id"], join_date=join_date,
        bond_payment_plan=bond_payment_plan,
    )
    return {
        "household": household,
        "membership": membership,
        "member_headers": make_member_headers(household["id"]),
    }


# ─────────────────────────────────────────────────────
# Tier 3 — full-lifecycle shortcuts
# ─────────────────────────────────────────────────────


def invoice_membership(api: ApiClient, membership_id: str) -> Dict[str, Any]:
    """Cut the season invoice, flipping access PENDING -> ACTIVE (PRD §3.4)."""
    return get_success_data(api.invoice_membership(membership_id, TREASURER), 200)


def pay_membership(api: ApiClient, membership_id: str, amount_cents: int,
                   allocation: Any = Ellipsis) -> Dict[str, Any]:
    payload = f.membership_payment_payload(
        amount_cents=amount_cents, allocation=allocation
    )
    return get_success_data(
        api.create_membership_payment(membership_id, payload, TREASURER), 200
    )


def pay_membership_in_full(api: ApiClient, membership_id: str) -> Dict[str, Any]:
    """Settle the whole balance so the membership arrives at PAID."""
    membership = read_membership(api, membership_id)
    return pay_membership(api, membership_id, membership["balance_due_cents"])


def pay_household(api: ApiClient, household_id: str, amount_cents: int,
                  allocation: str) -> Dict[str, Any]:
    payload = f.household_payment_payload(
        amount_cents=amount_cents, allocation=allocation
    )
    return get_success_data(
        api.create_household_payment(household_id, payload, TREASURER), 200
    )


def setup_active_membership(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """``setup_club`` plus the invoice, so access is ACTIVE and dues INVOICED."""
    ctx = setup_club(api, **kwargs)
    ctx["membership"] = invoice_membership(api, ctx["membership"]["id"])
    ctx["household"] = read_household(api, ctx["household"]["id"])
    return ctx


def setup_paid_membership(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An ACTIVE membership settled in full, so dues_status is PAID."""
    ctx = setup_active_membership(api, **kwargs)
    ctx["membership"] = pay_membership_in_full(api, ctx["membership"]["id"])
    ctx["household"] = read_household(api, ctx["household"]["id"])
    ctx["season"] = read_season(api, ctx["season"]["id"])
    return ctx


def run_billing_run(api: ApiClient, season_id: str,
                    as_of_date: Any = Ellipsis) -> Dict[str, Any]:
    """Run the PRD §3.1 billing checkpoint against a season."""
    payload = f.billing_run_payload(as_of_date=as_of_date)
    return get_success_data(api.run_billing_run(season_id, TREASURER, payload), 200)


def setup_delinquent_membership(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """An INVOICED membership aged into DELINQUENT by a billing checkpoint.

    PRD §3.1 step four ages "every membership whose ``dues_status`` is
    ``INVOICED``, whose ``balance_due_cents`` is greater than 0, and whose
    season's ``dues_due_date`` is strictly earlier than the effective date".
    """
    ctx = setup_active_membership(api, **kwargs)
    ctx["season"] = run_billing_run(api, ctx["season"]["id"])
    ctx["membership"] = read_membership(api, ctx["membership"]["id"])
    return ctx


# ── Guards, certifications and shifts (PRD §3.8) ──────

CERT_ISSUED_ON = "2026-06-01"
CERT_EXPIRES_ON = "2028-05-31"


def certify(api: ApiClient, lifeguard_id: str, cert_type: str,
            issued_on: str = CERT_ISSUED_ON,
            expires_on: str = CERT_EXPIRES_ON) -> Dict[str, Any]:
    payload = f.certification_payload(
        lifeguard_id=lifeguard_id, cert_type=cert_type,
        issued_on=issued_on, expires_on=expires_on,
    )
    return get_success_data(api.create_certification(payload, POOL_MANAGER), 201)


def setup_certified_guard(api: ApiClient, full_name: str = "Dana Reyes",
                          expires_on: str = CERT_EXPIRES_ON,
                          **overrides: Any) -> Dict[str, Any]:
    """A guard holding both wall certifications: LIFEGUARD and CPR_AED.

    PRD §3.8 refuses to schedule "unless the guard holds a certification with
    ``cert_type`` ``LIFEGUARD`` and ``status`` ``VALID`` and another with
    ``cert_type`` ``CPR_AED`` and ``status`` ``VALID``".
    """
    guard = create_lifeguard(api, full_name=full_name, **overrides)
    lifeguard_cert = certify(api, guard["id"], CertType.LIFEGUARD,
                             expires_on=expires_on)
    cpr_cert = certify(api, guard["id"], CertType.CPR_AED, expires_on=expires_on)
    return {
        "lifeguard": read_lifeguard(api, guard["id"]),
        "lifeguard_cert": lifeguard_cert,
        "cpr_cert": cpr_cert,
    }


def schedule_shift(api: ApiClient, lifeguard_id: str, season_id: str,
                   start_iso: str, end_iso: str,
                   shift_role: str = ShiftRole.PRIMARY) -> Dict[str, Any]:
    payload = f.guard_shift_payload(
        lifeguard_id=lifeguard_id, season_id=season_id,
        start_iso=start_iso, end_iso=end_iso, shift_role=shift_role,
    )
    return get_success_data(api.create_guard_shift(payload, POOL_MANAGER), 201)


def transition_shift(api: ApiClient, shift_id: str,
                     to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_guard_shift(
            shift_id, f.transition_payload(to_status), POOL_MANAGER
        ),
        200,
    )


def setup_confirmed_shift(api: ApiClient, season_id: str, start_iso: str,
                          end_iso: str, full_name: str = "Dana Reyes",
                          shift_role: str = ShiftRole.PRIMARY) -> Dict[str, Any]:
    """A certified guard on a CONFIRMED shift covering the given interval.

    Only CONFIRMED shifts count toward coverage: PRD §3.8 says "Shifts merely
    ``SCHEDULED`` do not count toward coverage, because an unconfirmed guard may
    not show".
    """
    guard = setup_certified_guard(api, full_name=full_name)
    shift = schedule_shift(api, guard["lifeguard"]["id"], season_id,
                           start_iso, end_iso, shift_role)
    shift = transition_shift(api, shift["id"], "CONFIRMED")
    return {"lifeguard": guard["lifeguard"], "certs": guard, "shift": shift}


def setup_coverage(api: ApiClient, season_id: str, start_iso: str, end_iso: str,
                   guard_count: int) -> List[Dict[str, Any]]:
    """``guard_count`` distinct certified guards on CONFIRMED covering shifts."""
    return [
        setup_confirmed_shift(api, season_id, start_iso, end_iso,
                              full_name=f"Guard {index + 1}")
        for index in range(guard_count)
    ]


# ── Swim team, meets and volunteer rosters (PRD §3.6) ──


def register_swimmer(api: ApiClient, membership_id: str, season_id: str,
                     swimmer_name: str = "Ben Nguyen",
                     swimmer_birthdate: str = "2014-03-11",
                     squad: str = Squad.JUNIOR,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    payload = f.registration_payload(
        membership_id=membership_id, season_id=season_id,
        swimmer_name=swimmer_name, swimmer_birthdate=swimmer_birthdate,
        squad=squad,
    )
    return get_success_data(
        api.create_registration(payload, headers or SWIM_TEAM_COACH), 201
    )


def transition_registration(api: ApiClient, registration_id: str,
                            to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_registration(
            registration_id, f.transition_payload(to_status), SWIM_TEAM_COACH
        ),
        200,
    )


def setup_confirmed_registration(api: ApiClient, ctx: Dict[str, Any],
                                 swimmer_name: str = "Ben Nguyen",
                                 swimmer_birthdate: str = "2014-03-11",
                                 squad: str = Squad.JUNIOR) -> Dict[str, Any]:
    """Register a swimmer and confirm them onto the squad.

    PRD §3.6 requires the membership to be "``access_status`` ``ACTIVE`` and
    ``dues_status`` ``INVOICED`` or ``PAID``" before a confirmation takes, so
    the caller must pass an already-invoiced context.
    """
    reg = register_swimmer(api, ctx["membership"]["id"], ctx["season"]["id"],
                           swimmer_name, swimmer_birthdate, squad)
    return transition_registration(api, reg["id"], "CONFIRMED")


def create_meet(api: ApiClient, season_id: str, name: str = "Home Invitational",
                start_iso: str = "2027-07-10T08:00:00Z",
                end_iso: str = "2027-07-10T14:00:00Z",
                expected_swimmers: int = 20,
                volunteer_slots_required: int = 4) -> Dict[str, Any]:
    payload = f.meet_payload(
        season_id=season_id, name=name, start_iso=start_iso, end_iso=end_iso,
        expected_swimmers=expected_swimmers,
        volunteer_slots_required=volunteer_slots_required,
    )
    return get_success_data(api.create_meet(payload, SWIM_TEAM_COACH), 201)


def assign_volunteer(api: ApiClient, meet_id: str, registration_id: str,
                     job_code: str) -> Dict[str, Any]:
    payload = f.volunteer_assignment_payload(
        meet_id=meet_id, swim_team_registration_id=registration_id,
        job_code=job_code,
    )
    return get_success_data(
        api.create_volunteer_assignment(payload, SWIM_TEAM_COACH), 201
    )


def close_roster(api: ApiClient, meet_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_meet_roster(meet_id, SWIM_TEAM_COACH), 200)


def setup_meet_with_assignment(api: ApiClient, ctx: Dict[str, Any],
                               volunteer_slots_required: int = 2,
                               job_code: str = "STARTER",
                               start_iso: str = "2027-07-10T08:00:00Z",
                               end_iso: str = "2027-07-10T14:00:00Z"
                               ) -> Dict[str, Any]:
    """A meet with one CONFIRMED swimmer holding one ASSIGNED volunteer job."""
    registration = setup_confirmed_registration(api, ctx)
    meet = create_meet(api, ctx["season"]["id"], start_iso=start_iso,
                       end_iso=end_iso,
                       volunteer_slots_required=volunteer_slots_required)
    assignment = assign_volunteer(api, meet["id"], registration["id"], job_code)
    return {
        "registration": registration,
        "meet": read_meet(api, meet["id"]),
        "assignment": assignment,
    }


# ── Waitlist queue (PRD §3.2) ─────────────────────────


def join_waitlist(api: ApiClient, household_id: str, category_id: str,
                  priority_tier: Any = Ellipsis,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    payload = f.waitlist_entry_payload(
        household_id=household_id, membership_category_id=category_id,
        priority_tier=priority_tier,
    )
    return get_success_data(
        api.create_waitlist_entry(payload, headers or MEMBERSHIP_CHAIR), 201
    )


def extend_next_offer(api: ApiClient, category_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.next_waitlist_offer(f.next_offer_payload(category_id),
                                MEMBERSHIP_CHAIR),
        200,
    )


def respond_to_offer(api: ApiClient, entry_id: str, household_id: str,
                     decision: str, requeue: Any = Ellipsis) -> Dict[str, Any]:
    """Only the charged household may respond (PRD §3.2)."""
    payload = f.waitlist_respond_payload(decision=decision, requeue=requeue)
    return get_success_data(
        api.respond_waitlist_entry(entry_id, payload,
                                   make_member_headers(household_id)),
        200,
    )


def setup_accepted_waitlist_entry(api: ApiClient, household_id: str,
                                  category_id: str) -> Dict[str, Any]:
    """A household holding an ACCEPTED entry, ready to be sold a membership."""
    join_waitlist(api, household_id, category_id)
    offered = extend_next_offer(api, category_id)
    return respond_to_offer(api, offered["id"], household_id, "ACCEPT")


# ── Parties (PRD §3.7) ────────────────────────────────


def request_party(api: ApiClient, membership_id: str,
                  headers: Optional[Dict[str, str]] = None,
                  zone: str = Zone.PAVILION,
                  start_iso: str = "2027-07-15T14:00:00Z",
                  end_iso: str = "2027-07-15T18:00:00Z",
                  guest_count: int = 8,
                  host_party_size: int = 4) -> Dict[str, Any]:
    payload = f.party_reservation_payload(
        membership_id=membership_id, zone=zone, start_iso=start_iso,
        end_iso=end_iso, guest_count=guest_count,
        host_party_size=host_party_size,
    )
    return get_success_data(
        api.create_party_reservation(payload, headers or POOL_MANAGER), 201
    )


def transition_party(api: ApiClient, reservation_id: str, to_status: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    return get_success_data(
        api.transition_party_reservation(
            reservation_id, f.transition_payload(to_status),
            headers or POOL_MANAGER,
        ),
        200,
    )


# ─────────────────────────────────────────────────────
# Tier 4 — accumulation and threshold targeting
# ─────────────────────────────────────────────────────


def record_visit(api: ApiClient, membership_id: str, household_id: str,
                 guest_count: int, visit_start_iso: str,
                 sponsor_name: str = "Alice Nguyen",
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Record a guest visit against the household's *current* version.

    PRD §2.7 makes ``expected_household_version`` non-optional and requires it to
    equal "the sponsoring household's current ``version``", so the helper reads
    the household immediately before writing.
    """
    household = read_household(api, household_id)
    payload = f.guest_visit_payload(
        membership_id=membership_id,
        expected_household_version=household["version"],
        sponsor_name=sponsor_name, guest_count=guest_count,
        visit_start_iso=visit_start_iso,
    )
    return get_success_data(
        api.create_guest_visit(payload, headers or POOL_MANAGER), 201
    )


def void_visit(api: ApiClient, visit_id: str,
               reason: str = "Recorded against the wrong household"
               ) -> Dict[str, Any]:
    return get_success_data(
        api.void_guest_visit(visit_id, f.void_visit_payload(reason),
                             POOL_MANAGER),
        200,
    )


def contribute_reserve(api: ApiClient, season_id: str, amount_cents: int,
                       note: Any = Ellipsis) -> Dict[str, Any]:
    """Book a lump special assessment onto the season's reserve (PRD §3.10)."""
    payload = f.reserve_contribution_payload(
        amount_cents=amount_cents, note=note
    )
    return get_success_data(
        api.create_reserve_contribution(season_id, payload, TREASURER), 200
    )


def file_finding(api: ApiClient, season_id: str, severity: str,
                 headers: Optional[Dict[str, str]] = None,
                 inspected_on: str = "2027-07-01",
                 finding_code: str = "HC-410",
                 narrative: str = "Chlorine log incomplete for two days."
                 ) -> Dict[str, Any]:
    payload = f.inspection_finding_payload(
        season_id=season_id, severity=severity, inspected_on=inspected_on,
        finding_code=finding_code, narrative=narrative,
    )
    return get_success_data(
        api.create_inspection_finding(payload, headers or HEALTH_INSPECTOR), 201
    )


def transition_finding(api: ApiClient, finding_id: str, to_status: str,
                       headers: Dict[str, str],
                       remediation_note: Any = Ellipsis) -> Dict[str, Any]:
    payload = f.finding_transition_payload(
        to_status=to_status, remediation_note=remediation_note
    )
    return get_success_data(
        api.transition_inspection_finding(finding_id, payload, headers), 200
    )


def report_case(api: ApiClient, household_id: str, severity: str,
                headers: Optional[Dict[str, str]] = None,
                subject_name: str = "Teen guest of the household"
                ) -> Dict[str, Any]:
    payload = f.conduct_case_payload(
        household_id=household_id, severity=severity, subject_name=subject_name
    )
    return get_success_data(
        api.create_conduct_case(payload, headers or POOL_MANAGER), 201
    )


def transition_case(api: ApiClient, case_id: str, to_status: str,
                    headers: Dict[str, str],
                    sanction_type: Any = Ellipsis) -> Dict[str, Any]:
    payload = f.case_transition_payload(
        to_status=to_status, sanction_type=sanction_type
    )
    return get_success_data(
        api.transition_conduct_case(case_id, payload, headers), 200
    )


def sanction_household(api: ApiClient, household_id: str, severity: str,
                       sanction_type: str,
                       reporter: Optional[Dict[str, str]] = None,
                       decider: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    """Report a case and sanction it, honouring two-person control.

    PRD §2.8: "Sanctioning or dismissing a conduct case requires that
    ``X-User-ID`` differ from the case's ``reported_by_user_id``", so the
    reporter and the decider are deliberately different identities.
    """
    case = report_case(api, household_id, severity,
                       headers=reporter or POOL_MANAGER)
    transition_case(api, case["id"], "UNDER_REVIEW",
                    decider or BOARD_PRESIDENT)
    case = transition_case(api, case["id"], "SANCTIONED",
                           decider or BOARD_PRESIDENT,
                           sanction_type=sanction_type)
    return case


# ─────────────────────────────────────────────────────
# Tier 5 — terminal and finalisation states
# ─────────────────────────────────────────────────────


def write_off_membership(api: ApiClient, membership_id: str,
                         reason: str = "Uncollectible after two notices"
                         ) -> Dict[str, Any]:
    """PRD §3.4: available only from DELINQUENT; suspends ACTIVE access."""
    return get_success_data(
        api.write_off_membership(membership_id, f.write_off_payload(reason),
                                 TREASURER),
        200,
    )


def close_season(api: ApiClient, season_id: str) -> Dict[str, Any]:
    return get_success_data(api.close_season(season_id, POOL_MANAGER), 200)


def reinstate_household(api: ApiClient, household_id: str,
                        to_standing: str = "GOOD_STANDING",
                        reason: str = "Board reinstatement after review"
                        ) -> Dict[str, Any]:
    payload = f.standing_transition_payload(
        to_standing=to_standing, reason=reason
    )
    return get_success_data(
        api.create_standing_transition(household_id, payload, BOARD_PRESIDENT),
        200,
    )


def propose_project(api: ApiClient, season_id: str, budget_cents: int,
                    title: str = "Main pool resurfacing",
                    project_kind: Any = Ellipsis) -> Dict[str, Any]:
    payload = f.capital_project_payload(
        funding_season_id=season_id, budget_cents=budget_cents, title=title,
        **({} if project_kind is Ellipsis else {"project_kind": project_kind}),
    )
    return get_success_data(api.create_capital_project(payload, TREASURER), 201)


def setup_approved_project(api: ApiClient, season_id: str, budget_cents: int,
                           title: str = "Main pool resurfacing"
                           ) -> Dict[str, Any]:
    """A project approved by a president who is not the proposing treasurer."""
    project = propose_project(api, season_id, budget_cents, title)
    return get_success_data(
        api.transition_capital_project(
            project["id"], f.transition_payload("APPROVED"), BOARD_PRESIDENT
        ),
        200,
    )


def draw_funds(api: ApiClient, project_id: str, draw_amount_cents: int,
               expected_version: Optional[int] = None) -> Dict[str, Any]:
    """Draw reserve funds, reading the project's version when not supplied."""
    if expected_version is None:
        expected_version = read_project(api, project_id)["version"]
    payload = f.fund_project_payload(
        draw_amount_cents=draw_amount_cents,
        expected_capital_project_version=expected_version,
    )
    return get_success_data(
        api.fund_capital_project(project_id, payload, TREASURER), 200
    )


def setup_funded_project(api: ApiClient, season_id: str, budget_cents: int,
                         draw_amount_cents: int) -> Dict[str, Any]:
    """An APPROVED project carrying a first successful draw, so it is FUNDED."""
    project = setup_approved_project(api, season_id, budget_cents)
    return draw_funds(api, project["id"], draw_amount_cents,
                      project["version"])


def setup_party_ready_household(api: ApiClient,
                                clock_iso: str = "2027-07-01T09:00:00Z",
                                **kwargs: Any) -> Dict[str, Any]:
    """An ACTIVE COUPLE membership able to clear both fiscal party gates.

    The COUPLE category carries ``bond_cents`` of 0, so PRD §3.7's requirement
    that "``bond_paid_cents`` having reached the category's ``bond_cents``" is
    satisfied without a bond payment, and an invoiced-but-unpaid membership is
    not delinquent under PRD §3.4.
    """
    kwargs.setdefault("category", "COUPLE")
    kwargs.setdefault("member_count", 2)
    kwargs.setdefault("bond_payment_plan", BondPaymentPlan.FULL)
    return setup_active_membership(api, clock_iso=clock_iso, **kwargs)
