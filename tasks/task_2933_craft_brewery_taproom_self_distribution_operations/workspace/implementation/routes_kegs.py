"""The keg float and the taproom bar."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
import envelope
import helpers
import store
import validation
from errors import ApiError
from validation import ALL_ROLES, authenticate

bp = Blueprint("kegs", __name__)

KEG_STATES = ("EMPTY_DIRTY", "CLEANED", "FILLED", "TAPPED", "DEPLOYED", "DECOMMISSIONED")
DEPLOYMENT_CHANNELS = ("TAPROOM", "DISTRIBUTION", "EVENT")
MOVEMENT_TYPES = ("TAP", "DEPLOY_DISTRIBUTION", "DEPLOY_EVENT", "RETURN", "DECOMMISSION")
CONTAINER_TYPES = ("SAMPLE_4OZ", "HALF_PINT_8OZ", "PINT_16OZ", "CROWLER_32OZ", "GROWLER_64OZ")
GROWLER_LABEL_KEYS = ("brand_name", "abv_statement", "net_contents",
                      "health_warning", "fill_date")


# ---------------------------------------------------------------------------
# keg assets
# ---------------------------------------------------------------------------

@bp.get("/keg-assets")
def list_kegs():
    authenticate(ALL_ROLES)
    packaging_run_id = validation.query_string("packaging_run_id")
    filled_beer_id = validation.query_string("filled_beer_id")
    state = validation.query_enum("state", KEG_STATES)
    deployment_channel = validation.query_enum("deployment_channel", DEPLOYMENT_CHANNELS)

    def predicate(row):
        return (helpers.matches(row, "packaging_run_id", packaging_run_id)
                and helpers.matches(row, "filled_beer_id", filled_beer_id)
                and helpers.matches(row, "state", state)
                and helpers.matches(row, "deployment_channel", deployment_channel))

    rows, limit, offset, total = helpers.listing("kegs", derive.serialize_keg, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/keg-assets/<keg_id>")
def read_keg(keg_id):
    authenticate(ALL_ROLES)
    return envelope.object_response(derive.serialize_keg(helpers.find("kegs", keg_id)))


@bp.post("/keg-assets")
def create_keg():
    authenticate(["BreweryAdmin", "CellarOperator"])
    payload = validation.body()
    keg_serial = validation.field_string(payload, "keg_serial", 1, 24)
    size_bbl = validation.field_number(payload, "size_bbl", None, allowed=calc.KEG_SIZES)
    helpers.unique("kegs", keg_serial)
    row = store.new_row({
        "keg_serial": keg_serial,
        "size_bbl": size_bbl,
        "packaging_run_id": None,
        "filled_beer_id": None,
        "state": "EMPTY_DIRTY",
        "filled_volume_oz": calc.oz(0),
        "poured_volume_oz": calc.oz(0),
        "returned_volume_oz": None,
        "depletion_variance_oz": None,
        "shrinkage_flagged": False,
        "cycle_count": 0,
        "last_cleaned_utc": None,
        "tapped_at_utc": None,
        "deployment_channel": None,
    })
    helpers.insert("kegs", row)
    return envelope.object_response(derive.serialize_keg(row), 201)


@bp.post("/keg-assets/<keg_id>/clean")
def clean_keg(keg_id):
    authenticate(["CellarOperator"])
    payload = validation.body()
    ppm = validation.field_int(payload, "sanitizer_ppm")
    seconds = validation.field_int(payload, "contact_time_seconds")
    keg = helpers.find("kegs", keg_id)
    if keg.get("state") != "EMPTY_DIRTY":
        raise ApiError("ERR_KEG_TRANSITION_INVALID")
    if not calc.sanitation_passes(ppm, seconds):
        raise ApiError("ERR_SANITATION_BELOW_STANDARD")
    keg["state"] = "CLEANED"
    keg["last_cleaned_utc"] = helpers.now()
    keg["packaging_run_id"] = None
    keg["filled_beer_id"] = None
    keg["returned_volume_oz"] = None
    keg["depletion_variance_oz"] = None
    keg["shrinkage_flagged"] = False
    store.touch(keg)
    return envelope.object_response(derive.serialize_keg(keg))


@bp.post("/keg-assets/<keg_id>/fill")
def fill_keg(keg_id):
    authenticate(["CellarOperator"])
    payload = validation.body()
    run_id = validation.field_id(payload, "packaging_run_id")
    keg = helpers.find("kegs", keg_id)
    run = helpers.find("runs", run_id)
    if keg.get("state") != "CLEANED":
        raise ApiError("ERR_KEG_TRANSITION_INVALID")
    if run.get("state") != "COMPLETED":
        raise ApiError("ERR_RUN_NOT_COMPLETED")
    if calc.BBL_PER_UNIT[run["package_type"]] != Decimal(keg["size_bbl"]):
        raise ApiError("ERR_KEG_SIZE_MISMATCH")
    if (run.get("kegs_filled_count") or 0) >= int(run.get("units_produced") or 0):
        raise ApiError("ERR_RUN_UNITS_EXHAUSTED")

    batch = derive.batch_of_run(run)
    seen = set()
    keg["state"] = "FILLED"
    keg["packaging_run_id"] = run["id"]
    keg["filled_beer_id"] = batch.get("beer_id") if batch else None
    keg["filled_volume_oz"] = calc.oz(Decimal(keg["size_bbl"]) * calc.OZ_PER_BBL)
    keg["poured_volume_oz"] = calc.oz(0)
    cascades.touch_once(keg, seen)

    run["kegs_filled_count"] = (run.get("kegs_filled_count") or 0) + 1
    if run.get("reconciliation_state") == "NOT_APPLICABLE":
        run["reconciliation_state"] = "OPEN"
    cascades.touch_once(run, seen)
    return envelope.object_response(derive.serialize_keg(keg))


@bp.post("/keg-assets/<keg_id>/movements")
def move_keg(keg_id):
    authenticate(["CellarOperator", "TaproomStaff"])
    payload = validation.body()
    movement_type = validation.field_enum(payload, "movement_type", MOVEMENT_TYPES)
    keg = helpers.find("kegs", keg_id)
    helpers.brewery()

    permit = None
    if payload.get("event_permit_id") is not None:
        permit_id = validation.field_id(payload, "event_permit_id")
        permit = helpers.find("permits", permit_id)

    legal = {
        "TAP": ("FILLED",),
        "DEPLOY_DISTRIBUTION": ("FILLED",),
        "DEPLOY_EVENT": ("FILLED",),
        "RETURN": ("TAPPED", "DEPLOYED"),
        "DECOMMISSION": ("EMPTY_DIRTY",),
    }
    if keg.get("state") not in legal[movement_type]:
        raise ApiError("ERR_KEG_TRANSITION_INVALID")

    helpers.require_notice_active()
    beer = store.DB["beers"].get(keg.get("filled_beer_id"))

    seen = set()
    if movement_type == "TAP":
        _require_formula(beer)
        keg["state"] = "TAPPED"
        keg["tapped_at_utc"] = helpers.now()
        keg["deployment_channel"] = "TAPROOM"
    elif movement_type == "DEPLOY_DISTRIBUTION":
        _require_formula(beer)
        if beer is None or beer.get("label_state") != "COLA_APPROVED":
            raise ApiError("ERR_LABEL_NOT_APPROVED")
        keg["state"] = "DEPLOYED"
        keg["deployment_channel"] = "DISTRIBUTION"
    elif movement_type == "DEPLOY_EVENT":
        _require_formula(beer)
        if not _event_permit_ok(permit, keg.get("filled_beer_id")):
            raise ApiError("ERR_EVENT_PERMIT_NOT_APPROVED")
        keg["state"] = "DEPLOYED"
        keg["deployment_channel"] = "EVENT"
    elif movement_type == "RETURN":
        returned_gal = _returned_volume(payload)
        returned_oz, variance, flagged = calc.depletion_variance(
            returned_gal, keg.get("filled_volume_oz") or 0,
            keg.get("poured_volume_oz") or 0)
        if returned_oz > calc.oz(keg.get("filled_volume_oz") or 0):
            raise ApiError("ERR_RETURN_EXCEEDS_FILL")
        keg["state"] = "EMPTY_DIRTY"
        keg["returned_volume_oz"] = returned_oz
        keg["depletion_variance_oz"] = variance
        keg["shrinkage_flagged"] = flagged
        keg["cycle_count"] = (keg.get("cycle_count") or 0) + 1
        cascades.touch_once(keg, seen)
        run = store.DB["runs"].get(keg.get("packaging_run_id"))
        cascades.reconcile_run_after_return(run, seen)
        return envelope.object_response(derive.serialize_keg(keg))
    else:
        keg["state"] = "DECOMMISSIONED"
    cascades.touch_once(keg, seen)
    return envelope.object_response(derive.serialize_keg(keg))


def _require_formula(beer):
    if beer is None or not derive.formula_ok(beer):
        raise ApiError("ERR_FORMULA_NOT_APPROVED")


def _returned_volume(payload):
    for name in ("returned_volume_gal", "returned_volume_gallons"):
        if payload.get(name) is not None:
            return validation.field_number(payload, name, None, minimum=0)
    validation.bad("Field 'returned_volume_gal' is required for a RETURN movement.")


def _event_permit_ok(permit, beer_id):
    current = helpers.now()

    def covers(candidate):
        return (candidate.get("state") == "APPROVED"
                and candidate.get("featured_beer_id") == beer_id
                and candidate["event_start_utc"] <= current <= candidate["event_end_utc"])

    if permit is not None:
        return covers(permit)
    for candidate in derive.rows("permits"):
        if covers(candidate):
            return True
    return False


# ---------------------------------------------------------------------------
# taproom pours
# ---------------------------------------------------------------------------

@bp.get("/taproom-pours")
def list_pours():
    authenticate(ALL_ROLES)
    keg_asset_id = validation.query_string("keg_asset_id")
    container_type = validation.query_enum("container_type", CONTAINER_TYPES)

    def predicate(row):
        return (helpers.matches(row, "keg_asset_id", keg_asset_id)
                and helpers.matches(row, "container_type", container_type))

    rows, limit, offset, total = helpers.listing("pours", derive.serialize_pour, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/taproom-pours/<pour_id>")
def read_pour(pour_id):
    authenticate(ALL_ROLES)
    return envelope.object_response(derive.serialize_pour(helpers.find("pours", pour_id)))


@bp.post("/taproom-pours")
def create_pour():
    user_id, _role = authenticate(["TaproomStaff"])
    payload = validation.body()
    keg_asset_id = validation.field_id(payload, "keg_asset_id")
    container_type = validation.field_enum(payload, "container_type", CONTAINER_TYPES)
    price_cents = validation.field_int(payload, "price_cents", minimum=0)

    sealed = container_type in calc.GROWLER_CONTAINERS
    if sealed:
        container_sanitized = validation.field_bool(payload, "container_sanitized")
        ppm = validation.field_int(payload, "sanitizer_ppm")
        seconds = validation.field_int(payload, "contact_time_seconds")
        attested_by = validation.field_string(payload, "attested_by_user_id", 1, None)
        label_fields = validation.field_object(payload, "label_fields")
    else:
        validation.forbid(payload, calc.GROWLER_ONLY_FIELDS,
                          "for a draft container type")
        container_sanitized = None
        ppm = None
        seconds = None
        attested_by = None
        label_fields = None

    helpers.brewery()
    keg = helpers.find("kegs", keg_asset_id)
    helpers.require_notice_active()
    if keg.get("state") != "TAPPED":
        raise ApiError("ERR_KEG_NOT_TAPPED")
    beer = store.DB["beers"].get(keg.get("filled_beer_id"))
    _require_formula(beer)

    verdict = "NOT_REQUIRED"
    if sealed:
        if not calc.sanitation_passes(ppm, seconds):
            raise ApiError("ERR_SANITATION_BELOW_STANDARD")
        verdict = "PASS"
        if not validation.non_blank_members(label_fields, GROWLER_LABEL_KEYS):
            raise ApiError("ERR_GROWLER_LABEL_INCOMPLETE")
        if attested_by == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    volume_oz = calc.POUR_OZ[container_type]
    if volume_oz > derive.keg_remaining_oz(keg):
        raise ApiError("ERR_POUR_EXCEEDS_KEG_VOLUME")

    pour = store.new_row({
        "keg_asset_id": keg_asset_id,
        "container_type": container_type,
        "volume_oz": calc.oz(volume_oz),
        "price_cents": price_cents,
        "poured_at_utc": helpers.now(),
        "poured_by_user_id": user_id,
        "container_sanitized": container_sanitized,
        "sanitizer_ppm": ppm,
        "contact_time_seconds": seconds,
        "sanitation_verdict": verdict,
        "attested_by_user_id": attested_by,
        "label_fields": label_fields,
    }, versioned=False)
    helpers.insert("pours", pour)

    keg["poured_volume_oz"] = calc.oz(Decimal(keg.get("poured_volume_oz") or 0) + volume_oz)
    store.touch(keg)
    return envelope.object_response(derive.serialize_pour(pour), 201)
