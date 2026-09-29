"""Customer intake, the KYC dimension and the origination dimension
(PRD 3.3 and 3.4)."""
from flask import Blueprint

import auth
import derive
import envelope
import errors
import ser
import store
import valid
from store import db, touch
from views_provider import load_provider

bp = Blueprint("customers", __name__)

EVIDENCE_LEVELS = ("BUSINESS_REGISTRY_VERIFIED", "CONTRACT_ONLY",
                   "SELF_ATTESTED")
KYC_STATES = ("PENDING", "UNDER_REVIEW", "VERIFIED", "REJECTED")
ORIGINATION_STATES = ("DISABLED", "ENABLED", "SUSPENDED", "TERMINATED")
RISK_TIERS = ("LOW", "ELEVATED", "HIGH")
KYC_DECISIONS = ("VERIFY", "REJECT")
ACTIONS = ("ENABLE", "SUSPEND", "RESTORE", "TERMINATE")
SUSPENSION_CAUSES = ("NOTICE_EXPIRY", "BLOCKING_ANALYTICS",
                     "TRAFFIC_RISK_THRESHOLD", "REGULATOR_ORDER",
                     "PROVIDER_REQUEST")
ROLE_CAUSE = {
    auth.PROVIDER_ADMIN: "PROVIDER_REQUEST",
    auth.REGULATOR: "REGULATOR_ORDER",
}
SELF_CLEARABLE_BY_PROVIDER = ("PROVIDER_REQUEST",)

READ_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER, auth.KYC_ANALYST,
              auth.FRAUD_ANALYST, auth.PROVIDER_ADMIN, auth.CALLER)
LIST_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER, auth.KYC_ANALYST,
              auth.FRAUD_ANALYST, auth.PROVIDER_ADMIN)


def load_customer(customer_id):
    row = db.customers.get(customer_id)
    if row is None:
        errors.fail(errors.ERR_CUSTOMER_NOT_FOUND,
                    "No customer with id %s" % customer_id)
    return row


def require_verified(customer):
    if customer["kyc_state"] != "VERIFIED":
        errors.fail(errors.ERR_CUSTOMER_NOT_KYC_VERIFIED,
                    "The customer's kyc_state is not VERIFIED")


@bp.route("/rmd/customers", methods=["POST"])
@auth.require(auth.PROVIDER_ADMIN)
def onboard_customer():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    legal_name = valid.req_str(data, "legal_name")
    contact_email = valid.req_str(data, "contact_email")
    evidence = valid.req_enum(data, "kyc_evidence_level", EVIDENCE_LEVELS)
    load_provider(provider_id)
    auth.own_provider(provider_id)

    row = store.base_row()
    row.update({
        "provider_id": provider_id,
        "legal_name": legal_name,
        "contact_email": contact_email,
        "kyc_evidence_level": evidence,
        "kyc_state": "PENDING",
        "origination_state": "DISABLED",
        "kyc_submitted_by_user_id": None,
        "kyc_decided_by_user_id": None,
        "kyc_decided_at": None,
        "traffic_risk_index": 0.0,
        "risk_tier": "LOW",
        "observation_count": 0,
        "false_positive_count": 0,
        "suspension_cause": None,
        "suspension_source_id": None,
    })
    db.customers[row["id"]] = row
    return envelope.created(ser.customer(row))


@bp.route("/rmd/customers/<customer_id>/kyc-submit", methods=["POST"])
@auth.require(auth.KYC_ANALYST)
def kyc_submit(customer_id):
    data = valid.body()
    evidence = valid.opt_enum(data, "kyc_evidence_level", EVIDENCE_LEVELS)
    row = load_customer(customer_id)
    if row["kyc_state"] not in ("PENDING", "REJECTED", "VERIFIED"):
        errors.fail(errors.ERR_CUSTOMER_KYC_STATE_INVALID,
                    "A customer already UNDER_REVIEW cannot be resubmitted")
    row["kyc_state"] = "UNDER_REVIEW"
    row["kyc_submitted_by_user_id"] = auth.acting_id()
    row["kyc_decided_by_user_id"] = None
    if evidence is not None:
        row["kyc_evidence_level"] = evidence
    touch(row)
    return envelope.ok(ser.customer(row))


@bp.route("/rmd/customers/<customer_id>/kyc-decision", methods=["POST"])
@auth.require(auth.KYC_ANALYST)
def kyc_decision(customer_id):
    data = valid.body()
    decision = valid.req_enum(data, "decision", KYC_DECISIONS)
    evidence = valid.opt_enum(data, "kyc_evidence_level", EVIDENCE_LEVELS)
    row = load_customer(customer_id)
    if auth.acting_id() == row["kyc_submitted_by_user_id"]:
        errors.fail(errors.ERR_SEGREGATION_OF_DUTIES,
                    "The submitting analyst may not decide the package")
    if row["kyc_state"] != "UNDER_REVIEW":
        errors.fail(errors.ERR_CUSTOMER_KYC_STATE_INVALID,
                    "Only a customer UNDER_REVIEW can be decided")

    row["kyc_state"] = "VERIFIED" if decision == "VERIFY" else "REJECTED"
    row["kyc_decided_by_user_id"] = auth.acting_id()
    row["kyc_decided_at"] = db.now()
    if evidence is not None:
        row["kyc_evidence_level"] = evidence
    touch(row)
    return envelope.ok(ser.customer(row))


def _suspension_cause_for_role(data):
    expected = ROLE_CAUSE.get(auth.acting_role())
    cause = valid.req_enum(data, "suspension_cause", SUSPENSION_CAUSES)
    if cause != expected:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "suspension_cause %s is not available to role %s"
                    % (cause, auth.acting_role()))
    return cause


@bp.route("/rmd/customers/<customer_id>/origination-actions",
          methods=["POST"])
@auth.require(auth.PROVIDER_ADMIN, auth.REGULATOR)
def origination_action(customer_id):
    data = valid.body()
    action = valid.req_enum(data, "action", ACTIONS)
    cause = None
    if action == "SUSPEND":
        cause = _suspension_cause_for_role(data)
    row = load_customer(customer_id)
    auth.own_provider(row["provider_id"])
    state = row["origination_state"]

    if action == "ENABLE":
        if state != "DISABLED":
            _bad_origination("ENABLE is only available from DISABLED")
        require_verified(row)
        row["origination_state"] = "ENABLED"
        row["suspension_cause"] = None
        row["suspension_source_id"] = None
        touch(row)
    elif action == "SUSPEND":
        if state != "ENABLED":
            _bad_origination("SUSPEND is only available from ENABLED")
        derive.suspend_customer(row, cause, None)
    elif action == "RESTORE":
        if state != "SUSPENDED":
            _bad_origination("RESTORE is only available from SUSPENDED")
        require_verified(row)
        if (auth.acting_role() == auth.PROVIDER_ADMIN
                and row["suspension_cause"] not in SELF_CLEARABLE_BY_PROVIDER):
            errors.fail(errors.ERR_SUSPENSION_CAUSE_NOT_SELF_CLEARABLE,
                        "A ProviderAdmin may only clear a PROVIDER_REQUEST "
                        "suspension")
        derive.restore_customer(row)
    else:
        if state not in ("DISABLED", "ENABLED", "SUSPENDED"):
            _bad_origination("TERMINATE is not available from TERMINATED")
        derive.terminate_customer(row)
    return envelope.ok(ser.customer(row))


def _bad_origination(message):
    errors.fail(errors.ERR_ORIGINATION_STATE_INVALID, message)


@bp.route("/rmd/customers/<customer_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_customer(customer_id):
    row = load_customer(customer_id)
    auth.own(provider_id=row["provider_id"], customer_id=row["id"])
    return envelope.ok(ser.customer(row))


@bp.route("/rmd/customers", methods=["GET"])
@auth.require(*LIST_ROLES)
def list_customers():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    kyc_state = valid.arg_enum("kyc_state", KYC_STATES)
    origination_state = valid.arg_enum("origination_state",
                                       ORIGINATION_STATES)
    risk_tier = valid.arg_enum("risk_tier", RISK_TIERS)

    rows = auth.scope_rows(db.customers.values(),
                           provider_of=lambda r: r["provider_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if kyc_state is not None:
        rows = [r for r in rows if r["kyc_state"] == kyc_state]
    if origination_state is not None:
        rows = [r for r in rows if r["origination_state"] == origination_state]
    if risk_tier is not None:
        rows = [r for r in rows if r["risk_tier"] == risk_tier]
    return envelope.collection(rows, ser.customer, limit, offset)
