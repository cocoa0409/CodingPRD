"""The explicit cascades: recomputation fan-out, supersession and revocation."""
import db
from services import calc, posture


def recompute_open_assessments(product):
    """Routine churn touches DRAFT, SUBMITTED and PEER_REVIEWED rows only."""
    for assessment in calc.assessments_of(product["id"]):
        if assessment["status"] not in calc.RECOMPUTABLE_ASSESSMENT_STATUSES:
            continue
        if calc.recompute_assessment_numbers(assessment):
            db.touch(assessment)


def product_data_changed(product):
    """Recompute open assessments, the chemical load and the posture."""
    if product is None:
        return
    recompute_open_assessments(product)
    posture.recompute_load(product)
    posture.recompute_posture(product)


def material_data_changed(material):
    """Fan out to every product that reaches this material."""
    for product in calc.products_reaching(material):
        product_data_changed(product)


def load_and_posture(material):
    for product in calc.products_reaching(material):
        posture.recompute_load(product)
        posture.recompute_posture(product)


def flag_placements_non_compliant(determination):
    for placement in calc.placements_of(determination["id"]):
        if placement["status"] in ("IMPLEMENTED", "VERIFIED"):
            placement["status"] = "NON_COMPLIANT"
            db.touch(placement)


def revoke_determination(determination, recompute_posture=True):
    """APPROVED -> REVOKED, taking its live placements down with it."""
    determination["status"] = "REVOKED"
    db.touch(determination)
    flag_placements_non_compliant(determination)
    determination["covered_channel_count"] = 0
    product = db.get("products", determination["product_id"])
    if product is not None and recompute_posture:
        posture.recompute_posture(product)
    return determination


def supersede_determination(determination):
    """APPROVED -> SUPERSEDED because a newer determination was approved."""
    determination["status"] = "SUPERSEDED"
    db.touch(determination)
    instant = db.now()
    for placement in calc.placements_of(determination["id"]):
        if placement.get("effective_to") is None:
            placement["effective_to"] = instant
            db.touch(placement)
    determination["covered_channel_count"] = posture.covered_channel_count(determination)
    return determination


def revoke_determinations_citing(assessment):
    for determination in db.rows("warning_determinations"):
        if determination.get("assessment_id") != assessment["id"]:
            continue
        if determination["status"] == "APPROVED":
            revoke_determination(determination, recompute_posture=False)


def supersede_final_assessment(assessment, recompute_numbers=False, touch_product=True):
    """FINAL -> SUPERSEDED: verdict first, then the determination cascade."""
    if recompute_numbers:
        calc.recompute_assessment_numbers(assessment)
    else:
        calc.recompute_verdict_only(assessment)
    assessment["status"] = "SUPERSEDED"
    db.touch(assessment)
    revoke_determinations_citing(assessment)
    product = db.get("products", assessment["product_id"])
    if product is not None:
        if touch_product:
            db.touch(product)
        posture.recompute_posture(product)
    return assessment


def products_touching_chemical(chemical):
    """Products whose active components reach a material linked to this chemical."""
    out = []
    for link in db.rows("material_chemicals"):
        if link["chemical_id"] != chemical["id"]:
            continue
        material = db.get("materials", link["material_id"])
        if material is None:
            continue
        for product in calc.products_reaching(material):
            if product not in out:
                out.append(product)
    return out


def chemical_data_changed(chemical):
    for product in products_touching_chemical(chemical):
        posture.recompute_load(product)
        posture.recompute_posture(product)


def supersede_finals_for_chemical(chemical):
    for assessment in db.rows("exposure_assessments"):
        if assessment["chemical_id"] == chemical["id"] and assessment["status"] == "FINAL":
            supersede_final_assessment(assessment)
