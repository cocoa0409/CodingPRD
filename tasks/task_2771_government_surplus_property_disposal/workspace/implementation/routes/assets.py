"""Surplus asset, valuation and clearance endpoints (PRD sections 3.3, 3.8)."""
import db as store
from db import db, by_created, iso_date
from errors import ApiError
from middleware import (Fields, endpoint, future_date, list_params,
                        plain_filters, read_body)
from response import collection, created, ok
from services import calc, cascades, rollups
from services.enums import (CATEGORY, CERT_METHOD, CERT_TYPE, CLEARANCE_STATUS,
                            CONDITION_CODE, DEMIL_CODE, DEMIL_METHODS,
                            DISPOSITION_STATUS, SANITIZATION_METHODS)
from services.serialize import view, views


def register(app):

    @app.route("/assets", methods=["POST"])
    @endpoint(["AgencyOfficer", "ProgramAdmin"])
    def create_asset(ctx):
        body = read_body()
        f = Fields(body)
        f.string("turn_in_id", required=True, minlen=1)
        f.enum("category", CATEGORY, required=True)
        f.string("description", required=True, minlen=1, maxlen=200)
        f.integer("acquisition_cost_cents", required=True, minv=1)
        f.date("acquisition_date", required=True)
        f.string("component_of_asset_id")
        f.boolean("is_data_bearing", default=False)
        f.boolean("is_restricted", default=False)
        f.enum("demil_code", DEMIL_CODE)
        f.boolean("federal_source", default=False)
        f.date("federal_use_period_start_on")
        f.string("vin")
        f.integer("odometer_reading", minv=0)
        f.string("title_number")
        f.string("lien_holder_name")
        f.done()
        if f["category"] == "VEHICLE":
            if f["vin"] is None or f["odometer_reading"] is None or f["title_number"] is None:
                raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED",
                               "vin, odometer_reading and title_number are required "
                               "for a VEHICLE")
        if f["is_restricted"] and f["demil_code"] is None:
            raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED",
                           "demil_code is required when is_restricted is true")
        if f["federal_source"] and f["federal_use_period_start_on"] is None:
            raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED",
                           "federal_use_period_start_on is required when "
                           "federal_source is true")
        future_date(f["acquisition_date"], "acquisition_date")
        turn_in = rollups.fetch(db.turn_ins, f["turn_in_id"], "ERR_TURN_IN_NOT_FOUND")
        parent = None
        if f["component_of_asset_id"] is not None:
            parent = rollups.fetch(db.assets, f["component_of_asset_id"],
                                   "ERR_ASSET_NOT_FOUND")
        if parent is not None:
            if parent["turn_in_id"] != turn_in["id"]:
                raise ApiError("ERR_ASSET_COMPONENT_CYCLE",
                               "component_of_asset_id must reference an asset on the "
                               "same turn-in")
            seen = set()
            walk = parent
            while walk is not None:
                if walk["id"] in seen:
                    raise ApiError("ERR_ASSET_COMPONENT_CYCLE",
                                   "the component graph would contain a cycle")
                seen.add(walk["id"])
                walk = db.assets.get(walk["component_of_asset_id"]) \
                    if walk["component_of_asset_id"] else None
        if turn_in["status"] != "DRAFT":
            raise ApiError("ERR_TURN_IN_NOT_DRAFT",
                           "assets may only be added to a DRAFT turn-in")
        is_vehicle = f["category"] == "VEHICLE"
        end_on = None
        if f["federal_source"] and f["federal_use_period_start_on"] is not None:
            end_on = calc.use_period_end(f["federal_use_period_start_on"], f["category"])
        asset = store.base_row()
        asset.update({
            "turn_in_id": turn_in["id"],
            "component_of_asset_id": parent["id"] if parent is not None else None,
            "category": f["category"],
            "description": f["description"],
            "acquisition_cost_cents": f["acquisition_cost_cents"],
            "acquisition_date": iso_date(f["acquisition_date"]),
            "is_data_bearing": f["is_data_bearing"],
            "is_restricted": f["is_restricted"],
            "demil_code": f["demil_code"] if f["is_restricted"] else None,
            "federal_source": f["federal_source"],
            "federal_use_period_start_on": iso_date(f["federal_use_period_start_on"]),
            "federal_use_period_end_on": iso_date(end_on),
            "vin": f["vin"] if is_vehicle else None,
            "odometer_reading": f["odometer_reading"] if is_vehicle else None,
            "title_number": f["title_number"] if is_vehicle else None,
            "lien_holder_name": f["lien_holder_name"],
            "odometer_disclosure_reading": None,
            "lien_release_reference": None,
            "title_recipient_name": None,
            "condition_code": None,
            "fair_market_value_cents": None,
            "disposition_status": "INTAKE",
            "clearance_status": ("REQUIRED_PENDING"
                                if (f["is_data_bearing"] or f["is_restricted"])
                                else "NOT_REQUIRED"),
            "released_at": None,
        })
        db.assets[asset["id"]] = asset
        rollups.recompute_turn_in(turn_in, ctx)
        return created(view("SurplusAsset", asset))

    @app.route("/assets/<asset_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "SurplusAssessor",
               "ClearanceTechnician", "AgencyOfficer", "FinanceController"])
    def get_asset(ctx, asset_id):
        asset = rollups.fetch(db.assets, asset_id, "ERR_ASSET_NOT_FOUND")
        return ok(view("SurplusAsset", asset))

    @app.route("/assets", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "SurplusAssessor", "ClearanceTechnician"])
    def list_assets(ctx):
        filters, limit, offset = list_params({
            "category": CATEGORY,
            "disposition_status": DISPOSITION_STATUS,
            "clearance_status": CLEARANCE_STATUS,
        })
        plain = plain_filters(["turn_in_id", "component_of_asset_id"])
        rows = by_created(db.assets.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        for key, value in plain.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("SurplusAsset", rows), limit, offset)

    # -- valuation ---------------------------------------------------------

    @app.route("/assets/<asset_id>/condition-assessments", methods=["POST"])
    @endpoint(["SurplusAssessor"])
    def create_assessment(ctx, asset_id):
        body = read_body()
        f = Fields(body)
        f.enum("condition_code", CONDITION_CODE, required=True)
        f.boolean("functional", required=True)
        f.integer("repair_cost_estimate_cents", required=True, minv=0)
        f.date("assessed_on", required=True)
        f.integer("expected_asset_version", required=True)
        f.string("notes")
        f.done()
        future_date(f["assessed_on"], "assessed_on")
        asset = rollups.fetch(db.assets, asset_id, "ERR_ASSET_NOT_FOUND")
        if f["expected_asset_version"] != asset["version"]:
            raise ApiError("ERR_STALE_ASSET_VERSION",
                           "expected_asset_version does not match the asset's "
                           "current version")
        turn_in = db.turn_ins.get(asset["turn_in_id"])
        existing = rollups.assessments_of_asset(asset["id"])
        allowed = ("SUBMITTED",) if not existing else ("SUBMITTED", "ACCEPTED")
        if turn_in is None or turn_in["status"] not in allowed:
            raise ApiError("ERR_INVALID_STATE",
                           "the asset's turn-in is not in a state that admits "
                           "this assessment")
        if asset["disposition_status"] not in ("INTAKE", "ASSESSED"):
            raise ApiError("ERR_ASSET_NOT_ASSESSABLE",
                           "the asset's disposition state does not admit assessment")
        row = store.base_row(with_common=False)
        row.update({
            "asset_id": asset["id"],
            "assessor_user_id": ctx.user_id,
            "condition_code": f["condition_code"],
            "functional": f["functional"],
            "repair_cost_estimate_cents": f["repair_cost_estimate_cents"],
            "assessed_on": iso_date(f["assessed_on"]),
            "notes": f["notes"],
            "superseded": False,
        })
        db.assessments[row["id"]] = row
        if asset["disposition_status"] == "INTAKE":
            asset["disposition_status"] = "ASSESSED"
        rollups.revalue_asset(asset, ctx)
        ctx.touch(asset)
        rollups.recompute_turn_in(turn_in, ctx)
        return created(view("ConditionAssessment", row))

    @app.route("/assets/<asset_id>/condition-assessments", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "SurplusAssessor", "AgencyOfficer"])
    def list_assessments(ctx, asset_id):
        filters, limit, offset = list_params()
        asset = rollups.fetch(db.assets, asset_id, "ERR_ASSET_NOT_FOUND")
        rows = sorted(rollups.assessments_of_asset(asset["id"]),
                      key=calc.assessment_rank_key, reverse=True)
        return collection(views("ConditionAssessment", rows), limit, offset)

    # -- clearance ---------------------------------------------------------

    @app.route("/assets/<asset_id>/clearance-certificates", methods=["POST"])
    @endpoint(["ClearanceTechnician"])
    def create_certificate(ctx, asset_id):
        body = read_body()
        f = Fields(body)
        f.enum("cert_type", CERT_TYPE, required=True)
        f.enum("method", CERT_METHOD, required=True)
        f.boolean("serials_verified", required=True)
        f.date("certified_on", required=True)
        f.string("notes")
        f.done()
        future_date(f["certified_on"], "certified_on")
        asset = rollups.fetch(db.assets, asset_id, "ERR_ASSET_NOT_FOUND")
        for assessment in rollups.assessments_of_asset(asset["id"]):
            if assessment["assessor_user_id"] == ctx.user_id:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                               "the technician clearing this asset also assessed it")
        cert_type = f["cert_type"]
        method = f["method"]
        if cert_type == "DATA_SANITIZATION" and method not in SANITIZATION_METHODS:
            raise ApiError("ERR_CLEARANCE_METHOD_MISMATCH",
                           "method is outside the DATA_SANITIZATION family")
        if cert_type == "DEMILITARIZATION" and method not in DEMIL_METHODS:
            raise ApiError("ERR_CLEARANCE_METHOD_MISMATCH",
                           "method is outside the DEMILITARIZATION family")
        if method == "DESTROY" and asset["demil_code"] != "Q":
            raise ApiError("ERR_CLEARANCE_METHOD_MISMATCH",
                           "DESTROY is admitted only for a demil_code Q asset")
        if asset["clearance_status"] == "NOT_REQUIRED":
            raise ApiError("ERR_CLEARANCE_NOT_APPLICABLE",
                           "the asset carries no clearance obligation")
        destroying = cert_type == "DEMILITARIZATION" and method == "DESTROY"
        if destroying and asset["disposition_status"] not in (
                "ASSESSED", "SCREENING", "AUCTION_ELIGIBLE", "LISTED"):
            raise ApiError("ERR_INVALID_STATE",
                           "the asset's disposition state does not admit destruction")
        if (not f["serials_verified"] and asset["clearance_status"] == "CLEARED"
                and asset["disposition_status"] == "RELEASED"):
            raise ApiError("ERR_INVALID_STATE",
                           "a released asset may not be moved back to BLOCKED")
        row = store.base_row(with_common=False)
        row.update({
            "asset_id": asset["id"],
            "cert_type": cert_type,
            "method": method,
            "technician_user_id": ctx.user_id,
            "serials_verified": f["serials_verified"],
            "certified_on": iso_date(f["certified_on"]),
            "notes": f["notes"],
        })
        db.certificates[row["id"]] = row
        if destroying:
            cascades.destroy_asset(asset, ctx)
        elif not f["serials_verified"]:
            asset["clearance_status"] = "BLOCKED"
            ctx.touch(asset)
        else:
            rollups.evaluate_clearance(asset, ctx)
            ctx.touch(asset)
        return created(view("ClearanceCertificate", row))

    @app.route("/assets/<asset_id>/clearance-certificates", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "ClearanceTechnician", "FinanceController"])
    def list_certificates(ctx, asset_id):
        filters, limit, offset = list_params({"cert_type": CERT_TYPE})
        asset = rollups.fetch(db.assets, asset_id, "ERR_ASSET_NOT_FOUND")
        rows = rollups.certificates_of_asset(asset["id"])
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("ClearanceCertificate", rows), limit, offset)
