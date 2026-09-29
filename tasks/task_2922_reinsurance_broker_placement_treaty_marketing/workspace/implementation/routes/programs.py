"""The treaty placement file and everything hung directly off a program."""
from decimal import Decimal

from flask import Blueprint

import calc
import db
import enums
import response
import serialize
import services
import validate
from errors import fail
from middleware import (
    BROKER_ACCOUNTANT,
    BROKER_ACTUARY,
    BROKER_PLACEMENT_LEAD,
    CEDENT_UNDERWRITER,
    COMPLIANCE_OFFICER,
    require,
)
from routes._common import CEDENT_READ, EVERY_ROLE, LEDGER_READ, ordered_filtered, paged, q
from util import add_days, day_span, dec, pct4

bp = Blueprint("programs", __name__)

DEFAULT_CURRENCY = "USD"
DEFAULT_BROKERAGE_PCT = Decimal("2.5000")
CERTAINTY_DAYS = calc.CERTAINTY_WINDOW_DAYS


# ---------------------------------------------------------------------------
# Opening and reading the file
# ---------------------------------------------------------------------------

def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap."""
    return a_start < b_end and b_start < a_end


@bp.route("/programs", methods=["POST"])
def create_program():
    require((BROKER_PLACEMENT_LEAD,))
    shape = validate.Shape()
    cedent_id = shape.id_ref("cedent_id")
    program_name = shape.string("program_name", min_len=1, max_len=120)
    line_of_business = shape.enum("line_of_business", enums.LINES_OF_BUSINESS)
    underwriting_year = shape.integer("underwriting_year", minimum=2020, maximum=2035)
    inception_date = shape.instant("inception_date")
    expiry_date = shape.instant("expiry_date")
    estimated_premium_income_minor = shape.money("estimated_premium_income_minor",
                                                 minimum=None, exclusive_min=0)
    prior_program_id = shape.id_ref("prior_program_id", required=False, default=None)
    currency_code = shape.upper_code("currency_code", 3, required=False,
                                     default=DEFAULT_CURRENCY)
    brokerage_pct = shape.percent("brokerage_pct", minimum=0, maximum=10,
                                  required=False, default=DEFAULT_BROKERAGE_PCT)
    signdown_method = shape.enum("signdown_method", enums.SIGNDOWN_METHODS,
                                 required=False, default="PRO_RATA")

    cedent = services.get_cedent(cedent_id)
    prior = None
    if prior_program_id is not None:
        prior = services.get_prior_program(prior_program_id)

    # Priority 43: the treaty period itself.
    if expiry_date <= inception_date:
        fail("ERR_TREATY_PERIOD_INVALID",
             "expiry_date must be strictly after inception_date")
    if inception_date.year != underwriting_year:
        fail("ERR_TREATY_PERIOD_INVALID",
             "inception_date must fall in the underwriting_year")

    # Priority 50: overlapping live period for the same cedent and line.
    for other in db.ordered(db.programs):
        if other["cedent_id"] != cedent_id:
            continue
        if other["line_of_business"] != line_of_business:
            continue
        if other["placement_status"] == "WITHDRAWN":
            continue
        if _overlaps(inception_date, expiry_date,
                     other["inception_date"], other["expiry_date"]):
            fail("ERR_OVERLAPPING_TREATY_PERIOD",
                 "the treaty period overlaps program %s" % other["id"])

    # Priority 51: the renewal chain.
    if prior is not None:
        if (prior["cedent_id"] != cedent_id
                or prior["line_of_business"] != line_of_business
                or prior["underwriting_year"] != underwriting_year - 1):
            fail("ERR_RENEWAL_PRIOR_MISMATCH",
                 "prior_program_id is not the expiring program of this treaty")

    row = db.base_row()
    row.update({
        "cedent_id": cedent_id,
        "prior_program_id": prior_program_id,
        "program_name": program_name,
        "line_of_business": line_of_business,
        "underwriting_year": underwriting_year,
        "inception_date": inception_date,
        "expiry_date": expiry_date,
        "currency_code": currency_code,
        "estimated_premium_income_minor": estimated_premium_income_minor,
        "brokerage_pct": pct4(brokerage_pct),
        "signdown_method": signdown_method,
        "placement_status": "DRAFT",
        "documentation_status": "NOT_STARTED",
        "contract_certainty_deadline": add_days(inception_date, CERTAINTY_DAYS),
        "disclosure_acknowledged": False,
        "gross_written_premium_minor": 0,
        "brokerage_earned_minor": 0,
        "net_remittance_minor": 0,
        "rounding_residue_minor": 0,
        "fiduciary_holding_minor": 0,
        "withdrawal_reason": None,
    })
    db.programs[row["id"]] = row
    assert cedent is not None
    return response.object_response(serialize.program(row), 201)


@bp.route("/programs", methods=["GET"])
def list_programs():
    require(CEDENT_READ)
    rows = ordered_filtered(db.programs, [
        ("cedent_id", q("cedent_id")),
        ("prior_program_id", q("prior_program_id")),
        ("placement_status", q("placement_status")),
        ("documentation_status", q("documentation_status")),
        ("line_of_business", q("line_of_business")),
    ])
    return paged(rows, serialize.program)


@bp.route("/programs/<program_id>", methods=["GET"])
def read_program(program_id):
    require(CEDENT_READ)
    program = services.get_program(program_id)
    return response.object_response(serialize.program(program), 200)


# ---------------------------------------------------------------------------
# Placement-state transitions
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/go-to-market", methods=["POST"])
def go_to_market(program_id):
    require((BROKER_PLACEMENT_LEAD,))
    program = services.get_program(program_id)
    if program["placement_status"] != "SUBMISSION_READY":
        fail("ERR_PROGRAM_STATE_INVALID",
             "a program is released to market only from SUBMISSION_READY")
    cedent = services.get_cedent(program["cedent_id"])
    if cedent["status"] != "ACTIVE":
        fail("ERR_CEDENT_SUSPENDED", "the ceding insurer is suspended")
    layers = services.layers_of_program(program["id"])
    if not any(l["status"] == "OPEN" for l in layers):
        fail("ERR_PROGRAM_STATE_INVALID",
             "at least one layer of the program must still be OPEN")
    if program["documentation_status"] != "NOT_STARTED":
        fail("ERR_PROGRAM_STATE_INVALID",
             "the program's documentation has already started")

    program["placement_status"] = "IN_MARKET"
    db.touch(program)
    return response.object_response(serialize.program(program), 200)


@bp.route("/programs/<program_id>/bind", methods=["POST"])
def bind(program_id):
    require((BROKER_PLACEMENT_LEAD,))
    program = services.get_program(program_id)
    if program["placement_status"] != "FIRM_ORDER":
        fail("ERR_PROGRAM_STATE_INVALID", "a program is bound only from FIRM_ORDER")
    if not program["disclosure_acknowledged"]:
        fail("ERR_DISCLOSURE_NOT_ACKNOWLEDGED",
             "the compensation disclosure has not been acknowledged")
    for layer in services.layers_of_program(program["id"]):
        if layer["status"] == "LAPSED":
            continue
        if layer["status"] not in ("FULLY_PLACED", "SIGNED_DOWN"):
            fail("ERR_LAYER_STATE_INVALID",
                 "layer %s is neither fully placed nor signed down" % layer["id"])

    services.bind_program(program)
    return response.object_response(serialize.program(program), 200)


@bp.route("/programs/<program_id>/settle", methods=["POST"])
def settle(program_id):
    require((BROKER_ACCOUNTANT,))
    program = services.get_program(program_id)
    if program["placement_status"] != "BOUND":
        fail("ERR_PROGRAM_STATE_INVALID", "a program is settled only from BOUND")
    if program["documentation_status"] not in ("WORDING_AGREED", "EXECUTED"):
        fail("ERR_DOCUMENTATION_NOT_AGREED",
             "the placement's wording has never been agreed")
    for txn in services.transactions_of_program(program["id"]):
        if txn["status"] in ("PENDING", "APPROVED", "HELD"):
            fail("ERR_PROGRAM_HAS_OPEN_TRANSACTIONS",
                 "movement %s is still open" % txn["id"])

    services.settle_program(program)
    return response.object_response(serialize.program(program), 200)


@bp.route("/programs/<program_id>/withdraw", methods=["POST"])
def withdraw(program_id):
    require((BROKER_PLACEMENT_LEAD,))
    shape = validate.Shape()
    reason = shape.string("reason", min_len=1, max_len=500)

    program = services.get_program(program_id)
    if program["placement_status"] not in (
            "DRAFT", "SUBMISSION_READY", "IN_MARKET", "FIRM_ORDER"):
        fail("ERR_PROGRAM_STATE_INVALID",
             "a program cannot be withdrawn from %s" % program["placement_status"])

    if program["placement_status"] in ("IN_MARKET", "FIRM_ORDER"):
        services.withdraw_program_cascade(program)

    program["withdrawal_reason"] = reason
    program["placement_status"] = "WITHDRAWN"
    db.touch(program)
    return response.object_response(serialize.program(program), 200)


@bp.route("/programs/<program_id>/market-sweep", methods=["POST"])
def market_sweep(program_id):
    require((BROKER_PLACEMENT_LEAD,))
    program = services.get_program(program_id)
    if program["placement_status"] != "IN_MARKET":
        fail("ERR_PROGRAM_STATE_INVALID", "only an IN_MARKET program can be swept")

    now = db.now()
    layer_ids = {l["id"] for l in services.layers_of_program(program["id"])}
    for submission in db.ordered(db.market_submissions):
        if submission["layer_id"] not in layer_ids:
            continue
        if submission["status"] != "SENT":
            continue
        if submission["response_deadline"] <= now:
            submission["status"] = "EXPIRED"
            db.touch(submission)
    for quote in db.ordered(db.quotes):
        if quote["layer_id"] not in layer_ids:
            continue
        if quote["status"] not in ("QUOTED", "COUNTERED", "REQUOTED"):
            continue
        if quote["expires_at"] <= now:
            quote["status"] = "LAPSED"
            db.touch(quote)
    return response.object_response(serialize.program(program), 200)


@bp.route("/programs/<program_id>/documentation-checkpoint", methods=["POST"])
def documentation_checkpoint(program_id):
    require((COMPLIANCE_OFFICER,))
    program = services.get_program(program_id)
    if db.now() <= program["contract_certainty_deadline"]:
        fail("ERR_CERTAINTY_NOT_BREACHED",
             "the contract certainty deadline has not yet passed")
    if program["documentation_status"] not in (
            "NOT_STARTED", "SLIP_ISSUED", "WORDING_DRAFTED"):
        fail("ERR_CERTAINTY_NOT_BREACHED",
             "the program's documentation state has nothing left to test")

    services.breach_contract_certainty(program)
    return response.object_response(serialize.program(program), 200)


# ---------------------------------------------------------------------------
# Exposure packages of a program (PRD 3.2)
# ---------------------------------------------------------------------------

def score_submission(row):
    row["completeness_score"] = calc.submission_completeness_score(
        row["exposure_records_count"],
        row["data_quality_flags_count"],
        row["historical_years_supplied"],
        row["loss_history_completeness_pct"],
        row["actuarial_report_attached"],
    )
    return row["completeness_score"]


@bp.route("/programs/<program_id>/exposure-submissions", methods=["POST"])
def create_exposure_submission(program_id):
    require((BROKER_PLACEMENT_LEAD, CEDENT_UNDERWRITER))
    shape = validate.Shape()
    package_label = shape.string("package_label", min_len=1, max_len=80)
    exposure_records_count = shape.integer("exposure_records_count", minimum=0)
    data_quality_flags_count = shape.integer("data_quality_flags_count", minimum=0)
    historical_years_supplied = shape.integer("historical_years_supplied",
                                              minimum=0, maximum=20)
    cat_model_version = shape.string("cat_model_version", min_len=1, max_len=40)
    loss_history_completeness_pct = shape.percent("loss_history_completeness_pct",
                                                  minimum=0, maximum=100)
    actuarial_report_attached = shape.boolean("actuarial_report_attached",
                                              required=False, default=False)
    if data_quality_flags_count > exposure_records_count:
        from errors import bad_request
        bad_request("data_quality_flags_count may not exceed exposure_records_count")

    program = services.get_program(program_id)

    row = db.base_row()
    row.update({
        "program_id": program["id"],
        "package_label": package_label,
        "exposure_records_count": exposure_records_count,
        "data_quality_flags_count": data_quality_flags_count,
        "historical_years_supplied": historical_years_supplied,
        "cat_model_version": cat_model_version,
        "loss_history_completeness_pct": pct4(loss_history_completeness_pct),
        "actuarial_report_attached": actuarial_report_attached,
        "completeness_score": Decimal("0.00"),
        "status": "DRAFT",
        "actuary_signoff_user_id": None,
        "signed_off_at": None,
        "review_note": None,
    })
    score_submission(row)
    db.exposure_submissions[row["id"]] = row
    return response.object_response(serialize.exposure_submission(row), 201)


@bp.route("/programs/<program_id>/exposure-submissions", methods=["GET"])
def list_program_exposure_submissions(program_id):
    require(CEDENT_READ)
    validate.pagination()
    services.get_program(program_id)
    rows = [r for r in db.ordered(db.exposure_submissions)
            if r["program_id"] == program_id]
    status = q("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows, serialize.exposure_submission)


# ---------------------------------------------------------------------------
# Layers of a program (PRD 3.3)
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/layers", methods=["POST"])
def create_layer(program_id):
    require((BROKER_PLACEMENT_LEAD,))
    shape = validate.Shape()
    layer_label = shape.string("layer_label", min_len=1, max_len=80)
    layer_type = shape.enum("layer_type", enums.LAYER_TYPES)
    attachment_minor = shape.money("attachment_minor", minimum=0)
    limit_minor = shape.money("limit_minor", minimum=None, exclusive_min=0)
    base_rate_pct = shape.percent("base_rate_pct", exclusive_min=0, maximum=100)
    subject_premium_base_minor = shape.money("subject_premium_base_minor",
                                             minimum=None, exclusive_min=0)
    expected_loss_cost_minor = shape.money("expected_loss_cost_minor", minimum=0)
    cession_pct = shape.percent("cession_pct", minimum=0, maximum=100,
                                required=False, default=Decimal("0.0000"))
    reinstatements_total = shape.integer("reinstatements_total", minimum=0, maximum=5,
                                         required=False, default=0)
    reinstatement_premium_pct = shape.percent("reinstatement_premium_pct",
                                              minimum=0, maximum=200, required=False,
                                              default=Decimal("100.0000"))
    sublimit_minor = shape.money("sublimit_minor", minimum=0, required=False, default=0)
    ceding_commission_pct = shape.percent("ceding_commission_pct", minimum=0,
                                          maximum=60, required=False,
                                          default=Decimal("0.0000"))
    excluded_perils = shape.enum_array("excluded_perils", enums.PERILS,
                                       required=False, default=[])

    program = services.get_program(program_id)
    if program["placement_status"] not in ("DRAFT", "SUBMISSION_READY"):
        fail("ERR_PROGRAM_STATE_INVALID",
             "layers may only be added while the program is DRAFT or SUBMISSION_READY")

    row = db.base_row()
    row.update({
        "program_id": program["id"],
        "layer_label": layer_label,
        "layer_type": layer_type,
        "attachment_minor": attachment_minor,
        "limit_minor": limit_minor,
        "cession_pct": pct4(cession_pct),
        "base_rate_pct": pct4(base_rate_pct),
        "subject_premium_base_minor": subject_premium_base_minor,
        "expected_loss_cost_minor": expected_loss_cost_minor,
        "reinstatements_total": reinstatements_total,
        "reinstatement_premium_pct": pct4(reinstatement_premium_pct),
        "sublimit_minor": sublimit_minor,
        "ceding_commission_pct": pct4(ceding_commission_pct),
        "excluded_perils": list(excluded_perils),
        "quoted_gross_premium_minor": 0,
        "written_line_total_pct": Decimal("0.0000"),
        "signed_line_total_pct": Decimal("0.0000"),
        "limit_eroded_minor": 0,
        "reinstatements_used": 0,
        "incurred_ceded_minor": 0,
        "loss_ratio_pct": None,
        "provisional_ceding_commission_minor": None,
        "final_ceding_commission_minor": None,
        "ceding_commission_delta_minor": None,
        "status": "OPEN",
    })
    services.check_layer_structure(row)
    services.apply_technical_premium(row)
    db.layers[row["id"]] = row
    return response.object_response(serialize.layer(row), 201)


@bp.route("/programs/<program_id>/layers", methods=["GET"])
def list_program_layers(program_id):
    require(EVERY_ROLE)
    validate.pagination()
    services.get_program(program_id)
    rows = [r for r in db.ordered(db.layers) if r["program_id"] == program_id]
    status = q("status")
    layer_type = q("layer_type")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if layer_type is not None:
        rows = [r for r in rows if r["layer_type"] == layer_type]
    return paged(rows, serialize.layer)


# ---------------------------------------------------------------------------
# The slip-to-contract trail (PRD 3.7)
# ---------------------------------------------------------------------------

DOC_SEQUENCE = {
    "SLIP": (("NOT_STARTED",), "SLIP_ISSUED"),
    "WORDING_DRAFT": (("SLIP_ISSUED",), "WORDING_DRAFTED"),
    "AGREED_WORDING": (("WORDING_DRAFTED", "CERTAINTY_BREACHED"), "WORDING_AGREED"),
    "EXECUTED_CONTRACT": (("WORDING_AGREED",), "EXECUTED"),
}

DOC_PLACEMENT = {
    "SLIP": ("FIRM_ORDER", "BOUND"),
    "EXECUTED_CONTRACT": ("BOUND",),
}


@bp.route("/programs/<program_id>/contract-documents", methods=["POST"])
def file_contract_document(program_id):
    actor = require((BROKER_PLACEMENT_LEAD,))
    shape = validate.Shape()
    document_type = shape.enum("document_type", enums.DOCUMENT_TYPES)
    wording_reference = shape.string("wording_reference", min_len=1, max_len=60)

    program = services.get_program(program_id)
    admitted, next_state = DOC_SEQUENCE[document_type]
    if program["documentation_status"] not in admitted:
        fail("ERR_DOCUMENT_SEQUENCE_INVALID",
             "a %s does not follow from %s"
             % (document_type, program["documentation_status"]))
    required_placement = DOC_PLACEMENT.get(document_type)
    if required_placement is not None and program["placement_status"] not in required_placement:
        fail("ERR_PROGRAM_STATE_INVALID",
             "a %s requires the placement to be %s"
             % (document_type, " or ".join(required_placement)))

    issued_at = db.now()
    row = db.base_row(versioned=False)
    row.update({
        "program_id": program["id"],
        "document_type": document_type,
        "wording_reference": wording_reference,
        "issued_at": issued_at,
        "days_from_inception": day_span(issued_at, program["inception_date"]),
        "filed_by_user_id": actor.user_id,
    })
    db.contract_documents[row["id"]] = row

    program["documentation_status"] = next_state
    db.touch(program)
    if document_type == "AGREED_WORDING":
        services.release_held_transactions(program)
    return response.object_response(serialize.contract_document(row), 201)


@bp.route("/programs/<program_id>/contract-documents", methods=["GET"])
def list_program_documents(program_id):
    require(CEDENT_READ)
    validate.pagination()
    services.get_program(program_id)
    rows = [r for r in db.ordered(db.contract_documents)
            if r["program_id"] == program_id]
    document_type = q("document_type")
    if document_type is not None:
        rows = [r for r in rows if r["document_type"] == document_type]
    return paged(rows, serialize.contract_document)


# ---------------------------------------------------------------------------
# Compensation disclosures of a program (PRD 3.6)
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/brokerage-disclosures", methods=["POST"])
def create_disclosure(program_id):
    require((BROKER_ACCOUNTANT,))
    shape = validate.Shape()
    brokerage_pct = shape.percent("brokerage_pct", minimum=0, maximum=100)
    contingent_commission_pct = shape.percent("contingent_commission_pct", minimum=0,
                                              maximum=10, required=False,
                                              default=Decimal("0.0000"))
    market_service_fee_minor = shape.money("market_service_fee_minor", minimum=0,
                                           required=False, default=0)

    program = services.get_program(program_id)

    row = db.base_row()
    row.update({
        "program_id": program["id"],
        "brokerage_pct": pct4(brokerage_pct),
        "contingent_commission_pct": pct4(contingent_commission_pct),
        "market_service_fee_minor": market_service_fee_minor,
        "disclosed_by_user_id": None,
        "acknowledged_by_user_id": None,
        "decision_note": None,
        "status": "DRAFT",
    })
    db.brokerage_disclosures[row["id"]] = row
    return response.object_response(serialize.brokerage_disclosure(row), 201)


@bp.route("/programs/<program_id>/brokerage-disclosures", methods=["GET"])
def list_program_disclosures(program_id):
    require(CEDENT_READ)
    validate.pagination()
    services.get_program(program_id)
    rows = [r for r in db.ordered(db.brokerage_disclosures)
            if r["program_id"] == program_id]
    status = q("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows, serialize.brokerage_disclosure)


# ---------------------------------------------------------------------------
# The fiduciary ledger of a program (PRD 3.8)
# ---------------------------------------------------------------------------

LINK_REQUIRED = ("REINSURER_REMITTANCE", "REINSTATEMENT_PREMIUM", "CLAIM_COLLECTION")


@bp.route("/programs/<program_id>/fiduciary-transactions", methods=["POST"])
def book_transaction(program_id):
    actor = require((BROKER_ACCOUNTANT,))
    shape = validate.Shape()
    txn_type = shape.enum("txn_type", enums.TXN_TYPES)
    amount_minor = shape.money("amount_minor", minimum=None, exclusive_min=0)
    expected_program_version = shape.integer("expected_program_version", minimum=0)
    signing_line_id = shape.id_ref("signing_line_id", required=False, default=None)

    program = services.get_program(program_id)
    line = None
    if signing_line_id is not None:
        line = services.get_signing_line(signing_line_id)

    if expected_program_version != program["version"]:
        fail("ERR_STALE_PROGRAM_VERSION",
             "expected_program_version %s is not the program's current version %s"
             % (expected_program_version, program["version"]))

    if txn_type == "REMITTANCE_REVERSAL":
        fail("ERR_TRANSACTION_TYPE_LINK_INVALID",
             "a REMITTANCE_REVERSAL is only ever created by the system")
    if txn_type in LINK_REQUIRED and line is None:
        fail("ERR_TRANSACTION_TYPE_LINK_INVALID",
             "a %s must be attributed to a signing line" % txn_type)
    if txn_type not in LINK_REQUIRED and line is not None:
        fail("ERR_TRANSACTION_TYPE_LINK_INVALID",
             "a %s may not carry a signing_line_id" % txn_type)

    if line is not None:
        layer = services.layer_of_line(line)
        if layer["program_id"] != program["id"]:
            fail("ERR_LINE_LAYER_MISMATCH",
                 "signing line %s does not sit on a layer of this program"
                 % line["id"])

    row = services.new_transaction(program, txn_type, amount_minor, actor.user_id,
                                   signing_line_id=signing_line_id)
    db.touch(program)
    return response.object_response(serialize.fiduciary_transaction(row), 201)


@bp.route("/programs/<program_id>/fiduciary-transactions", methods=["GET"])
def list_program_transactions(program_id):
    require(LEDGER_READ)
    validate.pagination()
    services.get_program(program_id)
    rows = services.transactions_of_program(program_id)
    for field in ("signing_line_id", "reverses_transaction_id", "txn_type", "status"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paged(rows, serialize.fiduciary_transaction)


# ---------------------------------------------------------------------------
# Renewal analytics (PRD 3.9)
# ---------------------------------------------------------------------------

def _placement_efficiency(program_id):
    written = Decimal("0.0000")
    signed = Decimal("0.0000")
    for line in services.lines_of_program(program_id):
        written += dec(line["written_line_pct"])
        if line["status"] == "BOUND" and line["signed_line_pct"] is not None:
            signed += dec(line["signed_line_pct"])
    return calc.placement_efficiency_pct(signed, written)


@bp.route("/programs/<program_id>/renewal-reports", methods=["POST"])
def create_renewal_report(program_id):
    actor = require((BROKER_ACTUARY,))
    validate.Shape()
    program = services.get_program(program_id)
    if program["placement_status"] not in ("BOUND", "SETTLED"):
        fail("ERR_PROGRAM_STATE_INVALID",
             "renewal analytics require a BOUND or SETTLED program")

    current_limit = services.bound_limit_minor(program["id"])
    current_rate = calc.rate_on_line_pct(program["gross_written_premium_minor"],
                                        current_limit)

    prior = None
    if program["prior_program_id"] is not None:
        prior = db.programs.get(program["prior_program_id"])
    if prior is None:
        prior_limit = 0
        prior_rate = Decimal("0.0000")
    else:
        prior_limit = services.bound_limit_minor(prior["id"])
        prior_rate = calc.rate_on_line_pct(prior["gross_written_premium_minor"],
                                           prior_limit)

    if prior is None or prior_limit == 0 or prior_rate == Decimal("0.0000"):
        rate_change = Decimal("0.00")
        exposure_change = Decimal("0.00")
    else:
        rate_change = calc.rate_change_pct(current_rate, prior_rate)
        exposure_change = calc.exposure_change_pct(current_limit, prior_limit)

    risk_adjusted = calc.risk_adjusted_rate_change_pct(rate_change, exposure_change)
    efficiency = _placement_efficiency(program["id"])
    index = calc.market_condition_index(risk_adjusted, efficiency)

    row = db.base_row(versioned=False)
    row.update({
        "program_id": program["id"],
        "current_rate_on_line_pct": current_rate,
        "prior_rate_on_line_pct": prior_rate,
        "rate_change_pct": rate_change,
        "exposure_change_pct": exposure_change,
        "risk_adjusted_rate_change_pct": risk_adjusted,
        "placement_efficiency_pct": efficiency,
        "market_condition_index": index,
        "generated_by_user_id": actor.user_id,
        "as_of": db.now(),
    })
    db.renewal_reports[row["id"]] = row
    return response.object_response(serialize.renewal_report(row), 201)


@bp.route("/programs/<program_id>/renewal-reports", methods=["GET"])
def list_program_reports(program_id):
    require(CEDENT_READ)
    validate.pagination()
    services.get_program(program_id)
    rows = [r for r in db.ordered(db.renewal_reports)
            if r["program_id"] == program_id]
    return paged(rows, serialize.renewal_report)
