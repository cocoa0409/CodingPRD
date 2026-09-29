"""Claims, remittance, margin and assistance enrollments. PRD 3.8."""
from flask import Blueprint

import core
from core import (
    DB,
    Field,
    READ_ROLES,
    ROLE_BILLING,
    add_days,
    base_row,
    created,
    fail,
    get_body,
    get_claim,
    get_encounter,
    get_enrollment,
    get_patient,
    listing,
    ok,
    pagination,
    query_filters,
    touch,
    validate,
)
from domain import (
    ADMINISTRATION_CPT_CODE,
    claim_lines_terminal,
    expire_stale_enrollments,
    finalize_claim_margin,
    policy_for,
    run_waterfall,
)

bp = Blueprint("billing", __name__)

DRUG_LINE_STATUSES = ["PENDING", "SUBMITTED", "PAID", "DENIED", "APPEALED", "WRITTEN_OFF"]
ADMIN_LINE_STATUSES = ["PENDING", "SUBMITTED", "PAID", "DENIED"]
DRUG_OUTCOMES = ["PAID", "DENIED", "WRITTEN_OFF"]
ADMIN_OUTCOMES = ["PAID", "DENIED"]
DENIAL_CODES = ["NOT_COVERED", "AUTHORIZATION_MISSING", "WASTAGE_NOT_PAYABLE", "DUPLICATE_CLAIM"]
PROGRAM_TYPES = ["MANUFACTURER_COPAY_CARD", "INDEPENDENT_FOUNDATION", "FREE_DRUG_PAP"]
ENROLLMENT_STATUSES = ["PENDING", "ACTIVE", "EXHAUSTED", "TERMINATED", "EXPIRED"]


# ---------------------------------------------------------------- claim create
@bp.post("/claims")
@core.api([ROLE_BILLING])
def create_claim():
    body = get_body()
    values = validate(body, [Field("injection_encounter_id", "id", required=True)])
    enc = get_encounter(values["injection_encounter_id"])
    if enc["status"] != "ATTESTED":  # step 13
        fail("ERR_ENCOUNTER_STATE_INVALID", "only an ATTESTED encounter may be billed")

    patient = DB.patients[enc["patient_id"]]
    payer = DB.payers[patient["payer_id"]]
    drug = DB.drugs[enc["effective_drug_id"]]
    policy = policy_for(payer["id"], drug["id"])
    if policy is None:  # step 20
        fail("ERR_PAYER_POLICY_MISSING", "no coverage policy for this payer and product")
    for existing in DB.claims.values():  # step 37
        if existing["injection_encounter_id"] == enc["id"]:
            fail("ERR_DUPLICATE_CLAIM", "a claim already exists for this encounter")

    rate = int(policy["drug_allowed_cents_per_billing_unit"])
    drug_billed = int(enc["administered_billing_units"]) * rate
    wastage_billed = int(enc["wasted_billing_units"]) * rate
    admin_billed = int(policy["admin_allowed_cents"])

    claim = base_row()
    claim.update(
        {
            "injection_encounter_id": enc["id"],
            "patient_id": enc["patient_id"],
            "payer_id": payer["id"],
            "assistance_enrollment_id": None,
            "hcpcs_code": drug["hcpcs_code"],
            "administration_cpt_code": ADMINISTRATION_CPT_CODE,
            "modifiers": list(enc["modifiers"] or []),
            "billed_billing_units": int(enc["total_billed_billing_units"]),
            "drug_billed_cents": drug_billed,
            "wastage_billed_cents": wastage_billed,
            "admin_billed_cents": admin_billed,
            "drug_allowed_cents": drug_billed,
            "wastage_allowed_cents": wastage_billed if policy["wastage_reimbursed"] else 0,
            "admin_allowed_cents": admin_billed,
            "drug_paid_cents": 0,
            "wastage_paid_cents": 0,
            "admin_paid_cents": 0,
            "total_allowed_cents": 0,
            "coinsurance_cents": 0,
            "foundation_applied_cents": 0,
            "patient_responsibility_cents": 0,
            "practice_writeoff_cents": 0,
            "standard_drug_cost_cents": 0,
            "provisional_margin_cents": 0,
            "actual_acquisition_cost_cents": None,
            "realized_margin_cents": None,
            "drug_line_status": "PENDING",
            "admin_line_status": "PENDING",
            "denial_code": None,
            "appeal_basis": None,
        }
    )
    DB.claims[claim["id"]] = claim

    expire_stale_enrollments(enc["patient_id"])
    run_waterfall(claim, provisional=True)

    units = int(enc["administered_billing_units"]) + int(enc["wasted_billing_units"])
    claim["standard_drug_cost_cents"] = units * int(drug["asp_cents_per_billing_unit"])
    claim["provisional_margin_cents"] = (
        int(claim["drug_allowed_cents"])
        + int(claim["wastage_allowed_cents"])
        + int(claim["admin_allowed_cents"])
        - claim["standard_drug_cost_cents"]
    )

    enc["status"] = "BILLED"
    touch(enc)
    return created(claim)


@bp.get("/claims/<cid>")
@core.api(READ_ROLES)
def read_claim(cid):
    return ok(get_claim(cid))


@bp.get("/claims")
@core.api(READ_ROLES)
def list_claims():
    limit, offset = pagination()
    filters = query_filters(
        {
            "injection_encounter_id": ("injection_encounter_id", "string"),
            "patient_id": ("patient_id", "string"),
            "payer_id": ("payer_id", "string"),
            "assistance_enrollment_id": ("assistance_enrollment_id", "string"),
            "drug_line_status": ("drug_line_status", "enum", DRUG_LINE_STATUSES),
            "admin_line_status": ("admin_line_status", "enum", ADMIN_LINE_STATUSES),
        }
    )
    return listing(DB.claims.values(), filters, limit, offset)


@bp.post("/claims/<cid>/submit")
@core.api([ROLE_BILLING])
def submit_claim(cid):
    get_body()
    claim = get_claim(cid)
    if claim["drug_line_status"] != "PENDING" or claim["admin_line_status"] != "PENDING":
        fail("ERR_CLAIM_LINE_STATE_INVALID", "the claim's lines have already left PENDING")
    claim["drug_line_status"] = "SUBMITTED"
    claim["admin_line_status"] = "SUBMITTED"
    touch(claim)
    return ok(claim)


@bp.post("/claims/<cid>/remittance")
@core.api([ROLE_BILLING])
def post_remittance(cid):
    body = get_body()
    values = validate(
        body,
        [
            Field("drug_line_outcome", "enum", values=DRUG_OUTCOMES),
            Field("drug_allowed_cents", "integer", minimum=0),
            Field("drug_paid_cents", "integer", minimum=0),
            Field("wastage_allowed_cents", "integer", minimum=0),
            Field("wastage_paid_cents", "integer", minimum=0),
            Field("admin_line_outcome", "enum", values=ADMIN_OUTCOMES),
            Field("admin_allowed_cents", "integer", minimum=0),
            Field("admin_paid_cents", "integer", minimum=0),
            Field("denial_code", "enum", values=DENIAL_CODES),
        ],
    )
    drug_outcome = values["drug_line_outcome"]
    admin_outcome = values["admin_line_outcome"]
    if drug_outcome is None and admin_outcome is None:
        fail("ERR_INVALID_REQUEST", "at least one line outcome must be supplied")
    if drug_outcome == "PAID":
        for name in ("drug_allowed_cents", "drug_paid_cents"):
            if values[name] is None:
                fail("ERR_INVALID_REQUEST", "%s is required for a PAID drug line" % name)
    if drug_outcome == "DENIED" and values["denial_code"] is None:
        fail("ERR_INVALID_REQUEST", "denial_code is required for a DENIED drug line")
    if admin_outcome == "PAID":
        for name in ("admin_allowed_cents", "admin_paid_cents"):
            if values[name] is None:
                fail("ERR_INVALID_REQUEST", "%s is required for a PAID admin line" % name)
    if admin_outcome == "DENIED" and values["denial_code"] is None:
        fail("ERR_INVALID_REQUEST", "denial_code is required for a DENIED admin line")

    claim = get_claim(cid)
    drug_status = claim["drug_line_status"]
    admin_status = claim["admin_line_status"]

    if drug_outcome is not None:
        if drug_status == "PENDING":
            fail("ERR_CLAIM_LINE_STATE_INVALID", "the drug line is still PENDING")
        if drug_outcome in ("PAID", "DENIED") and drug_status not in ("SUBMITTED", "APPEALED"):
            fail("ERR_CLAIM_LINE_STATE_INVALID", "the drug line cannot go %s" % drug_outcome)
        if drug_outcome == "WRITTEN_OFF" and drug_status not in ("DENIED", "APPEALED"):
            fail("ERR_CLAIM_LINE_STATE_INVALID", "the drug line cannot be written off")
    if admin_outcome is not None:
        if admin_status == "PENDING":
            fail("ERR_CLAIM_LINE_STATE_INVALID", "the administration line is still PENDING")
        if admin_status != "SUBMITTED":
            fail("ERR_CLAIM_LINE_STATE_INVALID", "the administration line cannot go %s" % admin_outcome)

    if drug_outcome == "PAID":
        claim["drug_allowed_cents"] = values["drug_allowed_cents"]
        claim["drug_paid_cents"] = values["drug_paid_cents"]
        claim["wastage_allowed_cents"] = values["wastage_allowed_cents"] or 0
        claim["wastage_paid_cents"] = values["wastage_paid_cents"] or 0
        claim["drug_line_status"] = "PAID"
    elif drug_outcome == "DENIED":
        claim["drug_paid_cents"] = 0
        claim["wastage_paid_cents"] = 0
        claim["denial_code"] = values["denial_code"]
        claim["drug_line_status"] = "DENIED"
    elif drug_outcome == "WRITTEN_OFF":
        claim["drug_paid_cents"] = 0
        claim["drug_line_status"] = "WRITTEN_OFF"

    if admin_outcome == "PAID":
        claim["admin_allowed_cents"] = values["admin_allowed_cents"]
        claim["admin_paid_cents"] = values["admin_paid_cents"]
        claim["admin_line_status"] = "PAID"
    elif admin_outcome == "DENIED":
        claim["admin_paid_cents"] = 0
        claim["denial_code"] = values["denial_code"]
        claim["admin_line_status"] = "DENIED"

    run_waterfall(claim, provisional=False)
    if claim_lines_terminal(claim):
        finalize_claim_margin(claim)
    touch(claim)
    return ok(claim)


@bp.post("/claims/<cid>/appeal-drug-line")
@core.api([ROLE_BILLING])
def appeal_drug_line(cid):
    body = get_body()
    values = validate(body, [Field("appeal_basis", "string", required=True, minlen=1)])
    claim = get_claim(cid)
    if claim["drug_line_status"] != "DENIED":
        fail("ERR_CLAIM_LINE_STATE_INVALID", "only a DENIED drug line may be appealed")
    payer = DB.payers[claim["payer_id"]]
    if DB.clock > add_days(claim["updated_at"], payer["appeal_window_days"]):
        fail("ERR_APPEAL_WINDOW_CLOSED", "the payer's appeal window has closed")
    claim["appeal_basis"] = values["appeal_basis"]
    claim["drug_line_status"] = "APPEALED"
    touch(claim)
    return ok(claim)


# ------------------------------------------------------- assistance enrollments
@bp.post("/assistance-enrollments")
@core.api([ROLE_BILLING])
def create_enrollment():
    body = get_body()
    values = validate(
        body,
        [
            Field("patient_id", "id", required=True),
            Field("program_type", "enum", required=True, values=PROGRAM_TYPES),
            Field("annual_benefit_cents", "integer", required=True, minimum=0),
            Field("per_encounter_cap_cents", "integer", required=True, minimum=0),
            Field("effective_date", "datetime", required=True),
            Field("expiration_date", "datetime", required=True),
        ],
    )
    patient = get_patient(values["patient_id"])
    payer = DB.payers[patient["payer_id"]]
    if values["program_type"] == "MANUFACTURER_COPAY_CARD" and payer["federal_program"]:
        fail(
            "ERR_COPAY_CARD_FEDERAL_INELIGIBLE",
            "a federal-program patient may not use a manufacturer copay card",
        )
    row = base_row()
    row.update(
        {
            "patient_id": patient["id"],
            "program_type": values["program_type"],
            "status": "PENDING",
            "annual_benefit_cents": values["annual_benefit_cents"],
            "benefit_used_cents": 0,
            "per_encounter_cap_cents": values["per_encounter_cap_cents"],
            "effective_date": values["effective_date"],
            "expiration_date": values["expiration_date"],
            "termination_reason": None,
        }
    )
    DB.enrollments[row["id"]] = row
    return created(row)


@bp.get("/assistance-enrollments/<eid>")
@core.api(READ_ROLES)
def read_enrollment(eid):
    return ok(get_enrollment(eid))


@bp.get("/assistance-enrollments")
@core.api(READ_ROLES)
def list_enrollments():
    limit, offset = pagination()
    filters = query_filters(
        {
            "patient_id": ("patient_id", "string"),
            "program_type": ("program_type", "enum", PROGRAM_TYPES),
            "status": ("status", "enum", ENROLLMENT_STATUSES),
        }
    )
    return listing(DB.enrollments.values(), filters, limit, offset)


@bp.post("/assistance-enrollments/<eid>/approve")
@core.api([ROLE_BILLING])
def approve_enrollment(eid):
    get_body()
    row = get_enrollment(eid)
    if row["status"] != "PENDING":
        fail("ERR_ENROLLMENT_STATE_INVALID", "only a PENDING enrollment may be approved")
    for other in DB.enrollments.values():
        if (
            other["id"] != row["id"]
            and other["patient_id"] == row["patient_id"]
            and other["status"] == "ACTIVE"
        ):
            fail("ERR_DUPLICATE_ACTIVE_ENROLLMENT", "the patient already has an ACTIVE enrollment")
    row["status"] = "ACTIVE"
    touch(row)
    return ok(row)


@bp.post("/assistance-enrollments/<eid>/terminate")
@core.api([ROLE_BILLING])
def terminate_enrollment(eid):
    body = get_body()
    values = validate(body, [Field("termination_reason", "string", required=True, minlen=1)])
    row = get_enrollment(eid)
    if row["status"] not in ("PENDING", "ACTIVE", "EXHAUSTED"):
        fail("ERR_ENROLLMENT_STATE_INVALID", "a %s enrollment cannot be terminated" % row["status"])
    row["status"] = "TERMINATED"
    row["termination_reason"] = values["termination_reason"]
    touch(row)
    return ok(row)
