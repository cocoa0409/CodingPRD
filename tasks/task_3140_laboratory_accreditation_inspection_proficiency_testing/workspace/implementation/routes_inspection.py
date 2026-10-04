"""Inspection cycles, team assignments, and findings."""
from datetime import timedelta

from flask import request

import services
import store
from auth import require_auth
from errors import ApiError
from helpers import (
    ALL_READERS,
    body,
    get_or_404,
    new_record,
    public,
    require_fields,
)
from util import fmt_instant, fmt_ts, list_response, parse_ts, success

DECISIONS = {"ACCREDITED", "CONDITIONAL", "DENIED"}


def register_inspection_routes(app):

    # ---------------- cycles ----------------

    @app.route("/inspection-cycles", methods=["POST"])
    def create_cycle():
        require_auth(["AccreditationOfficer"])
        data = body()
        require_fields(data, ["laboratory_id", "scheduled_start", "scheduled_end"])
        with store.lock():
            lab = get_or_404("laboratories", data["laboratory_id"], "ERR_LABORATORY_NOT_FOUND")
            start = parse_ts(data["scheduled_start"])
            end = parse_ts(data["scheduled_end"])
            if end <= start:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "scheduled_end must be after scheduled_start"
                )
            for c in store.STORES["inspection_cycles"].values():
                if c["laboratory_id"] != lab["id"]:
                    continue
                if c["status"] not in services.CYCLE_OPEN_STATUSES:
                    continue
                # half-open [start, end) overlap
                if start < c["_sched_end"] and end > c["_sched_start"]:
                    raise ApiError(
                        "ERR_CYCLE_WINDOW_OVERLAP",
                        409,
                        "cycle window overlaps an existing cycle of this laboratory",
                    )
            rec = new_record(
                {
                    "laboratory_id": lab["id"],
                    "scheduled_start": fmt_instant(start),
                    "scheduled_end": fmt_instant(end),
                    "status": "TEAM_ASSEMBLY",
                    "posture_ready": services.compute_posture(lab["id"]),
                    "deficiency_burden_score": 0,
                    "provisional_decision": None,
                    "final_decision": None,
                    "appeal_count": 0,
                }
            )
            rec["_sched_start"] = start
            rec["_sched_end"] = end
            rec["_decided_dt"] = None
            store.STORES["inspection_cycles"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/inspection-cycles", methods=["GET"])
    def list_cycles():
        require_auth(ALL_READERS)
        items = list(store.STORES["inspection_cycles"].values())
        lab = request.args.get("laboratory_id")
        if lab is not None:
            items = [c for c in items if c["laboratory_id"] == lab]
        return list_response(items)

    @app.route("/inspection-cycles/<cycleId>", methods=["GET"])
    def get_cycle(cycleId):
        require_auth(ALL_READERS)
        rec = get_or_404("inspection_cycles", cycleId, "ERR_CYCLE_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/inspection-cycles/<cycleId>/screen-team", methods=["POST"])
    def screen_team(cycleId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            cycle = get_or_404("inspection_cycles", cycleId, "ERR_CYCLE_NOT_FOUND")
            if cycle["status"] != "TEAM_ASSEMBLY":
                raise ApiError("ERR_INVALID_STATE", 409, "cycle is not in TEAM_ASSEMBLY")
            assignments = [
                a
                for a in store.STORES["team_assignments"].values()
                if a["inspection_cycle_id"] == cycle["id"]
            ]
            has_lead = any(
                a["role_in_team"] == "LEAD" and a["status"] == "CLEARED" for a in assignments
            )
            has_pending = any(a["status"] == "PENDING" for a in assignments)
            if not has_lead or has_pending:
                raise ApiError(
                    "ERR_TEAM_INCOMPLETE",
                    409,
                    "team must have a CLEARED LEAD and no PENDING assignments",
                )
            if any(a["status"] == "CONFLICTED" for a in assignments):
                raise ApiError(
                    "ERR_CONFLICTED_INSPECTOR", 409, "a CONFLICTED assignment must be replaced"
                )
            cycle["status"] = "SCREENED"
            services.touch(cycle)
        return success(public(cycle), status=200)

    @app.route("/inspection-cycles/<cycleId>/conduct", methods=["POST"])
    def conduct_cycle(cycleId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            cycle = get_or_404("inspection_cycles", cycleId, "ERR_CYCLE_NOT_FOUND")
            if cycle["status"] != "SCREENED":
                raise ApiError("ERR_INVALID_STATE", 409, "cycle is not in SCREENED")
            posture = services.compute_posture(cycle["laboratory_id"])
            if cycle["posture_ready"] != posture:
                cycle["posture_ready"] = posture
            now = store.now()
            if not (cycle["_sched_start"] <= now < cycle["_sched_end"]):
                raise ApiError(
                    "ERR_INSPECTION_WINDOW_NOT_OPEN",
                    409,
                    "current time is outside the inspection window",
                )
            if not posture:
                raise ApiError("ERR_CYCLE_NOT_READY", 409, "cycle posture is not ready")
            cycle["status"] = "CONDUCTED"
            services.touch(cycle)
        return success(public(cycle), status=200)

    @app.route("/inspection-cycles/<cycleId>/issue-findings", methods=["POST"])
    def issue_findings(cycleId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            cycle = get_or_404("inspection_cycles", cycleId, "ERR_CYCLE_NOT_FOUND")
            if cycle["status"] != "CONDUCTED":
                raise ApiError("ERR_INVALID_STATE", 409, "cycle is not in CONDUCTED")
            findings = [
                f
                for f in store.STORES["inspection_findings"].values()
                if f["inspection_cycle_id"] == cycle["id"]
            ]
            if not any(
                f["status"] in ("CITED", "RESPONSE_SUBMITTED", "ACCEPTED") for f in findings
            ):
                raise ApiError(
                    "ERR_NO_FINDINGS", 409, "no findings in CITED/RESPONSE_SUBMITTED/ACCEPTED"
                )
            issued_at = store.now()
            for f in findings:
                if f["status"] in ("CITED", "RESPONSE_SUBMITTED"):
                    if f["deficiency_level"] == "LEVEL_1":
                        due = issued_at + timedelta(days=14)
                    else:
                        due = services.add_business_days_end(issued_at, 5)
                    f["response_due_at"] = fmt_instant(due)
                    f["_response_due_dt"] = due
                    services.touch(f)
            services.recompute_burden(cycle["id"])
            b = cycle["deficiency_burden_score"]
            if b == 0:
                cycle["provisional_decision"] = "ACCREDITED"
            elif b <= 6:
                cycle["provisional_decision"] = "CONDITIONAL"
            else:
                cycle["provisional_decision"] = "DENIED"
            cycle["status"] = "FINDINGS_ISSUED"
            services.touch(cycle)
        return success(public(cycle), status=200)

    def _do_decide(cycle, decision, new_status):
        if decision not in DECISIONS:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "decision must be ACCREDITED, CONDITIONAL, or DENIED"
            )
        burden = services.compute_burden(cycle["id"])
        cycle["deficiency_burden_score"] = burden
        if burden > 0 and decision != "DENIED":
            raise ApiError(
                "ERR_DECISION_BLOCKED_BY_BURDEN",
                409,
                "non-DENIED decision blocked by deficiency burden",
            )
        cycle["final_decision"] = decision
        cycle["status"] = new_status
        cycle["_decided_dt"] = store.now()
        services.touch(cycle)
        lab = store.STORES["laboratories"].get(cycle["laboratory_id"])
        if lab:
            services.apply_lab_decision(lab, decision)

    @app.route("/inspection-cycles/<cycleId>/decide", methods=["POST"])
    def decide_cycle(cycleId):
        require_auth(["AccreditationOfficer"])
        data = body()
        with store.lock():
            cycle = get_or_404("inspection_cycles", cycleId, "ERR_CYCLE_NOT_FOUND")
            if cycle["status"] != "FINDINGS_ISSUED":
                raise ApiError("ERR_INVALID_STATE", 409, "cycle is not in FINDINGS_ISSUED")
            _do_decide(cycle, data.get("decision"), "DECIDED")
        return success(public(cycle), status=200)

    @app.route("/inspection-cycles/<cycleId>/re-decide", methods=["POST"])
    def redecide_cycle(cycleId):
        require_auth(["AccreditationOfficer"])
        data = body()
        with store.lock():
            cycle = get_or_404("inspection_cycles", cycleId, "ERR_CYCLE_NOT_FOUND")
            if cycle["status"] != "INTERIM_SELF_INSPECTION":
                raise ApiError(
                    "ERR_INVALID_STATE", 409, "cycle is not in INTERIM_SELF_INSPECTION"
                )
            _do_decide(cycle, data.get("decision"), "RE_DECIDED")
        return success(public(cycle), status=200)

    @app.route("/inspection-cycles/<cycleId>/appeal", methods=["POST"])
    def appeal_cycle(cycleId):
        user_id, role = require_auth(["LaboratoryDirector"])
        with store.lock():
            cycle = get_or_404("inspection_cycles", cycleId, "ERR_CYCLE_NOT_FOUND")
            if cycle["status"] not in ("DECIDED", "RE_DECIDED"):
                raise ApiError("ERR_INVALID_STATE", 409, "cycle is not DECIDED or RE_DECIDED")
            if cycle["laboratory_id"] != user_id:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    403,
                    "LaboratoryDirector may only act for their own laboratory",
                )
            if store.now() > cycle["_decided_dt"] + timedelta(days=30):
                raise ApiError("ERR_APPEAL_WINDOW_CLOSED", 409, "appeal window has closed")
            if cycle["appeal_count"] >= 2:
                raise ApiError("ERR_APPEAL_LIMIT_REACHED", 409, "appeal limit reached")
            cycle["appeal_count"] += 1
            cycle["status"] = "APPEALED"
            services.touch(cycle)
        return success(public(cycle), status=200)

    @app.route("/inspection-cycles/<cycleId>/self-inspect", methods=["POST"])
    def self_inspect(cycleId):
        user_id, role = require_auth(["LaboratoryDirector"])
        with store.lock():
            cycle = get_or_404("inspection_cycles", cycleId, "ERR_CYCLE_NOT_FOUND")
            if cycle["status"] != "APPEALED":
                raise ApiError("ERR_INVALID_STATE", 409, "cycle is not in APPEALED")
            if cycle["laboratory_id"] != user_id:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    403,
                    "LaboratoryDirector may only act for their own laboratory",
                )
            cycle["status"] = "INTERIM_SELF_INSPECTION"
            services.touch(cycle)
        return success(public(cycle), status=200)

    # ---------------- team assignments ----------------

    @app.route("/team-assignments", methods=["POST"])
    def create_team_assignment():
        require_auth(["AccreditationOfficer"])
        data = body()
        require_fields(data, ["inspection_cycle_id", "inspector_id", "role_in_team"])
        if data["role_in_team"] not in ("LEAD", "MEMBER"):
            raise ApiError("ERR_INVALID_REQUEST", 400, "role_in_team must be LEAD or MEMBER")
        with store.lock():
            cycle = get_or_404(
                "inspection_cycles", data["inspection_cycle_id"], "ERR_CYCLE_NOT_FOUND"
            )
            get_or_404("inspector_profiles", data["inspector_id"], "ERR_INSPECTOR_NOT_FOUND")
            rec = new_record(
                {
                    "inspection_cycle_id": cycle["id"],
                    "inspector_id": data["inspector_id"],
                    "role_in_team": data["role_in_team"],
                    "status": "PENDING",
                }
            )
            store.STORES["team_assignments"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/team-assignments", methods=["GET"])
    def list_team_assignments():
        require_auth(ALL_READERS)
        items = list(store.STORES["team_assignments"].values())
        cid = request.args.get("inspection_cycle_id")
        if cid is not None:
            items = [a for a in items if a["inspection_cycle_id"] == cid]
        iid = request.args.get("inspector_id")
        if iid is not None:
            items = [a for a in items if a["inspector_id"] == iid]
        return list_response(items)

    @app.route("/team-assignments/<assignmentId>", methods=["GET"])
    def get_team_assignment(assignmentId):
        require_auth(ALL_READERS)
        rec = get_or_404("team_assignments", assignmentId, "ERR_ASSIGNMENT_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/team-assignments/<assignmentId>/clear", methods=["POST"])
    def clear_assignment(assignmentId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            asg = get_or_404("team_assignments", assignmentId, "ERR_ASSIGNMENT_NOT_FOUND")
            if asg["status"] != "PENDING":
                raise ApiError("ERR_INVALID_STATE", 409, "assignment is not PENDING")
            insp = get_or_404(
                "inspector_profiles", asg["inspector_id"], "ERR_INSPECTOR_NOT_FOUND"
            )
            cycle = get_or_404(
                "inspection_cycles", asg["inspection_cycle_id"], "ERR_CYCLE_NOT_FOUND"
            )
            if insp["status"] != "ACTIVE":
                raise ApiError("ERR_INSPECTOR_SUSPENDED", 409, "inspector is SUSPENDED")
            lab_enrollments = [
                e
                for e in store.STORES["enrollments"].values()
                if e["laboratory_id"] == cycle["laboratory_id"]
                and e["status"] in ("WAITING", "ACTIVE")
            ]
            lab_disciplines = {e["discipline"] for e in lab_enrollments}
            if not any(s in lab_disciplines for s in insp["specialties"]):
                raise ApiError(
                    "ERR_SPECIALTY_MISMATCH",
                    409,
                    "inspector specialties do not match the laboratory's enrolled disciplines",
                )
            if insp["affiliated_laboratory_id"] == cycle["laboratory_id"]:
                raise ApiError(
                    "ERR_SELF_INSPECTION", 409, "inspector belongs to the cycle's laboratory"
                )
            cutoff = cycle["_sched_start"] - timedelta(days=365)
            for c2 in store.STORES["inspection_cycles"].values():
                if c2["laboratory_id"] != cycle["laboratory_id"] or c2["id"] == cycle["id"]:
                    continue
                if c2["status"] not in services.CYCLE_CONDUCTED_ONWARD:
                    continue
                if not (cutoff <= c2["_sched_start"]):
                    continue
                for a2 in store.STORES["team_assignments"].values():
                    if a2["inspection_cycle_id"] != c2["id"]:
                        continue
                    if a2["status"] not in ("CLEARED", "PENDING", "REPLACED"):
                        continue
                    other = store.STORES["inspector_profiles"].get(a2["inspector_id"])
                    if other and other["affiliated_laboratory_id"] == insp["affiliated_laboratory_id"]:
                        raise ApiError(
                            "ERR_RECIPROCAL_CONFLICT",
                            409,
                            "inspector's affiliated laboratory inspected this laboratory within 365 days",
                        )
            asg["status"] = "CLEARED"
            services.touch(asg)
        return success(public(asg), status=200)

    @app.route("/team-assignments/<assignmentId>/flag-conflict", methods=["POST"])
    def flag_conflict(assignmentId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            asg = get_or_404("team_assignments", assignmentId, "ERR_ASSIGNMENT_NOT_FOUND")
            if asg["status"] != "PENDING":
                raise ApiError("ERR_INVALID_STATE", 409, "assignment is not PENDING")
            asg["status"] = "CONFLICTED"
            services.touch(asg)
        return success(public(asg), status=200)

    @app.route("/team-assignments/<assignmentId>/replace", methods=["POST"])
    def replace_assignment(assignmentId):
        require_auth(["AccreditationOfficer"])
        data = body()
        require_fields(data, ["replacement_inspector_id"])
        with store.lock():
            asg = get_or_404("team_assignments", assignmentId, "ERR_ASSIGNMENT_NOT_FOUND")
            if asg["status"] != "CONFLICTED":
                raise ApiError("ERR_INVALID_STATE", 409, "assignment is not CONFLICTED")
            get_or_404(
                "inspector_profiles",
                data["replacement_inspector_id"],
                "ERR_INSPECTOR_NOT_FOUND",
            )
            asg["status"] = "REPLACED"
            services.touch(asg)
            rec = new_record(
                {
                    "inspection_cycle_id": asg["inspection_cycle_id"],
                    "inspector_id": data["replacement_inspector_id"],
                    "role_in_team": asg["role_in_team"],
                    "status": "PENDING",
                }
            )
            store.STORES["team_assignments"][rec["id"]] = rec
        return success(public(asg), status=200)

    # ---------------- findings ----------------

    @app.route("/inspection-findings", methods=["POST"])
    def create_finding():
        user_id, role = require_auth(["Inspector"])
        data = body()
        require_fields(
            data,
            ["inspection_cycle_id", "section_id", "checklist_item_code", "deficiency_level"],
        )
        if not isinstance(data["checklist_item_code"], str) or not data[
            "checklist_item_code"
        ].strip():
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "checklist_item_code must be a non-empty string"
            )
        if data["deficiency_level"] not in ("LEVEL_1", "LEVEL_2"):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "deficiency_level must be LEVEL_1 or LEVEL_2"
            )
        with store.lock():
            cycle = get_or_404(
                "inspection_cycles", data["inspection_cycle_id"], "ERR_CYCLE_NOT_FOUND"
            )
            section = get_or_404("sections", data["section_id"], "ERR_SECTION_NOT_FOUND")
            get_or_404("inspector_profiles", user_id, "ERR_INSPECTOR_NOT_FOUND")
            if cycle["status"] != "CONDUCTED":
                raise ApiError("ERR_INVALID_STATE", 409, "cycle is not in CONDUCTED")
            enr = store.STORES["enrollments"].get(section["enrollment_id"])
            if not enr or enr["laboratory_id"] != cycle["laboratory_id"]:
                raise ApiError(
                    "ERR_SECTION_NOT_IN_LABORATORY",
                    409,
                    "section does not belong to the cycle's laboratory",
                )
            rec = new_record(
                {
                    "inspection_cycle_id": cycle["id"],
                    "section_id": section["id"],
                    "checklist_item_code": data["checklist_item_code"],
                    "deficiency_level": data["deficiency_level"],
                    "cited_by_inspector_id": user_id,
                    "response_due_at": None,
                    "response_text": None,
                    "status": "CITED",
                }
            )
            rec["_response_due_dt"] = None
            store.STORES["inspection_findings"][rec["id"]] = rec
            services.recompute_burden(cycle["id"])
        return success(public(rec), status=201)

    @app.route("/inspection-findings", methods=["GET"])
    def list_findings():
        require_auth(ALL_READERS)
        items = list(store.STORES["inspection_findings"].values())
        cid = request.args.get("inspection_cycle_id")
        if cid is not None:
            items = [f for f in items if f["inspection_cycle_id"] == cid]
        sid = request.args.get("section_id")
        if sid is not None:
            items = [f for f in items if f["section_id"] == sid]
        iid = request.args.get("cited_by_inspector_id")
        if iid is not None:
            items = [f for f in items if f["cited_by_inspector_id"] == iid]
        return list_response(items)

    @app.route("/inspection-findings/<findingId>", methods=["GET"])
    def get_finding(findingId):
        require_auth(ALL_READERS)
        rec = get_or_404("inspection_findings", findingId, "ERR_FINDING_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/inspection-findings/<findingId>/respond", methods=["POST"])
    def respond_finding(findingId):
        user_id, role = require_auth(["LaboratoryDirector"])
        data = body()
        require_fields(data, ["response_text"])
        if not isinstance(data["response_text"], str) or not data["response_text"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "response_text must be a non-empty string")
        with store.lock():
            f = get_or_404("inspection_findings", findingId, "ERR_FINDING_NOT_FOUND")
            if f["status"] != "CITED":
                raise ApiError("ERR_INVALID_STATE", 409, "finding is not CITED")
            cycle = get_or_404(
                "inspection_cycles", f["inspection_cycle_id"], "ERR_CYCLE_NOT_FOUND"
            )
            if cycle["laboratory_id"] != user_id:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    403,
                    "LaboratoryDirector may only act for their own laboratory",
                )
            if cycle["status"] != "FINDINGS_ISSUED":
                raise ApiError(
                    "ERR_FINDING_NOT_RESPONDABLE",
                    409,
                    "cycle is not in FINDINGS_ISSUED",
                )
            if f.get("_response_due_dt") is not None and store.now() > f["_response_due_dt"]:
                raise ApiError(
                    "ERR_RESPONSE_DEADLINE_PASSED", 409, "response deadline has passed"
                )
            f["response_text"] = data["response_text"]
            f["status"] = "RESPONSE_SUBMITTED"
            services.touch(f)
            services.recompute_burden(cycle["id"])
        return success(public(f), status=200)

    @app.route("/inspection-findings/<findingId>/accept", methods=["POST"])
    def accept_finding(findingId):
        user_id, role = require_auth(["Inspector"])
        with store.lock():
            f = get_or_404("inspection_findings", findingId, "ERR_FINDING_NOT_FOUND")
            if f["status"] != "RESPONSE_SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", 409, "finding is not RESPONSE_SUBMITTED")
            if user_id == f["cited_by_inspector_id"]:
                raise ApiError(
                    "ERR_SEGREGATION_OF_DUTIES",
                    409,
                    "citing inspector may not accept the response",
                )
            f["status"] = "ACCEPTED"
            services.touch(f)
            services.recompute_burden(f["inspection_cycle_id"])
        return success(public(f), status=200)

    @app.route("/inspection-findings/<findingId>/withdraw", methods=["POST"])
    def withdraw_finding(findingId):
        require_auth(["Inspector"])
        with store.lock():
            f = get_or_404("inspection_findings", findingId, "ERR_FINDING_NOT_FOUND")
            if f["status"] != "CITED":
                raise ApiError("ERR_INVALID_STATE", 409, "finding is not CITED")
            f["status"] = "WITHDRAWN"
            services.touch(f)
            services.recompute_burden(f["inspection_cycle_id"])
        return success(public(f), status=200)
