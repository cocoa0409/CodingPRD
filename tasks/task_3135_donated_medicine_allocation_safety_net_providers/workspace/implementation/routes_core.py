"""Routes: clock, donors, lots, sites, licenses."""
from flask import request

from common import (
    ApiError, DONORS, LOTS, SITES, LICENSES, LOCK,
    auth_context, require_roles, body, ok, ok_list,
    req_str, opt_str, req_int, req_bool, req_num, req_list, req_enum,
    stamp_new, bump, sorted_items, get_or_404, parse_dt,
    donor_json, lot_json, site_json, license_json,
    lot_available, site_active_license_count, suspend_site_cascade,
    run_sweep, set_clock, clock,
)

PRODUCT_CLASSES = {"STANDARD", "COLD_CHAIN", "CONTROLLED", "RESTRICTED_USE"}
DOSAGE_FORMS = {"TABLET", "CAPSULE", "VIAL", "AMPOULE", "SYRUP", "CREAM", "DEVICE"}
UOMS = {"UNIT", "VIAL", "PACK", "BOX"}
SITE_TYPES = {"FREE_CLINIC", "FQHC", "RURAL_HEALTH_CENTER", "DISASTER_RESPONDER", "HOSPITAL_CHARITY"}
LICENSE_TYPES = {"PHARMACY", "MEDICAL_DIRECTOR", "DEA", "WHOLESALER", "IMPORT"}

DONOR_GET_ROLES = ("PlatformAdmin", "ComplianceOfficer", "AllocationOfficer", "DonorReportingOfficer")
LOT_GET_ROLES = ("PlatformAdmin", "QAPharmacist", "AllocationOfficer", "LogisticsCoordinator",
                 "ComplianceOfficer", "DonorReportingOfficer")
SITE_GET_ONE_ROLES = ("PlatformAdmin", "ComplianceOfficer", "AllocationOfficer",
                      "LogisticsCoordinator", "SiteCoordinator", "EmergencyManager")
SITE_LIST_ROLES = ("PlatformAdmin", "ComplianceOfficer", "AllocationOfficer",
                   "LogisticsCoordinator", "EmergencyManager")
LICENSE_ROLES = ("ComplianceOfficer", "SiteCoordinator", "PlatformAdmin")


def register(app):

    # ------------------------------------------------------------------ clock
    @app.post("/medicine-relief/_clock/set_current_utc")
    def set_current_utc():
        require_roles("PlatformAdmin")
        b = body()
        dt = parse_dt(req_str(b, "current_utc"))
        with LOCK:
            set_clock(dt)
            run_sweep()
            current = clock()
        return ok({"current_utc": current.strftime("%Y-%m-%dT%H:%M:%SZ") if current.microsecond == 0
                   else current.isoformat().replace("+00:00", "Z")})

    # ----------------------------------------------------------------- donors
    @app.post("/medicine-relief/donors")
    def create_donor():
        require_roles("PlatformAdmin")
        b = body()
        donor = {
            "legal_name": req_str(b, "legal_name"),
            "country_code": req_str(b, "country_code"),
            "dea_registration_no": opt_str(b, "dea_registration_no"),
            "tax_id": req_str(b, "tax_id"),
            "status": "ACTIVE",
        }
        with LOCK:
            stamp_new(donor)
            DONORS[donor["id"]] = donor
        return ok(donor_json(donor), 201)

    @app.get("/medicine-relief/donors/<donor_id>")
    def get_donor(donor_id):
        require_roles(*DONOR_GET_ROLES)
        with LOCK:
            return ok(donor_json(get_or_404(DONORS, donor_id, "ManufacturerDonor")))

    @app.get("/medicine-relief/donors")
    def list_donors():
        require_roles(*DONOR_GET_ROLES)
        status = request.args.get("status")
        cc = request.args.get("country_code")
        with LOCK:
            items = [d for d in sorted_items(DONORS)
                     if (status is None or d["status"] == status)
                     and (cc is None or d["country_code"] == cc)]
            return ok_list([donor_json(d) for d in items])

    @app.post("/medicine-relief/donors/<donor_id>/suspend")
    def suspend_donor(donor_id):
        require_roles("PlatformAdmin")
        with LOCK:
            donor = get_or_404(DONORS, donor_id, "ManufacturerDonor")
            if donor["status"] != "ACTIVE":
                raise ApiError("ERR_INVALID_STATE", 409, "Donor is not ACTIVE")
            donor["status"] = "SUSPENDED"
            bump(donor)
            return ok(donor_json(donor))

    @app.post("/medicine-relief/donors/<donor_id>/deactivate")
    def deactivate_donor(donor_id):
        require_roles("PlatformAdmin")
        with LOCK:
            donor = get_or_404(DONORS, donor_id, "ManufacturerDonor")
            if donor["status"] == "DEACTIVATED":
                raise ApiError("ERR_INVALID_STATE", 409, "Donor already DEACTIVATED")
            donor["status"] = "DEACTIVATED"
            bump(donor)
            return ok(donor_json(donor))

    # ------------------------------------------------------------------- lots
    @app.post("/medicine-relief/lots")
    def create_lot():
        auth_context()
        _, role = auth_context()
        if role not in ("PlatformAdmin", "QAPharmacist"):
            raise ApiError("ERR_FORBIDDEN_ROLE", 403, f"Role {role} is not permitted for this endpoint")
        b = body()
        donor_id = req_str(b, "donor_id")
        ndc_code = req_str(b, "ndc_code")
        product_name = req_str(b, "product_name")
        product_class = req_enum(b, "product_class", PRODUCT_CLASSES)
        dosage_form = req_enum(b, "dosage_form", DOSAGE_FORMS)
        uom = req_enum(b, "unit_of_measure", UOMS)
        qty = req_int(b, "quantity_received")
        if qty <= 0:
            raise ApiError("ERR_QUANTITY_INVALID", 422, "quantity_received must be a positive integer")
        expiration_date = req_str(b, "expiration_date")
        exp_dt = parse_dt(expiration_date)
        tmin = req_num(b, "storage_temp_min_c")
        tmax = req_num(b, "storage_temp_max_c")
        ruc = b.get("restricted_use_conditions", [])
        if ruc is None:
            ruc = []
        if not isinstance(ruc, list) or any(not isinstance(x, str) for x in ruc):
            raise ApiError("ERR_INVALID_REQUEST", 400, "restricted_use_conditions must be an array of strings")
        uav = req_num(b, "unit_acquisition_value_usd")
        uwv = req_num(b, "unit_wholesale_value_usd")
        with LOCK:
            donor = DONORS.get(donor_id)
            if donor is None:
                raise ApiError("ERR_NOT_FOUND", 404, f"ManufacturerDonor not found: {donor_id}")
            if product_class == "CONTROLLED" and not donor["dea_registration_no"]:
                raise ApiError("ERR_CONTROLLED_DONOR_UNREGISTERED", 422,
                               "Controlled lot intake requires a donor with DEA registration")
            if donor["status"] != "ACTIVE":
                raise ApiError("ERR_DONOR_NOT_ACTIVE", 409, "Donor is not ACTIVE")
            lot = {
                "donor_id": donor_id,
                "ndc_code": ndc_code,
                "product_name": product_name,
                "product_class": product_class,
                "dosage_form": dosage_form,
                "unit_of_measure": uom,
                "quantity_received": qty,
                "quantity_quarantined": qty,
                "quantity_committed": 0,
                "quantity_shipped": 0,
                "quantity_expired": 0,
                "expiration_date": expiration_date,
                "expiration_date_raw": expiration_date,
                "storage_temp_min_c": tmin,
                "storage_temp_max_c": tmax,
                "restricted_use_conditions": ruc,
                "unit_acquisition_value_usd": uav,
                "unit_wholesale_value_usd": uwv,
                "lot_posture": "QUARANTINED",
                "intake_recorded_at": clock(),
            }
            stamp_new(lot)
            LOTS[lot["id"]] = lot
            return ok(lot_json(lot), 201)

    @app.get("/medicine-relief/lots/<lot_id>")
    def get_lot(lot_id):
        require_roles(*LOT_GET_ROLES)
        with LOCK:
            return ok(lot_json(get_or_404(LOTS, lot_id, "ProductLot")))

    @app.get("/medicine-relief/lots")
    def list_lots():
        require_roles(*LOT_GET_ROLES)
        donor_id = request.args.get("donor_id")
        posture = request.args.get("lot_posture")
        pclass = request.args.get("product_class")
        ndc = request.args.get("ndc_code")
        with LOCK:
            items = [l for l in sorted_items(LOTS)
                     if (donor_id is None or l["donor_id"] == donor_id)
                     and (posture is None or l["lot_posture"] == posture)
                     and (pclass is None or l["product_class"] == pclass)
                     and (ndc is None or l["ndc_code"] == ndc)]
            return ok_list([lot_json(l) for l in items])

    @app.post("/medicine-relief/lots/<lot_id>/release")
    def release_lot(lot_id):
        require_roles("QAPharmacist")
        with LOCK:
            lot = get_or_404(LOTS, lot_id, "ProductLot")
            if lot["lot_posture"] != "QUARANTINED":
                raise ApiError("ERR_INVALID_STATE", 409, "Lot is not QUARANTINED")
            donor = DONORS.get(lot["donor_id"])
            if lot["product_class"] == "CONTROLLED" and (donor is None or not donor["dea_registration_no"]):
                raise ApiError("ERR_CONTROLLED_DONOR_UNREGISTERED", 422,
                               "Controlled lot release requires a donor with DEA registration")
            if donor is None or donor["status"] != "ACTIVE":
                raise ApiError("ERR_DONOR_NOT_ACTIVE", 409, "Donor is not ACTIVE")
            lot["lot_posture"] = "RELEASABLE"
            lot["quantity_quarantined"] -= lot["quantity_received"]
            bump(lot)
            return ok(lot_json(lot))

    @app.post("/medicine-relief/lots/<lot_id>/recall")
    def recall_lot(lot_id):
        from common import LINES, SHIPMENTS, cancel_shipment
        require_roles("QAPharmacist")
        with LOCK:
            lot = get_or_404(LOTS, lot_id, "ProductLot")
            if lot["lot_posture"] not in ("QUARANTINED", "RELEASABLE"):
                raise ApiError("ERR_INVALID_STATE", 409, "Lot cannot be recalled from its current posture")
            # release RESERVED lines against this lot
            for line in [l for l in LINES.values()
                         if l["lot_id"] == lot["id"] and l["status"] == "RESERVED"]:
                line["status"] = "RELEASED"
                bump(line)
                lot["quantity_committed"] -= line["quantity"]
            # cancel in-packing / ready shipments containing lines on this lot
            affected_shipments = set()
            from common import DECISIONS
            for line in LINES.values():
                if line["lot_id"] != lot["id"]:
                    continue
                dec = DECISIONS.get(line["decision_id"])
                if dec is None:
                    continue
                for sh in SHIPMENTS.values():
                    if sh["allocation_decision_id"] == dec["id"] \
                            and sh["status"] in ("PACKING", "READY_TO_DISPATCH"):
                        affected_shipments.add(sh["id"])
            for sh_id in affected_shipments:
                cancel_shipment(SHIPMENTS[sh_id], recalled_lot_ids={lot["id"]})
            if lot["lot_posture"] == "QUARANTINED":
                lot["quantity_expired"] += lot["quantity_quarantined"]
                lot["quantity_quarantined"] = 0
            # PRD §3.2: "The lot's `quantity_available` is recomputed and falls
            # to zero for any non-shipped units." With the derived ledger
            # (available = received - quarantined - committed - shipped -
            # expired), the remaining non-shipped units fold into the expired
            # bucket so the ledger keeps reconciling.
            remaining = lot_available(lot)
            if remaining > 0:
                lot["quantity_expired"] += remaining
            lot["lot_posture"] = "RECALLED"
            bump(lot)
            return ok(lot_json(lot))

    # ------------------------------------------------------------------ sites
    @app.post("/medicine-relief/sites")
    def create_site():
        _, role = auth_context()
        if role not in ("PlatformAdmin", "ComplianceOfficer"):
            raise ApiError("ERR_FORBIDDEN_ROLE", 403, f"Role {role} is not permitted for this endpoint")
        b = body()
        underserved = req_num(b, "underserved_index")
        if underserved < 0.0 or underserved > 1.0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "underserved_index must be between 0.0 and 1.0")
        site = {
            "organization_name": req_str(b, "organization_name"),
            "site_type": req_enum(b, "site_type", SITE_TYPES),
            "country_code": req_str(b, "country_code"),
            "cold_storage_capacity_l": req_int(b, "cold_storage_capacity_l"),
            "has_dea_registration": req_bool(b, "has_dea_registration"),
            "monthly_patient_volume": req_int(b, "monthly_patient_volume"),
            "underserved_index": underserved,
            "qualification_status": "PENDING_REVIEW",
            "qualified_at": None,
        }
        with LOCK:
            stamp_new(site)
            SITES[site["id"]] = site
            return ok(site_json(site), 201)

    @app.get("/medicine-relief/sites/<site_id>")
    def get_site(site_id):
        require_roles(*SITE_GET_ONE_ROLES)
        with LOCK:
            return ok(site_json(get_or_404(SITES, site_id, "RecipientSite")))

    @app.get("/medicine-relief/sites")
    def list_sites():
        require_roles(*SITE_LIST_ROLES)
        qs = request.args.get("qualification_status")
        cc = request.args.get("country_code")
        st = request.args.get("site_type")
        with LOCK:
            items = [s for s in sorted_items(SITES)
                     if (qs is None or s["qualification_status"] == qs)
                     and (cc is None or s["country_code"] == cc)
                     and (st is None or s["site_type"] == st)]
            return ok_list([site_json(s) for s in items])

    @app.post("/medicine-relief/sites/<site_id>/qualify")
    def qualify_site(site_id):
        require_roles("ComplianceOfficer")
        with LOCK:
            site = get_or_404(SITES, site_id, "RecipientSite")
            if site["qualification_status"] != "PENDING_REVIEW":
                raise ApiError("ERR_INVALID_STATE", 409, "Site is not PENDING_REVIEW")
            now = clock()
            if site["country_code"] != "US":
                has_import = any(
                    lic for lic in LICENSES.values()
                    if lic["site_id"] == site["id"]
                    and lic["license_type"] == "IMPORT"
                    and lic["verification_status"] == "VERIFIED"
                    and parse_dt(lic["expires_on_raw"]) > now
                )
                if not has_import:
                    raise ApiError("ERR_IMPORT_LICENSE_MISSING", 422,
                                   "International site lacks a VERIFIED, unexpired IMPORT license")
            if site_active_license_count(site["id"]) < 1:
                raise ApiError("ERR_NO_VERIFIED_LICENSE", 422,
                               "Site has no VERIFIED, unexpired license")
            site["qualification_status"] = "QUALIFIED"
            site["qualified_at"] = now
            bump(site)
            return ok(site_json(site))

    @app.post("/medicine-relief/sites/<site_id>/suspend")
    def suspend_site(site_id):
        require_roles("ComplianceOfficer")
        b = body()
        with LOCK:
            site = get_or_404(SITES, site_id, "RecipientSite")
            if site["qualification_status"] != "QUALIFIED":
                raise ApiError("ERR_INVALID_STATE", 409, "Site is not QUALIFIED")
            if "expected_site_version" in b and b["expected_site_version"] is not None:
                if b["expected_site_version"] != site["version"]:
                    raise ApiError("ERR_STALE_VERSION", 412,
                                   "expected_site_version does not match the site's current version")
            site["qualification_status"] = "SUSPENDED"
            bump(site)
            suspend_site_cascade(site)
            return ok(site_json(site))

    @app.post("/medicine-relief/sites/<site_id>/reinstate")
    def reinstate_site(site_id):
        require_roles("ComplianceOfficer")
        with LOCK:
            site = get_or_404(SITES, site_id, "RecipientSite")
            if site["qualification_status"] != "SUSPENDED":
                raise ApiError("ERR_INVALID_STATE", 409, "Site is not SUSPENDED")
            if site_active_license_count(site["id"]) < 1:
                raise ApiError("ERR_NO_VERIFIED_LICENSE", 422,
                               "Site has no VERIFIED, unexpired license")
            site["qualification_status"] = "QUALIFIED"
            bump(site)
            return ok(site_json(site))

    @app.post("/medicine-relief/sites/<site_id>/revoke")
    def revoke_site(site_id):
        from common import SHIPMENTS, cancel_shipment
        require_roles("ComplianceOfficer")
        with LOCK:
            site = get_or_404(SITES, site_id, "RecipientSite")
            if site["qualification_status"] not in ("QUALIFIED", "SUSPENDED"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Site must be QUALIFIED or SUSPENDED to be revoked")
            site["qualification_status"] = "REVOKED"
            bump(site)
            suspend_site_cascade(site)
            for sh in list(SHIPMENTS.values()):
                if sh["site_id"] == site["id"] and sh["status"] in (
                        "PACKING", "AWAITING_CUSTOMS_DOCS", "READY_TO_DISPATCH"):
                    cancel_shipment(sh)
            return ok(site_json(site))

    # -------------------------------------------------------------- licenses
    @app.post("/medicine-relief/licenses")
    def create_license():
        _, role = auth_context()
        if role not in ("SiteCoordinator", "ComplianceOfficer"):
            raise ApiError("ERR_FORBIDDEN_ROLE", 403, f"Role {role} is not permitted for this endpoint")
        b = body()
        site_id = req_str(b, "site_id")
        license_type = req_enum(b, "license_type", LICENSE_TYPES)
        issuing_authority = req_str(b, "issuing_authority")
        license_number = req_str(b, "license_number")
        expires_on = req_str(b, "expires_on")
        parse_dt(expires_on)
        with LOCK:
            get_or_404(SITES, site_id, "RecipientSite")
            lic = {
                "site_id": site_id,
                "license_type": license_type,
                "issuing_authority": issuing_authority,
                "license_number": license_number,
                "expires_on": expires_on,
                "expires_on_raw": expires_on,
                "verification_status": "PENDING",
            }
            stamp_new(lic)
            LICENSES[lic["id"]] = lic
            return ok(license_json(lic), 201)

    @app.get("/medicine-relief/licenses/<license_id>")
    def get_license(license_id):
        require_roles(*LICENSE_ROLES)
        with LOCK:
            return ok(license_json(get_or_404(LICENSES, license_id, "License")))

    @app.get("/medicine-relief/licenses")
    def list_licenses():
        require_roles(*LICENSE_ROLES)
        site_id = request.args.get("site_id")
        vs = request.args.get("verification_status")
        lt = request.args.get("license_type")
        with LOCK:
            items = [l for l in sorted_items(LICENSES)
                     if (site_id is None or l["site_id"] == site_id)
                     and (vs is None or l["verification_status"] == vs)
                     and (lt is None or l["license_type"] == lt)]
            return ok_list([license_json(l) for l in items])

    @app.post("/medicine-relief/licenses/<license_id>/verify")
    def verify_license(license_id):
        require_roles("ComplianceOfficer")
        with LOCK:
            lic = get_or_404(LICENSES, license_id, "License")
            if lic["verification_status"] != "PENDING":
                raise ApiError("ERR_INVALID_STATE", 409, "License is not PENDING")
            if parse_dt(lic["expires_on_raw"]) <= clock():
                raise ApiError("ERR_LICENSE_EXPIRED", 422,
                               "License expiry must be in the future at verification time")
            lic["verification_status"] = "VERIFIED"
            bump(lic)
            return ok(license_json(lic))

    @app.post("/medicine-relief/licenses/<license_id>/reject")
    def reject_license(license_id):
        require_roles("ComplianceOfficer")
        with LOCK:
            lic = get_or_404(LICENSES, license_id, "License")
            if lic["verification_status"] != "PENDING":
                raise ApiError("ERR_INVALID_STATE", 409, "License is not PENDING")
            lic["verification_status"] = "REJECTED"
            bump(lic)
            return ok(license_json(lic))
