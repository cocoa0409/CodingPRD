"""Cross-entity cascades (PRD 3.4, 3.7, 3.8): approval, deny/withdraw cleanup,
suspension, cancellation hops, vacatur restore, delinquency cascade."""
from datetime import timedelta

import constants
from db import new_row, store, touch


def product_rows(collection, product_id):
    return [r for r in store[collection].values() if r.get("product_id") == product_id]


def cleanup_proposed_rows(product_id, now):
    """Deny/withdraw cleanup: PROPOSED use sites -> REMOVED, PROPOSED tolerances
    -> REVOKED, with pre_removal_status / pre_revocation_status left null."""
    for site in product_rows("use_sites", product_id):
        if site["status"] == "PROPOSED":
            site["status"] = "REMOVED"
            site["removed_at"] = now
            touch(site)
    for tol in product_rows("tolerances", product_id):
        if tol["status"] == "PROPOSED":
            tol["status"] = "REVOKED"
            tol["revoked_at"] = now
            touch(tol)


def approval_cascade(application, product, now):
    """Application APPROVE -> Product UNREGISTERED -> REGISTERED (PRD 3.4)."""
    from services.calcs import mint_registration_number

    product["classification"] = application["final_classification"]
    ai = store["active_ingredients"][product["active_ingredient_id"]]
    product["signal_word"] = constants.SIGNAL_WORD_BY_TOX[ai["tox_category"]]
    product["epa_registration_number"] = mint_registration_number(
        exclude_application_id=application["id"]
    )
    product["status"] = "REGISTERED"
    touch(product)

    for site in product_rows("use_sites", product["id"]):
        if site["status"] == "PROPOSED":
            site["status"] = "ACTIVE"
            touch(site)
    for tol in product_rows("tolerances", product["id"]):
        if tol["status"] == "PROPOSED":
            tol["status"] = "ESTABLISHED"
            tol["established_at"] = now
            touch(tol)

    schedule_next_case(product, now + timedelta(days=constants.REVIEW_CYCLE_DAYS))


def schedule_next_case(product, opened_at):
    """Auto-created review case: cycle_number = 1 + pre-existing case count."""
    existing = product_rows("review_cases", product["id"])
    case = new_row()
    case.update(
        {
            "product_id": product["id"],
            "cycle_number": len(existing) + 1,
            "opened_at": opened_at,
            "due_at": opened_at + timedelta(days=constants.REVIEW_COMPLETION_DAYS),
            "status": "SCHEDULED",
            "completed_at": None,
        }
    )
    store["review_cases"][case["id"]] = case
    return case


def suspend_product(product, now):
    """Product REGISTERED/UNDER_REVIEW -> SUSPENDED; hop A denies SUBMITTED
    state registrations."""
    if product["status"] in ("REGISTERED", "UNDER_REVIEW"):
        product["status"] = "SUSPENDED"
        touch(product)
    for reg in product_rows("state_registrations", product["id"]):
        if reg["status"] == "SUBMITTED":
            reg["status"] = "DENIED"
            touch(reg)


def cancel_product(product, now):
    """The full cancellation cascade (PRD 3.8 hops 1-3)."""
    # Hop 1: the product itself.
    product["status"] = "CANCELLED"
    touch(product)

    # Hop 2: tolerances PROPOSED/ESTABLISHED -> REVOKED with the prior status
    # captured (this is what makes the vacatur restore possible).
    revoked_commodities = set()
    for tol in product_rows("tolerances", product["id"]):
        if tol["status"] in ("PROPOSED", "ESTABLISHED"):
            tol["pre_revocation_status"] = tol["status"]
            tol["status"] = "REVOKED"
            tol["revoked_at"] = now
            touch(tol)
            revoked_commodities.add(tol["commodity_code"])

    # Hop 2: ACTIVE use sites -> REMOVED with marker.
    for site in product_rows("use_sites", product["id"]):
        if site["status"] == "ACTIVE":
            site["pre_removal_status"] = "ACTIVE"
            site["status"] = "REMOVED"
            site["removed_at"] = now
            touch(site)

    # Hop 2: non-terminal applications -> WITHDRAWN; their remaining PROPOSED
    # rows are cleaned up with the pre_* markers left null (never restored).
    for app in product_rows("applications", product["id"]):
        if app["status"] in ("DRAFT", "IN_REVIEW", "DATA_DEFICIENCY"):
            app["status"] = "WITHDRAWN"
            touch(app)
    for site in product_rows("use_sites", product["id"]):
        if site["status"] == "PROPOSED":
            site["status"] = "REMOVED"
            site["removed_at"] = now
            touch(site)

    # Hop 2: state registrations follow the federal layer.
    for reg in product_rows("state_registrations", product["id"]):
        if reg["status"] in ("GRANTED", "LAPSED"):
            reg["status"] = "REVOKED"
            touch(reg)
        elif reg["status"] == "SUBMITTED":
            reg["status"] = "DENIED"
            touch(reg)

    # Hop 3: SUBMITTED NEW_USE amendments commodity-matched to a just-revoked
    # tolerance are auto-rejected; all other pending amendments are untouched.
    for amendment in product_rows("amendments", product["id"]):
        if (
            amendment["status"] == "SUBMITTED"
            and amendment["amendment_type"] == "NEW_USE"
            and amendment["payload"].get("commodity_code") in revoked_commodities
        ):
            amendment["status"] = "REJECTED"
            amendment["decided_at"] = now
            touch(amendment)


def vacatur_restore(proceeding, now):
    """Restore after vacating an EFFECTIVE CANCELLATION (PRD 3.8).

    Restores product status and marked tolerances/use sites; state
    registrations, withdrawn applications, and cascade-rejected amendments are
    deliberately NOT restored (documented asymmetry).
    """
    product = store["products"][proceeding["product_id"]]
    product["status"] = proceeding["pre_effective_product_status"]
    touch(product)
    effective_at = proceeding["effective_at"]
    for tol in product_rows("tolerances", product["id"]):
        if tol["pre_revocation_status"] is not None and tol["revoked_at"] == effective_at:
            tol["status"] = tol["pre_revocation_status"]
            tol["pre_revocation_status"] = None
            tol["revoked_at"] = None
            touch(tol)
    for site in product_rows("use_sites", product["id"]):
        if site["pre_removal_status"] == "ACTIVE" and site["removed_at"] == effective_at:
            site["status"] = "ACTIVE"
            site["pre_removal_status"] = None
            site["removed_at"] = None
            touch(site)


def dci_delinquency_cascade(dci, now):
    """DCI -> DELINQUENT and the referral/auto-suspension cascade (PRD 3.7)."""
    dci["status"] = "DELINQUENT"
    touch(dci)
    case = store["review_cases"][dci["review_case_id"]]
    if case["status"] not in ("DCI_PENDING", "UNDER_REVIEW"):
        return
    case["status"] = "REFERRED"
    touch(case)
    product = store["products"][case["product_id"]]
    if product["status"] in ("SUSPENDED", "CANCELLED"):
        return
    # Hop 2: system-created EFFECTIVE suspension proceeding.
    proceeding = new_row()
    proceeding.update(
        {
            "product_id": product["id"],
            "proceeding_type": "SUSPENSION",
            "reason": "DCI_DELINQUENCY",
            "status": "EFFECTIVE",
            "auto_created": True,
            "initiated_by_ref": "system",
            "initiated_at": now,
            "hearing_held_at": None,
            "effective_at": now,
            "vacated_at": None,
            "pre_effective_product_status": product["status"],
            "existing_stocks_authorized_units": None,
            "stocks_method": None,
            "depletion_rate_units_per_month": None,
            "allow_sale_until": None,
            "allow_use_until": None,
            "existing_stocks_disposals": [],
            "existing_stocks_disposed_units": 0,
        }
    )
    store["proceedings"][proceeding["id"]] = proceeding
    # Hops 3-4: product -> SUSPENDED, SUBMITTED state registrations -> DENIED.
    suspend_product(product, now)
