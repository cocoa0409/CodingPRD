"""Logical-clock test-driving surface and the month-close administrative run."""

from flask import Blueprint

from db import DB, parse_iso8601, touch
from errors import ApiError
from middleware import authenticate
from response import success
from routes import common
from services import calc, machines

bp = Blueprint("ops", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    """Set the logical clock to a supplied instant.

    PlatformAdmin may drive it and the Anonymous role is admitted here as well
    so fixtures can be established from an empty database (PRD §2.4). Advancing
    the clock changes no entity's version.
    """
    authenticate(["PlatformAdmin", "Anonymous"])
    data = common.body()
    instant = parse_iso8601(common.require(data, "to_iso8601"))
    if instant is None:
        raise ApiError("ERR_INVALID_REQUEST")
    DB.clock = instant
    # The scaffold declares this operation's output as null, so the 2xx body
    # carries an empty object (PRD §2.2).
    return success({})


@bp.post("/api/month-close/runs")
def month_close_run():
    """Close the reporting period — the widest-reaching operation in the API.

    PRD §3.6, in order: re-band every utilization cycle, advance each cycle's
    reporting index, score shortfall fees then drive the compliance cascade,
    recompute each agreement's commitment state, decay then recompute the
    penalty balance, return expired acceptance windows to DRAFT, expire
    contracts the clock has reached, sweep evidence, and detect dormancy.
    """
    authenticate(["PlatformAdmin"])
    data = common.body()
    as_of = data.get("as_of_utc")
    if as_of is not None:
        parsed = parse_iso8601(as_of)
        if parsed is None:
            raise ApiError("ERR_INVALID_REQUEST")
        DB.clock = parsed

    # 1. Re-band every utilization cycle from the completed cases in its window.
    for cycle in DB.utilization_cycles.values():
        cycle["utilization_band"] = calc.utilization_band(cycle)

    # 2. Advance each cycle's reporting index.
    for cycle in DB.utilization_cycles.values():
        cycle["reporting_period_index"] = int(cycle.get("reporting_period_index") or 0) + 1
        touch(cycle)

    # 3. Score each agreement's shortfall fee, then drive the compliance cascade.
    for agreement in DB.placement_agreements.values():
        account = DB.hospital_accounts.get(agreement.get("hospital_account_id"))
        shortfall = calc.shortfall_procedures(agreement)
        waived = bool(agreement.get("is_shortfall_waived"))
        agreement["shortfall_procedures"] = shortfall
        agreement["last_shortfall_fee_cents"] = calc.shortfall_fee(agreement)
        # The streak counts consecutive prior closed intervals with a shortfall.
        # The provisional view at reconciliation ignores is_shortfall_waived.
        if shortfall > 0:
            agreement["_shortfall_streak"] = int(agreement.get("_shortfall_streak") or 0) + 1
        else:
            agreement["_shortfall_streak"] = 0
        machines.refresh_commitment(agreement)
        # The escalation ladder can force REMEDIATION_REQUIRED regardless of
        # the tier produced by the ladder above.
        if calc.escalation_effective(agreement):
            agreement["compliance_status"] = "REMEDIATION_REQUIRED"
        elif not waived:
            # PRD §2.12: "`MEETS_COMMITMENT` applies when the current interval's
            # shortfall is 0 or has been waived. `SHORTFALL_WARNING` applies when
            # the tier is 10 or below. `SHORTFALL_CHARGEABLE` applies when the
            # tier is above 10 and at or below 25. `NON_COMPLIANT` applies when
            # the tier exceeds 25." The tier is written even at a zero shortfall,
            # because the streak is what the ladder reads.
            tier = calc.compliance_tier(agreement)
            if shortfall == 0:
                agreement["compliance_status"] = "MEETS_COMMITMENT"
            elif tier <= 10:
                agreement["compliance_status"] = "SHORTFALL_WARNING"
            elif tier <= 25:
                agreement["compliance_status"] = "SHORTFALL_CHARGEABLE"
            else:
                agreement["compliance_status"] = "NON_COMPLIANT"
            if tier > 25:
                if agreement.get("_prior_tier_above_25"):
                    agreement["compliance_status"] = "REMEDIATION_REQUIRED"
                agreement["_prior_tier_above_25"] = True
            else:
                agreement["_prior_tier_above_25"] = False
        # The waiver forgives exactly one interval.
        agreement["is_shortfall_waived"] = False
        touch(agreement)
        if account is not None:
            machines.refresh_posture(account)

    # 4. Decay the penalty balance, then recompute it.
    for account in DB.hospital_accounts.values():
        balance = int(account.get("_coverage_ceiling_points") or 0)
        if balance > 0:
            balance -= calc.MONTHLY_DECAY_POINTS
        account["_penalty_balance"] = max(0, balance)
        account["_coverage_ceiling_points"] = 0

    # 5. Return agreements whose acceptance window has expired to DRAFT.
    for agreement in DB.placement_agreements.values():
        account = DB.hospital_accounts.get(agreement.get("hospital_account_id"))
        machines.agreement_acceptance_expire(agreement, account)

    # 6. Expire contracts the logical clock has reached.
    for contract in DB.service_contracts.values():
        machines.contract_expire(contract)

    # 7. Sweep credentialing evidence.
    machines.evidence_expiry_sweep()

    # 8. Reconcile expansion eligibility and expansion status.
    for system in DB.robot_systems.values():
        machines.refresh_system(system)

    # 9. Detect accounts that have gone dormant — an ACTIVE account with no
    #    case scheduled inside the just-closed cycle window.
    for account in DB.hospital_accounts.values():
        if account.get("account_status") != "ACTIVE":
            continue
        systems = calc.systems_of_account(account.get("id"))
        if not systems:
            continue
        scheduled = 0
        for system in systems:
            cycle = calc.current_cycle(system)
            if cycle is not None:
                scheduled += calc.scheduled_case_count(cycle)
        if scheduled == 0:
            machines.account_to_dormant(account)

    # The month-close run creates nothing addressable, so its 2xx body
    # carries an empty object (PRD §2.2).
    return success({})