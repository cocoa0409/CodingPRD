"""Markets, payer contracts, formulary entries, patients."""
import db
import helpers as H
import services as S
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_MARKET_CODE_TAKEN, ERR_CONTRACT_WINDOW_INVALID,
    ERR_CONTRACT_INVALID_STATE, ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success_object, success_list

MARKET_READ_ROLES = {"PlatformAdmin", "Dispatcher", "TriageNurse", "BillingSpecialist", "PayerAdjudicator"}
CONTRACT_READ_ROLES = {"PlatformAdmin", "BillingSpecialist", "PayerAdjudicator"}
PATIENT_LIST_ROLES = {"PlatformAdmin", "TriageNurse", "Dispatcher", "BillingSpecialist"}
PATIENT_GET_ROLES = {"PlatformAdmin", "TriageNurse", "Dispatcher", "BillingSpecialist", "AdvancedPracticeProvider"}


def register(app):

    # ---------------- Markets ----------------
    @app.post("/dh/markets")
    def create_market():
        require_roles({"PlatformAdmin"})
        body = H.get_json_body()
        market_code = H.require(body, "market_code", "string")
        display_name = H.require(body, "display_name", "string")
        polygon_geojson = H.require(body, "polygon_geojson", "string")
        rw_urgent = H.require(body, "response_window_minutes_urgent", "integer")
        rw_standard = H.require(body, "response_window_minutes_standard", "integer")
        is_active = H.optional(body, "is_active", True, ftype="boolean")
        with db.lock():
            S.run_system_sweeps()
            for m in db.STORES["markets"].values():
                if m["market_code"] == market_code:
                    raise_err(ERR_MARKET_CODE_TAKEN, "market_code must be unique")
            market = H.new_entity()
            market.update({
                "market_code": market_code,
                "display_name": display_name,
                "polygon_geojson": polygon_geojson,
                "response_window_minutes_urgent": rw_urgent,
                "response_window_minutes_standard": rw_standard,
                "is_active": is_active,
                "open_visit_count": 0,
            })
            db.STORES["markets"][market["id"]] = market
        return success_object(market, 201)

    @app.get("/dh/markets")
    def list_markets():
        require_roles(MARKET_READ_ROLES)
        with db.lock():
            S.run_system_sweeps()
            is_active_q = H.request.args.get("is_active")
            items = list(db.STORES["markets"].values())
            if is_active_q is not None:
                want = is_active_q.lower() in ("true", "1", "yes")
                items = [m for m in items if m.get("is_active") == want]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.get("/dh/markets/<mid>")
    def get_market(mid):
        require_roles(MARKET_READ_ROLES)
        with db.lock():
            S.run_system_sweeps()
            market = db.STORES["markets"].get(mid)
            if market is None:
                raise_err(ERR_NOT_FOUND, "market not found")
        return success_object(market)

    # ---------------- Payer contracts ----------------
    @app.post("/dh/payer-contracts")
    def create_contract():
        require_roles({"PlatformAdmin"})
        body = H.get_json_body()
        payer_code = H.require(body, "payer_code", "string")
        market_id = H.require(body, "market_id", "string", fk_store="markets")
        urgent_rate = H.require(body, "urgent_base_rate_cents", "integer")
        standard_rate = H.require(body, "standard_base_rate_cents", "integer")
        modifier = H.require(body, "place_of_service_modifier_pct", "number")
        max_claim = H.require(body, "max_claim_cents", "integer")
        eff_from = H.require(body, "effective_from", "datetime")
        eff_to = H.require(body, "effective_to", "datetime")
        with db.lock():
            S.run_system_sweeps()
            contract = H.new_entity()
            contract.update({
                "payer_code": payer_code,
                "market_id": market_id,
                "urgent_base_rate_cents": urgent_rate,
                "standard_base_rate_cents": standard_rate,
                "place_of_service_modifier_pct": modifier,
                "max_claim_cents": max_claim,
                "effective_from": eff_from,
                "effective_to": eff_to,
                "status": "DRAFT",
            })
            db.STORES["payer_contracts"][contract["id"]] = contract
        return success_object(contract, 201)

    @app.get("/dh/payer-contracts")
    def list_contracts():
        require_roles(CONTRACT_READ_ROLES)
        with db.lock():
            S.run_system_sweeps()
            page, total, limit, offset = H.list_response(
                list(db.STORES["payer_contracts"].values()),
                filters={
                    "payer_code": H.request.args.get("payer_code"),
                    "market_id": H.request.args.get("market_id"),
                    "status": H.request.args.get("status"),
                },
            )
        return success_list(page, total, limit, offset)

    @app.get("/dh/payer-contracts/<cid>")
    def get_contract(cid):
        require_roles(CONTRACT_READ_ROLES)
        with db.lock():
            S.run_system_sweeps()
            contract = db.STORES["payer_contracts"].get(cid)
            if contract is None:
                raise_err(ERR_NOT_FOUND, "payer contract not found")
        return success_object(contract)

    @app.post("/dh/payer-contracts/<cid>/activate")
    def activate_contract(cid):
        require_roles({"PlatformAdmin"})
        with db.lock():
            S.run_system_sweeps()
            contract = db.STORES["payer_contracts"].get(cid)
            if contract is None:
                raise_err(ERR_NOT_FOUND, "payer contract not found")
            if contract["status"] != "DRAFT":
                raise_err(ERR_CONTRACT_INVALID_STATE, "contract is not DRAFT")
            if H.parse_dt(contract["effective_from"]) >= H.parse_dt(contract["effective_to"]):
                raise_err(ERR_CONTRACT_WINDOW_INVALID, "effective_from must precede effective_to")
            contract["status"] = "ACTIVE"
            H.touch(contract)
        return success_object(contract)

    @app.post("/dh/payer-contracts/<cid>/terminate")
    def terminate_contract(cid):
        require_roles({"PlatformAdmin"})
        with db.lock():
            S.run_system_sweeps()
            contract = db.STORES["payer_contracts"].get(cid)
            if contract is None:
                raise_err(ERR_NOT_FOUND, "payer contract not found")
            if contract["status"] != "ACTIVE":
                raise_err(ERR_CONTRACT_INVALID_STATE, "contract is not ACTIVE")
            contract["status"] = "TERMINATED"
            H.touch(contract)
        return success_object(contract)

    # ---------------- Formulary entries ----------------
    @app.post("/dh/payer-contracts/<cid>/formulary-entries")
    def create_formulary_entry(cid):
        require_roles({"PlatformAdmin"})
        with db.lock():
            S.run_system_sweeps()
            contract = db.STORES["payer_contracts"].get(cid)
            if contract is None:
                raise_err(ERR_NOT_FOUND, "payer contract not found")
            body = H.get_json_body()
            drug_code = H.require(body, "drug_code", "string")
            max_units = H.require(body, "max_units_per_visit", "integer")
            requires_preauth = H.require(body, "requires_physician_preauth", "boolean")
            unit_price = H.require(body, "unit_price_cents", "integer")
            entry = H.new_entity()
            entry.update({
                "payer_contract_id": cid,
                "drug_code": drug_code,
                "max_units_per_visit": max_units,
                "requires_physician_preauth": requires_preauth,
                "unit_price_cents": unit_price,
            })
            db.STORES["formulary_entries"][entry["id"]] = entry
        return success_object(entry, 201)

    @app.get("/dh/payer-contracts/<cid>/formulary-entries")
    def list_formulary_entries(cid):
        require_roles({"PlatformAdmin", "BillingSpecialist", "AdvancedPracticeProvider"})
        with db.lock():
            S.run_system_sweeps()
            contract = db.STORES["payer_contracts"].get(cid)
            if contract is None:
                raise_err(ERR_NOT_FOUND, "payer contract not found")
            items = [e for e in db.STORES["formulary_entries"].values()
                     if e["payer_contract_id"] == cid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    # ---------------- Patients ----------------
    @app.post("/dh/patients")
    def create_patient():
        require_roles({"PlatformAdmin", "TriageNurse"})
        body = H.get_json_body()
        full_name = H.require(body, "full_name", "string")
        dob = H.require(body, "date_of_birth", "string")
        try:
            dob_parsed = H.parse_date(dob)
        except ValueError:
            raise_err(ERR_INVALID_REQUEST, "date_of_birth must be YYYY-MM-DD")
        payer_code = H.require(body, "payer_code", "string")
        member_id = H.require(body, "member_id", "string")
        pcp_name = H.require(body, "pcp_name", "string")
        pcp_npi = H.require(body, "pcp_npi", "string")
        comorbidity_count = H.optional(body, "comorbidity_count", 0, ftype="integer")
        home_address_geo = H.require(body, "home_address_geo", "string")
        with db.lock():
            S.run_system_sweeps()
            patient = H.new_entity()
            patient.update({
                "full_name": full_name,
                "date_of_birth": dob_parsed,
                "payer_code": payer_code,
                "member_id": member_id,
                "pcp_name": pcp_name,
                "pcp_npi": pcp_npi,
                "comorbidity_count": comorbidity_count,
                "home_address_geo": home_address_geo,
            })
            db.STORES["patients"][patient["id"]] = patient
        return success_object(serialize_patient(patient), 201)

    @app.get("/dh/patients")
    def list_patients():
        require_roles(PATIENT_LIST_ROLES)
        with db.lock():
            S.run_system_sweeps()
            items = [serialize_patient(p) for p in db.STORES["patients"].values()]
            page, total, limit, offset = H.list_response(
                items, filters={"payer_code": H.request.args.get("payer_code")})
        return success_list(page, total, limit, offset)

    @app.get("/dh/patients/<pid>")
    def get_patient(pid):
        require_roles(PATIENT_GET_ROLES)
        with db.lock():
            S.run_system_sweeps()
            patient = db.STORES["patients"].get(pid)
            if patient is None:
                raise_err(ERR_NOT_FOUND, "patient not found")
        return success_object(serialize_patient(patient))

    @app.get("/dh/patients/<pid>/visit-requests")
    def list_patient_visit_requests(pid):
        require_roles(PATIENT_LIST_ROLES)
        with db.lock():
            S.run_system_sweeps()
            patient = db.STORES["patients"].get(pid)
            if patient is None:
                raise_err(ERR_NOT_FOUND, "patient not found")
            items = [v for v in db.STORES["visit_requests"].values() if v["patient_id"] == pid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)


def serialize_patient(patient):
    out = dict(patient)
    dob = out.get("date_of_birth")
    if hasattr(dob, "isoformat"):
        out["date_of_birth"] = dob.isoformat()
    return out
