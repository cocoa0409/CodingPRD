"""Proposals, the revision cycle and panel score sheets — PRD 3.3 and 3.4."""
import calc
from auth import ALL_ROLES, PANEL_READERS, acting_user, fetch, guard, require_owner
from envelope import created, listing, ok
from errors import ApiError
from logic import ordered
from router import route
from shape import body, ref, req_int, req_pct, req_str
from store import db, insert, now, parse_iso_instant, touch

LIVE_PROPOSAL_STATES = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "SCORED")
WITHDRAWABLE = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "SCORED")


def _deadline(prospectus):
    return parse_iso_instant(prospectus["submission_deadline"])


def _fiscal_floors(prospectus, fee_pct, guarantee_cents):
    if fee_pct < prospectus["minimum_franchise_fee_pct"]:
        raise ApiError("ERR_FEE_BELOW_MINIMUM",
                       "Offered franchise fee is below the prospectus minimum")
    if guarantee_cents < prospectus["minimum_annual_guarantee_cents"]:
        raise ApiError("ERR_GUARANTEE_BELOW_MINIMUM",
                       "Proposed annual guarantee is below the prospectus minimum")


@route("/proposals", methods=["POST"])
def proposals_create():
    guard("Concessionaire")
    data = body()
    prospectus = None
    offeror = None
    prospectus_ref = ref(data, "prospectus_id")
    if prospectus_ref is not None:
        prospectus = fetch(db.prospectuses, prospectus_ref, "ERR_PROSPECTUS_NOT_FOUND")
    offeror_ref = ref(data, "offeror_id")
    if offeror_ref is not None:
        offeror = fetch(db.offerors, offeror_ref, "ERR_OFFEROR_NOT_FOUND")
    if offeror is not None:
        require_owner(offeror["id"])
    row = {
        "prospectus_id": req_str(data, "prospectus_id"),
        "offeror_id": req_str(data, "offeror_id"),
        "offered_franchise_fee_pct": req_pct(data, "offered_franchise_fee_pct", gt=0, le=100),
        "proposed_capital_investment_cents": req_int(
            data, "proposed_capital_investment_cents", minimum=0),
        "proposed_annual_guarantee_cents": req_int(
            data, "proposed_annual_guarantee_cents", minimum=1),
        "experience_years": req_int(data, "experience_years", minimum=0),
        "financial_capacity_ratio": req_pct(data, "financial_capacity_ratio", gt=0),
        "revision_round": 0,
        "evaluation_count": 0,
        "composite_score": None,
        "status": "SUBMITTED",
    }
    if offeror["status"] != "ELIGIBLE":
        raise ApiError("ERR_OFFEROR_DEBARRED", "Offeror is not eligible to bid")
    if not now() < _deadline(prospectus):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED", "The submission window has closed")
    for existing in db.proposals.values():
        if (existing["prospectus_id"] == prospectus["id"]
                and existing["offeror_id"] == offeror["id"]
                and existing["status"] not in ("WITHDRAWN", "NOT_SELECTED")):
            raise ApiError("ERR_DUPLICATE_PROPOSAL",
                           "This offeror already holds a live proposal on this prospectus")
    _fiscal_floors(prospectus, row["offered_franchise_fee_pct"],
                   row["proposed_annual_guarantee_cents"])
    return created(insert(db.proposals, row))


@route("/proposals/<proposal_id>/begin-review", methods=["POST"])
def proposals_begin_review(proposal_id):
    guard("ConcessionSpecialist")
    proposal = fetch(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    if proposal["status"] != "SUBMITTED":
        raise ApiError("ERR_PROPOSAL_STATUS_INVALID",
                       "Proposal status %s cannot enter review" % proposal["status"])
    prospectus = db.prospectuses.get(proposal["prospectus_id"])
    if prospectus is None or prospectus["status"] not in ("ISSUED", "CLOSED"):
        raise ApiError("ERR_PROSPECTUS_STATUS_INVALID",
                       "The solicitation is not open for review")
    proposal["status"] = "UNDER_REVIEW"
    touch(proposal)
    return ok(proposal)


@route("/proposals/<proposal_id>/request-revision", methods=["POST"])
def proposals_request_revision(proposal_id):
    guard("ConcessionSpecialist")
    proposal = fetch(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    if proposal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_PROPOSAL_STATUS_INVALID",
                       "Proposal status %s cannot be sent back" % proposal["status"])
    if proposal["evaluation_count"] != 0:
        raise ApiError("ERR_EVALUATION_ALREADY_STARTED",
                       "The panel has already begun scoring this proposal")
    prospectus = db.prospectuses.get(proposal["prospectus_id"])
    if prospectus is None or prospectus["status"] != "ISSUED":
        raise ApiError("ERR_PROSPECTUS_STATUS_INVALID",
                       "The solicitation is no longer open")
    if not proposal["revision_round"] < calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED", "The revision allowance is exhausted")
    proposal["status"] = "REVISION_REQUESTED"
    proposal["revision_round"] = proposal["revision_round"] + 1
    touch(proposal)
    return ok(proposal)


@route("/proposals/<proposal_id>/resubmit", methods=["POST"])
def proposals_resubmit(proposal_id):
    guard("Concessionaire")
    proposal = fetch(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    require_owner(proposal["offeror_id"])
    data = body()
    fee_pct = req_pct(data, "offered_franchise_fee_pct", gt=0, le=100)
    capital = req_int(data, "proposed_capital_investment_cents", minimum=0)
    guarantee = req_int(data, "proposed_annual_guarantee_cents", minimum=1)
    if proposal["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_PROPOSAL_STATUS_INVALID",
                       "Proposal status %s cannot be resubmitted" % proposal["status"])
    prospectus = db.prospectuses.get(proposal["prospectus_id"])
    if prospectus is None or prospectus["status"] != "ISSUED":
        raise ApiError("ERR_PROSPECTUS_STATUS_INVALID", "The solicitation is no longer open")
    if not now() < _deadline(prospectus):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED", "The submission window has closed")
    _fiscal_floors(prospectus, fee_pct, guarantee)
    proposal["offered_franchise_fee_pct"] = fee_pct
    proposal["proposed_capital_investment_cents"] = capital
    proposal["proposed_annual_guarantee_cents"] = guarantee
    proposal["status"] = "SUBMITTED"
    touch(proposal)
    return ok(proposal)


@route("/proposals/<proposal_id>/withdraw", methods=["POST"])
def proposals_withdraw(proposal_id):
    guard("Concessionaire")
    proposal = fetch(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    require_owner(proposal["offeror_id"])
    if proposal["status"] not in WITHDRAWABLE:
        raise ApiError("ERR_PROPOSAL_STATUS_INVALID",
                       "Proposal status %s cannot be withdrawn" % proposal["status"])
    proposal["status"] = "WITHDRAWN"
    touch(proposal)
    return ok(proposal)


@route("/proposals/<proposal_id>/evaluations", methods=["POST"])
def proposals_file_evaluation(proposal_id):
    guard("EvaluationPanelist")
    proposal = fetch(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND")
    data = body()
    scores = {}
    for field in ("score_experience", "score_operating_plan", "score_capital_investment",
                  "score_financial_capacity", "score_fee_offer"):
        scores[field] = req_int(data, field, minimum=0, maximum=100)
    if proposal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_PROPOSAL_STATUS_INVALID",
                       "Proposal status %s does not admit a score sheet" % proposal["status"])
    sheets = [e for e in db.evaluations.values() if e["proposal_id"] == proposal_id]
    if len(sheets) >= calc.REQUIRED_PANELIST_COUNT:
        raise ApiError("ERR_PANEL_ALREADY_COMPLETE", "The panel is already complete")
    for sheet in sheets:
        if sheet["panelist_user_id"] == acting_user():
            raise ApiError("ERR_DUPLICATE_PANELIST_EVALUATION",
                           "This panelist has already filed on this proposal")
    row = {"proposal_id": proposal_id, "panelist_user_id": acting_user()}
    row.update(scores)
    evaluation = insert(db.evaluations, row, common_fields=False)
    proposal["evaluation_count"] = proposal["evaluation_count"] + 1
    if proposal["evaluation_count"] == calc.REQUIRED_PANELIST_COUNT:
        prospectus = db.prospectuses.get(proposal["prospectus_id"])
        filed = ordered([e for e in db.evaluations.values()
                         if e["proposal_id"] == proposal_id])
        proposal["composite_score"] = calc.composite_score(filed, prospectus)
        proposal["status"] = "SCORED"
    touch(proposal)
    return created(evaluation)


@route("/proposals", methods=["GET"])
def proposals_list():
    guard(*ALL_ROLES)
    return listing(db.proposals, ("prospectus_id", "offeror_id", "status"))


@route("/proposals/<proposal_id>", methods=["GET"])
def proposals_read(proposal_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.proposals, proposal_id, "ERR_PROPOSAL_NOT_FOUND"))


@route("/proposal-evaluations", methods=["GET"])
def evaluations_list():
    guard(*PANEL_READERS)
    return listing(db.evaluations, ("proposal_id",))


@route("/proposal-evaluations/<evaluation_id>", methods=["GET"])
def evaluations_read(evaluation_id):
    guard(*PANEL_READERS)
    return ok(fetch(db.evaluations, evaluation_id, "ERR_EVALUATION_NOT_FOUND"))
