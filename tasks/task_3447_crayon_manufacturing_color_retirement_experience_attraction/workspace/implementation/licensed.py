"""Licensed and co-branded lines: two-party approval workflow (PRD 3.6)."""
from calculations import compute_royalty_cents
from constants import (
    OPS_ROLES, ROLE_BRAND_MANAGER, ROLE_LICENSOR, ROYALTY_RATE_MAX,
)
from envelope import ok
from errors import ApiError
from store import STORE
from validation import (
    auth, body, get_or_404, new_entity, req_dt, req_enum, req_int, req_num,
    req_str, require_role, touch,
)

BRAND_ACTIONS = ("SUBMIT", "BRAND_APPROVE", "BRAND_REQUEST_REVISION",
                 "BRAND_REJECT", "REINSTATE")
LICENSOR_ACTIONS = ("LICENSOR_APPROVE", "LICENSOR_REQUEST_REVISION", "LICENSOR_REJECT")
LINE_ACTION_STATES = {
    "SUBMIT": ("DRAFT",),
    "LICENSOR_APPROVE": ("LICENSOR_REVIEW",),
    "LICENSOR_REQUEST_REVISION": ("LICENSOR_REVIEW",),
    "LICENSOR_REJECT": ("LICENSOR_REVIEW",),
    "BRAND_APPROVE": ("BRAND_REVIEW",),
    "BRAND_REQUEST_REVISION": ("BRAND_REVIEW",),
    "BRAND_REJECT": ("BRAND_REVIEW",),
    "REINSTATE": ("SUSPENDED",),
}


def serialize_line(line):
    return {
        "id": line["id"],
        "name": line["name"],
        "licensor_user_id": line["licensor_user_id"],
        "formula_id": line["formula_id"],
        "term_start": line["term_start"],
        "term_end": line["term_end"],
        "royalty_rate": line["royalty_rate"],
        "royalty_base": line["royalty_base"],
        "pinned_formula_version": line["pinned_formula_version"],
        "projected_royalty_cents": line["projected_royalty_cents"],
        "status": line["status"],
        "submitted_by_user_id": line["submitted_by_user_id"],
        "created_at": line["created_at"],
        "updated_at": line["updated_at"],
        "version": line["version"],
    }


def create_line():
    _, role = auth()
    require_role(role, {ROLE_BRAND_MANAGER})
    data = body()
    name = req_str(data, "name")
    licensor_user_id = req_str(data, "licensor_user_id")
    formula_id = req_str(data, "formula_id")
    start_raw, term_start = req_dt(data, "term_start")
    end_raw, term_end = req_dt(data, "term_end")
    royalty_rate = req_num(data, "royalty_rate")
    royalty_base = req_enum(data, "royalty_base", ("GROSS", "NET"))
    if not (royalty_rate > 0 and royalty_rate <= ROYALTY_RATE_MAX):
        raise ApiError("ERR_INVALID_REQUEST", "royalty_rate must be > 0 and <= 0.5")
    get_or_404(STORE.formulas, formula_id)
    if term_end <= term_start:
        raise ApiError("ERR_DATE_ORDER")
    line = new_entity({
        "name": name,
        "licensor_user_id": licensor_user_id,
        "formula_id": formula_id,
        "term_start": start_raw,
        "term_end": end_raw,
        "royalty_rate": royalty_rate,
        "royalty_base": royalty_base,
        "pinned_formula_version": None,
        "projected_royalty_cents": 0,
        "status": "DRAFT",
        "submitted_by_user_id": None,
    })
    STORE.lines[line["id"]] = line
    return ok(serialize_line(line), status=201)


def get_line(line_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    line = get_or_404(STORE.lines, line_id)
    # projected_royalty_cents is recomputed on every read (no version bump).
    line["projected_royalty_cents"] = compute_royalty_cents(line)
    return ok(serialize_line(line))


def _recall_touches_color(color_id):
    for case in STORE.recall_cases.values():
        if case["status"] in ("OPEN", "CONTAINED") \
                and color_id in case.get("_affected_color_ids", []):
            return True
    return False


def line_transition(line_id):
    user_id, role = auth()
    require_role(role, {ROLE_BRAND_MANAGER, ROLE_LICENSOR})
    data = body()
    action = req_enum(data, "action", BRAND_ACTIONS + LICENSOR_ACTIONS)
    expected_version = req_int(data, "expected_formula_version")
    line = get_or_404(STORE.lines, line_id)
    formula = STORE.formulas[line["formula_id"]]
    # Optimistic concurrency (stage 5): every transition carries the pin view.
    if expected_version != formula["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # Action-level authorization.
    if action in BRAND_ACTIONS and role != ROLE_BRAND_MANAGER:
        raise ApiError("ERR_UNAUTHORIZED")
    if action in LICENSOR_ACTIONS:
        if role != ROLE_LICENSOR:
            raise ApiError("ERR_UNAUTHORIZED")
        if user_id != line["licensor_user_id"]:
            raise ApiError("ERR_UNAUTHORIZED")
    # State gate (stage 6).
    if line["status"] not in LINE_ACTION_STATES[action]:
        raise ApiError("ERR_LICENSE_STATE")
    # Segregation of duties (stage 7): BRAND_APPROVE never by the submitter.
    if action == "BRAND_APPROVE" and user_id == line["submitted_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION")
    if action == "REINSTATE":
        # Recall gate (stage 7): no OPEN/CONTAINED case touching the color.
        if _recall_touches_color(formula["color_id"]):
            raise ApiError("ERR_RECALL_ACTIVE")
        # Pin freshness (stage 10).
        if formula["status"] != "APPROVED" \
                or line["pinned_formula_version"] != formula["version"]:
            raise ApiError("ERR_STALE_PIN")
    if action == "SUBMIT":
        line["status"] = "LICENSOR_REVIEW"
        line["submitted_by_user_id"] = user_id
        touch(line)
    elif action == "LICENSOR_APPROVE":
        line["status"] = "BRAND_REVIEW"
        touch(line)
    elif action == "LICENSOR_REQUEST_REVISION":
        line["status"] = "DRAFT"
        touch(line)
    elif action == "LICENSOR_REJECT":
        line["status"] = "REJECTED"
        touch(line)
    elif action == "BRAND_APPROVE":
        # Version-pinning on approval: use-count bump advances Formula.version.
        formula["licensed_use_count"] += 1
        touch(formula)
        line["pinned_formula_version"] = formula["version"]
        line["status"] = "APPROVED"
        touch(line)
    elif action == "BRAND_REQUEST_REVISION":
        line["status"] = "LICENSOR_REVIEW"
        touch(line)
    elif action == "BRAND_REJECT":
        line["status"] = "REJECTED"
        touch(line)
    else:  # REINSTATE
        line["status"] = "APPROVED"
        touch(line)
    line["projected_royalty_cents"] = compute_royalty_cents(line)
    return ok(serialize_line(line))


def register(app):
    app.add_url_rule("/crayon-works/licensed-lines", view_func=create_line, methods=["POST"])
    app.add_url_rule("/crayon-works/licensed-lines/<line_id>", view_func=get_line, methods=["GET"])
    app.add_url_rule("/crayon-works/licensed-lines/<line_id>/transition",
                     view_func=line_transition, methods=["POST"])
