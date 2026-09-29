"""Quality measure abstractions: two variants, one lifecycle (PRD 3.9)."""
from flask import Blueprint

import db
import response as resp
from constants import CASE_TERMINAL, MEASURE_CODES
from errors import fail
from middleware import (
    Field,
    apply_filters,
    authenticate,
    load_path,
    load_ref,
    pagination,
    read_body,
)
from services import reporting

bp = Blueprint("abstractions", __name__)

CREATE_SPEC = [
    Field("case_id", "str"),
    Field("measure_code", "str", enum=MEASURE_CODES),
]

FINALIZE_SPEC = [Field("attestation_note", "str", min_len=1)]
RETRACT_SPEC = [Field("retraction_reason", "str", min_len=1)]


def _recompute_attached(report):
    """PRD 3.9: the count, the three rates and the mean, under the report's
    current rate_variant."""
    reporting.recompute_counts(report)
    reporting.recompute_rates(report, report["rate_variant"])
    reporting.recompute_mean_dtn_excess(report)


@bp.route("/abstractions", methods=["POST"])
def create_abstraction():
    user_id, _role = authenticate(("QualityAbstractor",))
    body = read_body(CREATE_SPEC)
    case = load_ref("cases", body["case_id"])
    if case["status"] in CASE_TERMINAL:
        fail("ERR_CASE_NOT_ACTIVE",
             "Abstraction begins while the case is live; this case is %s."
             % case["status"])
    for existing in db.all_of("abstractions"):
        if (existing["case_id"] == case["id"]
                and existing["measure_code"] == body["measure_code"]
                and existing["status"] != "RETRACTED"):
            fail("ERR_DUPLICATE_ABSTRACTION",
                 "A live abstraction already covers this case and measure.")
    record = {
        "case_id": case["id"],
        "report_id": None,
        "measure_code": body["measure_code"],
        "status": "DRAFT",
        "variant": "PROVISIONAL",
        "numerator_flag": False,
        "denominator_included": True,
        "exclusion_reason": "NONE",
        "abstracted_by_user_id": user_id,
        "attested_by_user_id": None,
        "attestation_note": None,
        "retraction_reason": None,
    }
    reporting.evaluate_abstraction(record, case, "PROVISIONAL")
    report = reporting.draft_report_for_case(case)
    if report is not None:
        record["report_id"] = report["id"]
    db.insert("abstractions", record)
    if report is not None:
        _recompute_attached(report)
    return resp.object_response(record, 201)


@bp.route("/abstractions/<record_id>", methods=["GET"])
def read_abstraction(record_id):
    authenticate("any")
    return resp.object_response(load_path("abstractions", record_id))


@bp.route("/abstractions", methods=["GET"])
def list_abstractions():
    authenticate("any")
    limit, offset = pagination()
    records = apply_filters(db.all_of("abstractions"), {
        "case_id": "case_id",
        "report_id": "report_id",
        "measure_code": "measure_code",
        "status": "status",
        "variant": "variant",
        "denominator_included": "denominator_included",
    })
    return resp.list_response(records, limit, offset)


@bp.route("/abstractions/<record_id>/finalize", methods=["POST"])
def finalize_abstraction(record_id):
    user_id, _role = authenticate(("QualityAbstractor",))
    record = load_path("abstractions", record_id)
    body = read_body(FINALIZE_SPEC)
    if record["status"] != "DRAFT":
        fail("ERR_INVALID_ABSTRACTION_STATE",
             "No finalisation is declared from %s." % record["status"])
    case = db.get("cases", record["case_id"])
    if case is None or case["status"] not in CASE_TERMINAL:
        fail("ERR_INVALID_ABSTRACTION_STATE",
             "An abstraction is attested only after its case has finished.")
    if user_id == record["abstracted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The attesting user must differ from abstracted_by_user_id.")
    record["status"] = "FINALIZED"
    record["variant"] = "CERTIFIED"
    record["attested_by_user_id"] = user_id
    record["attestation_note"] = body["attestation_note"]
    reporting.evaluate_abstraction(record, case, "CERTIFIED")
    db.touch(record)
    if record["report_id"]:
        report = db.get("reports", record["report_id"])
        if report is not None:
            _recompute_attached(report)
    return resp.object_response(record)


@bp.route("/abstractions/<record_id>/retract", methods=["POST"])
def retract_abstraction(record_id):
    authenticate(("QualityAbstractor",))
    record = load_path("abstractions", record_id)
    body = read_body(RETRACT_SPEC)
    report = db.get("reports", record["report_id"]) if record["report_id"] else None
    if record["status"] == "FINALIZED":
        if report is not None and report["status"] not in ("DRAFT", "RETURNED"):
            fail("ERR_INVALID_ABSTRACTION_STATE",
                 "The attached report is %s." % report["status"])
    elif record["status"] != "DRAFT":
        fail("ERR_INVALID_ABSTRACTION_STATE",
             "No retraction is declared from %s." % record["status"])
    record["status"] = "RETRACTED"
    record["retraction_reason"] = body["retraction_reason"]
    record["report_id"] = None
    db.touch(record)
    if report is not None:
        _recompute_attached(report)
    return resp.object_response(record)
