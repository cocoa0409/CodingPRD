"""PT subscriptions, shipments, results, and investigations."""
from decimal import Decimal, ROUND_HALF_UP
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
from util import fmt_instant, fmt_ts, is_num, list_response, parse_ts, success


def register_pt_routes(app):

    # ---------------- subscriptions ----------------

    @app.route("/pt-subscriptions", methods=["POST"])
    def create_pt_subscription():
        user_id, role = require_auth(["LaboratoryDirector"])
        data = body()
        require_fields(data, ["enrollment_id", "analytes"])
        with store.lock():
            enr = get_or_404("enrollments", data["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
            if enr["status"] != "ACTIVE":
                raise ApiError("ERR_ENROLLMENT_INACTIVE", 409, "enrollment is not ACTIVE")
            if enr["laboratory_id"] != user_id:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    403,
                    "LaboratoryDirector may only act for their own laboratory",
                )
            analytes = data["analytes"]
            if not isinstance(analytes, list) or not analytes:
                raise ApiError("ERR_INVALID_REQUEST", 400, "analytes must be a non-empty array")
            seen = set()
            any_critical = False
            for a in analytes:
                if not isinstance(a, dict):
                    raise ApiError("ERR_INVALID_REQUEST", 400, "each analyte must be an object")
                name = a.get("name")
                crit = a.get("critical")
                if not isinstance(name, str) or not name.strip():
                    raise ApiError("ERR_INVALID_REQUEST", 400, "analyte name must be a non-empty string")
                if not isinstance(crit, bool):
                    raise ApiError("ERR_INVALID_REQUEST", 400, "analyte critical must be boolean")
                if name in seen:
                    raise ApiError("ERR_INVALID_REQUEST", 400, "duplicate analyte name")
                seen.add(name)
                if crit:
                    any_critical = True
            if not any_critical:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "at least one analyte must be critical"
                )
            rec = new_record(
                {
                    "enrollment_id": enr["id"],
                    "analytes": [{"name": a["name"], "critical": a["critical"]} for a in analytes],
                }
            )
            store.STORES["pt_subscriptions"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/pt-subscriptions", methods=["GET"])
    def list_pt_subscriptions():
        require_auth(ALL_READERS)
        items = list(store.STORES["pt_subscriptions"].values())
        enr = request.args.get("enrollment_id")
        if enr is not None:
            items = [s for s in items if s["enrollment_id"] == enr]
        return list_response(items)

    @app.route("/pt-subscriptions/<subscriptionId>", methods=["GET"])
    def get_pt_subscription(subscriptionId):
        require_auth(ALL_READERS)
        rec = get_or_404("pt_subscriptions", subscriptionId, "ERR_SUBSCRIPTION_NOT_FOUND")
        return success(public(rec), status=200)

    # ---------------- shipments ----------------

    @app.route("/pt-shipments", methods=["POST"])
    def create_pt_shipment():
        require_auth(["PTCoordinator"])
        data = body()
        require_fields(data, ["subscription_id", "event_code"])
        if not isinstance(data["event_code"], str) or not data["event_code"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "event_code must be a non-empty string")
        with store.lock():
            sub = get_or_404("pt_subscriptions", data["subscription_id"], "ERR_SUBSCRIPTION_NOT_FOUND")
            shipped = store.now()
            due = shipped + timedelta(days=10)
            for other in store.STORES["pt_shipments"].values():
                if other["subscription_id"] != sub["id"] or other["status"] != "OPEN":
                    continue
                # closed intervals [shipped_at, due_at] intersect
                if shipped <= other["_due_dt"] and due >= other["_shipped_dt"]:
                    raise ApiError(
                        "ERR_SHIPMENT_WINDOW_OVERLAP",
                        409,
                        "shipment window overlaps an existing OPEN shipment",
                    )
            rec = new_record(
                {
                    "subscription_id": sub["id"],
                    "event_code": data["event_code"],
                    "shipped_at": fmt_instant(shipped),
                    "due_at": fmt_instant(due),
                    "status": "OPEN",
                    "closure_reason": None,
                }
            )
            rec["_shipped_dt"] = shipped
            rec["_due_dt"] = due
            store.STORES["pt_shipments"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/pt-shipments", methods=["GET"])
    def list_pt_shipments():
        require_auth(ALL_READERS)
        items = list(store.STORES["pt_shipments"].values())
        sub = request.args.get("subscription_id")
        if sub is not None:
            items = [s for s in items if s["subscription_id"] == sub]
        return list_response(items)

    @app.route("/pt-shipments/<shipmentId>", methods=["GET"])
    def get_pt_shipment(shipmentId):
        require_auth(ALL_READERS)
        rec = get_or_404("pt_shipments", shipmentId, "ERR_SHIPMENT_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/pt-shipments/<shipmentId>/close", methods=["POST"])
    def close_pt_shipment(shipmentId):
        require_auth(["PTCoordinator"])
        with store.lock():
            rec = get_or_404("pt_shipments", shipmentId, "ERR_SHIPMENT_NOT_FOUND")
            if rec["status"] != "OPEN":
                raise ApiError("ERR_SHIPMENT_CLOSED", 409, "shipment is not OPEN")
            rec["status"] = "CLOSED"
            rec["closure_reason"] = "ADMIN_CLOSED"
            services.touch(rec)
        return success(public(rec), status=200)

    # ---------------- results ----------------

    @app.route("/pt-results", methods=["POST"])
    def create_pt_result():
        user_id, role = require_auth(["LaboratoryDirector"])
        data = body()
        require_fields(data, ["shipment_id", "collected_at", "analyte_scores"])
        with store.lock():
            ship = get_or_404("pt_shipments", data["shipment_id"], "ERR_SHIPMENT_NOT_FOUND")
            sub = get_or_404(
                "pt_subscriptions", ship["subscription_id"], "ERR_SUBSCRIPTION_NOT_FOUND"
            )
            enr = get_or_404("enrollments", sub["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
            # state
            if ship["status"] != "OPEN":
                raise ApiError("ERR_SHIPMENT_CLOSED", 409, "shipment is not OPEN")
            # safety (priority 5): PT collection window first, then active-enrollment
            collected = parse_ts(data["collected_at"])
            if collected < ship["_shipped_dt"] or collected > ship["_shipped_dt"] + timedelta(days=5):
                raise ApiError(
                    "ERR_PT_COLLECTION_WINDOW",
                    409,
                    "collected_at outside the 5-day collection window",
                )
            if enr["status"] != "ACTIVE":
                raise ApiError("ERR_ENROLLMENT_INACTIVE", 409, "enrollment is not ACTIVE")
            # temporal: submission deadline
            if store.now() > ship["_due_dt"]:
                raise ApiError(
                    "ERR_SUBMISSION_DEADLINE_PASSED", 409, "submission deadline has passed"
                )
            # referential: analyte coverage
            scores = data["analyte_scores"]
            if not isinstance(scores, list) or not scores:
                raise ApiError("ERR_INVALID_REQUEST", 400, "analyte_scores must be a non-empty array")
            score_map = {}
            for entry in scores:
                if not isinstance(entry, dict):
                    raise ApiError("ERR_INVALID_REQUEST", 400, "each analyte score must be an object")
                name = entry.get("name")
                sc = entry.get("score")
                if not isinstance(name, str):
                    raise ApiError("ERR_INVALID_REQUEST", 400, "analyte score name must be a string")
                if not is_num(sc) or sc < 0 or sc > 100:
                    raise ApiError(
                        "ERR_INVALID_REQUEST", 400, "analyte score must be a number in 0..100"
                    )
                if name in score_map:
                    raise ApiError("ERR_INVALID_REQUEST", 400, "duplicate analyte score name")
                score_map[name] = sc
            sub_names = {a["name"] for a in sub["analytes"]}
            if set(score_map.keys()) != sub_names:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    "analyte_scores must cover exactly the subscription's analyte names",
                )
            # grading
            total = len(sub["analytes"])
            passed = sum(1 for a in sub["analytes"] if score_map[a["name"]] >= 80)
            event_score = float(
                (Decimal(100) * Decimal(passed) / Decimal(total)).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
            )
            critical_failed = any(
                a["critical"] and score_map[a["name"]] < 80 for a in sub["analytes"]
            )
            evaluation = (
                "UNSATISFACTORY" if (event_score < 80.0 or critical_failed) else "SATISFACTORY"
            )
            rec = new_record(
                {
                    "shipment_id": ship["id"],
                    "collected_at": fmt_instant(collected),
                    "analyte_scores": [{"name": k, "score": v} for k, v in score_map.items()],
                    "event_score": event_score,
                    "event_evaluation": evaluation,
                    "status": "GRADED",
                }
            )
            rec["_collected_dt"] = collected
            store.STORES["pt_results"][rec["id"]] = rec
            # standing recomputation + possible investigation
            services.recompute_standing(enr)
            services.touch(enr)
            inv = services.maybe_open_investigation(enr, rec["id"])
            if inv is not None:
                inv_rec = new_record(inv)
                store.STORES["pt_investigations"][inv_rec["id"]] = inv_rec
        return success(public(rec), status=201)

    @app.route("/pt-results", methods=["GET"])
    def list_pt_results():
        require_auth(ALL_READERS)
        items = list(store.STORES["pt_results"].values())
        ship = request.args.get("shipment_id")
        if ship is not None:
            items = [r for r in items if r["shipment_id"] == ship]
        return list_response(items)

    @app.route("/pt-results/<resultId>", methods=["GET"])
    def get_pt_result(resultId):
        require_auth(ALL_READERS)
        rec = get_or_404("pt_results", resultId, "ERR_RESULT_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/pt-results/<resultId>/void", methods=["POST"])
    def void_pt_result(resultId):
        require_auth(["PTCoordinator"])
        with store.lock():
            rec = get_or_404("pt_results", resultId, "ERR_RESULT_NOT_FOUND")
            if rec["status"] == "GRADED":
                raise ApiError("ERR_RESULT_ALREADY_GRADED", 409, "result already graded")
            if rec["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", 409, "result is not SUBMITTED")
            rec["status"] = "VOID"
            services.touch(rec)
        return success(public(rec), status=200)

    # ---------------- investigations ----------------

    @app.route("/pt-investigations", methods=["GET"])
    def list_pt_investigations():
        require_auth(ALL_READERS)
        items = list(store.STORES["pt_investigations"].values())
        enr = request.args.get("enrollment_id")
        if enr is not None:
            items = [i for i in items if i["enrollment_id"] == enr]
        return list_response(items)

    @app.route("/pt-investigations/<investigationId>", methods=["GET"])
    def get_pt_investigation(investigationId):
        require_auth(ALL_READERS)
        rec = get_or_404("pt_investigations", investigationId, "ERR_INVESTIGATION_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/pt-investigations/<investigationId>/begin-review", methods=["POST"])
    def begin_review(investigationId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            rec = get_or_404("pt_investigations", investigationId, "ERR_INVESTIGATION_NOT_FOUND")
            if rec["status"] != "OPEN":
                raise ApiError(
                    "ERR_INVALID_INVESTIGATION_STATE", 409, "investigation is not OPEN"
                )
            rec["status"] = "UNDER_REVIEW"
            services.touch(rec)
        return success(public(rec), status=200)

    @app.route(
        "/pt-investigations/<investigationId>/require-corrective-action", methods=["POST"]
    )
    def require_corrective_action(investigationId):
        require_auth(["AccreditationOfficer"])
        data = body()
        with store.lock():
            rec = get_or_404("pt_investigations", investigationId, "ERR_INVESTIGATION_NOT_FOUND")
            if rec["status"] != "UNDER_REVIEW":
                raise ApiError(
                    "ERR_INVALID_INVESTIGATION_STATE", 409, "investigation is not UNDER_REVIEW"
                )
            notes = data.get("corrective_action_notes")
            if not isinstance(notes, str) or not notes.strip():
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "corrective_action_notes must be non-empty"
                )
            rec["status"] = "CORRECTIVE_ACTION_REQUIRED"
            rec["corrective_action_notes"] = notes
            services.touch(rec)
            enr = store.STORES["enrollments"].get(rec["enrollment_id"])
            if enr and enr["status"] == "ACTIVE":
                services.set_enrollment_status(enr, "SUSPENDED")
        return success(public(rec), status=200)

    @app.route("/pt-investigations/<investigationId>/resolve", methods=["POST"])
    def resolve_investigation(investigationId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            rec = get_or_404("pt_investigations", investigationId, "ERR_INVESTIGATION_NOT_FOUND")
            if rec["status"] not in ("OPEN", "UNDER_REVIEW", "CORRECTIVE_ACTION_REQUIRED"):
                raise ApiError(
                    "ERR_INVALID_INVESTIGATION_STATE",
                    409,
                    "investigation cannot be resolved from its current state",
                )
            from_state = rec["status"]
            rec["status"] = "RESOLVED"
            services.touch(rec)
            enr = store.STORES["enrollments"].get(rec["enrollment_id"])
            if enr:
                if enr["unsuccessful_event_streak"] != 0:
                    enr["unsuccessful_event_streak"] = 0
                    services.touch(enr)
                if from_state == "CORRECTIVE_ACTION_REQUIRED" and enr["status"] == "SUSPENDED":
                    services.set_enrollment_status(enr, "ACTIVE")
        return success(public(rec), status=200)

    @app.route("/pt-investigations/<investigationId>/cease-testing", methods=["POST"])
    def cease_testing(investigationId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            rec = get_or_404("pt_investigations", investigationId, "ERR_INVESTIGATION_NOT_FOUND")
            if rec["status"] not in ("OPEN", "UNDER_REVIEW"):
                raise ApiError(
                    "ERR_INVALID_INVESTIGATION_STATE",
                    409,
                    "cease-testing requires OPEN or UNDER_REVIEW",
                )
            enr = get_or_404("enrollments", rec["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
            if enr["standing_rolling"] != "UNSATISFACTORY":
                raise ApiError(
                    "ERR_CESSATION_REQUIRES_ROLLING_UNSATISFACTORY",
                    409,
                    "standing_rolling is not UNSATISFACTORY",
                )
            rec["status"] = "TESTING_CEASED"
            services.touch(rec)
            if enr["status"] in ("ACTIVE", "SUSPENDED"):
                services.set_enrollment_status(enr, "CEASED")
        return success(public(rec), status=200)
