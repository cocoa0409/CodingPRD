"""Response envelope helpers (PRD S2.2 / scaffold response_envelope).

Success:  {meta: {api_request_id, api_request_timestamp, [limit, offset,
           total_count, has_more]}, response_type: "object"|"array", data: ...}
Error:    {meta: {api_request_id, api_request_timestamp}, response_type: "error",
           data: {error_id, message}}
"""

from flask import jsonify

from utils import fmt_ts, new_request_id, utc_now_dt


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(utc_now_dt()),
    }


class ListPayload:
    """A list-shaped success response carrying the pagination block in `meta`."""

    def __init__(self, items, limit, offset, total_count):
        self.items = items
        self.limit = limit
        self.offset = offset
        self.total_count = total_count

    def render(self):
        meta = _meta()
        meta["limit"] = self.limit
        meta["offset"] = self.offset
        meta["total_count"] = self.total_count
        meta["has_more"] = (self.offset + len(self.items)) < self.total_count
        return (
            jsonify({"meta": meta, "response_type": "array", "data": self.items}),
            200,
        )


def object_success(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def error_body(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )