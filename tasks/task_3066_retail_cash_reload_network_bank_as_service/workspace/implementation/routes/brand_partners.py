"""Brand partner endpoints and the suspension / restore cascades."""

from flask import Blueprint, request

import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core

bp = Blueprint("brand_partners", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)
LIST_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
)

SERVICE_FLAG = {
    "CARD_ISSUANCE": "card_issuance_enabled",
    "LEDGERING": "ledgering_enabled",
    "COMPLIANCE_OVERSIGHT": "compliance_oversight_enabled",
}
SERVICE_SCOPE = tuple(SERVICE_FLAG) + ("DISPUTE_HANDLING",)

# Terminal dispute states do not keep a brand's open_dispute_count above zero.
NON_TERMINAL_DISPUTE = ("OPEN", "RETAILER_RESPONSE", "PROGRAM_REVIEW", "ESCALATED")


def checklist_complete(brand):
    """True exactly when every declared service has its enabling flag set.

    DISPUTE_HANDLING has no enabling flag in the entity model, so it places no
    requirement on the checklist.
    """
    for service in brand["services_scope"]:
        flag = SERVICE_FLAG.get(service)
        if flag is not None and not brand.get(flag, False):
            return False
    return True


def open_dispute_count(brand):
    brand_accounts = {
        a["id"] for a in db.card_accounts.values() if a["brand_partner_id"] == brand["id"]
    }
    return sum(
        1
        for d in db.dispute_cases.values()
        if d["card_account_id"] in brand_accounts and d["case_status"] in NON_TERMINAL_DISPUTE
    )


def personalised(brand):
    out = core.public(core.BRAND_PARTNER, brand)
    out["onboarding_checklist_complete"] = checklist_complete(brand)
    out["open_dispute_count"] = open_dispute_count(brand)
    return out


@bp.post("/v1/brand-partners")
def create_brand_partner():
    middleware.authenticate(("PlatformAdmin", "ComplianceOfficer"))
    data = rh.body()
    program_id = rh.require_str(data, "program_id")
    brand_name = rh.require_str(data, "brand_name")
    scope = rh.require_array(data, "services_scope")
    for service in scope:
        if service not in SERVICE_SCOPE:
            raise errors.invalid_request("services_scope contains an unknown service %r." % (service,))

    program = core.ref_program(program_id)
    core.guard_not_frozen(program)
    core.guard_not_restricted(program)

    expected = rh.require_int(data, "expected_program_version")
    if expected != program["version"]:
        raise errors.stale_version()

    row = core.common_fields()
    row.update(
        {
            "program_id": program["id"],
            "brand_name": brand_name,
            "services_scope": list(scope),
            "card_issuance_enabled": rh.optional_bool(data, "card_issuance_enabled", True),
            "ledgering_enabled": rh.optional_bool(data, "ledgering_enabled", False),
            "compliance_oversight_enabled": rh.optional_bool(
                data, "compliance_oversight_enabled", False
            ),
            "partner_status": "PENDING_ONBOARDING",
            "suspension_source": "NONE",
        }
    )
    db.register(db.brand_partners, row)
    core.touch(program)
    return response.ok(personalised(row), 201)


@bp.get("/v1/brand-partners/<brand_id>")
def get_brand_partner(brand_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(personalised(core.get_brand(brand_id)))


@bp.get("/v1/brand-partners")
def list_brand_partners():
    middleware.authenticate(LIST_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(db.brand_partners, program_id=request.args.get("program_id"))
    total = len(rows)
    return response.array(
        [personalised(r) for r in rows[offset : offset + limit]], limit, offset, total
    )


# --- state machine ------------------------------------------------------------
ALLOWED = {
    "PENDING_ONBOARDING": ("ACTIVE",),
    "ACTIVE": ("SUSPENDED", "PENDING_ONBOARDING"),
    "SUSPENDED": ("ACTIVE", "OFFBOARDED"),
    "OFFBOARDED": (),
}


@bp.post("/v1/brand-partners/<brand_id>/state")
def move_brand_state(brand_id):
    middleware.authenticate(("ComplianceOfficer",))
    brand = core.get_brand(brand_id)
    program = core.get_program(brand["program_id"])

    data = rh.body()
    to_status = rh.require_enum(
        data, "to_status", ("PENDING_ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED")
    )

    current = brand["partner_status"]
    if to_status not in ALLOWED.get(current, ()):
        raise errors.invalid_state(
            "No transition from %s to %s." % (current, to_status)
        )

    core.guard_not_frozen(program)

    if to_status == "ACTIVE":
        core.guard_not_restricted(program)
        if not checklist_complete(brand):
            raise errors.brand_onboarding_incomplete(
                "The onboarding checklist for the declared services scope is incomplete."
            )
        brand["partner_status"] = "ACTIVE"
        if current == "SUSPENDED":
            brand["suspension_source"] = "NONE"
            _restore_accounts(brand)
        core.touch(brand)
        core.recompute_program(program)
        core.touch(program)
        return response.ok(personalised(brand))

    if to_status == "SUSPENDED":
        brand["partner_status"] = "SUSPENDED"
        brand["suspension_source"] = "COMPLIANCE"
        core.touch(brand)
        moved_accounts = []
        for account in _brand_accounts(brand):
            if account["compliance_hold_status"] == "CLEAR":
                account["compliance_hold_status"] = "REVIEW"
                core.touch(account)
                moved_accounts.append(account)
        for account in moved_accounts:
            for load in core.account_loads(account):
                if load["load_status"] == "INITIATED":
                    load["load_status"] = "DECLINED"
                    load["reversal_reason"] = "NONE"
                    core.touch(load)
        core.recompute_program(program)
        core.touch(program)
        return response.ok(personalised(brand))

    if to_status == "PENDING_ONBOARDING":
        if open_dispute_count(brand) != 0:
            raise errors.invalid_state(
                "A brand carrying an open dispute cannot be reverted for re-onboarding."
            )
        brand["partner_status"] = "PENDING_ONBOARDING"
        core.touch(brand)
        return response.ok(personalised(brand))

    # OFFBOARDED
    if open_dispute_count(brand) != 0:
        raise errors.invalid_state(
            "A brand carrying an open dispute cannot be offboarded."
        )
    brand["partner_status"] = "OFFBOARDED"
    core.touch(brand)
    for account in _brand_accounts(brand):
        if account["compliance_hold_status"] in ("CLEAR", "REVIEW"):
            account["compliance_hold_status"] = "FROZEN"
            core.touch(account)
    return response.ok(personalised(brand))


def _brand_accounts(brand):
    return [a for a in db.card_accounts.values() if a["brand_partner_id"] == brand["id"]]


def _restore_accounts(brand):
    """REVIEW returns to CLEAR unless a non-terminal alert references the
    account; accounts a freeze had pushed to FROZEN first return to REVIEW."""
    for account in _brand_accounts(brand):
        if account["compliance_hold_status"] == "FROZEN":
            account["compliance_hold_status"] = "REVIEW"
            core.touch(account)
        if account["compliance_hold_status"] == "REVIEW":
            if core.has_non_terminal_alert(account["id"]):
                continue
            account["compliance_hold_status"] = "CLEAR"
            core.touch(account)