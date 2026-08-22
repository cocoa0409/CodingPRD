"""Exemption claims: filing, opposition and the ruling fork (PRD 3.6)."""

from flask import request

from auth import check_judgment_ownership
from domain import (
    EXEMPTION_RESPONSE_DAYS,
    OPPOSITION_RESPONSE_DAYS,
    add_days,
    by_seq,
    get_action,
    get_claim,
    guard_judgment_alive,
    invalid_state,
    judgment_of_claim,
    quash_action,
    to_date,
)
from errors import ApiError
from store import bump, new_row, store
from validators import (
    ENUM_CLAIM_OUTCOME,
    ENUM_CLAIM_TYPE,
    check_enum,
    json_body,
    pagination,
    positive,
    present,
    require_int,
    require_string,
)
from web import endpoint, make_list

from .helpers import apply_filter, scope, serialize

READ_ROLES = ("CaseManager", "EnforcementOfficer", "ComplianceOfficer", "Debtor")


def _judgment_for_claim(claim):
    action = store.enforcement_actions.get(claim["enforcement_action_id"])
    return store.judgments.get(action["judgment_id"]) if action else None


def register(app):
    # ---- POST /exemption-claims ------------------------------------------
    @endpoint(app, "/exemption-claims", "POST", ("Debtor",), 201)
    def create_claim(ctx):
        body = json_body()
        action = None
        if present(body, "enforcement_action_id"):
            action = get_action(body.get("enforcement_action_id"))
            check_judgment_ownership(ctx, store.judgments.get(action["judgment_id"]))
        enforcement_action_id = require_string(body, "enforcement_action_id")
        require_string(body, "claim_type")
        claimed_amount = require_int(body, "claimed_amount_cents")
        claim_type = check_enum(body, "claim_type", ENUM_CLAIM_TYPE)
        positive(claimed_amount, "claimed_amount_cents")

        if action["served_on"] is None:
            invalid_state("An exemption claim may only be filed against a served writ.")
        judgment = store.judgments.get(action["judgment_id"])
        guard_judgment_alive(judgment)

        filed_on = store.clock_date()
        served_on = to_date(action["served_on"])
        filing_deadline = add_days(served_on, EXEMPTION_RESPONSE_DAYS)
        # rung 21 - the window is inclusive on both ends
        if filed_on < served_on or filed_on > filing_deadline:
            raise ApiError("ERR_EXEMPTION_WINDOW_CLOSED", "The exemption filing window is closed.")

        row = new_row({
            "enforcement_action_id": enforcement_action_id,
            "claim_type": claim_type,
            "claimed_amount_cents": claimed_amount,
            "filed_on": filed_on.isoformat(),
            "filing_deadline_on": filing_deadline.isoformat(),
            "opposition_deadline_on": add_days(filed_on, OPPOSITION_RESPONSE_DAYS).isoformat(),
            "opposed_on": None,
            "opposed_by_user_id": None,
            "ruled_by_user_id": None,
            "status": "FILED",
        })
        store.exemption_claims[row["id"]] = row
        return serialize(row)

    # ---- GET /exemption-claims -------------------------------------------
    @endpoint(app, "/exemption-claims", "GET", READ_ROLES, 200)
    def list_claims(ctx):
        limit, offset = pagination(request.args)
        rows = by_seq(list(store.exemption_claims.values()))
        rows = apply_filter(rows, request.args, "enforcement_action_id")
        rows = apply_filter(rows, request.args, "status")
        rows = scope(ctx, rows, _judgment_for_claim)
        return make_list(rows, limit, offset, serialize)

    # ---- GET /exemption-claims/{exemption_claim_id} ----------------------
    @endpoint(app, "/exemption-claims/<exemption_claim_id>", "GET", READ_ROLES, 200)
    def read_claim(ctx, exemption_claim_id):
        claim = get_claim(exemption_claim_id)
        check_judgment_ownership(ctx, _judgment_for_claim(claim))
        return serialize(claim)

    # ---- POST /exemption-claims/{id}/oppose ------------------------------
    @endpoint(app, "/exemption-claims/<exemption_claim_id>/oppose", "POST",
              ("EnforcementOfficer",), 200)
    def oppose_claim(ctx, exemption_claim_id):
        claim = get_claim(exemption_claim_id)
        action = store.enforcement_actions.get(claim["enforcement_action_id"])
        if claim["status"] != "FILED":
            invalid_state("Only a FILED exemption claim may be opposed.")
        if action is None or action["status"] not in ("SERVED", "SUSPENDED"):
            invalid_state("The linked enforcement action is not live.")
        judgment = store.judgments.get(action["judgment_id"])
        guard_judgment_alive(judgment)
        claim["status"] = "OPPOSED"
        claim["opposed_on"] = store.clock_date().isoformat()
        claim["opposed_by_user_id"] = ctx.user_id
        bump(claim)
        return serialize(claim)

    # ---- POST /exemption-claims/{id}/rule --------------------------------
    @endpoint(app, "/exemption-claims/<exemption_claim_id>/rule", "POST",
              ("ComplianceOfficer",), 200)
    def rule_claim(ctx, exemption_claim_id):
        claim = get_claim(exemption_claim_id)
        body = json_body()
        require_string(body, "outcome")
        outcome = check_enum(body, "outcome", ENUM_CLAIM_OUTCOME)
        if claim["status"] != "OPPOSED":
            invalid_state("Only an OPPOSED exemption claim may be ruled on.")
        judgment = judgment_of_claim(claim)
        guard_judgment_alive(judgment)
        # rung 18 - segregation of duties, keyed on X-User-ID
        opposer = claim.get("opposed_by_user_id")
        if opposer and ctx.user_id and opposer == ctx.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The officer who opposed the claim may not rule on it.")

        claim["ruled_by_user_id"] = ctx.user_id
        claim["status"] = outcome
        bump(claim)
        if outcome == "SUSTAINED":
            action = store.enforcement_actions.get(claim["enforcement_action_id"])
            if action is not None:
                quash_action(action, claim)
        return serialize(claim)
