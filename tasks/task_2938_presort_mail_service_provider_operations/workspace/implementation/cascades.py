"""The multi-link state cascades: sortation, verification, deposit and revision.

Every precondition is checked by the caller before any of these run, so a
partial cascade is never an observable outcome (PRD §2.11).
"""

import calc
import domain
from store import db, touch


def _member_jobs(batch_id):
    """Member jobs in batch-member creation order."""
    jobs = []
    for member in domain.batch_members(batch_id):
        job = db.mail_jobs.get(member["mail_job_id"])
        if job is not None:
            jobs.append((member, job))
    return jobs


# ------------------------------------------------------- closing sortation ---

def close_sortation(batch):
    batch["status"] = "SORTED"
    domain.derive_batch(batch)
    facility = db.entry_facilities[batch["entry_facility_id"]]
    for _member, job in _member_jobs(batch["id"]):
        if job["status"] == "POOLED":
            job["status"] = "PRESORTED"
            job["postage_due_cents"] = 0
            touch(job)
    for container in domain.batch_containers(batch["id"]):
        if container["status"] == "STAGED":
            container["status"] = "DOCUMENTED"
            container["placard_id"] = "%s-%s-%d" % (
                facility["facility_code"],
                container["destination_zip3"],
                container["sequence_index"],
            )
            touch(container)
    touch(batch)


# ---------------------------------------------------- verification outcomes ---

def accept_clean(statement, batch, permit, user_id):
    statement["status"] = "ACCEPTED_CLEAN"
    statement["verified_by_user_id"] = user_id
    statement["adjustment_cents"] = 0
    statement["verified_postage_cents"] = statement["declared_postage_cents"]

    permit["reserved_cents"] -= statement["declared_postage_cents"]
    touch(permit)

    for member, job in _member_jobs(batch["id"]):
        member["allocated_adjustment_cents"] = 0
        touch(member)
        job["postage_due_cents"] = member["allocated_postage_cents"]
        touch(job)
        client = db.clients.get(job["client_id"])
        if client is not None:
            client["unbilled_postage_cents"] += job["postage_due_cents"]
            touch(client)
    touch(statement)


def accept_with_adjustment(statement, batch, permit, user_id):
    adjustment = statement["adjustment_cents"]
    statement["status"] = "ACCEPTED_WITH_ADJUSTMENT"
    statement["verified_by_user_id"] = user_id
    statement["verified_postage_cents"] = (
        statement["declared_postage_cents"] + adjustment
    )

    permit["reserved_cents"] -= statement["declared_postage_cents"]
    permit["balance_cents"] -= adjustment
    touch(permit)

    members = domain.batch_members(batch["id"])
    domain.write_allocation(members, adjustment, "allocated_adjustment_cents")

    for member, job in _member_jobs(batch["id"]):
        job["postage_due_cents"] = (
            member["allocated_postage_cents"] + member["allocated_adjustment_cents"]
        )
        touch(job)
        client = db.clients.get(job["client_id"])
        if client is not None:
            client["unbilled_postage_cents"] += job["postage_due_cents"]
            touch(client)
    touch(statement)


def return_for_correction(statement, batch, permit, user_id):
    statement["status"] = "RETURNED_FOR_CORRECTION"
    statement["verified_by_user_id"] = user_id
    statement["adjustment_cents"] = 0
    statement["verified_postage_cents"] = 0

    # link 1 — release the encumbrance, total funds unchanged
    permit["reserved_cents"] -= statement["declared_postage_cents"]
    permit["balance_cents"] += statement["declared_postage_cents"]
    touch(permit)

    # link 2 — the batch loses its pricing
    batch["status"] = "REWORK"
    domain.reset_batch_pricing(batch)
    touch(batch)

    # link 3 — members, jobs and containers
    pairs = _member_jobs(batch["id"])
    for member, _job in pairs:
        member["allocated_postage_cents"] = 0
        member["allocated_adjustment_cents"] = 0
        member["share_basis_pct"] = None
        touch(member)
    reworked = []
    for _member, job in pairs:
        if job["status"] == "PRESORTED":
            job["status"] = "REWORK"
            job["rework_count"] += 1
            job["postage_due_cents"] = 0
            touch(job)
            reworked.append(job)
    for container in domain.batch_containers(batch["id"]):
        if container["status"] == "DOCUMENTED":
            container["status"] = "RETURNED"
            touch(container)

    # link 4 — repeated rework suspends the mailer
    for job in reworked:
        if job["rework_count"] < calc.REWORK_SUSPEND_THRESHOLD:
            continue
        client = db.clients.get(job["client_id"])
        if client is not None and client["status"] == "ACTIVE":
            client["status"] = "SUSPENDED"
            client["suspension_reason"] = calc.REWORK_SUSPENSION_REASON
            touch(client)
    touch(statement)


# ------------------------------------------------------------------ revision ---

def revise(statement, batch):
    statement["status"] = "DRAFT"
    statement["revision_index"] += 1
    statement["adjustment_cents"] = 0
    statement["verified_postage_cents"] = 0
    statement["verification_error_count"] = 0
    statement["submitted_by_user_id"] = None
    statement["verified_by_user_id"] = None

    # the batch returns REWORK -> OPEN and recomputes itself first
    batch["status"] = "OPEN"
    domain.derive_batch(batch)
    for _member, job in _member_jobs(batch["id"]):
        if job["status"] == "REWORK":
            job["status"] = "POOLED"
            touch(job)
    for container in domain.batch_containers(batch["id"]):
        if container["status"] == "RETURNED":
            container["status"] = "STAGED"
            container["placard_id"] = None
            touch(container)
    touch(batch)

    # only afterwards does the statement re-freeze
    statement["statement_piece_count"] = batch["total_piece_count"]
    statement["rate_mills_per_piece"] = batch["rate_mills_per_piece"]
    statement["declared_postage_cents"] = calc.postage_cents(
        statement["statement_piece_count"], statement["rate_mills_per_piece"]
    )
    touch(statement)


# -------------------------------------------------------------------- void ---

def void_statement(statement, reason):
    was_submitted = statement["status"] == "SUBMITTED"
    statement["status"] = "VOID"
    statement["void_reason"] = reason
    if was_submitted:
        permit = db.permit_accounts.get(statement["permit_account_id"])
        if permit is not None:
            permit["reserved_cents"] -= statement["declared_postage_cents"]
            permit["balance_cents"] += statement["declared_postage_cents"]
            touch(permit)
        batch = db.commingle_batches.get(statement["commingle_batch_id"])
        if batch is not None and batch["status"] == "DOCUMENTED":
            batch["status"] = "SORTED"
            touch(batch)
    touch(statement)


# ----------------------------------------------------------------- deposit ---

def deposit(shipment, batch):
    now = db.now()
    shipment["status"] = "DEPOSITED"
    shipment["deposited_at_utc"] = now
    touch(shipment)

    # link 1
    batch["status"] = "CLOSED"
    touch(batch)

    # link 2 + link 3 (containers, then one service-level record each)
    for container in domain.batch_containers(batch["id"]):
        if container["status"] != "DOCUMENTED":
            continue
        container["status"] = "DEPOSITED"
        touch(container)
        db.insert(
            "service_level_records",
            {
                "sort_container_id": container["id"],
                "zone": container["zone"],
                "committed_days": container["committed_days"],
                "piece_count": container["piece_count"],
                "deposited_at_utc": now,
                "actual_delivery_days": None,
                "scanned_at_utc": None,
                "on_time": None,
            },
        )

    # link 3 (jobs) + link 4 (client lifetime counter)
    for _member, job in _member_jobs(batch["id"]):
        if job["status"] != "PRESORTED":
            continue
        job["status"] = "MAILED"
        job["mailed_at_utc"] = now
        touch(job)
        client = db.clients.get(job["client_id"])
        if client is not None:
            client["lifetime_pieces_mailed"] += job["accepted_piece_count"]
            touch(client)
