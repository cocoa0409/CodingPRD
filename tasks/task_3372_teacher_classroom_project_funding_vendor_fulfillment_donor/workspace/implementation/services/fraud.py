"""Fraud clawback cascade (SCAFFOLD fraud_clawback), fired when a FraudCase
resolves CONFIRMED. Fixed order: suspend teacher; cancel open-pipeline
projects (created_at ASC); refund their CAPTURED/CHOICE_PENDING donations
with match clawback; cancel their ISSUED/SHIPPED purchase orders.
DELIVERED and DIVERSION_REPORTED POs are left untouched as evidence."""
import store
from services import matching

PIPELINE_STATES = ("DRAFT", "IN_REVIEW", "VETTING", "RETURNED", "FUNDING", "FUNDED")


def confirm_fraud_case(case, now):
    teacher = store.teachers.get(case["teacher_id"])
    if teacher is not None and teacher["employment_status"] != "SUSPENDED":
        teacher["employment_status"] = "SUSPENDED"
        store.touch(teacher)

    projects = [
        p for p in store.projects.values()
        if p["teacher_id"] == case["teacher_id"] and p["status"] in PIPELINE_STATES
    ]
    projects.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for project in projects:
        was = project["status"]
        project["status"] = "CANCELLED"
        store.touch(project)
        if was not in ("FUNDING", "FUNDED"):
            continue

        donations = [
            d for d in store.donations.values()
            if d["project_id"] == project["id"] and d["status"] in ("CAPTURED", "CHOICE_PENDING")
        ]
        donations.sort(key=lambda d: (d["created_at"], d["_seq"]))
        for donation in donations:
            matching.clawback_match(donation, now)
            donation["status"] = "REFUNDED"
            donation["refund_reason"] = "FRAUD_CLAWBACK"
            donor = store.donors.get(donation["donor_id"]) if donation["donor_id"] else None
            if donor is not None:
                donor["lifetime_refunded_cents"] += donation["amount_cents"]
                store.touch(donor)
            store.touch(donation)

        orders = [
            po for po in store.purchase_orders.values()
            if po["project_id"] == project["id"] and po["status"] in ("ISSUED", "SHIPPED")
        ]
        orders.sort(key=lambda po: (po["created_at"], po["_seq"]))
        for po in orders:
            po["status"] = "CANCELLED"
            store.touch(po)
