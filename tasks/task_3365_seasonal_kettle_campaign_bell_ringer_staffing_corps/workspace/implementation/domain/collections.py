"""Counting room controls: variance, handling fees and deposits (PRD 3.4)."""
from flask import request

from core import calcs, clock, store, validate
from core.auth import require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

DEPOSIT_STATUSES = ("SUBMITTED", "VERIFIED", "VARIANCE_HOLD", "DEPOSITED", "RECONCILED")


def refresh_location_total(location):
    location["location_total_cents"] = calcs.location_total_cents(location["id"])
    store.touch(location)
    return location


def refresh_campaign_total(campaign):
    campaign["total_raised_cents"] = calcs.campaign_total_raised(campaign["id"])
    store.touch(campaign)
    return campaign


def refresh_totals_for_collection(collection):
    location = store.find("kettle_locations", collection.get("kettle_location_id"))
    if location is not None:
        refresh_location_total(location)
        campaign = store.find("campaigns", location.get("campaign_id"))
        if campaign is not None:
            refresh_campaign_total(campaign)


@bp.route("/kettle-collections", methods=["POST"])
def create_collection():
    require_role(["CountingRoomTeller", "FinanceOfficer", "CorpsOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("kettle_location_id", validate.STRING, required=True),
            validate.f("collected_on", validate.DATETIME, required=True),
            validate.f("declared_cents", validate.INTEGER, required=True),
            validate.f("coin_cents", validate.INTEGER),
            validate.f("currency_cents", validate.INTEGER),
            validate.f("check_cents", validate.INTEGER),
        ]
    )
    location = validate.reference("kettle_locations", values["kettle_location_id"], "kettle location")
    campaign = store.find("campaigns", location.get("campaign_id"))
    if campaign is None or campaign.get("status") != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_NOT_ACTIVE")
    if location.get("status") != "ACTIVE":
        raise ApiError("ERR_LOCATION_NOT_ACTIVE")

    collected_on = values["collected_on"]
    starts_on = clock.parse(location.get("placement_starts_on"))
    ends_on = clock.parse(location.get("placement_ends_on"))
    if starts_on is None or ends_on is None or not (starts_on <= collected_on <= ends_on):
        raise ApiError("ERR_COLLECTION_OUTSIDE_PLACEMENT_WINDOW")

    collection = {
        "kettle_location_id": location["id"],
        "collected_on": clock.fmt(collected_on),
        "declared_cents": int(values["declared_cents"]),
        "coin_cents": int(values.get("coin_cents", 0) or 0),
        "currency_cents": int(values.get("currency_cents", 0) or 0),
        "check_cents": int(values.get("check_cents", 0) or 0),
        "counted_total_cents": 0,
        "variance_cents": 0,
        "handling_fee_cents": 0,
        "deposit_status": "SUBMITTED",
        "deposited_cents": 0,
        "deposit_reference": None,
    }
    collection["counted_total_cents"] = calcs.counted_total(collection)
    collection["handling_fee_cents"] = calcs.handling_fee_cents(
        collection["coin_cents"], collection["currency_cents"], collection["check_cents"]
    )
    store.insert("kettle_collections", collection)
    return success(store.public(collection)), 201


@bp.route("/kettle-collections", methods=["GET"])
def list_collections():
    require_role(
        [
            "PlatformAdmin",
            "CountingRoomTeller",
            "FinanceOfficer",
            "CorpsOfficer",
            "KettleCoordinator",
            "TerritorialCommander",
            "DivisionalOfficer",
        ]
    )
    args = request.args
    rows = store.ordered("kettle_collections")
    for field in ("kettle_location_id", "deposit_status"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    collected_on = args.get("collected_on")
    if collected_on:
        rows = [r for r in rows if str(r.get("collected_on") or "").startswith(collected_on[:10])]
    return page([store.public(r) for r in rows], args)


@bp.route("/kettle-collections/<collection_id>", methods=["GET"])
def get_collection(collection_id):
    require_role(
        [
            "PlatformAdmin",
            "CountingRoomTeller",
            "FinanceOfficer",
            "CorpsOfficer",
            "KettleCoordinator",
            "TerritorialCommander",
            "DivisionalOfficer",
        ]
    )
    collection = validate.path_row("kettle_collections", collection_id, "kettle collection")
    return success(store.public(collection))


@bp.route("/kettle-collections/<collection_id>/verify", methods=["POST"])
def verify_collection(collection_id):
    require_role(["CountingRoomTeller", "FinanceOfficer", "PlatformAdmin"])
    values = validate.shape(
        [validate.f("expected_kettle_collection_version", validate.INTEGER, required=True)]
    )
    collection = validate.path_row("kettle_collections", collection_id, "kettle collection")
    validate.expect_version(
        collection, values["expected_kettle_collection_version"], "expected_kettle_collection_version"
    )
    status = collection.get("deposit_status")
    if status == "RECONCILED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    collection["counted_total_cents"] = calcs.counted_total(collection)
    collection["handling_fee_cents"] = calcs.handling_fee_cents(
        collection.get("coin_cents"), collection.get("currency_cents"), collection.get("check_cents")
    )
    variance = calcs.provisional_variance(collection)
    collection["variance_cents"] = variance

    if abs(variance) <= calcs.VARIANCE_TOLERANCE_CENTS:
        collection["deposit_status"] = "VERIFIED"
        store.touch(collection)
    else:
        collection["deposit_status"] = "VARIANCE_HOLD"
        store.touch(collection)
        location = store.find("kettle_locations", collection.get("kettle_location_id"))
        if location is not None:
            calcs.apply_variance_demotion(location)
    return success(store.public(collection))


@bp.route("/kettle-collections/<collection_id>/recount", methods=["POST"])
def recount_collection(collection_id):
    require_role(["CountingRoomTeller", "FinanceOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("coin_cents", validate.INTEGER, required=True),
            validate.f("currency_cents", validate.INTEGER, required=True),
            validate.f("check_cents", validate.INTEGER, required=True),
        ]
    )
    collection = validate.path_row("kettle_collections", collection_id, "kettle collection")
    status = collection.get("deposit_status")
    if status == "RECONCILED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "VARIANCE_HOLD":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    for name in ("coin_cents", "currency_cents", "check_cents"):
        if values[name] < 0:
            raise ApiError("ERR_INVALID_REQUEST", "%s must be zero or greater." % name)

    collection["coin_cents"] = int(values["coin_cents"])
    collection["currency_cents"] = int(values["currency_cents"])
    collection["check_cents"] = int(values["check_cents"])
    # PRD §3.4: `counted_total_cents` "is the sum of the coin, currency and
    # cheque counts" and `handling_fee_cents` is computed from those counts, so
    # replacing the counts re-derives both before the collection is re-verified.
    collection["counted_total_cents"] = calcs.counted_total(collection)
    collection["handling_fee_cents"] = calcs.handling_fee_cents(
        collection.get("coin_cents"), collection.get("currency_cents"), collection.get("check_cents")
    )
    collection["deposit_status"] = "SUBMITTED"
    store.touch(collection)
    return success(store.public(collection))


@bp.route("/kettle-collections/<collection_id>/deposit", methods=["POST"])
def deposit_collection(collection_id):
    require_role(["FinanceOfficer", "PlatformAdmin"])
    values = validate.shape([validate.f("deposited_cents", validate.INTEGER, required=True)])
    collection = validate.path_row("kettle_collections", collection_id, "kettle collection")
    status = collection.get("deposit_status")
    if status == "RECONCILED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    expected = calcs.counted_total(collection) - int(collection.get("handling_fee_cents", 0) or 0)
    if int(values["deposited_cents"]) != expected:
        raise ApiError("ERR_DEPOSIT_AMOUNT_MISMATCH")

    collection["deposited_cents"] = int(values["deposited_cents"])
    collection["deposit_reference"] = clock.new_deposit_reference()
    collection["deposit_status"] = "DEPOSITED"
    store.touch(collection)
    refresh_totals_for_collection(collection)
    return success(store.public(collection))


@bp.route("/kettle-collections/<collection_id>/reconcile", methods=["POST"])
def reconcile_collection(collection_id):
    require_role(["FinanceOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("matched", validate.BOOLEAN, required=True),
            validate.f("bank_confirmed_cents", validate.INTEGER),
        ]
    )
    collection = validate.path_row("kettle_collections", collection_id, "kettle collection")
    status = collection.get("deposit_status")
    if status == "RECONCILED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "DEPOSITED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    deposited = int(collection.get("deposited_cents", 0) or 0)
    bank = values.get("bank_confirmed_cents")
    if bank is None:
        bank = deposited
    if abs(int(bank) - deposited) > calcs.VARIANCE_TOLERANCE_CENTS:
        raise ApiError("ERR_VARIANCE_EXCEEDS_TOLERANCE")

    if values["matched"] and int(bank) == deposited:
        collection["deposit_status"] = "RECONCILED"
        collection["variance_cents"] = calcs.final_variance(collection)
    else:
        collection["deposit_status"] = "VARIANCE_HOLD"
    store.touch(collection)
    refresh_totals_for_collection(collection)
    return success(store.public(collection))
