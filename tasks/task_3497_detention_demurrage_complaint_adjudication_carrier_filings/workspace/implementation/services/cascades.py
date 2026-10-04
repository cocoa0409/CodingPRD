"""Automatic enforcement cascades (PRD §2.10) and the bond-coverage ledger
(c calculations.bond_coverage_tracking)."""
import store
from store import touch
from constants import SCORE_SUSPENSION_THRESHOLD


def _cascade_carrier_suspension(carrier):
    """Carrier just became SUSPENDED: settle its book of business."""
    suspended_tariff_ids = set()
    for t in store.tariffs.values():
        if t["carrier_id"] == carrier["id"] and t["publication_status"] == "PUBLISHED":
            t["publication_status"] = "SUSPENDED"
            touch(t)
            suspended_tariff_ids.add(t["id"])
    for inv in store.invoices.values():
        if (
            inv["carrier_id"] == carrier["id"]
            and inv["invoice_status"] in ("ISSUED", "DISPUTED")
            and inv["charge_basis"] == "TARIFF"
            and inv["tariff_id"] in suspended_tariff_ids
        ):
            inv["invoice_status"] = "VOIDED"
            touch(inv)
            for d in store.disputes.values():
                if d["invoice_id"] == inv["id"] and d["resolution"] == "PENDING":
                    # Cascade waiver: response_was_late left untouched.
                    d["resolution"] = "UPHELD_WAIVED"
                    d["resolved_amount_cents"] = 0
                    touch(d)


def apply_score_event(carrier, score_delta, penalty_cents=0):
    """One ledger event on the carrier: penalty accrual (if any), score change,
    automatic suspension the moment the score drops below the threshold, and a
    single version bump for the whole event."""
    carrier["cumulative_civil_penalties_cents"] += penalty_cents
    carrier["compliance_score"] = max(0, carrier["compliance_score"] + score_delta)
    if (
        carrier["compliance_score"] < SCORE_SUSPENSION_THRESHOLD
        and carrier["status"] == "ACTIVE"
    ):
        carrier["status"] = "SUSPENDED"
        touch(carrier)
        _cascade_carrier_suspension(carrier)
    else:
        touch(carrier)


def refresh_bond_coverage(license_rec):
    total = 0
    for b in license_rec["surety_bonds"]:
        b["available_cents"] = b["coverage_cents"] - b["drawn_cents"]
        b["bond_status"] = (
            "EXHAUSTED" if b["drawn_cents"] == b["coverage_cents"] else "ACTIVE"
        )
        total += b["available_cents"]
    license_rec["total_available_coverage_cents"] = total


def apply_license_sufficiency(license_rec):
    """Sufficiency rule, checked after every ledger mutation, in this order:
    coverage reached -> ACTIVE (restore contracts this license's coverage loss
    suspended); else coverage lost while ACTIVE -> SUSPENDED (suspend the
    carrier's EFFECTIVE contracts)."""
    total = license_rec["total_available_coverage_cents"]
    required = license_rec["required_bond_cents"]
    if total >= required and license_rec["license_status"] != "ACTIVE":
        license_rec["license_status"] = "ACTIVE"
        for cid in license_rec["_suspended_contract_ids"]:
            c = store.contracts.get(cid)
            if c is not None and c["contract_status"] == "SUSPENDED":
                c["contract_status"] = "EFFECTIVE"
                touch(c)
        license_rec["_suspended_contract_ids"] = set()
    elif total < required and license_rec["license_status"] == "ACTIVE":
        license_rec["license_status"] = "SUSPENDED"
        for c in store.contracts.values():
            if (
                c["carrier_id"] == license_rec["organization_id"]
                and c["contract_status"] == "EFFECTIVE"
            ):
                c["contract_status"] = "SUSPENDED"
                touch(c)
                license_rec["_suspended_contract_ids"].add(c["id"])


def has_active_license(carrier_id):
    return any(
        lic["organization_id"] == carrier_id and lic["license_status"] == "ACTIVE"
        for lic in store.licenses.values()
    )
