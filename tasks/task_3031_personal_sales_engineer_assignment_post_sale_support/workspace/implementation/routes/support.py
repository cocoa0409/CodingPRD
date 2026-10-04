"""Tech-support tickets, escalation to the service department, ledger reads.

PRD §3.7.
"""

from db import DB, iso
from errors import ApiError, Err
from middleware import guard
from response import (as_enum, as_str, body, created_obj, ensure_known,
                      has, ok_obj, page)
from services import calc, core

CHANNELS = ("PHONE", "EMAIL", "CHAT")
TICKET_ROLES = ["PlatformAdmin", "SupportAgent", "ServiceDepartment"]
LEDGER_ROLES = ["PlatformAdmin", "SupportAgent", "ServiceDepartment"]


def register(app):
    @app.route("/support-tickets", methods=["POST"])
    def create_ticket():
        guard(["SupportAgent", "Anonymous"])
        data = body()
        ensure_known(data, ["customer_id", "subject", "channel",
                            "service_center_id"])
        customer = core.fetch("customers", as_str(data, "customer_id", required=True),
                              Err.CUSTOMER_NOT_FOUND)
        center = core.fetch("service_centers",
                            as_str(data, "service_center_id", required=True),
                            Err.REFERENCED_RESOURCE_NOT_FOUND)
        row = core.new_row(
            "support_tickets",
            customer_id=customer["id"],
            subject=as_str(data, "subject", required=True),
            channel=as_enum(data, "channel", CHANNELS),
            service_center_id=center["id"],
            status="OPEN",
            required_entitlement="BASIC",
            escalated_at=None,
            escalated_by=None,
            prior_service_center_id=None,
            escalation_seq=0,
            escalation_count=0,
        )
        return created_obj(core.public(row))

    @app.route("/support-tickets", methods=["GET"])
    def list_tickets():
        guard(TICKET_ROLES)
        return page(core.all_rows("support_tickets"), filters=(
            ("customer_id", "customer_id", None),
            ("service_center_id", "service_center_id", None),
            ("status", "status", None),
        ))

    @app.route("/support-tickets/<ident>", methods=["GET"])
    def get_ticket(ident):
        guard(TICKET_ROLES)
        return ok_obj(core.public(core.fetch("support_tickets", ident,
                                             Err.REFERENCED_RESOURCE_NOT_FOUND)))

    @app.route("/support-tickets/<ident>/triage", methods=["POST"])
    def triage_ticket(ident):
        guard(["SupportAgent"])
        ticket = core.fetch("support_tickets", ident,
                            Err.REFERENCED_RESOURCE_NOT_FOUND)
        core.require_state(ticket, ("OPEN",))
        customer = core.fetch("customers", ticket["customer_id"],
                              Err.CUSTOMER_NOT_FOUND)
        # priority 25: a NONE entitlement is refused with its own 403.
        if customer.get("tech_support_entitlement") not in ("BASIC", "EXTENDED"):
            raise ApiError(Err.ENTITLEMENT_REQUIRED)
        ticket["status"] = "IN_TRIAGE"
        core.recompute_required_entitlement(ticket)
        return ok_obj(core.public(ticket))

    @app.route("/support-tickets/<ident>/escalate", methods=["POST"])
    def escalate_ticket(ident):
        user_id, _role = guard(["SupportAgent"])
        ticket = core.fetch("support_tickets", ident,
                            Err.REFERENCED_RESOURCE_NOT_FOUND)
        core.require_state(ticket, ("IN_TRIAGE",))
        # priority 38, then priority 26, then priority 27.
        if ticket.get("required_entitlement") != "EXTENDED":
            raise ApiError(Err.ESCALATION_NOT_PERMITTED)
        center = DB.get("service_centers", ticket.get("service_center_id"))
        if center is None:
            raise ApiError(Err.ESCALATION_DESK_REQUIRED)
        if not core.has_free_slot(center):
            raise ApiError(Err.SERVICE_CENTER_CAPACITY_FULL_AT_ESCALATION)

        ticket["status"] = "ESCALATED"
        ticket["escalated_at"] = iso(DB.now())
        ticket["escalated_by"] = user_id
        ticket["escalation_seq"] = core.next_escalation_seq(ticket["id"])
        core.append_ledger(ticket, center["id"], "SERVICE_DEPARTMENT_ESCALATION")
        core.adjust_open_tickets(center["id"], 1)
        core.recompute_escalation_count(ticket)
        core.touch(ticket)
        return ok_obj(core.public(ticket))

    @app.route("/support-tickets/<ident>/de-escalate", methods=["POST"])
    def de_escalate_ticket(ident):
        guard(["ServiceDepartment"])
        ticket = core.fetch("support_tickets", ident,
                            Err.REFERENCED_RESOURCE_NOT_FOUND)
        core.require_state(ticket, ("ESCALATED",))
        ticket["status"] = "IN_TRIAGE"
        ticket["escalated_at"] = None
        core.append_ledger(ticket, ticket.get("service_center_id"),
                           "ESCALATION_WITHDRAWN")
        if ticket.get("service_center_id"):
            core.adjust_open_tickets(ticket["service_center_id"], -1)
        core.recompute_escalation_count(ticket)
        core.touch(ticket)
        return ok_obj(core.public(ticket))

    @app.route("/support-tickets/<ident>/resolve", methods=["POST"])
    def resolve_ticket(ident):
        _user_id, role = guard(["SupportAgent", "ServiceDepartment"])
        ticket = core.fetch("support_tickets", ident,
                            Err.REFERENCED_RESOURCE_NOT_FOUND)
        if role == "ServiceDepartment":
            core.require_state(ticket, ("IN_TRIAGE", "ESCALATED"))
        else:
            core.require_state(ticket, ("IN_TRIAGE",))
        was_escalated = ticket.get("status") == "ESCALATED"
        ticket["status"] = "RESOLVED"
        core.touch(ticket)
        # Resolving from ESCALATED releases the slot the escalation occupied.
        if was_escalated and ticket.get("service_center_id"):
            core.adjust_open_tickets(ticket["service_center_id"], -1)
        return ok_obj(core.public(ticket))

    # ---- escalation ledger ----------------------------------------------
    @app.route("/escalation-ledger", methods=["GET"])
    def list_ledger():
        guard(LEDGER_ROLES)
        return page(core.all_rows("escalation_ledger"), filters=(
            ("support_ticket_id", "support_ticket_id", None),
            ("service_center_id", "service_center_id", None),
        ))

    @app.route("/escalation-ledger/<ident>", methods=["GET"])
    def get_ledger_row(ident):
        guard(LEDGER_ROLES)
        return ok_obj(core.public(core.fetch("escalation_ledger", ident,
                                             Err.REFERENCED_RESOURCE_NOT_FOUND)))