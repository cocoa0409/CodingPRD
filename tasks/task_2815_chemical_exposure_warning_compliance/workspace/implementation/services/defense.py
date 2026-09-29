"""The defence file: the compliance-summary score (PRD 3.9)."""
from util import D, rhu, fmt_dt, out_num
import db
from services import calc, money, posture

W_WARNING = D(40)
W_ASSESSMENT = D(25)
W_WARRANTY = D(20)
W_RECORDKEEPING = D(15)

HALF = D("0.5")
FULL = D("1.0")
ZERO = D("0.0")


def approved_determination(product):
    for determination in calc.determinations_of(product["id"]):
        if determination["status"] == "APPROVED":
            return determination
    return None


def summary(product, notice=None):
    if notice is None:
        variant = "AS_OF_TODAY"
        as_of = db.now()
    else:
        variant = "AS_OF_SERVICE_DATE"
        as_of = notice["served_at"]

    determination = approved_determination(product)
    required = list(determination.get("required_channels") or []) if determination else []
    required_channel_count = len(required)
    covered = []
    verified = []
    if determination is not None:
        for channel in required:
            hits = [p for p in calc.placements_of(determination["id"])
                    if p["channel"] == channel
                    and posture.window_covers(p["effective_from"], p["effective_to"], as_of)]
            if any(p["status"] in ("IMPLEMENTED", "VERIFIED") for p in hits):
                covered.append(channel)
            if any(p["status"] == "VERIFIED" for p in hits):
                verified.append(channel)
    if determination is None or required_channel_count == 0:
        warning_evidence = ZERO
    elif len(verified) == required_channel_count:
        warning_evidence = FULL
    elif len(covered) == required_channel_count:
        warning_evidence = HALF
    else:
        warning_evidence = ZERO

    finals = []
    reviewed = []
    for assessment in calc.assessments_of(product["id"]):
        if assessment["status"] == "FINAL":
            if variant == "AS_OF_TODAY":
                finals.append(assessment)
            elif assessment.get("finalized_at") is not None and \
                    assessment["finalized_at"] <= as_of:
                finals.append(assessment)
        elif assessment["status"] == "PEER_REVIEWED":
            reviewed.append(assessment)
    if finals:
        assessment_evidence = FULL
    elif reviewed:
        assessment_evidence = HALF
    else:
        assessment_evidence = ZERO

    components = calc.active_components(product["id"])
    materials = []
    for component in components:
        material = db.get("materials", component["material_id"])
        if material is not None:
            materials.append(material)

    if not materials:
        warranty_evidence = ZERO
    else:
        full = True
        half = True
        for material in materials:
            supplier = db.get("suppliers", material.get("supplier_id"))
            if not money.supplier_qualifies(supplier, material, as_of,
                                            require_pass_through=False):
                full = False
                half = False
                break
            if not supplier.get("pass_through_warning_obligation"):
                full = False
        warranty_evidence = FULL if full else (HALF if half else ZERO)

    def response_counts(material):
        if variant == "AS_OF_TODAY":
            return True
        received = material.get("data_received_at")
        return received is not None and received <= as_of

    if not materials:
        recordkeeping_evidence = ZERO
        verified_material_count = 0
    else:
        verified_material_count = len(
            [m for m in materials
             if m.get("disclosure_status") == "VERIFIED" and response_counts(m)])
        all_verified = all(m.get("disclosure_status") == "VERIFIED" and response_counts(m)
                           for m in materials)
        all_received = all(m.get("disclosure_status") in ("RECEIVED", "VERIFIED")
                           and response_counts(m) for m in materials)
        if all_verified:
            recordkeeping_evidence = FULL
        elif all_received:
            recordkeeping_evidence = HALF
        else:
            recordkeeping_evidence = ZERO

    score = rhu(W_WARNING * warning_evidence + W_ASSESSMENT * assessment_evidence
                + W_WARRANTY * warranty_evidence + W_RECORDKEEPING * recordkeeping_evidence, 0)
    return {
        "product_id": product["id"],
        "variant": variant,
        "as_of": fmt_dt(as_of),
        "defense_strength_score": int(score),
        "warning_evidence": float(warning_evidence),
        "assessment_evidence": float(assessment_evidence),
        "warranty_evidence": float(warranty_evidence),
        "recordkeeping_evidence": float(recordkeeping_evidence),
        "required_channel_count": required_channel_count,
        "covered_channel_count": len(covered),
        "verified_channel_count": len(verified),
        "final_assessment_count": len(finals),
        "verified_material_count": verified_material_count,
        "active_component_count": len(components),
    }
