"""The §1.5 `/psc/_scenarios/seed-reference` grid, built on demand only.

Nothing here runs at import time or at boot. The store starts empty; these rows
are materialised only when the test-driving endpoint is explicitly invoked.
"""

from core import db, stamp, new_id


REFERENCE_PLAN = {
    "payer_name": "HORIZON HMO",
    "plan_type": "HMO",
    "copay_cents": 2500,
    "coinsurance_pct": 0.25,
    "deductible_remaining_cents": 0,
    "allowed_amount_cents": 10000,
    "prior_paid_pct": 0.0,
    "status": "ACTIVE",
}

# (test_panel, icd10_code, is_covered)
NECESSITY_GRID = [
    ("CMP", "E11.9", True),
    ("CMP", "R53.83", True),
    ("CMP", "Z00.00", False),
    ("CBC", "D64.9", True),
    ("CBC", "R50.9", True),
    ("CBC", "Z00.0", False),
    ("LIPID", "E78.5", True),
    ("LIPID", "E11.9", True),
    ("LIPID", "Z00.00", False),
    ("A1C", "E11.9", True),
    ("A1C", "R73.03", True),
    ("A1C", "Z00.00", False),
    ("TSH", "E03.9", True),
    ("TSH", "E05.90", True),
    ("TSH", "Z00.00", False),
    ("PT_INR", "I48.91", True),
    ("PT_INR", "Z79.01", True),
    ("PT_INR", "Z00.00", False),
    ("FERRITIN", "D50.9", True),
    ("FERRITIN", "E61.1", True),
    ("FERRITIN", "Z00.00", False),
    ("HCG_QUAL", "O09.90", True),
    ("HCG_QUAL", "N92.6", True),
    ("HCG_QUAL", "Z00.00", False),
    ("LACTATE", "R57.1", True),
    ("LACTATE", "A41.9", True),
    ("LACTATE", "Z00.00", False),
    ("GTT", "O24.419", True),
    ("GTT", "R73.09", True),
    ("GTT", "Z00.00", False),
]

# (test_panel, tube_code, required_volume_ml, min_volume_ml, order_of_draw,
#  stability_minutes, max_urgency_hours, special_handling_codes, recollectable)
TUBE_GRID = [
    ("BMP", "SST_GOLD", 5.0, 1.0, 2, 120, 4, [], True),
    ("BMP", "EDTA_LAVENDER", 4.0, 0.5, 4, 240, 4, [], True),
    ("BMP", "SODIUM_HEPARIN_GREEN", 4.0, 0.5, 5, 30, 2, ["CHILLED"], True),
    ("CMP", "SST_GOLD", 5.0, 1.0, 2, 90, 4, [], True),
    ("CMP", "EDTA_LAVENDER", 4.0, 0.5, 4, 240, 4, [], True),
    ("CBC", "EDTA_LAVENDER", 4.0, 0.5, 4, 360, 4, [], True),
    ("LIPID", "SST_GOLD", 5.0, 1.0, 2, 120, 6, ["PROTECT_FROM_LIGHT"], True),
    ("A1C", "EDTA_LAVENDER", 4.0, 0.5, 4, 360, 8, [], True),
    ("TSH", "SST_GOLD", 5.0, 1.0, 2, 180, 6, [], True),
    ("PT_INR", "SODIUM_CITRATE_BLUE", 2.7, 0.5, 3, 4320, 4, [], True),
    ("FERRITIN", "SST_GOLD", 5.0, 1.0, 2, 180, 6, [], True),
    ("HCG_QUAL", "SST_GOLD", 5.0, 1.0, 2, 180, 8, [], True),
    ("LACTATE", "SODIUM_FLUORIDE_GRAY", 2.0, 0.5, 6, 1440, 2, ["ICE_SLURRY"], True),
    ("GTT", "SODIUM_FLUORIDE_GRAY", 2.0, 0.5, 6, 1440, 2, ["ICE_SLURRY"], True),
]


def seed_reference():
    """Idempotently materialise the reference grid; never duplicates a row."""
    created = 0

    plan = None
    for p in db.insurance_plans.values():
        if p["payer_name"] == REFERENCE_PLAN["payer_name"]:
            plan = p
            break
    if plan is None:
        plan = stamp({"payer_name": REFERENCE_PLAN["payer_name"]})
        plan.update({k: v for k, v in REFERENCE_PLAN.items() if k != "payer_name"})
        db.insurance_plans[plan["id"]] = plan
        created += 1

    have_rules = {(r["test_panel"], r["icd10_code"]) for r in db.necessity_rules.values()}
    for panel, code, covered in NECESSITY_GRID:
        if (panel, code) in have_rules:
            continue
        row = stamp({"test_panel": panel, "icd10_code": code, "is_covered": covered})
        db.necessity_rules[row["id"]] = row
        created += 1

    have_tubes = {(r["test_panel"], r["tube_code"]) for r in db.tube_requirements.values()}
    for (panel, tube, req_v, min_v, od, stab, urg, handling, reco) in TUBE_GRID:
        if (panel, tube) in have_tubes:
            continue
        row = stamp({
            "test_panel": panel,
            "tube_code": tube,
            "required_volume_ml": req_v,
            "min_volume_ml": min_v,
            "order_of_draw": od,
            "stability_minutes": stab,
            "max_urgency_hours": urg,
            "special_handling_codes": list(handling),
            "is_recollection_eligible": reco,
            "status": "ACTIVE",
        })
        db.tube_requirements[row["id"]] = row
        created += 1

    return created, plan["id"]