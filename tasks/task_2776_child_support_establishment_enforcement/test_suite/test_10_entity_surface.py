"""
The declared shape of a row: what a create returns, what a read recomputes.

These cases exercise the envelope, the defaults, the immutable financial rows and
the payload band of the evaluation order, each against the fields the contract
declares for the entity rather than against any workflow outcome.
"""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START, DEFAULT_LIMIT, MISSING_UUID
from test_helpers.test_users import (
    CASE_WORKER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    PROGRAM_ADMIN_HEADERS,
)

#: The obligor payload of the creation case, spelled out so the response can be
#: compared field by field against what was actually sent.
OBLIGOR_REQUEST = {
    "role_type": "NONCUSTODIAL_PARTY",
    "full_name": "Alex Ruiz",
    "ssn_last4": "1111",
    "residence_state_code": "MN",
    "employer_name": "Northline Fabrication LLC",
    "monthly_gross_income_cents": 300000,
    "income_verification_source": "VERIFIED_WAGE_RECORD",
    "supports_second_family": False,
    "has_valid_drivers_license": True,
}


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _two_parties_and_no_case() -> fx.Scenario:
    """The custodial party and a located obligor, with no case opened yet."""
    fx.set_clock(CLOCK_START)
    scenario = fx.Scenario()
    scenario.custodial_party = fx.create_custodial_party(
        full_name="Dana Ruiz", ssn_last4="1212"
    )
    scenario.noncustodial_party = fx.create_noncustodial_party(
        full_name="Alex Ruiz", ssn_last4="1313"
    )
    scenario.noncustodial_party = fx.record_locate_outcome(scenario.ncp_id, "LOCATED")
    return scenario


def _order_with_three_monthly_charges() -> fx.Scenario:
    """An entered order at 75,000 cents carrying three consecutive charges."""
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Dana Ruiz", "ssn_last4": "1414"},
        ncp_overrides={"full_name": "Alex Ruiz", "ssn_last4": "1515"},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = fx.post_monthly_charges(
        scenario.order_id, ["2026-08-01", "2026-09-01", "2026-10-01"], due_day=15
    )
    return scenario


def _assistance_case_with_one_part_paid_charge() -> fx.Scenario:
    """
    A TANF case whose single 75,000-cent charge is due and 20,000 cents paid.

    The clock stands at 2026-08-20: the charge's due date has passed, so the
    unpaid remainder is arrears, but no month end has gone by since it fell due.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Dana Ruiz", "ssn_last4": "1616"},
        ncp_overrides={"full_name": "Alex Ruiz", "ssn_last4": "1717"},
        case_overrides={
            "case_type": "PA_REFERRAL",
            "tanf_assistance": True,
            "child_count": 2,
            "good_cause_claim": False,
        },
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = [fx.post_monthly_charge(scenario.order_id, "2026-08-01", due_day=15)]
    fx.set_clock("2026-08-20T00:00:00Z")
    scenario.payments = [fx.post_payment(scenario.case_id, 20000, source="DIRECT_PAY")]
    scenario.reload_case()
    return scenario


# ---------------------------------------------------------------------------
# What a create returns
# ---------------------------------------------------------------------------


def test_01_registering_a_participant_returns_the_whole_row_at_once():
    """
    One create, and every server-maintained field is already populated.

    Every persisted resource carries a server-minted `id` — a UUID with no type prefix of any kind — and a `created_at` timestamp rendered as an ISO 8601 UTC instant with exactly three fractional-second digits.

    `locate_status` starts at `NOT_NEEDED` and may become `PENDING`, `LOCATED` or `UNLOCATABLE`.

    Three remedy flags — `license_suspension_active`, `lien_recorded` and `credit_bureau_reported` — all start false and are true only while an `ACTIVE` enforcement remedy of the matching kind names the participant.

    Design: Corner/entities/participant_creation_returns_every_declared_field
    """
    fx.set_clock(CLOCK_START)

    response = api_client.create_participant(
        f.participant_payload(**OBLIGOR_REQUEST), CASE_WORKER_HEADERS
    )
    created = validate_success(response, 201)

    a.assert_versioned_row(created, expected_version=1)
    assert is_valid_uuid(created["id"])
    a.assert_instant_equals(created["created_at"], CLOCK_START, "created_at")
    a.assert_instant_equals(created["updated_at"], CLOCK_START, "updated_at")

    # Every declared input is echoed exactly as it was sent.
    for field, value in OBLIGOR_REQUEST.items():
        assert created[field] == value, f"{field} was not echoed: {created[field]!r}"

    assert created["locate_status"] == "NOT_NEEDED"
    assert created["locate_attempt_count"] == 0
    assert created["license_suspension_active"] is False
    assert created["lien_recorded"] is False
    assert created["credit_bureau_reported"] is False


def test_02_the_computed_figures_of_a_participant_with_no_cases_are_all_zero():
    """
    The four computed figures are present and at their empty-universe values.

    Four computed figures round out the row: `enforcement_risk_score` with its band `enforcement_risk_tier`, `compromise_risk_score` with its band `compromise_risk_tier`, the cross-case `total_arrears_certified_cents`, and `open_case_count`, the number of `SupportCase` rows referencing this participant in either party field whose `case_status` is not `CLOSED`.

    The **payment-history component** is 100 minus the floor of one hundred times the summed `total_collected_principal_cents` divided by the greater of 1 and the summed `total_charged_principal_cents`, and it is 0 outright when nothing has been charged.

    Both scores band identically: a score of at least 67 is `HIGH`, a score of at least 34 but below 67 is `MEDIUM`, and anything below 34 is `LOW`.

    Design: Corner/entities/participant_creation_returns_every_declared_field
    """
    fx.set_clock(CLOCK_START)

    created = validate_success(
        api_client.create_participant(
            f.participant_payload(**OBLIGOR_REQUEST), CASE_WORKER_HEADERS
        ),
        201,
    )

    assert created["enforcement_risk_score"] == 0
    assert created["enforcement_risk_tier"] == "LOW"
    assert created["compromise_risk_score"] == 0
    assert created["compromise_risk_tier"] == "LOW"
    assert created["total_arrears_certified_cents"] == 0
    assert created["open_case_count"] == 0

    # The computing read reaches the same conclusion from the same empty data.
    reread = fx.read_participant(created["id"])
    assert reread["enforcement_risk_score"] == 0
    assert reread["compromise_risk_score"] == 0
    assert reread["total_arrears_certified_cents"] == 0
    assert reread["open_case_count"] == 0
    assert reread["version"] == 1


def test_03_reading_a_freshly_opened_case_adds_nothing_and_loses_nothing():
    """
    The five inputs come back untouched beside nine money fields at zero.

    A newly opened case sits at `case_status` `OPENED`, `enforcement_posture` `NORMAL` and `interstate_role` `NONE`, with `locate_referral_count` at zero, every money field at zero, and `closed_reason` and `closed_at` both absent.

    Reading a case is likewise a computing read: `arrears_principal_cents`, `assigned_arrears_cents`, `unassigned_arrears_cents` and `interest_receivable_cents` are all recomputed before the row is returned, with `arrears_principal_cents` defined as the sum of `unpaid_balance_cents` across the case's charges whose `status` is `OPEN` and whose `due_date` falls on or before the current logical clock date.

    Design: Corner/entities/case_single_read_returns_the_stored_row
    """
    scenario = _two_parties_and_no_case()
    case = fx.open_case(
        scenario.cp_id,
        scenario.ncp_id,
        case_type="DIRECT_APPLICATION",
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )

    stored = validate_success(api_client.get_case(case["id"], CASE_WORKER_HEADERS))

    assert stored["case_type"] == "DIRECT_APPLICATION"
    assert stored["custodial_party_id"] == scenario.cp_id
    assert stored["noncustodial_party_id"] == scenario.ncp_id
    assert stored["child_count"] == 2
    assert stored["tanf_assistance"] is False
    assert stored["good_cause_claim"] is False

    a.assert_case_dimensions(stored, "OPENED", "NORMAL", "NONE")
    a.assert_money_fields(
        stored,
        arrears_principal_cents=0,
        assigned_arrears_cents=0,
        unassigned_arrears_cents=0,
        interest_receivable_cents=0,
        interest_collected_cents=0,
        interest_written_off_cents=0,
        unapplied_credit_cents=0,
        total_charged_principal_cents=0,
        total_collected_principal_cents=0,
    )
    assert stored["locate_referral_count"] == 0
    a.assert_absent(stored, "closed_reason", "closed_at")
    a.assert_versioned_row(stored, expected_version=1)


# ---------------------------------------------------------------------------
# What a listing returns
# ---------------------------------------------------------------------------


def test_04_two_pages_of_charges_report_the_same_pre_pagination_total():
    """
    Three charges, a window of two, and `has_more` telling the truth twice.

    The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` counts the rows matching the filters before pagination is applied and `has_more` is true exactly when rows remain beyond the current window.

    Collections are returned in ascending `created_at` order — oldest row first — and that ordering is stable and unconditional; no list endpoint offers an alternative sort.

    Design: Corner/entities/charge_listing_paginates_with_total_count_and_has_more
    """
    scenario = _order_with_three_monthly_charges()
    posted_ids = [charge["id"] for charge in scenario.charges]

    first, first_meta = validate_paginated(
        api_client.list_charges(
            FINANCE_OFFICER_HEADERS,
            {"order_id": scenario.order_id, "limit": 2, "offset": 0},
        )
    )
    assert len(first) == 2
    a.assert_pagination(first_meta, total_count=3, has_more=True, limit=2, offset=0)
    a.assert_ascending_created_at(first)

    second, second_meta = validate_paginated(
        api_client.list_charges(
            FINANCE_OFFICER_HEADERS,
            {"order_id": scenario.order_id, "limit": 2, "offset": 2},
        )
    )
    assert len(second) == 1
    a.assert_pagination(second_meta, total_count=3, has_more=False, limit=2, offset=2)

    assert first[0]["id"] != second[0]["id"]
    # The two windows partition the three posted rows exactly.
    assert [row["id"] for row in first] + [row["id"] for row in second] == posted_ids


def test_05_the_unpaginated_listing_falls_back_to_the_declared_default_window():
    """
    Three rows fit inside a default window of ten, and a filter empties the set.

    `limit` defaults to 10 when omitted, has a minimum of 1 and a maximum of 100.

    Charges accept `case_id`, `order_id`, `status` and `charge_type`.

    Design: Corner/entities/charge_listing_paginates_with_total_count_and_has_more
    """
    scenario = _order_with_three_monthly_charges()

    rows, meta = validate_paginated(
        api_client.list_charges(FINANCE_OFFICER_HEADERS, {"order_id": scenario.order_id})
    )
    assert len(rows) == 3
    a.assert_pagination(meta, total_count=3, has_more=False, limit=DEFAULT_LIMIT, offset=0)

    voided, void_meta = validate_paginated(
        api_client.list_charges(
            FINANCE_OFFICER_HEADERS, {"order_id": scenario.order_id, "status": "VOID"}
        )
    )
    assert voided == []
    a.assert_pagination(void_meta, total_count=0, has_more=False)

    # The case-side filter reaches the same three rows from the other direction.
    by_case, case_meta = validate_paginated(
        api_client.list_charges(FINANCE_OFFICER_HEADERS, {"case_id": scenario.case_id})
    )
    assert len(by_case) == 3
    a.assert_pagination(case_meta, total_count=3)


# ---------------------------------------------------------------------------
# What an unresolvable path segment returns
# ---------------------------------------------------------------------------


def test_06_each_of_the_twelve_path_segments_answers_with_its_own_not_found():
    """
    One absent identifier, twelve reads, twelve different error identifiers.

    `{participant_id}` must resolve to a `Participant` or the answer is `ERR_PARTICIPANT_NOT_FOUND`; `{case_id}` to a `SupportCase` or `ERR_CASE_NOT_FOUND`; `{paternity_action_id}` to a `PaternityAction` or `ERR_PATERNITY_ACTION_NOT_FOUND`; `{order_id}` to a `SupportOrder` or `ERR_ORDER_NOT_FOUND`; `{employer_id}` to an `Employer` or `ERR_EMPLOYER_NOT_FOUND`; `{iwo_id}` to an `IncomeWithholdingOrder` or `ERR_IWO_NOT_FOUND`; `{charge_id}` to an `ObligationCharge` or `ERR_CHARGE_NOT_FOUND`; `{payment_id}` to a `PaymentTransaction` or `ERR_PAYMENT_NOT_FOUND`; `{modification_review_id}` to a `ModificationReview` or `ERR_REVIEW_NOT_FOUND`; `{enforcement_action_id}` to an `EnforcementAction` or `ERR_ENFORCEMENT_ACTION_NOT_FOUND`; `{interstate_referral_id}` to an `InterstateReferral` or `ERR_REFERRAL_NOT_FOUND`; and `{compromise_offer_id}` to a `CompromiseOffer` or `ERR_OFFER_NOT_FOUND`.

    All twelve of these are HTTP 404.

    The `message` provides a human-readable explanation of what went wrong.

    Design: Corner/entities/every_path_id_segment_returns_its_own_not_found_error
    """
    fx.set_clock(CLOCK_START)

    reads = [
        (api_client.get_participant, ApiErrorId.PARTICIPANT_NOT_FOUND.value),
        (api_client.get_case, ApiErrorId.CASE_NOT_FOUND.value),
        (api_client.get_paternity_action, ApiErrorId.PATERNITY_ACTION_NOT_FOUND.value),
        (api_client.get_order, ApiErrorId.ORDER_NOT_FOUND.value),
        (api_client.get_employer, ApiErrorId.EMPLOYER_NOT_FOUND.value),
        (api_client.get_withholding_order, ApiErrorId.IWO_NOT_FOUND.value),
        (api_client.get_charge, ApiErrorId.CHARGE_NOT_FOUND.value),
        (api_client.get_payment, ApiErrorId.PAYMENT_NOT_FOUND.value),
        (api_client.get_modification_review, ApiErrorId.REVIEW_NOT_FOUND.value),
        (api_client.get_enforcement_action, ApiErrorId.ENFORCEMENT_ACTION_NOT_FOUND.value),
        (api_client.get_interstate_referral, ApiErrorId.REFERRAL_NOT_FOUND.value),
        (api_client.get_compromise_offer, ApiErrorId.OFFER_NOT_FOUND.value),
    ]

    seen = []
    for read, expected_error_id in reads:
        body = validate_error(read(MISSING_UUID, CASE_WORKER_HEADERS), expected_error_id, 404)
        assert isinstance(body.get("message"), str) and body["message"] != ""
        seen.append(body["error_id"])

    a.assert_all_distinct(seen, "not-found error ids")
    assert len(seen) == 12


# ---------------------------------------------------------------------------
# Required inputs and declared defaults
# ---------------------------------------------------------------------------


def test_07_each_required_case_input_is_rejected_when_it_is_the_one_omitted():
    """
    Five omissions, five payload refusals, and the sixth input is optional.

    The payload names a `case_type`, the `custodial_party_id` and `noncustodial_party_id` of the two participants, a `child_count` between 1 and 6, the `tanf_assistance` flag that must agree with the case type, and optionally `good_cause_claim`.

    Next comes payload schema validation (`ERR_VALIDATION`): required fields present, enum values inside their declared sets, integer money values non-negative, `child_count` between 1 and 6 inclusive, `installment_count` between 3 and 36 inclusive, `genetic_probability_pct` between 0 and 100 inclusive, and ISO dates well formed.

    Design: Corner/entities/case_creation_missing_required_child_count_is_rejected
    """
    scenario = _two_parties_and_no_case()
    complete = {
        "case_type": "DIRECT_APPLICATION",
        "custodial_party_id": scenario.cp_id,
        "noncustodial_party_id": scenario.ncp_id,
        "child_count": 2,
        "tanf_assistance": False,
    }

    for omitted in complete:
        partial = {key: value for key, value in complete.items() if key != omitted}
        response = api_client.create_case(partial, CASE_WORKER_HEADERS)
        refusal = validate_error(response, ApiErrorId.VALIDATION.value, 422)
        assert refusal["error_id"] == ApiErrorId.VALIDATION.value, f"omitted {omitted}"

    # The one input that carries a declared default may be left out safely.
    opened = validate_success(api_client.create_case(complete, CASE_WORKER_HEADERS), 201)
    assert opened["good_cause_claim"] is False

    cases, meta = validate_paginated(api_client.list_cases(CASE_WORKER_HEADERS))
    assert meta["total_count"] == 1
    assert [row["id"] for row in cases] == [opened["id"]]


def test_08_omitting_every_optional_input_lands_on_the_declared_defaults():
    """
    A participant, a case, an employer and an order built from required inputs only.

    The provenance of that figure is `income_verification_source`, one of `VERIFIED_WAGE_RECORD`, `SELF_REPORTED` or `NONE`, defaulting to `NONE`.

    A boolean `supports_second_family` records whether the obligor supports a second family in the same household and defaults to false; it is an input to both the guideline credit and the federal withholding tier.

    A boolean `has_valid_drivers_license` records whether the person holds an unsuspended state licence and defaults to true.

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    fx.set_clock(CLOCK_START)

    obligor = validate_success(
        api_client.create_participant(
            {
                "role_type": "NONCUSTODIAL_PARTY",
                "full_name": "Alex Ruiz",
                "ssn_last4": "1313",
                "residence_state_code": "MN",
            },
            CASE_WORKER_HEADERS,
        ),
        201,
    )

    assert obligor["income_verification_source"] == "NONE"
    assert obligor["supports_second_family"] is False
    assert obligor["has_valid_drivers_license"] is True
    # Inputs with no declared default stay absent rather than becoming zero.
    a.assert_absent(obligor, "monthly_gross_income_cents", "employer_name")


def test_09_the_case_employer_and_order_defaults_are_populated_not_absent():
    """
    Three more creates, each one input short, and each declared default present.

    A family-violence good-cause claim, recorded as `good_cause_claim` on the case and defaulting to false, bars the agency from disclosing party information to anyone outside it.

    An optional `remittance_fee_cents` records the per-payment administrative fee the employer may retain from the employee; it defaults to zero and may not exceed 500 cents — five dollars.

    Employers in `MN`, `NY`, `FL`, `CA` and `PA` have no state ceiling of their own — their `statutory_cap_pct` is absent, and those employers defer entirely to the federal ceiling.

    Two money inputs are optional: `medical_support_monthly_cents`, the monthly cash medical add-on, defaults to zero and must not be negative; and `requested_monthly_cents`, the amount the caseworker asks the order to carry, defaults to absent, must not be negative when present, and when absent means the order should take the guideline amount as calculated.

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    scenario = _two_parties_and_no_case()

    case = validate_success(
        api_client.create_case(
            {
                "case_type": "DIRECT_APPLICATION",
                "custodial_party_id": scenario.cp_id,
                "noncustodial_party_id": scenario.ncp_id,
                "child_count": 1,
                "tanf_assistance": False,
            },
            CASE_WORKER_HEADERS,
        ),
        201,
    )
    assert case["good_cause_claim"] is False

    employer = validate_success(
        api_client.create_employer(
            {
                "legal_name": "Kestrel Metalworks Inc",
                "fein": f.next_fein(),
                "state_code": "MN",
                "pay_frequency": "MONTHLY",
            },
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )
    assert employer["remittance_fee_cents"] == 0
    assert employer["active_iwo_count"] == 0
    a.assert_absent(employer, "statutory_cap_pct")

    fx.open_paternity_action(case["id"], "PRESUMED_MARITAL")
    order = validate_success(
        api_client.create_order(
            case["id"],
            {
                "order_type": "CURRENT_SUPPORT",
                "origin_state_code": "MN",
                "effective_date": "2026-08-01",
            },
            CASE_WORKER_HEADERS,
        ),
        201,
    )
    assert order["medical_support_monthly_cents"] == 0
    a.assert_absent(order, "requested_monthly_cents")


# ---------------------------------------------------------------------------
# Money fields recomputed from the charge and payment rows
# ---------------------------------------------------------------------------


def test_10_a_payment_on_an_assistance_case_splits_at_the_pass_through_cap():
    """
    20,000 cents lands wholly in bucket one and then divides ten thousand each way.

    **Bucket one, current support for the current period**: the `OPEN` `CURRENT_SUPPORT` charges of the case whose period contains the payment's `received_at` date — that is, `period_start_date` less than or equal to that date and `period_end_date` strictly greater — are taken in order of `due_date` and then `created_at`, and each absorbs the smaller of the remaining balance and its own `unpaid_balance_cents`, accumulating into `applied_current_cents`.

    On an assistance case the arrears are assigned to the state and only a capped pass-through of *current* support reaches the family: the pass-through is the smaller of `applied_current_cents` and 10,000 cents — one hundred dollars — `disbursed_to_cp_cents` is exactly that pass-through, and `retained_by_state_cents` is the whole distributable total less the pass-through.

    Both branches are exact integer arithmetic with no rounding step, and both satisfy the same invariant: `disbursed_to_cp_cents` plus `retained_by_state_cents` plus the payment's `unapplied_credit_cents` equals `amount_cents`.

    Design: Corner/entities/case_money_fields_derive_from_charges_payments_and_the_tanf_flag
    """
    scenario = _assistance_case_with_one_part_paid_charge()
    payment = scenario.payments[0]

    assert scenario.case["tanf_assistance"] is True
    assert scenario.order["monthly_obligation_cents"] == 75000

    a.assert_waterfall_buckets(
        payment,
        applied_current_cents=20000,
        applied_medical_cents=0,
        applied_arrears_cents=0,
        applied_interest_cents=0,
        applied_genetic_cost_cents=0,
        unapplied_credit_cents=0,
    )
    # min(applied_current 20000, 10000) reaches the family; the rest is retained.
    assert payment["disbursed_to_cp_cents"] == 10000
    assert payment["retained_by_state_cents"] == 10000
    a.assert_distribution_invariant(payment)
    a.assert_instant_equals(payment["received_at"], "2026-08-20T00:00:00Z", "received_at")


def test_11_the_case_arrears_fields_follow_the_charge_and_the_assistance_flag():
    """
    55,000 cents of unpaid balance, all of it assigned, and no interest yet.

    Reading a case is likewise a computing read: `arrears_principal_cents`, `assigned_arrears_cents`, `unassigned_arrears_cents` and `interest_receivable_cents` are all recomputed before the row is returned, with `arrears_principal_cents` defined as the sum of `unpaid_balance_cents` across the case's charges whose `status` is `OPEN` and whose `due_date` falls on or before the current logical clock date.

    Assignment is what splits the arrears figure into two computed components: `assigned_arrears_cents` equals `arrears_principal_cents` when `tanf_assistance` is true and equals zero otherwise, and `unassigned_arrears_cents` is `arrears_principal_cents` minus `assigned_arrears_cents`.

    The **aggregate month-end measure** instead walks every calendar month-end date falling strictly before the as-of date.

    Design: Corner/entities/case_money_fields_derive_from_charges_payments_and_the_tanf_flag
    """
    scenario = _assistance_case_with_one_part_paid_charge()

    charge = fx.read_charge(scenario.charges[0]["id"])
    assert charge["amount_cents"] == 75000
    assert charge["paid_cents"] == 20000
    assert charge["unpaid_balance_cents"] == 55000
    assert charge["status"] == "OPEN"

    settled = fx.read_case(scenario.case_id)
    assert settled["arrears_principal_cents"] == 55000
    assert settled["assigned_arrears_cents"] == 55000
    assert settled["unassigned_arrears_cents"] == 0
    # The only month end before 2026-08-20 is 2026-07-31, when nothing was due.
    assert settled["interest_receivable_cents"] == 0
    assert settled["total_charged_principal_cents"] == 75000


# ---------------------------------------------------------------------------
# System fields, the logical clock and the version counter
# ---------------------------------------------------------------------------


def test_12_the_audit_stamps_are_minted_from_the_clock_and_never_from_input():
    """
    Two participants created a month apart, then one of them patched a month later.

    Most resources additionally carry `updated_at`, in the same format, refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row.

    The clock starts at the fixed instant 2026-08-01T00:00:00Z and must not fall back to real wall-clock time before the first clock-setting call.

    The participant's `version` increases by 1 and both risk variants are recomputed.

    Design: Corner/entities/system_fields_are_clock_derived_and_version_increments_on_patch
    """
    fx.set_clock(CLOCK_START)
    first = fx.create_noncustodial_party(full_name="Alex Ruiz", ssn_last4="1616")
    a.assert_instant_equals(first["created_at"], CLOCK_START, "created_at")
    a.assert_instant_equals(first["updated_at"], CLOCK_START, "updated_at")
    assert first["version"] == 1

    fx.set_clock("2026-09-01T00:00:00Z")
    second = fx.create_custodial_party(full_name="Dana Ruiz", ssn_last4="1717")
    # The second create reads the moved clock, not the process start time.
    a.assert_instant_equals(second["created_at"], "2026-09-01T00:00:00Z", "created_at")
    assert second["version"] == 1
    assert first["created_at"] != second["created_at"]
    assert first["id"] != second["id"]
    assert is_valid_uuid(second["id"])

    fx.set_clock("2026-10-01T00:00:00Z")
    patched = fx.patch_income(first["id"], 330000, "VERIFIED_WAGE_RECORD")

    assert patched["id"] == first["id"]
    a.assert_instant_equals(patched["created_at"], CLOCK_START, "created_at")
    a.assert_instant_equals(patched["updated_at"], "2026-10-01T00:00:00Z", "updated_at")
    assert patched["version"] == 2
    assert patched["monthly_gross_income_cents"] == 330000

    # Patching one row leaves the other exactly where it was.
    untouched = fx.read_participant(second["id"])
    a.assert_instant_equals(untouched["updated_at"], "2026-09-01T00:00:00Z", "updated_at")
    assert untouched["version"] == 1


def test_13_a_value_outside_its_declared_type_is_refused_at_the_payload_band():
    """
    Seven well-formed requests break a declared constraint; the inclusive top passes.

    A `CaseWorker` registers each person as a `Participant`, declaring a `role_type` of either `CUSTODIAL_PARTY` or `NONCUSTODIAL_PARTY`, a `full_name` between 1 and 120 characters, an `ssn_last4` of exactly four digits used for locate matching, and a `residence_state_code`.

    A `monthly_gross_income_cents` figure may be supplied and defaults to absent, and when present it must not be negative; absent means the income is unknown.

    Registration names a `legal_name`, a `fein` in the two-digit, hyphen, seven-digit form that must be unique across all employers, a `state_code`, and a `pay_frequency` of `WEEKLY`, `BIWEEKLY`, `SEMIMONTHLY` or `MONTHLY` describing the payroll cycle.

    Design: Corner/entities/type_constraints_bound_enums_and_integer_ranges
    """
    scenario = _two_parties_and_no_case()
    fein = f.next_fein()

    def case_body(**overrides):
        body = {
            "case_type": "DIRECT_APPLICATION",
            "custodial_party_id": scenario.cp_id,
            "noncustodial_party_id": scenario.ncp_id,
            "child_count": 2,
            "tanf_assistance": False,
        }
        body.update(overrides)
        return body

    refused = [
        api_client.create_participant(
            {
                "role_type": "PARENT",
                "full_name": "Kim Vance",
                "ssn_last4": "2020",
                "residence_state_code": "MN",
            },
            CASE_WORKER_HEADERS,
        ),
        api_client.create_participant(
            {
                "role_type": "NONCUSTODIAL_PARTY",
                "full_name": "Kim Vance",
                "ssn_last4": "2020",
                "residence_state_code": "MN",
                "monthly_gross_income_cents": -1,
            },
            CASE_WORKER_HEADERS,
        ),
        api_client.create_participant(
            {
                "role_type": "NONCUSTODIAL_PARTY",
                "full_name": "Kim Vance",
                "ssn_last4": "2020",
                "residence_state_code": "MN",
                "monthly_gross_income_cents": 300000,
                "income_verification_source": "GUESSED",
            },
            CASE_WORKER_HEADERS,
        ),
        api_client.create_case(case_body(child_count=7), CASE_WORKER_HEADERS),
        api_client.create_case(case_body(child_count=0), CASE_WORKER_HEADERS),
        api_client.create_employer(
            {
                "legal_name": "Kestrel Metalworks Inc",
                "fein": fein,
                "state_code": "MN",
                "pay_frequency": "DAILY",
            },
            PROGRAM_ADMIN_HEADERS,
        ),
        api_client.create_employer(
            {
                "legal_name": "Kestrel Metalworks Inc",
                "fein": fein,
                "state_code": "MN",
                "pay_frequency": "MONTHLY",
                "remittance_fee_cents": -5,
            },
            PROGRAM_ADMIN_HEADERS,
        ),
    ]
    for response in refused:
        validate_error(response, ApiErrorId.VALIDATION.value, 422)

    # The declared band is inclusive at its top.
    accepted = validate_success(
        api_client.create_case(case_body(child_count=6), CASE_WORKER_HEADERS), 201
    )
    assert accepted["child_count"] == 6

    _people, people_meta = validate_paginated(api_client.list_participants(CASE_WORKER_HEADERS))
    assert people_meta["total_count"] == 2
    _employers, employer_meta = validate_paginated(
        api_client.list_employers(PROGRAM_ADMIN_HEADERS)
    )
    assert employer_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# The two immutable financial events
# ---------------------------------------------------------------------------


def _non_assistance_case_with_one_charge_and_a_first_payment() -> fx.Scenario:
    """
    A DIRECT_APPLICATION case with one 75,000-cent charge and 20,000 cents paid
    against it at 2026-08-20, ready for a second collection to land beside it.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Dana Ruiz", "ssn_last4": "2121"},
        ncp_overrides={"full_name": "Alex Ruiz", "ssn_last4": "2222"},
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = [fx.post_monthly_charge(scenario.order_id, "2026-08-01", due_day=15)]
    fx.set_clock("2026-08-20T00:00:00Z")
    scenario.payments = [fx.post_payment(scenario.case_id, 20000, source="DIRECT_PAY")]
    return scenario


def test_14_a_posted_payment_is_unchanged_by_the_next_one_and_carries_no_version():
    """
    A second collection moves the charge and leaves the first payment row alone.

    Two resources are exceptions and carry only `id` and `created_at`: an `ObligationCharge` and a `PaymentTransaction` are immutable financial events.

    Neither has an `updated_at` field and neither has a `version` field, and neither exposes an update endpoint.

    On a non-assistance case the family receives current support, medical support and arrears: `disbursed_to_cp_cents` is `applied_current_cents` plus `applied_medical_cents` plus `applied_arrears_cents`, and `retained_by_state_cents` is `applied_interest_cents` plus `applied_genetic_cost_cents`.

    Design: Corner/entities/charge_and_payment_rows_expose_no_version_and_no_update_endpoint
    """
    scenario = _non_assistance_case_with_one_charge_and_a_first_payment()
    first = scenario.payments[0]

    assert first["applied_current_cents"] == 20000
    assert first["disbursed_to_cp_cents"] == 20000
    a.assert_immutable_financial_event(first)

    second = fx.post_payment(scenario.case_id, 5000, source="DIRECT_PAY")
    assert second["applied_current_cents"] == 5000
    a.assert_immutable_financial_event(second)
    assert second["id"] != first["id"]

    reread = fx.read_payment(first["id"])
    # Field for field identical: the second payment reallocated nothing.
    assert reread == first
    a.assert_immutable_financial_event(reread)

    charge = fx.read_charge(scenario.charges[0]["id"])
    assert charge["paid_cents"] == 25000
    assert charge["unpaid_balance_cents"] == 50000
    a.assert_immutable_financial_event(charge)


def test_15_the_charge_row_itself_carries_no_audit_stamp_beyond_its_creation():
    """
    The one operation that moves a charge bumps the case instead of the charge.

    A charge is immutable once posted: it carries no `version` field and there is no endpoint that edits it.

    Voiding a charge is the one operation that changes a charge's `status` after creation, and because the charge itself carries no version, that operation bumps the owning case's `version` instead.

    Design: Corner/entities/charge_and_payment_rows_expose_no_version_and_no_update_endpoint
    """
    scenario = _non_assistance_case_with_one_charge_and_a_first_payment()
    unpaid = fx.post_monthly_charge(scenario.order_id, "2026-09-01", due_day=15)

    a.assert_immutable_financial_event(unpaid)
    assert unpaid["status"] == "OPEN"
    assert unpaid["paid_cents"] == 0

    case_version_before = fx.read_case(scenario.case_id)["version"]
    voided = fx.void_charge(unpaid["id"])

    assert voided["status"] == "VOID"
    a.assert_immutable_financial_event(voided)
    assert fx.read_case(scenario.case_id)["version"] == case_version_before + 1


# ---------------------------------------------------------------------------
# The parent link and the body foreign keys
# ---------------------------------------------------------------------------


def test_16_the_parent_order_is_resolved_before_its_state_is_judged():
    """
    An absent order answers 404; a real but unentered one answers 409 twice.

    Next comes path-variable resolution, in left-to-right path order, yielding the appropriate not-found error.

    A `FinanceOfficer` posts a charge against an `ENTERED` order, naming a `charge_type` of `CURRENT_SUPPORT`, `MEDICAL_SUPPORT`, `ARREARS_JUDGMENT` or `GENETIC_TEST_COST`, the `period_start_date` that inclusively opens the obligation period, the `period_end_date` that **exclusively** closes it, and the `due_date` on which the charge became payable.

    `amount_cents` is optional: omitted, it defaults to the order's `monthly_obligation_cents` for a `CURRENT_SUPPORT` charge and to the order's `medical_support_monthly_cents` for a `MEDICAL_SUPPORT` charge.

    Design: Corner/entities/charge_posting_against_a_draft_parent_order_is_refused
    """
    scenario = _two_parties_and_no_case()
    case = fx.open_case(
        scenario.cp_id,
        scenario.ncp_id,
        case_type="DIRECT_APPLICATION",
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    fx.open_paternity_action(case["id"], "PRESUMED_MARITAL")
    order = fx.draft_order(
        case["id"],
        origin_state_code="MN",
        effective_date="2026-08-01",
        medical_support_monthly_cents=0,
    )
    charge_body = f.charge_payload(
        period_start_date="2026-08-01",
        period_end_date="2026-09-01",
        due_date="2026-08-15",
        amount_cents=75000,
    )

    # A bad path id never reaches the state check.
    validate_error(
        api_client.post_charge(MISSING_UUID, charge_body, FINANCE_OFFICER_HEADERS),
        ApiErrorId.ORDER_NOT_FOUND.value,
        404,
    )

    assert order["status"] == "DRAFT"
    validate_error(
        api_client.post_charge(order["id"], charge_body, FINANCE_OFFICER_HEADERS),
        ApiErrorId.INVALID_ORDER_STATUS.value,
        409,
    )

    calculated = fx.calculate_order(order["id"])
    assert calculated["status"] == "CALCULATED"
    assert calculated["guideline_monthly_cents"] == 75000
    validate_error(
        api_client.post_charge(order["id"], charge_body, FINANCE_OFFICER_HEADERS),
        ApiErrorId.INVALID_ORDER_STATUS.value,
        409,
    )

    entered = fx.enter_order(order["id"])
    assert entered["monthly_obligation_cents"] == 75000

    posted = validate_success(
        api_client.post_charge(
            order["id"],
            f.charge_payload(
                period_start_date="2026-08-01",
                period_end_date="2026-09-01",
                due_date="2026-08-15",
            ),
            FINANCE_OFFICER_HEADERS,
        ),
        201,
    )
    # The grandparent link is carried on the charge, not walked through a URL.
    assert posted["order_id"] == order["id"]
    assert posted["case_id"] == case["id"]
    assert posted["amount_cents"] == 75000


def test_17_the_case_body_keys_are_resolved_then_the_roles_then_the_flag():
    """
    Five refusals from three different bands on one endpoint, then the success.

    Foreign keys supplied in a request body rather than in the path — `custodial_party_id`, `noncustodial_party_id`, `employer_id`, `iwo_id`, `compromise_offer_id`, `signed_by_participant_id` and `participant_id` — are resolved after payload schema validation, and a body foreign key that does not resolve answers with `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404).

    The two named participants must carry the matching roles — the custodial id must point at a `CUSTODIAL_PARTY` participant and the noncustodial id at a `NONCUSTODIAL_PARTY` participant — and the two ids must differ; any violation is `ERR_PARTY_ROLE_MISMATCH` (HTTP 422).

    Any other combination is refused with `ERR_TANF_FLAG_MISMATCH` (HTTP 422).

    Below those come the referential checks in this order: party role agreement (`ERR_PARTY_ROLE_MISMATCH`), assistance-flag agreement (`ERR_TANF_FLAG_MISMATCH`), obligor whereabouts (`ERR_NCP_NOT_LOCATED`), and continuing exclusive jurisdiction (`ERR_NO_CONTROLLING_ORDER_JURISDICTION`).

    Design: Corner/entities/case_body_foreign_keys_are_resolved_then_role_and_flag_checked
    """
    scenario = _two_parties_and_no_case()

    def body(**overrides):
        payload = {
            "case_type": "DIRECT_APPLICATION",
            "custodial_party_id": scenario.cp_id,
            "noncustodial_party_id": scenario.ncp_id,
            "child_count": 2,
            "tanf_assistance": False,
        }
        payload.update(overrides)
        return payload

    validate_error(
        api_client.create_case(body(custodial_party_id=MISSING_UUID), CASE_WORKER_HEADERS),
        ApiErrorId.REFERENCED_ENTITY_NOT_FOUND.value,
        404,
    )
    # Both ids resolve, so the referential band answers instead.
    validate_error(
        api_client.create_case(
            body(custodial_party_id=scenario.ncp_id, noncustodial_party_id=scenario.cp_id),
            CASE_WORKER_HEADERS,
        ),
        ApiErrorId.PARTY_ROLE_MISMATCH.value,
        422,
    )
    validate_error(
        api_client.create_case(
            body(noncustodial_party_id=scenario.cp_id), CASE_WORKER_HEADERS
        ),
        ApiErrorId.PARTY_ROLE_MISMATCH.value,
        422,
    )
    validate_error(
        api_client.create_case(body(tanf_assistance=True), CASE_WORKER_HEADERS),
        ApiErrorId.TANF_FLAG_MISMATCH.value,
        422,
    )
    # The rule is an equivalence, not a one-way implication.
    validate_error(
        api_client.create_case(body(case_type="PA_REFERRAL"), CASE_WORKER_HEADERS),
        ApiErrorId.TANF_FLAG_MISMATCH.value,
        422,
    )

    opened = validate_success(
        api_client.create_case(
            body(case_type="PA_REFERRAL", tanf_assistance=True), CASE_WORKER_HEADERS
        ),
        201,
    )
    assert opened["custodial_party_id"] == scenario.cp_id
    assert opened["noncustodial_party_id"] == scenario.ncp_id
    assert opened["assigned_arrears_cents"] == 0

    _rows, meta = validate_paginated(api_client.list_cases(CASE_WORKER_HEADERS))
    assert meta["total_count"] == 1
