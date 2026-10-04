"""Cross-entity side effects: the target rejection cascade and shared helpers.
"""
import db
from models import touch


def reject_target_cascade(target):
    """PRD section 3.8. Fires on decisive council-vote failure, failed
    referendum, or commission DENIED decision."""
    target["status"] = "REJECTED"
    for case in db.valuation_cases_of_target(target["id"]):
        if case["status"] in ("OPEN", "FINALIZED"):
            case["status"] = "SUPERSEDED"
            touch(case)
    for case in db.valuation_cases_of_target(target["id"]):
        if case["status"] == "SUPERSEDED":
            for entry in db.valuation_entries_of_case(case["id"]):
                if entry["status"] in ("SUBMITTED", "SELECTED"):
                    entry["status"] = "NOT_SELECTED"
                    touch(entry)
    for item in db.transition_items_of_target(target["id"]):
        if item["status"] == "PENDING":
            item["status"] = "BLOCKED"
            touch(item)
    for emp in db.employee_transitions_of_target(target["id"]):
        if emp["status"] == "PENDING":
            emp["status"] = "WITHDRAWN"
            touch(emp)
    touch(target)


def supersede_open_cases(target, except_case_id=None):
    """Every OPEN valuation case of the target -> SUPERSEDED; its SUBMITTED
    entries -> NOT_SELECTED. Used on case-create supersede."""
    for case in db.valuation_cases_of_target(target["id"]):
        if case["status"] == "OPEN" and case["id"] != except_case_id:
            case["status"] = "SUPERSEDED"
            touch(case)
            for entry in db.valuation_entries_of_case(case["id"]):
                if entry["status"] == "SUBMITTED":
                    entry["status"] = "NOT_SELECTED"
                    touch(entry)
