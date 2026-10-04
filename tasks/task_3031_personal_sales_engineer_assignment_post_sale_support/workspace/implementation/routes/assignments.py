"""The customer book: assignment creation, acceptance, endings, coverage.

PRD §2.4, §2.5, §3.1.
"""

from db import DB, iso, parse_dt
from errors import ApiError, Err, invalid_value
from middleware import guard, require_engineer_owner
from response import (as_enum, as_instant, as_int, as_str, body, created_obj,
                      ensure_known, has, ok_obj, page)
from services import core

REASON_CODES = ("NEW_ACCOUNT", "PERMANENT_TRANSFER", "REGION_CHANGE",
                "TEMPORARY_COVERAGE")
ASSIGNMENT_ROLES = ["PlatformAdmin", "SalesEngineerOps", "Engineer"]


def next_sequence(customer_id, exclude_id=None):
    """The next reassignment index on this book.

    The row being activated is skipped: creation already reserved it a slot, so
    counting it would double-advance the index and the first assignment an
    account ever receives would not carry sequence 1 (PRD §2.4).
    """
    highest = 0
    for row in core.assignments_for_customer(customer_id):
        if row["id"] == exclude_id:
            continue
        highest = max(highest, int(row.get("sequence") or 0))
    return highest + 1


def register(app):
    @app.route("/assignments", methods=["POST"])
    def create_assignment():
        guard(["SalesEngineerOps", "PlatformAdmin"])
        data = body()
        ensure_known(data, ["customer_id", "engineer_id", "reason_code",
                            "commission_share_bps", "effective_until",
                            "expected_customer_version"],
                     optional=("commission_share_bps", "effective_until"))

        customer = core.fetch("customers", as_str(data, "customer_id", required=True),
                              Err.CUSTOMER_NOT_FOUND)
        engineer = core.fetch("engineers", as_str(data, "engineer_id", required=True),
                              Err.ENGINEER_NOT_FOUND)
        reason_code = as_enum(data, "reason_code", REASON_CODES)
        share_bps = as_int(data, "commission_share_bps", default=5000)
        effective_until = None
        if has(data, "effective_until"):
            effective_until = as_instant(data, "effective_until", required=True)

        # --- priority 16: the share may not exceed the engineer's cap ---
        if share_bps > int(engineer.get("commission_cap_bps") or 5000):
            raise ApiError(Err.COMMISSION_CAP_EXCEEDED)

        # --- validation precedence (PRD §2.11): request-shape checks precede
        # the optimistic-concurrency comparison, which in turn precedes the
        # domain business rules.  The temporary-coverage pairing is a request
        # shape check, so it is evaluated before the version guard.
        temporary = reason_code == "TEMPORARY_COVERAGE"
        if temporary and effective_until is None:
            raise ApiError(Err.TEMPORARY_COVERAGE_UNTIL_REQUIRED)
        if not temporary and effective_until is not None:
            raise ApiError(Err.TEMPORARY_COVERAGE_UNTIL_REQUIRED)

        # --- priority 34: optimistic concurrency on the customer's book ---
        expected = as_int(data, "expected_customer_version", required=True)
        if int(customer.get("version") or 1) != expected:
            raise ApiError(Err.STALE_VERSION)

        # --- priority 11: the requested coverage window must be disjoint from
        # every ENDED interval on this book (PRD §2.4).
        if core.covered_overlap(customer["id"], DB.now()):
            raise ApiError(Err.ASSIGNMENT_COVERAGE_OVERLAP)

        row = core.new_row(
            "assignments",
            customer_id=customer["id"],
            engineer_id=engineer["id"],
            reason_code=reason_code,
            commission_share_bps=share_bps,
            effective_until=iso(effective_until),
            sequence=next_sequence(customer["id"]),
            assigned_at=None,
            status="PENDING_ACCEPT",
            _ended_at=None,
        )
        # The creation is a write against the customer's book (PRD §2.5).
        core.bump(customer)
        core.recompute_active_book_size(engineer["id"])
        return created_obj(core.public(row))

    @app.route("/assignments", methods=["GET"])
    def list_assignments():
        guard(ASSIGNMENT_ROLES)
        return page(core.all_rows("assignments"), filters=(
            ("engineer_id", "engineer_id", None),
            ("customer_id", "customer_id", None),
            ("status", "status", None),
        ))

    @app.route("/assignments/<ident>", methods=["GET"])
    def get_assignment(ident):
        guard(ASSIGNMENT_ROLES)
        return ok_obj(core.public(core.fetch("assignments", ident,
                                             Err.CUSTOMER_NOT_FOUND)))

    @app.route("/assignments/<ident>/accept", methods=["POST"])
    def accept_assignment(ident):
        user_id, role = guard(["Engineer"])
        assignment = core.fetch("assignments", ident, Err.ENGINEER_NOT_FOUND)
        core.require_state(assignment, ("PENDING_ACCEPT"))
        require_engineer_owner(user_id, role, assignment)
        engineer = core.fetch("engineers", assignment["engineer_id"],
                              Err.ENGINEER_NOT_FOUND)
        if engineer.get("status") != "ACTIVE":
            raise ApiError(Err.INVALID_STATE,
                           "Only an ACTIVE engineer may take on book rows.")
        holder = core.active_assignment(assignment["customer_id"])
        if holder is not None and holder["id"] != assignment["id"]:
            raise ApiError(Err.INVALID_STATE,
                           "Another assignment already holds this customer's book.")
        if int(engineer.get("active_book_size") or 0) >= int(engineer.get("max_book_size") or 0):
            raise ApiError(Err.BOOK_CAPACITY_EXCEEDED)

        now = DB.now()
        assignment["status"] = "ACTIVE"
        assignment["assigned_at"] = iso(now)
        assignment["_ended_at"] = None
        # Acceptance advances the BOOK's reassignment index and the row adopts
        # it: the sequence starts at 1 for the first assignment an account ever
        # receives and increments each time the book changes hands (PRD §2.4).
        sequence = next_sequence(assignment["customer_id"], assignment["id"])
        assignment["sequence"] = sequence
        for other in core.assignments_for_customer(assignment["customer_id"]):
            if other["id"] != assignment["id"] and int(other.get("sequence") or 0) >= sequence:
                other["sequence"] = sequence + 1
                core.touch(other)
        core.touch(assignment)
        core.recompute_active_book_size(engineer["id"])
        customer = core.fetch("customers", assignment["customer_id"],
                              Err.CUSTOMER_NOT_FOUND)
        core.recompute_customer_mirror(customer["id"])
        core.bump(customer)
        core.recompute_entitlement(customer["id"])
        return ok_obj(core.public(assignment))

    @app.route("/assignments/<ident>/decline", methods=["POST"])
    def decline_assignment(ident):
        user_id, role = guard(["Engineer"])
        assignment = core.fetch("assignments", ident, Err.ENGINEER_NOT_FOUND)
        core.require_state(assignment, ("PENDING_ACCEPT"))
        require_engineer_owner(user_id, role, assignment)
        # Customer.assigned_engineer_id is left exactly as it was -- still null,
        # because a proposal that was never accepted must not perturb the book.
        core.end_assignment_row(assignment, DB.now())
        return ok_obj(core.public(assignment))

    @app.route("/assignments/<ident>/end", methods=["POST"])
    def end_assignment(ident):
        user_id, role = guard(["SalesEngineerOps", "PlatformAdmin"])
        assignment = core.fetch("assignments", ident, Err.ENGINEER_NOT_FOUND)
        core.require_state(assignment, ("ACTIVE"))
        core.end_assignment_row(assignment, DB.now())

        customer = core.fetch("customers", assignment["customer_id"],
                              Err.CUSTOMER_NOT_FOUND)
        core.recompute_active_book_size(assignment["engineer_id"])
        core.recompute_customer_mirror(customer["id"])
        core.bump(customer)

        # Hop 1/2: entitlement downgrade.  Hop 3/4: escalate this customer's
        # open EXTENDED-entitlement tickets and consume a desk slot for each.
        core.recompute_entitlement(customer["id"])
        for ticket in DB.all("support_tickets"):
            if ticket["customer_id"] != customer["id"]:
                continue
            if ticket["status"] not in ("OPEN", "IN_TRIAGE"):
                continue
            if ticket.get("required_entitlement") != "EXTENDED":
                continue
            ticket["status"] = "ESCALATED"
            ticket["escalated_at"] = iso(DB.now())
            ticket["escalated_by"] = user_id
            ticket["escalation_seq"] = core.next_escalation_seq(ticket["id"])
            core.append_ledger(ticket, ticket.get("service_center_id"),
                               "SERVICE_DEPARTMENT_ESCALATION")
            if ticket.get("service_center_id"):
                core.adjust_open_tickets(ticket["service_center_id"], 1)
            core.recompute_escalation_count(ticket)
            core.touch(ticket)
        return ok_obj(core.public(assignment))

    @app.route("/assignments/<ident>/reopen", methods=["POST"])
    def reopen_assignment(ident):
        guard(["SalesEngineerOps", "PlatformAdmin"])
        data = body()
        ensure_known(data, ["expected_customer_version"],
                     optional=("expected_customer_version",))
        assignment = core.fetch("assignments", ident, Err.ENGINEER_NOT_FOUND)
        core.require_state(assignment, ("ENDED"))
        engineer = core.fetch("engineers", assignment["engineer_id"],
                              Err.ENGINEER_NOT_FOUND)
        if engineer.get("status") != "ACTIVE":
            raise ApiError(Err.INVALID_STATE,
                           "Only an ACTIVE engineer may take on book rows.")
        holder = core.active_assignment(assignment["customer_id"])
        if holder is not None and holder["id"] != assignment["id"]:
            raise ApiError(Err.INVALID_STATE,
                           "Another assignment already holds this customer's book.")

        now = DB.now()
        # Priority 11: the re-proposed window must not overlap a later-sequence
        # ended interval on this book.  Adjacency at an identical instant is
        # permitted, hence the strict comparison.
        if core.covered_overlap(assignment["customer_id"], now,
                                exclude_id=assignment["id"]):
            raise ApiError(Err.ASSIGNMENT_COVERAGE_OVERLAP)
        if int(engineer.get("active_book_size") or 0) >= int(engineer.get("max_book_size") or 0):
            raise ApiError(Err.BOOK_CAPACITY_EXCEEDED)

        assignment["status"] = "ACTIVE"
        assignment["assigned_at"] = iso(now)
        assignment["_ended_at"] = None
        sequence = int(assignment.get("sequence") or 0) + 1
        assignment["sequence"] = sequence
        for other in core.assignments_for_customer(assignment["customer_id"]):
            if other["id"] != assignment["id"] and int(other.get("sequence") or 0) >= sequence:
                other["sequence"] = sequence + 1
                core.touch(other)
        core.touch(assignment)
        core.recompute_active_book_size(engineer["id"])
        customer = core.fetch("customers", assignment["customer_id"],
                              Err.CUSTOMER_NOT_FOUND)
        core.recompute_customer_mirror(customer["id"])
        core.bump(customer)
        core.recompute_entitlement(customer["id"])
        return ok_obj(core.public(assignment))

    # ---- customer lifecycle ---------------------------------------------
    @app.route("/customers/<ident>/activate", methods=["POST"])
    def activate_customer(ident):
        guard(["SalesEngineerOps", "PlatformAdmin"])
        customer = core.fetch("customers", ident, Err.CUSTOMER_NOT_FOUND)
        core.require_state(customer, ("PENDING",))
        customer["status"] = "ACTIVE"
        core.touch(customer)
        return ok_obj(core.public(customer))

    @app.route("/customers/<ident>/suspend", methods=["POST"])
    def suspend_customer(ident):
        guard(["PlatformAdmin"])
        customer = core.fetch("customers", ident, Err.CUSTOMER_NOT_FOUND)
        core.require_state(customer, ("ACTIVE",))
        customer["status"] = "PENDING"
        _end_book(customer)
        core.touch(customer)
        return ok_obj(core.public(customer))

    @app.route("/customers/<ident>/close", methods=["POST"])
    def close_customer(ident):
        guard(["PlatformAdmin"])
        customer = core.fetch("customers", ident, Err.CUSTOMER_NOT_FOUND)
        core.require_state(customer, ("PENDING", "ACTIVE"))
        customer["status"] = "CLOSED"
        _end_book(customer)
        core.touch(customer)
        return ok_obj(core.public(customer))


def _end_book(customer):
    """End every open assignment on a suspended or closed account."""
    now = DB.now()
    for assignment in core.assignments_for_customer(customer["id"]):
        if assignment["status"] not in ("PENDING_ACCEPT", "ACTIVE"):
            continue
        core.end_assignment_row(assignment, now)
        core.recompute_active_book_size(assignment["engineer_id"])
    core.recompute_customer_mirror(customer["id"])
    core.recompute_entitlement(customer["id"])