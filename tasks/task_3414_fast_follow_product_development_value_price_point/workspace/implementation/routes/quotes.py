"""Cost quotes (PRD 3.5): ManufacturerRep submission with OCC on the product,
provisional landed cost at creation, same-CM supersession, the heavily gated
acceptance transition, withdrawal, settlement with actuals, lazy expiry.
"""
from flask import Blueprint

from core import clock
from core.auth import authenticate, forbid, require_role
from core.constants import ROLE_MANUFACTURER_REP, ROLE_SOURCING_LEAD
from core.envelope import pub, success_object
from core.errors import bad_request, err, not_found
from core.pagination import list_response
from core.store import new_record, store, touch
from core.validate import get_body, req_enum, req_int, req_num, req_dt, req_str
from services import calc, cascade

bp = Blueprint("quotes", __name__)

STATUSES = (
    "SUBMITTED",
    "UNDER_EVALUATION",
    "ACCEPTED",
    "SETTLED",
    "REJECTED",
    "SUPERSEDED",
    "WITHDRAWN",
    "EXPIRED",
    "INVALIDATED",
)
PENDING = ("SUBMITTED", "UNDER_EVALUATION")


@bp.post("/cost-quotes")
def create_cost_quote():
    user_id, role = authenticate()
    require_role(role, ROLE_MANUFACTURER_REP)
    body = get_body()
    # Ownership is part of authorization: a ManufacturerRep submits only its
    # own manufacturer's quotes.
    raw_cm = body.get("contract_manufacturer_id")
    if isinstance(raw_cm, str) and raw_cm != user_id:
        forbid("a ManufacturerRep may only submit quotes for its own manufacturer")
    product_id = req_str(body, "product_id")
    cm_id = req_str(body, "contract_manufacturer_id")
    unit_cost_cents = req_int(body, "unit_cost_cents", minimum=0)
    tooling_fee_cents = 0
    if body.get("tooling_fee_cents") is not None:
        tooling_fee_cents = req_int(body, "tooling_fee_cents", minimum=0)
    freight_total_cents = req_int(body, "freight_total_cents", minimum=0)
    unit_weight_grams = req_int(body, "unit_weight_grams", minimum=1)
    shipment_weight_grams = req_int(body, "shipment_weight_grams", minimum=1)
    if shipment_weight_grams < unit_weight_grams:
        raise bad_request(
            "field 'shipment_weight_grams' must be at least 'unit_weight_grams'"
        )
    duty_rate = req_num(body, "duty_rate", minimum=0, maximum=1)
    initial_order_qty = req_int(body, "initial_order_qty", minimum=1)
    valid_until = req_dt(body, "valid_until")
    production_quarter = req_str(body, "production_quarter")
    expected_product_version = req_int(body, "expected_product_version")

    product = store.products.get(product_id)
    if product is None:
        raise not_found("ERR_PRODUCT_NOT_FOUND", "product not found")
    cm = store.manufacturers.get(cm_id)
    if cm is None:
        raise not_found("ERR_MANUFACTURER_NOT_FOUND", "contract manufacturer not found")
    if expected_product_version != product["version"]:
        raise err(
            "ERR_STALE_VERSION",
            "expected_product_version does not match the product's current version",
        )
    if cm["status"] != "ACTIVE":
        raise err("ERR_CM_SUSPENDED", "the contract manufacturer is suspended")

    fields = {
        "product_id": product_id,
        "contract_manufacturer_id": cm_id,
        "unit_cost_cents": unit_cost_cents,
        "tooling_fee_cents": tooling_fee_cents,
        "freight_total_cents": freight_total_cents,
        "unit_weight_grams": unit_weight_grams,
        "shipment_weight_grams": shipment_weight_grams,
        "duty_rate": duty_rate,
        "initial_order_qty": initial_order_qty,
        "valid_until": valid_until,
        "production_quarter": production_quarter,
    }
    landed, fpu, dpu = calc.provisional_landed(fields)
    rec = new_record(
        dict(
            fields,
            status="SUBMITTED",
            landed_provisional_cents=landed,
            landed_settled_cents=None,
            pinned_formula_version=None,
            accepted_at=None,
        )
    )
    # Freight/duty per-unit components are reused verbatim at quantity lock.
    rec["_fpu"] = fpu
    rec["_dpu"] = dpu
    store.cost_quotes[rec["id"]] = rec
    # Creating a quote supersedes the same manufacturer's prior SUBMITTED
    # quote for the product, and advances the product's version (OCC).
    for other in store.cost_quotes.values():
        if (
            other["id"] != rec["id"]
            and other["product_id"] == product_id
            and other["contract_manufacturer_id"] == cm_id
            and other["status"] == "SUBMITTED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(product)
    return success_object(pub(rec), code=201)


@bp.get("/cost-quotes")
def list_cost_quotes():
    authenticate()
    for quote in store.cost_quotes.values():
        cascade.eval_quote_expiry(quote)
    return list_response(
        store.cost_quotes.values(),
        {
            "product_id": "product_id",
            "contract_manufacturer_id": "contract_manufacturer_id",
            "status": "status",
        },
        pub,
    )


@bp.get("/cost-quotes/<rid>")
def get_cost_quote(rid):
    authenticate()
    rec = store.cost_quotes.get(rid)
    if rec is None:
        raise not_found("ERR_COST_QUOTE_NOT_FOUND", "cost quote not found")
    cascade.eval_quote_expiry(rec)
    return success_object(pub(rec))


def _accept(rec):
    """UNDER_EVALUATION -> ACCEPTED gate chain, evaluated in validation
    priority order (PRD 2.8): product/formula (12), quote expiry (16), CM
    availability (24), MOQ (25), quarterly capacity (26), cost target (27)."""
    product = store.products.get(rec["product_id"])
    if product is None or product["status"] != "SOURCING":
        raise err(
            "ERR_PRODUCT_NOT_SOURCING", "the product is not in SOURCING status"
        )
    approved = [
        p
        for p in store.formula_projects.values()
        if p["product_id"] == rec["product_id"] and p["status"] == "APPROVED"
    ]
    if not approved:
        raise err(
            "ERR_FORMULA_NOT_APPROVED",
            "no APPROVED formula project exists for this product",
        )
    if clock.now() > rec["valid_until"]:
        # The quote lazily transitions to EXPIRED as the error is reported.
        rec["status"] = "EXPIRED"
        touch(rec)
        raise err("ERR_QUOTE_EXPIRED", "the quote's valid_until has passed")
    cm = store.manufacturers.get(rec["contract_manufacturer_id"])
    if cm is None or cm["status"] != "ACTIVE":
        raise err("ERR_CM_SUSPENDED", "the contract manufacturer is suspended")
    if rec["initial_order_qty"] < cm["moq_units"]:
        raise err(
            "ERR_BELOW_MOQ",
            "initial_order_qty is below the manufacturer's minimum order quantity",
        )
    consumed = calc.cm_accepted_count(
        rec["contract_manufacturer_id"], rec["production_quarter"], store.cost_quotes.values()
    )
    if consumed >= cm["capacity_slots_per_quarter"]:
        raise err(
            "ERR_CAPACITY_EXCEEDED",
            "the manufacturer's quarterly production slot pool is exhausted",
        )
    concept = store.concepts.get(product["concept_id"])
    target = concept["target_unit_cost_cents"] if concept else None
    if target is not None and rec["landed_provisional_cents"] > target:
        raise err(
            "ERR_COST_TARGET_EXCEEDED",
            "provisional landed cost exceeds the concept's target unit cost",
        )
    rec["pinned_formula_version"] = max(p["formula_version"] for p in approved)
    rec["status"] = "ACCEPTED"
    rec["accepted_at"] = clock.now()
    # Acceptance supersedes every other still-pending quote for the product.
    for other in store.cost_quotes.values():
        if (
            other["id"] != rec["id"]
            and other["product_id"] == rec["product_id"]
            and other["status"] in PENDING
        ):
            other["status"] = "SUPERSEDED"
            touch(other)


@bp.patch("/cost-quotes/<rid>")
def patch_cost_quote(rid):
    user_id, role = authenticate()
    require_role(role, ROLE_SOURCING_LEAD, ROLE_MANUFACTURER_REP)
    body = get_body()
    raw_target = body.get("status")
    # Field-level authorization (priority 2): withdrawal requires the quote's
    # own ManufacturerRep; every other status target requires SourcingLead.
    if raw_target is not None:
        if raw_target == "WITHDRAWN":
            require_role(role, ROLE_MANUFACTURER_REP)
        else:
            require_role(role, ROLE_SOURCING_LEAD)
    # Shape validation (priority 3) — enum membership and the conditionally
    # required settlement fields — precedes path resolution (priority 4).
    target = None
    if raw_target is not None:
        target = req_enum(body, "status", STATUSES)
    actual_qty = None
    actual_freight = None
    if target == "SETTLED":
        actual_qty = req_int(body, "actual_qty", minimum=1)
        actual_freight = req_int(body, "actual_freight_total_cents", minimum=0)
    rec = store.cost_quotes.get(rid)
    if rec is None:
        raise not_found("ERR_COST_QUOTE_NOT_FOUND", "cost quote not found")
    if raw_target == "WITHDRAWN" and rec["contract_manufacturer_id"] != user_id:
        forbid("a ManufacturerRep may only withdraw its own manufacturer's quotes")

    if target is None:
        return success_object(pub(rec))

    current = rec["status"]
    # Lazy expiry: a pending quote past valid_until becomes EXPIRED on any
    # attempted transition. For an acceptance attempt the pipeline reports
    # ERR_QUOTE_EXPIRED at its own step instead, so only pre-expire here when
    # the request is anything else.
    if current in PENDING and clock.now() > rec["valid_until"] and not (
        target == "ACCEPTED" and current == "UNDER_EVALUATION"
    ):
        cascade.eval_quote_expiry(rec)
        current = rec["status"]

    if target == "UNDER_EVALUATION" and current == "SUBMITTED":
        rec["status"] = "UNDER_EVALUATION"
    elif target == "ACCEPTED" and current == "UNDER_EVALUATION":
        _accept(rec)
    elif target == "REJECTED" and current == "UNDER_EVALUATION":
        rec["status"] = "REJECTED"
    elif target == "WITHDRAWN" and current in PENDING:
        rec["status"] = "WITHDRAWN"
    elif target == "SETTLED" and current == "ACCEPTED":
        product = store.products.get(rec["product_id"])
        if product is None or product["status"] != "LAUNCHED":
            raise err(
                "ERR_INVALID_STATE",
                "a quote can only be settled once its product is LAUNCHED",
            )
        rec["landed_settled_cents"] = calc.settled_landed(rec, actual_qty, actual_freight)
        rec["status"] = "SETTLED"
    else:
        raise err(
            "ERR_INVALID_STATE",
            "cannot transition a cost quote from %s to %s" % (current, target),
        )
    touch(rec)
    return success_object(pub(rec))
