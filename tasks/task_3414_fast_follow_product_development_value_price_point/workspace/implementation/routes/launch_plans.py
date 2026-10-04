"""Launch plans (PRD 3.8): quantity variants and markdown risk at creation,
single-pass quantity lock, approval (compliance + committed slot + sample
budget), execution fan-out, reconciliation with markdown exposure, and the
MarketingLead sampling track with append-only distribution events.
"""
from flask import Blueprint

from core import clock
from core.auth import authenticate, forbid, require_role
from core.constants import ROLE_MARKETING_LEAD, ROLE_PRODUCT_MANAGER
from core.envelope import pub, success_object
from core.errors import bad_request, err, not_found
from core.pagination import list_response
from core.store import new_record, store, touch
from core.validate import get_body, opt_int, opt_str, req_enum, req_int, req_str
from services import calc, cascade

bp = Blueprint("launch_plans", __name__)

STATUSES = ("DRAFT", "QUANTITY_LOCKED", "APPROVED", "EXECUTED", "RECONCILED")
SAMPLING_STATUSES = ("NONE", "PLANNED", "ACTIVE", "CLOSED")
VARIANTS = ("DEMAND", "RISK_ADJUSTED")
EVENT_TYPES = ("COMMIT", "DISTRIBUTE", "RELEASE")

PM_FIELDS = ("status", "variant")
ML_FIELDS = ("sampling_status", "sample_budget_cents")


def _pub_plan(rec):
    data = pub(rec)
    if rec["qty_locked_units"] is None:
        data["retail_units_available"] = None
    else:
        data["retail_units_available"] = (
            rec["qty_locked_units"]
            - rec["samples_committed"]
            - rec["samples_distributed"]
            - rec["markdown_units"]
        )
    return data


def _accepted_quote(product_id):
    """The product's operative ACCEPTED quote: the most recently accepted one
    (accepted_at, then insertion order)."""
    accepted = [
        q
        for q in store.cost_quotes.values()
        if q["product_id"] == product_id and q["status"] == "ACCEPTED"
    ]
    if not accepted:
        return None
    accepted.sort(key=lambda q: (q["accepted_at"], q["_seq"]))
    return accepted[-1]


@bp.post("/launch-plans")
def create_launch_plan():
    _, role = authenticate()
    require_role(role, ROLE_PRODUCT_MANAGER)
    body = get_body()
    product_id = req_str(body, "product_id")
    planogram_slot_id = req_str(body, "planogram_slot_id")
    demand = req_int(body, "demand_forecast_units", minimum=0)
    marketing_budget = req_int(body, "marketing_budget_cents", minimum=0)
    cogs_budget = req_int(body, "cogs_budget_cents", minimum=0)
    sample_budget = opt_int(body, "sample_budget_cents", default=0, minimum=0)
    product = store.products.get(product_id)
    if product is None:
        raise not_found("ERR_PRODUCT_NOT_FOUND", "product not found")
    slot = store.planogram_slots.get(planogram_slot_id)
    if slot is None:
        raise not_found("ERR_PLANOGRAM_SLOT_NOT_FOUND", "planogram slot not found")
    rec = new_record(
        {
            "product_id": product_id,
            "planogram_slot_id": planogram_slot_id,
            "demand_forecast_units": demand,
            "marketing_budget_cents": marketing_budget,
            "cogs_budget_cents": cogs_budget,
            "sample_budget_cents": sample_budget,
            "status": "DRAFT",
            "sampling_status": "NONE",
            "markdown_risk_pct": None,
            "capacity_units": None,
            "qty_demand_variant_units": None,
            "qty_risk_variant_units": None,
            "qty_locked_units": None,
            "locked_variant": None,
            "landed_locked_cents": None,
            "samples_committed": 0,
            "samples_distributed": 0,
            "sample_spend_cents": 0,
            "markdown_units": 0,
            "markdown_exposure_cents": None,
        }
    )
    # Creation-time computed quantities (calculations.launch_quantity variants
    # and calculations.markdown_risk via product -> concept -> trend).
    rec["capacity_units"] = calc.capacity_units(slot["facings"])
    concept = store.concepts.get(product["concept_id"])
    trend = store.trend_signals.get(concept["trend_signal_id"]) if concept else None
    if trend is not None:
        rec["markdown_risk_pct"] = calc.markdown_risk_pct(
            trend["created_at"], rec["created_at"]
        )
    else:
        rec["markdown_risk_pct"] = 0.0
    demand_variant, risk_variant = calc.qty_variants(
        demand, rec["capacity_units"], rec["markdown_risk_pct"]
    )
    rec["qty_demand_variant_units"] = demand_variant
    rec["qty_risk_variant_units"] = risk_variant
    store.launch_plans[rec["id"]] = rec
    return success_object(_pub_plan(rec), code=201)


@bp.get("/launch-plans")
def list_launch_plans():
    authenticate()
    return list_response(
        store.launch_plans.values(),
        {
            "product_id": "product_id",
            "planogram_slot_id": "planogram_slot_id",
            "status": "status",
        },
        _pub_plan,
    )


@bp.get("/launch-plans/<rid>")
def get_launch_plan(rid):
    authenticate()
    rec = store.launch_plans.get(rid)
    if rec is None:
        raise not_found("ERR_LAUNCH_PLAN_NOT_FOUND", "launch plan not found")
    return success_object(_pub_plan(rec))


def _lock_quantity(rec, variant):
    quote = _accepted_quote(rec["product_id"])
    if quote is None:
        raise err(
            "ERR_QUOTE_NOT_ACCEPTED", "no ACCEPTED cost quote exists for this product"
        )
    cm = store.manufacturers.get(quote["contract_manufacturer_id"])
    moq = cm["moq_units"]
    q0 = (
        rec["qty_demand_variant_units"]
        if variant == "DEMAND"
        else rec["qty_risk_variant_units"]
    )

    def landed_at(q):
        return calc.landed_unit_cost(
            quote["unit_cost_cents"], quote["tooling_fee_cents"], q, quote["_fpu"], quote["_dpu"]
        )

    qty, landed_locked = calc.lock_quantity(q0, rec["cogs_budget_cents"], moq, landed_at)
    rec["qty_locked_units"] = qty
    rec["locked_variant"] = variant
    rec["landed_locked_cents"] = landed_locked
    rec["status"] = "QUANTITY_LOCKED"


def _approve(rec):
    # Compliance gate (priority 8) evaluates before the slot referential check
    # (priority 13) and the budget check (priority 28).
    if not cascade.dossier_compliant(rec["product_id"]):
        raise err(
            "ERR_COMPLIANCE_GATE_FAILED",
            "the product's compliance dossier is not fully compliant",
        )
    slot = store.planogram_slots.get(rec["planogram_slot_id"])
    if slot is None or slot["status"] != "COMMITTED":
        raise err(
            "ERR_SLOT_NOT_COMMITTED", "the planogram slot is not in COMMITTED status"
        )
    if rec["sample_budget_cents"] > rec["marketing_budget_cents"]:
        raise err(
            "ERR_BUDGET_EXCEEDED",
            "sample_budget_cents exceeds marketing_budget_cents",
        )
    rec["status"] = "APPROVED"


def _execute(rec):
    slot = store.planogram_slots.get(rec["planogram_slot_id"])
    if slot is None or clock.now() < slot["occupancy_start"]:
        raise err(
            "ERR_LAUNCH_WINDOW_NOT_OPEN",
            "the slot's occupancy window has not started",
        )
    rec["status"] = "EXECUTED"
    # Atomic fan-out: product launches, slot activates, concept commercializes.
    product = store.products.get(rec["product_id"])
    if product is not None and product["status"] == "LAUNCH_READY":
        product["status"] = "LAUNCHED"
        product["launched_at"] = clock.now()
        touch(product)
        concept = store.concepts.get(product["concept_id"])
        if concept is not None and concept["status"] == "IN_DEVELOPMENT":
            concept["status"] = "COMMERCIALIZED"
            touch(concept)
    if slot["status"] == "COMMITTED":
        slot["status"] = "ACTIVE"
        touch(slot)


def _apply_sampling_transition(rec, target):
    current = rec["sampling_status"]
    if target == "PLANNED" and current == "NONE":
        if rec["status"] not in ("QUANTITY_LOCKED", "APPROVED", "EXECUTED"):
            raise err(
                "ERR_INVALID_STATE",
                "sampling can only be planned once the quantity is locked",
            )
        rec["sampling_status"] = "PLANNED"
    elif target == "ACTIVE" and current == "PLANNED":
        if rec["status"] != "EXECUTED":
            raise err(
                "ERR_INVALID_STATE",
                "sampling can only go active once the plan is EXECUTED",
            )
        rec["sampling_status"] = "ACTIVE"
    elif target == "CLOSED" and current == "ACTIVE":
        rec["sampling_status"] = "CLOSED"
    else:
        raise err(
            "ERR_INVALID_STATE",
            "cannot transition sampling_status from %s to %s" % (current, target),
        )


@bp.patch("/launch-plans/<rid>")
def patch_launch_plan(rid):
    _, role = authenticate()
    require_role(role, ROLE_PRODUCT_MANAGER, ROLE_MARKETING_LEAD)
    body = get_body()
    # Field-level authorization (priority 2): status/variant belong to
    # ProductManager; sampling_status/sample_budget_cents belong to
    # MarketingLead; mixing the two groups in one call is forbidden.
    pm_present = any(k in body and body[k] is not None for k in PM_FIELDS)
    ml_present = any(k in body and body[k] is not None for k in ML_FIELDS)
    if pm_present and ml_present:
        forbid("cannot mix plan-lifecycle and sampling fields in one call")
    if pm_present:
        require_role(role, ROLE_PRODUCT_MANAGER)
    if ml_present:
        require_role(role, ROLE_MARKETING_LEAD)

    # Shape validation (priority 3) precedes path resolution (priority 4):
    # enum membership for both field groups, the conditionally required
    # variant, and the sampling field shapes.
    target = None
    variant = None
    if pm_present:
        if body.get("status") is not None:
            target = req_enum(body, "status", STATUSES)
        if body.get("variant") is not None:
            variant = req_enum(body, "variant", VARIANTS)
        if target == "QUANTITY_LOCKED" and variant is None:
            raise bad_request(
                "field 'variant' is required when locking the quantity"
            )
    new_budget = None
    target_sampling = None
    if ml_present:
        if body.get("sample_budget_cents") is not None:
            new_budget = req_int(body, "sample_budget_cents", minimum=0)
        if body.get("sampling_status") is not None:
            target_sampling = req_enum(body, "sampling_status", SAMPLING_STATUSES)

    rec = store.launch_plans.get(rid)
    if rec is None:
        raise not_found("ERR_LAUNCH_PLAN_NOT_FOUND", "launch plan not found")
    if not pm_present and not ml_present:
        return success_object(_pub_plan(rec))

    if pm_present:
        if target is None:
            return success_object(_pub_plan(rec))
        current = rec["status"]
        if target == "QUANTITY_LOCKED" and current == "DRAFT":
            _lock_quantity(rec, variant)
        elif target == "APPROVED" and current == "QUANTITY_LOCKED":
            _approve(rec)
        elif target == "EXECUTED" and current == "APPROVED":
            _execute(rec)
        elif target == "RECONCILED" and current == "EXECUTED":
            if rec["sampling_status"] not in ("NONE", "CLOSED"):
                raise err(
                    "ERR_INVALID_STATE",
                    "sampling_status must be NONE or CLOSED to reconcile",
                )
            cascade.reconcile_plan(rec)
        else:
            raise err(
                "ERR_INVALID_STATE",
                "cannot transition a launch plan from %s to %s" % (current, target),
            )
    if ml_present:
        # The sampling transition is validated (and may raise) before the
        # budget write so a failed combined update leaves the record untouched.
        if target_sampling is not None:
            _apply_sampling_transition(rec, target_sampling)
        if new_budget is not None:
            rec["sample_budget_cents"] = new_budget
    touch(rec)
    return success_object(_pub_plan(rec))


@bp.post("/launch-plans/<rid>/sample-distributions")
def post_sample_distribution(rid):
    _, role = authenticate()
    require_role(role, ROLE_MARKETING_LEAD)
    body = get_body()
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    units = req_int(body, "units", minimum=1)
    opt_str(body, "channel")  # accepted, informational
    rec = store.launch_plans.get(rid)
    if rec is None:
        raise not_found("ERR_LAUNCH_PLAN_NOT_FOUND", "launch plan not found")
    if rec["status"] not in ("QUANTITY_LOCKED", "APPROVED", "EXECUTED"):
        raise err(
            "ERR_INVALID_STATE",
            "sampling events require a locked, unreconciled launch plan",
        )
    if rec["sampling_status"] == "CLOSED":
        raise err(
            "ERR_INVALID_STATE",
            "the sampling program is closed; no further distribution events "
            "are accepted",
        )
    if event_type == "DISTRIBUTE" and rec["sampling_status"] != "ACTIVE":
        raise err(
            "ERR_INVALID_STATE", "DISTRIBUTE requires sampling_status ACTIVE"
        )
    if event_type == "COMMIT":
        cap = calc.sample_cap(rec["qty_locked_units"])
        if rec["samples_committed"] + rec["samples_distributed"] + units > cap:
            raise err(
                "ERR_SAMPLE_OVERDRAW",
                "the event would exceed the sampling unit cap",
            )
        retail_available = (
            rec["qty_locked_units"]
            - rec["samples_committed"]
            - rec["samples_distributed"]
            - rec["markdown_units"]
        )
        if units > retail_available:
            raise err(
                "ERR_SAMPLE_OVERDRAW",
                "the event exceeds the available retail units",
            )
        rec["samples_committed"] += units
    elif event_type == "DISTRIBUTE":
        if units > rec["samples_committed"]:
            raise err(
                "ERR_SAMPLE_OVERDRAW",
                "the event exceeds the committed sampling units",
            )
        new_spend = rec["sample_spend_cents"] + units * rec["landed_locked_cents"]
        if new_spend > rec["sample_budget_cents"]:
            raise err(
                "ERR_SAMPLE_OVERDRAW", "the event would exceed the sample budget"
            )
        rec["sample_spend_cents"] = new_spend
        rec["samples_committed"] -= units
        rec["samples_distributed"] += units
    else:  # RELEASE — the compensating action
        if units > rec["samples_committed"]:
            raise err(
                "ERR_SAMPLE_OVERDRAW",
                "the event exceeds the committed sampling units",
            )
        rec["samples_committed"] -= units
    touch(rec)
    return success_object(_pub_plan(rec), code=201)
