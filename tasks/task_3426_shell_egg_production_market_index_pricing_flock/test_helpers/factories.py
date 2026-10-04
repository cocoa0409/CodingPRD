"""Payload factories — one per creatable resource, input fields only.

Optional fields are included only when explicitly supplied, so factories never
smuggle a client-chosen default into a slot the PRD leaves to the server.
"""

DEFAULT_COMPLEX = {
    "name": "Heartland Layers",
    "region_code": "MIDWEST",
    "mill_receiving_tons_per_day": 100,
}

DEFAULT_COMMITMENT_WINDOW = ("2026-09-01T00:00:00Z", "2027-03-01T00:00:00Z")


def create_complex_payload(**overrides) -> dict:
    payload = dict(DEFAULT_COMPLEX)
    payload.update(overrides)
    return payload


def create_house_payload(
    house_code="H1", housing_style="CONVENTIONAL", capacity_hens=100_000,
    **overrides,
) -> dict:
    payload = {
        "house_code": house_code,
        "housing_style": housing_style,
        "capacity_hens": capacity_hens,
    }
    payload.update(overrides)
    return payload


def create_certification_payload(
    program="CAGE_FREE",
    auditor_name="Humane Farm Auditors",
    scheduled_date="2026-09-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "program": program,
        "auditor_name": auditor_name,
        "scheduled_date": scheduled_date,
    }
    payload.update(overrides)
    return payload


def record_result_payload(result="PASSED") -> dict:
    return {"result": result}


def create_flock_payload(
    flock_code="F1",
    program="CONVENTIONAL",
    ownership="OWNED",
    placement_date="2026-09-01T00:00:00Z",
    placed_hen_count=10_000,
    grower_name=None,
    **overrides,
) -> dict:
    payload = {
        "flock_code": flock_code,
        "program": program,
        "ownership": ownership,
        "placement_date": placement_date,
        "placed_hen_count": placed_hen_count,
    }
    if grower_name is not None:
        payload["grower_name"] = grower_name
    payload.update(overrides)
    return payload


def create_disease_event_payload(
    pathogen="HPAI",
    detection_date="2026-09-01T00:00:00Z",
    scope_house_ids=(),
    **overrides,
) -> dict:
    payload = {
        "pathogen": pathogen,
        "detection_date": detection_date,
        "scope_house_ids": list(scope_house_ids),
    }
    payload.update(overrides)
    return payload


def create_depopulation_order_payload(house_id, disposal_method="INCINERATION") -> dict:
    return {"house_id": house_id, "disposal_method": disposal_method}


def create_quotation_payload(
    region_code="MIDWEST",
    size_class="LARGE",
    price_cents_per_dozen=150,
    effective_date="2026-09-07T00:00:00Z",
    source=None,
    **overrides,
) -> dict:
    payload = {
        "region_code": region_code,
        "size_class": size_class,
        "price_cents_per_dozen": price_cents_per_dozen,
        "effective_date": effective_date,
    }
    if source is not None:
        payload["source"] = source
    payload.update(overrides)
    return payload


def create_customer_payload(
    name="Sunrise Grocers", segment="RETAIL", credit_limit_cents=500_000_000,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "segment": segment,
        "credit_limit_cents": credit_limit_cents,
    }
    payload.update(overrides)
    return payload


def create_commitment_payload(
    program="CONVENTIONAL",
    region_code="MIDWEST",
    weekly_dozen_committed=100_000,
    price_adjustment_cents_per_dozen=0,
    effective_from=DEFAULT_COMMITMENT_WINDOW[0],
    effective_to=DEFAULT_COMMITMENT_WINDOW[1],
    cage_free_transition_deadline=None,
    required_cage_free_pct=None,
    **overrides,
) -> dict:
    payload = {
        "program": program,
        "region_code": region_code,
        "weekly_dozen_committed": weekly_dozen_committed,
        "price_adjustment_cents_per_dozen": price_adjustment_cents_per_dozen,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    if cage_free_transition_deadline is not None:
        payload["cage_free_transition_deadline"] = cage_free_transition_deadline
    if required_cage_free_pct is not None:
        payload["required_cage_free_pct"] = required_cage_free_pct
    payload.update(overrides)
    return payload


def create_order_payload(
    ship_week_start,
    dozen_ordered,
    size_class,
    expected_commitment_version,
    **overrides,
) -> dict:
    payload = {
        "ship_week_start": ship_week_start,
        "dozen_ordered": dozen_ordered,
        "size_class": size_class,
        "expected_commitment_version": expected_commitment_version,
    }
    payload.update(overrides)
    return payload


def dispute_payload(reason="dispute reason") -> dict:
    return {"reason": reason}


def create_feed_contract_payload(
    complex_id,
    commodity="CORN",
    total_tons=100,
    basis_cents_per_ton=2_000,
    spot_reference_cents_per_ton=17_000,
    delivery_start="2026-09-01T00:00:00Z",
    delivery_end="2026-09-30T00:00:00Z",
    is_organic_certified=False,
    **overrides,
) -> dict:
    payload = {
        "complex_id": complex_id,
        "commodity": commodity,
        "total_tons": total_tons,
        "basis_cents_per_ton": basis_cents_per_ton,
        "spot_reference_cents_per_ton": spot_reference_cents_per_ton,
        "delivery_start": delivery_start,
        "delivery_end": delivery_end,
        "is_organic_certified": is_organic_certified,
    }
    payload.update(overrides)
    return payload


def hedge_payload(hedged_tons, hedge_futures_cents_per_ton) -> dict:
    return {
        "hedged_tons": hedged_tons,
        "hedge_futures_cents_per_ton": hedge_futures_cents_per_ton,
    }


def receive_payload(tons, spot_cents_per_ton) -> dict:
    return {"tons": tons, "spot_cents_per_ton": spot_cents_per_ton}


def create_feed_batch_payload(program="CONVENTIONAL", corn_tons=0, soybean_tons=0) -> dict:
    return {
        "program": program,
        "corn_tons": corn_tons,
        "soybean_tons": soybean_tons,
    }


def create_packing_run_payload(
    program, dozen_input, run_date, expected_complex_version
) -> dict:
    return {
        "program": program,
        "dozen_input": dozen_input,
        "run_date": run_date,
        "expected_complex_version": expected_complex_version,
    }


def create_capital_project_payload(
    house_id,
    investment_cents=750_000_000,
    target_style="CAGE_FREE",
    construction_weeks=6,
    **overrides,
) -> dict:
    payload = {
        "house_id": house_id,
        "investment_cents": investment_cents,
        "target_style": target_style,
        "construction_weeks": construction_weeks,
    }
    payload.update(overrides)
    return payload
