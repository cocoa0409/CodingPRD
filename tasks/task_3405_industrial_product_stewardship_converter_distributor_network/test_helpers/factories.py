"""Payload factories — one per write endpoint, input fields only (PRD §4).

Optional fields default to None and are omitted from the payload when unset,
so a factory-produced body never carries keys the caller did not ask for.
"""


def _drop_none(payload):
    return {k: v for k, v in payload.items() if v is not None}


def clock_payload(current_utc):
    return {"current_utc": current_utc}


def jurisdiction_payload(code="DE", name=None, declaration_threshold_ppm=1000,
                         full_disclosure_threshold_ppm=10000, review_sla_days=None,
                         **overrides):
    payload = {
        "code": code,
        "name": name if name is not None else f"Jurisdiction {code}",
        "declaration_threshold_ppm": declaration_threshold_ppm,
        "full_disclosure_threshold_ppm": full_disclosure_threshold_ppm,
        "review_sla_days": review_sla_days,
    }
    payload = _drop_none(payload)
    payload.update(overrides)
    return payload


def substance_payload(cas_number="50-00-0", name="Formaldehyde",
                      restriction_class="RESTRICTED", **overrides):
    payload = {
        "cas_number": cas_number,
        "name": name,
        "restriction_class": restriction_class,
    }
    payload.update(overrides)
    return payload


def formulation_payload(product_code="F-100", name="Acrylic foam base",
                        base_polymer_family="acrylic", **overrides):
    payload = {
        "product_code": product_code,
        "name": name,
        "base_polymer_family": base_polymer_family,
    }
    payload.update(overrides)
    return payload


def component_payload(formulation_id, substance_id, concentration_ppm=5000, **overrides):
    payload = {
        "formulation_id": formulation_id,
        "substance_id": substance_id,
        "concentration_ppm": concentration_ppm,
    }
    payload.update(overrides)
    return payload


def clearance_payload(formulation_id, jurisdiction_id,
                      disclosure_package_level="FULL_DISCLOSURE", **overrides):
    payload = {
        "formulation_id": formulation_id,
        "jurisdiction_id": jurisdiction_id,
        "disclosure_package_level": disclosure_package_level,
    }
    payload.update(overrides)
    return payload


def decision_payload(decision="CLEARED", reviewer_note=None, **overrides):
    payload = _drop_none({"decision": decision, "reviewer_note": reviewer_note})
    payload.update(overrides)
    return payload


def converter_payload(name="ConvertOne GmbH", home_territory_code="DE", **overrides):
    payload = {"name": name, "home_territory_code": home_territory_code}
    payload.update(overrides)
    return payload


def audit_payload(audit_score=80, audit_standard="ISO9001", **overrides):
    payload = {"audit_score": audit_score, "audit_standard": audit_standard}
    payload.update(overrides)
    return payload


def distributor_payload(name="DistribOne GmbH", home_territory_code="DE", **overrides):
    payload = {"name": name, "home_territory_code": home_territory_code}
    payload.update(overrides)
    return payload


def authorization_payload(converter_id, capability="SLITTING", territory_code="DE",
                          valid_from="2026-10-01T00:00:00Z",
                          valid_to="2027-04-01T00:00:00Z",
                          expected_converter_version=None, **overrides):
    payload = {
        "converter_id": converter_id,
        "capability": capability,
        "territory_code": territory_code,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "expected_converter_version": expected_converter_version,
    }
    payload.update(overrides)
    return payload


def application_case_payload(formulation_id, customer_ref="K-1", substrate_class="METAL",
                             application_description=None, **overrides):
    payload = _drop_none({
        "formulation_id": formulation_id,
        "customer_ref": customer_ref,
        "substrate_class": substrate_class,
        "application_description": application_description,
    })
    payload.update(overrides)
    return payload


def book_lab_payload(bench_id="B1", bench_date="2026-10-05T00:00:00Z",
                     bench_hours=1.0, **overrides):
    payload = {"bench_id": bench_id, "bench_date": bench_date, "bench_hours": bench_hours}
    payload.update(overrides)
    return payload


def record_result_payload(peel_strength_n_per_25mm=16.0, test_temp_c=23,
                          test_standard="NOMINAL", **overrides):
    payload = {
        "peel_strength_n_per_25mm": peel_strength_n_per_25mm,
        "test_temp_c": test_temp_c,
        "test_standard": test_standard,
    }
    payload.update(overrides)
    return payload


def price_agreement_payload(formulation_id, jurisdiction_id, converter_id=None,
                            distributor_id=None, tier="STANDARD", base_price_cents=10000,
                            volume_breakpoints=None,
                            effective_from="2026-10-01T00:00:00Z",
                            effective_to="2027-06-01T00:00:00Z", **overrides):
    payload = _drop_none({
        "formulation_id": formulation_id,
        "jurisdiction_id": jurisdiction_id,
        "converter_id": converter_id,
        "distributor_id": distributor_id,
        "tier": tier,
        "base_price_cents": base_price_cents,
        "volume_breakpoints": volume_breakpoints,
        "effective_from": effective_from,
        "effective_to": effective_to,
    })
    payload.update(overrides)
    return payload


def order_payload(agreement_id, quantity=10, requested_ship_date="2026-11-01T00:00:00Z",
                  expected_price_agreement_version=None, converter_id=None,
                  distributor_id=None, intended_capability=None, lot_code=None,
                  **overrides):
    payload = _drop_none({
        "agreement_id": agreement_id,
        "converter_id": converter_id,
        "distributor_id": distributor_id,
        "quantity": quantity,
        "requested_ship_date": requested_ship_date,
        "intended_capability": intended_capability,
        "lot_code": lot_code,
        "expected_price_agreement_version": expected_price_agreement_version,
    })
    payload.update(overrides)
    return payload


def rebate_program_payload(formulation_id, partner_type="DISTRIBUTOR", converter_id=None,
                           distributor_id=None, period_start="2026-10-01T00:00:00Z",
                           period_end="2027-01-01T00:00:00Z", rebate_tiers=None,
                           budget_cap_cents=1000000, **overrides):
    if rebate_tiers is None:
        rebate_tiers = [{"threshold_qty": 0, "rate_pct": 0.01}]
    payload = _drop_none({
        "formulation_id": formulation_id,
        "partner_type": partner_type,
        "converter_id": converter_id,
        "distributor_id": distributor_id,
        "period_start": period_start,
        "period_end": period_end,
        "rebate_tiers": rebate_tiers,
        "budget_cap_cents": budget_cap_cents,
    })
    payload.update(overrides)
    return payload


def phase_out_program_payload(substance_id, jurisdiction_codes=("DE",),
                              trigger_concentration_ppm=1000, **overrides):
    payload = {
        "substance_id": substance_id,
        "jurisdiction_codes": list(jurisdiction_codes),
        "trigger_concentration_ppm": trigger_concentration_ppm,
    }
    payload.update(overrides)
    return payload


def qualification_payload(customer_ref="K-1", samples_passed=3, **overrides):
    payload = {"customer_ref": customer_ref, "samples_passed": samples_passed}
    payload.update(overrides)
    return payload


def counterfeit_report_payload(formulation_id, lot_code="L-X",
                               channel_description="gray-market reel lot",
                               implicated_converter_id=None, **overrides):
    payload = _drop_none({
        "formulation_id": formulation_id,
        "lot_code": lot_code,
        "channel_description": channel_description,
        "implicated_converter_id": implicated_converter_id,
    })
    payload.update(overrides)
    return payload


def disposition_payload(outcome="CONFIRMED_COUNTERFEIT", investigator_note=None, **overrides):
    payload = _drop_none({"outcome": outcome, "investigator_note": investigator_note})
    payload.update(overrides)
    return payload


def discontinue_payload(last_time_buy_deadline="2027-01-15T00:00:00Z",
                        last_ship_date="2027-03-01T00:00:00Z",
                        ltb_pool_quantity=1000, **overrides):
    payload = {
        "last_time_buy_deadline": last_time_buy_deadline,
        "last_ship_date": last_ship_date,
        "ltb_pool_quantity": ltb_pool_quantity,
    }
    payload.update(overrides)
    return payload


def successor_payload(product_code="F-100R", name="Reformulated base",
                      base_polymer_family="acrylic", expected_formulation_version=None,
                      **overrides):
    payload = {
        "product_code": product_code,
        "name": name,
        "base_polymer_family": base_polymer_family,
        "expected_formulation_version": expected_formulation_version,
    }
    payload.update(overrides)
    return payload
