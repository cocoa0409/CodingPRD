"""The competitive solicitation and the award — PRD 3.2 and 3.4."""
import calc
from auth import ALL_ROLES, acting_user, fetch, guard
from envelope import created, listing, ok
from errors import ApiError
from logic import ordered
from money import fmt_date
from router import route
from shape import body, ref, req_date, req_enum, req_instant, req_int, req_pct, req_str
from store import db, insert, now, parse_iso_instant, touch

SCORING_MODES = ("PER_CRITERION_ROUNDING", "FINAL_ROUNDING")
WEIGHT_FIELDS = ("weight_experience", "weight_operating_plan", "weight_capital_investment",
                 "weight_financial_capacity", "weight_fee_offer")


@route("/prospectuses", methods=["POST"])
def prospectuses_create():
    guard("ConcessionSpecialist")
    data = body()
    opportunity_ref = ref(data, "opportunity_id")
    if opportunity_ref is not None:
        fetch(db.opportunities, opportunity_ref, "ERR_OPPORTUNITY_NOT_FOUND")
    row = {
        "opportunity_id": req_str(data, "opportunity_id"),
        "minimum_franchise_fee_pct": req_pct(data, "minimum_franchise_fee_pct", gt=0, le=100),
        "minimum_annual_guarantee_cents": req_int(
            data, "minimum_annual_guarantee_cents", minimum=1),
        "term_years": req_int(data, "term_years", minimum=1, maximum=30),
        "submission_deadline": req_instant(data, "submission_deadline")[0],
    }
    for field in WEIGHT_FIELDS:
        row[field] = req_int(data, field, minimum=0, maximum=100)
    row["scoring_mode"] = req_enum(data, "scoring_mode", SCORING_MODES)
    row["min_technical_score"] = req_pct(data, "min_technical_score", ge=0, le=100)
    row["status"] = "DRAFT"
    if sum(row[field] for field in WEIGHT_FIELDS) != 100:
        raise ApiError("ERR_WEIGHTS_NOT_NORMALIZED",
                       "The five evaluation weights must total exactly 100")
    return created(insert(db.prospectuses, row))


@route("/prospectuses/<prospectus_id>/issue", methods=["POST"])
def prospectuses_issue(prospectus_id):
    guard("ConcessionSpecialist")
    prospectus = fetch(db.prospectuses, prospectus_id, "ERR_PROSPECTUS_NOT_FOUND")
    if prospectus["status"] != "DRAFT":
        raise ApiError("ERR_PROSPECTUS_STATUS_INVALID",
                       "Prospectus status %s cannot be issued" % prospectus["status"])
    opportunity = db.opportunities.get(prospectus["opportunity_id"])
    if opportunity is None or opportunity["status"] != "APPROVED_FOR_SOLICITATION":
        raise ApiError("ERR_OPPORTUNITY_NOT_APPROVED",
                       "The opportunity has not been approved for solicitation")
    if not now() < parse_iso_instant(prospectus["submission_deadline"]):
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED",
                       "The submission deadline has already passed")
    prospectus["status"] = "ISSUED"
    touch(prospectus)
    opportunity["status"] = "SOLICITED"
    touch(opportunity)
    return ok(prospectus)


@route("/prospectuses/<prospectus_id>/close", methods=["POST"])
def prospectuses_close(prospectus_id):
    guard("ConcessionSpecialist")
    prospectus = fetch(db.prospectuses, prospectus_id, "ERR_PROSPECTUS_NOT_FOUND")
    if prospectus["status"] != "ISSUED":
        raise ApiError("ERR_PROSPECTUS_STATUS_INVALID",
                       "Prospectus status %s cannot be closed" % prospectus["status"])
    if now() < parse_iso_instant(prospectus["submission_deadline"]):
        raise ApiError("ERR_SUBMISSION_WINDOW_OPEN",
                       "The submission window is still open")
    prospectus["status"] = "CLOSED"
    touch(prospectus)
    for proposal in ordered([p for p in db.proposals.values()
                             if p["prospectus_id"] == prospectus_id]):
        if proposal["status"] == "REVISION_REQUESTED":
            proposal["status"] = "NOT_SELECTED"
            touch(proposal)
    return ok(prospectus)


def _candidate_bond_requirement(proposal, prospectus):
    return calc.required_bond_amount(proposal["proposed_annual_guarantee_cents"],
                                     proposal["proposed_capital_investment_cents"],
                                     prospectus["term_years"])


@route("/prospectuses/<prospectus_id>/award", methods=["POST"])
def prospectuses_award(prospectus_id):
    guard("ContractingOfficer")
    prospectus = fetch(db.prospectuses, prospectus_id, "ERR_PROSPECTUS_NOT_FOUND")
    data = body()
    term_start_raw, term_start = req_date(data, "term_start")
    if prospectus["status"] != "CLOSED":
        raise ApiError("ERR_PROSPECTUS_STATUS_INVALID",
                       "Prospectus status %s cannot be awarded" % prospectus["status"])
    opportunity = db.opportunities.get(prospectus["opportunity_id"])
    proposals = ordered([p for p in db.proposals.values()
                         if p["prospectus_id"] == prospectus_id])
    candidates = []
    for proposal in proposals:
        if proposal["status"] != "SCORED":
            continue
        offeror = db.offerors.get(proposal["offeror_id"])
        if offeror is None or offeror["status"] != "ELIGIBLE":
            continue
        if proposal["composite_score"] is None:
            continue
        if proposal["composite_score"] < prospectus["min_technical_score"]:
            continue
        if proposal["offered_franchise_fee_pct"] < prospectus["minimum_franchise_fee_pct"]:
            continue
        required_capital = 0
        if opportunity is not None:
            required_capital = opportunity["required_capital_investment_cents"]
        if proposal["proposed_capital_investment_cents"] < required_capital:
            continue
        if offeror["bond_capacity_cents"] < _candidate_bond_requirement(proposal, prospectus):
            continue
        candidates.append(proposal)
    if not candidates:
        raise ApiError("ERR_NO_RESPONSIVE_PROPOSAL", "No responsive proposal was found")
    for evaluation in db.evaluations.values():
        proposal = db.proposals.get(evaluation["proposal_id"])
        if proposal is not None and proposal["prospectus_id"] == prospectus_id:
            if evaluation["panelist_user_id"] == acting_user():
                raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                               "A panelist on this solicitation may not award it")
    candidates.sort(key=lambda p: (-p["composite_score"],
                                   -p["offered_franchise_fee_pct"],
                                   -p["proposed_capital_investment_cents"],
                                   p["created_at"],
                                   p["_seq"]))
    winner = candidates[0]
    winner["status"] = "SELECTED"
    touch(winner)
    for proposal in proposals:
        if proposal["id"] == winner["id"]:
            continue
        if proposal["status"] in ("SUBMITTED", "UNDER_REVIEW", "SCORED"):
            proposal["status"] = "NOT_SELECTED"
            touch(proposal)
    required_bond = calc.required_bond_amount(winner["proposed_annual_guarantee_cents"],
                                              winner["proposed_capital_investment_cents"],
                                              prospectus["term_years"])
    lease_row = {
        "park_id": opportunity["park_id"] if opportunity is not None else None,
        "prospectus_id": prospectus_id,
        "offeror_id": winner["offeror_id"],
        "selected_proposal_id": winner["id"],
        "predecessor_lease_id": None,
        "performance_bond_id": None,
        "awarded_by_user_id": acting_user(),
        "executed_by_user_id": None,
        "base_fee_pct": winner["offered_franchise_fee_pct"],
        "minimum_annual_guarantee_cents": winner["proposed_annual_guarantee_cents"],
        "capital_investment_obligation_cents": winner["proposed_capital_investment_cents"],
        "term_years": prospectus["term_years"],
        "term_start": term_start_raw,
        "term_end": fmt_date(calc.term_end(term_start, prospectus["term_years"])),
        "required_bond_amount_cents": required_bond,
        "agency_maintenance_scope": "STRUCTURAL_ONLY",
        "insurance_expires_on": None,
        "carrier_name": None,
        "capital_investment_completed_cents": 0,
        "reported_receipts_ytd_cents": 0,
        "remitted_fee_ytd_cents": 0,
        "maintenance_reserve_balance_cents": 0,
        "outstanding_fee_balance_cents": 0,
        "possessory_interest_value_cents": None,
        "transfer_settlement_net_cents": None,
        "transfer_settlement_deficiency_cents": None,
        "contract_status": "PENDING_EXECUTION",
        "compliance_status": "COMPLIANT",
    }
    lease = insert(db.leases, lease_row)
    bond = insert(db.bonds, {
        "lease_id": lease["id"],
        "required_amount_cents": required_bond,
        "surety_name": None,
        "penal_sum_cents": None,
        "available_balance_cents": 0,
        "drawn_total_cents": 0,
        "status": "PENDING",
    })
    lease["performance_bond_id"] = bond["id"]
    if opportunity is not None:
        opportunity["status"] = "AWARDED"
        touch(opportunity)
    prospectus["status"] = "AWARDED"
    touch(prospectus)
    return created(lease)


@route("/prospectuses", methods=["GET"])
def prospectuses_list():
    guard(*ALL_ROLES)
    return listing(db.prospectuses, ("opportunity_id", "status"))


@route("/prospectuses/<prospectus_id>", methods=["GET"])
def prospectuses_read(prospectus_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.prospectuses, prospectus_id, "ERR_PROSPECTUS_NOT_FOUND"))
