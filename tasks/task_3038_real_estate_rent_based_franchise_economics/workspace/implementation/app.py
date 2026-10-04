"""Real Estate Rent Franchise API -- Flask application.

Mounts all endpoints under /franchise-system per SCAFFOLD 1.5 / PRD 4.
Validation cascade per PRD 2.8:
  1. auth headers          -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  2. role permitted        -> ERR_INSUFFICIENT_PERMISSIONS (403)
  3. path ids resolve      -> ERR_RESOURCE_NOT_FOUND (404, left to right)
  4. body FK ids resolve   -> ERR_RESOURCE_NOT_FOUND (404)
  5. state preconditions   -> ERR_INVALID_STATE or specific state error (409)
  6. operator ownership    -> ERR_NOT_RESOURCE_OWNER (403)
  7+. business rules       -> specific error ids
  last: OCC version match  -> ERR_STALE_VERSION (412)
"""

import os

from flask import Flask, request, Response

import calculations as calc
import store as st
from errors import *  # noqa: F401,F403 - the error id constants
from errors import ApiError
from middleware import require_roles
from response import error as err_response
from response import success

app = Flask(__name__)
app.url_map.strict_slashes = False

ADMIN = ("FranchisorAdmin",)
FINANCE = ("FranchiseFinance",)
OPERATOR = ("Operator",)
COOP = ("CoopManager",)
ALL = ("FranchisorAdmin", "FranchiseFinance", "Operator", "CoopManager")

NON_TERMINAL_AGREEMENT_STATES = ("DRAFT", "FEE_PENDING", "ACTIVE")
BLOCKING_SUBLEASE_STATES = ("PENDING", "ACTIVE", "DEFAULTED", "CURED")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(exc):
    return err_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return err_response(ERR_RESOURCE_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(exc):
    return err_response(ERR_RESOURCE_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(Exception)
def handle_exception(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    return err_response("ERR_INTERNAL", str(exc), 500)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

@app.before_request
def _temporal_sweep():
    if request.path.startswith("/franchise-system"):
        st.temporal_sweep()


def body():
    """Parsed JSON body (empty dict when absent or not JSON)."""
    return request.get_json(silent=True) or {}


def not_found(what="resource"):
    raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, f"{what} not found")


def get_or_404(kind, entity_id, what="resource"):
    ent = st.find(kind, entity_id)
    if ent is None:
        not_found(what)
    return ent


def invalid_state(message="Resource is not in a valid state for this operation"):
    raise ApiError(ERR_INVALID_STATE, 409, message)


def _bad_request(message):
    raise ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400, message)


def require_int(payload, field, minimum=None, allow_zero=True):
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad_request(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        _bad_request(f"{field} must be >= {minimum}")
    if not allow_zero and value == 0:
        _bad_request(f"{field} must be non-zero")
    return value


def require_str(payload, field):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        _bad_request(f"{field} must be a non-empty string")
    return value


def require_number(payload, field):
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad_request(f"{field} must be a number")
    return value


def require_fraction(payload, field, allow_zero=False):
    """Rate strictly between 0 and 1 (or >= 0 and < 1 when allow_zero)."""
    value = st.dec(require_number(payload, field))
    if allow_zero:
        if value < 0 or value >= 1:
            _bad_request(f"{field} must satisfy 0 <= {field} < 1")
    else:
        if value <= 0 or value >= 1:
            _bad_request(f"{field} must satisfy 0 < {field} < 1")
    return value


def require_date(payload, field):
    value = require_str(payload, field)
    try:
        return st.parse_date(value)
    except ValueError:
        _bad_request(f"{field} must be an ISO date (YYYY-MM-DD)")


def paginate(items, response_items):
    """Apply limit/offset pagination per PRD 2.3; sort by creation asc."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        _bad_request("limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        _bad_request("offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    window = ordered[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success(
        [st.public(e) for e in window],
        response_type="array",
        status_code=200,
        meta_extra=meta,
    )


def filter_by(items, **criteria):
    """Filter entities by equality on given fields; None means skip."""
    out = []
    for ent in items:
        ok = True
        for key, wanted in criteria.items():
            if wanted is None:
                continue
            if ent.get(key) != wanted:
                ok = False
                break
        if ok:
            out.append(ent)
    return out


def operator_of_store(store):
    return st.find("operators", store["operator_id"])


def active_agreement_for_store(store_id):
    for ag in st.DB["agreements"]:
        if ag["store_id"] == store_id and ag["status"] == "ACTIVE":
            return ag
    return None


def active_sublease_for_store(store_id):
    for sub in st.DB["subleases"]:
        if sub["store_id"] == store_id and sub["status"] == "ACTIVE":
            return sub
    return None


def recompute_and_touch_operator(operator):
    """Recompute aggregates; bump version only when a value changed."""
    before = (
        operator["stores_operated_count"],
        operator["delinquency_balance_cents"],
    )
    st.recompute_operator_aggregates(operator)
    after = (
        operator["stores_operated_count"],
        operator["delinquency_balance_cents"],
    )
    if before != after:
        st.touch(operator)


# ---------------------------------------------------------------------------
# Repossession unwind cascade (PRD 3.8)
# ---------------------------------------------------------------------------

def cascade_repossession(store):
    """Full unwind when a store completes repossession.

    Each entity touched gets its own updated_at refresh and version +1.
    """
    store_id = store["id"]

    agreement = active_agreement_for_store(store_id)
    if agreement is not None:
        agreement["status"] = "TERMINATED"
        st.touch(agreement)

    for charge in st.DB["rent_charges"]:
        if charge["store_id"] == store_id and charge["status"] == "OPEN":
            charge["status"] = "WAIVED"
            st.touch(charge)

    for fa in st.DB["fund_assessments"]:
        if fa["store_id"] == store_id and fa["status"] == "OPEN":
            fa["status"] = "WAIVED"
            st.touch(fa)

    for ca in st.DB["coop_assessments"]:
        if ca["store_id"] == store_id and ca["status"] == "ASSESSED":
            ca["status"] = "WAIVED"
            st.touch(ca)

    for ob in st.DB["reinvestment_obligations"]:
        if ob["store_id"] == store_id and ob["status"] in ("PENDING", "SUBMITTED"):
            ob["status"] = "BREACHED"
            st.touch(ob)

    operator = operator_of_store(store)
    if operator is not None and operator["status"] in ("APPROVED", "SUSPENDED"):
        operator["status"] = "TERMINATED"
        st.recompute_operator_aggregates(operator)
        st.touch(operator)


# ===========================================================================
# Clock (test-driving capability, PRD 2.5)
# ===========================================================================

@app.route("/franchise-system/_clock/set_current_utc", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def set_clock():
    payload = body()
    current_utc = payload.get("current_utc")
    if not isinstance(current_utc, str) or not current_utc.strip():
        _bad_request("current_utc is required")
    try:
        st.set_clock(current_utc)
    except ValueError:
        _bad_request("current_utc must be an ISO 8601 instant")
    return success({}, response_type="object", status_code=200)


# ===========================================================================
# Sites (PRD 3.1)
# ===========================================================================

@app.route("/franchise-system/sites", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def create_site():
    payload = body()
    site_code = require_str(payload, "site_code")
    address = require_str(payload, "address")
    acquisition_type = require_str(payload, "acquisition_type")
    if acquisition_type not in ("FEE_SIMPLE", "GROUND_LEASE"):
        _bad_request("acquisition_type must be FEE_SIMPLE or GROUND_LEASE")
    expiry = payload.get("ground_lease_expiry")
    if acquisition_type == "GROUND_LEASE":
        if not isinstance(expiry, str) or not expiry.strip():
            _bad_request("ground_lease_expiry is required for GROUND_LEASE sites")
        try:
            st._parse_dt(expiry)
        except ValueError:
            _bad_request("ground_lease_expiry must be an ISO 8601 instant")
    else:
        if expiry is not None:
            _bad_request("ground_lease_expiry is forbidden for FEE_SIMPLE sites")
        expiry = None
    site = st.make_entity(
        "sites",
        {
            "site_code": site_code,
            "address": address,
            "acquisition_type": acquisition_type,
            "ground_lease_expiry": expiry,
            "holding_status": "HELD",
        },
    )
    return success(st.public(site), status_code=201)


@app.route("/franchise-system/sites", methods=["GET"], strict_slashes=False)
@require_roles(*ALL)
def list_sites():
    items = filter_by(
        st.DB["sites"], holding_status=request.args.get("holding_status")
    )
    return paginate(items, None)


@app.route("/franchise-system/sites/<siteId>", methods=["GET"], strict_slashes=False)
@require_roles(*ALL)
def get_site(siteId):
    return success(st.public(get_or_404("sites", siteId, "site")))


@app.route("/franchise-system/sites/<siteId>/divest", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def divest_site(siteId):
    site = get_or_404("sites", siteId, "site")
    if site["holding_status"] != "COMMITTED":
        invalid_state("Site must be COMMITTED to divest")
    stores = [s for s in st.DB["stores"] if s["site_id"] == site["id"]]
    if not stores or stores[0]["status"] != "REPOSSESSED":
        raise ApiError(
            ERR_SITE_STORE_NOT_REPOSSESSED,
            409,
            "Divest requires the site's store to be REPOSSESSED",
        )
    site["holding_status"] = "DIVESTED"
    st.touch(site)
    return success(st.public(site))


@app.route("/franchise-system/sites/<siteId>/stores", methods=["GET"], strict_slashes=False)
@require_roles(*ALL)
def list_site_stores(siteId):
    get_or_404("sites", siteId, "site")
    items = [s for s in st.DB["stores"] if s["site_id"] == siteId]
    return paginate(items, None)


# ===========================================================================
# Operators (PRD 3.2)
# ===========================================================================

@app.route("/franchise-system/operators", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def create_operator():
    payload = body()
    legal_name = require_str(payload, "legal_name")
    net_worth = require_int(payload, "fy_net_worth_cents", minimum=0)
    op_income = require_int(payload, "fy_operating_income_cents")
    operator = st.make_entity(
        "operators",
        {
            "legal_name": legal_name,
            "status": "CANDIDATE",
            "fy_net_worth_cents": net_worth,
            "fy_operating_income_cents": op_income,
            "capacity_score": None,
            "capacity_grade": None,
            "max_stores": 0,
            "stores_operated_count": 0,
            "delinquency_balance_cents": 0,
            "escrow_balance_cents": 0,
        },
    )
    return success(st.public(operator), status_code=201)


@app.route("/franchise-system/operators", methods=["GET"], strict_slashes=False)
@require_roles(*ALL)
def list_operators():
    items = filter_by(st.DB["operators"], status=request.args.get("status"))
    return paginate(items, None)


@app.route("/franchise-system/operators/<operatorId>", methods=["GET"], strict_slashes=False)
@require_roles(*ALL)
def get_operator(operatorId):
    return success(st.public(get_or_404("operators", operatorId, "operator")))


@app.route("/franchise-system/operators/<operatorId>/approve", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def approve_operator(operatorId):
    operator = get_or_404("operators", operatorId, "operator")
    if operator["status"] != "CANDIDATE":
        invalid_state("Operator must be CANDIDATE to approve")
    qualifying = any(
        r["operator_id"] == operator["id"]
        and r["status"] == "SUBMITTED"
        and r["grade"] in ("STRONG", "ADEQUATE")
        for r in st.DB["capacity_reviews"]
    )
    if not qualifying:
        raise ApiError(
            ERR_CAPACITY_REVIEW_REQUIRED,
            409,
            "Operator approval requires a SUBMITTED capacity review graded STRONG or ADEQUATE",
        )
    operator["status"] = "APPROVED"
    operator["max_stores"] = calc.max_stores_for_grade(operator["capacity_grade"])
    st.touch(operator)
    return success(st.public(operator))


@app.route("/franchise-system/operators/<operatorId>/suspend", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def suspend_operator(operatorId):
    operator = get_or_404("operators", operatorId, "operator")
    if operator["status"] != "APPROVED":
        invalid_state("Operator must be APPROVED to suspend")
    operator["status"] = "SUSPENDED"
    st.touch(operator)
    return success(st.public(operator))


@app.route("/franchise-system/operators/<operatorId>/reinstate", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def reinstate_operator(operatorId):
    operator = get_or_404("operators", operatorId, "operator")
    if operator["status"] != "SUSPENDED":
        invalid_state("Operator must be SUSPENDED to reinstate")
    if operator["capacity_grade"] == "FAILING":
        raise ApiError(
            ERR_CAPACITY_GRADE_FAILING,
            409,
            "Reinstatement blocked while capacity_grade is FAILING",
        )
    st.recompute_operator_aggregates(operator)
    if operator["delinquency_balance_cents"] != 0:
        raise ApiError(
            ERR_OUTSTANDING_DELINQUENCY,
            409,
            "Reinstatement blocked while delinquency_balance_cents > 0",
        )
    operator["status"] = "APPROVED"
    st.touch(operator)
    return success(st.public(operator))


@app.route("/franchise-system/operators/<operatorId>/fiscal-snapshot", methods=["PUT"], strict_slashes=False)
@require_roles(*FINANCE)
def fiscal_snapshot(operatorId):
    operator = get_or_404("operators", operatorId, "operator")
    payload = body()
    net_worth = require_int(payload, "fy_net_worth_cents", minimum=0)
    op_income = require_int(payload, "fy_operating_income_cents")
    operator["fy_net_worth_cents"] = net_worth
    operator["fy_operating_income_cents"] = op_income
    st.touch(operator)
    return success(st.public(operator))


@app.route("/franchise-system/operators/<operatorId>/escrow-deposits", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def escrow_deposit(operatorId):
    operator = get_or_404("operators", operatorId, "operator")
    payload = body()
    amount = require_int(payload, "amount_cents", minimum=1)
    operator["escrow_balance_cents"] += amount
    st.touch(operator)
    return success(st.public(operator))


# ===========================================================================
# Capacity reviews (PRD 3.2)
# ===========================================================================

@app.route("/franchise-system/capacity-reviews", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def create_capacity_review():
    payload = body()
    operator_id = payload.get("operator_id")
    operator = st.find("operators", operator_id)
    if operator is None:
        not_found("operator")
    review_period = require_str(payload, "review_period")
    if not st.is_year(review_period):
        _bad_request("review_period must be a fiscal year in YYYY format")
    review = st.make_entity(
        "capacity_reviews",
        {
            "operator_id": operator["id"],
            "review_period": review_period,
            "active_defaults_count": None,
            "pending_reinvestment_count": None,
            "composite_score": None,
            "grade": None,
            "status": "DRAFT",
        },
    )
    return success(st.public(review), status_code=201)


@app.route("/franchise-system/capacity-reviews", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance")
def list_capacity_reviews():
    items = filter_by(
        st.DB["capacity_reviews"], operator_id=request.args.get("operator_id")
    )
    return paginate(items, None)


@app.route("/franchise-system/capacity-reviews/<reviewId>", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance")
def get_capacity_review(reviewId):
    return success(st.public(get_or_404("capacity_reviews", reviewId, "capacity review")))


@app.route("/franchise-system/capacity-reviews/<reviewId>/submit", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def submit_capacity_review(reviewId):
    review = get_or_404("capacity_reviews", reviewId, "capacity review")
    if review["status"] != "DRAFT":
        invalid_state("Capacity review must be DRAFT to submit")
    operator = st.find("operators", review["operator_id"])
    if operator is None:
        not_found("operator")

    st.recompute_operator_aggregates(operator)
    op_store_ids = {s["id"] for s in st.DB["stores"] if s["operator_id"] == operator["id"]}

    active_defaults = sum(
        1
        for d in st.DB["default_events"]
        if d["store_id"] in op_store_ids and d["status"] == "DECLARED"
    )
    pending_reinv = sum(
        1
        for o in st.DB["reinvestment_obligations"]
        if o["store_id"] in op_store_ids and o["status"] in ("PENDING", "BREACHED")
    )

    score = calc.capacity_score_components(operator, active_defaults, pending_reinv)
    grade = calc.grade_for_score(score)

    review["active_defaults_count"] = active_defaults
    review["pending_reinvestment_count"] = pending_reinv
    review["composite_score"] = score
    review["grade"] = grade
    review["status"] = "SUBMITTED"
    st.touch(review)

    operator["capacity_score"] = score
    operator["capacity_grade"] = grade
    operator["max_stores"] = calc.max_stores_for_grade(grade)
    st.touch(operator)

    return success(st.public(review))


# ===========================================================================
# Stores (PRD 3.3)
# ===========================================================================

@app.route("/franchise-system/stores", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def create_store():
    payload = body()
    store_code = require_str(payload, "store_code")

    # Body FK resolution (priority 4)
    site_id = payload.get("site_id")
    site = st.find("sites", site_id)
    if site is None:
        not_found("site")
    operator_id = payload.get("operator_id")
    operator = st.find("operators", operator_id)
    if operator is None:
        not_found("operator")

    # Business: site must be HELD (priority 7, ERR_PORTFOLIO_LIMIT_REACHED per
    # SCAFFOLD 1.4 validation row)
    if site["holding_status"] != "HELD":
        raise ApiError(
            ERR_PORTFOLIO_LIMIT_REACHED,
            409,
            "Site is not HELD",
        )

    # Business: operator must be APPROVED and headroom > 0
    st.recompute_operator_aggregates(operator)
    if operator["status"] != "APPROVED":
        raise ApiError(
            ERR_PORTFOLIO_LIMIT_REACHED,
            409,
            "Operator is not APPROVED",
        )
    headroom = operator["max_stores"] - operator["stores_operated_count"]
    if headroom <= 0:
        raise ApiError(
            ERR_PORTFOLIO_LIMIT_REACHED,
            409,
            "Store creation would exceed max_stores for the operator's grade",
        )

    # OCC last (priority 13)
    expected = payload.get("expected_operator_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            _bad_request("expected_operator_version must be an integer")
        if expected != operator["version"]:
            raise ApiError(
                ERR_STALE_VERSION,
                412,
                "expected_operator_version does not match the operator's current version",
            )

    store = st.make_entity(
        "stores",
        {
            "store_code": store_code,
            "site_id": site["id"],
            "operator_id": operator["id"],
            "status": "SETUP",
            "opened_at": None,
        },
    )
    site["holding_status"] = "COMMITTED"
    st.touch(site)
    st.recompute_operator_aggregates(operator)
    st.touch(operator)
    return success(st.public(store), status_code=201)


@app.route("/franchise-system/stores", methods=["GET"], strict_slashes=False)
@require_roles(*ALL)
def list_stores():
    items = filter_by(
        st.DB["stores"],
        site_id=request.args.get("site_id"),
        operator_id=request.args.get("operator_id"),
        status=request.args.get("status"),
    )
    return paginate(items, None)


@app.route("/franchise-system/stores/<storeId>", methods=["GET"], strict_slashes=False)
@require_roles(*ALL)
def get_store(storeId):
    return success(st.public(get_or_404("stores", storeId, "store")))


@app.route("/franchise-system/stores/<storeId>/open", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def open_store(storeId):
    store = get_or_404("stores", storeId, "store")
    if store["status"] != "SETUP":
        invalid_state("Store must be SETUP to open")
    if active_agreement_for_store(store["id"]) is None:
        raise ApiError(
            ERR_AGREEMENT_NOT_ACTIVE,
            409,
            "Store open requires an ACTIVE FranchiseAgreement",
        )
    if active_sublease_for_store(store["id"]) is None:
        raise ApiError(
            ERR_SUBLEASE_NOT_ACTIVE,
            409,
            "Store open requires an ACTIVE Sublease",
        )
    operator = operator_of_store(store)
    if operator is None or operator["status"] != "APPROVED":
        raise ApiError(
            ERR_OPERATOR_NOT_APPROVED,
            409,
            "Store open requires an APPROVED operator",
        )
    store["status"] = "OPEN"
    store["opened_at"] = st.iso_ts()
    st.touch(store)
    recompute_and_touch_operator(operator)
    return success(st.public(store))


# ===========================================================================
# Franchise agreements (PRD 3.3)
# ===========================================================================

@app.route("/franchise-system/agreements", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def create_agreement():
    payload = body()

    # Body FK resolution (priority 4)
    store_id = payload.get("store_id")
    store = st.find("stores", store_id)
    if store is None:
        not_found("store")
    operator_id = payload.get("operator_id")
    operator = st.find("operators", operator_id)
    if operator is None:
        not_found("operator")
    renewal_of_id = payload.get("renewal_of_id")
    referenced = None
    if renewal_of_id is not None:
        referenced = st.find("agreements", renewal_of_id)
        if referenced is None:
            not_found("referenced agreement")

    initial_fee = require_int(payload, "initial_fee_cents", minimum=1)
    royalty_rate = require_fraction(payload, "royalty_rate")
    ad_fund_rate = require_fraction(payload, "ad_fund_rate")
    occupancy_pct = require_fraction(payload, "occupancy_allocation_pct")
    term_years = require_int(payload, "term_years", minimum=1)
    term_start = require_date(payload, "term_start_date")

    if operator["id"] != store["operator_id"]:
        _bad_request("operator_id must equal the store's operator")

    # Singularity: at most one non-terminal agreement per store (priority 10)
    for ag in st.DB["agreements"]:
        if ag["store_id"] == store["id"] and ag["status"] in NON_TERMINAL_AGREEMENT_STATES:
            raise ApiError(
                ERR_ACTIVE_AGREEMENT_EXISTS,
                409,
                "Store already has a DRAFT/FEE_PENDING/ACTIVE agreement",
            )

    agreement = st.make_entity(
        "agreements",
        {
            "store_id": store["id"],
            "operator_id": operator["id"],
            "initial_fee_cents": initial_fee,
            "royalty_rate": payload["royalty_rate"],
            "ad_fund_rate": payload["ad_fund_rate"],
            "occupancy_allocation_pct": payload["occupancy_allocation_pct"],
            "term_years": term_years,
            "term_start_date": term_start.isoformat(),
            "term_end_date": calc.compute_term_end_date(term_start, term_years),
            "renewal_of_id": renewal_of_id,
            "status": "DRAFT",
        },
    )
    return success(st.public(agreement), status_code=201)


@app.route("/franchise-system/agreements", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def list_agreements():
    items = filter_by(
        st.DB["agreements"],
        store_id=request.args.get("store_id"),
        operator_id=request.args.get("operator_id"),
        status=request.args.get("status"),
        renewal_of_id=request.args.get("renewal_of_id"),
    )
    return paginate(items, None)


@app.route("/franchise-system/agreements/<agreementId>", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def get_agreement(agreementId):
    return success(st.public(get_or_404("agreements", agreementId, "agreement")))


@app.route("/franchise-system/agreements/<agreementId>/submit", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def submit_agreement(agreementId):
    agreement = get_or_404("agreements", agreementId, "agreement")
    if agreement["status"] != "DRAFT":
        invalid_state("Agreement must be DRAFT to submit")

    # Renewal gates (priority 11, checked per SCAFFOLD 1.2 transition order:
    # reinvestment gate before the window gate)
    if agreement.get("renewal_of_id"):
        referenced = st.find("agreements", agreement["renewal_of_id"])
        if referenced is None or referenced["status"] != "ACTIVE":
            raise ApiError(
                ERR_RENEWAL_WINDOW_NOT_OPEN,
                409,
                "Referenced agreement must be ACTIVE",
            )
        satisfied = any(
            o["agreement_id"] == referenced["id"] and o["status"] == "SATISFIED"
            for o in st.DB["reinvestment_obligations"]
        )
        if not satisfied:
            raise ApiError(
                ERR_RENEWAL_REINVESTMENT_UNMET,
                409,
                "Renewal requires the referenced agreement's ReinvestmentObligation to be SATISFIED",
            )
        days_to_end = (st.parse_date(referenced["term_end_date"]) - st.clock_date()).days
        if not (0 <= days_to_end <= calc.RENEWAL_WINDOW_DAYS):
            raise ApiError(
                ERR_RENEWAL_WINDOW_NOT_OPEN,
                409,
                "Referenced agreement's term does not end within 180 days",
            )

    agreement["status"] = "FEE_PENDING"
    st.touch(agreement)
    return success(st.public(agreement))


@app.route("/franchise-system/agreements/<agreementId>/record-fee-payment", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def record_fee_payment(agreementId):
    agreement = get_or_404("agreements", agreementId, "agreement")
    if agreement["status"] != "FEE_PENDING":
        invalid_state("Agreement must be FEE_PENDING to record fee payment")
    payload = body()
    amount = require_int(payload, "amount_cents", minimum=0)
    if amount < agreement["initial_fee_cents"]:
        raise ApiError(
            ERR_INSUFFICIENT_FEE_PAYMENT,
            402,
            "record-fee-payment amount_cents < initial_fee_cents",
        )
    agreement["status"] = "ACTIVE"
    st.touch(agreement)
    if agreement.get("renewal_of_id"):
        referenced = st.find("agreements", agreement["renewal_of_id"])
        if referenced is not None and referenced["status"] == "ACTIVE":
            referenced["status"] = "SUPERSEDED"
            st.touch(referenced)
    return success(st.public(agreement))


# ===========================================================================
# Subleases (PRD 3.3)
# ===========================================================================

def _check_ground_lease_bound(store, end_date):
    site = st.find("sites", store["site_id"])
    if site is not None and site["acquisition_type"] == "GROUND_LEASE":
        expiry = st._parse_dt(site["ground_lease_expiry"]).date()
        if end_date > expiry:
            raise ApiError(
                ERR_SUBLEASE_BEYOND_GROUND_LEASE,
                422,
                "GROUND_LEASE site: sublease end_date exceeds the site's ground_lease_expiry",
            )


@app.route("/franchise-system/subleases", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def create_sublease():
    payload = body()

    # Body FK resolution (priority 4)
    store_id = payload.get("store_id")
    store = st.find("stores", store_id)
    if store is None:
        not_found("store")
    operator_id = payload.get("operator_id")
    operator = st.find("operators", operator_id)
    if operator is None:
        not_found("operator")

    base_rent = require_int(payload, "base_rent_cents", minimum=1)
    pct_rent_rate = require_fraction(payload, "pct_rent_rate")
    escalation_rate = require_number(payload, "escalation_rate")
    if st.dec(escalation_rate) < 0:
        _bad_request("escalation_rate must be >= 0")
    escalation_month = require_int(payload, "escalation_month", minimum=1)
    if escalation_month > 12:
        _bad_request("escalation_month must be in 1..12")
    escalation_day = require_int(payload, "escalation_day", minimum=1)
    if escalation_day > 28:
        _bad_request("escalation_day must be in 1..28")
    start_date = require_date(payload, "start_date")
    end_date = require_date(payload, "end_date")

    if operator["id"] != store["operator_id"]:
        _bad_request("operator_id must equal the store's operator")

    # Temporal bounds (priority 8)
    if end_date <= start_date:
        raise ApiError(
            ERR_SUBLEASE_BEYOND_GROUND_LEASE,
            422,
            "Sublease end_date must be after start_date",
        )
    _check_ground_lease_bound(store, end_date)

    # Singularity (priority 10)
    for sub in st.DB["subleases"]:
        if sub["store_id"] == store["id"] and sub["status"] in BLOCKING_SUBLEASE_STATES:
            raise ApiError(
                ERR_ACTIVE_SUBLEASE_EXISTS,
                409,
                "Store already has a PENDING/ACTIVE/DEFAULTED/CURED sublease",
            )

    sublease = st.make_entity(
        "subleases",
        {
            "store_id": store["id"],
            "operator_id": operator["id"],
            "base_rent_cents": base_rent,
            "pct_rent_rate": payload["pct_rent_rate"],
            "escalation_rate": payload["escalation_rate"],
            "escalation_month": escalation_month,
            "escalation_day": escalation_day,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "status": "PENDING",
            "active_default_id": None,
        },
    )
    return success(st.public(sublease), status_code=201)


@app.route("/franchise-system/subleases", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def list_subleases():
    items = filter_by(
        st.DB["subleases"],
        store_id=request.args.get("store_id"),
        operator_id=request.args.get("operator_id"),
        status=request.args.get("status"),
        active_default_id=request.args.get("active_default_id"),
    )
    return paginate(items, None)


@app.route("/franchise-system/subleases/<subleaseId>", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def get_sublease(subleaseId):
    return success(st.public(get_or_404("subleases", subleaseId, "sublease")))


@app.route("/franchise-system/subleases/<subleaseId>/activate", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def activate_sublease(subleaseId):
    sublease = get_or_404("subleases", subleaseId, "sublease")
    if sublease["status"] != "PENDING":
        invalid_state("Sublease must be PENDING to activate")
    store = st.find("stores", sublease["store_id"])
    if active_agreement_for_store(sublease["store_id"]) is None:
        raise ApiError(
            ERR_AGREEMENT_NOT_ACTIVE,
            409,
            "Sublease activation requires an ACTIVE FranchiseAgreement",
        )
    for other in st.DB["subleases"]:
        if (
            other["id"] != sublease["id"]
            and other["store_id"] == sublease["store_id"]
            and other["status"] in ("ACTIVE", "DEFAULTED", "CURED")
        ):
            raise ApiError(
                ERR_ACTIVE_SUBLEASE_EXISTS,
                409,
                "Store already has an ACTIVE/DEFAULTED/CURED sublease",
            )
    if store is not None:
        _check_ground_lease_bound(store, st.parse_date(sublease["end_date"]))
    sublease["status"] = "ACTIVE"
    st.touch(sublease)
    return success(st.public(sublease))


@app.route("/franchise-system/subleases/<subleaseId>/declare-default", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def declare_default(subleaseId):
    sublease = get_or_404("subleases", subleaseId, "sublease")
    if sublease["status"] != "ACTIVE":
        invalid_state("Sublease must be ACTIVE to declare default")
    payload = body()
    reason = require_str(payload, "reason")
    cure_fee = require_int(payload, "cure_fee_cents", minimum=0)

    store = st.find("stores", sublease["store_id"])
    shortfall = st.store_delinquency(sublease["store_id"])

    event = st.make_entity(
        "default_events",
        {
            "sublease_id": sublease["id"],
            "store_id": sublease["store_id"],
            "reason": reason,
            "cure_fee_cents": cure_fee,
            "shortfall_cents": shortfall,
            "status": "DECLARED",
        },
    )
    sublease["status"] = "DEFAULTED"
    sublease["active_default_id"] = event["id"]
    st.touch(sublease)

    if store is not None and store["status"] == "OPEN":
        store["status"] = "SUSPENDED"
        st.touch(store)
        operator = operator_of_store(store)
        if operator is not None:
            recompute_and_touch_operator(operator)
    return success(st.public(event), status_code=200)


@app.route("/franchise-system/subleases/<subleaseId>/reinstate", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def reinstate_sublease(subleaseId):
    sublease = get_or_404("subleases", subleaseId, "sublease")
    if sublease["status"] != "CURED":
        invalid_state("Sublease must be CURED to reinstate")
    sublease["status"] = "ACTIVE"
    st.touch(sublease)
    return success(st.public(sublease))


# ===========================================================================
# Default events (PRD 3.7, 3.8)
# ===========================================================================

@app.route("/franchise-system/default-events", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance")
def list_default_events():
    items = filter_by(
        st.DB["default_events"],
        sublease_id=request.args.get("sublease_id"),
        store_id=request.args.get("store_id"),
        status=request.args.get("status"),
    )
    return paginate(items, None)


@app.route("/franchise-system/default-events/<defaultId>", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance")
def get_default_event(defaultId):
    return success(st.public(get_or_404("default_events", defaultId, "default event")))


@app.route("/franchise-system/default-events/<defaultId>/cure", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def cure_default(defaultId):
    event = get_or_404("default_events", defaultId, "default event")
    if event["status"] != "DECLARED":
        raise ApiError(
            ERR_DEFAULT_NOT_DECLARED,
            409,
            "Cure requires the DefaultEvent in DECLARED",
        )
    sublease = st.find("subleases", event["sublease_id"])
    store = st.find("stores", event["store_id"])
    operator = operator_of_store(store) if store else None
    if operator is None:
        not_found("operator")

    # All-or-nothing escrow waterfall (PRD 3.7)
    required = event["shortfall_cents"] + event["cure_fee_cents"]
    if operator["escrow_balance_cents"] < required:
        raise ApiError(
            ERR_INSUFFICIENT_CURE_FUNDS,
            402,
            "Escrow balance < shortfall + cure fee at cure time",
        )
    operator["escrow_balance_cents"] -= required

    # Apply the shortfall to OPEN rent charges oldest first (created_at ASC)
    remaining = event["shortfall_cents"]
    open_charges = sorted(
        (
            c
            for c in st.DB["rent_charges"]
            if c["store_id"] == event["store_id"] and c["status"] == "OPEN"
        ),
        key=lambda c: (c["created_at"], c["_seq"]),
    )
    for charge in open_charges:
        if remaining <= 0:
            break
        outstanding = charge["selected_rent_cents"] - charge["amount_paid_cents"]
        applied = min(remaining, outstanding)
        charge["amount_paid_cents"] += applied
        remaining -= applied
        if charge["amount_paid_cents"] >= charge["selected_rent_cents"]:
            charge["status"] = "PAID"
        st.touch(charge)

    event["status"] = "CURED"
    st.touch(event)

    if sublease is not None:
        sublease["status"] = "CURED"
        sublease["active_default_id"] = None
        st.touch(sublease)

    if store is not None and store["status"] == "SUSPENDED":
        store["status"] = "OPEN"
        st.touch(store)

    recompute_and_touch_operator(operator)
    return success(st.public(event))


@app.route("/franchise-system/default-events/<defaultId>/repossess", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def repossess_default(defaultId):
    event = get_or_404("default_events", defaultId, "default event")
    if event["status"] != "DECLARED":
        raise ApiError(
            ERR_DEFAULT_NOT_DECLARED,
            409,
            "Repossess requires the DefaultEvent in DECLARED",
        )
    sublease = st.find("subleases", event["sublease_id"])
    store = st.find("stores", event["store_id"])

    event["status"] = "REPOSSESSED"
    st.touch(event)

    if sublease is not None:
        sublease["status"] = "REPOSSESSED"
        sublease["active_default_id"] = None
        st.touch(sublease)

    if store is not None and store["status"] == "SUSPENDED":
        store["status"] = "REPOSSESSED"
        st.touch(store)
        cascade_repossession(store)

    return success(st.public(event))


# ===========================================================================
# Sales reports (PRD 3.4)
# ===========================================================================

@app.route("/franchise-system/sales-reports", methods=["POST"], strict_slashes=False)
@require_roles(*OPERATOR)
def create_sales_report():
    payload = body()
    store_id = payload.get("store_id")
    store = st.find("stores", store_id)
    if store is None:
        not_found("store")
    period_month = require_str(payload, "period_month")
    if not st.is_period_month(period_month):
        _bad_request("period_month must be in YYYY-MM format")
    gross = require_int(payload, "gross_sales_cents", minimum=0)

    uid = request.headers.get("X-User-ID")
    if uid != store["operator_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            403,
            "Operator may only report sales for owned stores",
        )

    report = st.make_entity(
        "sales_reports",
        {
            "store_id": store["id"],
            "period_month": period_month,
            "gross_sales_cents": gross,
            "status": "DRAFT",
        },
    )
    return success(st.public(report), status_code=201)


@app.route("/franchise-system/sales-reports", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def list_sales_reports():
    items = filter_by(
        st.DB["sales_reports"],
        store_id=request.args.get("store_id"),
        status=request.args.get("status"),
        period_month=request.args.get("period_month"),
    )
    return paginate(items, None)


@app.route("/franchise-system/sales-reports/<reportId>", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def get_sales_report(reportId):
    return success(st.public(get_or_404("sales_reports", reportId, "sales report")))


@app.route("/franchise-system/sales-reports/<reportId>/submit", methods=["POST"], strict_slashes=False)
@require_roles(*OPERATOR)
def submit_sales_report(reportId):
    report = get_or_404("sales_reports", reportId, "sales report")
    if report["status"] != "DRAFT":
        invalid_state("Sales report must be DRAFT to submit")
    store = st.find("stores", report["store_id"])
    if store is None:
        not_found("store")
    uid = request.headers.get("X-User-ID")
    if uid != store["operator_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            403,
            "Operator may only submit reports for owned stores",
        )
    if store["status"] != "OPEN":
        raise ApiError(
            ERR_STORE_NOT_OPEN,
            409,
            "Sales report submission requires the store OPEN",
        )
    report["status"] = "SUBMITTED"
    st.touch(report)
    return success(st.public(report))


# ===========================================================================
# Rent charges (PRD 3.5)
# ===========================================================================

@app.route("/franchise-system/rent-charges", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def create_rent_charge():
    payload = body()

    # Body FK resolution (priority 4)
    store_id = payload.get("store_id")
    store = st.find("stores", store_id)
    if store is None:
        not_found("store")
    sublease_id = payload.get("sublease_id")
    if sublease_id is not None:
        if st.find("subleases", sublease_id) is None:
            not_found("sublease")

    billing_period = require_str(payload, "billing_period")
    if not st.is_year(billing_period):
        _bad_request("billing_period must be a year in YYYY format")
    period_start = require_date(payload, "period_start")
    period_end = require_date(payload, "period_end")

    # The charge binds the sublease that is ACTIVE at billing time (PRD 3.5)
    sublease = active_sublease_for_store(store["id"])
    if sublease is None:
        raise ApiError(
            ERR_SUBLEASE_NOT_ACTIVE,
            409,
            "Rent charge requires an ACTIVE sublease",
        )

    # Period must lie entirely inside the sublease term (priority 9)
    sub_start = st.parse_date(sublease["start_date"])
    sub_end = st.parse_date(sublease["end_date"])
    if period_end < period_start or period_start < sub_start or period_end > sub_end:
        raise ApiError(
            ERR_CHARGE_PERIOD_OUT_OF_TERM,
            422,
            "RentCharge billing period falls outside the sublease term",
        )

    # OCC last (priority 13)
    expected = payload.get("expected_sublease_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            _bad_request("expected_sublease_version must be an integer")
        if expected != sublease["version"]:
            raise ApiError(
                ERR_STALE_VERSION,
                412,
                "expected_sublease_version does not match the sublease's current version",
            )

    count = calc.escalation_count(
        sublease["escalation_month"],
        sublease["escalation_day"],
        period_start,
        period_end,
    )
    effective_base = calc.effective_base_rent_cents(
        sublease["base_rent_cents"], sublease["escalation_rate"], count
    )

    annual_sales = 0
    for report in st.DB["sales_reports"]:
        if report["store_id"] != store["id"] or report["status"] != "LOCKED":
            continue
        month_start = st.parse_date(report["period_month"] + "-01")
        if period_start <= month_start <= period_end:
            annual_sales += report["gross_sales_cents"]

    percentage_rent = calc.percentage_rent_cents(annual_sales, sublease["pct_rent_rate"])
    selected = max(effective_base, percentage_rent)

    charge = st.make_entity(
        "rent_charges",
        {
            "store_id": store["id"],
            "sublease_id": sublease["id"],
            "billing_period": billing_period,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "escalation_count": count,
            "effective_base_rent_cents": effective_base,
            "percentage_rent_cents": percentage_rent,
            "annual_sales_cents": annual_sales,
            "selected_rent_cents": selected,
            "amount_paid_cents": 0,
            "status": "OPEN",
        },
    )
    # Side effect: increments the bound sublease's version (SCAFFOLD 1.5)
    st.touch(sublease)
    operator = operator_of_store(store)
    if operator is not None:
        recompute_and_touch_operator(operator)
    return success(st.public(charge), status_code=201)


@app.route("/franchise-system/rent-charges", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def list_rent_charges():
    items = filter_by(
        st.DB["rent_charges"],
        store_id=request.args.get("store_id"),
        sublease_id=request.args.get("sublease_id"),
        status=request.args.get("status"),
    )
    return paginate(items, None)


@app.route("/franchise-system/rent-charges/<chargeId>", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def get_rent_charge(chargeId):
    return success(st.public(get_or_404("rent_charges", chargeId, "rent charge")))


@app.route("/franchise-system/rent-charges/<chargeId>/pay", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def pay_rent_charge(chargeId):
    charge = get_or_404("rent_charges", chargeId, "rent charge")
    if charge["status"] != "OPEN":
        raise ApiError(
            ERR_CHARGE_NOT_OPEN,
            409,
            "Payment target charge is not OPEN",
        )
    payload = body()
    amount = require_int(payload, "amount_cents", minimum=1)
    charge["amount_paid_cents"] += amount
    if charge["amount_paid_cents"] >= charge["selected_rent_cents"]:
        charge["status"] = "PAID"
    st.touch(charge)
    store = st.find("stores", charge["store_id"])
    operator = operator_of_store(store) if store else None
    if operator is not None:
        recompute_and_touch_operator(operator)
    return success(st.public(charge))


# ===========================================================================
# Billing runs (PRD 3.4)
# ===========================================================================

@app.route("/franchise-system/billing-runs", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def create_billing_run():
    payload = body()
    store_id = payload.get("store_id")
    store = st.find("stores", store_id)
    if store is None:
        not_found("store")
    period_month = require_str(payload, "period_month")
    if not st.is_period_month(period_month):
        _bad_request("period_month must be in YYYY-MM format")

    report = None
    for r in st.DB["sales_reports"]:
        if (
            r["store_id"] == store["id"]
            and r["period_month"] == period_month
            and r["status"] == "SUBMITTED"
        ):
            report = r
            break
    if report is None:
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "No SUBMITTED sales report for this store and period_month",
        )

    agreement = active_agreement_for_store(store["id"])
    if agreement is None:
        raise ApiError(
            ERR_AGREEMENT_NOT_ACTIVE,
            409,
            "Billing run requires an ACTIVE FranchiseAgreement",
        )

    split = calc.monthly_royalty_ad_split(
        report["gross_sales_cents"],
        agreement["occupancy_allocation_pct"],
        agreement["royalty_rate"],
        agreement["ad_fund_rate"],
    )

    report["status"] = "LOCKED"
    st.touch(report)

    assessment = st.make_entity(
        "fund_assessments",
        {
            "store_id": store["id"],
            "agreement_id": agreement["id"],
            "period_month": period_month,
            "occupancy_share_cents": split["occupancy_share_cents"],
            "royalty_sales_cents": split["royalty_sales_cents"],
            "royalty_cents": split["royalty_cents"],
            "ad_fund_cents": split["ad_fund_cents"],
            "provisional_royalty_cents": 12 * split["royalty_cents"],
            "final_royalty_cents": None,
            "status": "OPEN",
        },
    )
    operator = operator_of_store(store)
    if operator is not None:
        recompute_and_touch_operator(operator)
    return success(st.public(assessment), status_code=201)


# ===========================================================================
# Fund assessments (PRD 3.4)
# ===========================================================================

@app.route("/franchise-system/fund-assessments", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def list_fund_assessments():
    items = filter_by(
        st.DB["fund_assessments"],
        store_id=request.args.get("store_id"),
        agreement_id=request.args.get("agreement_id"),
        status=request.args.get("status"),
    )
    return paginate(items, None)


@app.route("/franchise-system/fund-assessments/<assessmentId>", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def get_fund_assessment(assessmentId):
    return success(st.public(get_or_404("fund_assessments", assessmentId, "fund assessment")))


@app.route("/franchise-system/fund-assessments/<assessmentId>/pay", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def pay_fund_assessment(assessmentId):
    assessment = get_or_404("fund_assessments", assessmentId, "fund assessment")
    if assessment["status"] != "OPEN":
        raise ApiError(
            ERR_ASSESSMENT_NOT_OPEN,
            409,
            "Payment target assessment is not OPEN",
        )
    assessment["status"] = "PAID"
    st.touch(assessment)

    # Credit the national advertising fund by ad_fund_cents less the
    # per-credit admin fee (PRD 3.9)
    national_funds = [f for f in st.DB["advertising_funds"] if f["fund_type"] == "NATIONAL"]
    if national_funds:
        fund = national_funds[0]
        st.fund_credit(fund, assessment["ad_fund_cents"])
        st.touch(fund)

    store = st.find("stores", assessment["store_id"])
    operator = operator_of_store(store) if store else None
    if operator is not None:
        recompute_and_touch_operator(operator)
    return success(st.public(assessment))


# ===========================================================================
# Annual reconciliation (PRD 3.4)
# ===========================================================================

@app.route("/franchise-system/stores/<storeId>/annual-reconciliation", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def annual_reconciliation(storeId):
    store = get_or_404("stores", storeId, "store")
    payload = body()
    fiscal_year = require_str(payload, "fiscal_year")
    if not st.is_year(fiscal_year):
        _bad_request("fiscal_year must be a year in YYYY format")

    locked = [
        r
        for r in st.DB["sales_reports"]
        if r["store_id"] == store["id"]
        and r["status"] == "LOCKED"
        and r["period_month"].startswith(fiscal_year + "-")
    ]
    if not locked:
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "No LOCKED sales reports for this store and fiscal year",
        )

    agreement = active_agreement_for_store(store["id"])
    if agreement is None:
        raise ApiError(
            ERR_AGREEMENT_NOT_ACTIVE,
            409,
            "Annual reconciliation requires an ACTIVE FranchiseAgreement",
        )

    # final variant: rate applied to the year's actual summed
    # royalty-allocated sales (chronological replay)
    total_royalty_sales = 0
    for report in locked:
        occupancy_share = st.round_half_up_cents(
            st.dec(report["gross_sales_cents"]) * st.dec(agreement["occupancy_allocation_pct"])
        )
        total_royalty_sales += report["gross_sales_cents"] - occupancy_share
    final_royalty = st.round_half_up_cents(
        st.dec(total_royalty_sales) * st.dec(agreement["royalty_rate"])
    )

    year_assessments = [
        fa
        for fa in st.DB["fund_assessments"]
        if fa["store_id"] == store["id"] and fa["period_month"].startswith(fiscal_year + "-")
    ]
    last = None
    for fa in year_assessments:
        fa["final_royalty_cents"] = final_royalty
        st.touch(fa)
        last = fa

    data = st.public(last) if last is not None else {"final_royalty_cents": final_royalty}
    return success(data, status_code=200)


# ===========================================================================
# Reinvestment obligations (PRD 3.6)
# ===========================================================================

@app.route("/franchise-system/reinvestment-obligations", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def create_reinvestment_obligation():
    payload = body()
    store_id = payload.get("store_id")
    store = st.find("stores", store_id)
    if store is None:
        not_found("store")
    agreement_id = payload.get("agreement_id")
    agreement = st.find("agreements", agreement_id)
    if agreement is None:
        not_found("agreement")
    budget = require_int(payload, "required_budget_cents", minimum=1)
    deadline = require_date(payload, "deadline_date")

    obligation = st.make_entity(
        "reinvestment_obligations",
        {
            "store_id": store["id"],
            "agreement_id": agreement["id"],
            "required_budget_cents": budget,
            "deadline_date": deadline.isoformat(),
            "min_spend_cents": calc.min_spend_cents(budget),
            "verified_spend_cents": 0,
            "status": "PENDING",
        },
    )
    return success(st.public(obligation), status_code=201)


@app.route("/franchise-system/reinvestment-obligations", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def list_reinvestment_obligations():
    items = filter_by(
        st.DB["reinvestment_obligations"],
        store_id=request.args.get("store_id"),
        agreement_id=request.args.get("agreement_id"),
        status=request.args.get("status"),
    )
    return paginate(items, None)


@app.route("/franchise-system/reinvestment-obligations/<obligationId>", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "Operator")
def get_reinvestment_obligation(obligationId):
    return success(
        st.public(get_or_404("reinvestment_obligations", obligationId, "reinvestment obligation"))
    )


@app.route("/franchise-system/reinvestment-obligations/<obligationId>/submit-spend", methods=["POST"], strict_slashes=False)
@require_roles(*OPERATOR)
def submit_spend(obligationId):
    obligation = get_or_404("reinvestment_obligations", obligationId, "reinvestment obligation")
    if obligation["status"] != "PENDING":
        invalid_state("Reinvestment obligation must be PENDING to submit spend")
    store = st.find("stores", obligation["store_id"])
    if store is None:
        not_found("store")
    uid = request.headers.get("X-User-ID")
    if uid != store["operator_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            403,
            "Operator may only submit spend for owned stores",
        )
    if st.clock_date() > st.parse_date(obligation["deadline_date"]):
        raise ApiError(
            ERR_REINVESTMENT_DEADLINE_PASSED,
            409,
            "Spend submission after the obligation deadline_date",
        )
    payload = body()
    amount = require_int(payload, "amount_cents", minimum=1)
    obligation["verified_spend_cents"] += amount
    obligation["status"] = "SUBMITTED"
    st.touch(obligation)
    return success(st.public(obligation))


@app.route("/franchise-system/reinvestment-obligations/<obligationId>/verify-spend", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def verify_spend(obligationId):
    obligation = get_or_404("reinvestment_obligations", obligationId, "reinvestment obligation")
    if obligation["status"] != "SUBMITTED":
        invalid_state("Reinvestment obligation must be SUBMITTED to verify spend")
    if obligation["verified_spend_cents"] < obligation["min_spend_cents"]:
        raise ApiError(
            ERR_REINVESTMENT_UNDERFUNDED,
            409,
            "verify-spend with verified_spend_cents < min_spend_cents",
        )
    obligation["status"] = "SATISFIED"
    st.touch(obligation)
    return success(st.public(obligation))


@app.route("/franchise-system/reinvestment-obligations/<obligationId>/reject-spend", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def reject_spend(obligationId):
    obligation = get_or_404("reinvestment_obligations", obligationId, "reinvestment obligation")
    if obligation["status"] != "SUBMITTED":
        invalid_state("Reinvestment obligation must be SUBMITTED to reject spend")
    obligation["status"] = "BREACHED"
    st.touch(obligation)
    return success(st.public(obligation))


# ===========================================================================
# Advertising funds (PRD 3.9)
# ===========================================================================

@app.route("/franchise-system/advertising-funds", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def create_fund():
    payload = body()
    name = require_str(payload, "name")
    fund_type = require_str(payload, "fund_type")
    if fund_type not in ("NATIONAL", "LOCAL_COOP"):
        _bad_request("fund_type must be NATIONAL or LOCAL_COOP")
    admin_fee_rate = require_number(payload, "admin_fee_rate")
    if st.dec(admin_fee_rate) < 0:
        _bad_request("admin_fee_rate must be >= 0")
    region_code = payload.get("region_code")
    if fund_type == "NATIONAL":
        if region_code is not None:
            _bad_request("region_code must be null for NATIONAL funds")
        region_code = None
    else:
        if not isinstance(region_code, str) or not region_code.strip():
            _bad_request("region_code is required for LOCAL_COOP funds")
    fund = st.make_entity(
        "advertising_funds",
        {
            "name": name,
            "fund_type": fund_type,
            "admin_fee_rate": payload["admin_fee_rate"],
            "region_code": region_code,
            "balance_cents": 0,
            "governance_status": "ACTIVE",
        },
    )
    return success(st.public(fund), status_code=201)


@app.route("/franchise-system/advertising-funds", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "CoopManager")
def list_funds():
    items = filter_by(
        st.DB["advertising_funds"],
        fund_type=request.args.get("fund_type"),
        region_code=request.args.get("region_code"),
    )
    return paginate(items, None)


@app.route("/franchise-system/advertising-funds/<fundId>", methods=["GET"], strict_slashes=False)
@require_roles("FranchisorAdmin", "FranchiseFinance", "CoopManager")
def get_fund(fundId):
    return success(st.public(get_or_404("advertising_funds", fundId, "advertising fund")))


@app.route("/franchise-system/advertising-funds/<fundId>/freeze", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def freeze_fund(fundId):
    fund = get_or_404("advertising_funds", fundId, "advertising fund")
    if fund["governance_status"] != "ACTIVE":
        invalid_state("Fund must be ACTIVE to freeze")
    fund["governance_status"] = "FROZEN"
    st.touch(fund)
    return success(st.public(fund))


@app.route("/franchise-system/advertising-funds/<fundId>/unfreeze", methods=["POST"], strict_slashes=False)
@require_roles(*ADMIN)
def unfreeze_fund(fundId):
    fund = get_or_404("advertising_funds", fundId, "advertising fund")
    if fund["governance_status"] != "FROZEN":
        invalid_state("Fund must be FROZEN to unfreeze")
    fund["governance_status"] = "ACTIVE"
    st.touch(fund)
    return success(st.public(fund))


@app.route("/franchise-system/advertising-funds/<fundId>/disburse", methods=["POST"], strict_slashes=False)
@require_roles("FranchisorAdmin", "CoopManager")
def disburse_fund(fundId):
    fund = get_or_404("advertising_funds", fundId, "advertising fund")
    role = request.headers.get("X-User-Role")
    if role == "CoopManager" and fund["fund_type"] != "LOCAL_COOP":
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "CoopManager may disburse from LOCAL_COOP funds only",
        )
    if fund["governance_status"] != "ACTIVE":
        raise ApiError(
            ERR_FUND_FROZEN,
            409,
            "Disbursement while fund governance_status is FROZEN",
        )
    payload = body()
    amount = require_int(payload, "amount_cents", minimum=1)
    purpose = require_str(payload, "purpose")
    if amount > fund["balance_cents"]:
        raise ApiError(
            ERR_INSUFFICIENT_FUND_BALANCE,
            402,
            "Disbursement amount exceeds fund balance_cents",
        )
    st.fund_debit(fund, amount)
    st.touch(fund)
    return success(st.public(fund))


# ===========================================================================
# Co-op assessments (PRD 3.9)
# ===========================================================================

@app.route("/franchise-system/coop-assessments", methods=["POST"], strict_slashes=False)
@require_roles(*COOP)
def create_coop_assessment():
    payload = body()
    fund_id = payload.get("fund_id")
    fund = st.find("advertising_funds", fund_id)
    if fund is None:
        not_found("advertising fund")
    store_id = payload.get("store_id")
    store = st.find("stores", store_id)
    if store is None:
        not_found("store")
    amount = require_int(payload, "amount_cents", minimum=1)
    if fund["fund_type"] != "LOCAL_COOP":
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "CoopManager may assess into LOCAL_COOP funds only",
        )
    assessment = st.make_entity(
        "coop_assessments",
        {
            "fund_id": fund["id"],
            "store_id": store["id"],
            "amount_cents": amount,
            "status": "ASSESSED",
        },
    )
    return success(st.public(assessment), status_code=201)


@app.route("/franchise-system/coop-assessments", methods=["GET"], strict_slashes=False)
@require_roles(*ALL)
def list_coop_assessments():
    items = filter_by(
        st.DB["coop_assessments"],
        fund_id=request.args.get("fund_id"),
        store_id=request.args.get("store_id"),
        status=request.args.get("status"),
    )
    return paginate(items, None)


@app.route("/franchise-system/coop-assessments/<assessmentId>", methods=["GET"], strict_slashes=False)
@require_roles(*ALL)
def get_coop_assessment(assessmentId):
    return success(st.public(get_or_404("coop_assessments", assessmentId, "co-op assessment")))


@app.route("/franchise-system/coop-assessments/<assessmentId>/pay", methods=["POST"], strict_slashes=False)
@require_roles(*FINANCE)
def pay_coop_assessment(assessmentId):
    assessment = get_or_404("coop_assessments", assessmentId, "co-op assessment")
    if assessment["status"] != "ASSESSED":
        raise ApiError(
            ERR_ASSESSMENT_NOT_OPEN,
            409,
            "Payment target assessment is not ASSESSED",
        )
    assessment["status"] = "PAID"
    st.touch(assessment)
    fund = st.find("advertising_funds", assessment["fund_id"])
    if fund is not None:
        st.fund_credit(fund, assessment["amount_cents"])
        st.touch(fund)
    return success(st.public(assessment))


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
