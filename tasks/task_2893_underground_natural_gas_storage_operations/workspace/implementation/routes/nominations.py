"""Nomination endpoints: filing, submission and the allocation waterfall (PRD 3.5)."""
from flask import Blueprint

import auth
import config
import engine
import envelope
import serialize
import store
import validate
from errors import ApiError, bad_request
from routes.helpers import filter_eq, list_result
from utils import D

bp = Blueprint("nominations", __name__)

NON_TERMINAL = ("DRAFT", "SUBMITTED", "CONFIRMED", "CURTAILED")


@bp.post("/nominations")
def create_nomination():
    user_id, role = auth.require([config.ROLE_SHIPPER])
    body = validate.json_body()

    contract_id = validate.field_id(body, "contract_id")
    gas_day = validate.field_date(body, "gas_day")
    direction = validate.field_enum(body, "direction", config.DIRECTIONS)
    nominated = validate.field_int(body, "nominated_volume_dth", exclusive_minimum=0)
    expected_version = validate.field_int(body, "expected_contract_version")

    contract = validate.resolve_body_fk("StorageContract", contract_id)
    auth.check_contract_ownership(contract, user_id, role)

    gas_day_str = gas_day.isoformat()
    prior = [
        n for n in store.nominations_of_contract(contract["id"])
        if n["gas_day"] == gas_day_str and n["direction"] == direction
        and n["status"] in NON_TERMINAL
    ]
    for existing in prior:
        if store.has_confirmed_ticket(existing["id"]):
            raise ApiError("ERR_INVALID_NOMINATION_STATE",
                           "an actualised nomination may no longer be superseded.")

    if int(expected_version) != int(contract["version"]):
        raise ApiError("ERR_STALE_CONTRACT_VERSION",
                       "expected_contract_version does not match the contract's version.")

    field = store.storage_fields[contract["storage_field_id"]]
    if gas_day_str < contract["term_start_date"] or gas_day_str > contract["term_end_date"]:
        raise ApiError("ERR_GAS_DAY_OUTSIDE_TERM",
                       "gas_day falls outside the contract's term.")
    if store.now() >= store.nomination_cutoff(gas_day):
        raise ApiError("ERR_NOMINATION_WINDOW_CLOSED",
                       "the nomination cutoff for this gas day has passed.")
    if contract["service_class"] == "INTERRUPTIBLE" and direction != field["season"]:
        raise ApiError("ERR_SEASON_DIRECTION_MISMATCH",
                       "interruptible service must nominate with the field's season.")
    if direction == "INJECTION":
        daily_right = D(contract["max_daily_injection_dth"])
        room = D(contract["max_storage_quantity_dth"]) - D(contract["inventory_balance_dth"])
        if D(nominated) > daily_right or D(nominated) > room:
            raise ApiError("ERR_CONTRACT_RIGHTS_EXCEEDED",
                           "nominated_volume_dth exceeds the contract's rights.")
    else:
        if D(nominated) > D(contract["max_daily_withdrawal_dth"]):
            raise ApiError("ERR_CONTRACT_RIGHTS_EXCEEDED",
                           "nominated_volume_dth exceeds the contract's daily withdrawal right.")
    shipper = store.shippers[contract["shipper_id"]]
    if shipper["credit_status"] != "GOOD":
        raise ApiError("ERR_SHIPPER_CREDIT_SUSPENDED", "the shipper's credit is suspended.")

    nomination = store.new_record()
    nomination.update({
        "contract_id": contract["id"],
        "gas_day": gas_day_str,
        "direction": direction,
        "nominated_volume_dth": nominated,
        "confirmed_volume_dth": 0,
        "curtailed_volume_dth": 0,
        "status": "DRAFT",
        "revision_round": 0,
        "superseded_by_nomination_id": None,
        "submitted_at": None,
        "confirmed_at": None,
    })
    store.put("Nomination", nomination)

    for existing in store.sorted_rows(prior):
        existing["status"] = "SUPERSEDED"
        existing["superseded_by_nomination_id"] = nomination["id"]
        store.touch(existing)
    engine.reconcile_contract(contract, force_touch=True)
    return envelope.created(serialize.nomination(nomination))


@bp.get("/nominations")
def list_nominations():
    user_id, role = auth.require(config.SCHEDULE_READ_ROLES)
    limit, offset = validate.pagination()
    contract_id = validate.query_id("contract_id")
    gas_day = validate.query_date("gas_day")
    direction = validate.query_enum("direction", config.DIRECTIONS)
    status = validate.query_enum("status", config.NOMINATION_STATUSES)
    superseded_by = validate.query_id("superseded_by_nomination_id")

    rows = store.values("Nomination")
    visible = auth.visible_contract_ids(user_id, role)
    if visible is not None:
        rows = [row for row in rows if row["contract_id"] in visible]
    rows = filter_eq(rows, "contract_id", contract_id)
    rows = filter_eq(rows, "gas_day", gas_day)
    rows = filter_eq(rows, "direction", direction)
    rows = filter_eq(rows, "status", status)
    rows = filter_eq(rows, "superseded_by_nomination_id", superseded_by)
    return list_result(rows, serialize.nomination, limit, offset)


@bp.get("/nominations/<nomination_id>")
def read_nomination(nomination_id):
    user_id, role = auth.require(config.SCHEDULE_READ_ROLES)
    nomination = validate.resolve_path("Nomination", nomination_id)
    auth.check_contract_ownership(auth.contract_of_nomination(nomination), user_id, role)
    return envelope.object_response(serialize.nomination(nomination))


@bp.post("/nominations/<nomination_id>/submit")
def submit_nomination(nomination_id):
    user_id, role = auth.require([config.ROLE_SHIPPER])
    body = validate.json_body(required=False)
    revised = validate.field_int(body, "nominated_volume_dth", required=False,
                                 exclusive_minimum=0)
    nomination = validate.resolve_path("Nomination", nomination_id)

    if revised is not None and revised > int(nomination["nominated_volume_dth"]):
        raise bad_request("a re-submission may lower nominated_volume_dth but never raise it.")

    contract = auth.contract_of_nomination(nomination)
    auth.check_contract_ownership(contract, user_id, role)

    if nomination["status"] not in ("DRAFT", "CURTAILED"):
        raise ApiError("ERR_INVALID_NOMINATION_STATE",
                       "only a DRAFT or CURTAILED nomination may be submitted.")
    if nomination["status"] == "CURTAILED" and store.has_confirmed_ticket(nomination["id"]):
        raise ApiError("ERR_INVALID_NOMINATION_STATE",
                       "an actualised nomination may not be re-submitted.")
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_CONTRACT_STATE",
                       "the owning contract is not ACTIVE.")

    gas_day = validate.parse_date_string(nomination["gas_day"])
    if store.now() >= store.nomination_cutoff(gas_day):
        raise ApiError("ERR_NOMINATION_WINDOW_CLOSED",
                       "the nomination cutoff for this gas day has passed.")
    if nomination["status"] == "CURTAILED" and int(
            nomination["revision_round"]) >= config.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_NOMINATION_REVISION_LIMIT",
                       "this nomination has exhausted its revision rounds.")
    shipper = store.shippers[contract["shipper_id"]]
    if shipper["credit_status"] != "GOOD":
        raise ApiError("ERR_SHIPPER_CREDIT_SUSPENDED", "the shipper's credit is suspended.")

    resubmission = nomination["status"] == "CURTAILED"
    if revised is not None:
        nomination["nominated_volume_dth"] = revised
    if resubmission:
        nomination["revision_round"] = int(nomination["revision_round"]) + 1
        nomination["confirmed_volume_dth"] = 0
        nomination["curtailed_volume_dth"] = 0
    nomination["status"] = "SUBMITTED"
    nomination["submitted_at"] = store.now()
    store.touch(nomination)
    engine.reconcile_contract(contract)
    return envelope.object_response(serialize.nomination(nomination))


@bp.post("/nominations/<nomination_id>/confirm")
def confirm_nomination(nomination_id):
    auth.require([config.ROLE_SCHEDULING_COORDINATOR])
    validate.json_body(required=False)
    nomination = validate.resolve_path("Nomination", nomination_id)

    if nomination["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_NOMINATION_STATE",
                       "only a SUBMITTED nomination may be confirmed.")
    contract = store.contracts[nomination["contract_id"]]
    field = store.storage_fields[contract["storage_field_id"]]
    if field["field_posture"] == "FROZEN":
        raise ApiError("ERR_FIELD_FROZEN", "no nomination may be confirmed on a frozen field.")
    if field["field_posture"] == "RESTRICTED" and contract["service_class"] == "INTERRUPTIBLE":
        raise ApiError("ERR_INTERRUPTIBLE_RESTRICTED",
                       "interruptible service may not be confirmed on a restricted field.")
    shipper = store.shippers[contract["shipper_id"]]
    if shipper["credit_status"] != "GOOD":
        raise ApiError("ERR_SHIPPER_CREDIT_SUSPENDED", "the shipper's credit is suspended.")

    confirmed, curtailed = engine.nomination_confirm_waterfall(nomination, contract, field)
    nomination["confirmed_volume_dth"] = confirmed
    nomination["curtailed_volume_dth"] = curtailed
    nomination["status"] = "CONFIRMED" if curtailed == 0 else "CURTAILED"
    nomination["confirmed_at"] = store.now()
    store.touch(nomination)
    if curtailed > 0:
        engine.add_ledger(contract, "CURTAILMENT_CREDIT", nomination["gas_day"],
                          -D(curtailed), D(0),
                          "allocation curtailment %s" % nomination["gas_day"])
    engine.reconcile_contract(contract, force_touch=True)
    return envelope.object_response(serialize.nomination(nomination))
