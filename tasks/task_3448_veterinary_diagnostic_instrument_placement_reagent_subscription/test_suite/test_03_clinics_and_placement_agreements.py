"""Clinic onboarding and placement agreement lifecycle (PRD §2.7, §3.1, §3.3)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    activate_agreement,
    api_client,
    approve_agreement,
    assert_clinic,
    assert_placement_agreement,
    assert_version_incremented,
    create_clinic,
    create_clinic_payload,
    create_lease_agreement_payload,
    create_reagent_commitment_agreement_payload,
    draft_lease_agreement,
    draft_reagent_commitment_agreement,
    get_agreement,
    list_commitment_periods,
    make_clinic_manager_headers,
    set_clinic_status,
    setup_clinic_with_active_reagent_commitment,
    update_caseload,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_FINANCE = TEST_USERS["finance_reviewer_headers"]


def test_clinic_create_applies_defaults_and_roundtrips(api):
    """PRD §3.1: "A new clinic is born `ACTIVE`, and its
    `caseload_current_tests` is initialized to `caseload_baseline_tests` at
    creation." PRD §3.1: "Two optional membership codes shape the clinic's
    pricing for its lifetime: `corporate_group_code` and `buying_group_code`,
    each defaulting to null when omitted."

    Design: Corner/entities/clinic_create_applies_defaults_and_roundtrips
    """
    resp = api_client.create_clinic(create_clinic_payload(), _ADMIN)
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id")
    assert body["meta"].get("api_request_timestamp")

    assert_clinic(data)
    assert data["status"] == "ACTIVE"
    assert data["caseload_current_tests"] == 1000
    assert data["corporate_group_code"] is None
    assert data["buying_group_code"] is None

    fetched = validate_success(api_client.get_clinic(data["id"], _ADMIN))
    assert fetched["id"] == data["id"]
    assert fetched["caseload_current_tests"] == 1000


def test_placement_agreement_program_conditional_terms(api):
    """PRD §3.3: "A `REAGENT_COMMITMENT` draft must carry
    `monthly_minimum_cents` of at least 50000 cents — the platform floor
    `MIN_MONTHLY_MINIMUM_CENTS`. A `LEASE` draft must carry
    `lease_rate_cents`, the monthly lease charge. A `PURCHASE` draft must
    carry `purchase_price_cents`, the one-time instrument price. Fields
    belonging to the other program types must be absent." PRD §3.3: "Any
    violation of these conditionals is rejected with
    `ERR_INVALID_PROGRAM_TERMS`."

    Design: Corner/entities/placement_agreement_program_conditional_terms
    """
    clinic = create_clinic()
    cm = make_clinic_manager_headers(clinic["id"])

    missing_minimum = create_reagent_commitment_agreement_payload(clinic["id"])
    del missing_minimum["monthly_minimum_cents"]
    validate_error(
        api_client.create_placement_agreement(missing_minimum, cm),
        ApiErrorId.ERR_INVALID_PROGRAM_TERMS,
    )

    foreign_field = create_lease_agreement_payload(clinic["id"], term_months=36)
    del foreign_field["lease_rate_cents"]
    foreign_field["monthly_minimum_cents"] = 100000
    validate_error(
        api_client.create_placement_agreement(foreign_field, cm),
        ApiErrorId.ERR_INVALID_PROGRAM_TERMS,
    )

    ok = validate_success(api_client.create_placement_agreement(
        {
            "clinic_id": clinic["id"],
            "model": "VETCHEM_300",
            "program_type": "PURCHASE",
            "term_months": 24,
            "start_date": CLOCK_START_ISO,
            "purchase_price_cents": 950000,
        },
        cm,
    ), 201)
    assert ok["status"] == "DRAFT"

    data, _meta = validate_paginated(api_client.list_placement_agreements(
        _ADMIN, params={"clinic_id": clinic["id"]}
    ))
    assert len(data) == 1


def test_placement_agreement_invalid_enum_and_term_rejected(api):
    """PRD §3.3: "The draft names the analyzer `model` (`VETCHEM_300`,
    `VETHEMAT_500`, or `VETURINE_200`), the `program_type` (`PURCHASE`,
    `LEASE`, or `REAGENT_COMMITMENT`), the `term_months` (one of 24, 36, 48,
    or 60, else `ERR_INVALID_REQUEST`), and the inclusive contractual
    `start_date`."

    Design: Corner/entities/placement_agreement_invalid_enum_and_term_rejected
    """
    clinic = create_clinic()
    cm = make_clinic_manager_headers(clinic["id"])

    bad_enum = create_reagent_commitment_agreement_payload(clinic["id"])
    bad_enum["program_type"] = "LEASE_TO_OWN"
    validate_error(
        api_client.create_placement_agreement(bad_enum, cm),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    bad_term = {
        "clinic_id": clinic["id"],
        "model": "VETCHEM_300",
        "program_type": "PURCHASE",
        "term_months": 25,
        "start_date": CLOCK_START_ISO,
        "purchase_price_cents": 950000,
    }
    validate_error(
        api_client.create_placement_agreement(bad_term, cm),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    data, _meta = validate_paginated(api_client.list_placement_agreements(
        _ADMIN, params={"clinic_id": clinic["id"]}
    ))
    assert data == []


def test_placement_agreement_initial_state_and_computed_end_date(api):
    """PRD §3.3: "At creation the platform computes the read-only `end_date`
    per §2.7, and the agreement begins life in `DRAFT`." PRD §2.7: "A
    placement agreement's `end_date` is computed at creation as the
    `start_date` advanced by `term_months` calendar months, keeping the same
    day of month". PRD §3.3: "The agreement's cumulative ledgers —
    `cumulative_billed_cents`, `cumulative_unpaid_billed_cents`, and
    `service_credit_cents` — start at zero".

    Design: Corner/state_machines/placement_agreement_initial_state_and_computed_end_date
    """
    clinic = create_clinic()
    draft = draft_lease_agreement(clinic["id"])

    assert_placement_agreement(draft)
    assert draft["status"] == "DRAFT"
    assert draft["end_date"] == "2028-09-01T00:00:00Z"  # 2026-09-01 + 24 months
    assert draft.get("baseline_caseload_snapshot") is None
    assert draft["cumulative_billed_cents"] == 0


def test_approve_from_approved_rejected(api):
    """PRD §3.3: "Approval moves `DRAFT` → `APPROVED` and belongs to
    `FinanceReviewer`; against an agreement in any other state it fails with
    `ERR_AGREEMENT_INVALID_STATE`."

    Design: Corner/state_machines/approve_from_approved_rejected
    """
    clinic = create_clinic()
    draft = draft_reagent_commitment_agreement(clinic["id"])
    approved = approve_agreement(draft["id"])
    assert approved["status"] == "APPROVED"
    assert_version_incremented(draft["version"], approved["version"])

    validate_error(
        api_client.approve_placement_agreement(draft["id"], _FINANCE),
        ApiErrorId.ERR_AGREEMENT_INVALID_STATE,
    )
    after = get_agreement(draft["id"])
    assert after["status"] == "APPROVED"
    assert after["version"] == approved["version"]


def test_activate_from_draft_rejected(api):
    """PRD §3.3: "Activation refuses to proceed unless the agreement is
    `APPROVED` (`ERR_AGREEMENT_INVALID_STATE`)".

    Design: Corner/state_machines/activate_from_draft_rejected
    """
    clinic = create_clinic()
    draft = draft_reagent_commitment_agreement(clinic["id"])

    validate_error(
        api_client.activate_placement_agreement(draft["id"], _ADMIN),
        ApiErrorId.ERR_AGREEMENT_INVALID_STATE,
    )
    assert get_agreement(draft["id"])["status"] == "DRAFT"
    assert list_commitment_periods(draft["id"]) == []


def test_activation_snapshots_baseline_and_creates_periods(api):
    """PRD §3.3: "The clinic's `caseload_current_tests` is frozen into
    `baseline_caseload_snapshot`, the fixed reference against which all
    future renegotiation deltas are measured." PRD §3.3: "One commitment
    period per term month is created: each names its `period_month` in
    YYYY-MM form, opens with `period_status` `OPEN` and `billing_status`
    `NONE`, and copies its `minimum_cents` from the agreement's
    `monthly_minimum_cents`."

    Design: Corner/state_machines/activation_snapshots_baseline_and_creates_periods
    """
    clinic = create_clinic()
    draft = draft_reagent_commitment_agreement(clinic["id"])
    update_caseload(clinic["id"], 1250)  # drift BEFORE activation
    approve_agreement(draft["id"])

    activated = activate_agreement(draft["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["baseline_caseload_snapshot"] == 1250

    periods = list_commitment_periods(draft["id"])
    assert len(periods) == 24
    for period in periods:
        assert period["period_status"] == "OPEN"
        assert period["billing_status"] == "NONE"
        assert period["minimum_cents"] == 100000

    update_caseload(clinic["id"], 900)
    after = get_agreement(draft["id"])
    assert after["baseline_caseload_snapshot"] == 1250  # frozen at activation
    assert after["version"] == draft["version"] + 2  # approve +1, activate +1


def test_activate_rejected_while_clinic_suspended(api):
    """PRD §3.3: "Activation refuses to proceed unless the agreement is
    `APPROVED` (`ERR_AGREEMENT_INVALID_STATE`), the owning clinic is `ACTIVE`
    (`ERR_CLINIC_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/activate_requires_clinic_active
    """
    clinic = create_clinic()
    draft = draft_reagent_commitment_agreement(clinic["id"])
    approve_agreement(draft["id"])
    set_clinic_status(clinic["id"], "SUSPENDED")

    validate_error(
        api_client.activate_placement_agreement(draft["id"], _ADMIN),
        ApiErrorId.ERR_CLINIC_NOT_ACTIVE,
    )
    assert get_agreement(draft["id"])["status"] == "APPROVED"
    assert list_commitment_periods(draft["id"]) == []


def test_activate_succeeds_once_clinic_restored(api):
    """PRD §3.1: "From `SUSPENDED`, a clinic may return to `ACTIVE` only when
    none of its placement agreements sits in `BREACHED` with
    `cumulative_unpaid_billed_cents` above zero". PRD §3.3: "Activation moves
    `APPROVED` → `ACTIVE`" — the clinic dependency is evaluated at activation
    time, so restoring the clinic reopens the transition.

    Design: Difficulty/cross_entity_state_dependency/activate_requires_clinic_active
    """
    clinic = create_clinic()
    draft = draft_reagent_commitment_agreement(clinic["id"])
    approve_agreement(draft["id"])
    set_clinic_status(clinic["id"], "SUSPENDED")
    validate_error(
        api_client.activate_placement_agreement(draft["id"], _ADMIN),
        ApiErrorId.ERR_CLINIC_NOT_ACTIVE,
    )

    set_clinic_status(clinic["id"], "ACTIVE")
    activated = activate_agreement(draft["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["baseline_caseload_snapshot"] == 1000
    assert len(list_commitment_periods(draft["id"])) == 24


def test_placement_term_touching_endpoints_conflict(api):
    """PRD §2.7: "A placement agreement's term, by contrast, is a closed
    interval from `start_date` through `end_date`, both ends inclusive: at
    activation, another agreement for the same clinic and the same `model` in
    `APPROVED`, `ACTIVE`, or `RENEGOTIATION` conflicts when the new
    `start_date` falls on or before the existing `end_date` and the existing
    `start_date` falls on or before the new `end_date` — terms that merely
    touch at a boundary day conflict."

    Design: Difficulty/resource_temporal_overlap/placement_term_overlap_closed_interval
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]  # incumbent term [2026-09-01, 2028-09-01]

    touching = draft_reagent_commitment_agreement(
        clinic["id"], start_date="2028-09-01T00:00:00Z"
    )
    approve_agreement(touching["id"])
    validate_error(
        api_client.activate_placement_agreement(touching["id"], _ADMIN),
        ApiErrorId.ERR_PLACEMENT_TERM_OVERLAP,
    )
    assert get_agreement(touching["id"])["status"] == "APPROVED"


def test_placement_term_disjoint_activates(api):
    """PRD §2.7: the closed-interval conflict requires "the new `start_date`
    falls on or before the existing `end_date`" — a successor starting after
    the incumbent's last day clears the check. PRD §3.3: "Activation moves
    `APPROVED` → `ACTIVE`".

    Design: Difficulty/resource_temporal_overlap/placement_term_overlap_closed_interval
    """
    scenario = setup_clinic_with_active_reagent_commitment()
    clinic = scenario["clinic"]
    incumbent = scenario["agreement"]

    disjoint = draft_reagent_commitment_agreement(
        clinic["id"], start_date="2030-09-02T00:00:00Z"
    )
    approve_agreement(disjoint["id"])
    activated = activate_agreement(disjoint["id"])
    assert activated["status"] == "ACTIVE"

    after = get_agreement(incumbent["id"])
    assert after["status"] == "ACTIVE"
    assert after["version"] == incumbent["version"]
