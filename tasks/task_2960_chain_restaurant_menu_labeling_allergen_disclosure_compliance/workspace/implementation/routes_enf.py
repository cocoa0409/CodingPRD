"""Variance requests and enforcement files."""

import calc
import domain as D
from core import (CLOCK, ROLE_BRAND_OFFICER, ROLE_REGULATOR, S, authenticate,
                  body_or_empty, envelope, fail, fmt_date, get_body, insert, mark,
                  not_found, parse_date, require_scope, rows)
from validate import (opt_date, opt_enum, opt_string, peek_id, req_date, req_enum,
                      req_id, req_string)


def register(app):

    # -------------------------------------------------------------- variances
    @app.post("/variance-requests")
    def file_variance():
        authenticate([ROLE_BRAND_OFFICER])
        require_scope(peek_id(body_or_empty(), "brand_id"))
        body = get_body()
        brand_id = req_id(body, "brand_id")
        jurisdiction_id = req_id(body, "jurisdiction_id")
        requirement_code = req_enum(body, "requirement_code", D.REQUIREMENT_CODES)
        justification = req_string(body, "justification", 1, 400)
        requested_start = req_date(body, "requested_start_date")
        requested_end = req_date(body, "requested_end_date")
        brand = S.brands.get(brand_id)
        if brand is None:
            not_found("brand")
        jurisdiction = S.jurisdictions.get(jurisdiction_id)
        if jurisdiction is None:
            not_found("jurisdiction")
        if requested_start > requested_end:
            fail("ERR_INVALID_DATE_RANGE",
                 "requested_start_date must not fall after requested_end_date")
        variance = insert(S.variances, {
            "brand_id": brand_id,
            "jurisdiction_id": jurisdiction_id,
            "requirement_code": requirement_code,
            "justification": justification,
            "requested_start_date": fmt_date(requested_start),
            "requested_end_date": fmt_date(requested_end),
            "status": "SUBMITTED",
            "effective_start_date": None,
            "effective_end_date": None,
            "decision_note": None,
            "decided_by_user_id": None,
        })
        return envelope(D.variance_out(variance), 201)

    @app.post("/variance-requests/<variance_id>/decision")
    def decide_variance(variance_id):
        user_id, _role = authenticate([ROLE_REGULATOR])
        variance = S.variances.get(variance_id)
        if variance is not None:
            require_scope(variance["jurisdiction_id"])
        body = get_body()
        decision = req_enum(body, "decision", ("OPEN_REVIEW", "GRANTED", "DENIED"))
        note = opt_string(body, "decision_note", 0, 400, non_blank=False)
        supplied_start = opt_date(body, "effective_start_date")
        supplied_end = opt_date(body, "effective_end_date")
        if variance is None:
            not_found("variance")
        if variance["status"] in ("DENIED", "EXPIRED"):
            fail("ERR_ALREADY_TERMINAL", "variance request is in a terminal state")
        if decision == "OPEN_REVIEW":
            if variance["status"] != "SUBMITTED":
                fail("ERR_VARIANCE_STATE_INVALID", "OPEN_REVIEW is defined only from SUBMITTED")
        else:
            if variance["status"] != "UNDER_REVIEW":
                fail("ERR_VARIANCE_STATE_INVALID",
                     "%s is defined only from UNDER_REVIEW" % decision)
        if supplied_start is not None and supplied_end is not None and supplied_start > supplied_end:
            fail("ERR_INVALID_DATE_RANGE",
                 "effective_start_date must not fall after effective_end_date")
        effective_start = None
        effective_end = None
        if decision == "GRANTED":
            effective_start = supplied_start or parse_date(variance["requested_start_date"])
            effective_end = supplied_end or parse_date(variance["requested_end_date"])
            if effective_start > effective_end:
                fail("ERR_INVALID_DATE_RANGE",
                     "effective_start_date must not fall after effective_end_date")
            jurisdiction = S.jurisdictions[variance["jurisdiction_id"]]
            if jurisdiction["preemption_mode"] != "VARIANCE_ALLOWED":
                fail("ERR_VARIANCE_NOT_ALLOWED",
                     "the authority preempts local variances")
            for other in rows(S.variances):
                if other["id"] == variance_id or other["status"] != "GRANTED":
                    continue
                if (other["brand_id"] != variance["brand_id"]
                        or other["jurisdiction_id"] != variance["jurisdiction_id"]
                        or other["requirement_code"] != variance["requirement_code"]):
                    continue
                other_end = parse_date(other["effective_end_date"])
                if other_end is None:
                    continue
                if (effective_start - other_end).days <= calc.VARIANCE_COOLING_DAYS:
                    fail("ERR_VARIANCE_WINDOW_CONFLICT",
                         "the grant falls inside the cooling buffer of an existing grant")
        mark(variance)
        variance["decided_by_user_id"] = user_id
        variance["decision_note"] = note
        if decision == "OPEN_REVIEW":
            variance["status"] = "UNDER_REVIEW"
        elif decision == "DENIED":
            variance["status"] = "DENIED"
        else:
            variance["status"] = "GRANTED"
            variance["effective_start_date"] = fmt_date(effective_start)
            variance["effective_end_date"] = fmt_date(effective_end)
        return envelope(D.variance_out(variance), 200)

    # ------------------------------------------------------------ enforcement
    @app.post("/enforcement-actions")
    def open_citation():
        user_id, _role = authenticate([ROLE_REGULATOR])
        peeked = S.establishments.get(peek_id(body_or_empty(), "establishment_id") or "")
        if peeked is not None:
            require_scope(peeked["jurisdiction_id"])
        body = get_body()
        establishment_id = req_id(body, "establishment_id")
        citation_code = req_enum(body, "citation_code", D.CITATION_CODES)
        note = opt_string(body, "inspection_note", 0, 400, non_blank=False)
        establishment = S.establishments.get(establishment_id)
        if establishment is None:
            not_found("establishment")
        action = insert(S.enforcements, {
            "establishment_id": establishment_id,
            "jurisdiction_id": establishment["jurisdiction_id"],
            "citation_code": citation_code,
            "inspection_note": note,
            "status": "OPEN",
            "info_round_count": 0,
            "response_count": 0,
            "last_response_type": None,
            "penalty_basis": None,
            "violation_unit_count": None,
            "base_penalty_cents": None,
            "admin_fee_cents": None,
            "penalty_total_cents": 0,
            "opened_at": CLOCK.iso(),
            "closed_at": None,
        })
        return envelope(D.enforcement_out(action), 201)

    @app.post("/enforcement-actions/<action_id>/responses")
    def respond_to_citation(action_id):
        authenticate([ROLE_BRAND_OFFICER])
        action = S.enforcements.get(action_id)
        establishment = None
        if action is not None:
            establishment = S.establishments.get(action["establishment_id"])
            if establishment is not None:
                require_scope(establishment["brand_id"])
        body = get_body()
        response_type = req_enum(body, "response_type", D.RESPONSE_TYPES)
        opt_string(body, "response_note", 0, 400, non_blank=False)
        if action is None:
            not_found("enforcement")
        if action["status"] in ("CLOSED_COMPLIANT", "CLOSED_PENALTY"):
            fail("ERR_ALREADY_TERMINAL", "enforcement file is closed")
        if action["status"] not in ("OPEN", "INFO_REQUESTED"):
            fail("ERR_ACTION_STATE_INVALID",
                 "a response is defined only from OPEN or INFO_REQUESTED")
        brand = S.brands[establishment["brand_id"]]
        has_published = any(p["status"] == "PUBLISHED" for p in D.brand_packets(brand["id"]))
        if not has_published:
            fail("ERR_NO_PUBLISHED_PACKET", "brand has no PUBLISHED disclosure packet")
        if response_type == "REPRINT_COMPLETED" and establishment["outstanding_penalty_cents"] != 0:
            fail("ERR_OUTSTANDING_PENALTY", "the unit carries an outstanding penalty")
        mark(action)
        action["status"] = "RESPONSE_SUBMITTED"
        action["response_count"] = action["response_count"] + 1
        action["last_response_type"] = response_type
        return envelope(D.enforcement_out(action), 200)

    @app.post("/enforcement-actions/<action_id>/regulator-actions")
    def regulator_action(action_id):
        user_id, _role = authenticate([ROLE_REGULATOR])
        action = S.enforcements.get(action_id)
        if action is not None:
            require_scope(action["jurisdiction_id"])
        body = get_body()
        action_type = req_enum(body, "action_type", D.ACTION_TYPES)
        penalty_basis = opt_enum(body, "penalty_basis", D.PENALTY_BASES)
        opt_string(body, "action_note", 0, 400, non_blank=False)
        if action_type == "ASSESS_PENALTY" and penalty_basis is None:
            fail("ERR_VALIDATION", "penalty_basis is required for ASSESS_PENALTY")
        if action is None:
            not_found("enforcement")
        if action["status"] in ("CLOSED_COMPLIANT", "CLOSED_PENALTY"):
            fail("ERR_ALREADY_TERMINAL", "enforcement file is closed")
        status = action["status"]
        if action_type in ("REQUEST_INFO", "ESCALATE", "CLOSE_COMPLIANT"):
            if status != "RESPONSE_SUBMITTED":
                fail("ERR_ACTION_STATE_INVALID",
                     "%s is defined only from RESPONSE_SUBMITTED" % action_type)
        elif action_type == "ASSESS_PENALTY":
            if status != "ESCALATED":
                fail("ERR_ACTION_STATE_INVALID", "ASSESS_PENALTY is defined only from ESCALATED")
        else:
            if status != "PENALTY_ASSESSED":
                fail("ERR_ACTION_STATE_INVALID",
                     "%s is defined only from PENALTY_ASSESSED" % action_type)
        if action_type == "CLOSE_COMPLIANT":
            if action["last_response_type"] not in ("REPRINT_COMPLETED", "VARIANCE_CITED"):
                fail("ERR_ACTION_STATE_INVALID",
                     "CLOSE_COMPLIANT requires a REPRINT_COMPLETED or VARIANCE_CITED response")
        establishment = S.establishments[action["establishment_id"]]
        jurisdiction = S.jurisdictions[action["jurisdiction_id"]]
        brand = S.brands[establishment["brand_id"]]
        if action_type == "ESCALATE":
            if action["info_round_count"] < 1:
                fail("ERR_INFO_ROUND_REQUIRED", "at least one information round is required")
            requirement = D.CITATION_REQUIREMENT.get(action["citation_code"])
            if D.granted_variance_covers(brand["id"], jurisdiction["id"], requirement,
                                         CLOCK.today()):
                fail("ERR_CITATION_SHIELDED_BY_VARIANCE",
                     "a granted variance shields this citation")
        mark(action)
        if action_type == "REQUEST_INFO":
            action["status"] = "INFO_REQUESTED"
            action["info_round_count"] = action["info_round_count"] + 1
        elif action_type == "CLOSE_COMPLIANT":
            action["status"] = "CLOSED_COMPLIANT"
            action["closed_at"] = CLOCK.iso()
        elif action_type == "ESCALATE":
            action["status"] = "ESCALATED"
            D.recompute_obligation_counters(brand)
        elif action_type == "ASSESS_PENALTY":
            if penalty_basis == "PER_BOARD":
                units = len([
                    b for b in D.est_boards(establishment["id"])
                    if b["publication_status"] == "PUBLISHED"
                    and b["calorie_compliance_status"] in D.OPEN_REPRINT_STATUSES
                ])
            else:
                units = 1
            base, fee, total = calc.penalty_amounts(units, jurisdiction["enforcement_tier"])
            action["penalty_basis"] = penalty_basis
            action["violation_unit_count"] = units
            action["base_penalty_cents"] = base
            action["admin_fee_cents"] = fee
            action["penalty_total_cents"] = total
            action["status"] = "PENALTY_ASSESSED"
            D.recompute_est_penalty(establishment)
            D.recompute_jurisdiction_penalty(jurisdiction)
            D.recompute_obligation_counters(brand)
        elif action_type == "RESCIND_PENALTY":
            action["penalty_basis"] = None
            action["violation_unit_count"] = None
            action["base_penalty_cents"] = None
            action["admin_fee_cents"] = None
            action["penalty_total_cents"] = 0
            action["status"] = "RESPONSE_SUBMITTED"
            D.recompute_est_penalty(establishment)
            D.recompute_jurisdiction_penalty(jurisdiction)
            D.recompute_obligation_counters(brand)
        else:  # CLOSE_PENALTY
            action["status"] = "CLOSED_PENALTY"
            action["closed_at"] = CLOCK.iso()
            D.recompute_est_penalty(establishment)
            D.recompute_jurisdiction_penalty(jurisdiction)
        return envelope(D.enforcement_out(action), 200)
