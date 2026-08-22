"""Row factories that more than one route module needs."""
from decimal import Decimal

from store import base_row


def new_change_order_row(project_id, origin, scope_description, direct_cost,
                         schedule_impact_days=0, source_allowance_item_id=None):
    row = base_row()
    row.update({
        "project_id": project_id,
        "source_allowance_item_id": source_allowance_item_id,
        "priced_by_staff_id": None,
        "submitted_by_staff_id": None,
        "origin": origin,
        "scope_description": scope_description,
        "direct_cost": direct_cost,
        "schedule_impact_days": int(schedule_impact_days or 0),
        "markup_rate_applied": None,
        "contingency_rate_applied": None,
        "priced_amount": None,
        "status": "DRAFT",
        "revision_count": 0,
        "revision_note": None,
        "void_reason": None,
        "priced_at": None,
        "submitted_at": None,
        "client_response_due_at": None,
        "decided_at": None,
    })
    return row


def new_lien_waiver_row(draw_request_id, subcontractor_id, required_waiver_type,
                        required_amount):
    row = base_row()
    row.update({
        "draw_request_id": draw_request_id,
        "subcontractor_id": subcontractor_id,
        "required_waiver_type": required_waiver_type,
        "required_amount": required_amount,
        "waiver_type": None,
        "through_date": None,
        "amount_covered": None,
        "signed_document_ref": None,
        "status": "REQUESTED",
        "resubmit_count": 0,
        "received_at": None,
        "verified_at": None,
        "rejected_at": None,
        "voided_at": None,
    })
    return row
