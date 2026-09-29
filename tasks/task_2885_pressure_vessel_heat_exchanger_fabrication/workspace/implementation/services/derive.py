"""Derived fields, roll-ups and cascades (PRD sections 2.10, 3.1, 3.9).

Derived values are recomputed inside every request that changes one of their
inputs, and re-evaluated on every read that returns the owning record. A read
never mutates a record: the *_view helpers overlay the derived values on the
stored ones without touching `updated_at` or `version`.
"""

from decimal import Decimal

import db
from services import calc

OPEN_DISPOSITIONS = ("OPEN", "REPAIR", "USE_AS_IS")


# ---------------------------------------------------------------------------
# Child indexes
# ---------------------------------------------------------------------------

def children(store_name, field, value):
    return [rec for rec in db.all_of(store_name) if rec.get(field) == value]


def job_calculations(job_id):
    return children("calculations", "job_id", job_id)


def job_parts(job_id):
    return children("parts", "job_id", job_id)


def job_welds(job_id):
    return children("welds", "job_id", job_id)


def job_exams(job_id):
    weld_ids = {weld["id"] for weld in job_welds(job_id)}
    return [exam for exam in db.all_of("exams") if exam["weld_id"] in weld_ids]


def weld_exams(weld_id):
    return children("exams", "weld_id", weld_id)


def job_nonconformances(job_id):
    return children("nonconformances", "job_id", job_id)


def job_batches(job_id):
    return children("batches", "job_id", job_id)


def job_tests(job_id):
    return children("tests", "job_id", job_id)


def job_reports(job_id):
    return children("reports", "job_id", job_id)


def batch_welds(batch_id):
    return children("welds", "pwht_batch_id", batch_id)


# ---------------------------------------------------------------------------
# Certificate posture (PRD 3.1)
# ---------------------------------------------------------------------------

def certificate_status(cert):
    expires_on = calc.parse_date(cert["expires_on"])
    if expires_on < db.clock_today():
        return "EXPIRED"
    if cert["open_major_findings_count"] >= 3:
        return "SUSPENDED"
    if cert["open_major_findings_count"] >= 1 or cert["open_minor_findings_count"] > 5:
        return "PROBATION"
    return "ACTIVE"


def certificate_authorized(cert):
    expires_on = calc.parse_date(cert["expires_on"])
    return (certificate_status(cert) == "ACTIVE"
            and expires_on >= db.clock_today()
            and cert["open_major_findings_count"] == 0)


def certificate_expired(cert):
    return calc.parse_date(cert["expires_on"]) < db.clock_today()


def certificate_view(cert):
    out = db.public(cert)
    out["status"] = certificate_status(cert)
    out["stamping_authorized"] = certificate_authorized(cert)
    return out


def sync_certificate(cert):
    return db.mutate(cert, {
        "status": certificate_status(cert),
        "stamping_authorized": certificate_authorized(cert),
    })


def last_audit_closed_on(certificate_id):
    closed = [audit for audit in children("audits", "certificate_id", certificate_id)
              if audit["status"] == "CLOSED" and audit.get("closed_on")]
    if not closed:
        return None
    closed.sort(key=lambda a: (a["closed_on"], a["created_at"], a["_seq"]))
    return closed[-1]["closed_on"]


# ---------------------------------------------------------------------------
# Welder qualification continuity (PRD 3.5)
# ---------------------------------------------------------------------------
CONTINUITY_LIMIT_DAYS = 180


def qualification_days(qual):
    last = calc.parse_date(qual["last_continuity_date"])
    return (db.clock_today() - last).days


def qualification_status(qual):
    return "LAPSED" if qualification_days(qual) > CONTINUITY_LIMIT_DAYS else "QUALIFIED"


def qualification_view(qual):
    out = db.public(qual)
    out["days_since_continuity"] = qualification_days(qual)
    out["status"] = qualification_status(qual)
    return out


def sync_qualification(qual):
    return db.mutate(qual, {
        "days_since_continuity": qualification_days(qual),
        "status": qualification_status(qual),
    })


# ---------------------------------------------------------------------------
# Material heat mass ledger (PRD 3.4)
# ---------------------------------------------------------------------------

def heat_issued_lb(heat_id):
    total = Decimal("0.00")
    for part in children("parts", "heat_id", heat_id):
        if part["status"] == "ISSUED":
            total += part["issued_quantity_lb"]
    return calc.q(total, 2)


def sync_heat_ledger(heat):
    issued = heat_issued_lb(heat["id"])
    remaining = calc.q(heat["quantity_received_lb"] - issued, 2)
    changes = {"quantity_issued_lb": issued, "quantity_remaining_lb": remaining}
    status = heat["status"]
    if status == "ACCEPTED" and remaining == Decimal("0.00"):
        changes["status"] = "DEPLETED"
    elif status == "DEPLETED" and remaining > Decimal("0.00"):
        changes["status"] = "ACCEPTED"
    return db.mutate(heat, changes)


def part_traceability(part):
    heat = db.get("heats", part["heat_id"])
    if heat is None:
        return False
    return bool(heat["mtr_received"]) and heat["status"] in ("ACCEPTED", "DEPLETED")


def part_view(part):
    out = db.public(part)
    out["heat_traceability_complete"] = part_traceability(part)
    return out


def part_material_class(part):
    heat = db.get("heats", part["heat_id"])
    return None if heat is None else heat["material_class"]


# ---------------------------------------------------------------------------
# Vessel job roll-ups (PRD 3.2, 3.3, 3.6)
# ---------------------------------------------------------------------------

def governing_joint_efficiency(job_id):
    approved = [c for c in job_calculations(job_id) if c["status"] == "APPROVED"]
    if not approved:
        return None
    return min(c["joint_efficiency"] for c in approved)


def nonconformance_open_count(job_id):
    return len([n for n in job_nonconformances(job_id)
                if n["disposition"] in OPEN_DISPOSITIONS])


def weld_completion_pct(job_id):
    welds = job_welds(job_id)
    denominator = len(welds)
    if denominator == 0:
        return Decimal("0.00")
    numerator = 0
    for weld in welds:
        if (weld["fab_status"] == "WELDED"
                and weld["nde_status"] == "ACCEPTED"
                and weld["pwht_status"] in ("NOT_REQUIRED", "COMPLETE")):
            numerator += 1
    return calc.ratio_round(100 * numerator, denominator, 2)


def job_view(job):
    out = db.public(job)
    out["governing_joint_efficiency"] = governing_joint_efficiency(job["id"])
    out["nonconformance_open_count"] = nonconformance_open_count(job["id"])
    out["weld_completion_pct"] = weld_completion_pct(job["id"])
    return out


def recompute_job(job, changes=None):
    """Persist the job's roll-ups together with any explicit changes, as one
    mutation of the job record."""
    updates = dict(changes or {})
    updates["governing_joint_efficiency"] = governing_joint_efficiency(job["id"])
    updates["nonconformance_open_count"] = nonconformance_open_count(job["id"])
    updates["weld_completion_pct"] = weld_completion_pct(job["id"])
    return db.mutate(job, updates)


def approved_extent_for_component(job_id, component):
    if component is None:
        return None
    for sheet in job_calculations(job_id):
        if sheet["status"] == "APPROVED" and sheet["component"] == component:
            return sheet["rt_extent_declared"]
    return None


def resolve_weld_examination(weld, job):
    """Resolve required_volumetric_pct, volumetric_method and
    required_surface_method for one joint."""
    part_a = db.get("parts", weld["part_a_id"])
    component = part_a["component_type"] if part_a else None
    extent = approved_extent_for_component(job["id"], component)
    coverage = calc.required_volumetric_pct(weld, job, extent)
    method = calc.volumetric_method(weld, coverage)
    classes = []
    for key in ("part_a_id", "part_b_id"):
        part = db.get("parts", weld.get(key))
        if part is not None:
            material_class = part_material_class(part)
            if material_class:
                classes.append(material_class)
    surface = calc.required_surface_method(weld, classes)
    return coverage, method, surface


# ---------------------------------------------------------------------------
# Data package scoring and the AI_SIGNED <-> STAMP_HOLD cycle (PRD 3.9)
# ---------------------------------------------------------------------------

def _section_fractions(job):
    job_id = job["id"]
    required = job["required_components"]
    sheets = job_calculations(job_id)
    parts = job_parts(job_id)
    welds = job_welds(job_id)
    exams = job_exams(job_id)
    batches = [b for b in job_batches(job_id) if b["status"] != "ABORTED"]
    tests = job_tests(job_id)

    approved_components = {s["component"] for s in sheets if s["status"] == "APPROVED"}
    design_num = len([c for c in required if c in approved_components])

    material_num = 0
    for component in required:
        for part in parts:
            if part["status"] != "ISSUED" or part["component_type"] != component:
                continue
            heat = db.get("heats", part["heat_id"])
            if heat is not None and heat["status"] in ("ACCEPTED", "DEPLETED"):
                material_num += 1
                break

    welding_num = len([w for w in welds if w["fab_status"] == "WELDED"])
    nde_num = len([e for e in exams if e["result"] == "ACCEPT"])
    pwht_num = len([b for b in batches
                    if b["status"] == "COMPLETE" and b["chart_uploaded"]])
    test_num = len([t for t in tests if t["result"] == "PASS"])

    return {
        "DESIGN": (design_num, len(required)),
        "MATERIAL": (material_num, len(required)),
        "WELDING": (welding_num, len(welds)),
        "NDE": (nde_num, len(exams)),
        "PWHT": (pwht_num, len(batches)),
        "TEST": (test_num, len(tests)),
    }


def report_derived(report):
    job = db.get("jobs", report["job_id"])
    certificate = db.get("certificates", job["certificate_id"])
    fractions = _section_fractions(job)
    section_scores = {}
    missing_items = []
    total = Decimal("0.00")
    for section in calc.SECTION_ORDER:
        numerator, denominator = fractions[section]
        points, complete = calc.section_points(section, numerator, denominator)
        section_scores[section] = points
        total += points
        if not complete:
            missing_items.append(section)
    completeness = calc.q(total, 2)
    if nonconformance_open_count(job["id"]) > 0:
        missing_items.append("OPEN_NONCONFORMANCE")
    if not certificate_authorized(certificate):
        missing_items.append("CERTIFICATE_NOT_AUTHORIZED")
    return section_scores, completeness, missing_items


def report_hold_target(report):
    """The AI_SIGNED <-> STAMP_HOLD posture the current world implies."""
    status = report["status"]
    if status not in ("AI_SIGNED", "STAMP_HOLD"):
        return status
    job = db.get("jobs", report["job_id"])
    certificate = db.get("certificates", job["certificate_id"])
    holding = (not certificate_authorized(certificate)
               or nonconformance_open_count(job["id"]) > 0)
    return "STAMP_HOLD" if holding else "AI_SIGNED"


def report_view(report):
    out = db.public(report)
    section_scores, completeness, missing_items = report_derived(report)
    out["section_scores"] = section_scores
    out["completeness_score"] = completeness
    out["missing_items"] = missing_items
    return out


def sync_report(report):
    if report["status"] in ("VOIDED", "STAMPED"):
        return False
    section_scores, completeness, missing_items = report_derived(report)
    return db.mutate(report, {
        "section_scores": section_scores,
        "completeness_score": completeness,
        "missing_items": missing_items,
        "status": report_hold_target(report),
    })


def sync_job_reports(job):
    touched = 0
    for report in job_reports(job["id"]):
        if sync_report(report):
            touched += 1
    return touched


def sync_certificate_reports(certificate):
    touched = 0
    for job in children("jobs", "certificate_id", certificate["id"]):
        touched += sync_job_reports(job)
    return touched
