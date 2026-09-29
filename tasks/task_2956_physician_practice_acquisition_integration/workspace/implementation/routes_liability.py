"""POST /liability-items and the disposition action (PRD section 3.5)."""

import enums
import machines
import services
import store
import validate
from errors import ApiError
from store import set_field

# structure -> categories for which the disposition is not permitted
NOT_PERMITTED = {
    "EXCLUDED": {
        "EQUITY": ("MALPRACTICE_TAIL", "STARK_SELF_DISCLOSURE",
                   "PAYER_REFUND_EXPOSURE"),
    },
    "ASSUMED": {
        "ASSET": ("STARK_SELF_DISCLOSURE",),
    },
}


def create_liability_item():
    validate.gate(enums.ROLES_DEAL_LEAD)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    category = validate.req_enum(body, "category", enums.LIABILITY_CATEGORIES)
    description = validate.req_str(body, "description")
    estimated = validate.req_int(body, "estimated_amount_cents", minimum=0)
    cap = validate.opt_int(body, "indemnity_cap_cents", None, minimum=0)

    acquisition = store.require("acquisitions", acquisition_id)
    services.check_freeze(acquisition)

    row = {
        "acquisition_id": acquisition_id,
        "category": category,
        "description": description,
        "estimated_amount_cents": estimated,
        "indemnity_cap_cents": cap,
        "disposition": "UNASSIGNED",
        "escrowed_amount_cents": 0,
        "disposition_note": None,
    }
    store.insert("liability_items", row)
    return services.respond_created(row)


def _check_legality(acquisition, item, target):
    blocked = NOT_PERMITTED.get(target, {}).get(acquisition["structure"], ())
    if item["category"] in blocked:
        raise ApiError(
            "ERR_LIABILITY_DISPOSITION_NOT_PERMITTED",
            "Disposition '%s' is not permitted for category '%s' under a %s deal."
            % (target, item["category"], acquisition["structure"]),
        )


def item_disposition(entity_id):
    user_id, role = validate.gate(enums.ROLES_DEAL_LEAD)
    body = validate.json_body()
    target = validate.req_enum(body, "target_disposition",
                               machines.DISPOSITION_VALUES)
    note = validate.opt_str(body, "disposition_note")

    item = store.require("liability_items", entity_id)
    acquisition = store.require("acquisitions", item["acquisition_id"])
    from_state = item["disposition"]

    # Rank 3 in substance: the indemnity cap is an intra-body constraint, and it
    # is evaluated as soon as the item it refers to has been resolved.
    if target == "INDEMNIFIED":
        cap = item["indemnity_cap_cents"]
        if cap is None or cap < item["estimated_amount_cents"]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "indemnity_cap_cents must be present and at least "
                "estimated_amount_cents to indemnify this exposure.",
            )

    # Rank 14, then rank 15, then rank 25, then rank 46.
    machines.resolve(machines.DISPOSITION, from_state, target, role)
    services.check_freeze(acquisition)
    _check_legality(acquisition, item, target)

    if target == "ESCROWED":
        if item["estimated_amount_cents"] > acquisition["escrow_available_cents"]:
            raise ApiError("ERR_ESCROW_INSUFFICIENT",
                           "escrow_available_cents is %d; this exposure needs %d."
                           % (acquisition["escrow_available_cents"],
                              item["estimated_amount_cents"]))

    set_field(item, "disposition", target)
    if note is not None:
        set_field(item, "disposition_note", note)

    if target == "ESCROWED":
        set_field(item, "escrowed_amount_cents", item["estimated_amount_cents"])
        services.recompute_escrow(acquisition)
    elif from_state == "ESCROWED" and target == "EXCLUDED":
        set_field(item, "escrowed_amount_cents", 0)
        services.recompute_escrow(acquisition)

    return services.respond(item)


def register(app):
    app.add_url_rule("/liability-items", "create_liability_item",
                     create_liability_item, methods=["POST"])
    app.add_url_rule("/liability-items/<entity_id>/disposition",
                     "item_disposition", item_disposition, methods=["POST"])
