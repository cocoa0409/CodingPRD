"""Designations, claim preparation and the evidence file (PRD 3.4, 3.5, 3.6)."""

from flask import Blueprint, g

import calc
from errors import ApiError
from envelope import list_response, object_response
from guard import (
    authorize, check_shape, filter_rows, invalid_transition, lookup, need_claim,
    need_evidence, need_poa, need_representative, need_veteran, page_of,
    run_checks,
)
from store import bump, d, db, new_row, now_date, now_instant, ordered, \
    parse_date
from views import view, view_all

bp = Blueprint("claims", __name__, url_prefix="/cvso")

FRONT_DESK = ("CountyOfficer", "IntakeClerk")
READ_POA = ("IntakeClerk", "CountyOfficer", "StateAuditor", "SystemAdmin",
            "VeteranClient")
READ_CLAIMS = ("CountyOfficer", "IntakeClerk", "StateAuditor", "SystemAdmin",
               "VeteranClient")
READ_EVIDENCE_FILE = ("CountyOfficer", "StateAuditor", "SystemAdmin",
                      "VeteranClient")
READ_EVIDENCE = ("CountyOfficer", "StateAuditor", "SystemAdmin")


# --------------------------------------------------------------------------
# powers of attorney
# --------------------------------------------------------------------------

@bp.post("/powers-of-attorney")
def offer_designation():
    authorize(FRONT_DESK)
    body = check_shape({
        "required": ["veteran_id", "representative_id", "form_type", "scope",
                     "executed_on"],
    })
    veteran = need_veteran(body["veteran_id"])
    need_representative(body["representative_id"])

    def alive():
        if veteran["intake_status"] == "DECEASED":
            raise ApiError("ERR_VETERAN_DECEASED",
                           "the veteran's case is closed to new work")

    run_checks([(41, alive)])
    row = new_row()
    row["_kind"] = "power_of_attorney"
    row["veteran_id"] = body["veteran_id"]
    row["representative_id"] = body["representative_id"]
    row["form_type"] = body["form_type"]
    row["scope"] = body["scope"]
    row["executed_on"] = body["executed_on"]
    row["status"] = "OFFERED"
    row["accepted_at"] = None
    row["revoked_reason"] = None
    db.powers_of_attorney[row["id"]] = row
    return object_response(view(row), 201)


@bp.get("/powers-of-attorney")
def list_designations():
    authorize(READ_POA)
    run_checks()
    rows = filter_rows(ordered(db.powers_of_attorney.values()), {
        "veteran_id": "veteran_id",
        "representative_id": "representative_id",
        "status": "status",
        "form_type": "form_type",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/powers-of-attorney/<row_id>")
def read_designation(row_id):
    authorize(READ_POA)
    row = need_poa(row_id)
    run_checks()
    return object_response(view(row))


@bp.post("/powers-of-attorney/<row_id>/accept")
def accept_designation(row_id):
    def owner():
        poa = db.powers_of_attorney.get(row_id)
        return None if poa is None else poa["veteran_id"]

    authorize(("VeteranClient",), owner)
    body = check_shape({
        "required": ["expected_veteran_version"],
        "occ": "expected_veteran_version",
    })
    poa = need_poa(row_id)
    veteran = db.veterans.get(poa["veteran_id"])

    def from_state():
        if poa["status"] != "OFFERED":
            invalid_transition("acceptance is not available from %s"
                               % (poa["status"],))

    def alive():
        if veteran is not None and veteran["intake_status"] == "DECEASED":
            raise ApiError("ERR_VETERAN_DECEASED",
                           "the veteran's case is closed to new work")

    def fresh():
        if veteran is None or veteran["version"] != body["expected_veteran_version"]:
            raise ApiError("ERR_STALE_VETERAN_VERSION",
                           "expected_veteran_version does not match the"
                           " veteran's current version")

    rep = db.representatives.get(poa["representative_id"])

    def accredited():
        if rep is None or rep["accreditation_status"] != "ACTIVE":
            raise ApiError("ERR_REPRESENTATIVE_NOT_ACCREDITED",
                           "the designated representative is not accredited")

    def ceiling():
        if rep["active_poa_count"] >= calc.MAX_POA_PER_REPRESENTATIVE:
            raise ApiError("ERR_REPRESENTATIVE_CASELOAD_FULL",
                           "the representative holds the maximum designations")

    run_checks([(40, from_state), (41, alive), (45, fresh), (45.5, accredited),
                (69, ceiling)])

    poa["status"] = "ACTIVE"
    poa["accepted_at"] = now_instant()
    bump(poa)
    superseded = []
    for other in ordered(db.powers_of_attorney.values()):
        if other["id"] == poa["id"] or other["veteran_id"] != poa["veteran_id"]:
            continue
        if other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            bump(other)
            superseded.append(other)
    bump(veteran)
    calc.refresh_caseload(rep)
    for other in superseded:
        loser = db.representatives.get(other["representative_id"])
        if loser is not None and loser["id"] != rep["id"]:
            calc.refresh_caseload(loser)
    return object_response(view(poa))


@bp.post("/powers-of-attorney/<row_id>/revoke")
def revoke_designation(row_id):
    def owner():
        poa = db.powers_of_attorney.get(row_id)
        return None if poa is None else poa["veteran_id"]

    authorize(("VeteranClient", "CountyOfficer"), owner)
    body = check_shape({"required": ["reason"]})
    poa = need_poa(row_id)

    def from_state():
        if poa["status"] not in ("OFFERED", "ACTIVE"):
            invalid_transition("revocation is not available from %s"
                               % (poa["status"],))

    run_checks([(40, from_state)])
    was_active = poa["status"] == "ACTIVE"
    poa["status"] = "REVOKED"
    poa["revoked_reason"] = body["reason"]
    bump(poa)
    if not was_active:
        return object_response(view(poa))

    touched_preparers = set()
    reverted_ids = set()
    for claim in ordered(db.claims.values()):
        if claim.get("poa_id") != poa["id"]:
            continue
        touched_preparers.add(claim.get("prepared_by_representative_id"))
        if claim["status"] in ("EVIDENCE_DEVELOPMENT", "PEER_REVIEW",
                              "READY_TO_FILE"):
            claim["status"] = "DRAFT"
            claim["poa_id"] = None
            claim["peer_reviewed_by_representative_id"] = None
            bump(claim)
            reverted_ids.add(claim["id"])
        elif claim["status"] == "DRAFT":
            claim["poa_id"] = None
            bump(claim)

    released = {}
    for appointment in ordered(db.exam_appointments.values()):
        if appointment["claim_id"] in reverted_ids \
                and appointment["status"] == "SCHEDULED":
            appointment["status"] = "CANCELLED"
            appointment["cancellation_reason"] = "REPRESENTATION_CASCADE"
            bump(appointment)
            released[appointment["exam_site_id"]] = \
                released.get(appointment["exam_site_id"], 0) + 1
    for site_id, count in released.items():
        site = db.exam_sites.get(site_id)
        if site is None:
            continue
        site["booked_slot_count"] = site["booked_slot_count"] - count
        bump(site)

    calc.refresh_caseload(db.representatives.get(poa["representative_id"]))
    for rep_id in touched_preparers:
        if rep_id != poa["representative_id"]:
            calc.refresh_caseload(db.representatives.get(rep_id))
    return object_response(view(poa))


# --------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------

def _check_intent_to_file(claim_or_body, veteran):
    itf = claim_or_body.get("intent_to_file_date")
    if itf is None:
        return
    value = parse_date(itf)
    if value > now_date():
        raise ApiError("ERR_INTENT_TO_FILE_DATE_INVALID",
                       "intent_to_file_date is later than the logical-clock"
                       " date")
    if veteran is not None and value < d(veteran["service_end_date"]):
        raise ApiError("ERR_INTENT_TO_FILE_DATE_INVALID",
                       "intent_to_file_date precedes the veteran's"
                       " service_end_date")


@bp.post("/claims")
def open_claim():
    authorize(("CountyOfficer",))
    body = check_shape({
        "required": ["veteran_id", "poa_id", "claim_type", "claimed_conditions"],
        "optional": ["intent_to_file_date"],
        "claimed_conditions": True,
    })
    veteran = need_veteran(body["veteran_id"])
    poa = need_poa(body["poa_id"])

    def alive():
        if veteran["intake_status"] == "DECEASED":
            raise ApiError("ERR_VETERAN_DECEASED",
                           "the veteran's case is closed to new work")

    def verified():
        if veteran["discharge_doc_status"] != "VERIFIED":
            raise ApiError("ERR_DISCHARGE_NOT_VERIFIED",
                           "the veteran has no verified discharge document")

    def poa_active():
        if poa["status"] != "ACTIVE":
            raise ApiError("ERR_POA_NOT_ACTIVE",
                           "the cited designation is not ACTIVE")

    def itf():
        _check_intent_to_file(body, veteran)

    def same_veteran():
        if poa["veteran_id"] != body["veteran_id"]:
            raise ApiError("ERR_POA_VETERAN_MISMATCH",
                           "the designation belongs to another veteran")

    run_checks([(41, alive), (43, verified), (44, poa_active), (58, itf),
                (60, same_veteran)])

    row = new_row()
    row["_kind"] = "claim"
    row["veteran_id"] = body["veteran_id"]
    row["poa_id"] = body["poa_id"]
    row["prepared_by_representative_id"] = g.user_id
    row["peer_reviewed_by_representative_id"] = None
    row["claim_type"] = body["claim_type"]
    row["claimed_conditions"] = body["claimed_conditions"]
    row["status"] = "DRAFT"
    row["intent_to_file_date"] = body.get("intent_to_file_date")
    row["evidence_completeness_pct"] = 0.00
    row["rework_count"] = 0
    row["reopen_count"] = 0
    row["filed_on"] = None
    row["effective_date"] = None
    row["effective_date_basis"] = None
    row["decided_on"] = None
    row["decision_outcome"] = None
    row["awarded_rating_pct"] = 0
    row["retro_award_cents"] = 0
    row["withdrawal_reason"] = None
    db.claims[row["id"]] = row
    return object_response(view(row), 201)


@bp.get("/claims")
def list_claims():
    authorize(READ_CLAIMS)
    run_checks()
    rows = filter_rows(ordered(db.claims.values()), {
        "veteran_id": "veteran_id",
        "poa_id": "poa_id",
        "prepared_by_representative_id": "prepared_by_representative_id",
        "peer_reviewed_by_representative_id": "peer_reviewed_by_representative_id",
        "status": "status",
        "claim_type": "claim_type",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/claims/<row_id>")
def read_claim(row_id):
    authorize(READ_CLAIMS)
    row = need_claim(row_id)
    run_checks()
    return object_response(view(row))


@bp.patch("/claims/<row_id>")
def amend_claim(row_id):
    authorize(("CountyOfficer",))
    body = check_shape({
        "optional": ["claimed_conditions", "intent_to_file_date"],
        "claimed_conditions": True,
    })
    claim = need_claim(row_id)

    def from_state():
        if claim["status"] not in ("DRAFT", "EVIDENCE_DEVELOPMENT"):
            invalid_transition("an amendment is not available from %s"
                               % (claim["status"],))

    def itf():
        _check_intent_to_file(body, db.veterans.get(claim["veteran_id"]))

    run_checks([(40, from_state), (58, itf)])
    for field in ("claimed_conditions", "intent_to_file_date"):
        if field in body:
            claim[field] = body[field]
    calc.refresh_claim_score(claim)
    bump(claim)
    return object_response(view(claim))


CLAIM_FROM = {
    "OPEN_EVIDENCE_DEVELOPMENT": ("DRAFT",),
    "SUBMIT_FOR_REVIEW": ("EVIDENCE_DEVELOPMENT",),
    "RETURN_FOR_REWORK": ("PEER_REVIEW",),
    "MARK_READY": ("PEER_REVIEW",),
    "FILE": ("READY_TO_FILE",),
    "WITHDRAW": ("DRAFT", "EVIDENCE_DEVELOPMENT", "PEER_REVIEW",
                 "READY_TO_FILE"),
}

# Which identity field on the claim the acting X-User-ID must equal (PRD 3.5).
CLAIM_ACTOR = {
    "OPEN_EVIDENCE_DEVELOPMENT": "prepared_by_representative_id",
    "SUBMIT_FOR_REVIEW": "prepared_by_representative_id",
    "RETURN_FOR_REWORK": "peer_reviewed_by_representative_id",
    "MARK_READY": "peer_reviewed_by_representative_id",
    "FILE": "prepared_by_representative_id",
    "WITHDRAW": "prepared_by_representative_id",
}


@bp.post("/claims/<row_id>/transitions")
def drive_claim(row_id):
    authorize(("CountyOfficer",))

    def extra(body):
        if body.get("action") == "FILE":
            if parse_date(body["filed_on"]) > now_date():
                raise ApiError("ERR_VALIDATION",
                               "filed_on may not be later than the"
                               " logical-clock date")

    body = check_shape({
        "actions": tuple(CLAIM_FROM.keys()),
        "optional": ["reviewer_representative_id", "rework_note", "filed_on",
                     "reason"],
        "action_required": {
            "SUBMIT_FOR_REVIEW": ("reviewer_representative_id",),
            "RETURN_FOR_REWORK": ("rework_note",),
            "FILE": ("filed_on",),
            "WITHDRAW": ("reason",),
        },
        "extra": extra,
    })
    claim = need_claim(row_id)
    action = body["action"]
    reviewer = None
    if action == "SUBMIT_FOR_REVIEW":
        reviewer = lookup(db.representatives,
                          body["reviewer_representative_id"], "ERR_NOT_FOUND")
    veteran = db.veterans.get(claim["veteran_id"])
    poa = db.powers_of_attorney.get(claim.get("poa_id"))

    def from_state():
        if claim["status"] not in CLAIM_FROM[action]:
            invalid_transition("%s is not available from %s"
                               % (action, claim["status"]))

    def actor_identity():
        if claim.get(CLAIM_ACTOR[action]) != g.user_id:
            invalid_transition("%s may be driven only by the claim's %s"
                               % (action, CLAIM_ACTOR[action]))

    def alive():
        if veteran is not None and veteran["intake_status"] == "DECEASED":
            raise ApiError("ERR_VETERAN_DECEASED",
                           "the veteran's case is closed to new work")

    def verified():
        if action != "OPEN_EVIDENCE_DEVELOPMENT":
            return
        if veteran is None or veteran["discharge_doc_status"] != "VERIFIED":
            raise ApiError("ERR_DISCHARGE_NOT_VERIFIED",
                           "the veteran has no verified discharge document")

    def intake_open():
        if action != "OPEN_EVIDENCE_DEVELOPMENT":
            return
        if veteran is None or veteran["intake_status"] not in ("SCREENED",
                                                              "ACTIVE"):
            invalid_transition("the veteran's case is not open for development")

    def poa_active():
        if action != "OPEN_EVIDENCE_DEVELOPMENT":
            return
        if claim.get("poa_id") is None or poa is None \
                or poa["status"] != "ACTIVE":
            raise ApiError("ERR_POA_NOT_ACTIVE",
                           "the claim rests on no ACTIVE designation")

    def reviewer_accredited():
        if action != "SUBMIT_FOR_REVIEW":
            return
        if reviewer["accreditation_status"] != "ACTIVE":
            raise ApiError("ERR_REPRESENTATIVE_NOT_ACCREDITED",
                           "the nominated reviewer is not accredited")

    def segregation():
        if action != "SUBMIT_FOR_REVIEW":
            return
        if reviewer["id"] == claim["prepared_by_representative_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "a preparer may not peer-review their own claim")

    def outstanding():
        if action == "SUBMIT_FOR_REVIEW":
            blocked = "REQUESTED"
        elif action == "FILE":
            blocked = "INSUFFICIENT"
        else:
            return
        for item in db.evidence_items.values():
            if item["claim_id"] == claim["id"] and item["status"] == blocked:
                raise ApiError("ERR_EVIDENCE_ITEM_OUTSTANDING",
                               "an evidence item is still in %s" % (blocked,))

    def designee():
        if action != "SUBMIT_FOR_REVIEW":
            return
        if poa is not None and poa["representative_id"] == reviewer["id"]:
            raise ApiError("ERR_REVIEWER_IS_DESIGNATED_REPRESENTATIVE",
                           "the designated representative may not review")

    def complete_enough():
        if action != "MARK_READY":
            return
        from decimal import Decimal
        if Decimal(str(claim["evidence_completeness_pct"])) \
                < calc.EVIDENCE_READY_THRESHOLD_PCT:
            raise ApiError("ERR_EVIDENCE_INCOMPLETE",
                           "evidence_completeness_pct is below the"
                           " ready-to-file threshold")

    run_checks([
        (40, from_state), (40.5, actor_identity), (41, alive), (43, verified),
        (43.5, intake_open), (44, poa_active), (49.5, reviewer_accredited),
        (50, segregation), (51, outstanding), (62, designee),
        (65, complete_enough),
    ])

    if action == "OPEN_EVIDENCE_DEVELOPMENT":
        claim["status"] = "EVIDENCE_DEVELOPMENT"
        calc.refresh_claim_score(claim)
        bump(claim)
    elif action == "SUBMIT_FOR_REVIEW":
        claim["status"] = "PEER_REVIEW"
        claim["peer_reviewed_by_representative_id"] = reviewer["id"]
        calc.refresh_claim_score(claim)
        bump(claim)
    elif action == "RETURN_FOR_REWORK":
        claim["status"] = "EVIDENCE_DEVELOPMENT"
        claim["rework_count"] = claim["rework_count"] + 1
        calc.refresh_claim_score(claim)
        bump(claim)
    elif action == "MARK_READY":
        claim["status"] = "READY_TO_FILE"
        calc.refresh_claim_score(claim)
        bump(claim)
    elif action == "FILE":
        filed = parse_date(body["filed_on"])
        basis, effective = calc.choose_effective_date(claim, filed)
        claim["status"] = "FILED"
        claim["filed_on"] = body["filed_on"]
        claim["effective_date_basis"] = basis
        claim["effective_date"] = "%04d-%02d-%02d" % (
            effective.year, effective.month, effective.day)
        calc.refresh_claim_score(claim)
        bump(claim)
    else:
        claim["status"] = "WITHDRAWN"
        claim["withdrawal_reason"] = body["reason"]
        released = {}
        for appointment in ordered(db.exam_appointments.values()):
            if appointment["claim_id"] == claim["id"] \
                    and appointment["status"] == "SCHEDULED":
                appointment["status"] = "CANCELLED"
                appointment["cancellation_reason"] = "CLAIM_WITHDRAWN"
                bump(appointment)
                released[appointment["exam_site_id"]] = \
                    released.get(appointment["exam_site_id"], 0) + 1
        for site_id, count in released.items():
            site = db.exam_sites.get(site_id)
            if site is None:
                continue
            site["booked_slot_count"] = site["booked_slot_count"] - count
            bump(site)
        for item in ordered(db.evidence_items.values()):
            if item["claim_id"] == claim["id"] and item["status"] == "REQUESTED":
                item["status"] = "WAIVED"
                item["status_reason"] = "CLAIM_WITHDRAWN"
                calc.refresh_item_points(item)
                bump(item)
        calc.refresh_claim_score(claim)
        bump(claim)

    calc.refresh_caseload(calc.claim_preparer(claim))
    return object_response(view(claim))


@bp.post("/claims/<row_id>/record-decision")
def record_decision(row_id):
    authorize(("CountyOfficer",))

    def extra(body):
        rating = body["awarded_rating_pct"]
        if body["decision_outcome"] == "DENIED":
            if rating != 0:
                raise ApiError("ERR_VALIDATION",
                               "awarded_rating_pct must be 0 on a DENIED"
                               " decision")
        elif rating < 10:
            raise ApiError("ERR_VALIDATION",
                           "awarded_rating_pct must be a multiple of 10 from"
                           " 10 through 100")

    body = check_shape({
        "required": ["decision_outcome", "awarded_rating_pct", "decided_on"],
        "extra": extra,
    })
    claim = need_claim(row_id)

    def from_state():
        if claim["status"] != "FILED":
            invalid_transition("a decision may be recorded only from FILED")

    def decision_dates():
        decided = parse_date(body["decided_on"])
        if claim.get("filed_on") is not None and decided < d(claim["filed_on"]):
            raise ApiError("ERR_DECISION_DATE_INVALID",
                           "decided_on precedes the claim's filed_on")
        if decided > now_date():
            raise ApiError("ERR_DECISION_DATE_INVALID",
                           "decided_on is later than the logical-clock date")

    run_checks([(40, from_state), (57, decision_dates)])

    veteran = db.veterans.get(claim["veteran_id"])
    decided = parse_date(body["decided_on"])
    rating = body["awarded_rating_pct"]

    # hop one -- the claim
    claim["status"] = "DECIDED"
    claim["decision_outcome"] = body["decision_outcome"]
    claim["awarded_rating_pct"] = rating
    claim["decided_on"] = body["decided_on"]
    claim["retro_award_cents"] = calc.retro_award_cents(
        claim, veteran, rating, decided) if veteran is not None else 0
    bump(claim)

    if veteran is not None:
        # hop two -- the veteran's combined rating and priority band
        calc.refresh_veteran_rating(veteran)
        bump(veteran)

        # hop three -- state awards whose rating floor is no longer met
        touched_programs = set()
        for application in ordered(db.state_benefit_applications.values()):
            if application["veteran_id"] != veteran["id"]:
                continue
            if application["determination_status"] != "APPROVED":
                continue
            program = db.state_programs.get(application["program_id"])
            if program is None:
                continue
            if program["min_rating_pct"] <= veteran["combined_rating_pct"]:
                continue
            application["determination_status"] = "DENIED"
            application["determination_reason"] = \
                "RATING_REDUCED_BELOW_PROGRAM_MINIMUM"
            application["disbursement_status"] = "CLAWED_BACK"
            bump(application)
            touched_programs.add(program["id"])

        # hop four -- the programs' committed pools
        for program_id in touched_programs:
            program = db.state_programs.get(program_id)
            if program is None:
                continue
            program["allocated_cents"] = calc.program_allocated_cents(program_id)
            bump(program)

    calc.refresh_caseload(calc.claim_preparer(claim))
    return object_response(view(claim))


# --------------------------------------------------------------------------
# evidence items
# --------------------------------------------------------------------------

@bp.post("/claims/<row_id>/evidence-items")
def request_evidence(row_id):
    authorize(("CountyOfficer",))
    body = check_shape({
        "required": ["evidence_type", "provider_name"],
        "optional": ["nexus_opinion_strength"],
    })
    claim = need_claim(row_id)

    def nexus_agreement():
        strength = body.get("nexus_opinion_strength")
        if body["evidence_type"] == "NEXUS_LETTER":
            if strength is None or strength == "NONE":
                raise ApiError("ERR_NEXUS_STRENGTH_MISMATCH",
                               "a NEXUS_LETTER requires an opinion strength"
                               " other than NONE")
        elif strength is not None and strength != "NONE":
            raise ApiError("ERR_NEXUS_STRENGTH_MISMATCH",
                           "only a NEXUS_LETTER may carry an opinion strength")

    run_checks([(64, nexus_agreement)])
    row = new_row()
    row["_kind"] = "evidence_item"
    row["claim_id"] = claim["id"]
    row["evidence_type"] = body["evidence_type"]
    row["status"] = "REQUESTED"
    row["provider_name"] = body["provider_name"]
    row["nexus_opinion_strength"] = body.get("nexus_opinion_strength") or "NONE"
    row["requested_on"] = calc.clock_date_str()
    row["received_on"] = None
    row["weight_points"] = 0.00
    row["status_reason"] = None
    row["auto_generated"] = False
    db.evidence_items[row["id"]] = row
    calc.refresh_claim_score(claim)
    bump(claim)
    return object_response(view(row), 201)


@bp.get("/claims/<row_id>/evidence-items")
def read_evidence_file(row_id):
    authorize(READ_EVIDENCE_FILE)
    need_claim(row_id)
    run_checks()
    rows = [x for x in ordered(db.evidence_items.values())
            if x["claim_id"] == row_id]
    rows = filter_rows(rows, {"status": "status",
                              "evidence_type": "evidence_type"})
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/evidence-items")
def list_evidence():
    authorize(READ_EVIDENCE)
    run_checks()
    rows = filter_rows(ordered(db.evidence_items.values()), {
        "claim_id": "claim_id",
        "status": "status",
        "evidence_type": "evidence_type",
        "auto_generated": "auto_generated",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/evidence-items/<row_id>")
def read_evidence(row_id):
    authorize(READ_EVIDENCE)
    row = need_evidence(row_id)
    run_checks()
    return object_response(view(row))


EVIDENCE_FROM = {
    "RECEIVE": ("REQUESTED", "INSUFFICIENT"),
    "MARK_INSUFFICIENT": ("RECEIVED",),
    "RE_REQUEST": ("INSUFFICIENT",),
    "WAIVE": ("REQUESTED", "INSUFFICIENT"),
}


@bp.post("/evidence-items/<row_id>/status")
def drive_evidence(row_id):
    authorize(("CountyOfficer",))
    body = check_shape({
        "actions": tuple(EVIDENCE_FROM.keys()),
        "optional": ["reason"],
        "action_required": {
            "MARK_INSUFFICIENT": ("reason",),
            "WAIVE": ("reason",),
        },
    })
    item = need_evidence(row_id)
    action = body["action"]
    claim = db.claims.get(item["claim_id"])

    def from_state():
        if item["status"] not in EVIDENCE_FROM[action]:
            invalid_transition("%s is not available from %s"
                               % (action, item["status"]))

    def claim_open():
        if claim is None or claim["status"] not in ("EVIDENCE_DEVELOPMENT",
                                                   "PEER_REVIEW"):
            invalid_transition("the parent claim is not open for evidence"
                               " development")

    def not_before_request():
        if action == "RECEIVE" and now_date() < d(item["requested_on"]):
            invalid_transition("the logical-clock date precedes requested_on")

    run_checks([(40, from_state), (40.2, claim_open), (40.4, not_before_request)])

    if action == "RECEIVE":
        item["status"] = "RECEIVED"
        item["received_on"] = calc.clock_date_str()
    elif action == "MARK_INSUFFICIENT":
        item["status"] = "INSUFFICIENT"
        item["status_reason"] = body["reason"]
        item["received_on"] = None
    elif action == "RE_REQUEST":
        item["status"] = "REQUESTED"
        item["requested_on"] = calc.clock_date_str()
        item["received_on"] = None
    else:
        item["status"] = "WAIVED"
        item["status_reason"] = body["reason"]
    calc.refresh_item_points(item)
    bump(item)
    if claim is not None:
        calc.refresh_claim_score(claim)
        bump(claim)
    return object_response(view(item))
