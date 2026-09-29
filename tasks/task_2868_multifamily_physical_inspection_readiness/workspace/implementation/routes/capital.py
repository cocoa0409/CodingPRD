"""Capital needs planning and reserve allocation (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common

bp = Blueprint("capital", __name__)


def _closed_history(property_id):
    """finalized_at DESC with the later created_at breaking ties first."""
    rows = [
        i
        for i in derive.property_inspections(property_id)
        if i["status"] == "CLOSED" and i.get("finalized_at")
    ]
    rows.sort(
        key=lambda i: (
            store.parse_instant(i["finalized_at"]),
            store.parse_instant(i["created_at"]),
            i["_seq"],
        ),
        reverse=True,
    )
    return rows


def _scoped_inspections(property_id, basis):
    history = _closed_history(property_id)
    if basis == "INSPECTION_SCOPED":
        return history[: calc.RECURRENCE_INSPECTION_WINDOW]
    lower_bound = store.logical_now() - calc.days(calc.RECURRENCE_CALENDAR_DAYS)
    return [
        i
        for i in history
        if store.parse_instant(i["finalized_at"]) >= lower_bound
    ]


def _recurrence_counts(scope):
    """Distinct scoped inspections citing each definition through a non-VOIDED
    INSPECTION-sourced deficiency."""
    scope_ids = set(i["id"] for i in scope)
    counts = {}
    for row in store.deficiencies.values():
        if row["source"] != "INSPECTION":
            continue
        if row["status"] == "VOIDED":
            continue
        if row.get("inspection_id") not in scope_ids:
            continue
        counts.setdefault(row["defect_definition_id"], set()).add(row["inspection_id"])
    return counts


@bp.post("/capital-needs/recompute")
def recompute_capital_needs():
    user_id, role = auth.authenticate([auth.OWNER])
    values = shapes.validate(
        [
            shapes.F("property_id", "string"),
            shapes.F("expected_property_version", "integer"),
            shapes.F(
                "recurrence_basis",
                "enum",
                required=False,
                values=shapes.RECURRENCE_BASIS,
            ),
        ]
    )
    prop = common.body_fetch("property", values["property_id"])
    auth.require_owner(role, user_id, prop["id"])
    if values["expected_property_version"] != prop["version"]:
        raise ApiError(
            "ERR_STALE_PROPERTY_VERSION",
            "expected_property_version does not match the property's current version.",
        )
    basis = values.get("recurrence_basis") or "CALENDAR_SCOPED"

    scope = _scoped_inspections(prop["id"], basis)
    counts = _recurrence_counts(scope)
    survivors = []
    for definition_id, inspection_ids in counts.items():
        count = len(inspection_ids)
        if count < calc.RECURRENCE_MIN_COUNT:
            continue
        definition = store.definitions.get(definition_id)
        if definition is None:
            continue
        survivors.append((definition, count, calc.priority_score(count, definition)))
    survivors.sort(key=lambda entry: (-entry[2], entry[0]["code"]))
    shares = calc.allocate_reserve(
        prop["capital_reserve_cents"], [entry[2] for entry in survivors]
    )

    for item in store.by_seq(derive.property_capital_items(prop["id"])):
        if item["status"] == "ACTIVE":
            item["status"] = "SUPERSEDED"
            item["allocated_reserve_cents"] = 0
            store.touch(item, bump_version=True)

    computed_at = store.fmt_instant(store.logical_now())
    generation = []
    for index, (definition, count, score) in enumerate(survivors):
        row = {
            "property_id": prop["id"],
            "defect_definition_id": definition["id"],
            "recurrence_basis": basis,
            "recurrence_count": count,
            "priority_score": score,
            "allocation_rank": index + 1,
            "allocated_reserve_cents": shares[index],
            "status": "ACTIVE",
            "computed_at": computed_at,
        }
        store.stamp_new(row)
        store.capital_items[row["id"]] = row
        generation.append(row)

    prop["allocated_reserve_total_cents"] = sum(
        row["allocated_reserve_cents"] for row in generation
    )
    store.touch(prop, bump_version=True)
    return envelope.array(generation)


@bp.get("/capital-needs/<item_id>")
def read_capital_item(item_id):
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    item = common.fetch("capital_item", item_id)
    auth.require_owner(role, user_id, item["property_id"])
    return envelope.ok(item)


@bp.get("/capital-needs")
def list_capital_items():
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    return common.listing(
        store.capital_items.values(),
        ["property_id", "defect_definition_id", "status", "recurrence_basis"],
        role=role,
        user_id=user_id,
        property_getter=lambda r: r["property_id"],
    )
