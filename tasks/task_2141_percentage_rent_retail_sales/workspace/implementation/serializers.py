"""Per-entity response representations."""

from core import clock_now, serialize


def ser(rec):
    return serialize(rec)


def ser_report(rec):
    out = serialize(rec)
    delinquent = bool(
        (rec["status"] == "PENDING" and rec["due_at"] is not None and clock_now() > rec["due_at"])
        or rec["source"] == "LANDLORD_ESTIMATE"
    )
    out["is_delinquent"] = delinquent
    return out


def report_is_delinquent(rec):
    return bool(
        (rec["status"] == "PENDING" and rec["due_at"] is not None and clock_now() > rec["due_at"])
        or rec["source"] == "LANDLORD_ESTIMATE"
    )
