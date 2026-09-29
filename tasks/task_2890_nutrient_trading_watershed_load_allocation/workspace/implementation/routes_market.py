"""Practice projects, verification, certification, the registry and trading."""
from decimal import Decimal

from flask import Blueprint, g

from auth import require
from calc import (
    delivery_amounts,
    delivery_path,
    mint_batch,
    permit_need,
    reconcile,
    rows_where,
    watershed_of_project,
)
from cascade import (
    open_transactions_of_batch,
    restate_verified_ratio,
    revoke_project_cascade,
    void_transaction,
)
from common import collection_response, filtered, one, resolve, touched
from errors import ApiError
from store import (
    ONE4,
    ZERO2,
    db,
    dec,
    new_row,
    now_iso,
    parse_date,
    q2,
    q4,
    sorted_rows,
    touch,
)
from validation import bad, enum_arg, int_arg, spec, str_arg, validate_body

bp = Blueprint("market", __name__)

PRACTICE_TYPES = ("COVER_CROP", "RIPARIAN_BUFFER", "NUTRIENT_MANAGEMENT", "WETLAND_RESTORATION")
PROJECT_STATUSES = (
    "REGISTERED",
    "BASELINE_VERIFIED",
    "IMPLEMENTED",
    "CERTIFIED",
    "PENDING_REVERIFICATION",
    "REVOKED",
)
LIVE_PROJECT_STATUSES = (
    "REGISTERED",
    "BASELINE_VERIFIED",
    "IMPLEMENTED",
    "CERTIFIED",
    "PENDING_REVERIFICATION",
)
EVENT_TYPES = ("BASELINE", "IMPLEMENTATION", "REVERIFICATION")
OUTCOMES = ("PASS", "PARTIAL", "FAIL")
BATCH_STATUSES = ("ISSUED", "LISTED", "RETIRED", "INVALIDATED")
TRANSACTION_STATUSES = ("PROPOSED", "APPROVED", "VOIDED")

PROJECT_READ_ROLES = (
    "ProgramAdministrator",
    "RegistryAdministrator",
    "PracticeVerifier",
    "Producer",
    "Permittee",
)
EVENT_READ_ROLES = ("ProgramAdministrator", "RegistryAdministrator", "PracticeVerifier", "Producer")
TRANSACTION_READ_ROLES = (
    "ProgramAdministrator",
    "RegistryAdministrator",
    "PermitWriter",
    "Permittee",
)


# --------------------------------------------------------------------------
# practice projects
# --------------------------------------------------------------------------
@bp.route("/practice-projects", methods=["POST"])
def create_practice_project():
    require("Producer")
    body = validate_body(
        [
            spec("producer_id", "id"),
            spec("reach_id", "id"),
            spec("tract_code", "string"),
            spec("practice_type", "enum", enum=PRACTICE_TYPES),
            spec("enrolled_acres", "number", minimum=0, min_exclusive=True, dp=2),
            spec("baseline_met", "bool"),
            spec("pre_load_lbs_yr", "number", minimum=0, dp=2),
            spec("post_load_lbs_yr", "number", minimum=0, dp=2),
            spec("effective_start_date", "date"),
            spec("effective_end_date", "date"),
            spec("vintage_year", "int"),
        ]
    )
    if dec(body["post_load_lbs_yr"]) >= dec(body["pre_load_lbs_yr"]):
        bad("post_load_lbs_yr must be strictly below pre_load_lbs_yr.")
    start = parse_date(body["effective_start_date"])
    end = parse_date(body["effective_end_date"])
    if end <= start:
        bad("effective_end_date must fall strictly after effective_start_date.")

    if body["producer_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    producer = resolve(db.producers, "producer_id", body["producer_id"])
    reach = resolve(db.reaches, "reach_id", body["reach_id"])

    for other in sorted_rows(list(db.practice_projects.values())):
        if other["tract_code"] != body["tract_code"]:
            continue
        if other["practice_type"] != body["practice_type"]:
            continue
        if other["status"] not in LIVE_PROJECT_STATUSES:
            continue
        other_start = parse_date(other["effective_start_date"])
        other_end = parse_date(other["effective_end_date"])
        if start < other_end and other_start < end:
            raise ApiError("ERR_PRACTICE_PERIOD_OVERLAP")

    watershed = db.watersheds.get(reach["watershed_id"])
    if watershed is None or reach["trading_zone_code"] not in watershed["eligible_zone_codes"]:
        raise ApiError("ERR_ZONE_NOT_ELIGIBLE")

    row = new_row(
        "PracticeProject",
        producer_id=producer["id"],
        reach_id=reach["id"],
        tract_code=body["tract_code"],
        practice_type=body["practice_type"],
        enrolled_acres=q2(body["enrolled_acres"]),
        baseline_met=body["baseline_met"],
        pre_load_lbs_yr=q2(body["pre_load_lbs_yr"]),
        post_load_lbs_yr=q2(body["post_load_lbs_yr"]),
        effective_start_date=body["effective_start_date"],
        effective_end_date=body["effective_end_date"],
        vintage_year=body["vintage_year"],
        status="REGISTERED",
        verified_acres=None,
        baseline_verifier_user_id=None,
        implementation_verifier_user_id=None,
        certified_at=None,
    )
    db.practice_projects[row["id"]] = row
    return one(row, 201)


@bp.route("/practice-projects/<practice_project_id>", methods=["GET"])
def get_practice_project(practice_project_id):
    require(*PROJECT_READ_ROLES)
    return one(resolve(db.practice_projects, "practice_project_id", practice_project_id))


@bp.route("/practice-projects", methods=["GET"])
def list_practice_projects():
    require(*PROJECT_READ_ROLES)
    filters = {
        "producer_id": str_arg("producer_id"),
        "reach_id": str_arg("reach_id"),
        "status": enum_arg("status", PROJECT_STATUSES),
        "tract_code": str_arg("tract_code"),
    }
    return collection_response(filtered(db.practice_projects, filters))


# --------------------------------------------------------------------------
# verification events
# --------------------------------------------------------------------------
ACRES_REQUIRED = {("IMPLEMENTATION", "PASS"), ("REVERIFICATION", "PASS"), ("REVERIFICATION", "PARTIAL")}

EVENT_TRANSITIONS = {
    ("BASELINE", "PASS"): {"REGISTERED": "BASELINE_VERIFIED"},
    ("BASELINE", "FAIL"): {"REGISTERED": "REVOKED"},
    ("IMPLEMENTATION", "PASS"): {"BASELINE_VERIFIED": "IMPLEMENTED"},
    ("IMPLEMENTATION", "FAIL"): {"BASELINE_VERIFIED": "REVOKED"},
    ("REVERIFICATION", "PARTIAL"): {"CERTIFIED": "PENDING_REVERIFICATION"},
    ("REVERIFICATION", "PASS"): {"PENDING_REVERIFICATION": "CERTIFIED"},
    ("REVERIFICATION", "FAIL"): {"CERTIFIED": "REVOKED", "PENDING_REVERIFICATION": "REVOKED"},
}


def _event_sort(row):
    return (row["observed_at"], row["created_at"], row["_seq"])


@bp.route("/verification-events", methods=["POST"])
def create_verification_event():
    require("PracticeVerifier")
    body = validate_body(
        [
            spec("practice_project_id", "id"),
            spec("event_type", "enum", enum=EVENT_TYPES),
            spec("outcome", "enum", enum=OUTCOMES),
            spec("narrative", "string"),
            spec("verified_acres", "number", required=False, minimum=0, dp=2),
        ]
    )
    combo = (body["event_type"], body["outcome"])
    acres = body["verified_acres"]
    if combo in ACRES_REQUIRED and acres is None:
        bad("verified_acres is required for this event_type and outcome combination.")
    if combo not in ACRES_REQUIRED and acres is not None:
        bad("verified_acres is forbidden for this event_type and outcome combination.")

    project = resolve(db.practice_projects, "practice_project_id", body["practice_project_id"])

    if acres is not None:
        if dec(acres) > dec(project["enrolled_acres"]):
            bad("verified_acres may not exceed the project's enrolled_acres.")
        if combo == ("IMPLEMENTATION", "PASS") and dec(acres) <= 0:
            bad("verified_acres must be strictly above zero.")
        if project.get("verified_acres") is not None:
            if combo == ("REVERIFICATION", "PARTIAL") and dec(acres) >= dec(project["verified_acres"]):
                bad("verified_acres must be strictly below the project's current verified_acres.")
            if combo == ("REVERIFICATION", "PASS") and dec(acres) != dec(project["verified_acres"]):
                bad("verified_acres must equal the project's current verified_acres.")

    destinations = EVENT_TRANSITIONS.get(combo, {})
    target = destinations.get(project["status"])
    if target is None:
        raise ApiError("ERR_INVALID_STATE")

    if combo == ("BASELINE", "PASS") and not project["baseline_met"]:
        raise ApiError("ERR_BASELINE_NOT_MET")

    if body["event_type"] == "IMPLEMENTATION":
        if project.get("baseline_verifier_user_id") is not None and (
            project["baseline_verifier_user_id"] == g.user_id
        ):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # --- apply the transition
    project["status"] = target
    if combo == ("BASELINE", "PASS"):
        project["baseline_verifier_user_id"] = g.user_id
    if combo == ("IMPLEMENTATION", "PASS"):
        project["verified_acres"] = q2(acres)
        project["implementation_verifier_user_id"] = g.user_id
    touch(project, touched())

    if combo == ("REVERIFICATION", "PARTIAL"):
        ratio = q4(dec(acres) / dec(project["verified_acres"]))
        restate_verified_ratio(project, ratio, touched())
    elif combo == ("REVERIFICATION", "PASS"):
        restate_verified_ratio(project, ONE4, touched())
    elif combo == ("REVERIFICATION", "FAIL"):
        revoke_project_cascade(project, touched())

    event = new_row(
        "VerificationEvent",
        versioned=False,
        practice_project_id=project["id"],
        event_type=body["event_type"],
        outcome=body["outcome"],
        narrative=body["narrative"],
        verified_acres=None if acres is None else q2(acres),
        inspector_user_id=g.user_id,
        observed_at=now_iso(),
        resulting_project_status=project["status"],
    )
    db.verification_events[event["id"]] = event
    return one(event, 201)


@bp.route("/verification-events/<verification_event_id>", methods=["GET"])
def get_verification_event(verification_event_id):
    require(*EVENT_READ_ROLES)
    return one(resolve(db.verification_events, "verification_event_id", verification_event_id))


@bp.route("/verification-events", methods=["GET"])
def list_verification_events():
    require(*EVENT_READ_ROLES)
    filters = {
        "practice_project_id": str_arg("practice_project_id"),
        "event_type": enum_arg("event_type", EVENT_TYPES),
        "outcome": enum_arg("outcome", OUTCOMES),
    }
    return collection_response(filtered(db.verification_events, filters), sort_key=_event_sort)


# --------------------------------------------------------------------------
# certification
# --------------------------------------------------------------------------
@bp.route("/practice-projects/<practice_project_id>/certify", methods=["POST"])
def certify_practice_project(practice_project_id):
    require("RegistryAdministrator")
    project = resolve(db.practice_projects, "practice_project_id", practice_project_id)
    if project["status"] != "IMPLEMENTED":
        raise ApiError("ERR_INVALID_STATE")
    watershed = watershed_of_project(project)
    if watershed is None or watershed["program_status"] != "ACTIVE":
        raise ApiError("ERR_TRADING_SUSPENDED")
    if g.user_id in (
        project.get("baseline_verifier_user_id"),
        project.get("implementation_verifier_user_id"),
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    project["status"] = "CERTIFIED"
    project["certified_at"] = now_iso()
    touch(project, touched())
    batch = mint_batch(project, watershed, touched())
    return one(batch, 201)


# --------------------------------------------------------------------------
# credit batches
# --------------------------------------------------------------------------
def _batch_sort(row):
    return (row["serial_start"], row["created_at"], row["_seq"])


@bp.route("/credit-batches/<credit_batch_id>", methods=["GET"])
def get_credit_batch(credit_batch_id):
    require(*PROJECT_READ_ROLES)
    return one(resolve(db.credit_batches, "credit_batch_id", credit_batch_id))


@bp.route("/credit-batches", methods=["GET"])
def list_credit_batches():
    require(*PROJECT_READ_ROLES)
    filters = {
        "practice_project_id": str_arg("practice_project_id"),
        "status": enum_arg("status", BATCH_STATUSES),
        "vintage_year": int_arg("vintage_year"),
    }
    return collection_response(filtered(db.credit_batches, filters), sort_key=_batch_sort)


@bp.route("/credit-batches/<credit_batch_id>/list", methods=["POST"])
def list_credit_batch_onto_market(credit_batch_id):
    require("RegistryAdministrator")
    batch = resolve(db.credit_batches, "credit_batch_id", credit_batch_id)
    project = db.practice_projects.get(batch["practice_project_id"])
    watershed = watershed_of_project(project) if project else None
    if batch["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    if watershed is None or watershed["program_status"] != "ACTIVE":
        raise ApiError("ERR_TRADING_SUSPENDED")
    if project["status"] != "CERTIFIED":
        raise ApiError("ERR_PROJECT_NOT_CERTIFIED")
    if dec(batch["available_lbs"]) <= 0:
        raise ApiError("ERR_CREDIT_INSUFFICIENT")

    batch["status"] = "LISTED"
    touch(batch, touched())
    return one(batch)


@bp.route("/credit-batches/<credit_batch_id>/retire", methods=["POST"])
def retire_credit_batch(credit_batch_id):
    require("RegistryAdministrator")
    batch = resolve(db.credit_batches, "credit_batch_id", credit_batch_id)
    body = validate_body(
        [
            spec("retire_lbs", "number", minimum=0, dp=2),
            spec("reason", "string"),
        ]
    )
    if batch["status"] not in ("ISSUED", "LISTED"):
        raise ApiError("ERR_INVALID_STATE")
    for txn in db.credit_transactions.values():
        if txn["credit_batch_id"] == batch["id"] and txn["status"] == "PROPOSED":
            raise ApiError("ERR_BATCH_HAS_OPEN_TRANSACTIONS")
    amount = q2(body["retire_lbs"])
    if amount > dec(batch["available_lbs"]):
        raise ApiError("ERR_CREDIT_INSUFFICIENT")

    batch["available_lbs"] = q2(dec(batch["available_lbs"]) - amount)
    batch["retired_lbs"] = q2(dec(batch["retired_lbs"]) + amount)
    if batch["available_lbs"] == ZERO2:
        batch["status"] = "RETIRED"
    touch(batch, touched())

    project = db.practice_projects.get(batch["practice_project_id"])
    watershed = watershed_of_project(project) if project else None
    if watershed is not None:
        watershed["reserve_pool_lbs"] = q2(dec(watershed["reserve_pool_lbs"]) + amount)
        touch(watershed, touched())
    return one(batch)


# --------------------------------------------------------------------------
# credit transactions
# --------------------------------------------------------------------------
def _buyer_reach(permit):
    source = db.source_assessments.get(permit["source_assessment_id"])
    if source is None:
        return None
    return db.reaches.get(source["reach_id"])


def _generating_reach(batch):
    project = db.practice_projects.get(batch["practice_project_id"])
    if project is None:
        return None
    return db.reaches.get(project["reach_id"])


@bp.route("/credit-transactions", methods=["POST"])
def propose_credit_transaction():
    require("Permittee")
    body = validate_body(
        [
            spec("credit_batch_id", "id"),
            spec("permit_id", "id"),
            spec("requested_gross_lbs", "number", minimum=0, min_exclusive=True, dp=2),
            spec("reporting_period_year", "int"),
            spec("expected_credit_batch_version", "int"),
        ]
    )
    candidate = db.permits.get(body["permit_id"])
    if candidate is not None and candidate["permittee_user_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    batch = resolve(db.credit_batches, "credit_batch_id", body["credit_batch_id"])
    permit = resolve(db.permits, "permit_id", body["permit_id"])

    generating = _generating_reach(batch)
    buyer = _buyer_reach(permit)
    if generating is None or buyer is None or generating["watershed_id"] != buyer["watershed_id"]:
        raise ApiError("ERR_WATERSHED_MISMATCH")

    if body["expected_credit_batch_version"] != batch["version"]:
        raise ApiError("ERR_STALE_BATCH_VERSION")

    watershed = db.watersheds.get(buyer["watershed_id"])
    if watershed is None or watershed["program_status"] != "ACTIVE":
        raise ApiError("ERR_TRADING_SUSPENDED")

    if permit.get("reporting_period_year") != body["reporting_period_year"]:
        raise ApiError("ERR_REPORTING_YEAR_MISMATCH")

    delivery_ratio, path_count = delivery_path(generating, buyer)

    requested = q2(body["requested_gross_lbs"])
    if requested > dec(batch["available_lbs"]):
        raise ApiError("ERR_CREDIT_INSUFFICIENT")

    if permit["compliance_status"] != "SHORTFALL" or dec(permit["compliance_gap_lbs"]) <= 0:
        raise ApiError("ERR_NO_COMPLIANCE_GAP")

    retired_to_reserve, tradable, delivered = delivery_amounts(requested, watershed, delivery_ratio)
    if delivered <= ZERO2:
        raise ApiError("ERR_DELIVERY_BELOW_MINIMUM")

    txn = new_row(
        "CreditTransaction",
        credit_batch_id=batch["id"],
        permit_id=permit["id"],
        requested_gross_lbs=requested,
        reporting_period_year=body["reporting_period_year"],
        status="PROPOSED",
        delivery_ratio=delivery_ratio,
        path_reach_count=path_count,
        retired_to_reserve_lbs=retired_to_reserve,
        tradable_lbs=tradable,
        proposed_delivered_lbs=delivered,
        settled_gross_lbs=None,
        settled_delivered_lbs=None,
        applied_lbs=None,
        permit_gap_at_proposal_lbs=permit_need(permit),
        void_reason=None,
        voided_at=None,
        approved_at=None,
    )
    db.credit_transactions[txn["id"]] = txn

    batch["available_lbs"] = q2(dec(batch["available_lbs"]) - requested)
    batch["reserved_lbs"] = q2(dec(batch["reserved_lbs"]) + requested)
    touch(batch, touched())
    return one(txn, 201)


@bp.route("/credit-transactions/<credit_transaction_id>/approve", methods=["POST"])
def approve_credit_transaction(credit_transaction_id):
    require("RegistryAdministrator")
    txn = resolve(db.credit_transactions, "credit_transaction_id", credit_transaction_id)
    batch = db.credit_batches.get(txn["credit_batch_id"])
    permit = db.permits.get(txn["permit_id"])
    project = db.practice_projects.get(batch["practice_project_id"]) if batch else None
    watershed = watershed_of_project(project) if project else None

    if txn["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE")
    if batch is None or batch["status"] != "LISTED":
        raise ApiError("ERR_INVALID_STATE")
    if project is None or project["status"] not in ("CERTIFIED", "PENDING_REVERIFICATION"):
        raise ApiError("ERR_INVALID_STATE")
    if watershed is None or watershed["program_status"] != "ACTIVE":
        raise ApiError("ERR_TRADING_SUSPENDED")
    if permit is None or permit["compliance_status"] != "SHORTFALL" or dec(permit["compliance_gap_lbs"]) <= 0:
        raise ApiError("ERR_NO_COMPLIANCE_GAP")

    requested = dec(txn["requested_gross_lbs"])
    settled_gross = q2(requested * dec(batch["verified_ratio"]))
    retired_to_reserve, _tradable, settled_delivered = delivery_amounts(
        settled_gross, watershed, txn["delivery_ratio"]
    )
    need = permit_need(permit)
    applied = q2(min(settled_delivered, need))

    txn["settled_gross_lbs"] = settled_gross
    txn["settled_delivered_lbs"] = settled_delivered
    txn["retired_to_reserve_lbs"] = retired_to_reserve
    txn["applied_lbs"] = applied
    txn["status"] = "APPROVED"
    txn["approved_at"] = now_iso()
    touch(txn, touched())

    batch["reserved_lbs"] = q2(dec(batch["reserved_lbs"]) - requested)
    batch["retired_lbs"] = q2(dec(batch["retired_lbs"]) + settled_gross)
    batch["available_lbs"] = q2(dec(batch["available_lbs"]) + q2(requested - settled_gross))
    touch(batch, touched())

    watershed["reserve_pool_lbs"] = q2(dec(watershed["reserve_pool_lbs"]) + retired_to_reserve)
    touch(watershed, touched())

    reconcile(permit, "credit_approve", touched())
    return one(txn)


@bp.route("/credit-transactions/<credit_transaction_id>/void", methods=["POST"])
def void_credit_transaction(credit_transaction_id):
    require("RegistryAdministrator", "ProgramAdministrator")
    txn = resolve(db.credit_transactions, "credit_transaction_id", credit_transaction_id)
    validate_body([spec("reason", "string")])
    if txn["status"] not in ("PROPOSED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE")
    void_transaction(txn, "REGISTRY_ACTION", touched())
    return one(txn)


@bp.route("/credit-transactions/<credit_transaction_id>", methods=["GET"])
def get_credit_transaction(credit_transaction_id):
    require(*TRANSACTION_READ_ROLES)
    return one(resolve(db.credit_transactions, "credit_transaction_id", credit_transaction_id))


@bp.route("/credit-transactions", methods=["GET"])
def list_credit_transactions():
    require(*TRANSACTION_READ_ROLES)
    filters = {
        "credit_batch_id": str_arg("credit_batch_id"),
        "permit_id": str_arg("permit_id"),
        "status": enum_arg("status", TRANSACTION_STATUSES),
        "reporting_period_year": int_arg("reporting_period_year"),
    }
    return collection_response(filtered(db.credit_transactions, filters))
