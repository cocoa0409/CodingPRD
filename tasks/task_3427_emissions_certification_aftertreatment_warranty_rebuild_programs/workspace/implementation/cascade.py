"""Cascade hops and lazy-expiry materialization (PRD §2.4, §2.9).

Every hop of a cascade is an independent mutation of the affected resource:
its updated_at refreshes and its version increments by one at each hop.
"""
import clock
import store
from validators import touch

OPEN_CAMPAIGN_STATES = ("ANNOUNCED", "IN_PROGRESS", "COMPLETION_REVIEW")


# --- lazy expiry (§2.4): strictly-greater comparison, materialized on read/use ---
def materialize_technician(tech):
    if (tech["cert_status"] == "CERT_ACTIVE"
            and clock.now_dt() > tech["certification_expires_at"]):
        tech["cert_status"] = "EXPIRED"
        touch(tech)


def materialize_tool(tool):
    if (tool["tool_status"] == "CALIBRATED_ACTIVE"
            and clock.now_dt() > tool["calibration_valid_until"]):
        tool["tool_status"] = "RECAL_DUE"
        touch(tool)


# --- FieldCampaign COMPLETION_REVIEW -> CLOSED (system) + hold release ---
def close_campaign(campaign):
    campaign["status"] = "CLOSED"
    touch(campaign)
    fam = store.families.get(campaign["engine_family_id"])
    if fam is None:
        return
    other_open = any(
        c["engine_family_id"] == fam["id"] and c["id"] != campaign["id"]
        and c["status"] in OPEN_CAMPAIGN_STATES
        for c in store.campaigns.values())
    if not other_open and fam["certification_status"] == "COMPLIANCE_HOLD":
        fam["certification_status"] = (
            "IN_PRODUCTION" if fam["production_entered"] else "CERTIFIED")
        touch(fam)


# --- WarrantyClaim DENY_NEGLECT hops 1-2 (fleet) ---
def apply_neglect_denial(fleet):
    fleet["neglect_denial_count"] += 1
    touch(fleet)
    if fleet["neglect_denial_count"] >= 3 and fleet["status"] == "ACTIVE":
        fleet["status"] = "SUSPENDED"
        touch(fleet)


# --- RemanOrder REJECT / FORFEIT hops 2-3 (service center ledger) ---
def apply_core_reversal(center, provisional_core_credit_cents):
    center["core_credit_balance_cents"] -= provisional_core_credit_cents
    center["core_reversal_count"] += 1
    touch(center)
    if center["core_reversal_count"] >= 2 and center["auth_status"] == "AUTHORIZED":
        center["auth_status"] = "SUSPENDED"
        touch(center)
