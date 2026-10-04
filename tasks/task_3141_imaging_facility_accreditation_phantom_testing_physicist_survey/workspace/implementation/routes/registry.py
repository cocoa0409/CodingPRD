"""DoseRegistryRecord endpoints (PRD §3.6, §4)."""

from decimal import Decimal

import flask

import db
import response
from errors import fail
from middleware import require
from services import calculations, common

RECORD_FEE_CENTS = 2500


def register_routes(app):

    @app.route("/accreditation/dose-registry-records", methods=["POST"])
    @require(["FacilityAdmin"])
    def stage_record(principal):
        payload = common.body()
        common.require_fields(
            payload, ["unit_id", "exam_category_code", "exam_month", "dose_index_value"]
        )
        common.check_required_enum(payload, "exam_category_code", "exam_category_code")
        unit = common.get_unit(payload["unit_id"])
        if unit["unit_status"] != "ENROLLED":
            fail("ERR_UNIT_DEFERRED", "the owning modality unit is not ENROLLED")

        exam_month = db.parse_ts(payload["exam_month"])
        for other in db.DOSE_RECORDS.values():
            if other["unit_id"] != unit["id"]:
                continue
            if other["exam_category_code"] != payload["exam_category_code"]:
                continue
            if db.parse_ts(other["exam_month"]) == exam_month:
                fail("ERR_DOSE_RECORD_DUPLICATE", "this unit, category and month are already reported")

        # benchmark_comparison_value is accepted but ignored.
        record = common.make_record(
            id=db.new_id(),
            unit_id=unit["id"],
            exam_category_code=payload["exam_category_code"],
            exam_month=db.as_ts(payload["exam_month"]),
            dose_index_value=Decimal(str(payload["dose_index_value"])),
            benchmark_status="NOT_EVALUATED",
            submission_status="STAGED",
            submitted_at=None,
            benchmark_comparison_value=None,
            dose_benchmark_average=None,
            registry_fee_cents=0,
        )
        db.DOSE_RECORDS[record["id"]] = record
        common.touch(unit)
        return response.ok(common.serialize(record), 201)

    @app.route("/accreditation/dose-registry-records", methods=["GET"])
    @require(["Any"])
    def list_records(principal):
        rows = list(db.DOSE_RECORDS.values())
        for field in ("unit_id", "exam_category_code", "submission_status"):
            wanted = flask.request.args.get(field)
            if wanted:
                rows = [r for r in rows if r.get(field) == wanted]
        rows.sort(key=lambda r: r["created_at"])
        page, meta = response.paginate(rows, flask.request.args)
        return response.ok(common.serialize_many(page), 200, meta)

    @app.route("/accreditation/dose-registry-records/<record_id>", methods=["GET"])
    @require(["Any"])
    def read_record(principal, record_id):
        return response.ok(common.serialize(common.get_record(record_id)))

    @app.route("/accreditation/dose-registry-records/<record_id>/submit", methods=["POST"])
    @require(["FacilityAdmin"])
    def submit_record(principal, record_id):
        record = common.get_record(record_id)

        if record["submission_status"] in ("SUBMITTED", "REJECTED"):
            fail("ERR_ALREADY_TERMINAL", "the registry record has already reached a terminal state")
        if record["submission_status"] != "STAGED":
            fail("ERR_INVALID_STATE", "the registry record is not STAGED")

        if Decimal(str(record["dose_index_value"])) <= 0:
            fail("ERR_INVALID_REQUEST", "dose_index_value must be greater than zero")

        unit = db.MODALITY_UNITS.get(record["unit_id"])
        facility = db.FACILITIES.get(unit["facility_id"]) if unit is not None else None
        if facility is not None and facility["registry_credit_cents"] < RECORD_FEE_CENTS:
            fail("ERR_INSUFFICIENT_REGISTRY_CREDIT", "registry credit does not cover the record fee")

        stamp = db.now()
        if facility is not None:
            facility["registry_credit_cents"] = facility["registry_credit_cents"] - RECORD_FEE_CENTS

        record["submission_status"] = "SUBMITTED"
        record["benchmark_comparison_value"] = Decimal("0")
        status, comparison = calculations.registry_benchmark_classification(record)
        record["benchmark_status"] = status
        record["benchmark_comparison_value"] = comparison
        record["dose_benchmark_average"] = calculations.facility_dose_index_benchmark(record)
        record["registry_fee_cents"] = RECORD_FEE_CENTS
        record["submitted_at"] = db.SCENARIO_CLOCK
        common.touch(record, stamp)

        # Re-derive the unit average and its rank among the submits the unit has
        # ever made; the read-back reports the most recent six-digit figure.
        for other in sorted(
            (r for r in db.DOSE_RECORDS.values()
             if r["unit_id"] == record["unit_id"]
             and r["exam_category_code"] == record["exam_category_code"]),
            key=calculations.unit_submit_rank,
        ):
            other["dose_benchmark_average"] = calculations.facility_dose_index_benchmark(other)

        return response.ok(common.serialize(record))

    @app.route("/accreditation/dose-registry-records/<record_id>/reject", methods=["POST"])
    @require(["AccreditationBody"])
    def reject_record(principal, record_id):
        record = common.get_record(record_id)

        if record["submission_status"] == "REJECTED":
            fail("ERR_ALREADY_TERMINAL", "the registry record has already reached a terminal state")
        if record["submission_status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE", "the registry record is not SUBMITTED")

        unit = db.MODALITY_UNITS.get(record["unit_id"])
        facility = db.FACILITIES.get(unit["facility_id"]) if unit is not None else None

        stamp = db.now()
        record["registry_fee_cents"] = 0
        record["submitted_at"] = None
        record["benchmark_status"] = "NOT_EVALUATED"
        record["dose_benchmark_average"] = None
        common.set_field(record, "submission_status", "REJECTED", stamp)

        if facility is not None:
            facility["registry_credit_cents"] = facility["registry_credit_cents"] + RECORD_FEE_CENTS
        return response.ok(common.serialize(record))