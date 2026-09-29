"""Row lookups (ladder rungs 3 and 5) and collection filters."""
from db import db, sort_rows
from errors import ApiError

_NOT_FOUND = {
    "plan_updates": "ERR_PLAN_UPDATE_NOT_FOUND",
    "inventory_datasets": "ERR_INVENTORY_NOT_FOUND",
    "growth_scenarios": "ERR_SCENARIO_NOT_FOUND",
    "plan_elements": "ERR_ELEMENT_NOT_FOUND",
    "consistency_links": "ERR_LINK_NOT_FOUND",
    "venues": "ERR_VENUE_NOT_FOUND",
    "engagement_activities": "ERR_ACTIVITY_NOT_FOUND",
    "environmental_reviews": "ERR_REVIEW_NOT_FOUND",
    "hearings": "ERR_HEARING_NOT_FOUND",
    "amendments": "ERR_AMENDMENT_NOT_FOUND",
    "implementation_actions": "ERR_ACTION_NOT_FOUND",
}


def _fetch(collection, row_id):
    table = getattr(db, collection)
    if not isinstance(row_id, str):
        raise ApiError(_NOT_FOUND[collection])
    row = table.get(row_id)
    if row is None:
        raise ApiError(_NOT_FOUND[collection])
    return row


def plan(row_id):
    return _fetch("plan_updates", row_id)


def inventory(row_id):
    return _fetch("inventory_datasets", row_id)


def scenario(row_id):
    return _fetch("growth_scenarios", row_id)


def element(row_id):
    return _fetch("plan_elements", row_id)


def link(row_id):
    return _fetch("consistency_links", row_id)


def venue(row_id):
    return _fetch("venues", row_id)


def activity(row_id):
    return _fetch("engagement_activities", row_id)


def review(row_id):
    return _fetch("environmental_reviews", row_id)


def hearing(row_id):
    return _fetch("hearings", row_id)


def amendment(row_id):
    return _fetch("amendments", row_id)


def action(row_id):
    return _fetch("implementation_actions", row_id)


# --- collections ------------------------------------------------------------

def _by(collection, field, value):
    return sort_rows([r for r in getattr(db, collection).values()
                      if r.get(field) == value])


def inventories_of(plan_id):
    return _by("inventory_datasets", "plan_update_id", plan_id)


def scenarios_of(plan_id):
    return _by("growth_scenarios", "plan_update_id", plan_id)


def allocations_of(plan_id):
    return _by("housing_allocations", "plan_update_id", plan_id)


def elements_of(plan_id):
    return _by("plan_elements", "plan_update_id", plan_id)


def activities_of(plan_id):
    return _by("engagement_activities", "plan_update_id", plan_id)


def reviews_of(plan_id):
    return _by("environmental_reviews", "plan_update_id", plan_id)


def hearings_of(plan_id):
    return _by("hearings", "plan_update_id", plan_id)


def actions_of(plan_id):
    return _by("implementation_actions", "plan_update_id", plan_id)


def records_of(activity_id):
    return _by("participation_records", "activity_id", activity_id)


def alternatives_of(review_id):
    return _by("plan_alternatives", "environmental_review_id", review_id)


def amendments_of(hearing_id):
    return _by("amendments", "hearing_id", hearing_id)


def links_sourced_from(element_id):
    return _by("consistency_links", "source_element_id", element_id)


def links_targeting(element_id):
    return _by("consistency_links", "target_element_id", element_id)


def links_of_plan(plan_id):
    """Links whose SOURCE element belongs to the plan (PRD 2.9 filter)."""
    out = []
    for row in db.consistency_links.values():
        src = db.plan_elements.get(row["source_element_id"])
        if src is not None and src["plan_update_id"] == plan_id:
            out.append(row)
    return sort_rows(out)


def plan_of_element(element_row):
    return db.plan_updates.get(element_row["plan_update_id"])
