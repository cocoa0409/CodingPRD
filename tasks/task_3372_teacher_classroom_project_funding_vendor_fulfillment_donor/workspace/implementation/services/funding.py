"""Funding progress, PO issuance at FUNDED, and the thank-you gate."""
from datetime import timedelta

import store
from services import pricing

VENDOR_SHIP_SLA_DAYS = 10

# Statuses whose donations count toward funded_cents.
COUNTED_DONATION_STATES = ("CAPTURED", "CHOICE_PENDING")


def funded_cents(project):
    """sum(amount_cents + matched_cents) over the project's donations in
    CAPTURED or CHOICE_PENDING. Derived, so every status/match change is
    reflected immediately."""
    return sum(
        d["amount_cents"] + d["matched_cents"]
        for d in store.donations.values()
        if d["project_id"] == project["id"] and d["status"] in COUNTED_DONATION_STATES
    )


def issue_purchase_orders(project, now):
    """One PO per distinct vendor among pinned ProjectItems; line_items
    sorted by catalog-item created_at ASC; shipping quote over the vendor's
    lines at issuance."""
    groups = pricing.vendor_groups(project["id"])

    def group_key(pair):
        vendor_id, pairs = pair
        first = min((ci["created_at"], ci["_seq"]) for _, ci in pairs)
        return (first[0], first[1])

    for vendor_id, pairs in sorted(groups.items(), key=group_key):
        line_items = [
            {
                "catalog_item_id": ci["id"],
                "sku": ci["sku"],
                "quantity": item["quantity"],
                "pinned_unit_price_cents": item["pinned_unit_price_cents"],
            }
            for item, ci in pairs
        ]
        line_total = sum(li["pinned_unit_price_cents"] * li["quantity"] for li in line_items)
        po = store.base_record()
        po.update({
            "project_id": project["id"],
            "vendor_id": vendor_id,
            "line_items": line_items,
            "line_total_cents": line_total,
            "shipping_fee_cents": pricing.shipping_quote(pricing.shipping_lines(pairs)),
            "status": "ISSUED",
            "tracking_number": None,
            "issued_at": now,
            "ship_by_due": now + timedelta(days=VENDOR_SHIP_SLA_DAYS),
            "shipped_at": None,
            "delivered_at": None,
        })
        store.purchase_orders[po["id"]] = po


def create_thank_you_package(project):
    """Exactly one PENDING package per funded project."""
    for pkg in store.thank_you_packages.values():
        if pkg["project_id"] == project["id"]:
            return pkg
    pkg = store.bare_record()
    pkg.update({
        "project_id": project["id"],
        "status": "PENDING",
        "thank_you_note": None,
        "impact_report": None,
        "submitted_at": None,
    })
    store.thank_you_packages[pkg["id"]] = pkg
    return pkg


def check_funded(project, now):
    """Inclusive boundary: funded_cents >= goal_cents flips FUNDING -> FUNDED,
    auto-issues POs and creates the PENDING thank-you package."""
    if project["status"] != "FUNDING":
        return False
    if funded_cents(project) < project["goal_cents"]:
        return False
    project["status"] = "FUNDED"
    store.touch(project)
    issue_purchase_orders(project, now)
    create_thank_you_package(project)
    return True


def thank_you_debt(teacher_id):
    """A PENDING ThankYouPackage on a FULFILLED project blocks new projects."""
    for pkg in store.thank_you_packages.values():
        if pkg["status"] != "PENDING":
            continue
        project = store.projects.get(pkg["project_id"])
        if (
            project is not None
            and project["teacher_id"] == teacher_id
            and project["status"] == "FULFILLED"
        ):
            return True
    return False
