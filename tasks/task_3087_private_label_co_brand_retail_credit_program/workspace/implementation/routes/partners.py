"""RetailPartner and ProgramAgreement endpoints (PRD §3.1)."""
from flask import request

from core import auth, computations, domain
from core.auth import optional_field, require_field
from core.errors import ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND, fail
from core.store import add, store, touch
from .common import listing, single


def _share_ceiling_breached(revenue, subsidy) -> bool:
    return computations.dec(revenue) + computations.dec(subsidy) > computations.dec(1)


def _not_found(what):
    return fail(ERR_RESOURCE_NOT_FOUND, f"{what} does not exist.")


def _require_partner(partner_id):
    partner = store.partners.get(partner_id)
    if not partner:
        raise _not_found("RetailPartner")
    return partner


def _require_agreement(agreement_id):
    agreement = store.agreements.get(agreement_id)
    if not agreement:
        raise _not_found("ProgramAgreement")
    return agreement


def register(app):

    # --- RetailPartner ----------------------------------------------------

    @app.post("/servicing/partners")
    def create_partner():
        auth.require_role("ProgramAdmin")
        payload = auth.body()
        counterparty = require_field(payload, "retailer_name", "string")
        code = require_field(payload, "loyalty_program_code", "string")
        linked = optional_field(payload, "loyalty_link_enabled", "bool", True)
        partner = add("partners", {
            "retailer_name": counterparty,
            "partner_status": "ACTIVE",
            "loyalty_program_code": code,
            "loyalty_link_enabled": linked,
            "partner_portfolio_exposure_cents": 0,
        })
        return single(partner, 201)

    @app.get("/servicing/partners")
    def list_partners():
        auth.require_role("ProgramAdmin", "CardholderService", "Underwriter")
        return listing(list(store.partners.values()))

    @app.get("/servicing/partners/<partner_id>")
    def get_partner(partner_id):
        _user_id, role = auth.require_role(
            "ProgramAdmin", "CardholderService", "Underwriter", "RetailPartnerAnalyst")
        partner = _require_partner(partner_id)
        if role == "RetailPartnerAnalyst" and _user_id != partner_id:
            raise fail("ERR_UNAUTHORIZED",
                       "A RetailPartnerAnalyst may only read their own retailer.")
        return single(partner)

    @app.post("/servicing/partners/<partner_id>/suspend")
    def suspend_partner(partner_id):
        auth.require_role("ProgramAdmin")
        partner = _require_partner(partner_id)
        if partner["partner_status"] != "ACTIVE":
            raise fail(ERR_INVALID_STATE, "Only an ACTIVE partner can be suspended.")
        partner["partner_status"] = "SUSPENDED"
        touch(partner)
        return single(partner)

    @app.post("/servicing/partners/<partner_id>/reinstate")
    def reinstate_partner(partner_id):
        auth.require_role("ProgramAdmin")
        partner = _require_partner(partner_id)
        if partner["partner_status"] != "SUSPENDED":
            raise fail(ERR_INVALID_STATE, "Only a SUSPENDED partner can be reinstated.")
        partner["partner_status"] = "ACTIVE"
        touch(partner)
        return single(partner)

    @app.post("/servicing/partners/<partner_id>/offboard")
    def offboard_partner(partner_id):
        auth.require_role("ProgramAdmin")
        partner = _require_partner(partner_id)
        if partner["partner_status"] != "ACTIVE":
            raise fail(ERR_INVALID_STATE, "Only an ACTIVE partner can be offboarded.")
        programs = domain.programs_of_partner(partner_id)
        if any(p.get("program_status") != "CLOSED" for p in programs):
            raise fail(ERR_INVALID_STATE,
                       "Every credit program for this partner must be CLOSED before offboarding.")
        partner["partner_status"] = "OFFBOARDING"
        touch(partner)
        return single(partner)

    @app.get("/servicing/partners/<partner_id>/credit-programs")
    def list_partner_programs(partner_id):
        auth.require_role("ProgramAdmin", "Underwriter")
        _require_partner(partner_id)
        return listing(domain.programs_of_partner(partner_id))

    # --- ProgramAgreement -------------------------------------------------

    @app.post("/servicing/agreements")
    def create_agreement():
        auth.require_role("ProgramAdmin")
        payload = auth.body()
        partner_id = require_field(payload, "partner_id", "string")
        revenue = require_field(payload, "revenue_share_rate", "number")
        subsidy = require_field(payload, "promo_subsidy_rate", "number")
        term = require_field(payload, "promo_term_months", "int")
        _require_partner(partner_id)
        if _share_ceiling_breached(revenue, subsidy):
            raise fail("ERR_REVENUE_SHARE_INVALID",
                       "revenue_share_rate plus promo_subsidy_rate may not exceed 1.0.")
        agreement = add("agreements", {
            "partner_id": partner_id,
            "agreement_status": "DRAFT",
            "revenue_share_rate": revenue,
            "promo_subsidy_rate": subsidy,
            "promo_term_months": term,
            "minimum_charge_cents": optional_field(
                payload, "minimum_charge_cents", "int", computations.MINIMUM_CHARGE_CENTS_DEFAULT),
            "settlement_terms_days": optional_field(
                payload, "settlement_terms_days", "int", computations.SETTLEMENT_TERMS_DAYS_DEFAULT),
            "dispute_grace_days": optional_field(
                payload, "dispute_grace_days", "int", computations.DISPUTE_GRACE_DAYS_DEFAULT),
            "renewal_notice_days": optional_field(
                payload, "renewal_notice_days", "int", computations.RENEWAL_NOTICE_DAYS_DEFAULT),
            "purchase_right_rate": optional_field(
                payload, "purchase_right_rate", "number", computations.PURCHASE_RIGHT_RATE_DEFAULT),
        })
        return single(agreement, 201)

    @app.get("/servicing/agreements")
    def list_agreements():
        auth.require_role("ProgramAdmin", "CardholderService", "Underwriter")
        rows = list(store.agreements.values())
        partner_id = request.args.get("partner_id")
        return listing(rows, {"partner_id": partner_id})

    @app.get("/servicing/agreements/<agreement_id>")
    def get_agreement(agreement_id):
        _user_id, role = auth.require_role(
            "ProgramAdmin", "CardholderService", "Underwriter", "RetailPartnerAnalyst")
        agreement = _require_agreement(agreement_id)
        if role == "RetailPartnerAnalyst" and agreement.get("partner_id") != _user_id:
            raise fail("ERR_UNAUTHORIZED",
                       "A RetailPartnerAnalyst may only read their own retailer's agreement.")
        return single(agreement)

    @app.post("/servicing/agreements/<agreement_id>/open-negotiation")
    def open_negotiation(agreement_id):
        auth.require_role("ProgramAdmin")
        agreement = _require_agreement(agreement_id)
        if agreement["agreement_status"] != "DRAFT":
            raise fail(ERR_INVALID_STATE, "Only a DRAFT agreement can open negotiation.")
        if agreement["revenue_share_rate"] + agreement["promo_subsidy_rate"] > 1.0:
            raise fail("ERR_REVENUE_SHARE_INVALID",
                       "revenue_share_rate plus promo_subsidy_rate may not exceed 1.0.")
        agreement["agreement_status"] = "NEGOTIATION"
        touch(agreement)
        return single(agreement)

    def _guard_expected_version(agreement, payload, field="expected_agreement_version"):
        expected = require_field(payload, field, "int")
        if expected != agreement["version"]:
            raise fail("ERR_STALE_VERSION",
                       f"{field} does not match the agreement's current version.")
        if agreement["revenue_share_rate"] + agreement["promo_subsidy_rate"] > 1.0:
            raise fail("ERR_REVENUE_SHARE_INVALID",
                       "revenue_share_rate plus promo_subsidy_rate may not exceed 1.0.")

    @app.post("/servicing/agreements/<agreement_id>/execute")
    def execute_agreement(agreement_id):
        auth.require_role("ProgramAdmin")
        agreement = _require_agreement(agreement_id)
        payload = auth.body()
        _guard_expected_version(agreement, payload)
        if agreement["agreement_status"] != "NEGOTIATION":
            raise fail(ERR_INVALID_STATE, "Only a NEGOTIATION agreement can be executed.")
        agreement["agreement_status"] = "ACTIVE"
        touch(agreement)
        return single(agreement)

    @app.post("/servicing/agreements/<agreement_id>/reinstate")
    def reinstate_agreement(agreement_id):
        auth.require_role("ProgramAdmin")
        agreement = _require_agreement(agreement_id)
        payload = auth.body()
        _guard_expected_version(agreement, payload)
        if agreement["agreement_status"] != "SUSPENDED":
            raise fail(ERR_INVALID_STATE, "Only a SUSPENDED agreement can be reinstated.")
        agreement["agreement_status"] = "ACTIVE"
        touch(agreement)
        return single(agreement)

    @app.post("/servicing/agreements/<agreement_id>/terminate")
    def terminate_agreement(agreement_id):
        auth.require_role("ProgramAdmin")
        agreement = _require_agreement(agreement_id)
        payload = auth.body()
        expected = require_field(payload, "expected_agreement_version", "int")
        if expected != agreement["version"]:
            raise fail("ERR_STALE_VERSION",
                       "expected_agreement_version does not match the agreement's current version.")
        if agreement["agreement_status"] != "NEGOTIATION":
            raise fail(ERR_INVALID_STATE, "Only a NEGOTIATION agreement can be terminated.")
        agreement["agreement_status"] = "TERMINATED"
        touch(agreement)
        return single(agreement)