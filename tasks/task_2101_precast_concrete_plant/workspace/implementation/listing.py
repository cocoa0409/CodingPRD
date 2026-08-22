"""List helper: default sort by created_at ascending, then paginate (PRD 2.3)."""
import db
import response
import validation


def list_response(rows, serializer):
    limit, offset = validation.pagination()
    ordered = db.by_seq(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return response.array_response(
        [serializer(row) for row in page], limit, offset, total)
