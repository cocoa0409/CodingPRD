"""Multi-resource cascades.

PRD section 2.9: every entity a cascade touches has its `updated_at` refreshed and its
`version` incremented, and the whole cascade completes inside the triggering request.
"""

import calc
import db
from db import store


# --------------------------------------------------------------------------------------
# practice blocks
# --------------------------------------------------------------------------------------

def cancel_future_blocks(player_id, reason):
    """Cancel every block still SCHEDULED whose starts_at is STRICTLY LATER than the
    current instant and which lists this player.  Used by §3.5, §3.6 and §3.9."""
    instant = db.now()
    cancelled = []
    for block in db.in_creation_order(list(store.practice_blocks.values())):
        if block["block_status"] != "SCHEDULED":
            continue
        if not block["starts_at"] > instant:
            continue
        if player_id not in block["participant_player_ids"]:
            continue
        block["block_status"] = "CANCELLED"
        block["cancel_reason"] = reason
        db.touch(block)
        cancelled.append(block)
    return cancelled


# --------------------------------------------------------------------------------------
# wellness escalation (PRD section 3.6)
# --------------------------------------------------------------------------------------

def refresh_burnout_and_escalate(contract):
    """Recompute the persisted rolling score, then escalate the obligation dimension.

    The wellness dimension is escalation-only, so a score that has fallen back below a
    threshold never restores a WARNED or BREACH contract to COMPLIANT.
    """
    score = calc.rolling_burnout_score(contract)
    contract["burnout_score"] = score
    status = contract["obligation_status"]
    target = None
    if score >= calc.BURNOUT_BREACH_THRESHOLD and status in ("COMPLIANT", "WARNED"):
        target = "BREACH"
    elif score >= calc.BURNOUT_WARN_THRESHOLD and status == "COMPLIANT":
        target = "WARNED"
    if target is None:
        return score, None
    contract["obligation_status"] = target
    if target == "BREACH":
        # Only a breach stamps the hold and flags the organization.
        contract["wellness_hold_until"] = db.add_days(db.now(), calc.WELLNESS_HOLD_DAYS)
        organization = store.organizations.get(contract["organization_id"])
        if organization is not None:
            organization["wellness_flag_count"] += 1
            db.touch(organization)
    # Both escalations clear the player's future calendar.
    cancel_future_blocks(contract["player_id"], "WELLNESS_HOLD")
    return score, target


# --------------------------------------------------------------------------------------
# deliverable voiding (PRD section 3.7)
# --------------------------------------------------------------------------------------

def void_assignments_of_contract(contract):
    """Voiding is only ever a cascade.  A voided row leaves both counters, and a deal that
    drops below its quota bubbles FULFILLED -> ACTIVE in the same request."""
    touched_deals = set()
    for assignment in db.in_creation_order(list(store.assignments.values())):
        if assignment["contract_id"] != contract["id"]:
            continue
        if assignment["assignment_status"] not in ("ASSIGNED", "SUBMITTED", "APPROVED",
                                                   "REJECTED"):
            continue
        assignment["assignment_status"] = "VOIDED"
        db.touch(assignment)
        touched_deals.add(assignment["sponsorship_deal_id"])
    for deal_id in touched_deals:
        deal = store.deals.get(deal_id)
        if deal is None:
            continue
        if deal["deal_status"] == "FULFILLED" and not calc.deal_is_fulfilled(deal):
            deal["deal_status"] = "ACTIVE"
        db.touch(deal)


# --------------------------------------------------------------------------------------
# termination (PRD section 3.9)
# --------------------------------------------------------------------------------------

def terminate_contract(contract, organization, league):
    """The four-link cascade of a RELEASE or TRANSFER_OUT execution.

    `committed_salary_cents` and `active_roster_count` are derived from the contract set,
    so moving the contract out of the ACTIVE-or-SUSPENDED set already moves both counters
    by exactly the frozen `released_cap_cents`; the organization is still touched so its
    version advances as PRD section 2.9 requires.
    """
    contract["contract_status"] = "TERMINATED"
    db.touch(contract)

    player = store.players.get(contract["player_id"])
    if player is not None:
        player["player_status"] = "FREE_AGENT"
        player["current_organization_id"] = None
        cooldown_days = league["free_agency_cooldown_days"] if league else 0
        player["free_agency_window_ends_at"] = db.add_days(db.now(), cooldown_days)
        player["last_release_organization_id"] = organization["id"]
        db.touch(player)

    db.touch(organization)
    void_assignments_of_contract(contract)
    cancel_future_blocks(contract["player_id"], "CONTRACT_SUSPENDED")


def restore_contract(contract, organization, move):
    """The compensating reversal of §3.9.  Blocks stay cancelled and deliverables stay
    voided -- only the salary quantity is conserved."""
    contract["contract_status"] = "ACTIVE"
    db.touch(contract)

    player = store.players.get(contract["player_id"])
    if player is not None:
        player["player_status"] = "SIGNED"
        player["current_organization_id"] = organization["id"]
        player["free_agency_window_ends_at"] = None
        player["last_release_organization_id"] = None
        db.touch(player)

    db.touch(organization)
    move["buyout_credit_cents"] = 0
    move["commission_tier_bp"] = 0
    move["agent_commission_cents"] = 0
    move["net_to_org_cents"] = 0
    move["released_cap_cents"] = 0
