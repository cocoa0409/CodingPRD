"""Cornea tissue: reads, grading, classification, quarantine, disposal, custody."""

from flask import Blueprint, request

import auth
import calc
import cascade
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("tissues", __name__)

DISPOSITION_STATUSES = (
    "UNGRADED",
    "ELIGIBLE",
    "RESERVED",
    "ISSUED",
    "IMPLANTED",
    "QUARANTINED",
    "RELEASED_FOR_RESEARCH",
    "RELEASED_FOR_TRAINING",
    "DISCARDED",
)
CUSTODY_STATUSES = ("IN_HOUSE", "IN_TRANSIT", "AT_SURGEON", "RETURNED_TO_BANK", "DESTROYED")
METHODS = ("SLIT_LAMP", "SPECULAR")
SLIT_LAMP_FIELDS = ("epithelium_defect_grade", "stromal_clarity_grade", "dm_folds_grade")
SPECULAR_FIELDS = ("guttata_grade", "endothelial_cell_count")
DISPOSAL_METHODS = ("INCINERATION", "AUTOCLAVE", "RESEARCH_TRANSFER")
TRANSPLANT_CLASSIFICATIONS = ("TRANSPLANT_OPTICAL", "TRANSPLANT_THERAPEUTIC")
DISCARDABLE_FROM = ("ELIGIBLE", "QUARANTINED", "RELEASED_FOR_RESEARCH", "RELEASED_FOR_TRAINING")


def delivering_shipment(allocation_id, statuses=("DELIVERED",)):
    rows = [
        s
        for s in store.DB["shipments"].values()
        if s["allocation_id"] == allocation_id and s["status"] in statuses
    ]
    rows = store.by_created(rows)
    return rows[-1] if rows else None


def _surgeon_of_allocation(allocation):
    req = store.DB["requests"].get(allocation["request_id"])
    if req is None:
        return None
    return req["surgeon_id"]


def _require_custody_owner(actor, tissue):
    """Ownership for implantation and unused-tissue return (ladder rung 10)."""
    if not actor.is_surgeon:
        return None
    allocation = cascade.confirmed_allocation_for_tissue(tissue["id"])
    if allocation is None:
        return None
    if _surgeon_of_allocation(allocation) != actor.user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "This tissue was not issued to the acting surgeon."
        )
    return allocation


@bp.get("/eye-bank/tissues/<tissue_id>")
def get_tissue(tissue_id):
    auth.authenticate(
        (
            "EyeBankCoordinator",
            "LabTechnician",
            "MedicalDirector",
            "EvaluationTechnician",
            "Surgeon",
        )
    )
    row = validate.lookup("tissues", tissue_id)
    return envelope.ok(serialize.tissue(row))


@bp.get("/eye-bank/tissues")
def list_tissues():
    auth.authenticate(
        ("EyeBankCoordinator", "MedicalDirector", "EvaluationTechnician", "Surgeon")
    )
    rows = list(store.DB["tissues"].values())
    donor_id = request.args.get("donor_id")
    if donor_id is not None:
        rows = [r for r in rows if r["donor_id"] == donor_id]
    recovery_id = request.args.get("recovery_id")
    if recovery_id is not None:
        rows = [r for r in rows if r["recovery_id"] == recovery_id]
    disposition = request.args.get("disposition_status")
    if disposition is not None:
        validate.filter_enum("disposition_status", disposition, DISPOSITION_STATUSES)
        rows = [r for r in rows if r["disposition_status"] == disposition]
    custody = request.args.get("custody_status")
    if custody is not None:
        validate.filter_enum("custody_status", custody, CUSTODY_STATUSES)
        rows = [r for r in rows if r["custody_status"] == custody]
    rows = store.sort_desc(rows, lambda r: r["preserved_at"])
    return envelope.paginated(rows, serialize.tissue)


@bp.post("/eye-bank/tissues/<tissue_id>/evaluations")
def create_evaluation(tissue_id):
    actor = auth.authenticate(("EvaluationTechnician",))
    tissue = validate.lookup("tissues", tissue_id)
    body = auth.body_dict()

    technician = validate.resolve_fk(body, "evaluator_technician_id", "technicians")

    validate.req_str(body, "evaluator_technician_id")
    method = validate.req_enum(body, "method", METHODS)
    performed_at = validate.req_dt(body, "performed_at")
    if method == "SLIT_LAMP":
        required, forbidden = SLIT_LAMP_FIELDS, SPECULAR_FIELDS
    else:
        required, forbidden = SPECULAR_FIELDS, SLIT_LAMP_FIELDS
    for field in forbidden:
        if field in body and body.get(field) is not None:
            raise ApiError("ERR_INVALID_REQUEST", "%s is forbidden for %s." % (field, method))
    grades = {}
    if method == "SLIT_LAMP":
        grades["epithelium_defect_grade"] = validate.req_int(
            body, "epithelium_defect_grade", 0, 4
        )
        grades["stromal_clarity_grade"] = validate.req_int(body, "stromal_clarity_grade", 0, 4)
        grades["dm_folds_grade"] = validate.req_int(body, "dm_folds_grade", 0, 4)
        grades["guttata_grade"] = None
        grades["endothelial_cell_count"] = None
    else:
        grades["guttata_grade"] = validate.req_int(body, "guttata_grade", 0, 2)
        grades["endothelial_cell_count"] = validate.req_int(
            body, "endothelial_cell_count", 500, 4000
        )
        grades["epithelium_defect_grade"] = None
        grades["stromal_clarity_grade"] = None
        grades["dm_folds_grade"] = None
    expected = validate.req_int(body, "expected_tissue_version")
    if technician is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "evaluator_technician_id must reference a technician."
        )

    if expected != tissue["version"]:
        raise ApiError(
            "ERR_STALE_TISSUE_VERSION",
            "expected_tissue_version %s does not match %s." % (expected, tissue["version"]),
        )

    if actor.user_id != technician["id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "Grading on another technician's behalf is refused."
        )

    if tissue["disposition_status"] in ("IMPLANTED", "DISCARDED"):
        raise ApiError("ERR_TISSUE_NOT_ELIGIBLE", "This tissue is no longer gradeable.")

    recovery = store.DB["recoveries"].get(tissue["recovery_id"])
    if recovery is not None and recovery["technician_id"] == technician["id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The recovering technician may not grade this cornea.",
        )
    if (
        technician["status"] != "ACTIVE"
        or technician["certification_expires_at"] <= store.now()
        or technician["certification_level"] != "RECOVERY_AND_EVAL"
    ):
        raise ApiError("ERR_TECHNICIAN_NOT_CERTIFIED", "The evaluator may not grade tissue.")

    for earlier in store.by_created(
        [
            e
            for e in store.DB["evaluations"].values()
            if e["tissue_id"] == tissue_id and e["method"] == method and e["status"] == "RECORDED"
        ]
    ):
        earlier["status"] = "SUPERSEDED"
        store.touch(earlier)

    row = store.base_row()
    row.update(
        {
            "tissue_id": tissue_id,
            "evaluator_technician_id": technician["id"],
            "method": method,
            "performed_at": performed_at,
            "epithelium_defect_grade": grades["epithelium_defect_grade"],
            "stromal_clarity_grade": grades["stromal_clarity_grade"],
            "dm_folds_grade": grades["dm_folds_grade"],
            "guttata_grade": grades["guttata_grade"],
            "endothelial_cell_count": grades["endothelial_cell_count"],
            "status": "RECORDED",
            "tissue_version_after": tissue["version"],
        }
    )
    store.DB["evaluations"][row["id"]] = row

    store.touch(tissue)
    row["tissue_version_after"] = tissue["version"]

    return envelope.ok(serialize.evaluation(row), 201)


@bp.get("/eye-bank/tissues/<tissue_id>/evaluations")
def list_evaluations(tissue_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "EvaluationTechnician"))
    validate.lookup("tissues", tissue_id)
    rows = [e for e in store.DB["evaluations"].values() if e["tissue_id"] == tissue_id]
    rows = store.sort_desc(rows, lambda r: r["performed_at"])
    return envelope.nested_list(rows, serialize.evaluation)


@bp.post("/eye-bank/tissues/<tissue_id>/classify")
def classify(tissue_id):
    auth.authenticate(("MedicalDirector",))
    tissue = validate.lookup("tissues", tissue_id)
    body = auth.body_dict()
    override = validate.opt_enum(body, "intended_use_override", ("TRANSPLANT",))

    if tissue["disposition_status"] != "UNGRADED":
        raise ApiError("ERR_TISSUE_NOT_ELIGIBLE", "Only an UNGRADED tissue may be classified.")

    donor = store.DB["donors"][tissue["donor_id"]]
    if donor["consent_scope"] == "NONE":
        raise ApiError("ERR_CONSENT_SCOPE_VIOLATION", "The donor has no consent scope.")
    if donor["serology_status"] == "PENDING":
        raise ApiError("ERR_SEROLOGY_PENDING", "The donor has no resulted serology panel.")
    if donor["lookback_flag"]:
        raise ApiError("ERR_DONOR_UNDER_LOOKBACK", "The donor is under lookback investigation.")

    slit_lamp = calc.recorded_evaluation(tissue_id, "SLIT_LAMP")
    specular = calc.recorded_evaluation(tissue_id, "SPECULAR")
    if slit_lamp is None or specular is None:
        raise ApiError(
            "ERR_EVALUATION_INCOMPLETE",
            "Both a RECORDED SLIT_LAMP and a RECORDED SPECULAR evaluation are required.",
        )

    if override == "TRANSPLANT" and donor["screening_risk_score"] >= 50:
        raise ApiError(
            "ERR_SCREENING_RISK_TOO_HIGH",
            "The donor's screening risk forbids transplant intent.",
        )

    recovery = store.DB["recoveries"][tissue["recovery_id"]]
    band = recovery["time_limit_band"]
    quality = calc.tissue_quality_score(slit_lamp, specular, donor)
    ecd = specular["endothelial_cell_count"]
    classification = calc.tissue_classification(donor, band, quality, ecd)

    tissue["tissue_quality_score"] = quality
    tissue["classification"] = classification
    tissue["disposition_status"] = calc.CLASSIFICATION_DISPOSITION[classification]
    if classification == "UNSUITABLE":
        tissue["disposal_method"] = "INCINERATION"
        tissue["custody_status"] = "DESTROYED"
    hours = calc.final_shelf_life(tissue["preservation_medium"], band, donor, ecd)
    calc.apply_shelf_life(tissue, hours, "FINAL_AT_CLASSIFICATION")
    store.touch(tissue)

    return envelope.ok(serialize.tissue(tissue))


@bp.post("/eye-bank/tissues/<tissue_id>/quarantine")
def quarantine(tissue_id):
    auth.authenticate(("MedicalDirector", "EyeBankCoordinator"))
    tissue = validate.lookup("tissues", tissue_id)
    body = auth.body_dict()
    reason = validate.req_str(body, "quarantine_reason", 1, 500)

    if tissue["disposition_status"] not in ("ELIGIBLE", "RESERVED"):
        raise ApiError(
            "ERR_TISSUE_NOT_ELIGIBLE", "Only an ELIGIBLE or RESERVED tissue may be quarantined."
        )

    cascade.quarantine_tissue(tissue, reason)
    return envelope.ok(serialize.tissue(tissue))


@bp.post("/eye-bank/tissues/<tissue_id>/release-quarantine")
def release_quarantine(tissue_id):
    auth.authenticate(("MedicalDirector",))
    tissue = validate.lookup("tissues", tissue_id)

    if tissue["disposition_status"] != "QUARANTINED":
        raise ApiError("ERR_TISSUE_NOT_ELIGIBLE", "Only a QUARANTINED tissue may be released.")
    if tissue["classification"] not in TRANSPLANT_CLASSIFICATIONS:
        raise ApiError(
            "ERR_TISSUE_NOT_ELIGIBLE",
            "Only transplant-grade tissue may rejoin the allocatable pool.",
        )

    donor = store.DB["donors"][tissue["donor_id"]]
    if donor["serology_status"] == "REACTIVE":
        raise ApiError("ERR_SEROLOGY_REACTIVE", "The donor is serologically reactive.")
    if donor["lookback_flag"]:
        raise ApiError("ERR_DONOR_UNDER_LOOKBACK", "The donor is under lookback investigation.")

    tissue["disposition_status"] = "ELIGIBLE"
    tissue["quarantine_reason"] = None
    store.touch(tissue)
    return envelope.ok(serialize.tissue(tissue))


@bp.post("/eye-bank/tissues/<tissue_id>/discard")
def discard(tissue_id):
    auth.authenticate(("MedicalDirector", "EyeBankCoordinator"))
    tissue = validate.lookup("tissues", tissue_id)
    body = auth.body_dict()
    method = validate.req_enum(body, "disposal_method", DISPOSAL_METHODS)

    if tissue["disposition_status"] not in DISCARDABLE_FROM:
        raise ApiError("ERR_TISSUE_NOT_ELIGIBLE", "This tissue may not be disposed of.")
    if tissue["disposition_status"] == "RELEASED_FOR_RESEARCH" and method != "RESEARCH_TRANSFER":
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Research-released tissue must be disposed of by RESEARCH_TRANSFER.",
        )

    tissue["disposal_method"] = method
    tissue["disposition_status"] = "DISCARDED"
    tissue["custody_status"] = "DESTROYED"
    tissue["quarantine_reason"] = tissue["quarantine_reason"]
    store.touch(tissue)
    return envelope.ok(serialize.tissue(tissue))


@bp.post("/eye-bank/tissues/<tissue_id>/implant")
def implant(tissue_id):
    actor = auth.authenticate(("Surgeon",))
    tissue = validate.lookup("tissues", tissue_id)

    allocation = _require_custody_owner(actor, tissue)

    if tissue["disposition_status"] != "ISSUED":
        raise ApiError("ERR_TISSUE_NOT_ELIGIBLE", "Implantation requires an ISSUED tissue.")
    if tissue["custody_status"] != "AT_SURGEON":
        raise ApiError("ERR_TISSUE_CUSTODY_INVALID", "The tissue is not at the surgeon.")
    if tissue["expires_at"] <= store.now():
        raise ApiError("ERR_TISSUE_EXPIRED", "The tissue has expired.")

    shipment = None
    if allocation is not None:
        shipment = delivering_shipment(allocation["id"])
    if shipment is None or shipment["integrity_verdict"] not in ("PASS", "EXCURSION_MINOR"):
        raise ApiError(
            "ERR_SHIPMENT_INTEGRITY_FAILED",
            "The delivering shipment did not pass cold-chain adjudication.",
        )

    tissue["disposition_status"] = "IMPLANTED"
    store.touch(tissue)

    allocation["status"] = "CONSUMED"
    store.touch(allocation)
    req = store.DB["requests"].get(allocation["request_id"])
    if req is not None:
        req["status"] = "FULFILLED"
        store.touch(req)
        surgeon = store.DB["surgeons"].get(req["surgeon_id"])
        if surgeon is not None:
            calc.recompute_fee_ledger(surgeon)
            store.touch(surgeon)

    return envelope.ok(serialize.tissue(tissue))


@bp.post("/eye-bank/tissues/<tissue_id>/return")
def return_tissue(tissue_id):
    actor = auth.authenticate(("Surgeon",))
    tissue = validate.lookup("tissues", tissue_id)
    body = auth.body_dict()
    return_reason = validate.req_str(body, "return_reason", 1, 500)

    allocation = _require_custody_owner(actor, tissue)

    if tissue["disposition_status"] != "ISSUED":
        raise ApiError("ERR_TISSUE_NOT_ELIGIBLE", "Return requires an ISSUED tissue.")
    if tissue["custody_status"] != "AT_SURGEON":
        raise ApiError("ERR_TISSUE_CUSTODY_INVALID", "The tissue is not at the surgeon.")

    shipment = delivering_shipment(allocation["id"]) if allocation is not None else None

    tissue["custody_status"] = "RETURNED_TO_BANK"
    tissue["reissue_generation"] = tissue["reissue_generation"] + 1
    if (
        shipment is not None
        and shipment["integrity_verdict"] == "PASS"
        and tissue["expires_at"] > store.now()
    ):
        tissue["disposition_status"] = "ELIGIBLE"
        tissue["quarantine_reason"] = None
    else:
        tissue["disposition_status"] = "QUARANTINED"
        tissue["quarantine_reason"] = return_reason
    store.touch(tissue)

    if shipment is not None:
        shipment["status"] = "RETURNED"
        store.touch(shipment)
    if allocation is not None:
        cascade.release_allocation(allocation, "UNUSED_TISSUE_RETURNED")

    return envelope.ok(serialize.tissue(tissue))
