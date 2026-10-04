"""Routes: shipments and customs declarations."""
from decimal import Decimal

from flask import request

from common import (
    ApiError, LOTS, SITES, LICENSES, REQUESTS, DECISIONS, LINES, SHIPMENTS,
    CUSTOMS, LOCK,
    require_roles, body, ok, ok_list,
    req_str, opt_str, req_bool,
    stamp_new, bump, sorted_items, get_or_404, parse_dt,
    shipment_json, customs_json, decision_lines, money2, clock,
    cancel_shipment,
)

SHIP_ROLES = ("LogisticsCoordinator", "ComplianceOfficer", "PlatformAdmin", "SiteCoordinator")
CUSTOMS_ROLES = ("LogisticsCoordinator", "ComplianceOfficer", "PlatformAdmin")


def compute_temp_bands(sh):
    """(lots, min_c, max_c, requires_cold_chain) over PICKED lines' lots."""
    lots = {}
    for line in LINES.values():
        if line["decision_id"] == sh["allocation_decision_id"] and line["status"] == "PICKED":
            lot = LOTS.get(line["lot_id"])
            if lot is not None:
                lots[lot["id"]] = lot
    if not lots:
        raise ApiError("ERR_INVALID_STATE", 409, "Shipment has no PICKED lines")
    min_c = max(l["storage_temp_min_c"] for l in lots.values())
    max_c = min(l["storage_temp_max_c"] for l in lots.values())
    cold = any(l["product_class"] == "COLD_CHAIN" for l in lots.values())
    return list(lots.values()), min_c, max_c, cold


def register(app):

    # --------------------------------------------------------------- shipment
    @app.post("/medicine-relief/shipments")
    def create_shipment():
        require_roles("LogisticsCoordinator")
        b = body()
        decision_id = req_str(b, "allocation_decision_id")
        carrier = req_str(b, "carrier_name")
        cold_shipper = req_bool(b, "packed_with_cold_shipper")
        with LOCK:
            dec = get_or_404(DECISIONS, decision_id, "AllocationDecision")
            if dec["status"] != "FINALIZED":
                raise ApiError("ERR_INVALID_STATE", 409, "Decision is not FINALIZED")
            req_obj = REQUESTS.get(dec["request_id"])
            site = SITES.get(req_obj["site_id"]) if req_obj else None
            if site is None or site["qualification_status"] != "QUALIFIED":
                raise ApiError("ERR_SITE_NOT_QUALIFIED", 409, "Site is not QUALIFIED")
            lines = decision_lines(dec["id"])
            for line in lines:
                if line["status"] != "RESERVED":
                    raise ApiError("ERR_INVALID_STATE", 409,
                                   "Every decision line must be RESERVED to create a shipment")
            sh = {
                "site_id": site["id"],
                "allocation_decision_id": decision_id,
                "carrier_name": carrier,
                "is_international": site["country_code"] != "US",
                "requires_cold_chain": None,
                "temperature_band_min_c": None,
                "temperature_band_max_c": None,
                "packed_with_cold_shipper": cold_shipper,
                "customs_declaration_id": None,
                "status": "PACKING",
                "dispatched_at": None,
                "delivered_at": None,
            }
            stamp_new(sh)
            SHIPMENTS[sh["id"]] = sh
            for line in lines:
                lot = LOTS[line["lot_id"]]
                lot["quantity_committed"] -= line["quantity"]
                bump(lot)
                line["status"] = "PICKED"
                bump(line)
            return ok(shipment_json(sh), 201)

    @app.get("/medicine-relief/shipments/<shipment_id>")
    def get_shipment(shipment_id):
        require_roles(*SHIP_ROLES)
        with LOCK:
            return ok(shipment_json(get_or_404(SHIPMENTS, shipment_id, "Shipment")))

    @app.get("/medicine-relief/shipments")
    def list_shipments():
        require_roles(*SHIP_ROLES)
        site_id = request.args.get("site_id")
        status = request.args.get("status")
        dec_id = request.args.get("allocation_decision_id")
        cd_id = request.args.get("customs_declaration_id")
        with LOCK:
            items = [s for s in sorted_items(SHIPMENTS)
                     if (site_id is None or s["site_id"] == site_id)
                     and (status is None or s["status"] == status)
                     and (dec_id is None or s["allocation_decision_id"] == dec_id)
                     and (cd_id is None or s["customs_declaration_id"] == cd_id)]
            return ok_list([shipment_json(s) for s in items])

    @app.post("/medicine-relief/shipments/<shipment_id>/pack-complete")
    def pack_complete(shipment_id):
        require_roles("LogisticsCoordinator")
        with LOCK:
            sh = get_or_404(SHIPMENTS, shipment_id, "Shipment")
            if sh["status"] != "PACKING":
                raise ApiError("ERR_INVALID_STATE", 409, "Shipment is not PACKING")
            lots, min_c, max_c, cold = compute_temp_bands(sh)
            if min_c > max_c:
                raise ApiError("ERR_INCOMPATIBLE_TEMPERATURE_BANDS", 422,
                               "Included lots have incompatible storage temperature bands")
            if cold and not sh["packed_with_cold_shipper"]:
                raise ApiError("ERR_COLD_CHAIN_PACK_REQUIRED", 422,
                               "Cold-chain shipment requires a validated cold shipper")
            sh["temperature_band_min_c"] = min_c
            sh["temperature_band_max_c"] = max_c
            sh["requires_cold_chain"] = cold
            sh["status"] = "AWAITING_CUSTOMS_DOCS" if sh["is_international"] else "READY_TO_DISPATCH"
            bump(sh)
            return ok(shipment_json(sh))

    @app.post("/medicine-relief/shipments/<shipment_id>/dispatch")
    def dispatch_shipment(shipment_id):
        require_roles("LogisticsCoordinator")
        with LOCK:
            sh = get_or_404(SHIPMENTS, shipment_id, "Shipment")
            if sh["status"] != "READY_TO_DISPATCH":
                raise ApiError("ERR_INVALID_STATE", 409, "Shipment is not READY_TO_DISPATCH")
            if sh["is_international"]:
                cd = CUSTOMS.get(sh["customs_declaration_id"]) if sh["customs_declaration_id"] else None
                if cd is None or cd["status"] != "CLEARED":
                    raise ApiError("ERR_CUSTOMS_NOT_CLEARED", 409,
                                   "International shipment dispatch requires a CLEARED customs declaration")
            site = SITES.get(sh["site_id"])
            if site is None or site["qualification_status"] != "QUALIFIED":
                raise ApiError("ERR_SITE_NOT_QUALIFIED", 409, "Site is not QUALIFIED")
            sh["status"] = "DISPATCHED"
            sh["dispatched_at"] = clock()
            bump(sh)
            for line in LINES.values():
                if line["decision_id"] == sh["allocation_decision_id"] and line["status"] == "PICKED":
                    lot = LOTS[line["lot_id"]]
                    lot["quantity_shipped"] += line["quantity"]
                    bump(lot)
                    line["status"] = "SHIPPED"
                    bump(line)
            return ok(shipment_json(sh))

    @app.post("/medicine-relief/shipments/<shipment_id>/confirm-delivery")
    def confirm_delivery(shipment_id):
        uid, _ = require_roles("SiteCoordinator")
        with LOCK:
            sh = get_or_404(SHIPMENTS, shipment_id, "Shipment")
            if uid != sh["site_id"]:
                raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                               "Only the destination site's coordinator may confirm delivery")
            if sh["status"] != "DISPATCHED":
                raise ApiError("ERR_INVALID_STATE", 409, "Shipment is not DISPATCHED")
            sh["status"] = "DELIVERED"
            sh["delivered_at"] = clock()
            bump(sh)
            for line in LINES.values():
                if line["decision_id"] == sh["allocation_decision_id"] and line["status"] == "SHIPPED":
                    line["status"] = "DELIVERED"
                    bump(line)
            return ok(shipment_json(sh))

    @app.post("/medicine-relief/shipments/<shipment_id>/mark-delivery-failed")
    def mark_delivery_failed(shipment_id):
        require_roles("LogisticsCoordinator")
        b = body()
        opt_str(b, "reason")
        with LOCK:
            sh = get_or_404(SHIPMENTS, shipment_id, "Shipment")
            if sh["status"] != "DISPATCHED":
                raise ApiError("ERR_INVALID_STATE", 409, "Shipment is not DISPATCHED")
            sh["status"] = "DELIVERY_FAILED"
            bump(sh)
            for line in LINES.values():
                if line["decision_id"] == sh["allocation_decision_id"] and line["status"] == "SHIPPED":
                    lot = LOTS[line["lot_id"]]
                    lot["quantity_shipped"] -= line["quantity"]
                    lot["quantity_expired"] += line["quantity"]
                    bump(lot)
                    line["status"] = "FORFEITED"
                    bump(line)
            return ok(shipment_json(sh))

    @app.post("/medicine-relief/shipments/<shipment_id>/cancel")
    def cancel_shipment_endpoint(shipment_id):
        require_roles("LogisticsCoordinator")
        with LOCK:
            sh = get_or_404(SHIPMENTS, shipment_id, "Shipment")
            if sh["status"] not in ("PACKING", "AWAITING_CUSTOMS_DOCS", "READY_TO_DISPATCH"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Shipment cannot be cancelled from its current status")
            cancel_shipment(sh)
            return ok(shipment_json(sh))

    # ---------------------------------------------------------------- customs
    @app.post("/medicine-relief/customs-declarations")
    def create_customs():
        require_roles("LogisticsCoordinator")
        b = body()
        shipment_id = req_str(b, "shipment_id")
        hs_code = req_str(b, "hs_code")
        import_license_id = req_str(b, "import_license_id")
        with LOCK:
            sh = get_or_404(SHIPMENTS, shipment_id, "Shipment")
            lic = get_or_404(LICENSES, import_license_id, "License")
            if not sh["is_international"]:
                raise ApiError("ERR_INVALID_STATE", 409, "Shipment is not international")
            now = clock()
            if lic["verification_status"] != "VERIFIED" or parse_dt(lic["expires_on_raw"]) <= now:
                raise ApiError("ERR_IMPORT_LICENSE_MISSING", 422,
                               "Import license must be VERIFIED and unexpired")
            if lic["site_id"] != sh["site_id"]:
                raise ApiError("ERR_IMPORT_LICENSE_MISSING", 422,
                               "Import license does not belong to the destination site")
            site = SITES.get(sh["site_id"])
            cd = {
                "shipment_id": shipment_id,
                "hs_code": hs_code,
                "declared_value_usd": None,
                "import_license_id": import_license_id,
                "destination_country_code": site["country_code"] if site else None,
                "status": "DRAFT",
            }
            stamp_new(cd)
            CUSTOMS[cd["id"]] = cd
            sh["customs_declaration_id"] = cd["id"]
            bump(sh)
            return ok(customs_json(cd), 201)

    @app.get("/medicine-relief/customs-declarations/<declaration_id>")
    def get_customs(declaration_id):
        require_roles(*CUSTOMS_ROLES)
        with LOCK:
            return ok(customs_json(get_or_404(CUSTOMS, declaration_id, "CustomsDeclaration")))

    @app.get("/medicine-relief/customs-declarations")
    def list_customs():
        require_roles(*CUSTOMS_ROLES)
        sid = request.args.get("shipment_id")
        status = request.args.get("status")
        lid = request.args.get("import_license_id")
        with LOCK:
            items = [c for c in sorted_items(CUSTOMS)
                     if (sid is None or c["shipment_id"] == sid)
                     and (status is None or c["status"] == status)
                     and (lid is None or c["import_license_id"] == lid)]
            return ok_list([customs_json(c) for c in items])

    @app.post("/medicine-relief/customs-declarations/<declaration_id>/submit")
    def submit_customs(declaration_id):
        require_roles("LogisticsCoordinator")
        with LOCK:
            cd = get_or_404(CUSTOMS, declaration_id, "CustomsDeclaration")
            if cd["status"] != "DRAFT":
                raise ApiError("ERR_INVALID_STATE", 409, "Declaration is not DRAFT")
            sh = SHIPMENTS.get(cd["shipment_id"])
            if sh is None or not sh["is_international"]:
                raise ApiError("ERR_INVALID_STATE", 409, "Shipment is not international")
            if not cd["hs_code"]:
                raise ApiError("ERR_INVALID_REQUEST", 400, "hs_code must be non-empty")
            lic = LICENSES.get(cd["import_license_id"])
            now = clock()
            if lic is None or lic["verification_status"] != "VERIFIED" \
                    or parse_dt(lic["expires_on_raw"]) <= now:
                raise ApiError("ERR_IMPORT_LICENSE_MISSING", 422,
                               "Import license must be VERIFIED and unexpired")
            total = Decimal("0")
            for line in LINES.values():
                if line["decision_id"] == sh["allocation_decision_id"] and line["status"] == "PICKED":
                    lot = LOTS[line["lot_id"]]
                    total += money2(Decimal(line["quantity"]) * Decimal(str(lot["unit_acquisition_value_usd"])))
            if total <= 0:
                raise ApiError("ERR_CUSTOMS_VALUE_INVALID", 422,
                               "Declared value must be greater than zero")
            cd["declared_value_usd"] = float(total)
            cd["status"] = "SUBMITTED"
            bump(cd)
            return ok(customs_json(cd))

    @app.post("/medicine-relief/customs-declarations/<declaration_id>/clear")
    def clear_customs(declaration_id):
        require_roles("ComplianceOfficer")
        with LOCK:
            cd = get_or_404(CUSTOMS, declaration_id, "CustomsDeclaration")
            if cd["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", 409, "Declaration is not SUBMITTED")
            cd["status"] = "CLEARED"
            bump(cd)
            sh = SHIPMENTS.get(cd["shipment_id"])
            if sh is not None and sh["status"] == "AWAITING_CUSTOMS_DOCS":
                sh["status"] = "READY_TO_DISPATCH"
                bump(sh)
            return ok(customs_json(cd))

    @app.post("/medicine-relief/customs-declarations/<declaration_id>/reject")
    def reject_customs(declaration_id):
        require_roles("ComplianceOfficer")
        b = body()
        opt_str(b, "reason")
        with LOCK:
            cd = get_or_404(CUSTOMS, declaration_id, "CustomsDeclaration")
            if cd["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", 409, "Declaration is not SUBMITTED")
            cd["status"] = "REJECTED"
            bump(cd)
            return ok(customs_json(cd))
