"""Patient treatments: scheduling, administration, and voiding."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import administer as administer_service
from services import claims as claim_service
from services import helpers
from services.helpers import as_dt, as_int, as_str, check_occ
from utils import fmt_ts, parse_iso, utc_now_dt

READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "RevenueCycleManager",
    "NetworkAnalyst",
    "PlatformAdmin",
]


@route("POST", "/networks/patient-treatments", roles=["PracticeAdmin"], status=201, write=True)
def create_treatment(ctx):
    data = ctx.body
    practice = helpers.practice_or_404(as_str(data, "practice_id"))
    helpers.may_edit_practice(ctx.principal, practice["id"])
    provider = helpers.provider_or_404(as_str(data, "provider_id"))
    product = helpers.product_or_404(as_str(data, "drug_product_id"))
    protocol_id = as_str(data, "pathway_protocol_id")

    if provider.get("practice_id") != practice["id"]:
        raise ApiError("ERR_PRACTICE_MISMATCH")
    if product.get("network_id") != practice.get("network_id"):
        raise ApiError("ERR_CROSS_NETWORK_REFERENCE")
    protocol = helpers.protocol_or_404(protocol_id)
    if protocol.get("network_id") != practice.get("network_id"):
        raise ApiError("ERR_CROSS_NETWORK_REFERENCE")
    # The protocol must be PUBLISHED and in scope for the administered product;
    # the guard is what makes a mis-classed protocol unreachable at administration.
    if not helpers.protocol_matches_product(protocol, product):
        raise ApiError("ERR_INVALID_PROTOCOL_FOR_PRODUCT")

    administered_at = as_dt(data, "administered_at", required_=True)
    treatment = db.create(
        "treatments",
        {
            "practice_id": practice["id"],
            "provider_id": provider["id"],
            "drug_product_id": product["id"],
            "pathway_protocol_id": protocol["id"],
            "patient_reference": as_str(data, "patient_reference"),
            "regimen_code": as_str(data, "regimen_code"),
            "payer_name": as_str(data, "payer_name"),
            "admin_fee_cents": as_int(data, "admin_fee_cents", default=0),
            "policy_admin_fee_cents": 0,
            "administered_units": as_int(data, "administered_units", required_=True),
            "dose_count": as_int(data, "dose_count", default=1),
            "vial_yield_units": as_int(data, "vial_yield_units", default=1),
            "administered_at": fmt_ts(administered_at),
            "unmet_dose_units": 0,
            "dose_allocations": [],
            "is_pathway_concordant": False,
            "settlement_priority": None,
            "acquisition_cost_basis_cents": 0,
            "wastage_cost_basis_cents": 0,
            "wastage_units": 0,
            "status": "SCHEDULED",
        },
    )
    return serial(treatment), 201


@route("GET", "/networks/patient-treatments", roles=READ_ROLES)
def list_treatments(ctx):
    rows = filtered(
        db.all_records("treatments"),
        ctx,
        {
            "practice_id": "practice_id",
            "provider_id": "provider_id",
            "drug_product_id": "drug_product_id",
            "pathway_protocol_id": "pathway_protocol_id",
            "status": "status",
        },
    )
    return paginate(ctx, rows)


@route("GET", "/networks/patient-treatments/{treatmentId}", roles=READ_ROLES)
def get_treatment(ctx):
    return serial(helpers.treatment_or_404(ctx.path_id("treatmentId")))


@route("GET", "/networks/patient-treatments/{treatmentId}/consumptions", roles=READ_ROLES)
def treatment_consumptions(ctx):
    treatment = helpers.treatment_or_404(ctx.path_id("treatmentId"))
    return paginate(ctx, db.where("lot_consumptions", treatment_id=treatment["id"]))


@route("GET", "/networks/patient-treatments/{treatmentId}/claims", roles=READ_ROLES)
def treatment_claims(ctx):
    treatment = helpers.treatment_or_404(ctx.path_id("treatmentId"))
    rows = filtered(
        db.where("claims", treatment_id=treatment["id"]), ctx, {"status": "status"}
    )
    return paginate(ctx, rows)


@route(
    "POST",
    "/networks/patient-treatments/{treatmentId}/administer",
    roles=["PracticeAdmin"],
    write=True,
)
def administer_treatment(ctx):
    treatment = helpers.treatment_or_404(ctx.path_id("treatmentId"))
    practice = helpers.practice_or_404(treatment["practice_id"])
    helpers.may_edit_practice(ctx.principal, practice["id"])
    product = helpers.product_or_404(treatment["drug_product_id"])
    provider = helpers.provider_or_404(treatment["provider_id"])
    instant = utc_now_dt()

    # Priority 3.5 — stale practice view is rejected ahead of any business logic.
    check_occ(ctx.body, practice)

    if treatment["status"] != "SCHEDULED":
        raise ApiError("ERR_TREATMENT_NOT_SCHEDULED")
    if (
        practice["affiliation_status"] != "AFFILIATED"
        or practice["pathway_steering_status"] != "ACTIVE"
    ):
        raise ApiError("ERR_PRACTICE_NOT_AFFILIATED")
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE")

    administered_at = parse_iso(treatment.get("administered_at"))
    if administered_at is None or administered_at > instant:
        raise ApiError("ERR_INVALID_ADMINISTRATION_TIME")

    administered_units = int(treatment.get("administered_units") or 0)
    if administered_units <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "administered_units must be positive")

    # Priority 7 — the oncology regimen guard runs before stock sufficiency.
    protocol = helpers.protocol_or_404(treatment.get("pathway_protocol_id"))
    declared = protocol.get("declared_regimen_codes") or []
    if treatment.get("regimen_code") not in declared:
        raise ApiError("ERR_OFF_PATHWAY_REGIMEN_REJECTED")

    plan = administer_service.ensure_dose_plan(ctx.body)
    plan_detail = administer_service.draw_plan(
        administered_units,
        treatment.get("vial_yield_units"),
        treatment.get("dose_count"),
    )
    usable = administer_service.usable_units(practice["id"], product["id"], administered_at)
    if usable < plan_detail["total_draw_units"]:
        raise ApiError("ERR_INSUFFICIENT_STOCK")

    administer_service.administer(treatment, practice, plan)

    # A PayerClaim is created in DRAFT for this treatment.
    claim = db.create(
        "claims",
        {
            "practice_id": practice["id"],
            "treatment_id": treatment["id"],
            "payer_name": treatment.get("payer_name"),
            "billed_amount_cents": 0,
            "allowed_amount_cents": None,
            "paid_amount_cents": None,
            "billed_admin_fee_cents": 0,
            "written_off_admin_fee_cents": 0,
            "policy_admin_fee_cents": 0,
            "denial_reason_code": None,
            "appeal_round": 0,
            "post_settlement_disclosure": False,
            "write_off_tier": None,
            "write_off_cents": 0,
            "status": "DRAFT",
        },
    )
    claim_service.refresh_claim_fields(treatment, claim)
    db.touch(claim)

    helpers.recompute_adherence(practice)
    claim_service.assign_settlement_priority(practice)
    helpers.recompute_tier(practice)
    db.touch(practice)
    db.touch(treatment)
    return serial(treatment)


@route("POST", "/networks/patient-treatments/{treatmentId}/void", roles=["NetworkAdmin"], write=True)
def void_treatment(ctx):
    treatment = helpers.treatment_or_404(ctx.path_id("treatmentId"))
    practice = helpers.practice_or_404(treatment["practice_id"])
    claim = _claim_for(treatment)

    if treatment["status"] == "ADMINISTERED":
        if claim is not None and claim["status"] not in ("DRAFT", "DENIED"):
            raise ApiError("ERR_TREATMENT_HAS_SUBMITTED_CLAIM")
        if claim is not None and int(claim.get("appeal_round") or 0) > 0:
            raise ApiError("ERR_TREATMENT_HAS_SUBMITTED_CLAIM")
    elif treatment["status"] == "BILLED":
        if claim is None or claim["status"] != "VOIDED":
            raise ApiError("ERR_TREATMENT_HAS_SUBMITTED_CLAIM")
    else:
        raise ApiError("ERR_TREATMENT_NOT_ADMINISTERED")

    treatment["status"] = "VOIDED"
    if claim is not None and claim["status"] != "VOIDED":
        claim["status"] = "VOIDED"
        db.touch(claim)
    helpers.recompute_adherence(practice)
    db.touch(practice)
    db.touch(treatment)
    return serial(treatment)


def _claim_for(treatment):
    rows = db.where("claims", treatment_id=treatment["id"])
    return rows[0] if rows else None