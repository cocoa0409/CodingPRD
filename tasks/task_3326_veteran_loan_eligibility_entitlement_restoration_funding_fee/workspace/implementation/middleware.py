"""Auth middleware: header extraction, role checks, RBAC, veteran subtree."""
from flask import request

from db import STORE
from errors import unauthenticated, forbidden_role
import errors as E

ROLES = {"Veteran", "LoanOfficer", "Underwriter", "Appraiser", "ProgramAdmin"}


def actor():
    """Extract and validate X-User-ID / X-User-Role. Raises on failure."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    return {"user_id": uid, "role": role}


def require_roles(ctx, allowed):
    if ctx["role"] not in allowed:
        raise forbidden_role()


def check_veteran_subtree(ctx, veteran_id):
    """Veteran role may only act on the subtree of veteran id == X-User-ID."""
    if ctx["role"] == "Veteran" and ctx["user_id"] != veteran_id:
        raise forbidden_role()


def check_appraiser_identity(ctx, appraiser_id):
    if ctx["role"] == "Appraiser" and ctx["user_id"] != appraiser_id:
        raise forbidden_role()


def get_veteran_or_404(veteran_id):
    v = STORE.veterans.get(veteran_id)
    if v is None:
        raise E.not_found("ERR_VETERAN_NOT_FOUND", "veteran id does not resolve")
    return v


def get_coe_or_404(coe_id):
    c = STORE.coes.get(coe_id)
    if c is None:
        raise E.not_found("ERR_COE_NOT_FOUND", "certificate of eligibility id does not resolve")
    return c


def get_loan_or_404(loan_id):
    l = STORE.loans.get(loan_id)
    if l is None:
        raise E.not_found("ERR_LOAN_NOT_FOUND", "loan id does not resolve")
    return l


def get_appraisal_or_404(appraisal_id):
    a = STORE.appraisals.get(appraisal_id)
    if a is None:
        raise E.not_found("ERR_APPRAISAL_NOT_FOUND", "appraisal id does not resolve")
    return a


def get_repair_or_404(repair_id):
    r = STORE.repair_requirements.get(repair_id)
    if r is None:
        raise E.not_found("ERR_REPAIR_NOT_FOUND", "repair requirement id does not resolve")
    return r


def get_occupancy_cert_or_404(cert_id):
    c = STORE.occupancy_certificates.get(cert_id)
    if c is None:
        raise E.not_found("ERR_OCCUPANCY_CERT_NOT_FOUND", "occupancy certificate id does not resolve")
    return c


def get_assumption_or_404(assumption_id):
    a = STORE.assumption_requests.get(assumption_id)
    if a is None:
        raise E.not_found("ERR_ASSUMPTION_NOT_FOUND", "assumption request id does not resolve")
    return a


def get_refinance_or_404(refi_id):
    r = STORE.refinance_requests.get(refi_id)
    if r is None:
        raise E.not_found("ERR_REFINANCE_NOT_FOUND", "refinance request id does not resolve")
    return r


def get_fee_assessment_or_404(fee_id):
    f = STORE.funding_fee_assessments.get(fee_id)
    if f is None:
        raise E.not_found("ERR_FEE_ASSESSMENT_NOT_FOUND", "funding fee assessment id does not resolve")
    return f


def get_restoration_or_404(rest_id):
    r = STORE.restoration_requests.get(rest_id)
    if r is None:
        raise E.not_found("ERR_RESTORATION_NOT_FOUND", "entitlement restoration request id does not resolve")
    return r
