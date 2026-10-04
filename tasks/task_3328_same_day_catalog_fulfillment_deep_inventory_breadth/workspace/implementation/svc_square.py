"""Square-footage consignment domain: the cut-pipe quote and its two
commitment variants.

A request is quoted by a CustomerAccount and walked as a cut list ordered by
`cut_list_ordinal`. Two commitment figures are reported at once -- a
forward-looking allowance that counts cut-in-progress pipe, and an
on-hand-only allowance that swaps it for finished goods. The variant a
request *reports* is pinned by `committed_variant`: FORWARD_LOOKING while the
request is QUOTED, ON_HAND_ONLY from the first recorded cut onward.
"""

from calculations import pipe_length_commitment_two_variant
from common import (invalid_request, require, require_int, require_str)
from db import created_key
from errors import ApiError, not_found


def get_square_request(store, request_id):
    record = store.square_footage_requests.get(request_id)
    if record is None:
        raise not_found("ERR_INVALID_REQUEST",
                        "No square-footage request exists for id '%s'." % request_id)
    return record


def square_lines_of(store, request_id):
    rows = [line for line in store.square_footage_lines.values()
            if line.get("request_id") == request_id]
    return sorted(rows, key=lambda l: (l.get("cut_list_ordinal", 0), created_key(l)))


def _available_stock_mm(store):
    """Available pipe stock in millimetres.

    No catalog stock row carries pipe stock, so the yard's available figure is
    the pool of on-hand units across every stock row, expressed in millimetres.
    """
    units = sum(row.get("on_hand_units", 0) or 0 for row in store.stock_rows.values())
    from calculations import UNIT_MM_PER_FOOT
    return units * UNIT_MM_PER_FOOT


def _recompute(request, lines, store):
    """Recompute both variants and pin the reported one.

    While the request is QUOTED the reported variant is FORWARD_LOOKING and
    `prior_committed_length_feet` is seeded equal to `committed_length_feet`.
    At the first cut the variant flips to ON_HAND_ONLY and the prior figure
    captures the forward-looking value before the flip.
    """
    forward, on_hand = pipe_length_commitment_two_variant(
        lines, _available_stock_mm(store))

    already_cut = any(line.get("line_status") == "CUT" for line in lines)
    if already_cut:
        request["committed_variant"] = "ON_HAND_ONLY"
        if request.get("_variant_pinned") != "ON_HAND_ONLY":
            request["prior_committed_length_feet"] = forward
            request["_variant_pinned"] = "ON_HAND_ONLY"
        request["committed_length_feet"] = on_hand
    else:
        request["committed_variant"] = "FORWARD_LOOKING"
        request["committed_length_feet"] = forward
        request["prior_committed_length_feet"] = forward
    return request


def create_square_request(store, user_id, body):
    account_id = require_str(body, "account_id")
    from svc_orders import get_account
    account = get_account(store, account_id)

    raw_lines = require(body, "lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise invalid_request("Field 'lines' must be a non-empty array.")

    seen = set()
    entries = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise invalid_request("Every entry of 'lines' must be an object.")
        ordinal = require_int(entry, "cut_list_ordinal", 1)
        if ordinal in seen:
            raise invalid_request(
                "Field 'cut_list_ordinal' must be unique within a request.")
        seen.add(ordinal)
        feet = require_int(entry, "requested_feet", 1)
        entries.append((ordinal, feet))

    request = {
        "account_id": account_id,
        "request_status": "QUOTED",
        "committed_length_feet": 0,
        "committed_variant": "FORWARD_LOOKING",
        "prior_committed_length_feet": 0,
        "_variant_pinned": "FORWARD_LOOKING",
    }
    store.stamp(request)
    store.square_footage_requests[request["id"]] = request

    for ordinal, feet in entries:
        line = {
            "request_id": request["id"],
            "cut_list_ordinal": ordinal,
            "requested_feet": feet,
            "line_status": "PLANNED",
            "line_committed_feet": 0,
        }
        store.stamp(line)
        store.square_footage_lines[line["id"]] = line

    _recompute(request, square_lines_of(store, request["id"]), store)
    return request


def cut_square_request(store, request, body):
    """Record a cut against a cut-list ordinal and flip the variant."""
    status = request.get("request_status")
    if status in ("FULFILLED", "RETURNED"):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "Square-footage request '%s' is already terminal." % request["id"], 409)
    if status not in ("QUOTED", "CUTTING"):
        raise ApiError("ERR_INVALID_STATE",
                       "Square-footage request '%s' cannot take a cut from status '%s'."
                       % (request["id"], status), 409)

    ordinal = require_int(body, "cut_list_ordinal", 1)
    target = None
    for line in square_lines_of(store, request["id"]):
        if line.get("cut_list_ordinal") == ordinal:
            target = line
            break
    if target is None:
        raise invalid_request(
            "Field 'cut_list_ordinal' %s does not belong to this request." % ordinal)

    target["line_status"] = "CUT"
    store.touch(target)
    request["request_status"] = "CUTTING"
    _recompute(request, square_lines_of(store, request["id"]), store)
    store.touch(request)
    return request


def square_line_matches(line, args):
    request_id = args.get("request_id")
    if request_id and line.get("request_id") != request_id:
        return False
    line_status = args.get("line_status")
    if line_status and line.get("line_status") != line_status:
        return False
    return True