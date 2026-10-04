"""Payload factories — one per entity, input fields only."""

_SHOP_COUNTER = {"n": 0}


def _next_seq(name: str) -> int:
    _SHOP_COUNTER[name] = _SHOP_COUNTER.get(name, 0) + 1
    return _SHOP_COUNTER[name]


def create_shop_payload(**overrides) -> dict:
    n = _next_seq("shop")
    defaults = {
        "legal_name": f"Test Body Shop {n}",
        "state_code": "CA",
        "zip_code": "90001",
        "latitude": 34.05,
        "longitude": -118.24,
    }
    defaults.update(overrides)
    return defaults


def create_requirement_payload(**overrides) -> dict:
    n = _next_seq("req")
    defaults = {
        "requirement_code": f"EQ-T{n:03d}",
        "category": "EQUIPMENT",
        "description": f"Test requirement {n}",
        "severity_if_failed": "MINOR",
        "effective_from": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2027-08-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def create_attestation_payload(requirement_id, expected_shop_version, **overrides) -> dict:
    defaults = {
        "requirement_id": requirement_id,
        "evidence_uri": "s3://evidence/att.pdf",
        "expected_shop_version": expected_shop_version,
    }
    defaults.update(overrides)
    return defaults


def schedule_audit_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-09-02T09:00:00Z",
        "scheduled_end": "2026-09-02T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    n = _next_seq("tech")
    defaults = {
        "full_name": f"Tech Nic {n}",
        "tech_role": "NON_STRUCTURAL",
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(**overrides) -> dict:
    n = _next_seq("course")
    defaults = {
        "course_code": f"TR-T{n:03d}",
        "title": f"Test Course {n}",
        "required_for_roles": ["NON_STRUCTURAL"],
        "validity_months": 12,
        "credit_hours": 4,
    }
    defaults.update(overrides)
    return defaults


def create_completion_payload(course_id, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "completed_at": "2026-08-15T00:00:00Z",
        "proof_uri": "s3://proof/c.pdf",
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(expected_shop_version, technician_id, **overrides) -> dict:
    n = _next_seq("vin")
    defaults = {
        "expected_shop_version": expected_shop_version,
        "vin": f"1HGCV1F34LA{n:06d}"[-17:].rjust(17, "0"),
        "vehicle_model_year": 2015,
        "estimate_total_cents": 10000,
        "assigned_technician_id": technician_id,
    }
    defaults.update(overrides)
    return defaults


def create_procedure_step_payload(step_type, technician_id, performed_at, result, **overrides) -> dict:
    defaults = {
        "step_type": step_type,
        "performed_by_technician_id": technician_id,
        "performed_at": performed_at,
        "result": result,
    }
    if step_type in ("PRE_SCAN", "POST_SCAN") and result != "NOT_APPLICABLE":
        defaults["scan_report_uri"] = "s3://scans/report.json"
    defaults.update(overrides)
    return defaults


def create_part_line_payload(**overrides) -> dict:
    n = _next_seq("part")
    defaults = {
        "part_number": f"PN-{n:04d}",
        "part_class": "OE",
        "unit_cost_cents": 5000,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "claimant_contact": "customer@example.com",
        "defect_category": "WORKMANSHIP",
        "claim_amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_insurer_relation_payload(**overrides) -> dict:
    n = _next_seq("ins")
    defaults = {
        "insurer_code": f"INS-{n:03d}",
        "discount_pct_bps": 500,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    n = _next_seq("ref")
    defaults = {
        "consumer_zip": "90001",
        "source_type": "CONSUMER_DIRECT",
        "source_reference": "WEB",
        "vin": f"2HGFC2F59LH{n:06d}"[-17:].rjust(17, "0"),
    }
    defaults.update(overrides)
    return defaults
