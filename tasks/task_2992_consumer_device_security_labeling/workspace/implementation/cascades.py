"""Cascades, compensation and the expiry sweep (PRD 2.11, 3.2, 3.7, 3.9)."""

import calc
import store
from store import touch


def apply_changes(row, changes):
    """Write the supplied fields; refresh updated_at and bump version when any
    value actually moved (recomputation of a derived field is a mutation)."""
    changed = False
    for field, value in changes.items():
        if row.get(field) != value:
            row[field] = value
            changed = True
    if changed:
        touch(row)
    return changed


# --------------------------------------------------------------------------
# Retailer participation (PRD 3.8)
# --------------------------------------------------------------------------
def recount_retailer(retailer):
    count = 0
    for auth in store.authorizations_of_retailer(retailer["id"]):
        if auth["status"] == "AUTHORIZED":
            count += 1
    tier = calc.retailer_participation_tier(retailer["education_materials_ack"], count)
    return apply_changes(
        retailer, {"active_display_count": count, "participation_tier": tier}
    )


def recount_retailers(retailer_ids):
    for retailer_id in sorted(retailer_ids):
        retailer = store.retailers.get(retailer_id)
        if retailer is not None:
            recount_retailer(retailer)


# --------------------------------------------------------------------------
# Display withdrawal driven by a grant (PRD 3.2, 3.7, 3.9)
# --------------------------------------------------------------------------
def withdraw_grant_displays(grant, reason, touched=None):
    """Every AUTHORIZED display of this grant moves to WITHDRAWN."""
    if touched is None:
        touched = set()
    for auth in store.authorizations_of_grant(grant["id"]):
        if auth["status"] == "AUTHORIZED":
            apply_changes(auth, {"status": "WITHDRAWN", "withdrawal_reason": reason})
            touched.add(auth["retailer_id"])
    return touched


# --------------------------------------------------------------------------
# Lab bench ledger (PRD 3.5)
# --------------------------------------------------------------------------
def recompute_lab_ledger(lab):
    reserved = calc.lab_bench_hour_ledger(lab["id"])
    return apply_changes(
        lab,
        {
            "reserved_bench_hours": reserved,
            "available_bench_hours": lab["total_bench_hours"] - reserved,
        },
    )


def recompute_lab_ledger_by_id(lab_id):
    lab = store.test_labs.get(lab_id)
    if lab is not None:
        recompute_lab_ledger(lab)


# --------------------------------------------------------------------------
# Spec-change suspension cascade (PRD 3.2)
# --------------------------------------------------------------------------
def suspend_product_grants(product, reason, renewal_required):
    """Link one: ACTIVE grants of this product move to SUSPENDED.  Link two:
    their AUTHORIZED displays are withdrawn.  Link three: retailers recount."""
    touched = set()
    suspended = 0
    for grant in store.grants_of_product(product["id"]):
        if grant["grant_status"] != "ACTIVE":
            continue
        apply_changes(
            grant,
            {
                "grant_status": "SUSPENDED",
                "suspension_reason": reason,
                "renewal_required": renewal_required,
            },
        )
        withdraw_grant_displays(grant, "GRANT_SUSPENDED", touched)
        suspended += 1
    recount_retailers(touched)
    return suspended


# --------------------------------------------------------------------------
# Assessment supersession (PRD 3.3)
# --------------------------------------------------------------------------
IN_FLIGHT_ASSESSMENT_STATUSES = ("DRAFT", "UNDER_REVIEW", "DEFICIENT")


def supersede_open_assessments(product, new_assessment_id):
    for assessment in store.assessments_of_product(product["id"]):
        if assessment["id"] == new_assessment_id:
            continue
        if assessment["status"] not in IN_FLIGHT_ASSESSMENT_STATUSES:
            continue
        apply_changes(
            assessment,
            {
                "status": "SUPERSEDED",
                "superseded_by_assessment_id": new_assessment_id,
            },
        )
        labs = set()
        for engagement in store.engagements_of_assessment(assessment["id"]):
            if engagement["status"] not in ("SCHEDULED", "IN_PROGRESS"):
                continue
            apply_changes(
                engagement,
                {
                    "status": "CANCELLED",
                    "cancellation_reason": "ASSESSMENT_SUPERSEDED",
                },
            )
            labs.add(engagement["test_lab_id"])
        for lab_id in sorted(labs):
            recompute_lab_ledger_by_id(lab_id)


# --------------------------------------------------------------------------
# Penalty ledger, standing and its cascade (PRD 3.9)
# --------------------------------------------------------------------------
def recompute_manufacturer_ledger(manufacturer):
    """Re-aggregate the ledger, re-derive standing, then cascade."""
    ledger = calc.manufacturer_penalty_ledger(manufacturer["id"])
    standing = calc.standing_for(
        ledger["upheld_case_count"], ledger["outstanding_penalty_cents"]
    )
    changes = dict(ledger)
    changes["standing"] = standing
    apply_changes(manufacturer, changes)
    if standing == "GOOD":
        reinstate_sponsor_grants(manufacturer)
    else:
        suspend_sponsor_grants(manufacturer)


def suspend_sponsor_grants(manufacturer):
    """A standing that is no longer GOOD darkens the whole portfolio."""
    touched = set()
    for product in store.products_of_manufacturer(manufacturer["id"]):
        for grant in store.grants_of_product(product["id"]):
            if grant["grant_status"] != "ACTIVE":
                continue
            apply_changes(
                grant,
                {
                    "grant_status": "SUSPENDED",
                    "suspension_reason": "SPONSOR_DELINQUENT",
                    "renewal_required": False,
                },
            )
            withdraw_grant_displays(grant, "GRANT_SUSPENDED", touched)
    recount_retailers(touched)


def reinstate_sponsor_grants(manufacturer):
    """Compensation is asymmetric: grants recover, displays do not."""
    now = store.clock_now()
    for product in store.products_of_manufacturer(manufacturer["id"]):
        for grant in store.grants_of_product(product["id"]):
            if grant["grant_status"] != "SUSPENDED":
                continue
            if grant["suspension_reason"] != "SPONSOR_DELINQUENT":
                continue
            if grant["renewal_required"]:
                continue
            if grant["valid_until"] is None or now >= grant["valid_until"]:
                continue
            apply_changes(grant, {"grant_status": "ACTIVE", "suspension_reason": None})


# --------------------------------------------------------------------------
# The expiry sweep (PRD 3.7)
# --------------------------------------------------------------------------
def expiry_sweep():
    now = store.clock_now()
    touched = set()
    grants_suspended = 0
    grants_expired = 0
    authorizations_expired = 0
    engagements_started = 0

    # Support-period tail: still inside nominal validity, commitment lapsed.
    for grant in store.by_seq(list(store.label_grants.values())):
        if grant["grant_status"] != "ACTIVE":
            continue
        if grant["valid_until"] is None or grant["valid_until"] <= now:
            continue
        entry = store.registry_entry_of_grant(grant["id"])
        if entry is None or entry["support_period_end"] is None:
            continue
        if entry["support_period_end"] > now:
            continue
        apply_changes(
            grant,
            {
                "grant_status": "SUSPENDED",
                "suspension_reason": "SUPPORT_PERIOD_ENDED",
                "renewal_required": True,
            },
        )
        withdraw_grant_displays(grant, "GRANT_SUSPENDED", touched)
        grants_suspended += 1

    # Expiry outranks the support-period suspension above.
    for grant in store.by_seq(list(store.label_grants.values())):
        if grant["grant_status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if grant["valid_until"] is None or grant["valid_until"] > now:
            continue
        apply_changes(
            grant,
            {
                "grant_status": "EXPIRED",
                "renewal_required": True,
                "suspension_reason": None,
            },
        )
        withdraw_grant_displays(grant, "GRANT_EXPIRED", touched)
        grants_expired += 1

    # The only route to an EXPIRED authorization.
    for auth in store.by_seq(list(store.display_authorizations.values())):
        if auth["status"] != "AUTHORIZED":
            continue
        if auth["display_until"] is None or auth["display_until"] >= now:
            continue
        grant = store.label_grants.get(auth["label_grant_id"])
        if grant is None or grant["grant_status"] != "ACTIVE":
            continue
        apply_changes(auth, {"status": "EXPIRED"})
        touched.add(auth["retailer_id"])
        authorizations_expired += 1

    # Bench windows open; the laboratory's reservation is untouched.
    for engagement in store.by_seq(list(store.test_engagements.values())):
        if engagement["status"] != "SCHEDULED":
            continue
        if engagement["window_start"] > now:
            continue
        apply_changes(engagement, {"status": "IN_PROGRESS"})
        engagements_started += 1

    recount_retailers(touched)

    return {
        "grants_expired": grants_expired,
        "grants_suspended": grants_suspended,
        "authorizations_expired": authorizations_expired,
        "engagements_started": engagements_started,
    }
