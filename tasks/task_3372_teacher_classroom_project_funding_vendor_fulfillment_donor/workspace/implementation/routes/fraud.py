"""Fraud cases: reads and resolution (CONFIRMED fires the clawback cascade)."""
from flask import request

import store
from envelope import ok, page_payload
from errors import invalid_state, not_found
from security import actor, require_roles
from serializers import fraud_case_json
from services import fraud as fraud_service
from validators import as_enum, json_body, pagination_args, require_present

READ_ROLES = ("PlatformAdmin", "Reviewer")


def register(app):
    @app.route("/giving/fraud-cases/<case_id>", methods=["GET"])
    def get_case(case_id):
        _, role = actor()
        require_roles(role, READ_ROLES)
        case = store.fraud_cases.get(case_id)
        if case is None:
            raise not_found("Fraud case not found")
        return ok(fraud_case_json(case), 200)

    @app.route("/giving/fraud-cases", methods=["GET"])
    def list_cases():
        _, role = actor()
        require_roles(role, READ_ROLES)
        teacher_id = request.args.get("teacher_id")
        project_id = request.args.get("project_id")
        purchase_order_id = request.args.get("purchase_order_id")
        status = request.args.get("status")
        rows = list(store.fraud_cases.values())
        if teacher_id is not None:
            rows = [c for c in rows if c["teacher_id"] == teacher_id]
        if project_id is not None:
            rows = [c for c in rows if c["project_id"] == project_id]
        if purchase_order_id is not None:
            rows = [c for c in rows if c["purchase_order_id"] == purchase_order_id]
        if status is not None:
            rows = [c for c in rows if c["status"] == status]
        rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
        limit, offset = pagination_args()
        page, meta = page_payload([fraud_case_json(c) for c in rows], limit, offset)
        return ok(page, 200, pagination=meta)

    @app.route("/giving/fraud-cases/<case_id>/resolve", methods=["POST"])
    def resolve_case(case_id):
        data = json_body()
        outcome = as_enum(
            require_present(data, "outcome"), "outcome", ("CONFIRMED", "DISMISSED")
        )
        _, role = actor()
        require_roles(role, ("PlatformAdmin",))
        case = store.fraud_cases.get(case_id)
        if case is None:
            raise not_found("Fraud case not found")
        if case["status"] != "OPEN":
            raise invalid_state("Only an OPEN fraud case can be resolved")
        if outcome == "DISMISSED":
            case["status"] = "DISMISSED"
            store.touch(case)
            return ok(fraud_case_json(case), 200)
        case["status"] = "CONFIRMED"
        store.touch(case)
        fraud_service.confirm_fraud_case(case, store.logical_now())
        return ok(fraud_case_json(case), 200)
