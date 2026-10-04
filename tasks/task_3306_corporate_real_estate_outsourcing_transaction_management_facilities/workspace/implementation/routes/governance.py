"""Scorecards, discipline audits, KPI rows and audit review rounds."""
from datetime import timedelta

from core import auth, calc, domain
from core.db import DB, dec, new_common, serialize, touch
from core.errors import ApiError
from core.response import ok

from routes.registry import body, lookup, paginated_ok, req, route, validate

GOV_ONLY = ["GovernanceManager"]
GOV_ROLES = ["AccountExecutive", "GovernanceManager"]
SCORECARD_ROLES = ["AccountExecutive", "GovernanceManager", "FacilitiesManager"]
KPI_ROLES = ["AccountExecutive", "GovernanceManager", "FacilitiesManager"]

SERVICE_LINES = ("JANITORIAL", "SECURITY", "HVAC", "LANDSCAPING")
KPI_FAMILIES = ("SERVICE_LEVEL", "SAVINGS")
MEASUREMENT_UNITS = ("BPS", "CENTS")
MEASUREMENT_WINDOWS = ("QUARTERLY", "ANNUAL")
DISCIPLINES = ("TRANSACTION", "FACILITIES", "PROJECT")
PASS_TOKENS = ("PASS", "PASSED", "OK", "APPROVE", "APPROVED")
FAIL_TOKENS = ("FAIL", "FAILED", "REJECT", "REJECTED")


# ---------------------------------------------------------------------------
# Scorecards
# ---------------------------------------------------------------------------

@route("POST", "/api/scorecards", "create_scorecard", GOV_ONLY, 201)
def create_scorecard():
    data = validate(body(), [req("account_id"), req("service_line"),
                             req("quality_bps"), req("response_bps")])
    account = lookup("accounts", data.get("account_id"), "account")
    domain.lifecycle_gate(account, "create_scorecard")
    if data["service_line"] not in SERVICE_LINES:
        raise ApiError("ERR_INVALID_REQUEST", "service_line is not a facilities service line.")
    for field in ("quality_bps", "response_bps"):
        value = data[field]
        if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= 10000):
            raise ApiError("ERR_INVALID_REQUEST",
                           "%s must be an integer between 0 and 10000." % field)
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "service_line": data["service_line"],
        "quality_bps": data["quality_bps"],
        "response_bps": data["response_bps"],
        "composite_bps": 0,
        "adjustments_applied": 0,
        "scorecard_state": "DRAFT",
    })
    DB.insert("scorecards", obj)
    return ok(serialize(obj), 201)


@route("GET", "/api/scorecards", "list_scorecards", SCORECARD_ROLES)
def list_scorecards():
    rows = DB.ordered("scorecards")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    return paginated_ok(rows)


@route("GET", "/api/scorecards/<scorecard_id>", "get_scorecard", SCORECARD_ROLES)
def get_scorecard(scorecard_id):
    return ok(serialize(lookup("scorecards", scorecard_id, "scorecard")))


@route("POST", "/api/scorecards/<scorecard_id>/publish", "publish_scorecard", GOV_ONLY)
def publish_scorecard(scorecard_id):
    card = lookup("scorecards", scorecard_id, "scorecard")
    account = lookup("accounts", card.get("account_id"), "account")
    if card.get("scorecard_state") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT scorecard may be published.")
    if account.get("lifecycle_state") not in ("ACTIVE", "OFFBOARDING"):
        raise ApiError("ERR_INVALID_STATE",
                       "Publication requires an ACTIVE or OFFBOARDING account.")
    data = body()
    expected = data.get("expected_account_version")
    if expected is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_account_version is required on this operation.")
    if int(expected) != int(account.get("version") or 1):
        raise ApiError("ERR_STALE_VERSION",
                       "expected_account_version does not match the account version.")
    card["scorecard_state"] = "PUBLISHED"
    card["composite_bps"] = calc.weighted_scorecard_composite(card, account)
    touch(card)
    applied = 0
    for kpi in DB.children("service_level_kpis", account["id"]):
        if kpi.get("kpi_code") == "SLA_BPS":
            kpi["actual_value"] = card["composite_bps"]
            kpi["evaluation_state"] = "EVALUATED"
            domain.settle_kpi(kpi)
            touch(kpi)
            applied += 1
    card["adjustments_applied"] = applied
    domain.recompute_fee(account)
    domain.recompute_governance(account)
    touch(account)
    return ok(serialize(card))


# ---------------------------------------------------------------------------
# Discipline audits
# ---------------------------------------------------------------------------

@route("POST", "/api/discipline-audits", "create_discipline_audit", GOV_ONLY, 201)
def create_discipline_audit():
    data = validate(body(), [req("account_id"), req("discipline"), req("finding")])
    account = lookup("accounts", data.get("account_id"), "account")
    domain.lifecycle_gate(account, "create_discipline_audit")
    if data["discipline"] not in DISCIPLINES:
        raise ApiError("ERR_INVALID_REQUEST", "discipline is not a declared discipline.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "discipline": data["discipline"],
        "finding": data["finding"],
        "audit_state": "SCHEDULED",
        "remediation_required": False,
        "cooling_off_until": None,
    })
    DB.insert("discipline_audits", obj)
    return ok(serialize(obj), 201)


@route("GET", "/api/discipline-audits", "list_discipline_audits", GOV_ROLES)
def list_discipline_audits():
    rows = DB.ordered("discipline_audits")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    if args.get("discipline"):
        rows = [r for r in rows if r.get("discipline") == args.get("discipline")]
    return paginated_ok(rows)


@route("GET", "/api/discipline-audits/<audit_id>", "get_discipline_audit", GOV_ROLES)
def get_discipline_audit(audit_id):
    return ok(serialize(lookup("discipline_audits", audit_id, "discipline audit")))


@route("POST", "/api/discipline-audits/<audit_id>/start", "start_discipline_audit",
       GOV_ONLY)
def start_discipline_audit(audit_id):
    audit = lookup("discipline_audits", audit_id, "discipline audit")
    account = lookup("accounts", audit.get("account_id"), "account")
    if audit.get("audit_state") != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED audit may be started.")
    if account.get("lifecycle_state") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Starting an audit requires an ACTIVE account.")
    audit["audit_state"] = "IN_REVIEW"
    touch(audit)
    return ok(serialize(audit))


@route("POST", "/api/discipline-audits/<audit_id>/decide", "decide_discipline_audit",
       GOV_ONLY)
def decide_discipline_audit(audit_id):
    audit = lookup("discipline_audits", audit_id, "discipline audit")
    account = lookup("accounts", audit.get("account_id"), "account")
    data = body()
    outcome = data.get("outcome")
    if not isinstance(outcome, str):
        raise ApiError("ERR_INVALID_REQUEST", "outcome is required.")
    token = outcome.strip().upper()
    if token not in PASS_TOKENS and token not in FAIL_TOKENS:
        raise ApiError("ERR_INVALID_REQUEST", "outcome must be a pass or a failure.")
    if audit.get("audit_state") != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_REVIEW audit may be decided.")
    if token in PASS_TOKENS:
        audit["audit_state"] = "PASSED"
        audit["remediation_required"] = False
    else:
        audit["audit_state"] = "FAILED"
        audit["remediation_required"] = True
        audit["cooling_off_until"] = DB.clock + timedelta(hours=72)
    touch(audit)
    domain.recompute_governance(account)
    touch(account)
    return ok(serialize(audit))


def _next_round_no(audit_id):
    rounds = [r for r in DB.rows("audit_reviews")
              if r.get("discipline_audit_id") == audit_id]
    return len(rounds) + 1


@route("GET", "/api/discipline-audits/<audit_id>/reviews", "list_audit_reviews",
       GOV_ROLES)
def list_audit_reviews(audit_id):
    lookup("discipline_audits", audit_id, "discipline audit")
    rows = [r for r in DB.ordered("audit_reviews")
            if r.get("discipline_audit_id") == audit_id]
    return paginated_ok(rows)


@route("POST", "/api/discipline-audits/<audit_id>/reviews", "create_audit_review_for_audit",
       GOV_ONLY, 201)
def create_audit_review_for_audit(audit_id):
    audit = lookup("discipline_audits", audit_id, "discipline audit")
    account = lookup("accounts", audit.get("account_id"), "account")
    data = validate(body(), [req("reviewer_name"), req("round_notes")])
    domain.lifecycle_gate(account, "create_audit_review_for_audit")
    data = _audit_review_occ(data, account)
    obj = _new_audit_review(audit_id, data)
    touch(account)
    return ok(serialize(obj), 201)


def _audit_review_occ(data, account):
    expected = data.get("expected_account_version")
    if expected is not None and int(expected) != int(account.get("version") or 1):
        raise ApiError("ERR_STALE_VERSION",
                       "expected_account_version does not match the account version.")
    return data


def _new_audit_review(audit_id, data):
    obj = new_common()
    obj.update({
        "discipline_audit_id": audit_id,
        "reviewer_name": data["reviewer_name"],
        "round_notes": data["round_notes"],
        "review_round_no": _next_round_no(audit_id),
    })
    DB.insert("audit_reviews", obj)
    return obj


@route("POST", "/api/audit-reviews", "create_audit_review", GOV_ONLY, 201)
def create_audit_review():
    data = validate(body(), [req("discipline_audit_id"), req("reviewer_name"),
                             req("round_notes"), req("expected_account_version")])
    audit = lookup("discipline_audits", data.get("discipline_audit_id"), "discipline audit")
    account = lookup("accounts", audit.get("account_id"), "account")
    domain.lifecycle_gate(account, "create_audit_review_for_audit")
    data = _audit_review_occ(data, account)
    obj = _new_audit_review(audit["id"], data)
    touch(account)
    return ok(serialize(obj), 201)


@route("GET", "/api/audit-reviews/<review_id>", "get_audit_review", GOV_ROLES)
def get_audit_review(review_id):
    return ok(serialize(lookup("audit_reviews", review_id, "audit review")))


# ---------------------------------------------------------------------------
# Service level KPIs
# ---------------------------------------------------------------------------

@route("POST", "/api/service-level-kpis", "create_service_level_kpi", GOV_ONLY, 201)
def create_service_level_kpi():
    data = validate(body(), [req("account_id"), req("kpi_code"), req("kpi_family"),
                             req("measurement_unit"), req("measurement_window"),
                             req("target_value")])
    account = lookup("accounts", data.get("account_id"), "account")
    domain.lifecycle_gate(account, "create_service_level_kpi")
    if data["kpi_family"] not in KPI_FAMILIES:
        raise ApiError("ERR_INVALID_REQUEST", "kpi_family must be SERVICE_LEVEL or SAVINGS.")
    if data["measurement_unit"] not in MEASUREMENT_UNITS:
        raise ApiError("ERR_INVALID_REQUEST", "measurement_unit must be BPS or CENTS.")
    if data["measurement_window"] not in MEASUREMENT_WINDOWS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "measurement_window must be QUARTERLY or ANNUAL.")
    target = data["target_value"]
    if isinstance(target, bool) or not isinstance(target, int):
        raise ApiError("ERR_INVALID_REQUEST", "target_value must be an integer.")
    for existing in DB.children("service_level_kpis", account["id"]):
        if existing.get("kpi_code") == data["kpi_code"]:
            raise ApiError("ERR_INVALID_REQUEST", "kpi_code is unique per account.")
    obj = new_common()
    obj.update({
        "account_id": account["id"],
        "kpi_code": data["kpi_code"],
        "kpi_family": data["kpi_family"],
        "measurement_unit": data["measurement_unit"],
        "measurement_window": data["measurement_window"],
        "target_value": target,
        "actual_value": 0,
        "evaluation_state": "AWAITING_BASELINE",
        "escalation_status": "NONE",
        "gainshare_cents": 0,
        "penalty_cents": 0,
        "net_adjustment_cents": 0,
    })
    DB.insert("service_level_kpis", obj)
    return ok(serialize(obj), 201)


@route("GET", "/api/service-level-kpis", "list_service_level_kpis", KPI_ROLES)
def list_service_level_kpis():
    rows = DB.ordered("service_level_kpis")
    args = __import__("flask").request.args
    if args.get("account_id"):
        rows = [r for r in rows if r.get("account_id") == args.get("account_id")]
    if args.get("kpi_family"):
        rows = [r for r in rows if r.get("kpi_family") == args.get("kpi_family")]
    return paginated_ok(rows)


@route("GET", "/api/service-level-kpis/<kpi_id>", "get_service_level_kpi", KPI_ROLES)
def get_service_level_kpi(kpi_id):
    return ok(serialize(lookup("service_level_kpis", kpi_id, "service level KPI")))


@route("POST", "/api/service-level-kpis/<kpi_id>/evaluate", "evaluate_service_level_kpi",
       GOV_ONLY)
def evaluate_service_level_kpi(kpi_id):
    kpi = lookup("service_level_kpis", kpi_id, "service level KPI")
    account = lookup("accounts", kpi.get("account_id"), "account")
    data = body()
    actual = data.get("actual_value")
    if actual is None:
        raise ApiError("ERR_INVALID_REQUEST", "actual_value is required.")
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "actual_value must be a number.")
    kpi["actual_value"] = int(actual)
    kpi["evaluation_state"] = "EVALUATED"
    domain.settle_kpi(kpi)
    touch(kpi)
    domain.recompute_governance(account)
    touch(account)
    return ok(serialize(kpi))