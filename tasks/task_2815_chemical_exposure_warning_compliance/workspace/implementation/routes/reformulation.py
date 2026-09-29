"""Reformulation projects and the defence-file read (PRD 3.9)."""
from flask import Blueprint, request

import db
import response
import validate
from errors import fail
from middleware import guard
from util import D, rhu
from routes.common import list_endpoint
from services import calc, cascade, defense, posture

bp = Blueprint("reformulation", __name__)

READ_ROLES = ("ComplianceAnalyst", "ToxicologyReviewer", "RegulatoryCounsel", "RegistryAdmin")
TRIGGERS = ("START", "SUBMIT_VERIFICATION", "REWORK", "COMPLETE", "ABANDON")
LEGAL = {
    "START": ("PLANNED",),
    "SUBMIT_VERIFICATION": ("IN_PROGRESS",),
    "REWORK": ("VERIFICATION",),
    "COMPLETE": ("VERIFICATION",),
    "ABANDON": ("PLANNED", "IN_PROGRESS", "VERIFICATION"),
}
NON_TERMINAL = ("PLANNED", "IN_PROGRESS", "VERIFICATION")
REDUCTION_DP = 2
FALLBACK_ROUTE = "ORAL"
FALLBACK_USES = D(1)


def link_concentration(link):
    """The link's own current figure, the datum a project rewrites."""
    if link.get("measurement_basis") == "LAB_TESTED":
        result = link.get("lab_result_ppm")
        loq = link.get("lab_loq_ppm")
        if result is not None and loq is not None:
            return D(loq) / D(2) if D(result) < D(loq) else D(result)
    return D(link.get("declared_concentration_ppm") or 0)


def newest_final(product_id, chemical_id):
    """FINAL assessments ranked by finalized_at then created_at, both descending."""
    finals = [a for a in calc.assessments_of(product_id, chemical_id)
              if a["status"] == "FINAL"]
    if not finals:
        return None
    finals.sort(key=lambda a: (a.get("finalized_at") or a["created_at"], a["created_at"],
                               a["_seq"]), reverse=True)
    return finals[0]


def exposure_shape(product_id, chemical_id):
    """The route and uses_per_day the modelled recomputation reads."""
    assessment = newest_final(product_id, chemical_id)
    if assessment is None:
        candidates = calc.assessments_of(product_id, chemical_id)
        assessment = candidates[-1] if candidates else None
    if assessment is None:
        return FALLBACK_ROUTE, FALLBACK_USES
    return assessment["route"], assessment["uses_per_day"]


def windows_collide(new_start, new_end, old_start, old_end):
    """Half-open: touching endpoints do not collide."""
    if new_start is None or new_end is None or old_start is None or old_end is None:
        return False
    return new_start < old_end and old_start < new_end


@bp.route("/reformulation-projects", methods=["POST"])
@guard("ComplianceAnalyst")
def create_project(who):
    body = validate.body_json()
    validate.v_str(body, "product_id", required=True)
    validate.v_str(body, "chemical_id", required=True)
    validate.v_str(body, "material_chemical_id", required=True)
    target = validate.v_num(body, "target_concentration_ppm", required=True)
    start = validate.v_dt(body, "planned_start_date", required=True)
    end = validate.v_dt(body, "planned_end_date", required=True)
    validate.v_domain(body)
    validate.v_interval(start, end)
    product = validate.fk("products", body, "product_id", required=True)
    chemical = validate.fk("listed_chemicals", body, "chemical_id", required=True)
    link = validate.fk("material_chemicals", body, "material_chemical_id", required=True)
    validate.v_writable(body, ("product_id", "chemical_id", "material_chemical_id",
                               "target_concentration_ppm", "planned_start_date",
                               "planned_end_date"))
    if not target < link_concentration(link):
        fail("ERR_TARGET_NOT_BELOW_THRESHOLD",
             "target_concentration_ppm is not strictly below the link's current concentration")
    for other in db.rows("reformulation_projects"):
        if other["product_id"] != product["id"] or other["chemical_id"] != chemical["id"]:
            continue
        if other["status"] not in NON_TERMINAL:
            continue
        if windows_collide(start, end, other["planned_start_date"],
                           other["planned_end_date"]):
            fail("ERR_REFORMULATION_OVERLAP",
                 "the planned window collides with a live project on this pair")
    material = db.get("materials", link["material_id"])
    holders = [c for c in calc.active_components(product["id"])
               if material is not None and c["material_id"] == material["id"]]
    if link["chemical_id"] != chemical["id"] or not holders:
        fail("ERR_REFORMULATION_LINK_MISMATCH",
             "the named material-chemical link does not belong to this product and chemical")
    baseline = newest_final(product["id"], chemical["id"])
    row = db.insert("reformulation_projects", {
        "product_id": product["id"],
        "chemical_id": chemical["id"],
        "material_chemical_id": link["id"],
        "target_concentration_ppm": target,
        "planned_start_date": start,
        "planned_end_date": end,
        "baseline_daily_exposure_ug": (baseline["daily_exposure_ug"]
                                      if baseline is not None else D(0)),
        "verified_daily_exposure_ug": None,
        "reduction_pct": None,
        "status": "PLANNED",
    })
    return response.created(db.serialize("reformulation_projects", row))


def _rewrite_link(link, target):
    link["declared_concentration_ppm"] = target
    link["status"] = "DECLARED"
    link["measurement_basis"] = "SUPPLIER_DECLARED"
    link["lab_name"] = None
    link["lab_result_ppm"] = None
    link["lab_loq_ppm"] = None
    link["lab_reported_at"] = None


def _verified_exposure(product, chemical_id):
    route, uses = exposure_shape(product["id"], chemical_id)
    daily, _count = calc.daily_exposure(product, chemical_id, "MODELED", route, uses)
    return daily


def _below_safe_harbor(chemical, value):
    if value is None or chemical is None:
        return False
    level = chemical.get("safe_harbor_level_ug_per_day")
    if level is None:
        return False
    return D(value) < D(level)


@bp.route("/reformulation-projects/<project_id>/transitions", methods=["POST"])
@guard("ComplianceAnalyst")
def transition_project(who, project_id):
    body = validate.body_json()
    action = validate.v_action(body, TRIGGERS)
    project = validate.must_exist("reformulation_projects", project_id, "reformulation project")
    if project["status"] not in LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s" % (action, project["status"]))
    validate.v_writable(body, ("action",))
    product = db.get("products", project["product_id"])
    chemical = db.get("listed_chemicals", project["chemical_id"])
    link = db.get("material_chemicals", project["material_chemical_id"])

    if action == "START":
        project["status"] = "IN_PROGRESS"
        db.touch(project)
        return response.ok(db.serialize("reformulation_projects", project))

    if action == "REWORK":
        project["verified_daily_exposure_ug"] = None
        project["reduction_pct"] = None
        project["status"] = "IN_PROGRESS"
        db.touch(project)
        return response.ok(db.serialize("reformulation_projects", project))

    if action == "ABANDON":
        project["status"] = "ABANDONED"
        db.touch(project)
        return response.ok(db.serialize("reformulation_projects", project))

    if action == "COMPLETE":
        if not _below_safe_harbor(chemical, project.get("verified_daily_exposure_ug")):
            fail("ERR_TARGET_NOT_BELOW_THRESHOLD",
                 "verified_daily_exposure_ug is not strictly below the safe harbor level")
        project["status"] = "COMPLETED"
        db.touch(project)
        posture.recompute_posture(product)
        return response.ok(db.serialize("reformulation_projects", project))

    # SUBMIT_VERIFICATION: rewrite the formulation, then tear down what depended
    # on the old numbers.  PRD 3.9: "Submission is refused with
    # ERR_TARGET_NOT_BELOW_THRESHOLD when the resulting verified_daily_exposure_ug
    # is not strictly less than the chemical's safe_harbor_level_ug_per_day", so
    # the resulting exposure is priced against the gate before anything is kept.
    snapshot = {key: link.get(key) for key in
                ("declared_concentration_ppm", "status", "measurement_basis",
                 "lab_name", "lab_result_ppm", "lab_loq_ppm", "lab_reported_at")}
    _rewrite_link(link, project["target_concentration_ppm"])
    verified = _verified_exposure(product, project["chemical_id"])
    if not _below_safe_harbor(chemical, verified):
        link.update(snapshot)
        fail("ERR_TARGET_NOT_BELOW_THRESHOLD",
             "the resulting verified_daily_exposure_ug is not strictly below "
             "the safe harbor level")
    db.touch(link)
    material = db.get("materials", link["material_id"])
    affected = calc.products_reaching(material) if material is not None else []
    if product is not None and product not in affected:
        affected = affected + [product]
    for touched in affected:
        for assessment in calc.assessments_of(touched["id"]):
            if assessment["status"] == "FINAL":
                cascade.supersede_final_assessment(assessment, recompute_numbers=True,
                                                   touch_product=False)
        posture.recompute_load(touched)
        db.touch(touched)
        posture.recompute_posture(touched)
    project["verified_daily_exposure_ug"] = verified
    baseline = project.get("baseline_daily_exposure_ug")
    if baseline is None or D(baseline) == 0:
        project["reduction_pct"] = None
    else:
        project["reduction_pct"] = rhu(
            D(100) * (D(baseline) - D(verified)) / D(baseline), REDUCTION_DP)
    project["status"] = "VERIFICATION"
    db.touch(project)
    return response.ok(db.serialize("reformulation_projects", project))


@bp.route("/reformulation-projects/<project_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_project(who, project_id):
    project = validate.must_exist("reformulation_projects", project_id, "reformulation project")
    return response.ok(db.serialize("reformulation_projects", project))


@bp.route("/reformulation-projects", methods=["GET"])
@guard(*READ_ROLES)
def list_projects(who):
    return list_endpoint("reformulation_projects", {
        "product_id": "product_id",
        "chemical_id": "chemical_id",
        "material_chemical_id": "material_chemical_id",
        "status": "status",
    })


@bp.route("/products/<product_id>/compliance-summary", methods=["GET"])
@guard(*READ_ROLES)
def compliance_summary(who, product_id):
    product = validate.must_exist("products", product_id, "product")
    notice = None
    notice_id = request.args.get("as_of_notice_id")
    if notice_id is not None and notice_id != "":
        notice = validate.must_exist("notices", notice_id, "notice")
        if notice["product_id"] != product["id"]:
            fail("ERR_NOT_FOUND", "notice %s does not belong to this product" % notice_id)
    return response.ok(defense.summary(product, notice))
