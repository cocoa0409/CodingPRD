"""Lookups, batch derivation and the three cascades of PRD §2.11."""

import calc
from errors import ApiError
from store import db, order_by_created, touch

# ------------------------------------------------------------------ lookups ---

_NOT_FOUND = {
    "clients": "ERR_CLIENT_NOT_FOUND",
    "permit_accounts": "ERR_PERMIT_ACCOUNT_NOT_FOUND",
    "mail_jobs": "ERR_MAIL_JOB_NOT_FOUND",
    "commingle_batches": "ERR_BATCH_NOT_FOUND",
    "batch_members": "ERR_BATCH_MEMBER_NOT_FOUND",
    "sort_containers": "ERR_CONTAINER_NOT_FOUND",
    "entry_facilities": "ERR_ENTRY_FACILITY_NOT_FOUND",
    "postage_statements": "ERR_STATEMENT_NOT_FOUND",
    "drop_shipments": "ERR_DROP_SHIPMENT_NOT_FOUND",
    "service_level_records": "ERR_SERVICE_LEVEL_RECORD_NOT_FOUND",
    "client_invoices": "ERR_INVOICE_NOT_FOUND",
}


def must_get(collection, ident):
    record = getattr(db, collection).get(ident) if isinstance(ident, str) else None
    if record is None:
        raise ApiError(_NOT_FOUND[collection])
    return record


def get_client(ident):
    return must_get("clients", ident)


def get_permit(ident):
    return must_get("permit_accounts", ident)


def get_job(ident):
    return must_get("mail_jobs", ident)


def get_batch(ident):
    return must_get("commingle_batches", ident)


def get_facility(ident):
    return must_get("entry_facilities", ident)


def get_container(ident):
    return must_get("sort_containers", ident)


def get_statement(ident):
    return must_get("postage_statements", ident)


def get_shipment(ident):
    return must_get("drop_shipments", ident)


def get_slr(ident):
    return must_get("service_level_records", ident)


def get_invoice(ident):
    return must_get("client_invoices", ident)


# ------------------------------------------------------------- collections ---

def batch_members(batch_id):
    return order_by_created(
        [m for m in db.batch_members.values() if m["commingle_batch_id"] == batch_id]
    )


def batch_containers(batch_id):
    return sorted(
        [c for c in db.sort_containers.values() if c["commingle_batch_id"] == batch_id],
        key=lambda c: c["sequence_index"],
    )


def batch_statements(batch_id):
    return order_by_created(
        [
            s
            for s in db.postage_statements.values()
            if s["commingle_batch_id"] == batch_id
        ]
    )


def batch_shipments(batch_id):
    return order_by_created(
        [s for s in db.drop_shipments.values() if s["commingle_batch_id"] == batch_id]
    )


def member_for_job(job_id):
    for member in order_by_created(list(db.batch_members.values())):
        if member["mail_job_id"] == job_id:
            return member
    return None


def job_hygiene_runs(job_id):
    return sorted(
        [r for r in db.hygiene_runs.values() if r["mail_job_id"] == job_id],
        key=lambda r: r["run_index"],
    )


def statement_findings(statement_id):
    return order_by_created(
        [
            f
            for f in db.verification_findings.values()
            if f["postage_statement_id"] == statement_id
        ]
    )


def episode_findings(statement):
    """Findings recorded during the statement's current filing episode."""
    return [
        f
        for f in statement_findings(statement["id"])
        if f["_episode"] == statement["revision_index"]
    ]


def container_records(container_id):
    return order_by_created(
        [
            r
            for r in db.service_level_records.values()
            if r["sort_container_id"] == container_id
        ]
    )


# ------------------------------------------------ three-stage batch pricing ---

def derive_batch(batch, fresh_member_ids=()):
    """Stage one (tier), stage two (rate + batch postage), stage three (split).

    Rebuilds the batch's piece ledger from its currently attached members, then
    re-derives the tier, the rate, the batch postage and every member's
    share_basis_pct and allocated_postage_cents.
    """
    members = batch_members(batch["id"])
    total = sum(m["contributed_piece_count"] for m in members)
    batch["member_job_count"] = len(members)
    batch["total_piece_count"] = total

    facility = db.entry_facilities[batch["entry_facility_id"]]
    tier, rate, pool = calc.assess_postage(
        batch["mail_class"], total, facility["drop_ship_discount_bp"]
    )
    batch["achieved_tier"] = tier
    batch["rate_mills_per_piece"] = rate
    batch["batch_postage_cents"] = pool

    write_allocation(
        members, pool, "allocated_postage_cents", fresh_member_ids, with_share=True
    )


def write_allocation(members, pool_cents, field, fresh_member_ids=(), with_share=False):
    """Floor-plus-remainder allocation written onto `field` of each member."""
    if not members:
        return
    denominator = sum(m["contributed_piece_count"] for m in members)
    keyed = [(m["id"], m["contributed_piece_count"], m["_seq"]) for m in members]
    allocation = calc.allocate_pool(keyed, pool_cents)
    for member in members:
        changed = False
        amount = allocation.get(member["id"], 0)
        if member[field] != amount:
            member[field] = amount
            changed = True
        if with_share:
            share = calc.share_basis_pct(member["contributed_piece_count"], denominator)
            if member["share_basis_pct"] != share:
                member["share_basis_pct"] = share
                changed = True
        if changed and member["id"] not in fresh_member_ids:
            touch(member)


def reset_batch_pricing(batch):
    """Unwind performed by a returning verification (PRD §3.6 link 2)."""
    batch["achieved_tier"] = "NONE"
    batch["rate_mills_per_piece"] = 0
    batch["batch_postage_cents"] = 0


# ------------------------------------------------------------ dock capacity ---

def occupied_pallets(facility_id, window_start, window_end):
    """Half-open overlap geometry: touching endpoints do not overlap."""
    occupied = 0
    for shipment in db.drop_shipments.values():
        if shipment["entry_facility_id"] != facility_id:
            continue
        if shipment["status"] not in ("SCHEDULED", "IN_TRANSIT"):
            continue
        if (
            shipment["window_start_utc"] < window_end
            and window_start < shipment["window_end_utc"]
        ):
            occupied += shipment["pallet_count"]
    return occupied


def live_shipment_for_batch(batch_id):
    for shipment in order_by_created(list(db.drop_shipments.values())):
        if shipment["commingle_batch_id"] != batch_id:
            continue
        if shipment["status"] in ("SCHEDULED", "IN_TRANSIT"):
            return shipment
    return None


def accepted_statement(batch_id):
    for statement in batch_statements(batch_id):
        if statement["status"] in ("ACCEPTED_CLEAN", "ACCEPTED_WITH_ADJUSTMENT"):
            return statement
    return None


# ------------------------------------------------------------- billing scan ---

def client_invoices(client_id):
    return order_by_created(
        [i for i in db.client_invoices.values() if i["client_id"] == client_id]
    )


def overlapping_invoice(client_id, period_start, period_end):
    """Closed-interval exclusivity: adjacency conflicts (PRD §3.8)."""
    for invoice in client_invoices(client_id):
        if invoice["status"] not in ("ISSUED", "PAID"):
            continue
        if period_start <= invoice["period_end_utc"] and (
            invoice["period_start_utc"] <= period_end
        ):
            return invoice
    return None
