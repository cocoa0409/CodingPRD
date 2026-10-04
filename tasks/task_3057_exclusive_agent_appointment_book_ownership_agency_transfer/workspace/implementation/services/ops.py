"""The periodic agency ops sweep and the clock-driven re-evaluations
(PRD §3.9, §2.11; SCAFFOLD Agent / Agreement / Claim run_ops transitions).
"""

from decimal import Decimal

import clock
import db
from money import dec
from services import calculations as calc
from services import recompute


def run_ops(agency_id):
    """One sweep of the agency roll.

    In order: advance ops_run_index, roll the anniversary term, expire active
    agreements whose sponsors can no longer support them, sweep license
    expiries, shelf-reopen settled claims, acknowledge low market need, then
    recompute performance and valuation.
    """
    agency = db.agency_rows().get(agency_id)
    if agency is None:
        return None

    agency["ops_run_index"] = int(agency.get("ops_run_index", 0)) + 1
    _roll_term_if_due(agency)
    _expire_active_agreements(agency)
    _sweep_license_expiries(agency)
    _shelf_reopen_claims(agency)
    _acknowledge_market_need(agency)

    recompute.recompute_agency(agency_id)
    return agency


def _roll_term_if_due(agency):
    """At the anniversary boundary the term rolls and the trailing commission
    resets to zero so the new term starts from a clean figure (PRD §2.11).

    The unused allowance carries into the following term as that term's
    opening balance (PRD §2.7: the carryover leads the ledger).
    """
    start = agency.get("term_start_date")
    if not start:
        return
    boundary = clock.add_months(clock.parse_iso(start), 12)
    if clock.now() >= boundary:
        for agreement in recompute.agreements_for(agency["id"]):
            agreement["carryover_input_cents"] = agreement.get(
                "allowance_carryover_cents", Decimal(0))
        agency["term_start_date"] = clock.iso()
        agency["annualized_commission_cents"] = Decimal(0)
        agency["rolling_base_cents"] = Decimal(0)


def _expire_active_agreements(agency):
    """SUSPENDED agreements expire; a live sponsor whose agent can no longer
    support the agreement suspends it and pulls the agent out of force."""
    for agreement in recompute.agreements_for(agency["id"]):
        if agreement["status"] == "SUSPENDED":
            agreement["status"] = "TERMINATED"
            recompute.touch(agreement)
            recompute.terminate_staff_under_agency(agency["id"])
            continue
        if agreement["status"] != "ACTIVE":
            continue
        agent = db.agent_rows().get(agreement["agent_id"])
        if agent is None:
            continue
        if agent["license_status"] != "LICENSED":
            agreement["status"] = "SUSPENDED"
            recompute.touch(agreement)
            if agent["status"] == "ACTIVE":
                agent["status"] = "PENDING_TERMINATION"
                recompute.touch(agent)
            recompute.terminate_staff_under_agency(agency["id"])


def _sweep_license_expiries(agency):
    for agent in db.agent_rows().values():
        if agent.get("agency_id") != agency["id"]:
            continue
        before = agent["license_status"]
        recompute.refresh_license_status(agent["id"])
        if agent["license_status"] != before:
            recompute.touch(agent)


def _shelf_reopen_claims(agency):
    """A PAID claim whose policy was *restored* re-opens: policy_paid_cents -> 0.

    Only a policy that has actually been restored since the claim was paid
    qualifies.  A policy that has simply stayed OPEN is not restored, so its
    settled claim is left untouched by the sweep.
    """
    policy_ids = {p["id"] for p in calc.agency_policies(agency["id"])}
    for claim in db.claim_rows().values():
        if claim["policy_id"] not in policy_ids:
            continue
        if claim["status"] != "PAID":
            continue
        policy = db.policy_rows().get(claim["policy_id"])
        if policy is None or policy["status"] != "OPEN":
            continue
        if not policy.get("restored"):
            continue
        claim["status"] = "OPEN"
        claim["policy_paid_cents"] = Decimal(0)
        recompute.touch(claim)
        recompute.cascade_from_claim(claim["id"], bump_policy=True, bump_agency=False)


def _acknowledge_market_need(agency):
    """state_market_need_acknowledged := true when the agency's score is below 40."""
    if dec(agency["market_need_score"]) >= 40:
        return
    for agent in db.agent_rows().values():
        if agent.get("agency_id") == agency["id"] and not agent["state_market_need_acknowledged"]:
            agent["state_market_need_acknowledged"] = True
            recompute.touch(agent)


def on_clock_advanced():
    """Re-evaluate license expiry and retention/deadline windows (PRD §2.11)."""
    for agent_id in list(db.agent_rows().keys()):
        before = db.agent_rows()[agent_id]["license_status"]
        recompute.refresh_license_status(agent_id)
        agent = db.agent_rows()[agent_id]
        if agent["license_status"] != before:
            recompute.touch(agent)
        recompute.refresh_agent_is_new(agent_id)

    for transfer_id in list(db.transfer_rows().keys()):
        transfer = db.transfer_rows()[transfer_id]
        policies = [p for p in db.policy_rows().values()
                    if p.get("book_transfer_id") == transfer_id]
        successor = transfer.get("successor_agent_id")
        retained = [p for p in policies
                    if p["status"] == "OPEN" and p["holder_agent_id"] == successor]
        transfer["retained_policy_count"] = len(retained)
        transfer["retention_pct"] = calc.retention_pct(len(retained), len(policies))
        transfer["retention_met"] = calc.retention_met(transfer["retention_pct"])
        transfer["settlement_payable_cents"] = calc.book_transfer_settlement_cents(
            policies, clock.now(), for_cause=bool(transfer.get("for_cause")))
        recompute.touch(transfer)

    for agreement in list(db.agreement_rows().values()):
        recompute.recompute_termination_value(agreement, bump=True)


def maybe_promote_ceasing_agents(agency_id=None):
    """PENDING_TERMINATION -> TRANSITIONING once a same-region candidate agency
    exists with status ACTIVE and agency_level_units below twelve (PRD §3.7)."""
    promoted = False
    for agent in list(db.agent_rows().values()):
        if agent["status"] != "PENDING_TERMINATION":
            continue
        if agency_id is not None and agent.get("agency_id") != agency_id:
            continue
        agency = db.agency_rows().get(agent.get("agency_id"))
        if agency is None:
            continue
        candidates = _target_agencies(agency, exclude_agency_id=agency["id"])
        if not candidates:
            continue
        agent["status"] = "TRANSITIONING"
        recompute.touch(agent)
        promoted = True
    return promoted


def _target_agencies(ceasing_agency, exclude_agency_id=None):
    out = []
    for candidate in db.agency_rows().values():
        if candidate["id"] == exclude_agency_id:
            continue
        if candidate["status"] != "ACTIVE":
            continue
        if candidate["region_code"] != ceasing_agency["region_code"]:
            continue
        if calc.agency_level_units(candidate["id"]) >= calc.AGENCY_UNIT_CAP:
            continue
        out.append(candidate)
    return out