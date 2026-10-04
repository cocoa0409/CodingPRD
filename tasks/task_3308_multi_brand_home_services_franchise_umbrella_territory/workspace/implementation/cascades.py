"""Cascading side effects (PRD 2.13, 3.2, 3.4, 3.7).

Every cascade bumps the affected record's own `version` and `updated_at`,
because a cascaded write is a mutation like any other (PRD 2.9).
"""
from store import db, touch, now_iso
import derived
from config import REMEDIATION_OPEN_SET


def stand_down_agreement_territory(agreement):
    """Suspend: the bound territory retains its holder and its households until a
    reclaim actually fires (PRD 3.7)."""
    territory = db.territories.get(agreement.get("territory_id"))
    if territory is None:
        return None
    if territory.get("status") in ("AWARDED", "ACTIVE"):
        territory["status"] = "PENDING_REALLOCATION"
        derived.refresh_territory(territory)
        touch(territory)
    return territory


def reinstate_agreement_territory(agreement):
    territory = db.territories.get(agreement.get("territory_id"))
    if territory is None:
        return None
    if territory.get("status") == "PENDING_REALLOCATION":
        territory["status"] = "ACTIVE"
        derived.refresh_territory(territory)
        touch(territory)
    return territory


def activate_agreement_territory(agreement):
    """The bound territory follows an AWARDED agreement to ACTIVE automatically."""
    territory = db.territories.get(agreement.get("territory_id"))
    if territory is None:
        return None
    if territory.get("status") == "AWARDED":
        territory["status"] = "ACTIVE"
        derived.refresh_territory(territory)
        touch(territory)
    return territory


def recompute_franchisee(franchisee):
    if franchisee is None:
        return None
    derived.refresh_franchisee(franchisee)
    touch(franchisee)
    return franchisee


def expire_agreement_cascade(agreement):
    """EXPIRED: recompute the count; terminate the franchisee at zero; release
    the territory (holder cleared, PENDING_REALLOCATION, zero households)."""
    franchisee = db.franchisees.get(agreement.get("franchisee_id"))
    territory = db.territories.get(agreement.get("territory_id"))
    if territory is not None:
        territory["franchisee_id"] = None
        territory["status"] = "PENDING_REALLOCATION"
        territory["allocated_households"] = 0
        touch(territory)
    if franchisee is not None:
        derived.refresh_franchisee(franchisee)
        if int(franchisee.get("active_agreement_count") or 0) == 0:
            franchisee["status"] = "TERMINATED"
        touch(franchisee)
    return franchisee


def breach_cascade(work_order, account):
    """National-account economics: one more breach, one more credit, and a
    suspension once the count passes the program's tolerance."""
    if account is None:
        return None
    derived.refresh_account(account)
    if int(account.get("open_breach_count") or 0) > int(account.get("breach_tolerance") or 0):
        account["status"] = "SUSPENDED"
    touch(account)
    return account


def complete_referral_for_work_order(work_order):
    """A work order carrying an ACCEPTED referral moves it to COMPLETED."""
    if not work_order.get("referral_id"):
        return None
    referral = db.referrals.get(work_order.get("referral_id"))
    if referral is None or referral.get("status") != "ACCEPTED":
        return None
    referral["status"] = "COMPLETED"
    touch(referral)
    return referral


def reopen_agreement_standards(agreement):
    if agreement is None:
        return None
    derived.refresh_agreement(agreement)
    touch(agreement)
    return agreement


def stand_down_franchisee_territories(franchisee_id):
    """Deliberate franchisee suspension stands every held territory down."""
    changed = []
    for territory in db.territories.values():
        if territory.get("franchisee_id") != franchisee_id:
            continue
        if territory.get("status") in derived.TERRITORY_HOLDING_STATUSES:
            territory["status"] = "PENDING_REALLOCATION"
            derived.refresh_territory(territory)
            touch(territory)
            changed.append(territory)
    return changed


def terminate_transfer_assignments(territory_id):
    """Close out every live holding of a territory, stamping released_on."""
    closed = []
    for assignment in db.territory_assignments.values():
        if assignment.get("territory_id") != territory_id:
            continue
        if assignment.get("released_on") is None:
            assignment["released_on"] = now_iso()
            assignment["active"] = False
            touch(assignment)
            closed.append(assignment)
    return closed


def sweep_work_orders():
    """Sweep family 1: DISPATCHED|IN_PROGRESS whose sla_due_iso has been reached."""
    from store import parse_instant
    from calculations import labor_charge

    clock = derived.db.clock
    fired = []
    for work_order in list(db.work_orders.values()):
        if work_order.get("status") not in ("DISPATCHED", "IN_PROGRESS"):
            continue
        due = parse_instant(work_order.get("sla_due_iso") or "")
        if due is None or clock < due:
            continue
        work_order["status"] = "SLA_BREACHED"
        work_order["closed_clock_iso"] = derived.now_iso()
        work_order["labor_cents"] = labor_charge(work_order)
        work_order["revenue_cents"] = int(work_order.get("labor_cents") or 0) + int(
            work_order.get("parts_cents") or 0)
        touch(work_order)
        account = db.national_accounts.get(work_order.get("national_account_id"))
        if account is not None:
            breach_cascade(work_order, account)
        complete_referral_for_work_order(work_order)
        fired.append(work_order["id"])
    return fired


def sweep_agreements():
    """Sweep family 2: ACTIVE|RENEWAL_PENDING whose expires_on has been reached."""
    from store import parse_instant

    clock = derived.db.clock
    fired = []
    for agreement in list(db.agreements.values()):
        if agreement.get("lifecycle_status") not in ("ACTIVE", "RENEWAL_PENDING"):
            continue
        expires = parse_instant(agreement.get("expires_on") or "")
        if expires is None or clock < expires:
            continue
        agreement["lifecycle_status"] = "EXPIRED"
        touch(agreement)
        expire_agreement_cascade(agreement)
        fired.append(agreement["id"])
    return fired


def sweep_remediations():
    """Sweep family 3: OPEN remediations whose remediation_due_iso has been reached."""
    from store import parse_instant

    clock = derived.db.clock
    fired = []
    for audit in list(db.audits.values()):
        if audit.get("remediation_status") != "OPEN":
            continue
        due = parse_instant(audit.get("remediation_due_iso") or "")
        if due is None or clock < due:
            continue
        audit["remediation_status"] = "ESCALATED"
        touch(audit)
        agreement = db.agreements.get(audit.get("agreement_id"))
        if agreement is not None:
            derived.refresh_agreement(agreement)
            agreement["standards_status"] = "REMEDIATION_REQUIRED"
            touch(agreement)
        fired.append(audit["id"])
    return fired