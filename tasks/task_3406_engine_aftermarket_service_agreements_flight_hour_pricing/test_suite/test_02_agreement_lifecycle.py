"""Service agreement lifecycle: activation window, enrollment gates, the
ACTIVE <-> RENEGOTIATION cycle, and the OCC guard on amend."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_operator,
    create_engine,
    create_agreement,
    activate_agreement,
    create_active_agreement,
    open_renegotiation,
    enroll_engine,
    get_agreement,
    create_agreement_payload,
    amend_agreement_payload,
    enroll_engine_payload,
    issue_billing_statement_payload,
)


def test_agreement_renegotiation_cycle(api, contract_manager_headers,
                                       finance_controller_headers):
    """PRD §3.2: "Opening a renegotiation moves an `ACTIVE` agreement to
    `RENEGOTIATION` and increments its `version`; while the agreement is in
    `RENEGOTIATION`, billing issuance and shop-visit induction are blocked —
    both require an `ACTIVE` agreement and fail with
    `ERR_AGREEMENT_NOT_ACTIVE`." and "A successful amend returns the agreement
    to `ACTIVE` and increments its `version` again."
    PRD §2.5: "**`version` (integer):** A system-managed integer that
    increments by 1 with every modification to the resource" (create -> 1,
    then each transition adds 1).

    Design: Difficulty/non_linear_state_machine/agreement_renegotiation_cycle
    """
    create_operator(name="Echo Air", iata_code="EE", credit_rating="B")
    agreement = create_agreement(
        contract_ref="LTSA-E05",
        base_rate_per_fh_usd=100.00,
        escalation_pct=0.01,
        escalation_anchor_date="2026-09-01T00:00:00Z",
        start_date="2026-09-01T00:00:00Z",
        end_date="2027-08-31T00:00:00Z",
        allowed_sourcing_classes=["NEW"],
        max_workscope_cost_usd=500000,
    )
    assert agreement["version"] == 1

    agreement = activate_agreement(agreement)
    assert agreement["version"] == 2

    agreement = open_renegotiation(agreement)
    assert agreement["version"] == 3
    assert agreement["status"] == "RENEGOTIATION"

    # Billing issuance is blocked mid-cycle.
    res = api.issue_billing_statement(
        agreement["id"],
        issue_billing_statement_payload(period="2026-09"),
        finance_controller_headers,
    )
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)

    # Closing the cycle: amend with the current version applies new terms.
    amended = validate_success(
        api.amend_agreement(
            agreement["id"],
            amend_agreement_payload(3, base_rate_per_fh_usd=110.00),
            contract_manager_headers,
        ),
        200,
    )
    assert amended["version"] == 4
    assert amended["status"] == "ACTIVE"
    assert amended["base_rate_per_fh_usd"] == pytest.approx(110.00, abs=0.01)


def test_occ_stale_amend_version(api, contract_manager_headers):
    """PRD §2.7: "**Amending an agreement** requires the request to carry
    `expected_agreement_version`, the caller's last observed `version` of the
    agreement. If another writer has advanced the agreement's `version` since
    the client last read it — for example, a prior amend or an
    open-renegotiation has already bumped it — the amend is rejected with
    `ERR_STALE_VERSION` (HTTP 412), because the caller's amended terms were
    drafted against a stale contract baseline."

    Design: Corner/cross_cutting_layers/occ_stale_amend_version
    """
    create_operator(name="Zephyr Air", iata_code="ZA", credit_rating="B")
    agreement = create_active_agreement(contract_ref="LTSA-R3901")
    agreement = open_renegotiation(agreement)
    current_version = agreement["version"]  # bumped by open-renegotiation

    res = api.amend_agreement(
        agreement["id"],
        amend_agreement_payload(current_version - 1, base_rate_per_fh_usd=105.00),
        contract_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)

    after = get_agreement(agreement["id"])
    assert after["status"] == "RENEGOTIATION", "failed amend must not close the cycle"
    assert after["base_rate_per_fh_usd"] == pytest.approx(100.00, abs=0.01), (
        "failed amend must not apply terms"
    )


def test_amend_outside_renegotiation_rejected(api, contract_manager_headers):
    """PRD §3.2: "Amending is only possible from `RENEGOTIATION`; an amend
    attempt against an agreement in any other status is rejected with
    `ERR_AGREEMENT_NOT_IN_RENEGOTIATION`."

    The OCC version carried here is current, isolating the state gate.

    Design: Corner/validations/amend_outside_renegotiation_rejected
    """
    create_operator(name="Tide Air", iata_code="TC", credit_rating="B")
    agreement = create_active_agreement(contract_ref="LTSA-V3101")
    res = api.amend_agreement(
        agreement["id"],
        amend_agreement_payload(agreement["version"], base_rate_per_fh_usd=105.00),
        contract_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_IN_RENEGOTIATION.value)


def test_activate_before_start_date_rejected(api, contract_manager_headers):
    """PRD §3.2: "Activation moves the agreement from `DRAFT` to `ACTIVE` and
    is permitted only while the logical clock sits inside the contract term —
    on or after `start_date` and strictly before `end_date` — and only from
    `DRAFT`; an activation attempt outside the term window or from any other
    status is rejected with `ERR_INVALID_STATE`."

    Logical clock is 2026-09-01 (PRD §2.4); the term starts 2027-01-01.

    Design: Corner/validations/activate_before_start_date_rejected
    """
    create_operator(name="Sage Air", iata_code="SC", credit_rating="B")
    agreement = create_agreement(
        contract_ref="LTSA-V3001",
        escalation_anchor_date="2027-01-01T00:00:00Z",
        start_date="2027-01-01T00:00:00Z",
        end_date="2029-12-31T00:00:00Z",
    )
    res = api.activate_agreement(agreement["id"], contract_manager_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_enroll_into_draft_agreement_rejected(api, contract_manager_headers):
    """PRD §3.2: "The agreement must be `ACTIVE` — enrolling against a
    `DRAFT`, `RENEGOTIATION`, or `EXPIRED` agreement is rejected with
    `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Corner/validations/enroll_into_draft_agreement_rejected
    """
    operator = create_operator(name="Mesa Air", iata_code="MF", credit_rating="B")
    engine = create_engine(operator, esn="ESN-M201")
    draft = create_agreement(contract_ref="LTSA-V2301")
    res = api.enroll_engine(
        draft["id"], enroll_engine_payload(engine["id"]), contract_manager_headers
    )
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)


def test_engine_already_enrolled_rejected(api, contract_manager_headers):
    """PRD §3.2: "The engine must currently be `IN_SERVICE` and must not
    already belong to an agreement: an engine whose `agreement_id` is already
    set is rejected with `ERR_ENGINE_ALREADY_ENROLLED`".

    Design: Corner/validations/engine_already_enrolled_rejected
    """
    operator = create_operator(name="Lotus Air", iata_code="LG", credit_rating="B")
    engine = create_engine(operator, esn="ESN-L201")
    first = create_active_agreement(contract_ref="LTSA-V2201")
    enroll_engine(first, engine)
    second = create_active_agreement(contract_ref="LTSA-V2202",
                                     base_rate_per_fh_usd=120.00)
    res = api.enroll_engine(
        second["id"], enroll_engine_payload(engine["id"]), contract_manager_headers
    )
    validate_error(res, ApiErrorId.ERR_ENGINE_ALREADY_ENROLLED.value)


def test_agreement_missing_required_field_rejected(api, contract_manager_headers):
    """PRD §3.2: "A `ContractManager` drafts a **ServiceAgreement** by
    supplying the customer-facing `contract_ref` (unique across agreements),
    the `base_rate_per_fh_usd` (strictly positive), the `escalation_pct` (zero
    or positive), the `escalation_anchor_date` from which escalation
    anniversaries are counted, the contract term's `start_date` and
    `end_date`, the `allowed_sourcing_classes` the contract permits (a
    non-empty subset of `NEW`, `REPAIRED`, and `USM`), and the per-visit
    `max_workscope_cost_usd` cap (strictly positive)."
    PRD §2.8 (tier 4): "Required fields are present, types are valid, enum
    values are in range, numeric bounds are respected" — violations surface as
    `ERR_INVALID_REQUEST` (HTTP 400).

    Design: Corner/validations/agreement_missing_required_field_rejected
    """
    create_operator(name="Inlet Air", iata_code="II", credit_rating="B")
    payload = create_agreement_payload(contract_ref="LTSA-V1501")
    del payload["base_rate_per_fh_usd"]
    res = api.create_agreement(payload, contract_manager_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
