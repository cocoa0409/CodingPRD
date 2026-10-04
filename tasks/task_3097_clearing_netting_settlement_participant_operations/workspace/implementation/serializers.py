"""Resource serialization.

Each serializer emits exactly the fields the entity table declares, with the
computed fields derived at read time from the live store.
"""

from db import db
from services.deposit import posted_amount_cents

PARTICIPANT_FIELDS = (
    "id",
    "legal_name",
    "lei",
    "participant_class",
    "membership_status",
    "net_capital_cents",
    "required_min_net_capital_cents",
    "financial_standard_status",
    "is_defaulted",
    "requires_segregated_custody",
    "last_financial_review_at",
    "created_at",
    "updated_at",
    "version",
)

SECURITY_FIELDS = (
    "id",
    "ticker",
    "cusip",
    "currency",
    "prev_settlement_price_cents",
    "current_volatility_bps",
    "created_at",
    "updated_at",
    "version",
)

DEPOSIT_FIELDS = (
    "id",
    "participant_id",
    "posted_amount_cents",
    "status",
    "created_at",
    "updated_at",
    "version",
)

WINDOW_FIELDS = (
    "id",
    "security_id",
    "settlement_date",
    "trade_entry_deadline",
    "affirmation_deadline",
    "status",
    "created_at",
    "updated_at",
    "version",
)

TRADE_FIELDS = (
    "id",
    "participant_id",
    "counterparty_participant_id",
    "security_id",
    "side",
    "quantity",
    "trade_price_cents",
    "trade_date",
    "lock_status",
    "match_status",
    "affirmation_status",
    "allegations_received",
    "created_at",
    "updated_at",
    "version",
)

ACCOUNT_FIELDS = (
    "id",
    "participant_id",
    "account_number",
    "account_type",
    "status",
    "created_at",
    "updated_at",
    "version",
)

CORPORATE_ACTION_FIELDS = (
    "id",
    "security_id",
    "action_type",
    "ratio_numerator",
    "ratio_denominator",
    "cash_rate_cents_per_unit",
    "effective_date",
    "status",
    "applied_at",
    "created_at",
    "updated_at",
    "version",
)

FUND_FIELDS = (
    "id",
    "security_id",
    "status",
    "fund_balance_cents",
    "total_component_cents",
    "last_computed_at",
    "participant_class",
    "experiences_deficit",
    "created_at",
    "updated_at",
    "version",
)

COMPONENT_FIELDS = (
    "id",
    "clearing_fund_id",
    "participant_id",
    "component_amount_cents",
    "component_balance_cents",
    "generation",
    "status",
    "created_at",
    "updated_at",
    "version",
)

PROCEEDING_FIELDS = (
    "id",
    "participant_id",
    "reason_code",
    "status",
    "liquidation_proceeds_cents",
    "deficit_amount_cents",
    "defaulter_resources_cents",
    "allocated_total_cents",
    "created_at",
    "updated_at",
    "version",
)

LEDGER_FIELDS = (
    "id",
    "deposit_id",
    "participant_id",
    "amount_cents",
    "txn_type",
    "reason_code",
    "created_at",
)


def pick(record, fields):
    return {field: record.get(field) for field in fields}


def participant(record):
    return pick(record, PARTICIPANT_FIELDS)


def security(record):
    out = pick(record, SECURITY_FIELDS)
    out["prev_settlement_price_cents"] = record["prev_settlement_price_cents"]
    out["current_volatility_bps"] = record["current_volatility_bps"]
    return out


def deposit(record):
    out = pick(record, DEPOSIT_FIELDS)
    out["posted_amount_cents"] = posted_amount_cents(record)
    out["status"] = record["status"]
    return out


def deposit_transaction(record):
    return pick(record, LEDGER_FIELDS)


def trade(record):
    out = pick(record, TRADE_FIELDS)
    out["affirmation_status"] = record["affirmation_status"]
    return out


def window(record):
    return pick(record, WINDOW_FIELDS)


def net_position(record):
    out = {
        "id": record["id"],
        "window_id": record["window_id"],
        "participant_id": record["participant_id"],
        "security_id": record["security_id"],
        "net_quantity": record["net_quantity"],
        "cash_delta_cents": record["cash_delta_cents"],
        "settlement_obligation_cents": record["settlement_obligation_cents"],
        "dvp_status": record["dvp_status"],
        "funded_amount_cents": record["funded_amount_cents"],
        "failed_at": record["failed_at"],
        "failed_at_price_cents": record["failed_at_price_cents"],
        "mark_to_market_cents": record["mark_to_market_cents"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }
    return out


def custody_account(record):
    out = pick(record, ACCOUNT_FIELDS)
    out["positions"] = [
        {
            "id": position["id"],
            "security_id": position["security_id"],
            "settled_quantity": position["settled_quantity"],
            "last_corporate_action_applied_id": position["last_corporate_action_applied_id"],
        }
        for position in record["positions"]
    ]
    return out


def corporate_action(record):
    return pick(record, CORPORATE_ACTION_FIELDS)


def clearing_fund(record):
    out = pick(record, FUND_FIELDS)
    components = [
        comp for comp in db.fund_components.values()
        if comp["clearing_fund_id"] == record["id"]
    ]
    out["fund_balance_cents"] = sum(
        comp["component_balance_cents"]
        for comp in components
        if comp["status"] != "RELEASED"
    )
    out["total_component_cents"] = total_component_cents(record["id"])
    out["experiences_deficit"] = any(
        latest_component_amount(record["id"], participant_id) < 0
        for participant_id in participants_of_class(record["participant_class"])
    )
    return out


def total_component_cents(fund_id):
    total = 0
    for comp in db.fund_components.values():
        if comp["clearing_fund_id"] != fund_id:
            continue
        if comp["id"] == latest_component_id(fund_id, comp["participant_id"]):
            total += comp["component_amount_cents"]
    return total


def latest_component_id(fund_id, participant_id):
    rows = [
        comp for comp in db.fund_components.values()
        if comp["clearing_fund_id"] == fund_id and comp["participant_id"] == participant_id
    ]
    if not rows:
        return None
    rows.sort(key=lambda comp: (comp["created_at"], comp["id"]))
    return rows[-1]["id"]


def latest_component(fund_id, participant_id):
    rows = [
        comp for comp in db.fund_components.values()
        if comp["clearing_fund_id"] == fund_id and comp["participant_id"] == participant_id
    ]
    if not rows:
        return None
    rows.sort(key=lambda comp: (comp["created_at"], comp["id"]))
    return rows[-1]


def latest_component_amount(fund_id, participant_id):
    comp = latest_component(fund_id, participant_id)
    return comp["component_amount_cents"] if comp is not None else 0


def participants_of_class(participant_class):
    return [
        p["id"] for p in db.participants.values()
        if p["participant_class"] == participant_class and p["membership_status"] == "ACTIVE"
    ]


def fund_component(record):
    return pick(record, COMPONENT_FIELDS)


def default_proceeding(record):
    return pick(record, PROCEEDING_FIELDS)


def loss_allocation(record):
    return {
        "id": record["id"],
        "default_proceeding_id": record["default_proceeding_id"],
        "fund_component_id": record["fund_component_id"],
        "amount_cents": record["amount_cents"],
        "posted_at": record["posted_at"],
        "created_at": record["created_at"],
    }


def summarize(record):
    """Compact projection used where an endpoint returns its parent resource."""
    return record