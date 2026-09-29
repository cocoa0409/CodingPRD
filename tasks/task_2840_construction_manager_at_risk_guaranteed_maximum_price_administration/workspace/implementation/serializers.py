"""Entity to JSON projection.  Field names come straight from the scaffold."""
import clock
from money import out_num

MONEY = "money"
INT = "int"
BOOL = "bool"
STR = "str"
DT = "dt"

_COMMON = [
    ("id", STR),
    ("created_at", DT),
    ("updated_at", DT),
    ("version", INT),
]

PROJECT_FIELDS = [
    ("name", STR),
    ("owner_org", STR),
    ("cm_fee_pct", MONEY),
    ("insurance_rate", MONEY),
    ("precon_fee_amount", MONEY),
    ("gmp_status", STR),
    ("gmp_amount", MONEY),
    ("proposed_gmp_amount", MONEY),
    ("cost_of_work_budget_total", MONEY),
    ("general_conditions_total", MONEY),
    ("insurance_amount", MONEY),
    ("cm_fee_amount", MONEY),
    ("owner_contingency_original", MONEY),
    ("owner_contingency_remaining", MONEY),
    ("construction_contingency_original", MONEY),
    ("construction_contingency_remaining", MONEY),
    ("contingency_drawn_to_cost_total", MONEY),
    ("contingency_posture", STR),
    ("pending_amendment_count", INT),
    ("buyout_savings_trade_level", MONEY),
    ("buyout_savings_project_net", MONEY),
    ("audit_status", STR),
    ("audit_adjustment_total", MONEY),
    ("closeout_status", STR),
    ("provisional_savings_pool", MONEY),
    ("provisional_cm_savings_share", MONEY),
    ("provisional_owner_savings_share", MONEY),
    ("final_savings_pool", MONEY),
    ("final_cm_savings_share", MONEY),
    ("final_owner_savings_share", MONEY),
]

ESTIMATE_FIELDS = [
    ("project_id", STR),
    ("prior_estimate_id", STR),
    ("milestone_code", STR),
    ("milestone_rank", INT),
    ("submitted_cost_of_work", MONEY),
    ("variance_pct", MONEY),
    ("variance_basis", STR),
    ("variance_basis_estimate_id", STR),
    ("justification_note", STR),
    ("status", STR),
    ("reconciliation_stale", BOOL),
    ("reconciliation_note", STR),
    ("superseded_by_estimate_id", STR),
]

PROPOSAL_FIELDS = [
    ("project_id", STR),
    ("proposal_type", STR),
    ("based_on_estimate_id", STR),
    ("change_event_id", STR),
    ("cost_of_work_total", MONEY),
    ("general_conditions_total", MONEY),
    ("owner_contingency_amount", MONEY),
    ("construction_contingency_amount", MONEY),
    ("amount_delta", MONEY),
    ("provisional_fee_amount", MONEY),
    ("insurance_amount", MONEY),
    ("cm_fee_amount", MONEY),
    ("gmp_amount", MONEY),
    ("status", STR),
    ("owner_decision_note", STR),
    ("revision_count", INT),
    ("superseded_by_proposal_id", STR),
]

QUALIFICATION_ITEM_FIELDS = [
    ("gmp_proposal_id", STR),
    ("item_type", STR),
    ("text", STR),
    ("allowance_amount", MONEY),
    ("allocated_units", MONEY),
    ("unit_of_measure", STR),
    ("allowance_unit_rate", MONEY),
    ("remaining_units", MONEY),
    ("reconciled_units", MONEY),
    ("reconciled_amount", MONEY),
    ("variance_amount", MONEY),
    ("reconciliation_seq", INT),
    ("last_action", STR),
    ("status", STR),
]

WORK_PACKAGE_FIELDS = [
    ("project_id", STR),
    ("trade_division", STR),
    ("budget_amount", MONEY),
    ("self_perform_intent", BOOL),
    ("procurement_status", STR),
    ("transparency_status", STR),
    ("solicitation_opens_at", DT),
    ("solicitation_closes_at", DT),
    ("awarded_bid_id", STR),
    ("awarded_amount", MONEY),
    ("committed_amount", MONEY),
    ("replacement_reserve_amount", MONEY),
    ("bid_count", INT),
]

BID_FIELDS = [
    ("work_package_id", STR),
    ("bidder_type", STR),
    ("bidder_name", STR),
    ("base_bid_amount", MONEY),
    ("prepared_by_user_id", STR),
    ("opened_by_user_id", STR),
    ("opened_at", DT),
    ("status", STR),
]

SUBCONTRACT_FIELDS = [
    ("work_package_id", STR),
    ("awarded_bid_id", STR),
    ("subcontractor_name", STR),
    ("contract_amount", MONEY),
    ("performance_start", DT),
    ("performance_end", DT),
    ("bond_required", BOOL),
    ("bond_amount", MONEY),
    ("paid_to_date", MONEY),
    ("unpaid_committed_amount", MONEY),
    ("replacement_cost_amount", MONEY),
    ("contract_status", STR),
    ("bond_claim_status", STR),
    ("bond_claim_amount", MONEY),
    ("bond_recovered_amount", MONEY),
    ("default_notice_at", DT),
    ("cure_count", INT),
]

CHANGE_EVENT_FIELDS = [
    ("project_id", STR),
    ("qualification_item_id", STR),
    ("source_subcontract_id", STR),
    ("description", STR),
    ("estimated_amount", MONEY),
    ("origin", STR),
    ("classification", STR),
    ("status", STR),
    ("submitted_by_user_id", STR),
    ("classified_by_user_id", STR),
    ("classified_at", DT),
    ("review_note", STR),
    ("revision_count", INT),
]

DRAW_FIELDS = [
    ("project_id", STR),
    ("change_event_id", STR),
    ("source_subcontract_id", STR),
    ("contingency_type", STR),
    ("origin", STR),
    ("amount", MONEY),
    ("requires_owner_approval", BOOL),
    ("status", STR),
    ("approved_by_user_id", STR),
    ("posted_at", DT),
    ("voided_at", DT),
    ("void_reason", STR),
]

COST_REPORT_FIELDS = [
    ("project_id", STR),
    ("period_start", DT),
    ("period_end", DT),
    ("status", STR),
    ("line_count", INT),
    ("reported_cost_total", MONEY),
    ("undisputed_cost_total", MONEY),
    ("disputed_cost_total", MONEY),
    ("buyout_savings_to_date", MONEY),
    ("held_reason", STR),
    ("reconciled_at", DT),
    ("reconciliation_note", STR),
]

LINE_FIELDS = [
    ("line_seq", INT),
    ("work_package_id", STR),
    ("quantity", MONEY),
    ("unit_rate", MONEY),
    ("markup_pct", MONEY),
    ("line_amount", MONEY),
    ("disputed", BOOL),
]


def _project_fields(record, spec):
    out = {}
    for name, kind in spec:
        value = record.get(name)
        if value is None:
            out[name] = None
        elif kind == MONEY:
            out[name] = out_num(value)
        elif kind == DT:
            out[name] = clock.fmt(value)
        else:
            out[name] = value
    return out


def _render(record, spec):
    out = _project_fields(record, _COMMON)
    out.update(_project_fields(record, spec))
    return out


def project(record):
    return _render(record, PROJECT_FIELDS)


def estimate(record):
    return _render(record, ESTIMATE_FIELDS)


def proposal(record):
    return _render(record, PROPOSAL_FIELDS)


def qualification_item(record):
    return _render(record, QUALIFICATION_ITEM_FIELDS)


def work_package(record):
    return _render(record, WORK_PACKAGE_FIELDS)


def bid(record):
    out = _render(record, BID_FIELDS)
    # Open-book detail is suppressed while the bid is still sealed (PRD 3.4).
    if record["status"] in ("OPENED", "AWARDED", "NOT_AWARDED"):
        breakdown = record.get("open_book_cost_breakdown")
        if breakdown is None:
            out["open_book_cost_breakdown"] = None
        else:
            out["open_book_cost_breakdown"] = dict(
                (k, out_num(v)) for k, v in breakdown.items()
            )
    else:
        out["open_book_cost_breakdown"] = None
    return out


def subcontract(record):
    return _render(record, SUBCONTRACT_FIELDS)


def change_event(record):
    return _render(record, CHANGE_EVENT_FIELDS)


def draw(record):
    return _render(record, DRAW_FIELDS)


def cost_report(record):
    out = _render(record, COST_REPORT_FIELDS)
    out["lines"] = [_project_fields(line, LINE_FIELDS) for line in record["lines"]]
    return out
