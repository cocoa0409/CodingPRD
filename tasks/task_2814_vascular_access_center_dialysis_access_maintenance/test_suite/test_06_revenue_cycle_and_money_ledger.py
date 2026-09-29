"""The revenue cycle: two payer variants, per-line rounding and the money ledger.

The allowed amount is recomputed over the whole line set on every write, each line is
rounded before the summation, and the bill/deny/rebill loop must return the ledger to
the cent it started on -- twice, and no more.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success


def _three_line_fee_for_service_case(api):
    """A discharged fee-for-service case carrying 180050, 45075 and 90050 cent lines.

    Under fee-for-service the position factors of 100, 50 and 25 percent give
    180050 + 22538 + 22513 = 225101 cents. Under the bundled variant the imaging line
    and the second angioplasty line would both collapse into the primary, leaving
    180050.
    """
    bundle = fx.seed_case_with_consumed_balloon(api, quantity=2)
    bundle["code_one"] = fx.file_code_line(
        api, bundle, hcpcs_code="35476", code_family="ANGIOPLASTY",
        base_allowed_cents=180050, rank=1, modifier="NONE",
    )
    bundle["code_two"] = fx.file_code_line(
        api, bundle, hcpcs_code="75791", code_family="IMAGING",
        base_allowed_cents=45075, rank=2, modifier="NONE",
    )
    bundle["code_three"] = fx.file_code_line(
        api, bundle, hcpcs_code="35476", code_family="ANGIOPLASTY",
        base_allowed_cents=90050, rank=3, modifier="NONE",
    )
    return bundle


def test_01_the_preview_reports_both_variant_totals_and_their_delta(api):
    """The same three lines are worth 225101 cents to one payer and 180050 to the other.

    The PRD states: "It evaluates **both** variants of the allowed-amount calculation
    over the stored line set and reports the `procedure_id`, the `applicable_variant`
    echoing the patient's `payer_program`, the `bundled_esrd_total_cents` and
    `fee_for_service_total_cents` the two variants would produce, the
    `variant_delta_cents` obtained by subtracting the bundled total from the
    fee-for-service total, and the per-line `line_items`."

    The patient is `FEE_FOR_SERVICE`, so the applicable variant is the fee-for-service
    one and the delta of 45051 cents is exactly the two lines the bundled variant would
    have collapsed.

    Design: Difficulty/dual_variant_calc/reimbursement_bundled_esrd_vs_fee_for_service_divergence
    """
    bundle = _three_line_fee_for_service_case(api)

    preview = validate_success(
        api.get_reimbursement_preview(bundle["procedure_id"], bundle["coder_headers"])
    )
    assert preview["procedure_id"] == bundle["procedure_id"]
    assert preview["applicable_variant"] == "FEE_FOR_SERVICE"
    assert preview["fee_for_service_total_cents"] == 225101
    assert preview["bundled_esrd_total_cents"] == 180050
    assert preview["variant_delta_cents"] == 45051
    assert len(preview["line_items"]) == 3
    for money in ("fee_for_service_total_cents", "bundled_esrd_total_cents"):
        assertions.assert_cents(preview[money], money)


def test_02_the_preview_persists_nothing_it_computed(api):
    """The persisted variant stays fee-for-service and no line is re-resolved.

    The PRD states: "Calling it never changes a line's `is_bundled`,
    `reduction_factor_pct` or `allowed_cents`, never changes the procedure's
    `allowed_amount_cents` or `reimbursement_variant`, and never bumps a `version`."

    Design: Difficulty/dual_variant_calc/reimbursement_bundled_esrd_vs_fee_for_service_divergence
    """
    bundle = _three_line_fee_for_service_case(api)

    before = fx.read_procedure(api, bundle["procedure_id"])
    assert before["reimbursement_variant"] == "FEE_FOR_SERVICE"
    assert before["allowed_amount_cents"] == 225101
    assert before["billed_amount_cents"] == 0

    validate_success(
        api.get_reimbursement_preview(bundle["procedure_id"], fx.ADMIN)
    )

    after = fx.read_procedure(api, bundle["procedure_id"])
    assert after["allowed_amount_cents"] == 225101
    assert after["billed_amount_cents"] == 0
    assert after["reimbursement_variant"] == "FEE_FOR_SERVICE"
    assert after["version"] == before["version"]
    assert after["coding_status"] == "CODED"

    lines, meta = validate_paginated(
        api.list_procedure_codes(bundle["procedure_id"], bundle["coder_headers"])
    )
    assert meta["total_count"] == 3
    assert [line["allowed_cents"] for line in lines] == [180050, 22538, 22513]
    assert all(line["is_bundled"] is False for line in lines)
    assert sum(line["allowed_cents"] for line in lines) == 225101


def _four_line_bundled_esrd_case(api):
    """An aborted bundled-ESRD case whose four lines exercise every resolution branch.

    Rank 1 is the primary thrombectomy line; rank 2 shares its family and collapses;
    rank 3 is imaging carrying `M59`, which blocks the collapse; rank 4 carries `M52`,
    which halves its base before the position factor is applied.
    """
    center = fx.seed_center(api)
    patient = fx.seed_patient(api, center["facility_id"], payer_program="BUNDLED_ESRD")
    access = fx.seed_access_in_use(api, patient["id"], access_type="AVG")
    readings = fx.seed_reading_pair(api, access["id"], center["facility_id"])
    referral = fx.triage(
        api,
        fx.seed_referral(
            api, access["id"], center["facility_id"], missed_treatment_count=0
        )["id"],
    )
    procedure = fx.book_case(
        api, referral["id"], center["room_id"], center["operator_id"],
        referral["version"], "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
        procedure_type="THROMBECTOMY",
    )

    bundle = dict(center)
    bundle["access"] = access
    bundle["procedure_id"] = procedure["id"]
    bundle["reading_id"] = readings[-1]["id"]
    fx.set_clock(api, fx.CASE_START_CLOCK)
    fx.start_case(api, bundle)
    bundle["procedure"] = fx.abort(api, bundle, abort_reason="could not cross the clot")

    bundle["code_one"] = fx.file_code_line(
        api, bundle, hcpcs_code="36870", code_family="THROMBECTOMY",
        base_allowed_cents=300000, rank=1, modifier="NONE",
    )
    bundle["code_two"] = fx.file_code_line(
        api, bundle, hcpcs_code="36871", code_family="THROMBECTOMY",
        base_allowed_cents=100000, rank=2, modifier="NONE",
    )
    bundle["code_three"] = fx.file_code_line(
        api, bundle, hcpcs_code="75791", code_family="IMAGING",
        base_allowed_cents=90050, rank=3, modifier="M59",
    )
    bundle["code_four"] = fx.file_code_line(
        api, bundle, hcpcs_code="36905", code_family="ANGIOPLASTY",
        base_allowed_cents=45076, rank=4, modifier="M52",
    )
    return bundle


def test_03_each_line_is_resolved_by_family_modifier_and_position(api):
    """Four lines, four different outcomes, all rewritten by the final recomputation.

    The PRD states: "Under the bundled variant, a line that is **not** in first
    position, whose `modifier` is not `M59`, and whose `code_family` either equals the
    primary line's `code_family` or is `IMAGING`, collapses: its `is_bundled` becomes
    true, its `reduction_factor_pct` becomes 0, and its `allowed_cents` becomes 0."

    It also states: "The position factor depends on the line's **position in the ordered
    list, not on its rank value**: 100 percent for the first line, 50 percent for the
    second, and 25 percent for the third and every line after it".

    So the imaging line survives on its `M59` and still takes the fourth-position
    quarter: 90050 * 1.00 * 0.25 is 22512.5, which rounds half up to 22513. The `M52`
    line halves first: 45076 * 0.50 * 0.25 is 5634.5, which rounds half up to 5635.

    Design: Difficulty/combinatorial_formula/allowed_amount_rounds_each_line_before_summation_with_modifier_and_bundling
    """
    bundle = _four_line_bundled_esrd_case(api)

    lines, meta = validate_paginated(
        api.list_procedure_codes(bundle["procedure_id"], bundle["coder_headers"])
    )
    assert meta["total_count"] == 4
    assert [line["rank"] for line in lines] == [1, 2, 3, 4]
    by_rank = {line["rank"]: line for line in lines}

    assert by_rank[1]["is_bundled"] is False
    assert by_rank[1]["reduction_factor_pct"] == 100
    assert by_rank[1]["allowed_cents"] == 300000

    assert by_rank[2]["is_bundled"] is True
    assert by_rank[2]["reduction_factor_pct"] == 0
    assert by_rank[2]["allowed_cents"] == 0

    assert by_rank[3]["is_bundled"] is False
    assert by_rank[3]["reduction_factor_pct"] == 25
    assert by_rank[3]["allowed_cents"] == 22513

    assert by_rank[4]["is_bundled"] is False
    assert by_rank[4]["reduction_factor_pct"] == 25
    assert by_rank[4]["allowed_cents"] == 5635


def test_04_the_total_rounds_every_line_before_it_sums_them(api):
    """328148 cents, one more than rounding the summed products would give.

    The PRD states: "The procedure's `allowed_amount_cents` is the **sum of the
    already-rounded per-line amounts**."

    Summing the unrounded products 300000 + 0 + 22512.5 + 5634.5 and rounding once
    yields 328147, which is wrong. The two dimensions also stay independent: the case is
    clinically ABORTED while its coding dimension has reached CODED.

    Design: Difficulty/combinatorial_formula/allowed_amount_rounds_each_line_before_summation_with_modifier_and_bundling
    """
    bundle = _four_line_bundled_esrd_case(api)

    procedure = fx.read_procedure(api, bundle["procedure_id"])
    assert procedure["allowed_amount_cents"] == 328148
    assert procedure["allowed_amount_cents"] != 328147
    assert procedure["reimbursement_variant"] == "BUNDLED_ESRD"
    assert procedure["clinical_status"] == "ABORTED"
    assert procedure["coding_status"] == "CODED"
    assertions.assert_cents(procedure["allowed_amount_cents"], "allowed_amount_cents")

    lines, _meta = validate_paginated(
        api.list_procedure_codes(bundle["procedure_id"], bundle["coder_headers"])
    )
    assert sum(line["allowed_cents"] for line in lines) == 328148


def _attested_ledger_case(api):
    """An aborted fee-for-service case attested at 225101 cents, ready to be billed.

    The primary line is an unbundled angioplasty, so the code-to-device gate demands a
    consumed balloon; the abort supplies one. The other two lines belong to the exempt
    imaging and access-maintenance families.
    """
    bundle = fx.seed_case_with_consumed_balloon(
        api, quantity=2, terminal="ABORTED", sedation_level="NONE"
    )
    bundle["code_one"] = fx.file_code_line(
        api, bundle, hcpcs_code="35476", code_family="ANGIOPLASTY",
        base_allowed_cents=180050, rank=1, modifier="NONE",
    )
    bundle["code_two"] = fx.file_code_line(
        api, bundle, hcpcs_code="75791", code_family="IMAGING",
        base_allowed_cents=45075, rank=2, modifier="NONE",
    )
    bundle["code_three"] = fx.file_code_line(
        api, bundle, hcpcs_code="36901", code_family="ACCESS_MAINTENANCE_BUNDLE",
        base_allowed_cents=90050, rank=3, modifier="NONE",
    )
    bundle["procedure"] = fx.attest(api, bundle)
    assert bundle["procedure"]["coding_status"] == "ATTESTED"
    assert bundle["procedure"]["allowed_amount_cents"] == 225101
    return bundle


def test_05_two_denial_cycles_return_the_net_receivable_to_the_cent(api):
    """Bill, deny, rebill, deny, rebill -- and the net receivable never drifts.

    The PRD states: "The money must land back on its exact pre-denial value with zero
    drift; a cycle of bill, deny, rebill, deny, rebill must leave `net_receivable_cents`
    identical to its value after the original billing."

    It also states: "It records the payer's `denial_reason` category and remittance
    `denial_code`, sets `denied_amount_cents` equal to `billed_amount_cents` and
    `net_receivable_cents` to 0, and moves the procedure to `DENIED`.
    `billed_amount_cents` itself is not reduced".

    The recomputation reads the same three lines each time, so the restored amount is
    the same 225101 cents rather than a re-derived approximation of it.

    Design: Difficulty/compensating_invariant/rebill_restores_the_money_ledger_with_zero_drift_until_the_second_rebill_is_spent
    """
    bundle = _attested_ledger_case(api)

    billed = fx.bill(api, bundle)
    assert billed["coding_status"] == "BILLED"
    assert billed["billed_amount_cents"] == 225101
    assert billed["denied_amount_cents"] == 0
    assert billed["net_receivable_cents"] == 225101
    assert billed["rebill_count"] == 0
    baseline_net = billed["net_receivable_cents"]

    denied = fx.deny(api, bundle, denial_reason="DOCUMENTATION", denial_code="CO-16")
    assert denied["coding_status"] == "DENIED"
    assert denied["denial_reason"] == "DOCUMENTATION"
    assert denied["denial_code"] == "CO-16"
    assert denied["billed_amount_cents"] == 225101
    assert denied["denied_amount_cents"] == 225101
    assert denied["net_receivable_cents"] == 0
    assert denied["rebill_count"] == 0

    first_rebill = fx.rebill(api, bundle)
    assert first_rebill["coding_status"] == "REBILLED"
    assert first_rebill["billed_amount_cents"] == 225101
    assert first_rebill["denied_amount_cents"] == 0
    assert first_rebill["net_receivable_cents"] == baseline_net
    assert first_rebill["rebill_count"] == 1

    fx.deny(api, bundle, denial_reason="BUNDLING", denial_code="CO-97")
    second_rebill = fx.rebill(api, bundle)
    assert second_rebill["coding_status"] == "REBILLED"
    assert second_rebill["net_receivable_cents"] == baseline_net
    assert second_rebill["denied_amount_cents"] == 0
    assert second_rebill["rebill_count"] == 2
    assertions.assert_money_ledger(second_rebill)

    lines, meta = validate_paginated(
        api.list_procedure_codes(bundle["procedure_id"], bundle["coder_headers"])
    )
    assert meta["total_count"] == 3
    assert [line["allowed_cents"] for line in lines] == [180050, 22538, 22513]


def test_06_the_third_rebill_is_refused_and_leaves_the_denial_standing(api):
    """The allowance is two rebills; the third is refused and changes nothing.

    The PRD states: "It requires `coding_status` of `DENIED` and a `rebill_count`
    strictly below 2, so at most two rebills are ever accepted and a third is refused
    with `ERR_REBILL_LIMIT_REACHED`."

    Denial itself is not rationed -- it is "available from `BILLED` and from
    `REBILLED`" -- so the third denial succeeds and the case is left sitting in DENIED
    with a net receivable of 0, its version untouched by the refused rebill.

    Design: Difficulty/compensating_invariant/rebill_restores_the_money_ledger_with_zero_drift_until_the_second_rebill_is_spent
    """
    bundle = _attested_ledger_case(api)

    fx.bill(api, bundle)
    fx.deny(api, bundle)
    fx.rebill(api, bundle)
    fx.deny(api, bundle)
    fx.rebill(api, bundle)

    third_denial = fx.deny(api, bundle, denial_reason="TIMELY_FILING", denial_code="CO-29")
    assert third_denial["coding_status"] == "DENIED"
    assert third_denial["rebill_count"] == 2
    assert third_denial["net_receivable_cents"] == 0

    refused = api.rebill_procedure(bundle["procedure_id"], fx.ADMIN)
    validate_error(refused, "ERR_REBILL_LIMIT_REACHED", 409)

    settled = fx.read_procedure(api, bundle["procedure_id"])
    assert settled["coding_status"] == "DENIED"
    assert settled["rebill_count"] == 2
    assert settled["billed_amount_cents"] == 225101
    assert settled["denied_amount_cents"] == 225101
    assert settled["net_receivable_cents"] == 0
    assert settled["version"] == third_denial["version"]
    assert settled["clinical_status"] == "ABORTED"


def _aborted_case_billed_in_full(api):
    """A case abandoned in the room whose single line is nonetheless coded and billed."""
    bundle = fx.seed_case_with_consumed_balloon(
        api, quantity=2, terminal="ABORTED", sedation_level="NONE"
    )
    bundle["code"] = fx.file_code_line(
        api, bundle, hcpcs_code="35476", code_family="ANGIOPLASTY",
        base_allowed_cents=180050, rank=1, modifier="NONE",
    )
    bundle["procedure"] = fx.attest(api, bundle)
    bundle["procedure"] = fx.bill(api, bundle)
    return bundle


def test_07_the_coding_dimension_reaches_billed_from_a_clinically_aborted_case(api):
    """ABORTED is terminal for the clinical dimension only; the money still moves.

    The PRD states: "A discharged case may sit `UNCODED` indefinitely, and an aborted
    case may still be coded, attested and billed."

    It also states: "`DISCHARGED`, `ABORTED` and `CANCELLED` are all terminal for the
    clinical dimension. Any clinical transition attempted from one of them is refused
    with `ERR_PROCEDURE_TERMINAL`."

    So a second abort on the same case is refused while the coding dimension has already
    walked UNCODED, CODED, ATTESTED, BILLED without the clinical status moving at all.

    Design: Difficulty/non_linear_state_machine/procedure_clinical_aborted_while_coding_dimension_walks_all_the_way_to_billed
    """
    bundle = _aborted_case_billed_in_full(api)

    billed = fx.read_procedure(api, bundle["procedure_id"])
    assert billed["clinical_status"] == "ABORTED"
    assert billed["coding_status"] == "BILLED"
    assert billed["allowed_amount_cents"] == 180050
    assert billed["billed_amount_cents"] == 180050
    assert billed["denied_amount_cents"] == 0
    assert billed["net_receivable_cents"] == 180050
    assert billed["abort_reason"] is not None
    assertions.assert_money_ledger(billed)

    refused = api.abort_procedure(
        bundle["procedure_id"],
        {"abort_reason": "the room was already empty"},
        bundle["operator_headers"],
    )
    validate_error(refused, "ERR_PROCEDURE_TERMINAL", 409)

    settled = fx.read_procedure(api, bundle["procedure_id"])
    assert settled["clinical_status"] == "ABORTED"
    assert settled["coding_status"] == "BILLED"
    assert settled["version"] == billed["version"]


def test_08_the_abort_runs_only_the_device_hop_of_the_discharge_cascade(api):
    """Devices are consumed and wasted, but the referral and the access do not move.

    The PRD states: "It fires **none** of hops 2 through 5: the parent referral
    deliberately stays `SCHEDULED` so the case can be rebooked, the access keeps its
    `status` and every one of its counters, no conversion plan converts, and no source
    access is abandoned."

    It also states: "on the abort branch the usage's `wasted_quantity` is additionally
    set equal to its `quantity`, because devices opened for a case that was abandoned in
    the room cannot go back on the shelf."

    The access therefore keeps the DYSFUNCTIONAL status its triage gave it, with an
    angioplasty count of 0 -- that counter counts DISCHARGED procedures, and this one
    never reached DISCHARGED -- and `discharged_at` stays null even after billing.

    Design: Difficulty/non_linear_state_machine/procedure_clinical_aborted_while_coding_dimension_walks_all_the_way_to_billed
    """
    bundle = _aborted_case_billed_in_full(api)

    usage = fx.read_usage(api, bundle["usage_id"])
    assert usage["state"] == "CONSUMED"
    assert usage["quantity"] == 2
    assert usage["wasted_quantity"] == 2
    assertions.assert_instant_equals(usage["consumed_at"], fx.CASE_START_CLOCK, "consumed_at")
    assert usage["released_at"] is None

    lot = fx.read_lot(api, bundle["lot_id"])
    assert lot["received_quantity"] == 10
    assert lot["quantity_on_hand"] == 8
    assert lot["quantity_reserved"] == 0
    assert lot["status"] == "AVAILABLE"
    assertions.assert_device_unit_conservation(lot, [usage])

    referral = fx.read_referral(api, bundle["referral_id"])
    assert referral["status"] == "SCHEDULED"
    assert referral["completed_at"] is None

    access = fx.read_access(api, bundle["access_id"])
    assert access["status"] == "DYSFUNCTIONAL"
    assert access["angioplasty_count"] == 0
    assert access["intervention_burden_score"] == 0
    assertions.assert_burden_score(access)

    procedure = fx.read_procedure(api, bundle["procedure_id"])
    assert procedure["discharged_at"] is None
    assert procedure["sedation_end_at"] is None
