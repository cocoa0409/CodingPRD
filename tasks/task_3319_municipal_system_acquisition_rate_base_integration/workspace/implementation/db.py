"""In-memory data store. Starts empty on every boot — no seeding, ever.

Each store is a dict keyed by the resource id. Lists per parent are derived
by scanning; the dataset sizes in this benchmark are small.
"""

targets = {}
assessments = {}
capital_items = {}
valuation_cases = {}
valuation_entries = {}
council_events = {}
regulatory_applications = {}
customer_accounts = {}
transition_items = {}
employee_transitions = {}
tariff_cases = {}


def assessments_of_target(target_id):
    return [a for a in assessments.values() if a["target_id"] == target_id]


def capital_items_of_assessment(assessment_id):
    return [i for i in capital_items.values() if i["assessment_id"] == assessment_id]


def capital_items_of_target(target_id):
    assessment_ids = {a["id"] for a in assessments_of_target(target_id)}
    return [i for i in capital_items.values() if i["assessment_id"] in assessment_ids]


def valuation_cases_of_target(target_id):
    return [c for c in valuation_cases.values() if c["target_id"] == target_id]


def valuation_entries_of_case(case_id):
    return [e for e in valuation_entries.values() if e["case_id"] == case_id]


def council_events_of_target(target_id):
    return [e for e in council_events.values() if e["target_id"] == target_id]


def regulatory_applications_of_target(target_id):
    return [a for a in regulatory_applications.values() if a["target_id"] == target_id]


def customer_accounts_of_target(target_id):
    return [a for a in customer_accounts.values() if a["target_id"] == target_id]


def transition_items_of_target(target_id):
    return [i for i in transition_items.values() if i["target_id"] == target_id]


def employee_transitions_of_target(target_id):
    return [e for e in employee_transitions.values() if e["target_id"] == target_id]


def tariff_cases_of_target(target_id):
    return [t for t in tariff_cases.values() if t["target_id"] == target_id]
