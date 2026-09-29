"""Intake, cross-matching and determination (PRD §3.2, §3.3, §3.4)."""

from flask import Blueprint

import calc
import db
import enums
import envelope as env
import services
import validate as v
from errors import fail
from validate import endpoint

bp = Blueprint("applications", __name__)

LIVE_APPLICATION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED")


def _application_or_404(application_id):
    application = db.get("exemption_applications", application_id)
    if application is None:
        fail("ERR_APPLICATION_NOT_FOUND")
    return application


# --------------------------------------------------------------------------
# ExemptionApplication
# --------------------------------------------------------------------------
@bp.post("/exemption-applications")
@endpoint(["IntakeClerk"])
def create_application():
    body = v.body()
    parcel_id = v.req_str(body, "parcel_id")
    taxpayer_id = v.req_str(body, "taxpayer_id")
    program_id = v.req_str(body, "program_id")
    tax_year = v.req_int(body, "tax_year", minimum=2015, maximum=2100)
    claimed_occupancy_date = v.req_date(body, "claimed_occupancy_date")
    claimed_address = v.req_str(body, "claimed_address_normalized")

    if db.get("parcels", parcel_id) is None:
        fail("ERR_PARCEL_NOT_FOUND")
    if db.get("taxpayer_accounts", taxpayer_id) is None:
        fail("ERR_TAXPAYER_NOT_FOUND")
    if db.get("relief_programs", program_id) is None:
        fail("ERR_PROGRAM_NOT_FOUND")

    application = db.insert("exemption_applications", {
        "parcel_id": parcel_id,
        "taxpayer_id": taxpayer_id,
        "program_id": program_id,
        "tax_year": tax_year,
        "claimed_occupancy_date": claimed_occupancy_date,
        "claimed_address_normalized": claimed_address,
        "status": "DRAFT",
        "info_request_round": 0,
        "intake_user_id": v.caller_id(),
        "determined_by_user_id": None,
        "denial_reason": None,
        "resulting_grant_id": None,
    })
    return env.created(db.public(application))


@bp.get("/exemption-applications/<application_id>")
@endpoint(["IntakeClerk", "ExemptionsReviewer", "Taxpayer"])
def read_application(application_id):
    application = _application_or_404(application_id)
    if v.is_taxpayer() and application["taxpayer_id"] != v.caller_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    return env.ok(db.public(application))


@bp.get("/exemption-applications")
@endpoint(["IntakeClerk", "ExemptionsReviewer"])
def list_applications():
    limit, offset = v.pagination()
    parcel_id = v.q_str("parcel_id")
    taxpayer_id = v.q_str("taxpayer_id")
    program_id = v.q_str("program_id")
    status = v.q_enum("status", enums.APPLICATION_STATUSES)
    tax_year = v.q_int("tax_year")
    items = []
    for application in db.rows("exemption_applications"):
        if parcel_id is not None and application["parcel_id"] != parcel_id:
            continue
        if taxpayer_id is not None and application["taxpayer_id"] != taxpayer_id:
            continue
        if program_id is not None and application["program_id"] != program_id:
            continue
        if status is not None and application["status"] != status:
            continue
        if tax_year is not None and application["tax_year"] != tax_year:
            continue
        items.append(db.public(application))
    return env.listing(items, limit, offset)


@bp.post("/exemption-applications/<application_id>/submit")
@endpoint(["IntakeClerk"])
def submit_application(application_id):
    v.body()
    application = _application_or_404(application_id)
    if application["status"] != "DRAFT":
        fail("ERR_APPLICATION_NOT_DRAFT")

    program = db.get("relief_programs", application["program_id"])
    if program is not None and program["status"] != "OPEN":
        fail("ERR_INVALID_REQUEST", "The relief programme is not OPEN for new submissions.")

    taxpayer = db.get("taxpayer_accounts", application["taxpayer_id"])
    if taxpayer is not None and taxpayer["status"] == "BARRED":
        fail("ERR_TAXPAYER_BARRED")

    for other in db.rows("exemption_applications"):
        if other["id"] == application["id"]:
            continue
        if (
            other["parcel_id"] == application["parcel_id"]
            and other["program_id"] == application["program_id"]
            and other["tax_year"] == application["tax_year"]
            and other["status"] in LIVE_APPLICATION_STATUSES
        ):
            fail("ERR_DUPLICATE_APPLICATION")

    application["status"] = "SUBMITTED"
    db.touch(application)
    return env.ok(db.public(application))


@bp.post("/exemption-applications/<application_id>/respond-info")
@endpoint(["Taxpayer"])
def respond_info(application_id):
    application = _application_or_404(application_id)
    if application["taxpayer_id"] != v.caller_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    body = v.body()
    claimed_address = v.req_str(body, "claimed_address_normalized")
    claimed_occupancy_date = v.req_date(body, "claimed_occupancy_date")
    if application["status"] != "INFO_REQUESTED":
        fail("ERR_APPLICATION_NOT_INFO_REQUESTED")

    application["claimed_address_normalized"] = claimed_address
    application["claimed_occupancy_date"] = claimed_occupancy_date
    application["status"] = "UNDER_REVIEW"
    db.touch(application)
    return env.ok(db.public(application))


# --------------------------------------------------------------------------
# VerificationCheck (PRD §3.3)
# --------------------------------------------------------------------------
@bp.post("/exemption-applications/<application_id>/verification-checks")
@endpoint(["IntakeClerk", "ExemptionsReviewer"])
def record_verification_check(application_id):
    application = _application_or_404(application_id)
    body = v.body()
    source = v.req_enum(body, "source", enums.CHECK_SOURCES)

    taxpayer_id = application["taxpayer_id"]
    certification = None

    if source == "INCOME_DOR":
        certification = services.income_dor_certification(taxpayer_id, application["tax_year"])
        record = services.latest_registry_record(taxpayer_id, source)
        if record is None or record["reported_income_cents"] is None or certification is None:
            expected_value = (
                str(certification["household_income_cents"]) if certification is not None else ""
            )
            observed_value = ""
            result = "NO_RECORD"
        else:
            expected_value = str(certification["household_income_cents"])
            observed_value = str(record["reported_income_cents"])
            result = "MATCH" if expected_value == observed_value else "MISMATCH"
    else:
        expected_value = application["claimed_address_normalized"]
        record = services.latest_registry_record(taxpayer_id, source)
        if record is None:
            observed_value = ""
            result = "NO_RECORD"
        else:
            observed_value = record["address_normalized"] or ""
            result = "MATCH" if observed_value == expected_value else "MISMATCH"

    first_check = not db.find("verification_checks", application_id=application["id"])

    check = db.insert("verification_checks", {
        "application_id": application["id"],
        "source": source,
        "checked_at": db.now_iso(),
        "expected_value": expected_value,
        "observed_value": observed_value,
        "result": result,
    }, versioned=False)

    if first_check and application["status"] == "SUBMITTED":
        application["status"] = "UNDER_REVIEW"
        db.touch(application)

    if source == "INCOME_DOR" and result == "MATCH" and certification is not None:
        if certification["status"] == "PENDING":
            certification["status"] = "CERTIFIED"
            db.touch(certification)

    return env.created(db.public(check))


@bp.get("/exemption-applications/<application_id>/verification-checks")
@endpoint(["IntakeClerk", "ExemptionsReviewer", "FraudInvestigator"])
def list_verification_checks(application_id):
    limit, offset = v.pagination()
    source = v.q_enum("source", enums.CHECK_SOURCES)
    result = v.q_enum("result", enums.CHECK_RESULTS)
    application = _application_or_404(application_id)
    items = []
    for check in db.rows("verification_checks"):
        if check["application_id"] != application["id"]:
            continue
        if source is not None and check["source"] != source:
            continue
        if result is not None and check["result"] != result:
            continue
        items.append(db.public(check))
    return env.listing(items, limit, offset)


# --------------------------------------------------------------------------
# IncomeCertification (PRD §3.2)
# --------------------------------------------------------------------------
@bp.post("/income-certifications")
@endpoint(["IntakeClerk"])
def create_income_certification():
    body = v.body()
    taxpayer_id = v.req_str(body, "taxpayer_id")
    certification_year = v.req_int(body, "certification_year", minimum=2015, maximum=2100)
    household_income_cents = v.req_int(body, "household_income_cents", minimum=0)
    countable_asset_cents = v.req_int(body, "countable_asset_cents", minimum=0)
    household_size = v.req_int(body, "household_size", minimum=1, maximum=20)
    recertification_due_date = v.req_date(body, "recertification_due_date")

    if db.get("taxpayer_accounts", taxpayer_id) is None:
        fail("ERR_TAXPAYER_NOT_FOUND")

    certification = db.insert("income_certifications", {
        "taxpayer_id": taxpayer_id,
        "certification_year": certification_year,
        "household_income_cents": household_income_cents,
        "countable_asset_cents": countable_asset_cents,
        "household_size": household_size,
        "recertification_due_date": recertification_due_date,
        "status": "PENDING",
        "relief_tier": "NOT_ASSESSED",
        "relief_multiplier_bps": 0,
    })
    return env.created(db.public(certification))


@bp.get("/taxpayer-accounts/<taxpayer_id>/income-certifications")
@endpoint(["IntakeClerk", "ExemptionsReviewer", "Taxpayer"])
def list_income_certifications(taxpayer_id):
    limit, offset = v.pagination()
    certification_year = v.q_int("certification_year")
    status = v.q_enum("status", enums.CERTIFICATION_STATUSES)
    taxpayer = db.get("taxpayer_accounts", taxpayer_id)
    if taxpayer is None:
        fail("ERR_TAXPAYER_NOT_FOUND")
    if v.is_taxpayer() and taxpayer["id"] != v.caller_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    items = []
    for certification in db.rows("income_certifications"):
        if certification["taxpayer_id"] != taxpayer["id"]:
            continue
        if certification_year is not None and certification["certification_year"] != certification_year:
            continue
        if status is not None and certification["status"] != status:
            continue
        items.append(db.public(certification))
    return env.listing(items, limit, offset)


# --------------------------------------------------------------------------
# Determination (PRD §3.4)
# --------------------------------------------------------------------------
def _residency_verified(application_id):
    """The VOTER_REGISTRY and DEED_REGISTRY latest-check rule of PRD §3.3."""
    for source in ("VOTER_REGISTRY", "DEED_REGISTRY"):
        latest = services.latest_check_per_source(application_id, source)
        if latest is None or latest["result"] != "MATCH":
            return False
    return True


def _reaches_senior_age(date_of_birth, tax_year):
    year, month, day = date_of_birth.split("-")
    sixty_fifth = "%04d-%s-%s" % (int(year) + db.SENIOR_MIN_AGE, month, day)
    return sixty_fifth <= "%04d-01-01" % tax_year


def _eligible(program, taxpayer, application, ownership_record):
    code = program["program_code"]
    if code == "SENIOR_FREEZE":
        return _reaches_senior_age(taxpayer["date_of_birth"], application["tax_year"])
    if code == "VETERAN_DISABILITY":
        return taxpayer["disability_rating_pct_bps"] > 0
    if code == "AGRICULTURAL_USE":
        return ownership_record is not None
    return True


@bp.post("/exemption-applications/<application_id>/determine")
@endpoint(["ExemptionsReviewer"])
def determine_application(application_id):
    application = _application_or_404(application_id)
    if v.caller_id() == application["intake_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    body = v.body()
    outcome = v.req_enum(body, "outcome", enums.DETERMINATION_OUTCOMES)
    expected_parcel_version = v.req_int(body, "expected_parcel_version")
    denial_reason = v.opt_str(body, "denial_reason", None)

    parcel = db.get("parcels", application["parcel_id"])
    if parcel is None or parcel["version"] != expected_parcel_version:
        fail("ERR_STALE_PARCEL_VERSION")

    if application["status"] != "UNDER_REVIEW":
        fail("ERR_APPLICATION_NOT_UNDER_REVIEW")

    program = db.get("relief_programs", application["program_id"])
    taxpayer = db.get("taxpayer_accounts", application["taxpayer_id"])

    if outcome == "REQUEST_INFO":
        if application["info_request_round"] >= db.MAX_INFO_REQUEST_ROUNDS:
            fail("ERR_INFO_REQUEST_LIMIT_REACHED")
        application["info_request_round"] += 1
        application["status"] = "INFO_REQUESTED"
        db.touch(application)
        return env.ok(db.public(application))

    if outcome == "DENY":
        application["denial_reason"] = denial_reason
        application["determined_by_user_id"] = v.caller_id()
        application["status"] = "DENIED"
        db.touch(application)
        services.mail_notice(
            application["taxpayer_id"],
            "EXEMPTION_APPLICATION",
            application["id"],
            "DENIAL",
            "Exemption application denied.",
            appealable=True,
        )
        return env.ok(db.public(application))

    # ---- APPROVE ---------------------------------------------------------
    demanded_occupancy = (
        "AGRICULTURAL" if program["program_code"] == "AGRICULTURAL_USE" else "PRIMARY_RESIDENCE"
    )
    january_first = "%04d-01-01" % application["tax_year"]
    ownership_record = services.verified_ownership(
        application["parcel_id"], application["taxpayer_id"], demanded_occupancy, january_first
    )
    if ownership_record is None:
        fail("ERR_OWNERSHIP_NOT_VERIFIED")

    if not _residency_verified(application["id"]):
        fail("ERR_RESIDENCY_VERIFICATION_FAILED")

    if not _eligible(program, taxpayer, application, ownership_record):
        fail("ERR_EXEMPTION_TYPE_NOT_ELIGIBLE")

    for grant in db.rows("exemption_grants"):
        if (
            grant["parcel_id"] == application["parcel_id"]
            and grant["program_id"] == application["program_id"]
            and grant["effective_tax_year"] == application["tax_year"]
            and grant["benefit_status"] in ("ACTIVE", "SUSPENDED")
        ):
            fail("ERR_DUPLICATE_GRANT")

    certification = None
    relief_tier = None
    relief_multiplier_bps = 10000
    if program["requires_income_certification"]:
        certification = services.certified_certification(
            application["taxpayer_id"], application["tax_year"]
        )
        if certification is None:
            fail("ERR_INCOME_CERTIFICATION_REQUIRED")
        if program["income_limit_cents"] is None:
            relief_tier, relief_multiplier_bps = "TIER_FULL", 10000
        else:
            resolved = calc.income_relief_tier(
                certification["household_income_cents"], program["income_limit_cents"]
            )
            if resolved is None:
                fail("ERR_INCOME_LIMIT_EXCEEDED")
            relief_tier, relief_multiplier_bps = resolved
        if (
            program["asset_limit_cents"] is not None
            and certification["countable_asset_cents"] > program["asset_limit_cents"]
        ):
            fail("ERR_ASSET_LIMIT_EXCEEDED")

    assessed_basis_cents = calc.pre_event_assessed(parcel)
    benefit_amount_cents = calc.benefit_amount(
        assessed_basis_cents,
        program,
        relief_multiplier_bps,
        taxpayer["disability_rating_pct_bps"],
        ownership_record["ownership_pct_bps"],
    )

    frozen = assessed_basis_cents if program["freeze_enabled"] else None
    grant = db.insert("exemption_grants", {
        "application_id": application["id"],
        "parcel_id": application["parcel_id"],
        "taxpayer_id": application["taxpayer_id"],
        "program_id": application["program_id"],
        "ported_from_grant_id": None,
        "exemption_type": program["program_code"],
        "benefit_status": "ACTIVE",
        "suspension_reason": None,
        "effective_tax_year": application["tax_year"],
        "first_eligible_tax_year": int(ownership_record["occupancy_start_date"][:4]),
        "ownership_pct_bps_snapshot": ownership_record["ownership_pct_bps"],
        "relief_multiplier_bps": relief_multiplier_bps,
        "benefit_amount_cents": benefit_amount_cents,
        "applied_exempt_value_cents": 0,
        "frozen_value_cents": frozen,
        "portable_balance_cents": frozen,
        "_supporting_ownership_record_id": ownership_record["id"],
    })

    application["status"] = "APPROVED"
    application["determined_by_user_id"] = v.caller_id()
    application["resulting_grant_id"] = grant["id"]
    db.touch(application)

    calc.decompose(parcel)

    if certification is not None and relief_tier is not None:
        certification["relief_tier"] = relief_tier
        certification["relief_multiplier_bps"] = relief_multiplier_bps
        db.touch(certification)

    return env.ok(db.public(application))
