"""Payload factories — one per creation endpoint, client-supplied fields only."""

from .constants import TEST_DEFAULTS


def create_client_payload(**overrides) -> dict:
    payload = {"full_name": "Dana Reyes", "email": "dana@example.com"}
    payload.update(overrides)
    return payload


def create_lender_payload(**overrides) -> dict:
    payload = {
        "name": "Cornerstone Construction Bank",
        "retainage_pct": TEST_DEFAULTS["RETAINAGE_PCT"],
        "max_cumulative_draw_pct": TEST_DEFAULTS["MAX_CUMULATIVE_DRAW_PCT"],
        "review_window_days": TEST_DEFAULTS["REVIEW_WINDOW_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_staff_member_payload(**overrides) -> dict:
    payload = {"full_name": "Pat Morgan", "staff_function": "PROJECT_MANAGER"}
    payload.update(overrides)
    return payload


def create_subcontractor_payload(**overrides) -> dict:
    payload = {
        "company_name": "Ridgeline Framing",
        "trade": "FRAMING",
        "lead_time_days": 5,
        "crew_capacity": 1,
        "waiver_required": True,
    }
    payload.update(overrides)
    return payload


def create_project_payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "address": "18 Kestrel Ridge",
        "contract_type": "FIXED_PRICE",
        "base_contract_amount": TEST_DEFAULTS["BASE_CONTRACT_AMOUNT"],
        "target_substantial_completion_date": TEST_DEFAULTS[
            "TARGET_SUBSTANTIAL_COMPLETION"
        ],
    }
    payload.update(overrides)
    return payload


def create_allowance_item_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "category": "FLOORING",
        "allowance_amount": TEST_DEFAULTS["ALLOWANCE_AMOUNT"],
        "selection_deadline": TEST_DEFAULTS["SELECTION_DEADLINE"],
    }
    payload.update(overrides)
    return payload


def create_selection_payload(
    allowance_item_id: str, expected_allowance_item_version: int, **overrides
) -> dict:
    payload = {
        "allowance_item_id": allowance_item_id,
        "vendor_name": "Northwood Millwork",
        "vendor_quote_amount": 21000.00,
        "freight_amount": 1500.00,
        "install_amount": 1500.00,
        "lead_time_days": 20,
        "expected_allowance_item_version": expected_allowance_item_version,
    }
    payload.update(overrides)
    return payload


def create_change_order_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "origin": "CLIENT_REQUEST",
        "scope_description": "Add a screened porch",
        "direct_cost": 40000.00,
        "schedule_impact_days": 10,
    }
    payload.update(overrides)
    return payload


def create_schedule_task_payload(project_id: str, subcontractor_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "subcontractor_id": subcontractor_id,
        "task_name": "Frame shell",
        "planned_start": TEST_DEFAULTS["FRAME_TASK_START"],
        "planned_finish": TEST_DEFAULTS["FRAME_TASK_FINISH"],
    }
    payload.update(overrides)
    return payload


def create_cost_entry_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "entry_type": "SUBCONTRACT_INVOICE",
        "cost_code": "06-100",
        "amount": 10000.10,
        "incurred_at": "2026-08-10T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_draw_request_payload(
    project_id: str, expected_project_version: int, **overrides
) -> dict:
    payload = {
        "project_id": project_id,
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def receive_lien_waiver_payload(**overrides) -> dict:
    payload = {
        "waiver_type": "CONDITIONAL_PROGRESS",
        "through_date": TEST_DEFAULTS["PERIOD_END"],
        "amount_covered": 10000.10,
        "signed_document_ref": "waiver-001",
    }
    payload.update(overrides)
    return payload


def create_defect_ticket_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "phase": "PUNCH",
        "room": "Foyer",
        "description": "Scuffed base trim",
        "severity": "COSMETIC",
        "category": "WORKMANSHIP",
    }
    payload.update(overrides)
    return payload


def create_photo_document_payload(**overrides) -> dict:
    payload = {"captured_at": "2026-08-01T00:00:00.000Z", "caption": "Footings poured"}
    payload.update(overrides)
    return payload
