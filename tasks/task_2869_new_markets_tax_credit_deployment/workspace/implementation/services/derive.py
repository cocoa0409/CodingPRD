"""Derived values, cascades and shared lookups (PRD sections 2.7, 3.1, 3.3, 3.5)."""
from decimal import Decimal

import clock
from db import db
from services import calc

QUALIFYING_QLICI_STATUSES = ("DEPLOYED", "PARTIALLY_REPAID")
RECEIVABLE_QLICI_STATUSES = ("DEPLOYED", "PARTIALLY_REPAID", "NON_QUALIFYING")


# --- lookups --------------------------------------------------------------

def qlicis_of_qei(qei_id):
    return [q for q in db.qlicis.values() if q["qei_id"] == qei_id]


def qeis_of_award(award_id):
    return [q for q in db.qeis.values() if q["allocation_award_id"] == award_id]


def qeis_of_fund(fund_id):
    return [q for q in db.qeis.values() if q["investment_fund_id"] == fund_id]


def cbas_of_qalicb(qalicb_id):
    return [c for c in db.cbas.values() if c["qalicb_id"] == qalicb_id]


def cbas_of_award(award_id):
    return [c for c in db.cbas.values() if c["allocation_award_id"] == award_id]


def obligations_of_qei(qei_id):
    return [o for o in db.obligations.values() if o["qei_id"] == qei_id]


def unwinds_of_qei(qei_id):
    return [u for u in db.unwinds.values() if u["qei_id"] == qei_id]


def award_of_qei(qei):
    return db.awards[qei["allocation_award_id"]]


def cde_of_award(award):
    return db.cdes[award["cde_id"]]


def qalicbs_funded_by(qei_id, statuses=None):
    ids = []
    for qlici in qlicis_of_qei(qei_id):
        if statuses is not None and qlici["status"] not in statuses:
            continue
        if qlici["qalicb_id"] not in ids:
            ids.append(qlici["qalicb_id"])
    return [db.qalicbs[i] for i in ids if i in db.qalicbs]


# --- substantially-all measurement (PRD 3.5, 3.8) -------------------------

def pct_direct(qei):
    denominator = qei["qei_amount_cents"] - qei["permitted_fees_cents"]
    numerator = sum(
        q["outstanding_principal_cents"]
        for q in qlicis_of_qei(qei["id"])
        if q["status"] in QUALIFYING_QLICI_STATUSES
    )
    return calc.pct(numerator, denominator)


def pct_aggregate(qei, window_start_at, window_end_at, window_days):
    denominator = Decimal(qei["qei_amount_cents"]) * Decimal(window_days)
    total = Decimal(0)
    now = clock.now()
    for qlici in qlicis_of_qei(qei["id"]):
        if qlici["status"] not in QUALIFYING_QLICI_STATUSES:
            continue
        start = max(window_start_at, qlici["deployed_at"])
        end = min(window_end_at, now)
        if qlici["non_qualifying_since_at"] is not None:
            end = min(end, qlici["non_qualifying_since_at"])
        days = clock.whole_days_between(start, end)
        total += Decimal(qlici["principal_cents"]) * Decimal(days)
    return calc.pct(total, denominator)


# --- award derivations ----------------------------------------------------

def severe_distress_share(award):
    total = 0
    severe = 0
    for qei in qeis_of_award(award["id"]):
        if qei["deployment_status"] == "VOIDED":
            continue
        for qlici in qlicis_of_qei(qei["id"]):
            if qlici["status"] not in QUALIFYING_QLICI_STATUSES:
                continue
            outstanding = qlici["outstanding_principal_cents"]
            total += outstanding
            qalicb = db.qalicbs.get(qlici["qalicb_id"])
            if qalicb is None:
                continue
            tract = db.tracts.get(qalicb["census_tract_id"])
            if tract is not None and tract["distress_tier"] == "SEVERE":
                severe += outstanding
    if total == 0:
        return calc.ZERO
    return calc.pct(severe, total)


def compliance_posture(award):
    cde = db.cdes.get(award["cde_id"])
    if cde is not None and cde["certification_status"] == "DECERTIFIED":
        return "FROZEN"
    if award["recaptured_qei_count"] >= 1:
        return "FROZEN"
    if award["at_risk_qei_count"] >= 2 or award["cba_breach_count"] >= 1:
        return "RESTRICTED"
    return "UNRESTRICTED"


def recompute_award(award):
    qeis = qeis_of_award(award["id"])
    live = [q for q in qeis if q["deployment_status"] != "VOIDED"]
    award["issued_qei_count"] = len(live)
    award["at_risk_qei_count"] = sum(1 for q in qeis if q["compliance_status"] == "AT_RISK")
    award["recaptured_qei_count"] = sum(
        1 for q in qeis if q["compliance_status"] == "RECAPTURED")
    award["cba_breach_count"] = sum(
        1 for c in cbas_of_award(award["id"]) if c["status"] == "BREACHED")
    if award["lifecycle_status"] != "TERMINATED":
        award["remaining_authority_cents"] = (
            award["allocation_amount_cents"] - sum(q["qei_amount_cents"] for q in live))
    award["severe_distress_share_pct"] = severe_distress_share(award)
    award["compliance_posture"] = compliance_posture(award)


def recompute_fund(fund):
    if fund["status"] == "WOUND_UP":
        fund["leverage_loan_outstanding_cents"] = 0
        fund["capital_available_cents"] = 0
        fund["deployed_to_qei_cents"] = sum(
            q["qei_amount_cents"] for q in qeis_of_fund(fund["id"])
            if q["deployment_status"] != "VOIDED")
        return
    deployed = sum(
        q["qei_amount_cents"] for q in qeis_of_fund(fund["id"])
        if q["deployment_status"] != "VOIDED")
    fund["deployed_to_qei_cents"] = deployed
    if fund["status"] in ("FUNDED", "QEI_MADE"):
        fund["status"] = "QEI_MADE" if deployed > 0 else "FUNDED"
        fund["leverage_loan_outstanding_cents"] = fund["leverage_received_cents"]
    else:
        fund["leverage_loan_outstanding_cents"] = 0
    fund["capital_available_cents"] = (
        fund["equity_received_cents"] + fund["leverage_received_cents"] - deployed)


def recompute_qalicb(qalicb):
    qalicb["funding_qlici_count"] = sum(
        1 for q in db.qlicis.values()
        if q["qalicb_id"] == qalicb["id"] and q["status"] != "REPAID")


def recompute_all():
    """Immediate consistency: every derived value is refreshed inside the request."""
    for fund in db.funds.values():
        recompute_fund(fund)
    for qei in db.qeis.values():
        qei["substantially_all_pct_direct"] = pct_direct(qei)
    for qalicb in db.qalicbs.values():
        recompute_qalicb(qalicb)
    for award in db.awards.values():
        recompute_award(award)


# --- compliance-status helpers -------------------------------------------

def mark_at_risk_if_short(qei):
    """A recomputed percentage below the threshold puts a COMPLIANT investment AT_RISK."""
    if qei["compliance_status"] != "COMPLIANT":
        return False
    if qei["substantially_all_pct_direct"] >= calc.SUBSTANTIALLY_ALL_THRESHOLD:
        return False
    qei["compliance_status"] = "AT_RISK"
    qei["cure_deadline_at"] = clock.plus_days(clock.now(), calc.CURE_WINDOW_DAYS)
    return True


def return_to_compliant_if_cured(qei, honour_deadline=True):
    if qei["compliance_status"] != "AT_RISK":
        return False
    if qei["substantially_all_pct_direct"] < calc.SUBSTANTIALLY_ALL_THRESHOLD:
        return False
    if (honour_deadline and qei["cure_deadline_at"] is not None
            and clock.now() > qei["cure_deadline_at"]):
        return False
    qei["compliance_status"] = "COMPLIANT"
    qei["cure_deadline_at"] = None
    return True


def recapture(qei, trigger_type):
    qei["compliance_status"] = "RECAPTURED"
    qei["recapture_trigger_type"] = trigger_type
    qei["recapture_exposure_cents"] = calc.recapture_exposure_cents(
        qei["qei_amount_cents"], qei["compliance_years_completed"])
