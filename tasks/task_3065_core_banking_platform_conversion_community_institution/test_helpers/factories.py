"""Payload factories — one per entity, input fields only."""


def create_project_payload(**overrides) -> dict:
    defaults = {
        "institution_name": "First Community Bank",
        "incumbent_core_name": "LegacyCore",
        "target_core_name": "Fiserv DNA",
    }
    defaults.update(overrides)
    return defaults


def create_product_type_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "product_code": "DDA-STD",
        "kind": "DEPOSIT",
        "accrual_method": "ACT_365",
        "rate": 0.03,
        "statement_frequency": "MONTHLY",
    }
    defaults.update(overrides)
    return defaults


def create_gl_account_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "gl_code": "GL-1000",
        "description": "Demand deposits",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(project_id, product_type_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "legacy_account_number": "L-1001",
        "account_type": "DEPOSIT",
        "product_type_id": product_type_id,
        "opening_principal_cents": 100000,
        "statement_cycle_day": 1,
        "accrual_start_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_mock_run_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "run_label": "MOCK-1",
    }
    defaults.update(overrides)
    return defaults


def create_ancillary_system_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "name": "CARDS-1",
        "category": "CARDS",
        "interface_version": "v2",
    }
    defaults.update(overrides)
    return defaults


def create_training_session_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "branch_name": "MAIN",
        "scheduled_start": "2026-09-02T09:00:00Z",
        "scheduled_end": "2026-09-02T12:00:00Z",
        "capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "employee_code": "E1",
        "full_name": "Teller One",
        "branch_name": "MAIN",
        "role_scope": "TELLER",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(session_id, employee_id, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "employee_id": employee_id,
    }
    defaults.update(overrides)
    return defaults


def create_comm_payload(project_id, account_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "account_id": account_id,
        "comm_type": "ACCOUNT_NUMBER_CHANGE",
        "wave": 1,
    }
    defaults.update(overrides)
    return defaults


def create_defect_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "title": "post-conversion defect",
        "severity": "SEV2",
    }
    defaults.update(overrides)
    return defaults


def create_service_credit_payload(project_id, month, defect_ids, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "month": month,
        "defect_ids": list(defect_ids),
    }
    defaults.update(overrides)
    return defaults


def plan_cutover_payload(**overrides) -> dict:
    defaults = {
        "cutover_scheduled_date": "2026-09-20",
        "file_freeze_start": "2026-09-19T18:00:00Z",
        "go_no_go_checkpoint": "2026-09-19T20:00:00Z",
        "reopen_target": "2026-09-21T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_task_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "task_name": "extract",
        "sequence": 1,
        "conversion_window_start": "2026-09-19T19:00:00Z",
        "conversion_window_end": "2026-09-19T21:00:00Z",
        "owner_role": "CONVERSION_ENGINEER",
    }
    defaults.update(overrides)
    return defaults
