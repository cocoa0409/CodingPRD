"""Cascades (PRD 2.9). Every record a cascade touches advances its own version.

The pinned processing order for every multi-row hop is created_at ascending, the
same order the list endpoints return, so a list response is a faithful preview of
what the cascade will do.
"""

import config
import derive
import timeutil
from store import create_record, ordered, store, touch


# ----------------------------------------------------------------- the ledger
def post_ledger(enrollment, entry_type, amount_cents, effective_date, claim_id=None, memo=None):
    """Append one immutable ledger row. Benefit rows freeze the cap year."""
    ledger_kind = "BENEFIT" if entry_type in config.BENEFIT_ENTRY_TYPES else "CASH"
    body = {
        "enrollment_id": enrollment["id"],
        "claim_id": claim_id,
        "ledger_kind": ledger_kind,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "effective_date": timeutil.render_date(effective_date)
        if not isinstance(effective_date, str)
        else effective_date,
        "cap_year_start": enrollment["cap_year_start"] if ledger_kind == "BENEFIT" else None,
        "memo": memo,
    }
    return create_record(store.ledger_entries, body, versioned=False)


# -------------------------------------------------------------- partner hops
def withdraw_partner_campaigns(partner):
    """Every DRAFT / PARTNER_REVIEW / APPROVED campaign of the partner is withdrawn."""
    withdrawn = []
    for campaign in ordered(store.campaigns, lambda c: c["partner_id"] == partner["id"]):
        if campaign["status"] in ("DRAFT", "PARTNER_REVIEW", "APPROVED"):
            campaign["status"] = "WITHDRAWN"
            touch(campaign)
            withdrawn.append(campaign)
    return withdrawn


def withdraw_partner_products(partner):
    withdrawn = []
    for product in ordered(store.products, lambda p: p["partner_id"] == partner["id"]):
        if product["status"] != "WITHDRAWN":
            product["status"] = "WITHDRAWN"
            touch(product)
            withdrawn.append(product)
    return withdrawn


# ---------------------------------------------------------------- appeal hops
def open_appeal(claim, appeal_source):
    """Reopen a denied claim as an appeal and carry the retention cascade."""
    claim["status"] = "APPEAL_OPEN"
    claim["appeal_opened_at"] = store.now_iso()
    claim["appeal_source"] = appeal_source
    claim["appeal_count"] = claim.get("appeal_count", 0) + 1
    touch(claim)
    enrollment = derive.enrollment_of_claim(claim)
    if enrollment is not None:
        enrollment["retention_hold"] = True
        touch(enrollment)
        premises = derive.premises_of_enrollment(enrollment)
        if premises is not None:
            touch(premises)


def refresh_retention_hold(enrollment):
    """A policy holds retention only while one of its claims has an appeal open."""
    if enrollment is None:
        return
    held = any(c["status"] == "APPEAL_OPEN" for c in derive.claims_of_enrollment(enrollment["id"]))
    if bool(enrollment.get("retention_hold")) != held:
        enrollment["retention_hold"] = held
        touch(enrollment)
        premises = derive.premises_of_enrollment(enrollment)
        if premises is not None:
            touch(premises)


def refresh_regulator_hold(premises):
    """A regulator hold stands while any complaint citing this address is open."""
    if premises is None:
        return
    held = derive.premises_regulator_hold_still_open(premises["id"])
    if bool(premises.get("regulator_hold")) != held:
        premises["regulator_hold"] = held
        touch(premises)


# ------------------------------------------------------------------- cap hops
def refresh_cap_status(enrollment, cascade_denials=True):
    """Flip the cap dimension when the annual allowance is crossed either way."""
    product = derive.product_of_enrollment(enrollment)
    if product is None:
        return
    used = derive.annual_benefit_used_cents(enrollment)
    if used >= product["annual_cap_cents"]:
        if enrollment["cap_status"] == "WITHIN_CAP":
            enrollment["cap_status"] = "ANNUAL_CAP_EXHAUSTED"
            touch(enrollment)
            if cascade_denials:
                deny_open_triage_claims(enrollment)
    else:
        if enrollment["cap_status"] == "ANNUAL_CAP_EXHAUSTED":
            enrollment["cap_status"] = "WITHIN_CAP"
            touch(enrollment)


def deny_open_triage_claims(enrollment):
    """Cap exhaustion denies every claim of the policy still awaiting triage."""
    denied = []
    for claim in derive.claims_of_enrollment(enrollment["id"]):
        if claim["status"] != "TRIAGE":
            continue
        claim["status"] = "DENIED"
        claim["denial_reason"] = "CAP_EXHAUSTED"
        claim["denied_at"] = store.now_iso()
        touch(claim)
        denied.append(claim)
    return denied


# -------------------------------------------------------------- dispatch hops
def cancel_dispatch(dispatch, cancellation_reason):
    dispatch["status"] = "CANCELLED"
    dispatch["cancellation_reason"] = cancellation_reason
    touch(dispatch)
    # The contractor's open_dispatch_count is recomputed, so its version rises.
    contractor = store.contractors.get(dispatch["contractor_id"])
    if contractor is not None:
        touch(contractor)


def revert_claim_if_idle(claim):
    """A claim returns to APPROVED only once no dispatch of it is still open."""
    if claim["status"] != "DISPATCHED":
        return False
    for dispatch in derive.dispatches_of_claim(claim["id"]):
        if dispatch["status"] in config.OPEN_DISPATCH_STATUSES:
            return False
    claim["status"] = "APPROVED"
    touch(claim)
    return True


def cancel_open_dispatches_of_enrollment(enrollment, cancellation_reason):
    cancelled = []
    for dispatch in derive.dispatches_of_enrollment(enrollment["id"]):
        if dispatch["status"] in config.OPEN_DISPATCH_STATUSES:
            cancel_dispatch(dispatch, cancellation_reason)
            cancelled.append(dispatch)
    return cancelled
