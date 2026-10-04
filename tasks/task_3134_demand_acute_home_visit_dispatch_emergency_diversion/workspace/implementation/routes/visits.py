"""Visit requests, triage assessments, dispatch offers, follow-up notices, monitoring check-ins."""
from datetime import timedelta

import db
import helpers as H
import services as S
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_VR_INVALID_STATE, ERR_TRIAGE_ALREADY_EXISTS, ERR_TRIAGE_NOT_DRAFT,
    ERR_RED_FLAG_REQUIRES_EMS, ERR_ACUITY_TOO_HIGH_FOR_DECLINE,
    ERR_ACUITY_TOO_LOW_FOR_DIVERSION, ERR_MARKET_INACTIVE, ERR_OUT_OF_COVERAGE,
    ERR_NO_AVAILABLE_CARE_TEAM, ERR_STALE_VERSION, ERR_PCP_MISMATCH,
    ERR_CHECKIN_INVALID_STATE, ERR_CHECKIN_NOT_DUE, ERR_NOTICE_INVALID_STATE,
)
from middleware import require_roles
from response import success_object, success_list

VR_LIST_ROLES = {"PlatformAdmin", "Dispatcher", "TriageNurse", "BillingSpecialist", "PayerAdjudicator"}
VR_GET_ROLES = VR_LIST_ROLES | {"AdvancedPracticeProvider"}
VR_TRIAGE_READ = {"PlatformAdmin", "TriageNurse", "Dispatcher"}
VR_DISPATCH_READ = {"PlatformAdmin", "Dispatcher", "TriageNurse"}
VR_NOTICE_READ = {"PlatformAdmin", "TriageNurse"}
VR_CHECKIN_READ = {"PlatformAdmin", "TriageNurse"}
VR_HANDOFF_READ = {"PlatformAdmin", "TriageNurse", "Dispatcher"}
VR_ENCOUNTER_READ = {"PlatformAdmin", "TriageNurse", "Dispatcher", "AdvancedPracticeProvider"}
VR_DISPO_READ = {"PlatformAdmin", "TriageNurse", "AdvancedPracticeProvider"}
VR_TRANSPORT_READ = {"PlatformAdmin", "TriageNurse", "Dispatcher"}

REQUESTOR_ROLES = {"PATIENT", "PAYER", "PROVIDER", "FACILITY"}
TRIAGE_OUTCOMES = {"APPROPRIATE", "EMERGENCY_DIVERTED", "INAPPROPRIATE"}
CHECKIN_OUTCOMES = {"STABLE", "WORSENING", "EMERGENT"}


def _get_vr(vid):
    vr = db.STORES["visit_requests"].get(vid)
    if vr is None:
        raise_err(ERR_NOT_FOUND, "visit request not found")
    return vr


def register(app):

    # ---------------- Visit requests ----------------
    @app.post("/dh/visit-requests")
    def create_visit_request():
        require_roles({"TriageNurse", "Dispatcher"})
        body = H.get_json_body()
        patient_id = H.require(body, "patient_id", "string", fk_store="patients")
        market_id = H.require(body, "market_id", "string", fk_store="markets")
        requestor_role = H.require(body, "requestor_role", "string", enum=REQUESTOR_ROLES)
        chief_complaint = H.require(body, "chief_complaint", "string")
        with db.lock():
            S.run_system_sweeps()
            market = db.STORES["markets"][market_id]
            if not market.get("is_active", True):
                raise_err(ERR_MARKET_INACTIVE, "market is not active")
            patient = db.STORES["patients"][patient_id]
            point = H.parse_geo_point(patient.get("home_address_geo"))
            ring = H.parse_geo_polygon(market.get("polygon_geojson"))
            if not H.point_in_polygon(point, ring):
                raise_err(ERR_OUT_OF_COVERAGE, "patient home is outside the market coverage area")
            vr = H.new_entity()
            vr.update({
                "patient_id": patient_id,
                "market_id": market_id,
                "requestor_role": requestor_role,
                "chief_complaint": chief_complaint,
                "requested_at": H.logical_now_str(),
                "status": "INTAKE",
                "acuity_band": None,
                "assigned_care_team_id": None,
                "sla_deadline_at": None,
                "sla_breached": False,
                "claim_id": None,
            })
            db.STORES["visit_requests"][vr["id"]] = vr
            market["open_visit_count"] = market.get("open_visit_count", 0) + 1
            H.touch(market)
        return success_object(vr, 201)

    @app.get("/dh/visit-requests")
    def list_visit_requests():
        require_roles(VR_LIST_ROLES)
        with db.lock():
            S.run_system_sweeps()
            page, total, limit, offset = H.list_response(
                list(db.STORES["visit_requests"].values()),
                filters={
                    "patient_id": H.request.args.get("patient_id"),
                    "market_id": H.request.args.get("market_id"),
                    "status": H.request.args.get("status"),
                    "acuity_band": H.request.args.get("acuity_band"),
                    "assigned_care_team_id": H.request.args.get("assigned_care_team_id"),
                    "claim_id": H.request.args.get("claim_id"),
                },
            )
        return success_list(page, total, limit, offset)

    @app.get("/dh/visit-requests/<vid>")
    def get_visit_request(vid):
        require_roles(VR_GET_ROLES)
        with db.lock():
            S.run_system_sweeps()
            vr = _get_vr(vid)
        return success_object(vr)

    # --- visit sub-resource reads ---
    @app.get("/dh/visit-requests/<vid>/triage-assessments")
    def list_vr_triage(vid):
        require_roles(VR_TRIAGE_READ)
        with db.lock():
            S.run_system_sweeps()
            _get_vr(vid)
            items = [t for t in db.STORES["triage_assessments"].values()
                     if t["visit_request_id"] == vid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.get("/dh/visit-requests/<vid>/dispatch-assignments")
    def list_vr_dispatch(vid):
        require_roles(VR_DISPATCH_READ)
        with db.lock():
            S.run_system_sweeps()
            _get_vr(vid)
            items = [a for a in db.STORES["dispatch_assignments"].values()
                     if a["visit_request_id"] == vid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.get("/dh/visit-requests/<vid>/follow-up-notices")
    def list_vr_notices(vid):
        require_roles(VR_NOTICE_READ)
        with db.lock():
            S.run_system_sweeps()
            _get_vr(vid)
            items = [n for n in db.STORES["follow_up_notices"].values()
                     if n["visit_request_id"] == vid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.get("/dh/visit-requests/<vid>/monitoring-checkins")
    def list_vr_checkins(vid):
        require_roles(VR_CHECKIN_READ)
        with db.lock():
            S.run_system_sweeps()
            _get_vr(vid)
            items = [c for c in db.STORES["monitoring_checkins"].values()
                     if c["visit_request_id"] == vid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.get("/dh/visit-requests/<vid>/ems-handoffs")
    def list_vr_handoffs(vid):
        require_roles(VR_HANDOFF_READ)
        with db.lock():
            S.run_system_sweeps()
            _get_vr(vid)
            items = [h for h in db.STORES["ems_handoffs"].values()
                     if h["visit_request_id"] == vid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.get("/dh/visit-requests/<vid>/encounters")
    def list_vr_encounters(vid):
        require_roles(VR_ENCOUNTER_READ)
        with db.lock():
            S.run_system_sweeps()
            _get_vr(vid)
            items = [e for e in db.STORES["encounters"].values()
                     if e["visit_request_id"] == vid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.get("/dh/visit-requests/<vid>/disposition-decisions")
    def list_vr_decisions(vid):
        require_roles(VR_DISPO_READ)
        with db.lock():
            S.run_system_sweeps()
            _get_vr(vid)
            items = [d for d in db.STORES["disposition_decisions"].values()
                     if d["visit_request_id"] == vid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.get("/dh/visit-requests/<vid>/facility-transports")
    def list_vr_transports(vid):
        require_roles(VR_TRANSPORT_READ)
        with db.lock():
            S.run_system_sweeps()
            _get_vr(vid)
            items = [t for t in db.STORES["facility_transports"].values()
                     if t["visit_request_id"] == vid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    # --- triage assessment creation ---
    @app.post("/dh/visit-requests/<vid>/triage-assessments")
    def create_triage(vid):
        require_roles({"TriageNurse"})
        body = H.get_json_body()
        heart_rate = H.require(body, "heart_rate", "integer", min_val=20, max_val=250)
        systolic_bp = H.require(body, "systolic_bp", "integer", min_val=40, max_val=300)
        spo2_pct = H.require(body, "spo2_pct", "integer", min_val=50, max_val=100)
        flags = {}
        for f in S.RED_FLAG_FIELDS:
            flags[f] = H.require(body, f, "boolean")
        with db.lock():
            S.run_system_sweeps()
            vr = _get_vr(vid)
            if S.triage_for_visit(vid) is not None:
                raise_err(ERR_TRIAGE_ALREADY_EXISTS, "triage assessment already exists for this visit")
            if vr["status"] != "INTAKE":
                raise_err(ERR_VR_INVALID_STATE, "visit is not in INTAKE")
            triage = H.new_entity()
            triage.update({
                "visit_request_id": vid,
                "heart_rate": heart_rate,
                "systolic_bp": systolic_bp,
                "spo2_pct": spo2_pct,
                "is_chest_pain": flags["is_chest_pain"],
                "is_stroke_signs": flags["is_stroke_signs"],
                "is_severe_trauma": flags["is_severe_trauma"],
                "is_altered_mental_status": flags["is_altered_mental_status"],
                "acuity_score": None,
                "outcome": "DRAFT",
                "submitted_at": None,
            })
            db.STORES["triage_assessments"][triage["id"]] = triage
            vr["status"] = "TRIAGE_PENDING"
            H.touch(vr)
        return success_object(triage, 201)

    # --- dispatch offers (selector policy) ---
    @app.post("/dh/visit-requests/<vid>/dispatch-offers")
    def create_dispatch_offer(vid):
        require_roles({"Dispatcher"})
        body = H.get_json_body()
        expected_version = H.require(body, "expected_visit_request_version", "integer")
        with db.lock():
            S.run_system_sweeps()
            vr = _get_vr(vid)
            # OCC (priority 5) before state (priority 6)
            if expected_version != vr["version"]:
                raise_err(ERR_STALE_VERSION, "stale visit request version")
            if vr["status"] != "TRIAGED":
                raise_err(ERR_VR_INVALID_STATE, "visit is not TRIAGED")
            market = db.STORES["markets"][vr["market_id"]]
            if not market.get("is_active", True):
                raise_err(ERR_MARKET_INACTIVE, "market is not active")
            now = H.logical_now()
            needed = S.required_skills(vr)
            candidates = []
            for team in db.STORES["care_teams"].values():
                if team["market_id"] != vr["market_id"]:
                    continue
                if team["status"] != "AVAILABLE":
                    continue
                if team.get("active_dispatch_count", 0) != 0:
                    continue
                if not needed.issubset(set(team.get("skill_tags") or [])):
                    continue
                shift = S.find_operational_shift(team["id"], vr["market_id"], now)
                if shift is None:
                    continue
                minutes_since_available = max(
                    0, int((now - H.parse_dt(team["updated_at"])).total_seconds() // 60))
                score = 1000 - team.get("active_dispatch_count", 0) * 100 - minutes_since_available
                candidates.append((team, shift, score))
            if not candidates:
                raise_err(ERR_NO_AVAILABLE_CARE_TEAM, "no eligible care team")
            candidates.sort(key=lambda c: (-c[2], c[0]["created_at"]))
            winner, shift, score = candidates[0]
            da = H.new_entity()
            da.update({
                "visit_request_id": vid,
                "care_team_id": winner["id"],
                "vehicle_shift_id": shift["id"],
                "offered_at": H.logical_now_str(),
                "accepted_at": None,
                "selection_score": score,
                "status": "OFFERED",
            })
            db.STORES["dispatch_assignments"][da["id"]] = da
            winner["active_dispatch_count"] = winner.get("active_dispatch_count", 0) + 1
            if winner["status"] == "AVAILABLE" and winner["active_dispatch_count"] > 0:
                winner["status"] = "ON_DISPATCH"
            H.touch(winner)
            vr["status"] = "DISPATCH_PENDING"
            H.touch(vr)  # increments version per scaffold side effects
        return success_object(da, 201)

    # --- follow-up notices ---
    @app.post("/dh/visit-requests/<vid>/follow-up-notices")
    def create_notice(vid):
        require_roles({"TriageNurse"})
        body = H.get_json_body()
        pcp_npi = H.require(body, "pcp_npi", "string")
        payload_summary = H.require(body, "payload_summary", "string")
        if len(payload_summary) < 40:
            raise_err(ERR_INVALID_REQUEST, "payload_summary must be at least 40 characters")
        with db.lock():
            S.run_system_sweeps()
            vr = _get_vr(vid)
            patient = db.STORES["patients"].get(vr["patient_id"])
            if patient is None:
                raise_err(ERR_FK_NOT_FOUND, "patient not found")
            if pcp_npi != patient.get("pcp_npi"):
                raise_err(ERR_PCP_MISMATCH, "pcp_npi does not match the patient's PCP")
            notice = H.new_entity()
            notice.update({
                "visit_request_id": vid,
                "pcp_npi": pcp_npi,
                "payload_summary": payload_summary,
                "sent_at": None,
                "status": "QUEUED",
            })
            db.STORES["follow_up_notices"][notice["id"]] = notice
            S.auto_advance_dispositioned(vr)
        return success_object(notice, 201)

    # --- manual monitoring check-in ---
    @app.post("/dh/visit-requests/<vid>/monitoring-checkins")
    def create_checkin(vid):
        require_roles({"TriageNurse"})
        body = H.get_json_body()
        scheduled_at = H.require(body, "scheduled_at", "datetime")
        with db.lock():
            S.run_system_sweeps()
            _get_vr(vid)
            row = H.new_entity()
            row.update({
                "visit_request_id": vid,
                "scheduled_at": scheduled_at,
                "completed_at": None,
                "outcome": None,
                "status": "SCHEDULED",
            })
            db.STORES["monitoring_checkins"][row["id"]] = row
        return success_object(row, 201)

    # ---------------- Triage assessments ----------------
    @app.get("/dh/triage-assessments/<tid>")
    def get_triage(tid):
        require_roles({"PlatformAdmin", "TriageNurse", "Dispatcher"})
        with db.lock():
            S.run_system_sweeps()
            t = db.STORES["triage_assessments"].get(tid)
            if t is None:
                raise_err(ERR_NOT_FOUND, "triage assessment not found")
        return success_object(t)

    @app.post("/dh/triage-assessments/<tid>/submit")
    def submit_triage(tid):
        require_roles({"TriageNurse"})
        body = H.get_json_body()
        outcome = H.require(body, "outcome", "string", enum=TRIAGE_OUTCOMES)
        ems_agency_code = H.optional(body, "ems_agency_code", "EMS-DEFAULT")
        handoff_reason = H.optional(body, "handoff_reason", "Emergency diversion")
        with db.lock():
            S.run_system_sweeps()
            t = db.STORES["triage_assessments"].get(tid)
            if t is None:
                raise_err(ERR_NOT_FOUND, "triage assessment not found")
            if t["outcome"] != "DRAFT":
                raise_err(ERR_TRIAGE_NOT_DRAFT, "triage assessment already submitted")
            vr = _get_vr(t["visit_request_id"])
            patient = db.STORES["patients"].get(vr["patient_id"])
            now = H.logical_now()
            score, band = S.compute_acuity(t, patient, now)
            any_red = S.red_flag_count(t) > 0
            # outcome-consistency guards (priority 9, 10, 11). Per PRD, the band
            # derivation has exactly three outcomes: EMERGENT-band => EMERGENCY_DIVERTED,
            # NON_ACUTE => INAPPROPRIATE, URGENT/STANDARD => APPROPRIATE. Band-mismatching
            # submissions map onto the three named errors.
            if any_red and outcome != "EMERGENCY_DIVERTED":
                raise_err(ERR_RED_FLAG_REQUIRES_EMS, "red-flag symptom requires EMS diversion")
            if outcome == "INAPPROPRIATE" and (score >= 30 or any_red):
                raise_err(ERR_ACUITY_TOO_HIGH_FOR_DECLINE, "acuity score too high to decline")
            if outcome == "EMERGENCY_DIVERTED" and not (score >= 80 or any_red):
                raise_err(ERR_ACUITY_TOO_LOW_FOR_DIVERSION, "acuity score too low for EMS diversion")
            # APPROPRIATE has no score-based rejection in PRD: its cascade writes
            # URGENT at score >= 50 and STANDARD otherwise.
            t["acuity_score"] = score
            t["outcome"] = outcome
            t["submitted_at"] = H.fmt_dt(now)
            H.touch(t)
            vr["acuity_band"] = band
            if outcome == "APPROPRIATE":
                vr["status"] = "TRIAGED"
            elif outcome == "EMERGENCY_DIVERTED":
                vr["status"] = "EMS_DIVERTED"
                handoff = H.new_entity()
                handoff.update({
                    "triage_assessment_id": t["id"],
                    "visit_request_id": vr["id"],
                    "ems_agency_code": ems_agency_code,
                    "handoff_reason": handoff_reason,
                    "handed_off_at": H.fmt_dt(now),
                })
                db.STORES["ems_handoffs"][handoff["id"]] = handoff
                S.decr_open_visit_count(vr["market_id"])
            else:  # INAPPROPRIATE
                vr["status"] = "DECLINED"
                S.decr_open_visit_count(vr["market_id"])
            H.touch(vr)
        return success_object(t)

    @app.get("/dh/triage-assessments/<tid>/ems-handoff")
    def get_triage_handoff(tid):
        require_roles({"PlatformAdmin", "TriageNurse", "Dispatcher"})
        with db.lock():
            S.run_system_sweeps()
            t = db.STORES["triage_assessments"].get(tid)
            if t is None:
                raise_err(ERR_NOT_FOUND, "triage assessment not found")
            items = [h for h in db.STORES["ems_handoffs"].values()
                     if h["triage_assessment_id"] == tid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)
