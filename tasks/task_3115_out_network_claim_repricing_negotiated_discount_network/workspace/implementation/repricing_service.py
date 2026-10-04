"""Repricing service: policy selection, per-line pricing, determinations."""
from decimal import Decimal

import db
import errors
import util
import pricing


CLAIM_TYPES = {"PROFESSIONAL", "FACILITY", "ANCILLARY", "EMERGENCY"}
NETWORK_STATUSES = {"IN_NETWORK", "OUT_OF_NETWORK", "EMERGENCY_OON"}
METHODOLOGIES = {"CONTRACTED_NETWORK", "REFERENCE_BASED", "PERCENT_OF_MEDICARE",
                 "UCR", "NEGOTIATION_REQUIRED"}


def non_void_lines(claim_id):
    lines = [l for l in db.claim_lines.values()
             if l["claim_id"] == claim_id and l["status"] != "VOID"]
    lines.sort(key=lambda l: (l.get("_created_at_dt"), l.get("_seq", 0), l["id"]))
    return lines


def recompute_billed(claim):
    lines = non_void_lines(claim["id"])
    claim["billed_amount_cents"] = sum(
        l["unit_charge_cents"] * l["quantity_units"] for l in lines)


def find_covering_agreement(provider_id, service_date_dt):
    """ACTIVE agreement covering provider at service_date.

    Occupancy: effective_start inclusive, effective_end exclusive.
    """
    for a in db.network_agreements.values():
        if a["provider_id"] != provider_id:
            continue
        if a["status"] != "ACTIVE":
            continue
        if a["_effective_start_dt"] <= service_date_dt < a["_effective_end_dt"]:
            return a
    return None


def select_policy(payer_client_id, claim_type, network_status):
    """Return the selected ACTIVE policy (lowest priority, earliest created)."""
    cands = [p for p in db.repricing_policies.values()
             if p["payer_client_id"] == payer_client_id
             and p["claim_type"] == claim_type
             and p["network_status"] == network_status
             and p["status"] == "ACTIVE"]
    if not cands:
        return None
    cands.sort(key=lambda p: (p["priority"], p.get("_created_at_dt"), p["id"]))
    return cands[0]


def _find_medicare(procedure_code, region_code):
    for m in db.medicare_fee_schedule.values():
        if m["procedure_code"] == procedure_code and m["region_code"] == region_code:
            return m
    return None


def _find_ucr(procedure_code, region_code):
    for u in db.ucr_rates.values():
        if u["procedure_code"] == procedure_code and u["region_code"] == region_code:
            return u
    return None


def _new_determination(claim_id, methodology, policy_id, agreement_id,
                       supersedes_id, input_snapshot, computation_trace,
                       defensibility_notes):
    now = db.now()
    det = {
        "id": util.new_id(),
        "claim_id": claim_id,
        "methodology": methodology,
        "policy_id": policy_id,
        "agreement_id": agreement_id,
        "supersedes_determination_id": supersedes_id,
        "input_snapshot": input_snapshot,
        "computation_trace": computation_trace,
        "defensibility_notes": defensibility_notes,
        "status": "ACTIVE",
        "version": 1,
        "_seq": db.next_seq(),
        "_created_at_dt": now,
        "_updated_at_dt": now,
    }
    db.repricing_determinations[det["id"]] = det
    return det


def create_negotiated_determination(claim, defensibility_notes=None,
                                    extra_snapshot=None):
    """Create a NEGOTIATED determination superseding the current ACTIVE one."""
    prior = None
    for d in db.repricing_determinations.values():
        if d["claim_id"] == claim["id"] and d["status"] == "ACTIVE":
            prior = d
            break
    snapshot = {
        "methodology": "NEGOTIATED",
        "allowed_amount_cents": claim["allowed_amount_cents"],
    }
    if extra_snapshot:
        snapshot.update(extra_snapshot)
    trace = [{
        "step": "negotiated_amount",
        "allowed_amount_cents": claim["allowed_amount_cents"],
    }]
    det = _new_determination(
        claim["id"], "NEGOTIATED", None, None,
        prior["id"] if prior else None, snapshot, trace, defensibility_notes)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        util.touch(prior)
    return det


def _settle_claim_to(claim, amount_cents):
    """Replace claim allowed amount and recompute derived fields."""
    claim["allowed_amount_cents"] = amount_cents
    claim["payer_liability_cents"] = amount_cents - claim["patient_responsibility_cents"]
    claim["savings_cents"] = claim["billed_amount_cents"] - amount_cents + \
        claim["patient_responsibility_cents"]


def _plan_reprice(claim):
    """Pure planning phase: runs all business validations and computes the
    per-line allowed amounts WITHOUT mutating anything. Returns a plan dict.

    Raises the appropriate ApiError on any validation failure. A failed
    reprice is a pure rejection with no persisted state.
    """
    lines = non_void_lines(claim["id"])
    if not lines:
        raise errors.claim_has_no_lines()

    agreement = None
    policy = None
    methodology = None
    if claim["network_status"] == "IN_NETWORK":
        agreement = find_covering_agreement(claim["provider_id"],
                                            claim["_service_date_dt"])
        if agreement is None:
            raise errors.no_contracted_agreement()
        methodology = "CONTRACTED_NETWORK"
    else:
        policy = select_policy(claim["payer_client_id"], claim["claim_type"],
                               claim["network_status"])
        if policy is None:
            raise errors.no_repricing_policy()
        methodology = policy["methodology"]
        if claim.get("nsa_flag") and methodology == "NEGOTIATION_REQUIRED":
            raise errors.nsa_methodology_conflict()
        if methodology == "NEGOTIATION_REQUIRED":
            raise errors.negotiation_required()

    trace = []
    if methodology == "CONTRACTED_NETWORK" and agreement is None:
        # Policy-driven contracted pricing on an out-of-network claim still
        # prices off the covering NetworkAgreement (the methodology's rate
        # input); its absence is a rate-input failure.
        agreement = find_covering_agreement(claim["provider_id"],
                                            claim["_service_date_dt"])
        if agreement is None:
            raise errors.rate_input_missing()
    snapshot = {
        "methodology": methodology,
        "policy_id": policy["id"] if policy else None,
        "lines": [],
    }
    if policy is not None:
        snapshot["policy_parameters"] = {
            "percent_of_medicare": policy.get("percent_of_medicare"),
            "rbp_markup_percent": policy.get("rbp_markup_percent"),
            "ucr_percentile": policy.get("ucr_percentile"),
            "priority": policy.get("priority"),
        }
    if agreement is not None:
        snapshot["agreement_id"] = agreement["id"]
        snapshot["agreement_discount_percent"] = agreement["discount_percent"]

    line_results = []
    total_allowed = 0
    for line in lines:
        gross = pricing.line_gross(line)
        if methodology == "CONTRACTED_NETWORK":
            allowed = pricing.allowed_line_contracted(
                line, agreement["discount_percent"])
            snapshot["lines"].append({
                "line_id": line["id"],
                "procedure_code": line["procedure_code"],
                "region_code": line["region_code"],
                "gross_line_cents": gross,
                "unit_charge_cents": line["unit_charge_cents"],
                "quantity_units": line["quantity_units"],
                "agreement_id": agreement["id"],
                "discount_percent": agreement["discount_percent"],
            })
            trace.append({
                "step": "contracted_network_line",
                "line_id": line["id"],
                "gross_line_cents": gross,
                "discount_percent": agreement["discount_percent"],
                "allowed_line_cents": allowed,
            })
        elif methodology == "PERCENT_OF_MEDICARE":
            fee = _find_medicare(line["procedure_code"], line["region_code"])
            if fee is None:
                raise errors.rate_input_missing()
            allowed = pricing.allowed_line_percent_of_medicare(
                line, fee, policy["percent_of_medicare"])
            snapshot["lines"].append({
                "line_id": line["id"],
                "procedure_code": line["procedure_code"],
                "region_code": line["region_code"],
                "gross_line_cents": gross,
                "unit_charge_cents": line["unit_charge_cents"],
                "quantity_units": line["quantity_units"],
                "medicare_fee_schedule_entry_id": fee["id"],
                "base_rate_cents": fee["base_rate_cents"],
                "geographic_adjustment_factor": fee["geographic_adjustment_factor"],
            })
            trace.append({
                "step": "percent_of_medicare_line",
                "line_id": line["id"],
                "gross_line_cents": gross,
                "base_rate_cents": fee["base_rate_cents"],
                "geographic_adjustment_factor": fee["geographic_adjustment_factor"],
                "percent_of_medicare": policy["percent_of_medicare"],
                "allowed_line_cents": allowed,
            })
        elif methodology == "UCR":
            ucr = _find_ucr(line["procedure_code"], line["region_code"])
            if ucr is None:
                raise errors.rate_input_missing()
            allowed = pricing.allowed_line_ucr(line, ucr, policy["ucr_percentile"])
            snapshot["lines"].append({
                "line_id": line["id"],
                "procedure_code": line["procedure_code"],
                "region_code": line["region_code"],
                "gross_line_cents": gross,
                "unit_charge_cents": line["unit_charge_cents"],
                "quantity_units": line["quantity_units"],
                "ucr_rate_id": ucr["id"],
                "ucr_percentile": policy["ucr_percentile"],
            })
            trace.append({
                "step": "ucr_line",
                "line_id": line["id"],
                "gross_line_cents": gross,
                "ucr_percentile": policy["ucr_percentile"],
                "allowed_line_cents": allowed,
            })
        elif methodology == "REFERENCE_BASED":
            ucr = _find_ucr(line["procedure_code"], line["region_code"])
            if ucr is None:
                raise errors.rate_input_missing()
            allowed = pricing.allowed_line_reference_based(
                line, ucr, policy["rbp_markup_percent"])
            snapshot["lines"].append({
                "line_id": line["id"],
                "procedure_code": line["procedure_code"],
                "region_code": line["region_code"],
                "gross_line_cents": gross,
                "unit_charge_cents": line["unit_charge_cents"],
                "quantity_units": line["quantity_units"],
                "ucr_rate_id": ucr["id"],
                "rbp_markup_percent": policy["rbp_markup_percent"],
            })
            trace.append({
                "step": "reference_based_line",
                "line_id": line["id"],
                "gross_line_cents": gross,
                "benchmark_percentile": 80,
                "rbp_markup_percent": policy["rbp_markup_percent"],
                "allowed_line_cents": allowed,
            })
        else:
            raise errors.negotiation_required()
        line_results.append((line, allowed))
        total_allowed += allowed

    rbp_amount_cents = None
    if methodology == "REFERENCE_BASED":
        primary = lines[0]
        ucr_primary = _find_ucr(primary["procedure_code"], primary["region_code"])
        benchmark_total = ucr_primary["percentile_80_cents"] * primary["quantity_units"]
        rbp_amount_cents = pricing.rbp_amount(
            claim["billed_amount_cents"], total_allowed, benchmark_total,
            policy["rbp_markup_percent"])
        snapshot["rbp_benchmark_cents"] = benchmark_total
        trace.append({
            "step": "rbp_amount",
            "benchmark_cents": benchmark_total,
            "allowed_amount_cents": total_allowed,
            "rbp_amount_cents": rbp_amount_cents,
        })

    trace.append({
        "step": "claim_totals",
        "allowed_amount_cents": total_allowed,
    })

    return {
        "lines": line_results,
        "total_allowed": total_allowed,
        "methodology": methodology,
        "policy": policy,
        "agreement": agreement,
        "snapshot": snapshot,
        "trace": trace,
        "rbp_amount_cents": rbp_amount_cents,
    }


def _commit_reprice(claim, plan, defensibility_notes):
    """Apply a validated reprice plan: mutate lines, claim, agreement, and
    create the ACTIVE determination."""
    for line, allowed in plan["lines"]:
        line["allowed_amount_cents"] = allowed
        line["status"] = "PRICED"
        util.touch(line)

    total_allowed = plan["total_allowed"]
    claim["allowed_amount_cents"] = total_allowed
    claim["payer_liability_cents"] = total_allowed - claim["patient_responsibility_cents"]
    claim["savings_cents"] = claim["billed_amount_cents"] - total_allowed + \
        claim["patient_responsibility_cents"]
    claim["methodology_used"] = plan["methodology"]
    claim["rbp_amount_cents"] = plan["rbp_amount_cents"]

    plan["trace"][-1]["payer_liability_cents"] = claim["payer_liability_cents"]
    plan["trace"][-1]["savings_cents"] = claim["savings_cents"]

    det = _new_determination(
        claim["id"], plan["methodology"],
        plan["policy"]["id"] if plan["policy"] else None,
        plan["agreement"]["id"] if plan["agreement"] else None,
        None, plan["snapshot"], plan["trace"], defensibility_notes)

    claim["status"] = "PRICED"
    util.touch(claim)

    if plan["methodology"] == "CONTRACTED_NETWORK" and plan["agreement"] is not None:
        util.touch(plan["agreement"])

    return det


def reprice_claim(claim, defensibility_notes):
    plan = _plan_reprice(claim)
    return _commit_reprice(claim, plan, defensibility_notes)
