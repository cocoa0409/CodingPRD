"""Shared domain helpers: existence resolution, derived-field recomputes and
the two conserved ledgers of PRD 2.9."""
import store
import calc
from errors import ApiError

NOT_FOUND = {
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "machine_models": "ERR_MACHINE_MODEL_NOT_FOUND",
    "product_trials": "ERR_PRODUCT_TRIAL_NOT_FOUND",
    "machine_orders": "ERR_MACHINE_ORDER_NOT_FOUND",
    "production_lines": "ERR_PRODUCTION_LINE_NOT_FOUND",
    "build_slots": "ERR_BUILD_SLOT_NOT_FOUND",
    "long_lead_components": "ERR_COMPONENT_NOT_FOUND",
    "acceptance_tests": "ERR_ACCEPTANCE_TEST_NOT_FOUND",
    "installed_machines": "ERR_INSTALLED_MACHINE_NOT_FOUND",
    "format_kits": "ERR_FORMAT_KIT_NOT_FOUND",
    "service_contracts": "ERR_SERVICE_CONTRACT_NOT_FOUND",
    "field_engineers": "ERR_FIELD_ENGINEER_NOT_FOUND",
    "pm_visits": "ERR_PM_VISIT_NOT_FOUND",
    "warranty_claims": "ERR_WARRANTY_CLAIM_NOT_FOUND",
    "claim_lines": "ERR_CLAIM_LINE_NOT_FOUND",
    "stocking_recommendations": "ERR_STOCKING_RECOMMENDATION_NOT_FOUND",
}

COMMITTED_SLOT_STATUSES = ("RESERVED", "CONFIRMED", "IN_BUILD", "REWORK_HOLD")
OPEN_ORDER_EXCLUDED = ("ACCEPTED", "CANCELLED")
OPEN_CLAIM_STATUSES = ("SUBMITTED", "PRODUCT_VARIATION_REVIEW", "DEFECT_REVIEW")
COUNTED_PM_STATUSES = ("SCHEDULED", "BILLABLE_HOLD", "COMPLETED")
LIVE_VISIT_STATUSES = ("SCHEDULED", "BILLABLE_HOLD")


def must_get(table, row_id):
    row = store.get(table, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[table], "Referenced resource does not exist.")
    return row


def children(table, key, value):
    return [row for row in store.rows(table) if row.get(key) == value]


# --------------------------------------------------------------------------
# navigation
# --------------------------------------------------------------------------
def order_model(order):
    return store.get("machine_models", order["machine_model_id"])


def order_customer(order):
    return store.get("customers", order["customer_id"])


def machine_order(machine):
    return store.get("machine_orders", machine["machine_order_id"])


def machine_model(machine):
    order = machine_order(machine)
    return order_model(order) if order else None


def machine_customer(machine):
    return store.get("customers", machine["customer_id"])


def contract_machine(contract):
    return store.get("installed_machines", contract["installed_machine_id"])


# --------------------------------------------------------------------------
# derived fields / ledgers
# --------------------------------------------------------------------------
def _apply(row, field, value, bump=True):
    if row.get(field) == value:
        return False
    row[field] = value
    if bump:
        store.touch(row)
    return True


def recompute_customer_open_orders(customer, bump=True):
    if customer is None:
        return False
    count = sum(1 for order in store.rows("machine_orders")
                if order["customer_id"] == customer["id"]
                and order["fulfillment_status"] not in OPEN_ORDER_EXCLUDED)
    return _apply(customer, "open_order_count", count, bump)


def recompute_line_committed_days(line, bump=True):
    if line is None:
        return False
    total = sum(int(slot["slot_days"]) for slot in store.rows("build_slots")
                if slot["production_line_id"] == line["id"]
                and slot["status"] in COMMITTED_SLOT_STATUSES)
    return _apply(line, "committed_slot_days", total, bump)


def recompute_machine_open_claims(machine, bump=True):
    if machine is None:
        return False
    count = sum(1 for claim in store.rows("warranty_claims")
                if claim["installed_machine_id"] == machine["id"]
                and claim["status"] in OPEN_CLAIM_STATUSES)
    return _apply(machine, "open_claim_count", count, bump)


def recompute_contract_pm_used(contract, bump=True):
    if contract is None:
        return False
    count = sum(1 for visit in store.rows("pm_visits")
                if visit["service_contract_id"] == contract["id"]
                and visit["visit_type"] == "PM"
                and visit["status"] in COUNTED_PM_STATUSES)
    return _apply(contract, "pm_visits_used", count, bump)


def claim_lines_of(claim):
    return children("claim_lines", "warranty_claim_id", claim["id"])


def recompute_claimed_cost(claim, bump=True):
    total = sum(int(line["amount_cents"]) for line in claim_lines_of(claim))
    return _apply(claim, "claimed_cost_cents", total, bump)


def goodwill_ledger_value(contract):
    """PRD 2.9: initial pot less every ADJUDICATED claim's charge."""
    charged = sum(int(claim["goodwill_charged_cents"])
                  for claim in store.rows("warranty_claims")
                  if claim["service_contract_id"] == contract["id"]
                  and claim["status"] == "ADJUDICATED")
    return int(contract["goodwill_budget_initial_cents"]) - charged


# --------------------------------------------------------------------------
# billability (calculations.pm_visit_billability)
# --------------------------------------------------------------------------
def compute_billable(contract, visit_type, visit_id=None):
    if visit_type == "PM":
        prior = sum(1 for visit in store.rows("pm_visits")
                    if visit["service_contract_id"] == contract["id"]
                    and visit["visit_type"] == "PM"
                    and visit["status"] in COUNTED_PM_STATUSES
                    and visit["id"] != visit_id)
        return prior >= int(contract["pm_visits_included"])
    if visit_type == "CORRECTIVE":
        return not (contract["tier"] == "GOLD"
                    and contract["coverage_posture"] == "OPEN")
    return contract["tier"] == "BRONZE"


# --------------------------------------------------------------------------
# interval arithmetic
# --------------------------------------------------------------------------
def slots_collide(new_start, new_end, inc_start, inc_end, buffer_days):
    """Half-open day intervals, both sides widened by the changeover buffer."""
    return (store.parse_date(new_start) < store.parse_date(store.add_days(inc_end, buffer_days))
            and store.parse_date(inc_start) < store.parse_date(store.add_days(new_end, buffer_days)))


def visits_collide(new_start, new_end, inc_start, inc_end):
    """Closed millisecond intervals, no buffer of any kind."""
    return new_start <= inc_end and inc_start <= new_end


# --------------------------------------------------------------------------
# slot geometry
# --------------------------------------------------------------------------
def recompute_slot_geometry(slot, order, bump=False):
    slot_days = int(slot["requested_slot_days"]) + int(order["rework_days"])
    slot["slot_days"] = slot_days
    slot["end_date"] = store.add_days(slot["start_date"], slot_days)
    if bump:
        store.touch(slot)
    return slot


def set_order_fulfillment(order, new_status):
    order["fulfillment_status"] = new_status
    store.touch(order)
    return order
