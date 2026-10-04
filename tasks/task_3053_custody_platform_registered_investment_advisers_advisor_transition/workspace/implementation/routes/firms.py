"""Firms, custody agreements and firm entitlements."""

from core.context import body, check_if_match, need
from core.errors import fail
from core.response import ok, paginate
from core.store import STORE, new_token
from domain import calc
from domain.cascade import (apply_posture, redrive_households_for_billing,
                            redrive_models, revoke_entitlements,
                            suspend_entitlements, throttle_feeds,
                            unallocate_submitted_blocks)
from domain.guards import (current_agreement, no_outstanding_admin_action,
                           sod_guard)
from domain.model import create, serialize, touch
from domain.resolve import sorted_rows
from routes._base import identity, load, load_firm, params


def register(api):

    # ------------------------------------------------------------------ firms

    @api.route("/ria/firms", methods=["POST"], roles=["PlatformAdmin"])
    def create_firm():
        data = body()
        legal_name = need(data, "legal_name")
        crd_number = need(data, "crd_number")
        for existing in STORE.all("AdvisorFirm"):
            if existing.get("legal_name") == legal_name or existing.get("crd_number") == crd_number:
                fail("ERR_REFERENCE_MISMATCH", "legal_name and crd_number must be unique")
        firm = create(
            "AdvisorFirm",
            legal_name=legal_name,
            crd_number=crd_number,
            home_state_code=data.get("home_state_code"),
            custody_agreement_status="PENDING",
            firm_posture="SUSPENDED",
            posture_reason_code="CUSTODY_AGREEMENT_NOT_EXECUTED",
            agreement_executed_at=None,
            supervision_evidence_status="UNKNOWN",
            entitlement_count=0,
            household_fee_basis_total_cents=0,
        )
        calc.recompute_posture(firm, stamp=False)
        return ok(serialize(firm), 201)

    @api.route("/ria/firms", methods=["GET"],
               roles=["PlatformAdmin", "ComplianceReviewer", "CustodyOperationsOfficer"])
    def list_firms():
        p = params()
        posture = p.get("firm_posture")
        rows = sorted_rows("AdvisorFirm", {"firm_posture": posture})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/firms/<firm_id>", methods=["GET"],
               roles=["PlatformAdmin", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "AdvisorOperationsLead"])
    def read_firm(firm_id):
        firm = load_firm(firm_id)
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(firm), 200)

    @api.route("/ria/firms/<firm_id>/freeze", methods=["POST"], roles=["ComplianceReviewer"],
               if_match=True)
    def freeze_firm(firm_id):
        firm = load_firm(firm_id)
        data = body()
        check_if_match(firm, data)
        if firm.get("firm_posture") == "FROZEN":
            fail("ERR_INVALID_STATE")
        if firm.get("firm_posture") == "OPEN":
            requires_active = any(
                a.get("admin_action_kind") == "REGULATORY_FREEZE" and a.get("admin_action_status") == "ACTIVE"
                for a in STORE.find("AdminActionLog", firm_id=firm_id))
            if not requires_active:
                fail("ERR_INVALID_STATE")
        firm["firm_posture"] = "FROZEN"
        firm["posture_reason_code"] = "REGULATORY_FREEZE"
        touch(firm)
        apply_posture(firm)
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(firm), 200)

    # -------------------------------------------------------- agreements

    @api.route("/ria/firms/<firm_id>/custody-agreements", methods=["POST"],
               roles=["AdvisorOperationsLead"])
    def draft_agreement(firm_id):
        firm = load_firm(firm_id)
        from domain.guards import firm_active_guard
        firm_active_guard(firm)
        data = body()
        row = create("CustodyAgreement",
                     firm_id=firm_id,
                     agreement_status="DRAFT",
                     adviser_crd_number=need(data, "adviser_crd_number"),
                     drafted_by_user_id=None,
                     executed_by_user_id=None,
                     signed_at=None,
                     countersignature_hash=None,
                     superseded_by_agreement_id=None,
                     submitted_at=None)
        return ok(serialize(row), 201)

    @api.route("/ria/firms/<firm_id>/custody-agreements", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_agreements(firm_id):
        load_firm(firm_id)
        p = params()
        rows = sorted_rows("CustodyAgreement", {"firm_id": firm_id, "agreement_status": p.get("agreement_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/custody-agreements/<agreement_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def read_agreement(agreement_id):
        return ok(serialize(load("CustodyAgreement", agreement_id)), 200)

    @api.route("/ria/custody-agreements/<agreement_id>/submit", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def submit_agreement(agreement_id):
        row = load("CustodyAgreement", agreement_id)
        from domain.guards import firm_active_guard
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, "DRAFT", ("TERMINATED", "SUPERSEDED", "EXECUTED"))
        if firm.get("crd_number") != row.get("adviser_crd_number"):
            fail("ERR_REFERENCE_MISMATCH")
        for sibling in STORE.find("CustodyAgreement", firm_id=firm.get("id")):
            if sibling.get("id") == row.get("id"):
                continue
            if sibling.get("agreement_status") in ("PENDING_SIGNATURE", "EXECUTED"):
                fail("ERR_CUSTODY_AGREEMENT_REQUIRED",
                     "The firm already has a competing live agreement authority.")
        ident = identity()
        row["agreement_status"] = "PENDING_SIGNATURE"
        row["drafted_by_user_id"] = ident.user_id
        row["submitted_at"] = STORE.clock.now()
        touch(row)
        _restamp_payload_integrity(firm)
        return ok(serialize(row), 200)

    @api.route("/ria/custody-agreements/<agreement_id>/revert", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def revert_agreement(agreement_id):
        row = load("CustodyAgreement", agreement_id)
        from domain.guards import firm_active_guard
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        firm_active_guard(firm)
        _state_or_terminal(row, "PENDING_SIGNATURE", ("TERMINATED", "SUPERSEDED", "EXECUTED"))
        row["agreement_status"] = "DRAFT"
        row["drafted_by_user_id"] = None
        row["submitted_at"] = None
        touch(row)
        return ok(serialize(row), 200)

    @api.route("/ria/firms/<firm_id>/custody-agreements/execute", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=False)
    def execute_agreement(firm_id):
        firm = load_firm(firm_id)
        data = body()
        from domain.guards import firm_active_guard
        firm_active_guard(firm)
        pending = [a for a in STORE.find("CustodyAgreement", firm_id=firm_id)
                   if a.get("agreement_status") == "PENDING_SIGNATURE"]
        if not pending:
            if any(a.get("agreement_status") == "EXECUTED" for a in STORE.find("CustodyAgreement", firm_id=firm_id)):
                fail("ERR_INVALID_STATE")
            fail("ERR_CUSTODY_AGREEMENT_REQUIRED", "No agreement is awaiting counter-signature.")
        agreement = pending[0]
        if "if_match" in data or _has_header():
            check_if_match(agreement, data)
        if firm.get("crd_number") != agreement.get("adviser_crd_number"):
            fail("ERR_REFERENCE_MISMATCH")
        ident = identity()
        sod_guard(ident, agreement.get("drafted_by_user_id"))
        no_outstanding_admin_action(firm)

        now = STORE.clock.now()
        for older in STORE.find("CustodyAgreement", firm_id=firm_id):
            if older.get("id") == agreement.get("id"):
                continue
            if older.get("agreement_status") == "EXECUTED":
                older["agreement_status"] = "SUPERSEDED"
                older["superseded_by_agreement_id"] = agreement.get("id")
                touch(older)

        agreement["agreement_status"] = "EXECUTED"
        agreement["executed_by_user_id"] = ident.user_id
        agreement["signed_at"] = now
        agreement["countersignature_hash"] = new_token("cs_")
        touch(agreement)

        firm["custody_agreement_status"] = "EXECUTED"
        firm["agreement_executed_at"] = now
        touch(firm)
        revoke_entitlements(firm, agreement.get("id"))
        _restamp_payload_integrity(firm)
        apply_posture(firm)
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(agreement), 200)

    @api.route("/ria/firms/<firm_id>/custody-agreements/<agreement_id>/terminate", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=False)
    def terminate_agreement(firm_id, agreement_id):
        firm = load_firm(firm_id)
        row = load("CustodyAgreement", agreement_id)
        if row.get("firm_id") != firm_id:
            fail("ERR_PARENT_CHILD_MISMATCH")
        from domain.guards import firm_active_guard
        firm_active_guard(firm)
        data = body()
        if "if_match" in data or _has_header():
            check_if_match(row, data)
        curagr = current_agreement(firm)
        if curagr is None or curagr.get("id") != row.get("id"):
            fail("ERR_CUSTODY_AGREEMENT_REQUIRED", "Only the firm's current agreement may be terminated.")
        _state_or_terminal(row, "EXECUTED", ("TERMINATED", "SUPERSEDED"))
        open_accounts = [a for a in STORE.find("HouseholdAccount", firm_id=firm_id)
                         if a.get("account_status") == "OPEN"]
        if open_accounts:
            fail("ERR_OPEN_ACCOUNTS_BLOCK_TERMINATION")

        row["agreement_status"] = "TERMINATED"
        touch(row)
        firm["custody_agreement_status"] = "TERMINATED"
        touch(firm)
        suspend_entitlements(firm)
        unallocate_submitted_blocks(firm)
        throttle_feeds(firm, "CUSTODY_AGREEMENT_TERMINATED")
        # PRD §3.1: termination drops the firm to `SUSPENDED` with
        # `posture_reason_code` `CUSTODY_AGREEMENT_TERMINATED`, so the termination
        # reason is stamped over the ordinary derivation.
        calc.recompute_posture(firm)
        firm["posture_reason_code"] = "CUSTODY_AGREEMENT_TERMINATED"
        calc.recompute_firm_basis_total(firm)
        return ok(serialize(row), 200)

    @api.route("/ria/custody-agreements/<agreement_id>/firm-entitlements", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_agreement_entitlements(agreement_id):
        load("CustodyAgreement", agreement_id)
        p = params()
        rows = sorted_rows("AdvisorFirmEntitlement",
                           {"requested_custody_agreement_id": agreement_id,
                            "entitlement_status": p.get("entitlement_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/custody-agreements/<agreement_id>/successors", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_successors(agreement_id):
        load("CustodyAgreement", agreement_id)
        rows = sorted_rows("CustodyAgreement", {"superseded_by_agreement_id": agreement_id})
        return ok([serialize(r) for r in rows], 200)

    # -------------------------------------------------------- entitlements

    @api.route("/ria/firm-entitlements", methods=["POST"], roles=["AdvisorOperationsLead"])
    def request_entitlement():
        data = body()
        firm = load_firm(need(data, "firm_id"))
        from domain.guards import firm_active_guard
        firm_active_guard(firm)
        code = need(data, "entitlement_code")
        agreement_id = need(data, "requested_custody_agreement_id")
        agreement = load("CustodyAgreement", agreement_id)
        if agreement.get("firm_id") != firm.get("id"):
            fail("ERR_REFERENCE_MISMATCH")
        for sibling in STORE.find("AdvisorFirmEntitlement", firm_id=firm.get("id")):
            if sibling.get("entitlement_code") == code and sibling.get("entitlement_status") == "GRANTED":
                fail("ERR_ENTITLEMENT_DUPLICATE")
        row = create("AdvisorFirmEntitlement",
                     firm_id=firm.get("id"),
                     entitlement_code=code,
                     requested_custody_agreement_id=agreement_id,
                     entitlement_status="REQUESTED",
                     effective_from=None,
                     payload_integrity_verified=False)
        _stamp_payload_integrity(firm, row)
        return ok(serialize(row), 201)

    @api.route("/ria/firms/<firm_id>/firm-entitlements", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def list_entitlements(firm_id):
        load_firm(firm_id)
        p = params()
        rows = sorted_rows("AdvisorFirmEntitlement",
                           {"firm_id": firm_id, "entitlement_status": p.get("entitlement_status")})
        page, meta = paginate(rows, p)
        return ok([serialize(r) for r in page], 200, meta)

    @api.route("/ria/firm-entitlements/<entitlement_id>", methods=["GET"],
               roles=["AdvisorOperationsLead", "CustodyOperationsOfficer", "ComplianceReviewer",
                      "PlatformAdmin"])
    def read_entitlement(entitlement_id):
        return ok(serialize(load("AdvisorFirmEntitlement", entitlement_id)), 200)

    @api.route("/ria/firm-entitlements/<entitlement_id>/grant", methods=["POST"],
               roles=["CustodyOperationsOfficer"], if_match=True)
    def grant_entitlement(entitlement_id):
        row = load("AdvisorFirmEntitlement", entitlement_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        from domain.guards import firm_active_guard
        firm_active_guard(firm)
        _state_or_terminal(row, ("REQUESTED", "SUSPENDED"), ("REVOKED",))
        if firm.get("firm_posture") not in ("OPEN", "LIMITED"):
            fail("ERR_INVALID_STATE")
        agreement = current_agreement(firm)
        if agreement is None:
            fail("ERR_CUSTODY_AGREEMENT_REQUIRED")
        if row.get("requested_custody_agreement_id") != agreement.get("id"):
            fail("ERR_ENTITLEMENT_AGREEMENT_SUPERSEDED")
        for sibling in STORE.find("AdvisorFirmEntitlement", firm_id=firm.get("id")):
            if sibling.get("id") == row.get("id"):
                continue
            if sibling.get("entitlement_code") == row.get("entitlement_code") \
                    and sibling.get("entitlement_status") == "GRANTED":
                fail("ERR_ENTITLEMENT_DUPLICATE")
        row["entitlement_status"] = "GRANTED"
        row["effective_from"] = STORE.clock.now()
        row["payload_integrity_verified"] = True
        touch(row)
        calc.recompute_posture(firm)
        if row.get("entitlement_code") == "BILLING":
            redrive_households_for_billing(firm)
        return ok(serialize(row), 200)

    @api.route("/ria/firm-entitlements/<entitlement_id>/revoke", methods=["POST"],
               roles=["ComplianceReviewer"], if_match=True)
    def revoke_entitlement(entitlement_id):
        row = load("AdvisorFirmEntitlement", entitlement_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        from domain.guards import firm_active_guard
        firm_active_guard(firm)
        _state_or_terminal(row, ("SUSPENDED",), ("REVOKED",))
        row["entitlement_status"] = "REVOKED"
        row["effective_from"] = None
        touch(row)
        if row.get("entitlement_code") in ("MODEL_MANAGEMENT", "ALTERNATIVE_ASSETS"):
            redrive_models(firm)
        apply_posture(firm)
        return ok(serialize(row), 200)

    @api.route("/ria/firm-entitlements/<entitlement_id>/reopen", methods=["POST"],
               roles=["AdvisorOperationsLead"], if_match=True)
    def reopen_entitlement(entitlement_id):
        row = load("AdvisorFirmEntitlement", entitlement_id)
        data = body()
        check_if_match(row, data)
        firm = load_firm(row.get("firm_id"))
        from domain.guards import firm_active_guard
        firm_active_guard(firm)
        _state_or_terminal(row, ("REVOKED",), ())
        agreement = current_agreement(firm)
        if agreement is None:
            fail("ERR_CUSTODY_AGREEMENT_REQUIRED")
        row["entitlement_status"] = "REQUESTED"
        row["requested_custody_agreement_id"] = agreement.get("id")
        row["payload_integrity_verified"] = True
        row["effective_from"] = None
        touch(row)
        apply_posture(firm)
        return ok(serialize(row), 200)


def _has_header():
    from flask import request
    return request.headers.get("If-Match") is not None


def _state_or_terminal(row, from_states, terminal_states):
    from core.context import STATE_FIELDS
    field = STATE_FIELDS.get(row.get("_entity"))
    state = row.get(field)
    if terminal_states and state in terminal_states:
        fail("ERR_ALREADY_TERMINAL")
    allowed = from_states if isinstance(from_states, (tuple, list, set)) else (from_states,)
    if state not in allowed:
        fail("ERR_INVALID_STATE")


def _stamp_payload_integrity(firm, entitlement):
    agreement = current_agreement(firm)
    entitlement["payload_integrity_verified"] = (
        agreement is not None and entitlement.get("requested_custody_agreement_id") == agreement.get("id"))
    return entitlement


def _restamp_payload_integrity(firm):
    agreement = current_agreement(firm)
    for entitlement in STORE.find("AdvisorFirmEntitlement", firm_id=firm.get("id")):
        entitlement["payload_integrity_verified"] = (
            agreement is not None and entitlement.get("requested_custody_agreement_id") == agreement.get("id"))
        touch(entitlement)