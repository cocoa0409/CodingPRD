"""Claims, claim lines, follow-up notices, monitoring check-ins."""
import db
import helpers as H
import services as S
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
    ERR_CLAIM_INVALID_STATE, ERR_CLAIM_CAP_EXCEEDED, ERR_CONTRACT_NOT_IN_FORCE,
    ERR_APPEAL_LIMIT_REACHED, ERR_NOTICE_INVALID_STATE, ERR_CHECKIN_INVALID_STATE,
    ERR_CHECKIN_NOT_DUE,
)
from middleware import require_roles
from response import success_object, success_list

CLAIM_ROLES = {"PlatformAdmin", "BillingSpecialist", "PayerAdjudicator"}
NOTICE_ROLES = {"PlatformAdmin", "TriageNurse"}
CHECKIN_ROLES = {"PlatformAdmin", "TriageNurse"}
CHECKIN_OUTCOMES = {"STABLE", "WORSENING", "EMERGENT"}


def _get_claim(cid):
    claim = db.STORES["claims"].get(cid)
    if claim is None:
        raise_err(ERR_NOT_FOUND, "claim not found")
    return claim


def register(app):

    # ---------------- Claims ----------------
    @app.get("/dh/claims")
    def list_claims():
        require_roles(CLAIM_ROLES)
        with db.lock():
            S.run_system_sweeps()
            page, total, limit, offset = H.list_response(
                list(db.STORES["claims"].values()),
                filters={
                    "visit_request_id": H.request.args.get("visit_request_id"),
                    "payer_contract_id": H.request.args.get("payer_contract_id"),
                    "status": H.request.args.get("status"),
                },
            )
        return success_list(page, total, limit, offset)

    @app.get("/dh/claims/<cid>")
    def get_claim(cid):
        require_roles(CLAIM_ROLES)
        with db.lock():
            S.run_system_sweeps()
            claim = _get_claim(cid)
        return success_object(claim)

    @app.get("/dh/claims/<cid>/claim-lines")
    def list_claim_lines(cid):
        require_roles(CLAIM_ROLES)
        with db.lock():
            S.run_system_sweeps()
            _get_claim(cid)
            items = [l for l in db.STORES["claim_lines"].values() if l["claim_id"] == cid]
            page, total, limit, offset = H.list_response(items)
        return success_list(page, total, limit, offset)

    @app.post("/dh/claims/<cid>/submit")
    def submit_claim(cid):
        require_roles({"BillingSpecialist"})
        body = H.get_json_body()
        expected_version = H.require(body, "expected_visit_request_version", "integer")
        with db.lock():
            S.run_system_sweeps()
            claim = _get_claim(cid)
            vr = db.STORES["visit_requests"].get(claim["visit_request_id"])
            # OCC (priority 5) before state (priority 6)
            if expected_version != vr["version"]:
                raise_err(ERR_STALE_VERSION, "stale visit request version")
            if claim["status"] != "DRAFT":
                raise_err(ERR_CLAIM_INVALID_STATE, "claim is not DRAFT")
            contract = db.STORES["payer_contracts"].get(claim["payer_contract_id"])
            # Contract in force (priority 21/22): state check happened above; run
            # fiscal-temporal guards in scaffold priority order.
            enc = S.encounter_for_visit(vr["id"])
            ended_at = H.parse_dt(enc["ended_at"]) if enc and enc.get("ended_at") else None
            in_force = (
                contract is not None
                and contract["status"] == "ACTIVE"
                and ended_at is not None
                and H.parse_dt(contract["effective_from"]) <= ended_at < H.parse_dt(contract["effective_to"])
            )
            # Priority 21 (cap) precedes priority 22 (contract window) in scaffold ordering.
            if contract is not None and claim["final_total_cents"] > contract["max_claim_cents"]:
                raise_err(ERR_CLAIM_CAP_EXCEEDED, "claim total exceeds contract cap")
            if not in_force:
                raise_err(ERR_CONTRACT_NOT_IN_FORCE, "payer contract not in force")
            claim["status"] = "SUBMITTED"
            claim["submitted_at"] = H.logical_now_str()
            H.touch(claim)
            vr["status"] = "CLAIM_SUBMITTED"
            H.touch(vr)
        return success_object(claim)

    @app.post("/dh/claims/<cid>/adjudicate")
    def adjudicate_claim(cid):
        require_roles({"PayerAdjudicator"})
        body = H.get_json_body()
        outcome = H.require(body, "outcome", "string", enum={"PAID", "DENIED"})
        with db.lock():
            S.run_system_sweeps()
            claim = _get_claim(cid)
            if claim["status"] != "SUBMITTED":
                raise_err(ERR_CLAIM_INVALID_STATE, "claim is not SUBMITTED")
            vr = db.STORES["visit_requests"].get(claim["visit_request_id"])
            if outcome == "PAID":
                claim["status"] = "ADJUDICATED_PAID"
                vr["status"] = "CLAIM_ADJUDICATED_PAID"
            else:
                claim["status"] = "ADJUDICATED_DENIED"
                vr["status"] = "CLAIM_ADJUDICATED_DENIED"
            claim["adjudicated_at"] = H.logical_now_str()
            H.touch(claim)
            H.touch(vr)
            if outcome == "PAID":
                S.maybe_close_paid_visit(vr["id"])
        return success_object(claim)

    @app.post("/dh/claims/<cid>/appeal")
    def appeal_claim(cid):
        require_roles({"BillingSpecialist"})
        with db.lock():
            S.run_system_sweeps()
            claim = _get_claim(cid)
            if claim["status"] != "ADJUDICATED_DENIED":
                raise_err(ERR_CLAIM_INVALID_STATE, "claim is not ADJUDICATED_DENIED")
            claim["status"] = "APPEALED"
            claim["appeal_count"] = claim.get("appeal_count", 0) + 1
            H.touch(claim)
            vr = db.STORES["visit_requests"].get(claim["visit_request_id"])
            vr["status"] = "CLAIM_APPEALED"
            H.touch(vr)
        return success_object(claim)

    @app.post("/dh/claims/<cid>/resubmit")
    def resubmit_claim(cid):
        require_roles({"BillingSpecialist"})
        with db.lock():
            S.run_system_sweeps()
            claim = _get_claim(cid)
            if claim["status"] != "APPEALED":
                raise_err(ERR_CLAIM_INVALID_STATE, "claim is not APPEALED")
            if claim.get("appeal_count", 0) > 2:
                raise_err(ERR_APPEAL_LIMIT_REACHED, "appeal round limit reached")
            claim["status"] = "SUBMITTED"
            claim["submitted_at"] = H.logical_now_str()
            H.touch(claim)
            vr = db.STORES["visit_requests"].get(claim["visit_request_id"])
            vr["status"] = "CLAIM_SUBMITTED"
            H.touch(vr)
        return success_object(claim)

    # ---------------- Follow-up notices ----------------
    @app.get("/dh/follow-up-notices/<nid>")
    def get_notice(nid):
        require_roles(NOTICE_ROLES)
        with db.lock():
            S.run_system_sweeps()
            n = db.STORES["follow_up_notices"].get(nid)
            if n is None:
                raise_err(ERR_NOT_FOUND, "follow-up notice not found")
        return success_object(n)

    @app.post("/dh/follow-up-notices/<nid>/mark-sent")
    def mark_notice_sent(nid):
        require_roles({"TriageNurse"})
        with db.lock():
            S.run_system_sweeps()
            n = db.STORES["follow_up_notices"].get(nid)
            if n is None:
                raise_err(ERR_NOT_FOUND, "follow-up notice not found")
            if n["status"] != "QUEUED":
                raise_err(ERR_NOTICE_INVALID_STATE, "notice is not QUEUED")
            n["status"] = "SENT"
            n["sent_at"] = H.logical_now_str()
            H.touch(n)
        return success_object(n)

    @app.post("/dh/follow-up-notices/<nid>/mark-failed")
    def mark_notice_failed(nid):
        require_roles({"TriageNurse"})
        with db.lock():
            S.run_system_sweeps()
            n = db.STORES["follow_up_notices"].get(nid)
            if n is None:
                raise_err(ERR_NOT_FOUND, "follow-up notice not found")
            if n["status"] != "QUEUED":
                raise_err(ERR_NOTICE_INVALID_STATE, "notice is not QUEUED")
            n["status"] = "FAILED"
            H.touch(n)
        return success_object(n)

    # ---------------- Monitoring check-ins ----------------
    @app.get("/dh/monitoring-checkins/<mid>")
    def get_checkin(mid):
        require_roles(CHECKIN_ROLES)
        with db.lock():
            S.run_system_sweeps()
            c = db.STORES["monitoring_checkins"].get(mid)
            if c is None:
                raise_err(ERR_NOT_FOUND, "monitoring check-in not found")
        return success_object(c)

    @app.post("/dh/monitoring-checkins/<mid>/complete")
    def complete_checkin(mid):
        require_roles({"TriageNurse"})
        body = H.get_json_body()
        outcome = H.require(body, "outcome", "string", enum=CHECKIN_OUTCOMES)
        with db.lock():
            S.run_system_sweeps()
            c = db.STORES["monitoring_checkins"].get(mid)
            if c is None:
                raise_err(ERR_NOT_FOUND, "monitoring check-in not found")
            if c["status"] != "SCHEDULED":
                raise_err(ERR_CHECKIN_INVALID_STATE, "check-in is not SCHEDULED")
            now = H.logical_now()
            if now < H.parse_dt(c["scheduled_at"]):
                raise_err(ERR_CHECKIN_NOT_DUE, "check-in is not yet due")
            c["status"] = "COMPLETED"
            c["completed_at"] = H.fmt_dt(now)
            c["outcome"] = outcome
            H.touch(c)
            vr = db.STORES["visit_requests"].get(c["visit_request_id"])
            if outcome == "EMERGENT" and vr is not None:
                S.spawn_provider_visit(vr["patient_id"], vr["market_id"])
            if vr is not None:
                S.maybe_close_paid_visit(vr["id"])
        return success_object(c)

    @app.post("/dh/monitoring-checkins/<mid>/escalate")
    def escalate_checkin(mid):
        require_roles({"TriageNurse"})
        with db.lock():
            S.run_system_sweeps()
            c = db.STORES["monitoring_checkins"].get(mid)
            if c is None:
                raise_err(ERR_NOT_FOUND, "monitoring check-in not found")
            if c["status"] != "MISSED":
                raise_err(ERR_CHECKIN_INVALID_STATE, "check-in is not MISSED")
            c["status"] = "ESCALATED"
            H.touch(c)
            vr = db.STORES["visit_requests"].get(c["visit_request_id"])
            if vr is not None:
                S.spawn_provider_visit(vr["patient_id"], vr["market_id"])
                S.maybe_close_paid_visit(vr["id"])
        return success_object(c)
