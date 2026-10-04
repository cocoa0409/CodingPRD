"""JSON serializers.

Each entity is rendered with the exact field names declared in SCAFFOLD S1.1 plus
the common quartet (id / created_at / updated_at / version) that PRD S2.5 assigns
to every entity except AuditEvent.  Derived (source: computed) fields are
calculated on read from the live store so a stale bucket or balance is never
served.
"""

from utils import iso_from_ms

COMMON = ("id", "created_at", "updated_at", "version")

REGISTRY = {}


def serializer(*entity_names):
    def deco(fn):
        for n in entity_names:
            REGISTRY[n] = fn
        return fn
    return deco


def with_common(row, payload):
    """Prepend the common quartet (or just id/created_at for AuditEvent)."""
    out = {}
    if "created_at" in row:
        out["id"] = row["id"]
        out["created_at"] = iso_from_ms(row["created_at"])
        if "updated_at" in row:
            out["updated_at"] = iso_from_ms(row["updated_at"])
        if "version" in row:
            out["version"] = row["version"]
    out.update(payload)
    return out


def _all_rows(store, collection, key, ledger_id):
    return [r for r in collection.values() if r.get(key) == ledger_id]


def pending_balance(ctx, ledger_id):
    return sum(r["net_effect_cents"] for r in ctx.store.transactions.values()
               if r["ledger_id"] == ledger_id
               and r["lifecycle_status"] not in ("VOID", "REJECTED")
               and r["settlement_status"] in ("UNSETTLED", "IN_SETTLEMENT"))


def posted_balance(ctx, ledger_id):
    return sum(r["net_effect_cents"] for r in ctx.store.transactions.values()
               if r["ledger_id"] == ledger_id
               and r["lifecycle_status"] not in ("VOID", "REJECTED")
               and r["settlement_status"] == "SETTLED")


# ---------------------------------------------------------------- Ledger

@serializer("Ledger")
def ser_ledger(row, ctx):
    return with_common(row, {
        "name": row["name"],
        "currency": row["currency"],
        "period_index": row["period_index"],
        "period_opened_utc": iso_from_ms(row["period_opened_utc"]),
        "period_closed_through_index": row["period_closed_through_index"],
        "pending_balance_cents": pending_balance(ctx, row["id"]),
        "posted_balance_cents": posted_balance(ctx, row["id"]),
        "delivered_fee_transfers_cents": row["delivered_fee_transfers_cents"],
        "undeliverable_cents": row["undeliverable_cents"],
        "status": row["status"],
    })


# ---------------------------------------------------------------- LegalEntity

@serializer("LegalEntity")
def ser_legal_entity(row, ctx):
    return with_common(row, {
        "legal_name": row["legal_name"],
        "short_code": row["short_code"],
        "entity_type": row["entity_type"],
        "home_ledger_id": row["home_ledger_id"],
        "default_velocity_limit_cents": row["default_velocity_limit_cents"],
    })


# ---------------------------------------------------------------- Counterparty

def effective_limit_cents(ctx, counterparty):
    if counterparty.get("velocity_limit_cents") is not None:
        return counterparty["velocity_limit_cents"]
    entity = ctx.store.legal_entities.get(counterparty.get("legal_entity_id"))
    if entity is not None:
        return entity["default_velocity_limit_cents"]
    return 5000000


@serializer("Counterparty")
def ser_counterparty(row, ctx):
    return with_common(row, {
        "legal_entity_id": row["legal_entity_id"],
        "display_name": row["display_name"],
        "external_ref": row["external_ref"],
        "velocity_limit_cents": row["velocity_limit_cents"],
        "effective_velocity_limit_cents": effective_limit_cents(ctx, row),
        "status": row["status"],
    })


# ---------------------------------------------------------------- Relationship

@serializer("CounterpartyRelationship")
def ser_relationship(row, ctx):
    return with_common(row, {
        "legal_entity_id": row["legal_entity_id"],
        "partner_legal_entity_id": row["partner_legal_entity_id"],
        "purpose": row["purpose"],
        "account_data_sharing": row["account_data_sharing"],
        "status": row["status"],
    })


# ---------------------------------------------------------------- BankAccount

@serializer("BankAccount")
def ser_bank_account(row, ctx):
    pool_status = ctx.pool_forced_status(row["id"])
    return with_common(row, {
        "legal_entity_id": row["legal_entity_id"],
        "institution_name": row["institution_name"],
        "routing_number": row["routing_number"],
        "account_number_last4": row["account_number_last4"],
        "supported_rails": list(row["supported_rails"]),
        "available_funds_cents": row["available_funds_cents"],
        "forced_settlement_status": pool_status,
        "status": row["status"],
    })


# ---------------------------------------------------------------- VirtualAccount

@serializer("VirtualAccount")
def ser_virtual_account(row, ctx):
    return with_common(row, {
        "bank_account_id": row["bank_account_id"],
        "virtual_account_number": row["virtual_account_number"],
        "reference_code": row["reference_code"],
        "status": row["status"],
    })


# ---------------------------------------------------------------- BankStatement

@serializer("BankStatement")
def ser_bank_statement(row, ctx):
    return with_common(row, {
        "bank_account_id": row["bank_account_id"],
        "institution_ref": row["institution_ref"],
        "cycle_date": iso_from_ms(row["cycle_date_ms"]),
        "opening_balance_cents": row["opening_balance_cents"],
        "closing_balance_cents": row["closing_balance_cents"],
        "matching_algorithm": row["matching_algorithm"],
        "revision_number": row["revision_number"],
        "supersedes_statement_id": row["supersedes_statement_id"],
        "matched_posted_cents": row["matched_posted_cents"],
        "unmatched_amount_cents": row["unmatched_amount_cents"],
        "status": row["status"],
    })


# ---------------------------------------------------------------- StatementLine

@serializer("StatementLine")
def ser_statement_line(row, ctx):
    return with_common(row, {
        "bank_statement_id": row["bank_statement_id"],
        "bank_reference": row["bank_reference"],
        "amount_cents": row["amount_cents"],
        "direction": row["direction"],
        "effective_at": iso_from_ms(row["effective_at_ms"]),
        "embedded_reference_code": row["embedded_reference_code"],
        "match_state": row["match_state"],
    })


# ---------------------------------------------------------------- PaymentOrder

@serializer("PaymentOrder")
def ser_payment_order(row, ctx):
    return with_common(row, {
        "legal_entity_id": row["legal_entity_id"],
        "ledger_id": row["ledger_id"],
        "counterparty_id": row["counterparty_id"],
        "source_account_id": row["source_account_id"],
        "rail": row["rail"],
        "direction": row["direction"],
        "amount_cents": row["amount_cents"],
        "settlement_speed": row["settlement_speed"],
        "idempotency_key": row["idempotency_key"],
        "payable_to_name": row.get("payable_to_name"),
        "requested_release_utc": (iso_from_ms(row["requested_release_utc"])
                                  if row.get("requested_release_utc") is not None else None),
        "cutoffs": [{"rail": c["rail"],
                    "cutoff_utc": iso_from_ms(c["_cutoff_ms"]),
                    "calendar_code": c["calendar_code"]} for c in row["cutoffs"]],
        "cutoff_snapshot_utc": (iso_from_ms(row["cutoff_snapshot_ms"])
                                if row.get("cutoff_snapshot_ms") is not None else None),
        "status": row["status"],
        "settlement_status": row["settlement_status"],
        "initiator_user_id": row["initiator_user_id"],
        "approver_user_id": row["approver_user_id"],
        "return_reason": row["return_reason"],
        "failure_reason": row.get("failure_reason"),
    })


# ---------------------------------------------------------------- Transaction

@serializer("Transaction")
def ser_transaction(row, ctx):
    return with_common(row, {
        "ledger_id": row["ledger_id"],
        "payment_order_id": row["payment_order_id"],
        "entry_type": row["entry_type"],
        "direction": row["direction"],
        "amount_cents": row["amount_cents"],
        "net_effect_cents": row["net_effect_cents"],
        "value_effective_utc": iso_from_ms(row["value_effective_utc"]),
        "reverses_transaction_id": row["reverses_transaction_id"],
        "refunds_transaction_id": row["refunds_transaction_id"],
        "lifecycle_status": row["lifecycle_status"],
        "settlement_status": row["settlement_status"],
        "sequence": row["sequence"],
    })


# ---------------------------------------------------------------- ExceptionItem

@serializer("ExceptionItem")
def ser_exception(row, ctx):
    age = ctx.exception_age_days(row)
    return with_common(row, {
        "ledger_id": row["ledger_id"],
        "payment_order_id": row["payment_order_id"],
        "bank_statement_id": row["bank_statement_id"],
        "kind": row["kind"],
        "amount_cents": row["amount_cents"],
        "attributed_fee_cents": row["attributed_fee_cents"],
        "attributable_amount_cents": row["attributable_amount_cents"],
        "opened_utc": iso_from_ms(row["opened_utc"]),
        "closing_period_utc": iso_from_ms(row["closing_period_utc"]),
        "age_business_days": age,
        "aging_bucket": ctx.aging_bucket(age),
        "status": row["status"],
        "assignee_user_id": row["assignee_user_id"],
        "resolution_note": row["resolution_note"],
    })


# ---------------------------------------------------------------- AuditEvent

@serializer("AuditEvent")
def ser_audit_event(row, ctx):
    return {
        "id": row["id"],
        "created_at": iso_from_ms(row["created_at"]),
        "ledger_id": row["ledger_id"],
        "actor_user_id": row["actor_user_id"],
        "actor_role": row["actor_role"],
        "action": row["action"],
        "target_entity_type": row["target_entity_type"],
        "target_entity_id": row["target_entity_id"],
        "sequence_number": row["sequence_number"],
        "details": row["details"],
    }


# ---------------------------------------------------------------- SettlementPool

@serializer("SettlementPool")
def ser_settlement_pool(row, ctx):
    return with_common(row, {
        "ledger_id": row["ledger_id"],
        "name": row["name"],
        "member_bank_account_ids": list(row["member_bank_account_ids"]),
        "forced_settlement_status": ctx.pool_forced_status_for_pool(row),
        "status": row["status"],
    })


# ---------------------------------------------------------------- PoolMembership

@serializer("PoolMembership")
def ser_pool_membership(row, ctx):
    return with_common(row, {
        "settlement_pool_id": row["settlement_pool_id"],
        "bank_account_id": row["bank_account_id"],
        "weight_units": row["weight_units"],
    })


# ---------------------------------------------------------------- ReleaseRequest

@serializer("ReleaseRequest")
def ser_release_request(row, ctx):
    return with_common(row, {
        "payment_order_id": row["payment_order_id"],
        "counterparty_id": row["counterparty_id"],
        "initiator_user_id": row["initiator_user_id"],
        "needed_by_utc": iso_from_ms(row["needed_by_utc"]),
        "reason": row["reason"],
        "request_state": row["request_state"],
    })


# ---------------------------------------------------------------- BankingCalendar

@serializer("BankingCalendar")
def ser_banking_calendar(row, ctx):
    return with_common(row, {
        "legal_entity_id": row["legal_entity_id"],
        "calendar_date": row["calendar_date"],
        "timezone": row["timezone"],
        "is_open": bool(row["is_open"]),
        "cutoffs": [{k: v for k, v in c.items() if not k.startswith("_")}
                    for c in row["cutoffs"]],
        "allowed_rails": list(row["allowed_rails"]),
    })


def serialize(entity_name, row, ctx):
    return REGISTRY[entity_name](row, ctx)


def serialize_many(entity_name, rows, ctx):
    return [REGISTRY[entity_name](r, ctx) for r in rows]