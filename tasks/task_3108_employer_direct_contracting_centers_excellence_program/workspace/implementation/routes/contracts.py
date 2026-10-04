"""Contracts: creation, activation, repricing, termination, and patients."""
from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_bool,
    f_dt,
    f_int,
    f_map,
    f_str,
    new_row,
    paginate,
    q_str,
    respond_object,
    sort_created,
    touch,
)
from core import scope_employer
from domain import (
    CONTRACT_STATUSES,
    get_or_404,
    terminate_contract,
)

bp = Blueprint("contracts", __name__)


def _validate_price(bundle_price, components, template):
    if not components:
        raise ApiError(
            "ERR_COMPONENT_SUM_MISMATCH",
            "rate_components must not be empty.",
        )
    for key, value in components.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'rate_components' values must be integers.")
    if sum(components.values()) != bundle_price:
        raise ApiError(
            "ERR_COMPONENT_SUM_MISMATCH",
            "rate_components values must sum exactly to the bundle price.",
        )
    implant = components.get("implant")
    if implant is not None and implant > template["implant_component_cap_cents"]:
        raise ApiError(
            "ERR_IMPLANT_CAP_EXCEEDED",
            "Implant component exceeds the template cap.",
        )


def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open window overlap; touching endpoints do not overlap."""
    return a_from < b_to and b_from < a_to


@bp.route("/coe/contracts", methods=["POST"])
@endpoint("ProgramAdmin")
def create_contract():
    data = body()
    employer_id = f_str(data, "employer_id")
    template_id = f_str(data, "template_id")
    effective_from = f_dt(data, "effective_from")
    effective_to = f_dt(data, "effective_to")
    bundle_price = f_int(data, "bundle_price_cents", minimum=1)
    components = f_map(data, "rate_components")
    outlier_threshold = f_int(data, "outlier_threshold_cents", minimum=1)
    outlier_share = f_int(data, "outlier_share_pct", minimum=0, maximum=100)
    monthly_cap = f_int(data, "episode_cap_per_month", minimum=0)
    concurrent = f_int(data, "concurrent_capacity", minimum=0)
    travel = f_int(data, "travel_benefit_cents", minimum=0)
    lodging = f_int(data, "lodging_benefit_cents", minimum=0)
    companion = f_bool(data, "companion_allowed")
    if effective_to <= effective_from:
        raise ApiError(
            "ERR_INVALID_REQUEST", "effective_to must be strictly later than effective_from."
        )
    employer = db.employers.get(employer_id)
    if employer is None:
        raise ApiError("ERR_NOT_FOUND", "Employer does not exist.")
    template = db.templates.get(template_id)
    if template is None:
        raise ApiError("ERR_NOT_FOUND", "Bundle template does not exist.")
    _validate_price(bundle_price, components, template)
    if template["status"] == "RETIRED":
        raise ApiError("ERR_TEMPLATE_RETIRED", "Bundle template is RETIRED.")
    row = new_row(
        "contract",
        employer_id=employer_id,
        template_id=template_id,
        template_version=template["version"],
        effective_from=effective_from,
        effective_to=effective_to,
        bundle_price_cents=bundle_price,
        rate_components=components,
        outlier_threshold_cents=outlier_threshold,
        outlier_share_pct=outlier_share,
        episode_cap_per_month=monthly_cap,
        concurrent_capacity=concurrent,
        travel_benefit_cents=travel,
        lodging_benefit_cents=lodging,
        companion_allowed=companion,
        change_history=[],
        reprice_count=0,
        status="DRAFT",
        _created_bundle_price_cents=bundle_price,
        _created_rate_components=dict(components),
    )
    db.contracts[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.route("/coe/contracts", methods=["GET"])
@endpoint("ProgramAdmin")
def list_contracts():
    rows = list(db.contracts.values())
    employer_id = q_str("employer_id")
    if employer_id is not None:
        rows = [r for r in rows if r["employer_id"] == employer_id]
    template_id = q_str("template_id")
    if template_id is not None:
        rows = [r for r in rows if r["template_id"] == template_id]
    status = q_str("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.route("/coe/contracts/<contract_id>", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep", "ClaimsAdmin", "CareCoordinator")
def get_contract(contract_id):
    row = get_or_404("contracts", contract_id)
    scope_employer(row["employer_id"])
    return respond_object(dump(row))


@bp.route("/coe/contracts/<contract_id>/activate", methods=["POST"])
@endpoint("ProgramAdmin")
def activate_contract(contract_id):
    row = get_or_404("contracts", contract_id)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Contract is not DRAFT.")
    template = db.templates.get(row["template_id"])
    family = template["procedure_family"] if template else None
    for other in db.contracts.values():
        if (
            other["id"] != row["id"]
            and other["employer_id"] == row["employer_id"]
            and other["status"] == "ACTIVE"
        ):
            other_tpl = db.templates.get(other["template_id"])
            if other_tpl is None or other_tpl["procedure_family"] != family:
                continue
            if _windows_overlap(
                row["effective_from"], row["effective_to"],
                other["effective_from"], other["effective_to"],
            ):
                raise ApiError(
                    "ERR_CONTRACT_WINDOW_OVERLAP",
                    "An ACTIVE contract already covers this employer and family in an overlapping window.",
                )
    employer = db.employers.get(row["employer_id"])
    if employer is not None and employer["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYER_TERMINATED", "Employer is TERMINATED.")
    row["status"] = "ACTIVE"
    touch(row)
    return respond_object(dump(row))


@bp.route("/coe/contracts/<contract_id>/reprice", methods=["POST"])
@endpoint("ProgramAdmin")
def reprice_contract(contract_id):
    row = get_or_404("contracts", contract_id)
    data = body()
    expected_version = f_int(data, "expected_contract_version", minimum=0)
    new_price = f_int(data, "new_bundle_price_cents", minimum=1)
    new_components = f_map(data, "new_rate_components")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Contract is not ACTIVE.")
    if expected_version != row["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_contract_version is stale.")
    template = db.templates.get(row["template_id"])
    _validate_price(new_price, new_components, template)
    row["change_history"].append(
        {
            "new_bundle_price_cents": new_price,
            "new_rate_components": new_components,
            "effective_from_seq": db.next_amendment_day(),
            "amended_at": db.clock,
        }
    )
    row["reprice_count"] += 1
    row["bundle_price_cents"] = new_price
    row["rate_components"] = new_components
    touch(row)
    return respond_object(dump(row))


@bp.route("/coe/contracts/<contract_id>/terminate", methods=["POST"])
@endpoint("ProgramAdmin")
def terminate_contract_route(contract_id):
    row = get_or_404("contracts", contract_id)
    if row["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", "Contract is already TERMINATED.")
    terminate_contract(row)
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
@bp.route("/coe/patients", methods=["POST"])
@endpoint("CareCoordinator", "ProgramAdmin")
def create_patient():
    data = body()
    employer_id = f_str(data, "employer_id")
    full_name = f_str(data, "full_name")
    dob = f_str(data, "dob")
    member_id = f_str(data, "member_id")
    employer = db.employers.get(employer_id)
    if employer is None:
        raise ApiError("ERR_NOT_FOUND", "Employer does not exist.")
    row = new_row(
        "patient",
        employer_id=employer_id,
        full_name=full_name,
        dob=dob,
        member_id=member_id,
    )
    db.patients[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.route("/coe/patients", methods=["GET"])
@endpoint("ProgramAdmin", "CareCoordinator")
def list_patients():
    rows = list(db.patients.values())
    employer_id = q_str("employer_id")
    if employer_id is not None:
        rows = [r for r in rows if r["employer_id"] == employer_id]
    return paginate(sort_created(rows))


@bp.route("/coe/patients/<patient_id>", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep", "CareCoordinator", "PhysicianReviewer", "ClaimsAdmin")
def get_patient(patient_id):
    row = get_or_404("patients", patient_id)
    scope_employer(row["employer_id"])
    return respond_object(dump(row))
