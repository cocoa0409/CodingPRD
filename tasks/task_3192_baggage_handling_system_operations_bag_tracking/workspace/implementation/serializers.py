"""JSON serializers for every principal resource."""

from db import parse_iso
import calc

COMMON = ("id", "created_at", "updated_at", "version")


def _audit(value):
    """`created_at`/`updated_at` are published with three fractional digits."""
    if isinstance(value, str):
        moment = parse_iso(value)
        if moment is not None:
            return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)
    return value


def _pick(row, names):
    out = {}
    for name in names:
        if name in row:
            out[name] = row[name]
    return out


def _base(row):
    out = _pick(row, COMMON)
    for name in ("created_at", "updated_at"):
        if name in out:
            out[name] = _audit(out[name])
    return out


def station(row):
    out = _base(row)
    out.update(_pick(row, (
        "code", "name", "sorter_capacity_bags", "posture", "outage_active",
        "outage_started_utc", "active_bag_count", "manual_queue_depth",
        "open_liability_cents", "settled_liability_cents", "ops_run_index",
    )))
    return out


def airline(row):
    out = _base(row)
    out.update(_pick(row, (
        "code", "name", "interline_agreement_active", "max_excess_weight_lb",
        "excess_weight_fee_cents", "compensation_cap_cents",
    )))
    return out


def makeup_area(row):
    out = _base(row)
    out.update(_pick(row, (
        "station_id", "code", "capacity_slots", "buffer_minutes",
        "occupied_slots", "released_slots", "free_slots", "status",
    )))
    return out


def lane(row):
    out = _base(row)
    out.update(_pick(row, ("station_id", "lane_code", "status", "last_event_end_utc")))
    return out


def flight(row):
    out = _base(row)
    out.update(_pick(row, (
        "station_id", "airline_id", "flight_number", "bank_code",
        "scheduled_departure_utc", "sortation_open_utc", "sortation_close_utc",
        "status", "makeup_ready", "loaded_bag_count",
    )))
    return out


def scan_trail(store, bag_id):
    rows = calc.scans_of(store, bag_id)
    rows.sort(key=lambda r: (r["scan_utc"], r["created_at"], r.get("_seq", 0)))
    return [{"scan_point": r["scan_point"], "scan_source": r["scan_source"],
             "scan_utc": r["scan_utc"], "created_at": _audit(r["created_at"])}
            for r in rows]


def scan(row):
    out = _base(row)
    out.update(_pick(row, ("bag_id", "scan_point", "scan_source", "scan_utc", "result")))
    return out


def bag(store, row):
    out = _base(row)
    out.update(_pick(row, (
        "station_id", "flight_id", "makeup_area_id", "tag_number", "passenger_name",
        "passenger_ref", "itinerary_type", "weight_lb", "scale_weight_lb",
        "weight_variance_lb", "length_in", "width_in", "height_in", "linear_in",
        "custody_status", "screening_status", "routing_class", "excess_weight_fee_cents",
        "handling_charge_cents", "priority_score", "assigned_makeup_utc", "loaded_utc",
        "delivered_utc", "ops_run_index_at_acceptance", "anomaly_note", "rush_declared",
        "duplicate_flag",
    )))
    out["linear_in"] = row["linear_in"]
    out["duplicate_flag"] = calc.duplicate_flag(store, row)
    out["rush_declared"] = calc.rush_declared(store, row)
    out["priority_score"] = calc.priority_score(store, row)
    out["oversize_handling_fee_cents"] = calc.oversize_handling_fee(store, row)
    out["manual_sortation_delay_minutes"] = calc.manual_sortation_delay(store, row)
    out["screen_alarm_resolution_time_minutes"] = calc.screen_alarm_resolution_time(store, row)
    out["scan_trail"] = scan_trail(store, row["id"])
    return out


def screening(row):
    out = _base(row)
    out.update(_pick(row, (
        "bag_id", "lane_id", "start_utc", "end_utc", "alarm_code", "status",
        "resolution_outcome", "resolved_by",
    )))
    return out


def inspection(row):
    out = _base(row)
    out.update(_pick(row, (
        "screening_event_id", "station_id", "queue_position", "status",
        "assigned_to", "due_utc", "resolution",
    )))
    return out


def connection(row):
    out = _base(row)
    out.update(_pick(row, (
        "bag_id", "inbound_flight_id", "onward_flight_id", "required_mct_minutes",
        "connect_slack_minutes", "status", "rush_declared_utc",
    )))
    return out


def special_item(row):
    out = _base(row)
    out.update(_pick(row, (
        "bag_id", "item_type", "declared_value_cents", "requires_manual_screening",
        "handling_fee_cents", "liability_cap_cents", "waived_fee_cents",
    )))
    return out


def report(row):
    out = _base(row)
    out.update(_pick(row, (
        "bag_id", "station_id", "report_type", "status", "delivery_method",
        "compensation_offer_cents", "claim_status", "claim_amount_cents",
        "approved_cents", "compensation_settled_cents", "final_liability_cents",
        "outage_context",
    )))
    return out


def claim(row):
    out = _base(row)
    out.update(_pick(row, (
        "mishandled_report_id", "requested_amount_cents", "decision",
        "decided_by", "decided_utc",
    )))
    return out


def delivery(row):
    out = _base(row)
    out.update(_pick(row, (
        "bag_id", "mishandled_report_id", "method", "address_note", "scheduled_utc",
        "status", "delivered_utc", "courier_ref", "proof_required",
    )))
    return out


def tracking(store, bag_row):
    trail = scan_trail(store, bag_row["id"])
    last_point = trail[-1]["scan_point"] if trail else None
    last_utc = trail[-1]["scan_utc"] if trail else None
    conn = calc.connection_of(store, bag_row["id"])
    open_reports = sum(1 for r in calc.reports_of(store, bag_row["id"])
                       if r["status"] not in ("CLOSED",))
    return {
        "tag_number": bag_row["tag_number"],
        "custody_status": bag_row["custody_status"],
        "screening_status": bag_row["screening_status"],
        "last_scan_point": last_point,
        "last_scan_utc": last_utc,
        "scan_trail": trail,
        "onboard": bag_row["custody_status"] == "LOADED",
        "connection_status": conn["status"] if conn else None,
        "manual_sortation_delay_minutes": calc.manual_sortation_delay(store, bag_row),
        "open_reports": open_reports,
    }


def _order_key(row):
    return (row["created_at"], row.get("_seq", 0))


def sort_rows(rows):
    return sorted(rows, key=_order_key)