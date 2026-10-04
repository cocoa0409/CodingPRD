"""Workflow engine, part two: specimen, order, analyzer, interface, ledger and
advisory workflows.

Shares its guard helpers and cascade primitives with engine.py.
"""

from datetime import timedelta

import db
import rules
import middleware
from db import parse_dt, iso, get, put, touch, all_rows
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_ORDER_NOT_ACCESSIBLE,
    ERR_EMPTY_REQUISITION,
    ERR_CATALOG_ENTRY_NOT_PUBLISHED,
    ERR_INTERFACE_BUILD_NOT_CERTIFIED,
    ERR_SPECIMEN_TYPE_MISMATCH,
    ERR_INSUFFICIENT_SPECIMEN_VOLUME,
    ERR_TRANSPORT_TEMPERATURE_EXCEEDED,
    ERR_SPECIMEN_STABILITY_EXCEEDED,
    ERR_REFLEX_WINDOW_EXPIRED,
    ERR_INSUFFICIENT_STABILITY_FOR_REFLEX,
    ERR_REFLEX_CONDITION_NOT_MET,
    ERR_SPECIMEN_NOT_ACCEPTABLE,
    ERR_CRITICAL_VALUE_NOT_NOTIFIED,
    ERR_SOD_RESULT_ENTRY_RELEASE,
    ERR_INSTRUMENT_DOUBLE_BOOKED,
    ERR_COURIER_LEG_OVERLAP,
    ERR_UTILIZATION_GUARD_BLOCKED,
    ERR_VOID_AMOUNT_MISMATCH,
    ERR_ALIQUOT_PARENT_MISMATCH,
    ERR_ALIQUOT_OVERDRAW,
    ERR_DUPLICATE_ADD_ON_LINE,
    ERR_DUPLICATE_ACCESSION_NUMBER,
    ERR_CONTROL_ID_REUSED,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_INVALID_TEMPORAL_WINDOW,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_INTERFACE_RESULT_GATED,
    ERR_RETRY_LIMIT_REACHED,
    ERR_INVALID_REQUEST,
)

from engine import (
    CLIENT_TRANSITIONS,
    COURIER_TRANSITIONS,
    CATALOG_TRANSITIONS,
    SPECIMEN_TRANSITIONS,
    ORDER_TRANSITIONS,
    INSTRUMENT_TRANSITIONS,
    BUILD_TRANSITIONS,
    MESSAGE_TRANSITIONS,
    ADVISORY_TRANSITIONS,
    guard_transition,
    check_occ,
    require_intake_admissible,
    within_credit_ceiling,
    post_charge_to_ledger,
    void_charge_on_ledger,
    refresh_client_posture,
    _ledger_for,
    _order_for_specimen,
    _find_entry_by_code,
    orders_of_client_all,
    lines_for_catalog_entry,
)


# ---------------------------------------------------------------------------
# specimen acceptability (PRD section 2.5)
# ---------------------------------------------------------------------------

def _max_min_volume(specimen):
    values = [
        rules.dec(e.get("min_volume_ml"))
        for e in rules.ordered_catalog_entries_of_specimen(specimen["id"])
        if e.get("min_volume_ml") is not None
    ]
    return max(values) if values else None


def _check_specimen_quality(specimen):
    """Priority 8 then 8.5 then 9: type/container, condition, volume and temperature."""
    if specimen.get("condition") != "ACCEPTABLE":
        if not specimen.get("condition_reason_code"):
            raise ApiError(
                ERR_SPECIMEN_NOT_ACCEPTABLE,
                "A non-ACCEPTABLE condition requires a condition_reason_code.",
            )
        raise ApiError(
            ERR_SPECIMEN_NOT_ACCEPTABLE,
            "Specimen condition %s is not acceptable for testing." % (specimen.get("condition"),),
        )
    entries = rules.ordered_catalog_entries_of_specimen(specimen["id"])
    for entry in entries:
        if entry.get("required_specimen_type") not in (None, specimen.get("specimen_type")):
            raise ApiError(
                ERR_SPECIMEN_TYPE_MISMATCH,
                "specimen_type does not match the required specimen type.",
            )
        if entry.get("container_type") not in (None, specimen.get("container_type")):
            raise ApiError(
                ERR_SPECIMEN_TYPE_MISMATCH,
                "container_type does not match the required container.",
            )
    max_min = _max_min_volume(specimen)
    if max_min is not None and rules.dec(specimen.get("volume_ml")) < max_min:
        raise ApiError(
            ERR_INSUFFICIENT_SPECIMEN_VOLUME,
            "volume_ml is below the largest min_volume_ml over the ordered tests.",
        )
    for entry in entries:
        declared = entry.get("transport_temperature")
        if declared is not None and declared != specimen.get("transport_temperature"):
            raise ApiError(
                ERR_TRANSPORT_TEMPERATURE_EXCEEDED,
                "The observed transport_temperature differs from a declared transport condition.",
            )


def _check_stability_inclusive(specimen):
    """Priority 10: elapsed_hours <= binding_window_hours, inclusive."""
    window = rules.binding_window_hours(specimen)
    if window is None:
        return
    collected = parse_dt(specimen.get("collection_at"))
    if collected is None:
        return
    elapsed = rules.dec(db.hours_between(collected, db.now()))
    if elapsed > window:
        raise ApiError(
            ERR_SPECIMEN_STABILITY_EXCEEDED,
            "The specimen's binding stability window has elapsed.",
        )


def _check_strict_reflex_stability(specimen, entry):
    """Priority 11: remaining_stability_hours must exceed reflex_min_remaining_hours."""
    threshold = entry.get("reflex_min_remaining_hours")
    if threshold is None:
        return
    remaining = rules.remaining_stability_hours(specimen)
    if remaining is None:
        return
    if remaining <= rules.dec(threshold):
        raise ApiError(
            ERR_INSUFFICIENT_STABILITY_FOR_REFLEX,
            "Remaining stability does not strictly exceed reflex_min_remaining_hours.",
        )


# ---------------------------------------------------------------------------
# Specimen workflows
# ---------------------------------------------------------------------------

def engine_specimen_accession(specimen):
    if specimen.get("status") == "REJECTED":
        if specimen.get("rejection_reason_code") != "TEST_WITHDRAWN":
            raise ApiError(
                ERR_ORDER_NOT_ACCESSIBLE,
                "Only a withdrawal-cascaded rejection may be re-accessioned.",
            )
        if specimen.get("condition") != "ACCEPTABLE":
            raise ApiError(ERR_SPECIMEN_NOT_ACCEPTABLE, "Condition is not ACCEPTABLE.")
        _check_stability_inclusive(specimen)
        specimen["status"] = "ACCESSIONED"
        specimen["rejection_reason_code"] = None
        touch(specimen)
        return specimen
    if specimen.get("status") != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE, "Specimen is not in RECEIVED status.")
    _check_specimen_quality(specimen)
    _check_stability_inclusive(specimen)
    specimen["status"] = "ACCESSIONED"
    touch(specimen)
    # PRD section 3.3: "The act bubbles upward: the owning send-out order, if
    # still in SUBMITTED status, moves to ACCESSIONED in the same transaction."
    for order in rules.orders_of_specimen(specimen["id"]):
        if order.get("order_status") == "SUBMITTED":
            order["order_status"] = "ACCESSIONED"
            order["billing_status"] = "PROVISIONAL"
            order["provisional_charge_cents"] = rules.num(rules.provisional_charge_cents(order))
            order["stability_deadline_at"] = rules.stability_deadline(order)
            touch(order)
    return specimen


def engine_specimen_begin_testing(specimen, section):
    guard_transition("specimens", "begin-testing", SPECIMEN_TRANSITIONS, specimen)
    _check_specimen_quality(specimen)
    _check_stability_inclusive(specimen)
    if not _live_analyzer_run_covers(section):
        raise ApiError(
            ERR_INVALID_STATE,
            "Exactly one RUNNING analyzer run for the section must cover the logical clock.",
        )
    specimen["status"] = "IN_TESTING"
    touch(specimen)
    for order in rules.orders_of_specimen(specimen["id"]):
        if order.get("order_status") not in ("ACCESSIONED", "IN_TESTING"):
            continue
        for line in all_rows("order_test_lines"):
            if line.get("send_out_order_id") != order["id"]:
                continue
            if line.get("line_status") == "PENDING":
                line["line_status"] = "IN_PROGRESS"
                touch(line)
        if order.get("order_status") == "ACCESSIONED":
            order["order_status"] = "IN_TESTING"
            # rush_tier -> effective_tat_hours -> expected_result_at, once and in order
            rules.settle_rush_tier(order)
            touch(order)
    return specimen


def _live_analyzer_run_covers(section):
    """Exactly one RUNNING analyzer run must cover the logical clock.

    The precondition is deliberately about the count rather than about a section
    label: a catalog entry carries no section field, so the section is used only
    to disambiguate when more than one run is live. A single live run therefore
    satisfies the precondition whatever label it was booked under.
    """
    covering = []
    for run in all_rows("instrument_runs"):
        if run.get("run_status") != "RUNNING":
            continue
        start = parse_dt(run.get("reserved_start_at"))
        end = parse_dt(run.get("reserved_end_at"))
        if start is None or end is None:
            continue
        if start <= db.now() <= end:
            covering.append(run)
    if section is not None:
        matching = [r for r in covering if r.get("section") == section]
        if matching:
            covering = matching
    return len(covering) == 1


def engine_specimen_reject(specimen, rejection_reason_code):
    # Priority 5 then 5.5: REJECTED and RELEASED are declared terminal states, so
    # acting on them reports ERR_ALREADY_TERMINAL rather than the generic error.
    guard_transition("specimens", "reject", SPECIMEN_TRANSITIONS, specimen)
    if specimen.get("condition") != "ACCEPTABLE" and not specimen.get("condition_reason_code"):
        raise ApiError(
            ERR_SPECIMEN_NOT_ACCEPTABLE,
            "A non-ACCEPTABLE condition requires a condition_reason_code.",
        )
    if not rejection_reason_code:
        raise ApiError(ERR_INVALID_REQUEST, "rejection_reason_code is required.")
    origin = specimen.get("status")
    specimen["status"] = "REJECTED"
    specimen["rejection_reason_code"] = rejection_reason_code
    touch(specimen)
    raised = False
    for order in rules.orders_of_specimen(specimen["id"]):
        if origin == "RECEIVED" and order.get("order_status") in ("SUBMITTED", "ACCESSIONED"):
            _cancel_order(order, unconditional_lines=False)
            if not raised:
                raised = True
                _maybe_raise_duplicate_advisory(specimen)
        elif origin == "ACCESSIONED" and order.get("order_status") == "ACCESSIONED":
            _cancel_order(order, unconditional_lines=True)
    return specimen


def _cancel_order(order, unconditional_lines):
    """Cancel an order and the lines that were still in flight.

    PRD 3.4 cancels "every line on those cancelled orders that is not already
    cancelled", and PRD 3.10 pins that "lines in CANCELLED status are excluded
    from the [reportable] count and contribute no charge at all" — so a line that
    has already reached FINAL, with its own charge written, keeps its status and
    its billed_cents.
    """
    order["order_status"] = "CANCELLED"
    for line in all_rows("order_test_lines"):
        if line.get("send_out_order_id") != order["id"]:
            continue
        if line.get("line_status") in ("INTERIM", "FINAL", "CANCELLED"):
            continue
        line["line_status"] = "CANCELLED"
        touch(line)
    touch(order)


def _maybe_raise_duplicate_advisory(specimen):
    """Only when the same patient_mrn was submitted twice in the trailing 24 hours."""
    cutoff = db.now() - timedelta(hours=24)
    matches = []
    for order in all_rows("send_out_orders"):
        if order.get("patient_mrn") != specimen.get("patient_mrn"):
            continue
        requested = parse_dt(order.get("client_requested_at"))
        if requested is None or requested <= cutoff:
            continue
        matches.append(order)
    if len(matches) < 2:
        return None
    entry = rules.ordered_catalog_entries_of_specimen(specimen["id"])
    return _raise_advisory(
        client_laboratory_id=specimen.get("client_laboratory_id"),
        test_catalog_entry_id=entry[0]["id"] if entry else None,
        source_order_id=matches[0]["id"],
        advisory_type="DUPLICATE_ORDER",
        message="Duplicate patient submission within 24 hours.",
    )


def engine_specimen_create_aliquot(parent, body):
    if parent.get("status") not in ("RECEIVED", "ACCESSIONED", "IN_TESTING"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Parent specimen must be in RECEIVED, ACCESSIONED or IN_TESTING status.",
        )
    volume = body.get("aliquot_volume_ml")
    if volume is None:
        raise ApiError(ERR_INVALID_REQUEST, "aliquot_volume_ml is required.")
    volume_dec = rules.dec(volume)
    if volume_dec <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "aliquot_volume_ml must be strictly greater than zero.")
    child_volume = body.get("volume_ml", body.get("aliquot_volume_ml"))
    if rules.dec(child_volume) < volume_dec:
        raise ApiError(
            ERR_INSUFFICIENT_SPECIMEN_VOLUME,
            "The tube's received volume must be at least its captured aliquot volume.",
        )
    accession_number = body.get("accession_number")
    _check_accession_unique(accession_number)
    child = {
        "client_laboratory_id": parent.get("client_laboratory_id"),
        "courier_run_id": parent.get("courier_run_id"),
        "aliquot_parent_id": parent["id"],
        "accession_number": accession_number,
        "patient_mrn": parent.get("patient_mrn"),
        "specimen_type": parent.get("specimen_type"),
        "container_type": body.get("container_type", parent.get("container_type")),
        "volume_ml": child_volume,
        "aliquot_volume_ml": volume,
        "collection_at": parent.get("collection_at"),
        "received_at": parent.get("received_at"),
        "transport_temperature": parent.get("transport_temperature"),
        "condition": parent.get("condition"),
        "condition_reason_code": parent.get("condition_reason_code"),
        "rejection_reason_code": None,
        "status": "RECEIVED",
    }
    # Project the running total before the row is persisted: an overdraw is a
    # failed creation, so the offending tube is not added to the aliquot set (the
    # create/delete conservation claim covers the total and the child row count),
    # while the parent's condition and status do change and are not undone later.
    existing = rules.total_aliquot_volume_ml(parent)
    if existing + volume_dec > rules.dec(parent.get("volume_ml")):
        parent["total_aliquot_volume_ml"] = rules.num(existing)
        parent["status"] = "REJECTED"
        parent["condition"] = "INSUFFICIENT_VOLUME"
        parent["condition_reason_code"] = "ALIQUOT_OVERDRAW"
        touch(parent)
        raise ApiError(
            ERR_ALIQUOT_OVERDRAW,
            "The aliquot total exceeds the parent's received volume.",
        )
    db.stamp_common(child, "Specimen")
    put("specimens", child)
    parent["total_aliquot_volume_ml"] = rules.num(existing + volume_dec)
    touch(parent)
    return child


def engine_specimen_delete_aliquot(parent, child):
    if child.get("aliquot_parent_id") != parent["id"]:
        raise ApiError(ERR_ALIQUOT_PARENT_MISMATCH, "The aliquot does not belong to the parent.")
    db.remove("specimens", child["id"])
    total = rules.total_aliquot_volume_ml(parent)
    parent["total_aliquot_volume_ml"] = rules.num(total)
    touch(parent)
    return parent


def _check_accession_unique(accession_number):
    if accession_number is None:
        return
    for specimen in all_rows("specimens"):
        if specimen.get("accession_number") == accession_number:
            raise ApiError(
                ERR_DUPLICATE_ACCESSION_NUMBER,
                "accession_number is already carried by an existing specimen.",
            )


# ---------------------------------------------------------------------------
# SendOutOrder workflows
# ---------------------------------------------------------------------------

def engine_order_create(body, actor):
    test_lines = body.get("test_lines") or []
    if not test_lines:
        raise ApiError(ERR_EMPTY_REQUISITION, "A requisition must carry at least one test line.")
    client_id = body.get("client_laboratory_id")
    specimen_id = body.get("specimen_id")
    client = get("client_laboratories", client_id)
    if client is None:
        from errors import ERR_CLIENT_LABORATORY_NOT_FOUND

        raise ApiError(ERR_CLIENT_LABORATORY_NOT_FOUND, "client_laboratory_id does not resolve.")
    specimen = get("specimens", specimen_id)
    if specimen is None:
        from errors import ERR_SPECIMEN_NOT_FOUND

        raise ApiError(ERR_SPECIMEN_NOT_FOUND, "specimen_id does not resolve.")
    entries = []
    for line_spec in test_lines:
        entry_id = line_spec.get("test_catalog_entry_id")
        entry = get("test_catalog_entries", entry_id)
        if entry is None:
            from errors import ERR_TEST_CATALOG_ENTRY_NOT_FOUND

            raise ApiError(ERR_TEST_CATALOG_ENTRY_NOT_FOUND, "test_catalog_entry_id does not resolve.")
        if not rules.catalog_currency_ok(client_id, entry):
            raise ApiError(
                ERR_CATALOG_ENTRY_NOT_PUBLISHED,
                "The ordered catalog entry is not PUBLISHED or the client's certified build is stale.",
            )
        entries.append(entry)
    requested = parse_dt(body.get("client_requested_at"))
    if requested is None or requested > db.now():
        raise ApiError(
            ERR_INVALID_TEMPORAL_WINDOW,
            "client_requested_at must be at or before the logical clock.",
        )
    _check_utilization_guard(body, entries, specimen_id)
    require_intake_admissible(client)

    order = {
        "client_laboratory_id": client_id,
        "specimen_id": specimen_id,
        "reflex_source_order_id": body.get("reflex_source_order_id"),
        "order_number": body.get("order_number"),
        "patient_mrn": body.get("patient_mrn"),
        "client_requested_at": requested,
        "priority": body.get("priority"),
        "rush_tier": None,
        "base_tat_hours": None,
        "effective_tat_hours": None,
        "expected_result_at": None,
        "stability_deadline_at": None,
        "provisional_charge_cents": None,
        "order_final_charge_cents": None,
        "charge_variance_cents": None,
        "tat_credit_cents": None,
        "interpretive_comment": None,
        "override_utilization_guard": bool(body.get("override_utilization_guard", False)),
        "order_status": "SUBMITTED",
        "billing_status": "UNBILLED",
    }
    db.stamp_common(order, "SendOutOrder")
    put("send_out_orders", order)

    seen_sequences = set()
    sequence = 0
    for index, line_spec in enumerate(test_lines):
        sequence = line_spec.get("line_sequence")
        if sequence is None:
            sequence = index + 1
        if sequence in seen_sequences:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "line_sequence must be unique within an order.",
                http_status=409,
            )
        seen_sequences.add(sequence)
        line = {
            "send_out_order_id": order["id"],
            "test_catalog_entry_id": line_spec.get("test_catalog_entry_id"),
            "line_sequence": sequence,
            "is_add_on": bool(line_spec.get("is_add_on", False)),
            "add_on_at": None,
            "result_value": None,
            "result_units": None,
            "result_flag": None,
            "critical_value_notified_to": None,
            "critical_value_notified_at": None,
            "entered_by_user_id": None,
            "billed_cents": None,
            "tat_credit_cents": None,
            "result_released_at": None,
            "line_status": "PENDING",
        }
        db.stamp_common(line, "OrderTestLine")
        put("order_test_lines", line)

    _raise_utilization_advisories(order, entries)
    order["stability_deadline_at"] = rules.stability_deadline(order)
    return order


def _check_credit_admission(client):
    if (client.get("billing_arrangement") or "CLIENT") != "CLIENT":
        return
    rules.recompute_outstanding_balance(client)
    if rules.dec(client.get("outstanding_balance_cents")) >= rules.dec(client.get("credit_limit_cents")):
        raise ApiError(
            ERR_CREDIT_LIMIT_EXCEEDED,
            "The client's routed balance is at or above its credit limit.",
        )


def _check_utilization_guard(body, entries, specimen_id):
    """Priority 18: block a repeat of a utilization-managed test once ESCALATED."""
    if body.get("override_utilization_guard"):
        return
    client_id = body.get("client_laboratory_id")
    for entry in entries:
        if not entry.get("is_utilization_managed"):
            continue
        for advisory in all_rows("utilization_advisories"):
            if advisory.get("client_laboratory_id") != client_id:
                continue
            if advisory.get("test_catalog_entry_id") != entry["id"]:
                continue
            if advisory.get("status") != "ESCALATED":
                continue
            raise ApiError(
                ERR_UTILIZATION_GUARD_BLOCKED,
                "An advisory for this client and test is already ESCALATED.",
            )


def _raise_utilization_advisories(order, entries):
    """A repeat of a utilization-managed test for the same patient raises/re-sends."""
    for entry in entries:
        if not entry.get("is_utilization_managed"):
            continue
        prior = 0
        for other in all_rows("send_out_orders"):
            if other["id"] == order["id"]:
                continue
            if other.get("patient_mrn") != order.get("patient_mrn"):
                continue
            if other.get("client_laboratory_id") != order.get("client_laboratory_id"):
                continue
            for line in all_rows("order_test_lines"):
                if line.get("send_out_order_id") != other["id"]:
                    continue
                if line.get("test_catalog_entry_id") == entry["id"]:
                    prior += 1
                    break
        if prior < 1:
            continue
        existing = None
        for advisory in all_rows("utilization_advisories"):
            if (
                advisory.get("client_laboratory_id") == order.get("client_laboratory_id")
                and advisory.get("test_catalog_entry_id") == entry["id"]
                and advisory.get("status") != "DISMISSED"
            ):
                existing = advisory
                break
        if existing is not None and existing.get("status") == "ACKNOWLEDGED":
            # Send-back cycle: re-sent rather than duplicated, only when onboarding
            # has completed (PRD section 3.9).
            client = get("client_laboratories", order.get("client_laboratory_id"))
            if client is not None and client.get("onboarding_status") == "COMPLETE":
                existing["status"] = "SENT"
                existing["send_count"] = int(existing.get("send_count") or 0) + 1
                touch(existing)
        elif existing is None:
            _raise_advisory(
                client_laboratory_id=order.get("client_laboratory_id"),
                test_catalog_entry_id=entry["id"],
                source_order_id=order["id"],
                advisory_type="DUPLICATE_ORDER",
                message="Repeat ordering of a utilization-managed test for the same patient.",
            )


def engine_order_accession(order):
    guard_transition("send_out_orders", "accession", ORDER_TRANSITIONS, order)
    specimen = get("specimens", order.get("specimen_id"))
    if specimen is None or specimen.get("status") != "ACCESSIONED":
        raise ApiError(
            ERR_ORDER_NOT_ACCESSIBLE,
            "The order's specimen must be ACCESSIONED before the order can be accessioned.",
        )
    # PRD section 2.9: intake is admitted for ACTIVE and CREDIT_HOLD postures;
    # only SUSPENDED and INACTIVE are refused outright.
    client = get("client_laboratories", order.get("client_laboratory_id"))
    if (client or {}).get("status") not in ("ACTIVE", "CREDIT_HOLD"):
        raise ApiError(ERR_CLIENT_NOT_ACTIVE, "The owning client must be ACTIVE or CREDIT_HOLD.")
    for line in all_rows("order_test_lines"):
        if line.get("send_out_order_id") != order["id"]:
            continue
        entry = get("test_catalog_entries", line.get("test_catalog_entry_id"))
        if not rules.catalog_currency_ok(order.get("client_laboratory_id"), entry):
            raise ApiError(
                ERR_CATALOG_ENTRY_NOT_PUBLISHED,
                "An ordered catalog entry is not PUBLISHED or the client's build is stale.",
            )
    order["order_status"] = "ACCESSIONED"
    order["billing_status"] = "PROVISIONAL"
    order["provisional_charge_cents"] = rules.num(rules.provisional_charge_cents(order))
    order["stability_deadline_at"] = rules.stability_deadline(order)
    touch(order)
    return order


def engine_order_enter_results(order, body, actor):
    """Priority 4.5 OCC runs ahead of every business rule on this endpoint."""
    check_occ(body, "expected_send_out_order_version", order)
    specimen = get("specimens", order.get("specimen_id"))
    if specimen is None or specimen.get("status") != "IN_TESTING":
        raise ApiError(
            ERR_ORDER_NOT_ACCESSIBLE,
            "The order's specimen must be IN_TESTING to enter results.",
        )
    result_lines = body.get("result_lines") or []
    by_id = {}
    by_sequence = {}
    for line in all_rows("order_test_lines"):
        if line.get("send_out_order_id") != order["id"]:
            continue
        by_id[line["id"]] = line
        by_sequence[line.get("line_sequence")] = line
    touched_lines = []
    for spec in result_lines:
        target = None
        if spec.get("order_test_line_id") is not None:
            target = by_id.get(spec.get("order_test_line_id"))
            if target is None:
                from errors import ERR_ORDER_TEST_LINE_NOT_FOUND

                raise ApiError(
                    ERR_ORDER_TEST_LINE_NOT_FOUND,
                    "order_test_line_id does not resolve on this order.",
                )
        elif spec.get("line_sequence") is not None:
            target = by_sequence.get(spec.get("line_sequence"))
            if target is None:
                from errors import ERR_ORDER_TEST_LINE_NOT_FOUND

                raise ApiError(
                    ERR_ORDER_TEST_LINE_NOT_FOUND,
                    "line_sequence does not resolve on this order.",
                )
        else:
            raise ApiError(ERR_INVALID_REQUEST, "Each result line needs an identifier.")
        target["result_value"] = spec.get("result_value")
        if "result_units" in spec:
            target["result_units"] = spec.get("result_units")
        if "critical_value_notified_to" in spec:
            target["critical_value_notified_to"] = spec.get("critical_value_notified_to")
        if "critical_value_notified_at" in spec:
            target["critical_value_notified_at"] = parse_dt(spec.get("critical_value_notified_at"))
        target["entered_by_user_id"] = actor.user_id
        target["result_flag"] = rules.compute_result_flag(target)
        touch(target)
        touched_lines.append(target)
    # PRD 3.7: "The specimen then moves from IN_TESTING to RESULT_PENDING_REVIEW,
    # and the order waits there together with it until a pathologist signs the
    # results off." A specimen can carry more than one order, so the specimen
    # reaches review only once every line of every order against it is entered.
    specimen_lines = [
        l for l in all_rows("order_test_lines")
        if (get("send_out_orders", l.get("send_out_order_id")) or {}).get("specimen_id")
        == specimen["id"]
        and l.get("line_status") != "CANCELLED"
    ]
    if touched_lines and specimen_lines and all(
            l.get("result_value") is not None for l in specimen_lines):
        specimen["status"] = "RESULT_PENDING_REVIEW"
        touch(specimen)
    touch(order)
    return order


def engine_order_release_results(order, body, actor):
    guard_transition("send_out_orders", "release-results", ORDER_TRANSITIONS, order)
    lines = [l for l in all_rows("order_test_lines") if l.get("send_out_order_id") == order["id"]]
    if not lines or any(l.get("result_value") is None for l in lines):
        raise ApiError(
            ERR_INTERFACE_RESULT_GATED,
            "Every line must carry a result_value before release.",
        )
    # Priority 13 then 14.
    for line in lines:
        flag = rules.compute_result_flag(line)
        if flag in ("CRITICAL_HIGH", "CRITICAL_LOW"):
            if not line.get("critical_value_notified_to") or not line.get("critical_value_notified_at"):
                raise ApiError(
                    ERR_CRITICAL_VALUE_NOT_NOTIFIED,
                    "A critical result line lacks critical-value documentation.",
                )
        if line.get("entered_by_user_id") == actor.user_id:
            raise ApiError(
                ERR_SOD_RESULT_ENTRY_RELEASE,
                "The releasing user must differ from the result's entering user.",
            )
        if line.get("line_sequence") is None:
            raise ApiError(ERR_INVALID_REQUEST, "Every line must carry a line_sequence.")
    sequences = [l.get("line_sequence") for l in lines]
    if len(set(sequences)) != len(sequences):
        raise ApiError(ERR_INVALID_REQUEST, "Two lines share a line_sequence.")

    released_at = db.now()
    order["order_status"] = "RESULT_RELEASED"
    order["interpretive_comment"] = body.get("interpretive_comment")
    order["stability_deadline_at"] = rules.stability_deadline(order)
    touch(order)

    client = get("client_laboratories", order.get("client_laboratory_id"))

    # Lines transition to FINAL with their stamps, then volume_tier_price writes
    # billed_cents per line in ascending line_sequence order.
    for line in rules.lines_of_order(order["id"]):
        if line.get("line_status") in ("IN_PROGRESS", "INTERIM"):
            line["line_status"] = "FINAL"
        elif line.get("line_status") not in ("FINAL", "CANCELLED"):
            line["line_status"] = "FINAL"
        line["result_flag"] = rules.compute_result_flag(line)
        line["result_released_at"] = iso(released_at)
        line["billed_cents"] = rules.num(rules.volume_tier_price(line))
        touch(line)
    order["order_final_charge_cents"] = rules.num(rules.order_final_charge_cents(order))
    order["charge_variance_cents"] = rules.num(
        rules.dec(order["order_final_charge_cents"]) - rules.dec(order.get("provisional_charge_cents"))
    )
    rules.compute_turnaround_credit(order, released_at)

    # billing_status -> BILLED, ledger receives the final charge, posture recomputed.
    order["billing_status"] = "BILLED"
    if client is not None:
        ledger = _ledger_for(client["id"])
        if ledger is not None:
            ledger["billed_cents"] = rules.num(
                rules.round_half_up(
                    rules.dec(ledger.get("billed_cents"))
                    + rules.dec(order["order_final_charge_cents"]),
                    2,
                )
            )
            ledger["charge_entry_count"] = int(ledger.get("charge_entry_count") or 0) + 1
            rules.recompute_ledger(ledger)
            touch(ledger)
        refresh_client_posture(client)
    touch(order)

    _maybe_fire_reflex(order)
    return order


def engine_order_cancel(order):
    guard_transition("send_out_orders", "cancel", ORDER_TRANSITIONS, order)
    order["order_status"] = "CANCELLED"
    billed = rules.dec("0")
    for line in all_rows("order_test_lines"):
        if line.get("send_out_order_id") != order["id"]:
            continue
        if line.get("line_status") in ("PENDING", "IN_PROGRESS", "INTERIM"):
            line["line_status"] = "CANCELLED"
            touch(line)
        billed += rules.dec(line.get("billed_cents"))
    if billed > 0:
        order["billing_status"] = "VOIDED"
        client = get("client_laboratories", order.get("client_laboratory_id"))
        if client is not None:
            void_charge_on_ledger(client, billed)
    touch(order)
    return order


def engine_order_hold(order):
    if order.get("order_status") == "CANCELLED":
        if order.get("billing_status") != "VOIDED":
            raise ApiError(ERR_INVALID_STATE, "A cancelled order may only be held under billing review.")
    else:
        guard_transition("send_out_orders", "hold", ORDER_TRANSITIONS, order)
    order["order_status"] = "ON_HOLD"
    for line in all_rows("order_test_lines"):
        if line.get("send_out_order_id") != order["id"]:
            continue
        if line.get("line_status") == "IN_PROGRESS":
            line["line_status"] = "PENDING"
            touch(line)
    touch(order)
    return order


def engine_order_release_hold(order):
    guard_transition("send_out_orders", "release-hold", ORDER_TRANSITIONS, order)
    client = get("client_laboratories", order.get("client_laboratory_id"))
    if (client or {}).get("status") != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "The owning client must be ACTIVE.")
    if order.get("billing_status") not in ("UNBILLED", "PROVISIONAL"):
        raise ApiError(ERR_INVALID_STATE, "billing_status must be UNBILLED or PROVISIONAL.")
    order["order_status"] = "SUBMITTED"
    touch(order)
    return order


def engine_order_repeat_test(order, order_test_line_id):
    line = get("order_test_lines", order_test_line_id)
    if line is None or line.get("send_out_order_id") != order["id"]:
        from errors import ERR_ORDER_TEST_LINE_NOT_FOUND

        raise ApiError(ERR_ORDER_TEST_LINE_NOT_FOUND, "order_test_line_id does not resolve.")
    if line.get("line_status") != "FINAL":
        raise ApiError(ERR_INVALID_STATE, "Only a FINAL line may be flagged for repeat.")
    specimen = get("specimens", order.get("specimen_id"))
    has_live_aliquot = False
    if specimen is not None:
        for child in all_rows("specimens"):
            if child.get("aliquot_parent_id") != specimen["id"]:
                continue
            remaining = rules.remaining_stability_hours(child)
            if remaining is not None and remaining > 0:
                has_live_aliquot = True
                break
    if not has_live_aliquot:
        raise ApiError(
            ERR_INVALID_STATE,
            "The specimen must retain at least one aliquot with positive remaining stability.",
        )
    for other in all_rows("order_test_lines"):
        if other.get("send_out_order_id") != order["id"]:
            continue
        if other.get("test_catalog_entry_id") != line.get("test_catalog_entry_id"):
            continue
        if other.get("line_status") == "REPEAT_REQUIRED":
            raise ApiError(ERR_DUPLICATE_ADD_ON_LINE, "A repeat for this test is already outstanding.")
    line["line_status"] = "REPEAT_REQUIRED"
    touch(line)
    max_sequence = max(
        [int(l.get("line_sequence") or 0) for l in all_rows("order_test_lines")
         if l.get("send_out_order_id") == order["id"]] or [0]
    )
    replacement = _new_line(order, line.get("test_catalog_entry_id"), max_sequence + 1, is_add_on=True)
    replacement["add_on_at"] = iso(db.now())
    touch(order)
    return order


def _new_line(order, entry_id, sequence, is_add_on):
    line = {
        "send_out_order_id": order["id"],
        "test_catalog_entry_id": entry_id,
        "line_sequence": sequence,
        "is_add_on": bool(is_add_on),
        "add_on_at": None,
        "result_value": None,
        "result_units": None,
        "result_flag": None,
        "critical_value_notified_to": None,
        "critical_value_notified_at": None,
        "entered_by_user_id": None,
        "billed_cents": None,
        "tat_credit_cents": None,
        "result_released_at": None,
        "line_status": "PENDING",
    }
    db.stamp_common(line, "OrderTestLine")
    put("order_test_lines", line)
    return line


def _check_order_line_effect_eligibility(order, entry):
    """Shared gate for add-on and reflex lines: priority 6, 22-style and 23 checks."""
    if not rules.catalog_currency_ok(order.get("client_laboratory_id"), entry):
        raise ApiError(
            ERR_CATALOG_ENTRY_NOT_PUBLISHED,
            "The catalog entry is not PUBLISHED or the client's certified build is stale.",
        )
    existing = [
        l for l in all_rows("order_test_lines")
        if l.get("send_out_order_id") == order["id"]
        and l.get("test_catalog_entry_id") == entry["id"]
        and l.get("line_status") != "CANCELLED"
    ]
    if existing:
        raise ApiError(
            ERR_DUPLICATE_ADD_ON_LINE,
            "A non-cancelled line for this test already exists on the order.",
        )


def engine_order_add_on_test(order, body):
    # PRD section 2.11's validation precedence: domain rules run in the priority
    # order the workflows record, and §3.10 pins these two tiers as separate
    # calculators together. Apply the specimen-anchored bounds (stability and
    # reflex remaining) first, so a request that fails them reports the specific
    # identifier rather than the generic state error.
    specimen = get("specimens", order.get("specimen_id"))
    if specimen is None:
        raise ApiError(ERR_ORDER_NOT_ACCESSIBLE, "The order's specimen does not resolve.")
    entry = get("test_catalog_entries", body.get("test_catalog_entry_id"))
    if entry is None:
        from errors import ERR_TEST_CATALOG_ENTRY_NOT_FOUND

        raise ApiError(ERR_TEST_CATALOG_ENTRY_NOT_FOUND, "test_catalog_entry_id does not resolve.")
    _check_stability_inclusive(specimen)
    _check_strict_reflex_stability(specimen, entry)
    # PRD 3.5 places no order-status precondition on an add-on: it is "appended
    # to an already submitted order", and the only bounds it names are the
    # specimen's inclusive stability window and the entry's strict
    # reflex_min_remaining_hours. The INTERIM -> IN_PROGRESS revert leg it does
    # name applies only to lines that happen to sit in INTERIM.
    _check_order_line_effect_eligibility(order, entry)
    if entry.get("required_specimen_type") not in (None, specimen.get("specimen_type")):
        raise ApiError(ERR_SPECIMEN_TYPE_MISMATCH, "specimen_type does not match the entry's requirement.")
    if entry.get("container_type") not in (None, specimen.get("container_type")):
        raise ApiError(ERR_SPECIMEN_TYPE_MISMATCH, "container_type does not match the entry's requirement.")
    max_min = _max_min_volume(specimen)
    if max_min is not None and rules.dec(specimen.get("volume_ml")) < max_min:
        raise ApiError(ERR_INSUFFICIENT_SPECIMEN_VOLUME, "volume_ml is below the required minimum.")
    if entry.get("transport_temperature") not in (None, specimen.get("transport_temperature")):
        raise ApiError(
            ERR_TRANSPORT_TEMPERATURE_EXCEEDED,
            "The observed transport_temperature differs from the entry's requirement.",
        )
    _check_stability_inclusive(specimen)
    _check_strict_reflex_stability(specimen, entry)
    sequence = body.get("line_sequence")
    if sequence is None:
        sequence = max(
            [int(l.get("line_sequence") or 0) for l in all_rows("order_test_lines")
             if l.get("send_out_order_id") == order["id"]] or [0]
        ) + 1
    for other in all_rows("order_test_lines"):
        if other.get("send_out_order_id") == order["id"] and other.get("line_sequence") == sequence:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "line_sequence must be unique within an order.",
                http_status=409,
            )
    line = _new_line(order, entry["id"], sequence, is_add_on=True)
    line["add_on_at"] = parse_dt(body.get("add_on_at")) or db.now()
    line["result_flag"] = None
    for other in all_rows("order_test_lines"):
        if other.get("send_out_order_id") != order["id"]:
            continue
        if other.get("line_status") == "INTERIM":
            other["line_status"] = "IN_PROGRESS"
            touch(other)
    order["stability_deadline_at"] = rules.stability_deadline(order)
    touch(order)
    return order


def engine_order_reflex_test(order, body):
    guard_transition("send_out_orders", "order-reflex-test", ORDER_TRANSITIONS, order)
    entry = get("test_catalog_entries", body.get("test_catalog_entry_id"))
    if entry is None:
        from errors import ERR_TEST_CATALOG_ENTRY_NOT_FOUND

        raise ApiError(ERR_TEST_CATALOG_ENTRY_NOT_FOUND, "test_catalog_entry_id does not resolve.")
    specimen = get("specimens", order.get("specimen_id"))
    if specimen is None:
        raise ApiError(ERR_ORDER_NOT_ACCESSIBLE, "The order's specimen does not resolve.")
    trigger = _triggering_entry(order)
    released_at = _triggering_release_at(order)
    # Priority 12: the triggering entry's reflex_condition must be satisfied.
    if trigger is None or not _reflex_condition_satisfied(trigger, _triggering_value(order)):
        raise ApiError(
            ERR_REFLEX_CONDITION_NOT_MET,
            "The triggering entry's reflex_condition is not satisfied by the result.",
        )
    _check_order_line_effect_eligibility(order, entry)
    # Priority 10: within reflex_within_hours, inclusive.
    window = trigger.get("reflex_within_hours")
    if window is not None and released_at is not None:
        elapsed = rules.dec(db.hours_between(released_at, db.now()))
        if elapsed > rules.dec(window):
            raise ApiError(
                ERR_REFLEX_WINDOW_EXPIRED,
                "The reflex request falls outside reflex_within_hours of the triggering release.",
            )
    # Priority 11: strictly more remaining stability than reflex_min_remaining_hours.
    _check_strict_reflex_stability(specimen, trigger)
    sequence = body.get("line_sequence")
    if sequence is None:
        sequence = max(
            [int(l.get("line_sequence") or 0) for l in all_rows("order_test_lines")
             if l.get("send_out_order_id") == order["id"]] or [0]
        ) + 1
    for other in all_rows("order_test_lines"):
        if other.get("send_out_order_id") == order["id"] and other.get("line_sequence") == sequence:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "line_sequence must be unique within an order.",
                http_status=409,
            )
    line = _new_line(order, entry["id"], sequence, is_add_on=True)
    line["add_on_at"] = parse_dt(body.get("add_on_at")) or db.now()
    order["order_status"] = "REFLEX_PENDING"
    order["stability_deadline_at"] = rules.stability_deadline(order)
    touch(order)
    return order


def engine_order_reflex_cancel(order):
    guard_transition("send_out_orders", "reflex-cancel", ORDER_TRANSITIONS, order)
    for other in all_rows("send_out_orders"):
        if other.get("reflex_source_order_id") != order["id"]:
            continue
        if other.get("order_status") in ("CLOSED", "CANCELLED"):
            continue
        other["order_status"] = "CANCELLED"
        for line in all_rows("order_test_lines"):
            if line.get("send_out_order_id") == other["id"]:
                line["line_status"] = "CANCELLED"
                touch(line)
        touch(other)
    order["order_status"] = "RESULT_RELEASED"
    touch(order)
    return order


def engine_order_charge(order):
    guard_transition("send_out_orders", "charge", ORDER_TRANSITIONS, order)
    client = get("client_laboratories", order.get("client_laboratory_id"))
    if (client or {}).get("status") not in ("ACTIVE", "CREDIT_HOLD"):
        raise ApiError(ERR_CLIENT_NOT_ACTIVE, "The owning client must be ACTIVE or CREDIT_HOLD.")
    # Price every live line, then the order-level variants.
    for line in rules.live_lines_of_order(order["id"]):
        if line.get("billed_cents") is None:
            line["billed_cents"] = rules.num(rules.volume_tier_price(line))
    order["order_final_charge_cents"] = rules.num(rules.order_final_charge_cents(order))
    order["charge_variance_cents"] = rules.num(
        rules.dec(order["order_final_charge_cents"]) - rules.dec(order.get("provisional_charge_cents"))
    )
    within_credit_ceiling(client, order["order_final_charge_cents"])
    order["billing_status"] = "BILLED"
    touch(order)
    if client is not None:
        post_charge_to_ledger(client, order["order_final_charge_cents"])
    return order


# ---------------------------------------------------------------------------
# reflex chain helpers (PRD section 3.8)
# ---------------------------------------------------------------------------

def _triggering_entry(order):
    for line in rules.lines_of_order(order["id"]):
        entry = get("test_catalog_entries", line.get("test_catalog_entry_id"))
        if entry is not None and entry.get("reflex_condition") not in (None, "NONE"):
            return entry
    return None


def _triggering_value(order):
    for line in rules.lines_of_order(order["id"]):
        entry = get("test_catalog_entries", line.get("test_catalog_entry_id"))
        if entry is not None and entry.get("reflex_condition") not in (None, "NONE"):
            return line.get("result_value")
    return None


def _triggering_release_at(order):
    for line in rules.lines_of_order(order["id"]):
        released = parse_dt(line.get("result_released_at"))
        if released is not None:
            return released
    return None


def _reflex_condition_satisfied(entry, value):
    condition = entry.get("reflex_condition")
    if condition == "ALWAYS":
        return True
    if value is None:
        return False
    v = rules.dec(value)
    if condition == "RESULT_ABOVE_HIGH":
        high = entry.get("critical_value_high")
        return high is not None and v > rules.dec(high)
    if condition == "RESULT_BELOW_LOW":
        low = entry.get("critical_value_low")
        return low is not None and v < rules.dec(low)
    return False


def _maybe_fire_reflex(order):
    """Automatic reflex leg of release-results (cascade hop 2)."""
    fired = False
    for line in rules.lines_of_order(order["id"]):
        entry = get("test_catalog_entries", line.get("test_catalog_entry_id"))
        if entry is None or entry.get("reflex_condition") in (None, "NONE"):
            continue
        if _reflex_condition_satisfied(entry, line.get("result_value")):
            target = _find_entry_by_code(entry.get("reflex_test_code"))
            if target is None:
                continue
            order["order_status"] = "REFLEX_PENDING"
            reflex_order = {
                "client_laboratory_id": order.get("client_laboratory_id"),
                "specimen_id": order.get("specimen_id"),
                "reflex_source_order_id": order["id"],
                "order_number": order.get("order_number"),
                "patient_mrn": order.get("patient_mrn"),
                "client_requested_at": db.now(),
                "priority": order.get("priority"),
                "rush_tier": None,
                "base_tat_hours": None,
                "effective_tat_hours": None,
                "expected_result_at": None,
                "stability_deadline_at": None,
                "provisional_charge_cents": None,
                "order_final_charge_cents": None,
                "charge_variance_cents": None,
                "tat_credit_cents": None,
                "interpretive_comment": None,
                "override_utilization_guard": False,
                "order_status": "SUBMITTED",
                "billing_status": "UNBILLED",
            }
            db.stamp_common(reflex_order, "SendOutOrder")
            put("send_out_orders", reflex_order)
            _new_line(reflex_order, target["id"], 1, is_add_on=False)
            # Cascade hop 4: hold every live outbound message of this client.
            for message in all_rows("result_interface_messages"):
                if message.get("status") not in ("QUEUED", "VALIDATED"):
                    continue
                build = get("interface_builds", message.get("interface_build_id"))
                if build is None or build.get("status") != "CERTIFIED":
                    continue
                if build.get("client_laboratory_id") != order.get("client_laboratory_id"):
                    continue
                message["status"] = "HELD"
                touch(message)
            touch(order)
            fired = True
            break
    return fired


# ---------------------------------------------------------------------------
# InstrumentRun workflows
# ---------------------------------------------------------------------------

def engine_instrument_run_create(body):
    entry = get("test_catalog_entries", body.get("test_catalog_entry_id"))
    if entry is None:
        from errors import ERR_TEST_CATALOG_ENTRY_NOT_FOUND

        raise ApiError(ERR_TEST_CATALOG_ENTRY_NOT_FOUND, "test_catalog_entry_id does not resolve.")
    start = parse_dt(body.get("reserved_start_at"))
    end = parse_dt(body.get("reserved_end_at"))
    if start is None or end is None:
        raise ApiError(ERR_INVALID_REQUEST, "reserved_start_at and reserved_end_at are required.")
    if not start < end:
        raise ApiError(
            ERR_INSTRUMENT_DOUBLE_BOOKED,
            "reserved_start_at must fall strictly before reserved_end_at.",
        )
    buffer_minutes = int(body.get("decontamination_buffer_minutes") or 0)
    instrument_code = body.get("instrument_code")
    section = body.get("section")
    _check_instrument_overlap(instrument_code, section, start, end, buffer_minutes, exclude=None)
    run = {
        "test_catalog_entry_id": body.get("test_catalog_entry_id"),
        "instrument_code": instrument_code,
        "section": section,
        "decontamination_buffer_minutes": buffer_minutes,
        "reserved_start_at": start,
        "reserved_end_at": end,
        "occupied_until_at": end + timedelta(minutes=buffer_minutes),
        "run_status": "RESERVED",
    }
    db.stamp_common(run, "InstrumentRun")
    put("instrument_runs", run)
    return run


def _occupied_region(run):
    start = parse_dt(run.get("reserved_start_at"))
    end = parse_dt(run.get("reserved_end_at"))
    if start is None or end is None:
        return None
    buffer_minutes = int(run.get("decontamination_buffer_minutes") or 0)
    buffer_half = timedelta(minutes=buffer_minutes / 2.0)
    return start - buffer_half, end + buffer_half


def _check_instrument_overlap(instrument_code, section, start, end, buffer_minutes, exclude):
    buffer_half = timedelta(minutes=buffer_minutes / 2.0)
    candidate_start = start - buffer_half
    candidate_end = end + buffer_half
    for run in all_rows("instrument_runs"):
        if exclude is not None and run["id"] == exclude:
            continue
        if run.get("run_status") == "ABORTED":
            continue
        if run.get("instrument_code") != instrument_code or run.get("section") != section:
            continue
        region = _occupied_region(run)
        if region is None:
            continue
        other_start, other_end = region
        if candidate_start < other_end and other_start < candidate_end:
            raise ApiError(
                ERR_INSTRUMENT_DOUBLE_BOOKED,
                "The window collides with an existing non-aborted run once the buffer is applied.",
            )


def engine_instrument_run_abort(run):
    guard_transition("instrument_runs", "abort", INSTRUMENT_TRANSITIONS, run)
    run["run_status"] = "ABORTED"
    touch(run)
    return run


def engine_instrument_run_rebook(run, body):
    guard_transition("instrument_runs", "rebook", INSTRUMENT_TRANSITIONS, run)
    start = parse_dt(body.get("reserved_start_at"))
    end = parse_dt(body.get("reserved_end_at"))
    if start is None or end is None:
        raise ApiError(ERR_INVALID_REQUEST, "reserved_start_at and reserved_end_at are required.")
    if not start < end:
        raise ApiError(
            ERR_INSTRUMENT_DOUBLE_BOOKED,
            "reserved_start_at must fall strictly before reserved_end_at.",
        )
    buffer_minutes = int(run.get("decontamination_buffer_minutes") or 0)
    _check_instrument_overlap(
        run.get("instrument_code"),
        run.get("section"),
        start,
        end,
        buffer_minutes,
        exclude=run["id"],
    )
    run["reserved_start_at"] = start
    run["reserved_end_at"] = end
    run["occupied_until_at"] = end + timedelta(minutes=buffer_minutes)
    run["run_status"] = "RESERVED"
    touch(run)
    return run


# ---------------------------------------------------------------------------
# InterfaceBuild workflows
# ---------------------------------------------------------------------------

def engine_build_create(body):
    client = get("client_laboratories", body.get("client_laboratory_id"))
    if client is None:
        from errors import ERR_CLIENT_LABORATORY_NOT_FOUND

        raise ApiError(ERR_CLIENT_LABORATORY_NOT_FOUND, "client_laboratory_id does not resolve.")
    build = {
        "client_laboratory_id": body.get("client_laboratory_id"),
        "build_version_label": body.get("build_version_label"),
        "format": body.get("format"),
        "order_interface_enabled": bool(body.get("order_interface_enabled", False)),
        "result_interface_enabled": bool(body.get("result_interface_enabled", False)),
        "certified_at": None,
        "superseded_at": None,
        "status": "DRAFT",
    }
    db.stamp_common(build, "InterfaceBuild")
    put("interface_builds", build)
    rules.recompute_interface_status(client)
    touch(client)
    return build


def engine_build_start(build):
    guard_transition("interface_builds", "start-build", BUILD_TRANSITIONS, build)
    for other in all_rows("interface_builds"):
        if other["id"] == build["id"]:
            continue
        if other.get("client_laboratory_id") != build.get("client_laboratory_id"):
            continue
        if other.get("status") == "IN_BUILD":
            raise ApiError(
                ERR_INVALID_STATE,
                "Another build for this client is already IN_BUILD.",
            )
    if build.get("status") == "RETIRED":
        build["certified_at"] = None
        build["superseded_at"] = None
    build["status"] = "IN_BUILD"
    touch(build)
    _recompute_client_interface(build)
    return build


def engine_build_certify(build):
    guard_transition("interface_builds", "certify", BUILD_TRANSITIONS, build)
    build["status"] = "CERTIFIED"
    build["certified_at"] = iso(db.now())
    touch(build)
    for message in all_rows("result_interface_messages"):
        if message.get("status") != "HELD":
            continue
        owner = get("send_out_orders", message.get("send_out_order_id"))
        if owner is None:
            continue
        if owner.get("client_laboratory_id") != build.get("client_laboratory_id"):
            continue
        message["status"] = "VALIDATED"
        touch(message)
    _recompute_client_interface(build)
    return build


def engine_build_supersede(build):
    guard_transition("interface_builds", "supersede", BUILD_TRANSITIONS, build)
    other_certified = any(
        b.get("client_laboratory_id") == build.get("client_laboratory_id")
        and b.get("status") == "CERTIFIED"
        for b in all_rows("interface_builds")
    )
    if not other_certified:
        raise ApiError(
            ERR_INVALID_STATE,
            "Another build for this client must already be CERTIFIED before supersession.",
        )
    build["status"] = "SUPERSEDED"
    build["superseded_at"] = iso(db.now())
    touch(build)
    for message in all_rows("result_interface_messages"):
        if message.get("interface_build_id") != build["id"]:
            continue
        if message.get("status") in ("QUEUED", "VALIDATED"):
            message["status"] = "HELD"
            touch(message)
    _recompute_client_interface(build)
    return build


def engine_build_retire(build):
    guard_transition("interface_builds", "retire", BUILD_TRANSITIONS, build)
    for message in all_rows("result_interface_messages"):
        if message.get("interface_build_id") != build["id"]:
            continue
        if message.get("status") in ("QUEUED", "VALIDATED", "HELD"):
            raise ApiError(
                ERR_INVALID_STATE,
                "The build still carries live interface messages.",
            )
    build["status"] = "RETIRED"
    touch(build)
    _recompute_client_interface(build)
    return build


def engine_build_patch(build, body):
    certified = build.get("status") == "CERTIFIED" or build.get("certified_at") is not None
    if "order_interface_enabled" in body:
        build["order_interface_enabled"] = bool(body.get("order_interface_enabled"))
    if "result_interface_enabled" in body:
        build["result_interface_enabled"] = bool(body.get("result_interface_enabled"))
    if body.get("status") is not None:
        if body.get("status") == "DRAFT":
            if certified:
                raise ApiError(
                    ERR_INVALID_STATE,
                    "A certified build cannot be returned to DRAFT.",
                )
            build["status"] = "DRAFT"
        else:
            raise ApiError(ERR_INVALID_REQUEST, "Only DRAFT may be supplied as a build status.")
    touch(build)
    _recompute_client_interface(build)
    return build


def _recompute_client_interface(build):
    client = get("client_laboratories", build.get("client_laboratory_id"))
    if client is None:
        return
    rules.recompute_interface_status(client)
    touch(client)


# ---------------------------------------------------------------------------
# ResultInterfaceMessage workflows
# ---------------------------------------------------------------------------

def engine_message_create(body, actor):
    order = get("send_out_orders", body.get("send_out_order_id"))
    if order is None:
        from errors import ERR_SEND_OUT_ORDER_NOT_FOUND

        raise ApiError(ERR_SEND_OUT_ORDER_NOT_FOUND, "send_out_order_id does not resolve.")
    # Priority 4.5 runs before every business rule.
    check_occ(body, "expected_send_out_order_version", order)
    build = get("interface_builds", body.get("interface_build_id"))
    if build is None:
        from errors import ERR_INTERFACE_BUILD_NOT_FOUND

        raise ApiError(ERR_INTERFACE_BUILD_NOT_FOUND, "interface_build_id does not resolve.")
    if build.get("status") != "CERTIFIED" or build.get("client_laboratory_id") != order.get(
        "client_laboratory_id"
    ):
        raise ApiError(
            ERR_INTERFACE_BUILD_NOT_CERTIFIED,
            "The referenced build must be CERTIFIED and belong to the order's client.",
        )
    message_type = body.get("message_type")
    if message_type == "RESULT" and build.get("result_interface_enabled") is not True:
        raise ApiError(
            ERR_INTERFACE_BUILD_NOT_CERTIFIED,
            "The build does not carry outbound result traffic.",
        )
    if message_type == "INTERIM" and build.get("result_interface_enabled") is not True:
        raise ApiError(
            ERR_INTERFACE_BUILD_NOT_CERTIFIED,
            "The build does not carry outbound result traffic.",
        )
    if message_type == "RESULT":
        for line in all_rows("order_test_lines"):
            if line.get("send_out_order_id") != order["id"]:
                continue
            flag = rules.compute_result_flag(line)
            if flag in ("CRITICAL_HIGH", "CRITICAL_LOW"):
                if not line.get("critical_value_notified_to") or not line.get(
                    "critical_value_notified_at"
                ):
                    raise ApiError(
                        ERR_CRITICAL_VALUE_NOT_NOTIFIED,
                        "A critical result line lacks critical-value documentation.",
                    )
    control_id = body.get("control_id")
    for existing in all_rows("result_interface_messages"):
        if existing.get("control_id") != control_id:
            continue
        owner = get("send_out_orders", existing.get("send_out_order_id"))
        if owner is not None and owner.get("client_laboratory_id") == order.get("client_laboratory_id"):
            raise ApiError(ERR_CONTROL_ID_REUSED, "control_id is already used by this client.")

    _check_message_order_gate(order, message_type)

    message = {
        "send_out_order_id": order["id"],
        "interface_build_id": build["id"],
        "message_type": message_type,
        "control_id": control_id,
        "interpreted_comment_included": order.get("interpretive_comment") is not None,
        "discrete_field_count": None,
        "queued_at": None,
        "transmitted_at": None,
        "retry_count": 0,
        "next_retry_offset_minutes": None,
        "status": "QUEUED",
    }
    db.stamp_common(message, "ResultInterfaceMessage")
    put("result_interface_messages", message)
    if message_type == "INTERIM":
        order["order_status"] = "INTERIM_REPORTED"
        for line in all_rows("order_test_lines"):
            if line.get("send_out_order_id") != order["id"]:
                continue
            if line.get("line_status") == "IN_PROGRESS":
                line["line_status"] = "INTERIM"
                touch(line)
        message["status"] = "VALIDATED"
        message["queued_at"] = iso(db.now())
    # Queuing a message of any type bumps the owning order's version, which is what
    # makes a concurrently-read order view stale for the next writer.
    touch(order)
    touch(message)
    return message


def _check_message_order_gate(order, message_type):
    """Priority 20: the order's state must admit the queued message."""
    status = order.get("order_status")
    if message_type == "INTERIM":
        if status != "IN_TESTING":
            raise ApiError(
                ERR_INTERFACE_RESULT_GATED,
                "An INTERIM message requires the order to be IN_TESTING.",
            )
    elif message_type == "RESULT":
        if status not in ("RESULT_RELEASED", "REFLEX_PENDING", "CLOSED"):
            raise ApiError(
                ERR_INTERFACE_RESULT_GATED,
                "A RESULT message requires released results on the order.",
            )


def engine_message_validate(message):
    guard_transition("result_interface_messages", "validate", MESSAGE_TRANSITIONS, message)
    build = get("interface_builds", message.get("interface_build_id"))
    order = get("send_out_orders", message.get("send_out_order_id"))
    if message.get("status") == "FAILED":
        if int(message.get("retry_count") or 0) >= rules.RETRY_COUNT_LIMIT:
            raise ApiError(
                ERR_RETRY_LIMIT_REACHED,
                "A message with five failed attempts may no longer be validated.",
            )
    if build is None or order is None:
        raise ApiError(ERR_INTERFACE_BUILD_NOT_CERTIFIED, "The referenced build or order does not resolve.")
    if build.get("status") != "CERTIFIED" or build.get("client_laboratory_id") != order.get(
        "client_laboratory_id"
    ):
        raise ApiError(
            ERR_INTERFACE_BUILD_NOT_CERTIFIED,
            "The referenced build must be CERTIFIED and belong to the order's client.",
        )
    if int(message.get("retry_count") or 0) >= rules.RETRY_COUNT_LIMIT:
        raise ApiError(
            ERR_RETRY_LIMIT_REACHED,
            "A message with five failed attempts may no longer be validated.",
        )
    message["status"] = "VALIDATED"
    message["discrete_field_count"] = sum(
        1
        for line in all_rows("order_test_lines")
        if line.get("send_out_order_id") == order["id"]
        and line.get("line_status") in ("INTERIM", "FINAL")
    )
    touch(message)
    return message


def engine_message_transmit(message):
    guard_transition("result_interface_messages", "transmit", MESSAGE_TRANSITIONS, message)
    if int(message.get("retry_count") or 0) >= rules.RETRY_COUNT_LIMIT:
        raise ApiError(
            ERR_RETRY_LIMIT_REACHED,
            "A message with five failed attempts may no longer be transmitted.",
        )
    build = get("interface_builds", message.get("interface_build_id"))
    order = get("send_out_orders", message.get("send_out_order_id"))
    if build is None or order is None:
        raise ApiError(ERR_INTERFACE_BUILD_NOT_CERTIFIED, "The referenced build or order does not resolve.")
    if build.get("status") != "CERTIFIED" or build.get("client_laboratory_id") != order.get(
        "client_laboratory_id"
    ):
        raise ApiError(
            ERR_INTERFACE_BUILD_NOT_CERTIFIED,
            "The referenced build must be CERTIFIED and belong to the order's client.",
        )
    message["status"] = "TRANSMITTED"
    message["transmitted_at"] = iso(db.now())
    message["retry_count"] = 0
    message["next_retry_offset_minutes"] = None
    touch(message)
    if message.get("message_type") == "RESULT":
        specimen = get("specimens", order.get("specimen_id"))
        if specimen is not None and specimen.get("status") == "RESULT_PENDING_REVIEW":
            specimen["status"] = "RELEASED"
            touch(specimen)
    return message


def engine_message_fail(message):
    guard_transition("result_interface_messages", "fail", MESSAGE_TRANSITIONS, message)
    message["status"] = "FAILED"
    message["retry_count"] = int(message.get("retry_count") or 0) + 1
    message["next_retry_offset_minutes"] = rules.next_retry_offset_minutes(message["retry_count"])
    touch(message)
    return message


def engine_message_hold(message):
    guard_transition("result_interface_messages", "hold", MESSAGE_TRANSITIONS, message)
    message["status"] = "HELD"
    touch(message)
    return message


def engine_message_release_hold(message):
    guard_transition("result_interface_messages", "release-hold", MESSAGE_TRANSITIONS, message)
    build = get("interface_builds", message.get("interface_build_id"))
    if build is None or build.get("status") != "CERTIFIED":
        raise ApiError(ERR_INTERFACE_BUILD_NOT_CERTIFIED, "The referenced build must be CERTIFIED.")
    message["status"] = "VALIDATED"
    touch(message)
    return message


def engine_message_acknowledge(message, control_id):
    guard_transition("result_interface_messages", "acknowledge", MESSAGE_TRANSITIONS, message)
    if control_id is None or control_id != message.get("control_id"):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "The acknowledgement control_id must equal the message's control_id.",
        )
    message["status"] = "ACKNOWLEDGED"
    touch(message)
    order = get("send_out_orders", message.get("send_out_order_id"))
    if order is not None and message.get("message_type") == "RESULT":
        if _no_live_reflex_order(order):
            order["order_status"] = "CLOSED"
            touch(order)
    return message


def _no_live_reflex_order(order):
    terminal = {"CLOSED", "CANCELLED"}
    for other in all_rows("send_out_orders"):
        if other.get("reflex_source_order_id") != order["id"]:
            continue
        if other.get("order_status") not in terminal:
            return False
    return True


# ---------------------------------------------------------------------------
# BillingLedger workflows
# ---------------------------------------------------------------------------

def engine_ledger_create(body):
    client = get("client_laboratories", body.get("client_laboratory_id"))
    if client is None:
        from errors import ERR_CLIENT_LABORATORY_NOT_FOUND

        raise ApiError(ERR_CLIENT_LABORATORY_NOT_FOUND, "client_laboratory_id does not resolve.")
    ledger = {
        "client_laboratory_id": body.get("client_laboratory_id"),
        "billed_cents": 0,
        "voided_cents": 0,
        "net_billed_cents": 0,
        "charge_entry_count": 0,
        "status": "OPEN",
    }
    db.stamp_common(ledger, "BillingLedger")
    put("billing_ledgers", ledger)
    return ledger


def engine_ledger_void_charges(ledger, body):
    order = get("send_out_orders", body.get("send_out_order_id"))
    if order is None:
        from errors import ERR_SEND_OUT_ORDER_NOT_FOUND

        raise ApiError(ERR_SEND_OUT_ORDER_NOT_FOUND, "send_out_order_id does not resolve.")
    amount = rules.dec(body.get("void_amount_cents"))
    if order.get("billing_status") != "BILLED":
        raise ApiError(ERR_INVALID_STATE, "Only a BILLED order's charge may be voided.")
    if amount != rules.dec(order.get("order_final_charge_cents")):
        raise ApiError(
            ERR_VOID_AMOUNT_MISMATCH,
            "The void amount must exactly equal the order's final charge.",
        )
    if order.get("client_laboratory_id") != ledger.get("client_laboratory_id"):
        raise ApiError(
            ERR_VOID_AMOUNT_MISMATCH,
            "The order does not belong to this ledger's client.",
        )
    order["billing_status"] = "VOIDED"
    touch(order)
    ledger["voided_cents"] = rules.num(
        rules.round_half_up(rules.dec(ledger.get("voided_cents")) + amount, 2)
    )
    rules.recompute_ledger(ledger)
    touch(ledger)
    client = get("client_laboratories", ledger.get("client_laboratory_id"))
    if client is not None:
        refresh_client_posture(client)
    return ledger


# ---------------------------------------------------------------------------
# UtilizationAdvisory workflows
# ---------------------------------------------------------------------------

def _raise_advisory(client_laboratory_id, test_catalog_entry_id, source_order_id, advisory_type, message):
    advisory = {
        "client_laboratory_id": client_laboratory_id,
        "test_catalog_entry_id": test_catalog_entry_id,
        "source_order_id": source_order_id,
        "advisory_type": advisory_type,
        "message": message,
        "send_count": 0,
        "status": "OPEN",
    }
    db.stamp_common(advisory, "UtilizationAdvisory")
    put("utilization_advisories", advisory)
    client = get("client_laboratories", client_laboratory_id)
    if client is not None:
        rules.recompute_utilization(client)
        touch(client)
    return advisory


def engine_advisory_create(body):
    client = get("client_laboratories", body.get("client_laboratory_id"))
    if client is None:
        from errors import ERR_CLIENT_LABORATORY_NOT_FOUND

        raise ApiError(ERR_CLIENT_LABORATORY_NOT_FOUND, "client_laboratory_id does not resolve.")
    entry = get("test_catalog_entries", body.get("test_catalog_entry_id"))
    if entry is None:
        from errors import ERR_TEST_CATALOG_ENTRY_NOT_FOUND

        raise ApiError(ERR_TEST_CATALOG_ENTRY_NOT_FOUND, "test_catalog_entry_id does not resolve.")
    source_order_id = body.get("source_order_id")
    if source_order_id is not None and get("send_out_orders", source_order_id) is None:
        from errors import ERR_SEND_OUT_ORDER_NOT_FOUND

        raise ApiError(ERR_SEND_OUT_ORDER_NOT_FOUND, "source_order_id does not resolve.")
    return _raise_advisory(
        client_laboratory_id=client["id"],
        test_catalog_entry_id=entry["id"],
        source_order_id=source_order_id,
        advisory_type=body.get("advisory_type"),
        message=body.get("message"),
    )


def engine_advisory_acknowledge(advisory):
    client = get("client_laboratories", advisory.get("client_laboratory_id"))
    # PRD 3.9: delivery happens at one of two moments, each of which increments
    # send_count exactly once — the client's recorded receipt, or the client's
    # requirement publication (which is where an advisory raised during
    # onboarding is delivered, and which is run by engine_client_publish_
    # requirements). The two are distinct paths, not a first-then-second
    # delivery, so the initial OPEN -> SENT rung is recorded here as SENT rather
    # than jumping straight to ACKNOWLEDGED.
    if advisory.get("status") == "OPEN":
        if (client or {}).get("onboarding_status") != "COMPLETE":
            raise ApiError(
                ERR_INVALID_STATE,
                "The client's onboarding_status must be COMPLETE for delivery.",
            )
        advisory["status"] = "SENT"
        advisory["send_count"] = int(advisory.get("send_count") or 0) + 1
        touch(advisory)
    guard_transition("utilization_advisories", "acknowledge", ADVISORY_TRANSITIONS, advisory)
    advisory["status"] = "ACKNOWLEDGED"
    touch(advisory)
    return advisory


def engine_advisory_dismiss(advisory):
    guard_transition("utilization_advisories", "dismiss", ADVISORY_TRANSITIONS, advisory)
    advisory["status"] = "DISMISSED"
    touch(advisory)
    return advisory


def engine_advisory_escalate(advisory):
    guard_transition("utilization_advisories", "escalate", ADVISORY_TRANSITIONS, advisory)
    if int(advisory.get("send_count") or 0) < 2:
        raise ApiError(
            ERR_INVALID_STATE,
            "Escalation requires send_count of at least two.",
        )
    advisory["status"] = "ESCALATED"
    touch(advisory)
    client = get("client_laboratories", advisory.get("client_laboratory_id"))
    if client is not None:
        forward, settled = rules.recompute_utilization(client)
        client["forward_utilization_score"] = forward
        client["settled_utilization_score"] = settled
        touch(client)
    return advisory