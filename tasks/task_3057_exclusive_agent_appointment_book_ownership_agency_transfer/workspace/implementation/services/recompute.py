"""Cascading recomputation.

PRD §2.5 is explicit: derived figures are *recomputed from source*, never
accumulated as deltas, and every hop independently advances the affected
record's ``updated_at`` and increments its ``version``.  This module owns the
recompute_agency routine and the outward cascades that follow claims, policies,
staff and agreements.
"""

from decimal import Decimal

import clock
import db
from money import dec, round_cents
from services import calculations as calc

MONTHS_IN_TERM = 12


def touch(record):
    """Advance a record's updated_at and bump its version by one (PRD §2.4)."""
    record["updated_at"] = clock.iso()
    record["version"] = int(record.get("version", 1)) + 1
    return record


def _rebuild_agency_fields(agency_id):
    """Rebuild the agency's own derived figures in place (no version bump)."""
    agency = db.agency_rows().get(agency_id)
    if agency is None:
        return None
    agency["book_open_count"] = calc.book_open_count(agency_id)
    agency["exposure_inforce_cents"] = calc.exposure_inforce_cents(agency_id)
    agency["agency_level_units"] = calc.agency_level_units(agency_id)
    agency["agency_paid_claims_cents"] = calc.agency_paid_claims_cents(agency_id)
    agency["staffing_reimbursement_cents"] = calc.staffing_reimbursement_cents(agency_id)
    agency["loss_ratio"] = calc.loss_ratio(agency_id)
    agency["growth_new_pct"] = calc.growth_new_pct(
        agency["annualized_commission_cents"], agency.get("rolling_base_cents") or 0)
    agency["performance_status"] = calc.performance_status(
        agency["loss_ratio"], agency["growth_new_pct"])
    agency["agency_valuation_cents"] = calc.agency_valuation_cents(
        agency["annualized_commission_cents"],
        agency["agency_paid_claims_cents"],
        flagged=dec(agency["loss_ratio"]) > calc.LOSS_FLAG_THRESHOLD)
    return agency


def _rebuild_agreement_fields(agency_id):
    """Rebuild the agency's agreement-level derived ledger (no version bump)."""
    agreements = _agreements_for(agency_id)
    if not agreements:
        return []
    pool = calc.marketing_allowance_pool_cents(
        agency_id, agreements[0].get("carryover_input_cents", Decimal(0)))
    spent = calc.marketing_allowance_spent_cents(agency_id)
    carryover = round_cents(pool - spent)
    for agreement in agreements:
        agreement["marketing_allowance_pool_cents"] = pool
        agreement["marketing_allowance_spent_cents"] = spent
        agreement["allowance_carryover_cents"] = carryover
        agreement["staffing_reimbursement_cents"] = \
            calc.staffing_reimbursement_cents(agency_id)
        schedule = agreement.get("commission_schedule")
        agreement["direct_additions_commission_cents"] = \
            calc.direct_additions_commission_cents(agency_id, schedule)
        agreement["renewal_commission_cents"] = \
            calc.renewal_commission_cents(agency_id, schedule)
        agreement["direct_additions_revenue_cents"] = \
            calc.direct_additions_revenue_cents(agency_id, schedule)
    return agreements


def recompute_agency(agency_id):
    """Rebuild every derived book figure of one agency from its current children.

    PRD §2.4: a mutation of a derived property is a mutation of the owning
    record, so the recompute advances both the agency's and its agreement's
    ``updated_at`` and ``version``.
    """
    agency = _rebuild_agency_fields(agency_id)
    if agency is None:
        return None
    agreements = _rebuild_agreement_fields(agency_id)
    for agreement in agreements:
        touch(agreement)
    if agreements:
        agency["allowance_carryover_cents"] = agreements[0]["allowance_carryover_cents"]
        agency["marketing_allowance_pool_cents"] = \
            agreements[0]["marketing_allowance_pool_cents"]
        agency["marketing_allowance_spent_cents"] = \
            agreements[0]["marketing_allowance_spent_cents"]
    else:
        agency["marketing_allowance_spent_cents"] = \
            calc.marketing_allowance_spent_cents(agency_id)
        agency["marketing_allowance_pool_cents"] = Decimal(0)
    touch(agency)
    return agency


def recompute_agency_soft(agency_id):
    """The same rebuild WITHOUT advancing any version.  Used where the caller
    already owns the version bump, or where a system-side sweep must not
    invalidate a client's observed version."""
    agency = _rebuild_agency_fields(agency_id)
    if agency is None:
        return None
    agreements = _rebuild_agreement_fields(agency_id)
    if agreements:
        agency["allowance_carryover_cents"] = agreements[0]["allowance_carryover_cents"]
        agency["marketing_allowance_pool_cents"] = \
            agreements[0]["marketing_allowance_pool_cents"]
        agency["marketing_allowance_spent_cents"] = \
            agreements[0]["marketing_allowance_spent_cents"]
    else:
        agency["marketing_allowance_spent_cents"] = \
            calc.marketing_allowance_spent_cents(agency_id)
        agency["marketing_allowance_pool_cents"] = Decimal(0)
    agency["updated_at"] = clock.iso()
    return agency


def snapshot_agency(agency_id):
    """Compute the agency's derived figures WITHOUT mutating the store at all.
    Pure reads (GET /performance) use this."""
    agency = db.agency_rows().get(agency_id)
    if agency is None:
        return None
    exposure = calc.exposure_inforce_cents(agency_id)
    paid = calc.agency_paid_claims_cents(agency_id)
    ratio = calc.loss_ratio(agency_id)
    growth = calc.growth_new_pct(
        agency["annualized_commission_cents"], agency.get("rolling_base_cents") or 0)
    return {
        "book_open_count": calc.book_open_count(agency_id),
        "exposure_inforce_cents": exposure,
        "agency_paid_claims_cents": paid,
        "loss_ratio": ratio,
        "growth_new_pct": growth,
        "performance_status": calc.performance_status(ratio, growth),
        "agency_valuation_cents": calc.agency_valuation_cents(
            agency["annualized_commission_cents"], paid,
            flagged=dec(ratio) > calc.LOSS_FLAG_THRESHOLD),
    }


def _agreements_for(agency_id):
    rows = [a for a in db.agreement_rows().values() if a["agency_id"] == agency_id]
    rows.sort(key=lambda a: a["created_at"])
    return rows


def agreements_for(agency_id):
    return _agreements_for(agency_id)


def recompute_policy(policy_id):
    """Rebuild a policy's paid-claims roll-up, advancing its version."""
    policy = db.policy_rows().get(policy_id)
    if policy is None:
        return None
    policy["paid_claims_cents"] = calc.policy_paid_claims_cents(policy_id)
    touch(policy)
    return policy


def recompute_policy_soft(policy_id):
    policy = db.policy_rows().get(policy_id)
    if policy is None:
        return None
    policy["paid_claims_cents"] = calc.policy_paid_claims_cents(policy_id)
    policy["updated_at"] = clock.iso()
    return policy


def cascade_from_claim(claim_id, bump_policy=True, bump_agency=True):
    """The deepest cascade (PRD §3.8): policy claims -> agency claims ->
    loss ratio -> performance status / termination value / agency valuation."""
    claim = db.claim_rows().get(claim_id)
    if claim is None:
        return
    policy = db.policy_rows().get(claim["policy_id"])
    if policy is None:
        return

    if bump_policy:
        recompute_policy(policy["id"])
    else:
        recompute_policy_soft(policy["id"])

    agency_id = policy["owner_agency_id"]
    if bump_agency:
        recompute_agency(agency_id)
    else:
        recompute_agency_soft(agency_id)

    # termination value on the agency's agreement follows the loss ratio
    for agreement in _agreements_for(agency_id):
        recompute_termination_value(agreement, bump=bump_agency)
        if bump_agency:
            touch(agreement)


def recompute_termination_value(agreement, bump=False):
    agency = db.agency_rows().get(agreement["agency_id"])
    if agency is None:
        return
    agent = db.agent_rows().get(agreement["agent_id"])
    appointment_iso = agent.get("appointment_date") if agent else None
    current = clock.now()
    bonus = calc.cessation_bonus_cents(
        agency["id"], agreement["created_at"], current)
    agreement["termination_value_cents"] = calc.contract_value_cents(
        agency, appointment_iso, bonus, current)
    if bump:
        touch(agreement)


def recompute_book_transfer(transfer_id):
    """Rebuild a transfer's counts, retention and settlement (PRD §3.7)."""
    transfer = db.transfer_rows().get(transfer_id)
    if transfer is None:
        return None
    policies = [p for p in db.policy_rows().values()
                if p.get("book_transfer_id") == transfer_id]
    successor = transfer.get("successor_agent_id")
    retained = [p for p in policies
                if p["status"] == "OPEN" and p["holder_agent_id"] == successor]
    transfer["transferred_policy_count"] = len(policies)
    transfer["retained_policy_count"] = len(retained)
    transfer["retention_pct"] = calc.retention_pct(len(retained), len(policies))
    transfer["retention_met"] = calc.retention_met(transfer["retention_pct"])
    transfer["settlement_payable_cents"] = calc.book_transfer_settlement_cents(
        policies, clock.now(), for_cause=bool(transfer.get("for_cause")))
    touch(transfer)
    return transfer


def refresh_agent_is_new(agent_id):
    """is_new_agent is a derived recency flag: true for 24 months from appointment."""
    agent = db.agent_rows().get(agent_id)
    if agent is None:
        return None
    if not agent.get("appointment_date"):
        agent["is_new_agent"] = True
        return agent
    appointment = clock.parse_iso(agent["appointment_date"])
    horizon = clock.add_months(appointment, 24)
    agent["is_new_agent"] = clock.now() < horizon
    return agent


def refresh_license_status(agent_id):
    """A license whose expiry precedes the current instant is EXPIRED (PRD §2.10)."""
    agent = db.agent_rows().get(agent_id)
    if agent is None:
        return None
    expiry = agent.get("license_expiry_date")
    if agent.get("license_status") == "NOT_LICENSED":
        return agent
    if expiry is None:
        return agent
    if clock.parse_iso(expiry) < clock.now():
        agent["license_status"] = "EXPIRED"
    return agent


def active_staff_under_agency(agency_id):
    return [m for m in db.staff_rows().values()
            if m["agency_id"] == agency_id and m["status"] == "ACTIVE"]


def terminate_staff_under_agency(agency_id):
    """Every ACTIVE member under the agency becomes TERMINATED, then the two-hop
    cascade runs: agency_level_units, then staffing_reimbursement (PRD §3.5)."""
    changed = False
    for member in active_staff_under_agency(agency_id):
        member["status"] = "TERMINATED"
        touch(member)
        changed = True
    if changed:
        agency = db.agency_rows().get(agency_id)
        if agency is not None:
            agency["agency_level_units"] = calc.agency_level_units(agency_id)
            agency["staffing_reimbursement_cents"] = \
                calc.staffing_reimbursement_cents(agency_id)
            touch(agency)
            for agreement in _agreements_for(agency_id):
                agreement["staffing_reimbursement_cents"] = \
                    calc.staffing_reimbursement_cents(agency_id)
                touch(agreement)
    return changed