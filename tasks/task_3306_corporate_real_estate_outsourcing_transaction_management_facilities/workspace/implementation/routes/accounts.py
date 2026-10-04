"""PortfolioAccount routes and assignment routes."""
from core import auth, calc, domain
from core.db import (DB, new_common, parse_dt, serialize, touch)
from core.errors import ApiError
from core.response import ok

from routes.registry import (bp, body, listed, lookup, opt, paginated_ok, req,
                             route, validate, vt)

ALL_ROLES = auth.ROLES
EXEC_ONLY = ["AccountExecutive"]

TIERS = ("BASIC", "COMPLETE", "ENTERPRISE")


def _normalize(obj):
    domain.recompute_fee(obj)
    domain.recompute_governance(obj)
    return obj


@route("POST", "/api/accounts", "create_account", EXEC_ONLY, 201)
def create_account():
    data = validate(body(), [req("account_name"), req("client_name"),
                             req("portfolio_sqft"), req("platform_tier")])
    name = str(data["account_name"]).strip()
    if not (1 <= len(name) <= 120):
        raise ApiError("ERR_INVALID_REQUEST",
                       "account_name must be between 1 and 120 characters.")
    for existing in DB.rows("accounts"):
        if existing.get("account_name") == name:
            raise ApiError("ERR_INVALID_REQUEST",
                           "account_name must be unique across accounts.")
    sqft = data["portfolio_sqft"]
    if isinstance(sqft, bool) or not isinstance(sqft, int) or sqft < 1:
        raise ApiError("ERR_INVALID_REQUEST", "portfolio_sqft must be at least 1.")
    tier = data["platform_tier"]
    if tier not in TIERS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "platform_tier must be one of BASIC, COMPLETE, ENTERPRISE.")
    obj = new_common()
    obj.update({
        "account_name": name,
        "client_name": data["client_name"],
        "portfolio_sqft": sqft,
        "platform_tier": tier,
        "client_data_rights": calc.client_data_rights_for(tier),
        "governance_posture": "NORMAL",
        "open_escalation_count": 0,
        "lifecycle_state": "DRAFT",
        "completion_pct_bps": 0,
        "annual_net_fee_cents": 0,
        "fee_ledger_credit_cents": 0,
        "broker_pool_allocated_cents": 0,
        "portfolio_leased_sqft": 0,
    })
    _normalize(obj)
    DB.insert("accounts", obj)
    return ok(serialize(obj), 201)


@route("GET", "/api/accounts", "list_accounts", ALL_ROLES)
def list_accounts():
    return paginated_ok([_normalize(o) for o in DB.ordered("accounts")])


@route("GET", "/api/accounts/<account_id>", "get_account", ALL_ROLES)
def get_account(account_id):
    obj = lookup("accounts", account_id, "account")
    _normalize(obj)
    return ok(serialize(obj))


@route("PUT", "/api/accounts/<account_id>", "update_account", EXEC_ONLY)
def update_account(account_id):
    obj = lookup("accounts", account_id, "account")
    data = validate(body(), [opt("account_name", "str"), opt("client_name", "str"),
                             opt("portfolio_sqft", "int"), opt("platform_tier", "enum")])
    if "account_name" in data and data["account_name"] is not None:
        name = str(data["account_name"]).strip()
        if not (1 <= len(name) <= 120):
            raise ApiError("ERR_INVALID_REQUEST",
                           "account_name must be between 1 and 120 characters.")
        for existing in DB.rows("accounts"):
            if existing["id"] != account_id and existing.get("account_name") == name:
                raise ApiError("ERR_INVALID_REQUEST",
                               "account_name must be unique across accounts.")
        obj["account_name"] = name
    if "client_name" in data and data["client_name"] is not None:
        obj["client_name"] = data["client_name"]
    if "portfolio_sqft" in data and data["portfolio_sqft"] is not None:
        sqft = data["portfolio_sqft"]
        if sqft < 1:
            raise ApiError("ERR_INVALID_REQUEST", "portfolio_sqft must be at least 1.")
        obj["portfolio_sqft"] = sqft
    if "platform_tier" in data and data["platform_tier"] is not None:
        tier = data["platform_tier"]
        if tier not in TIERS:
            raise ApiError("ERR_INVALID_REQUEST",
                           "platform_tier must be one of BASIC, COMPLETE, ENTERPRISE.")
        obj["platform_tier"] = tier
        obj["client_data_rights"] = calc.client_data_rights_for(tier)
    _normalize(obj)
    touch(obj)
    return ok(serialize(obj))


def _activation_audits(account):
    from core.db import new_common
    for discipline in ("TRANSACTION", "FACILITIES", "PROJECT"):
        audit = new_common()
        audit.update({
            "account_id": account["id"],
            "discipline": discipline,
            "finding": "",
            "audit_state": "SCHEDULED",
            "remediation_required": False,
            "cooling_off_until": None,
        })
        DB.insert("discipline_audits", audit)


@route("POST", "/api/accounts/<account_id>/activate", "activate_account", EXEC_ONLY)
def activate_account(account_id):
    obj = lookup("accounts", account_id, "account")
    if obj.get("lifecycle_state") != "DRAFT" or obj.get("platform_tier") is None:
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DRAFT account with a declared platform tier may be activated.")
    obj["lifecycle_state"] = "ACTIVE"
    _activation_audits(obj)
    _normalize(obj)
    touch(obj)
    return ok(serialize(obj))


@route("POST", "/api/accounts/<account_id>/transitions", "begin_transition",
       EXEC_ONLY, 201)
def begin_transition(account_id):
    obj = lookup("accounts", account_id, "account")
    domain.lifecycle_gate(obj, "begin_transition")
    if obj.get("lifecycle_state") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "Offboarding may only begin on an ACTIVE account.")
    if obj.get("governance_posture") != "NORMAL":
        raise ApiError("ERR_INVALID_STATE",
                       "Offboarding may only begin while governance posture is NORMAL.")
    domain.consent_gate(obj["id"])
    domain.cooling_off_gate(obj["id"])
    obj["lifecycle_state"] = "OFFBOARDING"
    obj["completion_pct_bps"] = calc.transition_completion_score(obj["id"])
    for _ in range(1):
        row = new_common()
        row.update({"account_id": obj["id"], "transition_state": "OPEN",
                    "completion_pct_bps": 0})
        DB.insert("account_transitions", row)
    touch(obj)
    return ok(serialize(obj), 201)


@route("POST", "/api/accounts/<account_id>/abort-transition", "abort_transition",
       EXEC_ONLY)
def abort_transition(account_id):
    obj = lookup("accounts", account_id, "account")
    if obj.get("lifecycle_state") != "OFFBOARDING":
        raise ApiError("ERR_NOT_TRANSITIONING",
                       "The account is not offboarding; the transition cannot be aborted.")
    obj["lifecycle_state"] = "ACTIVE"
    for task in DB.children("transition_tasks", obj["id"]):
        if task.get("task_state") not in ("DONE", "FAILED"):
            task["task_state"] = "FAILED"
            touch(task)
    obj["completion_pct_bps"] = calc.transition_completion_score(obj["id"])
    for row in DB.children("account_transitions", obj["id"]):
        if row.get("transition_state") == "OPEN":
            row["transition_state"] = "CLOSED"
            touch(row)
    _normalize(obj)
    touch(obj)
    return ok(serialize(obj))


def _dispose_sites_of_vendor(vendor):
    for site in DB.children("facility_sites", vendor["account_id"]):
        if site.get("vendor_id") == vendor["id"] and site.get("vacancy_state") == "OCCUPIED":
            site["vacancy_state"] = "DISPOSED"
            touch(site)
    return vendor


def _dispose_site_cascade(site):
    if site.get("vacancy_state") != "DISPOSED":
        return 0
    revoked = 0
    for lic in DB.children("data_licenses", site["account_id"]):
        if lic.get("data_scope") == "LINE_ITEM" and lic.get("license_state") == "GRANTED":
            lic["license_state"] = "REVOKED"
            touch(lic)
            revoked += 1
    return revoked


def run_termination_cascade(account):
    for vendor in DB.children("facilities_vendors", account["id"]):
        if vendor.get("vendor_state") == "ACTIVE":
            vendor["vendor_state"] = "TERMINATED"
            touch(vendor)
            _dispose_sites_of_vendor(vendor)
    for site in DB.children("facility_sites", account["id"]):
        _dispose_site_cascade(site)


@route("POST", "/api/accounts/<account_id>/close", "close_account", EXEC_ONLY)
def close_account(account_id):
    obj = lookup("accounts", account_id, "account")
    domain.lifecycle_gate(obj, "close_account")
    if obj.get("lifecycle_state") != "OFFBOARDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an OFFBOARDING account may be closed.")
    domain.consent_gate(obj["id"])
    domain.cooling_off_gate(obj["id"])
    if obj.get("completion_pct_bps") != 10000:
        raise ApiError("ERR_TRANSITION_INCOMPLETE",
                       "Account closure requires completion_pct_bps of exactly 10000.")
    for task in DB.children("transition_tasks", obj["id"]):
        if task.get("blocking") and task.get("task_state") != "DONE":
            raise ApiError("ERR_BLOCKING_TASK_OPEN",
                           "A blocking transition task is not yet DONE.")
    for task in DB.children("transition_tasks", obj["id"]):
        if task.get("task_type") == "FINAL_RECONCILIATION" and task.get("task_state") != "DONE":
            raise ApiError("ERR_INVALID_STATE",
                           "Every FINAL_RECONCILIATION task must be DONE before closure.")
    obj["lifecycle_state"] = "CLOSED_TERMINATED"
    run_termination_cascade(obj)
    for row in DB.children("account_transitions", obj["id"]):
        if row.get("transition_state") == "OPEN":
            row["transition_state"] = "CLOSED"
            touch(row)
    _normalize(obj)
    touch(obj)
    return ok(serialize(obj))


@route("POST", "/api/accounts/<account_id>/close-converted", "close_account_converted",
       EXEC_ONLY)
def close_account_converted(account_id):
    obj = lookup("accounts", account_id, "account")
    domain.lifecycle_gate(obj, "close_account_converted")
    if obj.get("lifecycle_state") != "OFFBOARDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an OFFBOARDING account may be closed.")
    domain.consent_gate(obj["id"])
    domain.cooling_off_gate(obj["id"])
    if obj.get("completion_pct_bps") != 10000:
        raise ApiError("ERR_TRANSITION_INCOMPLETE",
                       "Account closure requires completion_pct_bps of exactly 10000.")
    for task in DB.children("transition_tasks", obj["id"]):
        if task.get("blocking") and task.get("task_state") != "DONE":
            raise ApiError("ERR_BLOCKING_TASK_OPEN",
                           "A blocking transition task is not yet DONE.")
    if obj.get("governance_posture") == "RESTRICTED":
        raise ApiError("ERR_INVALID_STATE",
                       "A RESTRICTED account cannot be closed by conversion.")
    obj["lifecycle_state"] = "CLOSED_CONVERTED"
    for lic in DB.children("data_licenses", obj["id"]):
        if lic.get("license_state") == "GRANTED":
            lic["license_state"] = "REVOKED"
            touch(lic)
    for row in DB.children("account_transitions", obj["id"]):
        if row.get("transition_state") == "OPEN":
            row["transition_state"] = "CLOSED"
            touch(row)
    _normalize(obj)
    touch(obj)
    return ok(serialize(obj))


# ---------------------------------------------------------------------------
# Account-scoped child listings
# ---------------------------------------------------------------------------

def _child_list(kind):
    def handler(account_id):
        lookup("accounts", account_id, "account")
        return paginated_ok([o for o in DB.ordered(kind) if o.get("account_id") == account_id])
    return handler


_CHILD_COLLECTIONS = [
    ("leases", "account_leases"),
    ("commission_records", "account_commission_records"),
    ("service_level_kpis", "account_service_level_kpis"),
    ("facilities_vendors", "account_facilities_vendors"),
    ("facility_sites", "account_facility_sites"),
    ("scorecards", "account_scorecards"),
    ("discipline_audits", "account_discipline_audits"),
    ("data_licenses", "account_data_licenses"),
    ("transition_tasks", "account_transition_tasks"),
    ("fee_accruals", "account_fee_accruals"),
    ("consolidation_projects", "account_consolidation_projects"),
]

for _kind, _name in _CHILD_COLLECTIONS:
    route("GET", "/api/accounts/<account_id>/" + _kind.replace("_", "-"),
          _name, ALL_ROLES)(_child_list(_kind))


@route("GET", "/api/accounts/<account_id>/audit-reviews", "account_audit_reviews",
       ["AccountExecutive", "GovernanceManager"])
def account_audit_reviews(account_id):
    lookup("accounts", account_id, "account")
    audit_ids = {a["id"] for a in DB.children("discipline_audits", account_id)}
    rows = [r for r in DB.ordered("audit_reviews") if r.get("discipline_audit_id") in audit_ids]
    return paginated_ok(rows)


# ---------------------------------------------------------------------------
# Account assignments
# ---------------------------------------------------------------------------

ASSIGNMENT_ROLES = ("ACCOUNT_EXECUTIVE", "TRANSACTION_MANAGER", "FACILITIES_MANAGER",
                    "OCCUPANCY_PLANNER", "GOVERNANCE_MANAGER", "DATA_STEWARD",
                    "TRANSITION_MANAGER", "APPROVAL_AUTHORITY")
APPROVAL_LEVELS = ("MANAGER", "DIRECTOR", "ACCOUNT_EXECUTIVE")


def _new_assignment(account_id, data):
    name = data.get("assignee_name")
    if not isinstance(name, str) or not name.strip():
        raise ApiError("ERR_INVALID_REQUEST", "assignee_name is required.")
    role = data.get("assignment_role")
    if role not in ASSIGNMENT_ROLES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "assignment_role must be one of %s." % ", ".join(ASSIGNMENT_ROLES))
    level = data.get("approval_level", "MANAGER")
    if level is None:
        level = "MANAGER"
    if level not in APPROVAL_LEVELS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "approval_level must be one of MANAGER, DIRECTOR, ACCOUNT_EXECUTIVE.")
    obj = new_common()
    obj.update({"account_id": account_id, "assignee_name": name,
                "assignment_role": role, "approval_level": level})
    DB.insert("account_assignments", obj)
    return obj


@route("POST", "/api/accounts/<account_id>/assignments",
       "create_account_assignment_for_account", ["AccountExecutive"], 201)
def create_account_assignment_for_account(account_id):
    lookup("accounts", account_id, "account")
    obj = _new_assignment(account_id, body())
    return ok(serialize(obj), 201)


@route("GET", "/api/accounts/<account_id>/assignments", "list_account_assignments",
       ALL_ROLES)
def list_account_assignments(account_id):
    lookup("accounts", account_id, "account")
    return paginated_ok(DB.children("account_assignments", account_id))


@route("POST", "/api/account-assignments", "create_account_assignment_flat",
       ["AccountExecutive"], 201)
def create_account_assignment_flat():
    data = body()
    account_id = data.get("account_id")
    lookup("accounts", account_id, "account")
    obj = _new_assignment(account_id, data)
    return ok(serialize(obj), 201)