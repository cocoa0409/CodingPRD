"""Route handlers and the endpoint table.

Each entry of ROUTES is (method, flask path, handler, allowed roles, scope spec).
Auth (priority 1), permissions (priority 2) and client scope (priority 2.5) are
applied by the dispatcher before the handler body resolves any resource id.
"""

import db
import rules
import serializers
import middleware
import workflow_one as w1
import workflows as w2
from db import get, put, all_rows, parse_dt, iso
from errors import (
    ApiError,
    ERR_CLIENT_LABORATORY_NOT_FOUND,
    ERR_COURIER_RUN_NOT_FOUND,
    ERR_TEST_CATALOG_ENTRY_NOT_FOUND,
    ERR_SPECIMEN_NOT_FOUND,
    ERR_SEND_OUT_ORDER_NOT_FOUND,
    ERR_ORDER_TEST_LINE_NOT_FOUND,
    ERR_INSTRUMENT_RUN_NOT_FOUND,
    ERR_INTERFACE_BUILD_NOT_FOUND,
    ERR_INTERFACE_MESSAGE_NOT_FOUND,
    ERR_BILLING_LEDGER_NOT_FOUND,
    ERR_UTILIZATION_ADVISORY_NOT_FOUND,
    ERR_ALIQUOT_NOT_FOUND,
    ERR_INVALID_REQUEST,
)

ALL = None  # sentinel: every declared role may call


# ---------------------------------------------------------------------------
# resolution helpers (validation priority 3/4 uses the entity-specific id)
# ---------------------------------------------------------------------------

FINDERS = {
    "client_laboratories": (ERR_CLIENT_LABORATORY_NOT_FOUND, "client laboratory"),
    "courier_runs": (ERR_COURIER_RUN_NOT_FOUND, "courier run"),
    "test_catalog_entries": (ERR_TEST_CATALOG_ENTRY_NOT_FOUND, "test catalog entry"),
    "specimens": (ERR_SPECIMEN_NOT_FOUND, "specimen"),
    "send_out_orders": (ERR_SEND_OUT_ORDER_NOT_FOUND, "send-out order"),
    "order_test_lines": (ERR_ORDER_TEST_LINE_NOT_FOUND, "order test line"),
    "instrument_runs": (ERR_INSTRUMENT_RUN_NOT_FOUND, "instrument run"),
    "interface_builds": (ERR_INTERFACE_BUILD_NOT_FOUND, "interface build"),
    "result_interface_messages": (ERR_INTERFACE_MESSAGE_NOT_FOUND, "result interface message"),
    "billing_ledgers": (ERR_BILLING_LEDGER_NOT_FOUND, "billing ledger"),
    "utilization_advisories": (ERR_UTILIZATION_ADVISORY_NOT_FOUND, "utilization advisory"),
}


def must(kind, row_id):
    row = get(kind, row_id)
    if row is None:
        error_id, label = FINDERS[kind]
        raise ApiError(error_id, "The %s id does not resolve." % (label,))
    return row


def body_client_id(body, field="client_laboratory_id"):
    return body.get(field)


# ---------------------------------------------------------------------------
# list helpers
# ---------------------------------------------------------------------------

def list_rows(kind, query, filters):
    rows = all_rows(kind)
    for param, field in filters:
        wanted = query.get(param)
        if wanted is None or wanted == "":
            continue
        rows = [r for r in rows if str(r.get(field)) == str(wanted)]
    rows = middleware.sort_by_created(rows)
    limit, offset = middleware.pagination_args(query)
    window, meta = middleware.paginate(rows, limit, offset)
    return window, meta


# ---------------------------------------------------------------------------
# ClientLaboratory
# ---------------------------------------------------------------------------

def _client_scope_from_body(params, body):
    """Scope for a create endpoint: the body names the acting client."""
    return body_client_id(body)


def _client_scope_from_path(params, body):
    """Scope for a single-client endpoint: the path segment names the client."""
    return params.get("id")


def _scope_from_order(params, body):
    order = get("send_out_orders", params.get("id"))
    if order is None:
        return None
    return order.get("client_laboratory_id")


def h_clock_set(params, body, actor):
    value = body.get("current_utc")
    if value is None:
        raise ApiError(ERR_INVALID_REQUEST, "current_utc is required.")
    w1.set_clock(value)
    return {}


def h_client_create(params, body, actor):
    for field in ("name", "clia_number", "client_type", "state_code"):
        if body.get(field) in (None, ""):
            raise ApiError(ERR_INVALID_REQUEST, "%s is required." % (field,))
    clia = body.get("clia_number")
    for other in all_rows("client_laboratories"):
        if other.get("clia_number") == clia:
            # PRD section 3.1: a reused CLIA number reports ERR_INVALID_REQUEST
            # but at HTTP 409, because it collides with an existing resource.
            raise ApiError(
                ERR_INVALID_REQUEST,
                "clia_number must be unique across non-deleted clients.",
                http_status=409,
            )
    credit_limit = body.get("credit_limit_cents", 500000)
    row = {
        "name": body.get("name"),
        "clia_number": clia,
        "client_type": body.get("client_type"),
        "state_code": body.get("state_code"),
        "billing_arrangement": body.get("billing_arrangement") or "CLIENT",
        "credit_limit_cents": int(credit_limit),
        "status": "PENDING_ONBOARDING",
        "onboarding_status": "DOCUMENTS_PENDING",
        "interface_status": "NOT_BUILT",
        "requirement_notes_published_at": None,
        "outstanding_balance_cents": 0,
        "billable_line_count": 0,
        "forward_utilization_score": 0,
        "settled_utilization_score": 0,
        "utilization_flag": False,
    }
    db.stamp_common(row, "ClientLaboratory")
    put("client_laboratories", row)
    return serializers.render("client_laboratories", row)


def h_client_list(params, body, actor):
    return _page("client_laboratories", params, [("status", "status"), ("state_code", "state_code")])


def h_client_get(params, body, actor):
    row = must("client_laboratories", params.get("id"))
    return serializers.render("client_laboratories", row)


def h_client_publish_requirements(params, body, actor):
    row = must("client_laboratories", params.get("id"))
    w1.engine_client_publish_requirements(row)
    return serializers.render("client_laboratories", row)


def h_client_activate(params, body, actor):
    row = must("client_laboratories", params.get("id"))
    w1.engine_client_activate(row)
    return serializers.render("client_laboratories", row)


def h_client_suspend(params, body, actor):
    row = must("client_laboratories", params.get("id"))
    w1.engine_client_suspend(row)
    return serializers.render("client_laboratories", row)


def h_client_reinstate(params, body, actor):
    row = must("client_laboratories", params.get("id"))
    w1.engine_client_reinstate(row)
    return serializers.render("client_laboratories", row)


def h_client_settle_balance(params, body, actor):
    row = must("client_laboratories", params.get("id"))
    if body.get("settlement_amount_cents") is None:
        raise ApiError(ERR_INVALID_REQUEST, "settlement_amount_cents is required.")
    w1.engine_client_settle_balance(row, body.get("settlement_amount_cents"))
    return serializers.render("client_laboratories", row)


def h_client_deactivate(params, body, actor):
    row = must("client_laboratories", params.get("id"))
    w1.engine_client_deactivate(row)
    return serializers.render("client_laboratories", row)


# ---------------------------------------------------------------------------
# CourierRun
# ---------------------------------------------------------------------------

def _leg_state_as_of(run, now):
    """The leg's state once the PRD 2.4 clock-derived advances are applied."""
    status = run.get("status")
    if status not in ("PLANNED", "DISPATCHED", "IN_TRANSIT"):
        return status
    departure = parse_dt(run.get("scheduled_departure_at"))
    delivery = parse_dt(run.get("scheduled_delivery_at"))
    if delivery is not None and delivery <= now:
        return "COMPLETED"
    if departure is not None and departure <= now:
        return "IN_TRANSIT"
    return "PLANNED"


def h_courier_create(params, body, actor):
    client = must("client_laboratories", body.get("client_laboratory_id"))
    w1.check_occ(body, "expected_client_laboratory_version", client)
    for field in (
        "route_code",
        "origin_city",
        "destination_city",
        "vehicle_id",
        "scheduled_departure_at",
        "scheduled_arrival_at",
        "scheduled_pickup_at",
        "scheduled_delivery_at",
        "temperature_control_mode",
    ):
        if body.get(field) in (None, ""):
            raise ApiError(ERR_INVALID_REQUEST, "%s is required." % (field,))
    pickup = parse_dt(body.get("scheduled_pickup_at"))
    delivery = parse_dt(body.get("scheduled_delivery_at"))
    if pickup is None or delivery is None:
        raise ApiError(ERR_INVALID_REQUEST, "The pickup and delivery instants must be ISO 8601.")
    vehicle = body.get("vehicle_id")
    now = db.now()
    for other in all_rows("courier_runs"):
        if other.get("vehicle_id") != vehicle:
            continue
        # PRD 2.10: only a leg "in PLANNED, DISPATCHED or IN_TRANSIT status" can
        # conflict, and PRD 2.4 makes the clock authoritative for the scheduled
        # advance, so a leg whose delivery instant the clock has already passed no
        # longer occupies the vehicle.
        if _leg_state_as_of(other, now) not in ("PLANNED", "DISPATCHED", "IN_TRANSIT"):
            continue
        # Inclusive start, exclusive end: proper overlap only.
        other_pickup = parse_dt(other.get("scheduled_pickup_at"))
        other_delivery = parse_dt(other.get("scheduled_delivery_at"))
        if other_pickup is None or other_delivery is None:
            continue
        if pickup < other_delivery and other_pickup < delivery:
            from errors import ERR_COURIER_LEG_OVERLAP

            raise ApiError(
                ERR_COURIER_LEG_OVERLAP,
                "The leg properly overlaps another live leg on the same vehicle.",
            )
    route_code = body.get("route_code")
    earlier = 0
    for other in all_rows("courier_runs"):
        if other.get("route_code") == route_code:
            earlier += 1
    base = rules.dec(body.get("base_transit_minutes", 0))
    increment = rules.dec(body.get("per_leg_increment_minutes", 0))
    row = {
        "client_laboratory_id": client["id"],
        "route_code": route_code,
        "origin_city": body.get("origin_city"),
        "destination_city": body.get("destination_city"),
        "vehicle_id": vehicle,
        "scheduled_departure_at": parse_dt(body.get("scheduled_departure_at")),
        "scheduled_arrival_at": parse_dt(body.get("scheduled_arrival_at")),
        "scheduled_pickup_at": pickup,
        "scheduled_delivery_at": delivery,
        "temperature_control_mode": body.get("temperature_control_mode"),
        "specimen_count": 0,
        "transit_allowance_minutes": rules.num(base + increment * earlier)
        if earlier
        else rules.num(base if base else 0),
        "status": "PLANNED",
    }
    db.stamp_common(row, "CourierRun")
    put("courier_runs", row)
    from db import touch

    touch(client)
    return serializers.render("courier_runs", row)


def h_courier_list(params, body, actor):
    return _page(
        "courier_runs",
        params,
        [("client_laboratory_id", "client_laboratory_id"), ("status", "status")],
    )


def h_courier_get(params, body, actor):
    row = must("courier_runs", params.get("id"))
    return serializers.render("courier_runs", row)


def h_courier_dispatch(params, body, actor):
    row = must("courier_runs", params.get("id"))
    w1.engine_courier_dispatch(row)
    return serializers.render("courier_runs", row)


def h_courier_recall(params, body, actor):
    row = must("courier_runs", params.get("id"))
    w1.engine_courier_recall(row)
    return serializers.render("courier_runs", row)


def h_courier_arrive(params, body, actor):
    row = must("courier_runs", params.get("id"))
    w1.engine_courier_arrive(row)
    return serializers.render("courier_runs", row)


# ---------------------------------------------------------------------------
# TestCatalogEntry
# ---------------------------------------------------------------------------

def h_catalog_create(params, body, actor):
    # Required shape. The four interpretation limits and client_price_cents are
    # deliberately absent from this list: PRD section 3.4 states that any of the
    # four limits may be null, and a null limit disables that side of flagging
    # rather than being treated as zero.
    for field in (
        "test_code",
        "test_name",
        "test_category",
        "method",
        "required_specimen_type",
        "container_type",
        "min_volume_ml",
        "transport_temperature",
        "stability_hours_ambient",
        "stability_hours_refrigerated",
        "stability_hours_frozen",
        "base_tat_hours",
        "list_price_cents",
        "floor_price_cents",
        "reflex_condition",
    ):
        if body.get(field) in (None, ""):
            raise ApiError(ERR_INVALID_REQUEST, "%s is required." % (field,))
    # PRD section 2.11: "a field carrying a value outside its enumerated set ...
    # is a request-shape failure reported as ERR_INVALID_REQUEST (HTTP 400)."
    # PRD section 2.5 draws transport_temperature from exactly AMBIENT,
    # REFRIGERATED and FROZEN; PRD section 3.4 draws test_category from exactly
    # ROUTINE, ESOTERIC and GENETIC.
    if body.get("transport_temperature") not in ("AMBIENT", "REFRIGERATED", "FROZEN"):
        raise ApiError(ERR_INVALID_REQUEST, "transport_temperature is outside its enumerated set.")
    if body.get("test_category") not in ("ROUTINE", "ESOTERIC", "GENETIC"):
        raise ApiError(ERR_INVALID_REQUEST, "test_category is outside its enumerated set.")
    if body.get("reflex_condition") not in ("ALWAYS", "RESULT_ABOVE_HIGH", "RESULT_BELOW_LOW", "NONE"):
        raise ApiError(ERR_INVALID_REQUEST, "reflex_condition is outside its enumerated set.")
    # The reflex block is only meaningful when a reflex actually applies.
    if body.get("reflex_condition") != "NONE":
        for field in ("reflex_test_code", "reflex_within_hours", "reflex_min_remaining_hours"):
            if body.get(field) in (None, ""):
                raise ApiError(ERR_INVALID_REQUEST, "%s is required." % (field,))
    code = body.get("test_code")
    for other in all_rows("test_catalog_entries"):
        if other.get("test_code") == code and other.get("status") != "WITHDRAWN":
            from errors import ERR_DUPLICATE_TEST_CODE

            raise ApiError(ERR_DUPLICATE_TEST_CODE, "test_code is already carried by a live entry.")
    row = {
        "test_code": code,
        "test_name": body.get("test_name"),
        "test_category": body.get("test_category"),
        "method": body.get("method"),
        "required_specimen_type": body.get("required_specimen_type"),
        "container_type": body.get("container_type"),
        "min_volume_ml": body.get("min_volume_ml"),
        "transport_temperature": body.get("transport_temperature"),
        "stability_hours_ambient": body.get("stability_hours_ambient"),
        "stability_hours_refrigerated": body.get("stability_hours_refrigerated"),
        "stability_hours_frozen": body.get("stability_hours_frozen"),
        "base_tat_hours": body.get("base_tat_hours"),
        "list_price_cents": body.get("list_price_cents"),
        "client_price_cents": body.get("client_price_cents"),
        "floor_price_cents": body.get("floor_price_cents"),
        "reference_low": body.get("reference_low"),
        "reference_high": body.get("reference_high"),
        "critical_value_low": body.get("critical_value_low"),
        "critical_value_high": body.get("critical_value_high"),
        "reflex_test_code": body.get("reflex_test_code"),
        "reflex_condition": body.get("reflex_condition"),
        "reflex_within_hours": body.get("reflex_within_hours"),
        "reflex_min_remaining_hours": body.get("reflex_min_remaining_hours"),
        "is_utilization_managed": bool(body.get("is_utilization_managed", False)),
        "status": "DRAFT",
    }
    db.stamp_common(row, "TestCatalogEntry")
    put("test_catalog_entries", row)
    return serializers.render("test_catalog_entries", row)


def h_catalog_list(params, body, actor):
    return _page(
        "test_catalog_entries",
        params,
        [("status", "status"), ("test_category", "test_category")],
    )


def h_catalog_get(params, body, actor):
    row = must("test_catalog_entries", params.get("id"))
    return serializers.render("test_catalog_entries", row)


def h_catalog_publish(params, body, actor):
    row = must("test_catalog_entries", params.get("id"))
    w1.engine_catalog_publish(row)
    return serializers.render("test_catalog_entries", row)


def h_catalog_deprecate(params, body, actor):
    row = must("test_catalog_entries", params.get("id"))
    w1.engine_catalog_deprecate(row)
    return serializers.render("test_catalog_entries", row)


def h_catalog_withdraw(params, body, actor):
    row = must("test_catalog_entries", params.get("id"))
    w1.engine_catalog_withdraw(row)
    return serializers.render("test_catalog_entries", row)


# ---------------------------------------------------------------------------
# Specimen
# ---------------------------------------------------------------------------

def h_specimen_create(params, body, actor):
    client = must("client_laboratories", body.get("client_laboratory_id"))
    courier = must("courier_runs", body.get("courier_run_id"))
    accession_number = body.get("accession_number")
    w2._check_accession_unique(accession_number)
    collected = parse_dt(body.get("collection_at"))
    received = parse_dt(body.get("received_at"))
    if collected is None or received is None:
        raise ApiError(ERR_INVALID_REQUEST, "collection_at and received_at are required.")
    if collected > received:
        from errors import ERR_INVALID_TEMPORAL_WINDOW

        raise ApiError(
            ERR_INVALID_TEMPORAL_WINDOW,
            "collection_at must be at or before received_at.",
        )
    condition = body.get("condition")
    condition_reason = body.get("condition_reason_code")
    if condition != "ACCEPTABLE" and not condition_reason:
        from errors import ERR_SPECIMEN_NOT_ACCEPTABLE

        raise ApiError(
            ERR_SPECIMEN_NOT_ACCEPTABLE,
            "A non-ACCEPTABLE condition requires a condition_reason_code.",
        )
    from datetime import timedelta

    requested = parse_dt(body.get("client_requested_at"))
    if requested is not None and requested > db.now():
        from errors import ERR_INVALID_TEMPORAL_WINDOW

        raise ApiError(ERR_INVALID_TEMPORAL_WINDOW, "client_requested_at is in the future.")

    w2.require_intake_admissible(client)

    row = {
        "client_laboratory_id": client["id"],
        "courier_run_id": courier["id"],
        "aliquot_parent_id": body.get("aliquot_parent_id"),
        "accession_number": accession_number,
        "patient_mrn": body.get("patient_mrn"),
        "specimen_type": body.get("specimen_type"),
        "container_type": body.get("container_type"),
        "volume_ml": body.get("volume_ml"),
        "aliquot_volume_ml": body.get("aliquot_volume_ml"),
        "collection_at": collected,
        "received_at": received,
        "transport_temperature": body.get("transport_temperature"),
        "condition": condition,
        "condition_reason_code": condition_reason,
        "rejection_reason_code": None,
        "status": "RECEIVED",
    }
    db.stamp_common(row, "Specimen")
    put("specimens", row)
    courier["specimen_count"] = sum(
        1 for s in all_rows("specimens") if s.get("courier_run_id") == courier["id"]
    )
    from db import touch

    touch(courier)
    return serializers.render("specimens", row)


def h_specimen_list(params, body, actor):
    return _page(
        "specimens",
        params,
        [
            ("client_laboratory_id", "client_laboratory_id"),
            ("courier_run_id", "courier_run_id"),
            ("aliquot_parent_id", "aliquot_parent_id"),
            ("status", "status"),
        ],
    )


def h_specimen_get(params, body, actor):
    row = must("specimens", params.get("id"))
    return serializers.render("specimens", row)


def h_specimen_accession(params, body, actor):
    row = must("specimens", params.get("id"))
    w2.engine_specimen_accession(row)
    return serializers.render("specimens", row)


def h_specimen_begin_testing(params, body, actor):
    row = must("specimens", params.get("id"))
    order = w2._order_for_specimen(row["id"])
    section = None
    if order is not None:
        for line in rules.lines_of_order(order["id"]):
            if line.get("line_status") == "PENDING":
                entry = get("test_catalog_entries", line.get("test_catalog_entry_id"))
                if entry is not None:
                    section = entry.get("section") or entry.get("method")
                break
    w2.engine_specimen_begin_testing(row, section)
    return serializers.render("specimens", row)


def h_specimen_reject(params, body, actor):
    row = must("specimens", params.get("id"))
    w2.engine_specimen_reject(row, body.get("rejection_reason_code"))
    return serializers.render("specimens", row)


def h_specimen_aliquot_create(params, body, actor):
    parent = must("specimens", params.get("id"))
    child = w2.engine_specimen_create_aliquot(parent, body)
    return serializers.render("specimens", child)


def h_specimen_aliquot_delete(params, body, actor):
    parent = must("specimens", params.get("id"))
    child = get("specimens", params.get("aliquot_id"))
    if child is None:
        raise ApiError(ERR_ALIQUOT_NOT_FOUND, "The aliquot id does not resolve.")
    w2.engine_specimen_delete_aliquot(parent, child)
    return serializers.render("specimens", parent)


# ---------------------------------------------------------------------------
# SendOutOrder
# ---------------------------------------------------------------------------

def h_order_create(params, body, actor):
    order = w2.engine_order_create(body, actor)
    return serializers.render("send_out_orders", order)


def h_order_list(params, body, actor):
    return _page(
        "send_out_orders",
        params,
        [
            ("client_laboratory_id", "client_laboratory_id"),
            ("specimen_id", "specimen_id"),
            ("reflex_source_order_id", "reflex_source_order_id"),
            ("order_status", "order_status"),
        ],
    )


def h_order_get(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    return serializers.render("send_out_orders", row)


def h_order_accession(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w2.engine_order_accession(row)
    return serializers.render("send_out_orders", row)


def h_order_enter_results(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w2.engine_order_enter_results(row, body, actor)
    return serializers.render("send_out_orders", row)


def h_order_release_results(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w2.engine_order_release_results(row, body, actor)
    return serializers.render("send_out_orders", row)


def h_order_cancel(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w1.engine_order_cancel(row)
    return serializers.render("send_out_orders", row)


def h_order_hold(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w1.engine_order_hold(row)
    return serializers.render("send_out_orders", row)


def h_order_release_hold(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w1.engine_order_release_hold(row)
    return serializers.render("send_out_orders", row)


def h_order_repeat_test(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w1.engine_order_repeat_test(row, body.get("order_test_line_id"))
    return serializers.render("send_out_orders", row)


def h_order_add_on_test(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w1.engine_order_add_on_test(row, body)
    return serializers.render("send_out_orders", row)


def h_order_reflex_test(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w1.engine_order_reflex_test(row, body)
    return serializers.render("send_out_orders", row)


def h_order_reflex_cancel(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w1.engine_order_reflex_cancel(row)
    return serializers.render("send_out_orders", row)


def h_order_charge(params, body, actor):
    row = must("send_out_orders", params.get("id"))
    w1.engine_order_charge(row)
    return serializers.render("send_out_orders", row)


# ---------------------------------------------------------------------------
# OrderTestLine
# ---------------------------------------------------------------------------

def h_line_list(params, body, actor):
    return _page(
        "order_test_lines",
        params,
        [
            ("send_out_order_id", "send_out_order_id"),
            ("test_catalog_entry_id", "test_catalog_entry_id"),
            ("line_status", "line_status"),
        ],
    )


def h_line_get(params, body, actor):
    row = must("order_test_lines", params.get("id"))
    return serializers.render("order_test_lines", row)


# ---------------------------------------------------------------------------
# InstrumentRun
# ---------------------------------------------------------------------------

def h_instrument_create(params, body, actor):
    row = w1.engine_instrument_run_create(body)
    return serializers.render("instrument_runs", row)


def h_instrument_list(params, body, actor):
    return _page(
        "instrument_runs",
        params,
        [
            ("test_catalog_entry_id", "test_catalog_entry_id"),
            ("instrument_code", "instrument_code"),
            ("run_status", "run_status"),
        ],
    )


def h_instrument_get(params, body, actor):
    row = must("instrument_runs", params.get("id"))
    return serializers.render("instrument_runs", row)


def h_instrument_abort(params, body, actor):
    row = must("instrument_runs", params.get("id"))
    w1.engine_instrument_run_abort(row)
    return serializers.render("instrument_runs", row)


def h_instrument_rebook(params, body, actor):
    row = must("instrument_runs", params.get("id"))
    w1.engine_instrument_run_rebook(row, body)
    return serializers.render("instrument_runs", row)


# ---------------------------------------------------------------------------
# InterfaceBuild
# ---------------------------------------------------------------------------

def h_build_create(params, body, actor):
    row = w1.engine_build_create(body)
    # PRD 3.1: interface_status "is derived on every write from the highest-status
    # interface build belonging to the client", and PRD 3.12's opening act
    # "triggers a recomputation of the owning client's interface_status".
    client = get("client_laboratories", row.get("client_laboratory_id"))
    if client is not None:
        rules.recompute_interface_status(client)
    return serializers.render("interface_builds", row)


def h_build_list(params, body, actor):
    return _page(
        "interface_builds",
        params,
        [("client_laboratory_id", "client_laboratory_id"), ("status", "status")],
    )


def h_build_get(params, body, actor):
    row = must("interface_builds", params.get("id"))
    return serializers.render("interface_builds", row)


def h_build_start(params, body, actor):
    row = must("interface_builds", params.get("id"))
    w1.engine_build_start(row)
    return serializers.render("interface_builds", row)


def h_build_certify(params, body, actor):
    row = must("interface_builds", params.get("id"))
    w1.engine_build_certify(row)
    return serializers.render("interface_builds", row)


def h_build_supersede(params, body, actor):
    row = must("interface_builds", params.get("id"))
    w1.engine_build_supersede(row)
    return serializers.render("interface_builds", row)


def h_build_retire(params, body, actor):
    row = must("interface_builds", params.get("id"))
    w1.engine_build_retire(row)
    return serializers.render("interface_builds", row)


def h_build_patch(params, body, actor):
    row = must("interface_builds", params.get("id"))
    w1.engine_build_patch(row, body)
    return serializers.render("interface_builds", row)


# ---------------------------------------------------------------------------
# ResultInterfaceMessage
# ---------------------------------------------------------------------------

def h_message_create(params, body, actor):
    row = w2.engine_message_create(body, actor)
    return serializers.render("result_interface_messages", row)


def h_message_list(params, body, actor):
    return _page(
        "result_interface_messages",
        params,
        [
            ("send_out_order_id", "send_out_order_id"),
            ("interface_build_id", "interface_build_id"),
            ("status", "status"),
        ],
    )


def h_message_get(params, body, actor):
    row = must("result_interface_messages", params.get("id"))
    return serializers.render("result_interface_messages", row)


def h_message_validate(params, body, actor):
    row = must("result_interface_messages", params.get("id"))
    w2.engine_message_validate(row)
    return serializers.render("result_interface_messages", row)


def h_message_transmit(params, body, actor):
    row = must("result_interface_messages", params.get("id"))
    w2.engine_message_transmit(row)
    return serializers.render("result_interface_messages", row)


def h_message_fail(params, body, actor):
    row = must("result_interface_messages", params.get("id"))
    w2.engine_message_fail(row)
    return serializers.render("result_interface_messages", row)


def h_message_hold(params, body, actor):
    row = must("result_interface_messages", params.get("id"))
    w2.engine_message_hold(row)
    return serializers.render("result_interface_messages", row)


def h_message_release_hold(params, body, actor):
    row = must("result_interface_messages", params.get("id"))
    w2.engine_message_release_hold(row)
    return serializers.render("result_interface_messages", row)


def h_message_acknowledge(params, body, actor):
    row = must("result_interface_messages", params.get("id"))
    w2.engine_message_acknowledge(row, body.get("control_id"))
    return serializers.render("result_interface_messages", row)


# ---------------------------------------------------------------------------
# BillingLedger
# ---------------------------------------------------------------------------

def h_ledger_create(params, body, actor):
    row = w2.engine_ledger_create(body)
    return serializers.render("billing_ledgers", row)


def h_ledger_list(params, body, actor):
    return _page(
        "billing_ledgers",
        params,
        [("client_laboratory_id", "client_laboratory_id"), ("status", "status")],
    )


def h_ledger_get(params, body, actor):
    row = must("billing_ledgers", params.get("id"))
    return serializers.render("billing_ledgers", row)


def h_ledger_void(params, body, actor):
    row = must("billing_ledgers", params.get("id"))
    w2.engine_ledger_void_charges(row, body)
    return serializers.render("billing_ledgers", row)


# ---------------------------------------------------------------------------
# UtilizationAdvisory
# ---------------------------------------------------------------------------

def h_advisory_create(params, body, actor):
    row = w2.engine_advisory_create(body)
    return serializers.render("utilization_advisories", row)


def h_advisory_list(params, body, actor):
    return _page(
        "utilization_advisories",
        params,
        [
            ("client_laboratory_id", "client_laboratory_id"),
            ("test_catalog_entry_id", "test_catalog_entry_id"),
            ("source_order_id", "source_order_id"),
            ("status", "status"),
        ],
    )


def h_advisory_get(params, body, actor):
    row = must("utilization_advisories", params.get("id"))
    return serializers.render("utilization_advisories", row)


def h_advisory_acknowledge(params, body, actor):
    row = must("utilization_advisories", params.get("id"))
    w2.engine_advisory_acknowledge(row)
    return serializers.render("utilization_advisories", row)


def h_advisory_dismiss(params, body, actor):
    row = must("utilization_advisories", params.get("id"))
    w2.engine_advisory_dismiss(row)
    return serializers.render("utilization_advisories", row)


def h_advisory_escalate(params, body, actor):
    row = must("utilization_advisories", params.get("id"))
    w2.engine_advisory_escalate(row)
    return serializers.render("utilization_advisories", row)


def _page(kind, params, filters):
    window, meta = list_rows(kind, params, filters)
    if not window:
        # An empty window still answers with an array and its pagination block
        # (PRD section 2.3: "the meta object carries four pagination fields").
        requested = params.get("limit")
        meta.setdefault(
            "limit",
            int(requested) if str(requested or "").isdigit() else 10,
        )
        meta.setdefault(
            "offset",
            int(params.get("offset") or 0)
            if str(params.get("offset") or "0").lstrip("-").isdigit() else 0,
        )
    rendered = [serializers.render(kind, r) for r in window]
    return {"_list": rendered, "_meta": meta}


# ---------------------------------------------------------------------------
# the endpoint table (PRD section 4)
# ---------------------------------------------------------------------------

P = "/reference-lab"

ROUTES = [
    # logical clock
    ("POST", "/_clock/set_current_utc", h_clock_set, ["ReferenceLabOperations"], None),
    # ClientLaboratory
    ("POST", P + "/client-laboratories", h_client_create, ["ReferenceLabOperations"], None),
    ("GET", P + "/client-laboratories", h_client_list,
     ["ReferenceLabOperations", "LabBillingSpecialist", "UtilizationReviewer", "LabClientAdmin"], None),
    ("GET", P + "/client-laboratories/<string:id>", h_client_get,
     ["ReferenceLabOperations", "LabBillingSpecialist", "UtilizationReviewer", "LabClientAdmin"],
     _client_scope_from_path),
    ("POST", P + "/client-laboratories/<string:id>/publish-requirements",
     h_client_publish_requirements, ["LabClientAdmin", "ReferenceLabOperations"], _client_scope_from_path),
    ("POST", P + "/client-laboratories/<string:id>/activate", h_client_activate,
     ["LabClientAdmin", "ReferenceLabOperations"], None),
    ("POST", P + "/client-laboratories/<string:id>/suspend", h_client_suspend,
     ["ReferenceLabOperations"], None),
    ("POST", P + "/client-laboratories/<string:id>/reinstate", h_client_reinstate,
     ["LabClientAdmin", "ReferenceLabOperations"], None),
    ("POST", P + "/client-laboratories/<string:id>/settle-balance", h_client_settle_balance,
     ["LabBillingSpecialist"], None),
    ("POST", P + "/client-laboratories/<string:id>/deactivate", h_client_deactivate,
     ["ReferenceLabOperations"], None),
    # CourierRun
    ("POST", P + "/courier-runs", h_courier_create, ["CourierCoordinator"], None),
    ("GET", P + "/courier-runs", h_courier_list,
     ["CourierCoordinator", "AccessioningTechnologist", "ReferenceLabOperations", "LabClientAdmin"], None),
    ("GET", P + "/courier-runs/<string:id>", h_courier_get,
     ["CourierCoordinator", "AccessioningTechnologist", "ReferenceLabOperations", "LabClientAdmin"], None),
    ("POST", P + "/courier-runs/<string:id>/dispatch", h_courier_dispatch,
     ["CourierCoordinator"], None),
    ("POST", P + "/courier-runs/<string:id>/recall", h_courier_recall, ["CourierCoordinator"], None),
    ("POST", P + "/courier-runs/<string:id>/arrive", h_courier_arrive,
     ["AccessioningTechnologist"], None),
    # TestCatalogEntry
    ("POST", P + "/test-catalog-entries", h_catalog_create,
     ["LabClientAdmin", "ReferenceLabOperations"], None),
    ("GET", P + "/test-catalog-entries", h_catalog_list,
     ["LabClientAdmin", "InterfaceAnalyst", "ReferenceLabOperations", "AccessioningTechnologist",
      "MedicalTechnologist", "Pathologist", "LabBillingSpecialist", "UtilizationReviewer",
      "CourierCoordinator", "MedicalDirector"], None),
    ("GET", P + "/test-catalog-entries/<string:id>", h_catalog_get,
     ["LabClientAdmin", "InterfaceAnalyst", "ReferenceLabOperations", "AccessioningTechnologist",
      "MedicalTechnologist", "Pathologist", "LabBillingSpecialist", "UtilizationReviewer",
      "CourierCoordinator", "MedicalDirector"], None),
    ("POST", P + "/test-catalog-entries/<string:id>/publish", h_catalog_publish,
     ["LabClientAdmin"], None),
    ("POST", P + "/test-catalog-entries/<string:id>/deprecate", h_catalog_deprecate,
     ["LabClientAdmin"], None),
    ("POST", P + "/test-catalog-entries/<string:id>/withdraw", h_catalog_withdraw,
     ["ReferenceLabOperations"], None),
    # Specimen
    ("POST", P + "/specimens", h_specimen_create,
     ["AccessioningTechnologist", "CourierCoordinator"], None),
    ("GET", P + "/specimens", h_specimen_list,
     ["AccessioningTechnologist", "MedicalTechnologist", "Pathologist", "ReferenceLabOperations"], None),
    ("GET", P + "/specimens/<string:id>", h_specimen_get,
     ["AccessioningTechnologist", "MedicalTechnologist", "Pathologist", "ReferenceLabOperations"], None),
    ("POST", P + "/specimens/<string:id>/accession", h_specimen_accession,
     ["AccessioningTechnologist"], None),
    ("POST", P + "/specimens/<string:id>/begin-testing", h_specimen_begin_testing,
     ["MedicalTechnologist"], None),
    ("POST", P + "/specimens/<string:id>/reject", h_specimen_reject,
     ["AccessioningTechnologist"], None),
    ("POST", P + "/specimens/<string:id>/aliquots", h_specimen_aliquot_create,
     ["AccessioningTechnologist"], None),
    ("DELETE", P + "/specimens/<string:id>/aliquots/<string:aliquot_id>", h_specimen_aliquot_delete,
     ["AccessioningTechnologist"], None),
    # SendOutOrder
    ("POST", P + "/send-out-orders", h_order_create,
     ["AccessioningTechnologist", "LabClientAdmin", "MedicalDirector"], _client_scope_from_body),
    ("GET", P + "/send-out-orders", h_order_list,
     ["AccessioningTechnologist", "MedicalTechnologist", "Pathologist", "InterfaceAnalyst",
      "LabBillingSpecialist", "ReferenceLabOperations", "UtilizationReviewer", "MedicalDirector",
      "LabClientAdmin"], None),
    ("GET", P + "/send-out-orders/<string:id>", h_order_get,
     ["AccessioningTechnologist", "MedicalTechnologist", "Pathologist", "InterfaceAnalyst",
      "LabBillingSpecialist", "ReferenceLabOperations", "UtilizationReviewer", "MedicalDirector",
      "LabClientAdmin"], None),
    ("POST", P + "/send-out-orders/<string:id>/accession", h_order_accession,
     ["AccessioningTechnologist"], None),
    ("POST", P + "/send-out-orders/<string:id>/enter-results", h_order_enter_results,
     ["MedicalTechnologist"], None),
    ("POST", P + "/send-out-orders/<string:id>/release-results", h_order_release_results,
     ["Pathologist"], None),
    ("POST", P + "/send-out-orders/<string:id>/cancel", h_order_cancel,
     ["ReferenceLabOperations", "LabClientAdmin"], _scope_from_order),
    ("POST", P + "/send-out-orders/<string:id>/hold", h_order_hold,
     ["ReferenceLabOperations"], None),
    ("POST", P + "/send-out-orders/<string:id>/release-hold", h_order_release_hold,
     ["LabBillingSpecialist"], None),
    ("POST", P + "/send-out-orders/<string:id>/repeat-test", h_order_repeat_test,
     ["Pathologist"], None),
    ("POST", P + "/send-out-orders/<string:id>/order-add-on-test", h_order_add_on_test,
     ["AccessioningTechnologist"], None),
    ("POST", P + "/send-out-orders/<string:id>/order-reflex-test", h_order_reflex_test,
     ["Pathologist"], None),
    ("POST", P + "/send-out-orders/<string:id>/reflex-cancel", h_order_reflex_cancel,
     ["Pathologist"], None),
    ("POST", P + "/send-out-orders/<string:id>/charge", h_order_charge,
     ["LabBillingSpecialist"], None),
    # OrderTestLine
    ("GET", P + "/order-test-lines", h_line_list,
     ["MedicalTechnologist", "Pathologist", "LabBillingSpecialist", "UtilizationReviewer",
      "ReferenceLabOperations", "AccessioningTechnologist", "MedicalDirector"], None),
    ("GET", P + "/order-test-lines/<string:id>", h_line_get,
     ["MedicalTechnologist", "Pathologist", "LabBillingSpecialist", "UtilizationReviewer",
      "ReferenceLabOperations", "AccessioningTechnologist", "MedicalDirector"], None),
    # InstrumentRun
    ("POST", P + "/instrument-runs", h_instrument_create, ["MedicalTechnologist"], None),
    ("GET", P + "/instrument-runs", h_instrument_list,
     ["MedicalTechnologist", "ReferenceLabOperations"], None),
    ("GET", P + "/instrument-runs/<string:id>", h_instrument_get,
     ["MedicalTechnologist", "ReferenceLabOperations"], None),
    ("POST", P + "/instrument-runs/<string:id>/abort", h_instrument_abort,
     ["MedicalTechnologist"], None),
    ("PATCH", P + "/instrument-runs/<string:id>", h_instrument_rebook,
     ["MedicalTechnologist"], None),
    # InterfaceBuild
    ("POST", P + "/interface-builds", h_build_create, ["InterfaceAnalyst"], None),
    ("GET", P + "/interface-builds", h_build_list,
     ["InterfaceAnalyst", "ReferenceLabOperations", "LabClientAdmin"], None),
    ("GET", P + "/interface-builds/<string:id>", h_build_get,
     ["InterfaceAnalyst", "ReferenceLabOperations", "LabClientAdmin"], None),
    ("POST", P + "/interface-builds/<string:id>/start-build", h_build_start,
     ["InterfaceAnalyst"], None),
    ("POST", P + "/interface-builds/<string:id>/certify", h_build_certify,
     ["InterfaceAnalyst"], None),
    ("POST", P + "/interface-builds/<string:id>/supersede", h_build_supersede,
     ["InterfaceAnalyst"], None),
    ("POST", P + "/interface-builds/<string:id>/retire", h_build_retire,
     ["InterfaceAnalyst"], None),
    ("PATCH", P + "/interface-builds/<string:id>", h_build_patch, ["InterfaceAnalyst"], None),
    # ResultInterfaceMessage
    ("POST", P + "/result-interface-messages", h_message_create,
     ["InterfaceAnalyst", "MedicalTechnologist"], None),
    ("GET", P + "/result-interface-messages", h_message_list,
     ["InterfaceAnalyst", "ReferenceLabOperations"], None),
    ("GET", P + "/result-interface-messages/<string:id>", h_message_get,
     ["InterfaceAnalyst", "ReferenceLabOperations"], None),
    ("POST", P + "/result-interface-messages/<string:id>/validate", h_message_validate,
     ["InterfaceAnalyst"], None),
    ("POST", P + "/result-interface-messages/<string:id>/transmit", h_message_transmit,
     ["InterfaceAnalyst"], None),
    ("POST", P + "/result-interface-messages/<string:id>/fail", h_message_fail,
     ["InterfaceAnalyst"], None),
    ("POST", P + "/result-interface-messages/<string:id>/hold", h_message_hold,
     ["InterfaceAnalyst"], None),
    ("POST", P + "/result-interface-messages/<string:id>/release-hold", h_message_release_hold,
     ["InterfaceAnalyst"], None),
    ("POST", P + "/result-interface-messages/<string:id>/acknowledge", h_message_acknowledge,
     ["InterfaceAnalyst", "ReferenceLabOperations"], None),
    # BillingLedger
    ("POST", P + "/billing-ledgers", h_ledger_create, ["LabBillingSpecialist"], None),
    ("GET", P + "/billing-ledgers", h_ledger_list,
     ["LabBillingSpecialist", "UtilizationReviewer", "ReferenceLabOperations"], None),
    ("GET", P + "/billing-ledgers/<string:id>", h_ledger_get,
     ["LabBillingSpecialist", "UtilizationReviewer", "ReferenceLabOperations"], None),
    ("POST", P + "/billing-ledgers/<string:id>/void-charges", h_ledger_void,
     ["LabBillingSpecialist"], None),
    # UtilizationAdvisory
    ("POST", P + "/utilization-advisories", h_advisory_create,
     ["UtilizationReviewer", "MedicalDirector"], None),
    ("GET", P + "/utilization-advisories", h_advisory_list,
     ["UtilizationReviewer", "MedicalDirector", "LabClientAdmin", "ReferenceLabOperations"], None),
    ("GET", P + "/utilization-advisories/<string:id>", h_advisory_get,
     ["UtilizationReviewer", "MedicalDirector", "LabClientAdmin", "ReferenceLabOperations"], None),
    ("POST", P + "/utilization-advisories/<string:id>/acknowledge", h_advisory_acknowledge,
     ["LabClientAdmin"], None),
    ("POST", P + "/utilization-advisories/<string:id>/dismiss", h_advisory_dismiss,
     ["LabClientAdmin"], None),
    ("POST", P + "/utilization-advisories/<string:id>/escalate", h_advisory_escalate,
     ["ReferenceLabOperations", "MedicalDirector"], None),
]