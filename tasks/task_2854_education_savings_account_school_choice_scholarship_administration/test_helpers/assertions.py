"""Shape assertions for the resources of the ESA administration API.

The common-property rules are checked here once so that every test can lean on
them: a bare UUID identifier with no type prefix, a ``created_at`` carrying
exactly three fractional-second digits, ``updated_at`` plus a ``version`` that
starts at 1 on mutable resources, and the deliberate absence of both of those on
the four append-only event record types.
"""

import re

from .api_client import canonical_instant

_BARE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_TS_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_CALENDAR_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def assert_bare_uuid(value, label="id"):
    """The identifier is a UUID with no type prefix of any kind."""
    assert isinstance(value, str), f"{label} should be a string, got {value!r}"
    assert _BARE_UUID.match(value), (
        f"{label} should be a bare UUID with no type prefix, got {value!r}"
    )


def assert_iso_millis(value, label="timestamp"):
    """The timestamp is an ISO 8601 UTC instant with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} should be a string, got {value!r}"
    assert _TS_MILLIS.match(value), (
        f"{label} should be an ISO 8601 UTC instant with exactly three "
        f"fractional-second digits, got {value!r}"
    )


def assert_calendar_date(value, label="date"):
    """The value is a plain YYYY-MM-DD calendar date."""
    assert isinstance(value, str), f"{label} should be a string, got {value!r}"
    assert _CALENDAR_DATE.match(value), (
        f"{label} should be a plain YYYY-MM-DD date, got {value!r}"
    )


def assert_instant_equals(actual, expected, label="timestamp"):
    """Two ISO 8601 UTC instants denote the same moment.

    The comparison runs through the canonical millisecond form so that a
    difference in printed fractional-second width is not treated as a mismatch.
    """
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label} should be the instant {expected!r}, got {actual!r}"
    )


def assert_money_cents(value, label="amount"):
    """A monetary quantity is a whole-cent integer, never a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} should be transported as a JSON integer of whole cents, got {value!r}"
    )


def assert_created_record(data, label="record"):
    """The identifier and creation instant every resource the API mints carries."""
    assert_bare_uuid(data.get("id"), f"{label}.id")
    assert_iso_millis(data.get("created_at"), f"{label}.created_at")


def assert_mutable_record(data, label="record", expected_version=None):
    """A mutable resource additionally carries ``updated_at`` and ``version``."""
    assert_created_record(data, label)
    assert_iso_millis(data.get("updated_at"), f"{label}.updated_at")
    version = data.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{label}.version should be an integer, got {version!r}"
    )
    assert version >= 1, f"{label}.version starts at 1, got {version!r}"
    if expected_version is not None:
        assert version == expected_version, (
            f"{label}.version should be {expected_version}, got {version}"
        )


def assert_append_only_record(data, label="record"):
    """An append-only event record carries only ``id`` and ``created_at``.

    Those four record types have no ``updated_at`` and no ``version`` field at all.
    """
    assert_created_record(data, label)
    assert "updated_at" not in data, (
        f"{label} is append-only event evidence and must carry no updated_at field, "
        f"got {data.get('updated_at')!r}"
    )
    assert "version" not in data, (
        f"{label} is append-only event evidence and must carry no version field, "
        f"got {data.get('version')!r}"
    )


def assert_version_advanced_by(before, after, steps=1, label="record"):
    """The resource's version rose by exactly ``steps``."""
    assert after == before + steps, (
        f"{label}.version should rise by exactly {steps} from {before}, got {after}"
    )


# --- Per-resource shape checks ---------------------------------------------------


def assert_program_year(data, label="program_year"):
    assert_mutable_record(data, label)
    assert data.get("status") in (
        "DRAFT",
        "WINDOW_OPEN",
        "AWARDING",
        "ACTIVE",
        "CLOSED",
    ), f"{label}.status is not a declared programme-year state: {data.get('status')!r}"
    assert_money_cents(data.get("base_award_cents"), f"{label}.base_award_cents")
    for field in ("total_seats", "seats_committed", "seats_available", "current_quarter"):
        value = data.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{label}.{field} should be an integer, got {value!r}"
        )
    assert 0 <= data["current_quarter"] <= 4, (
        f"{label}.current_quarter only ever holds 0 through 4, "
        f"got {data['current_quarter']}"
    )
    assert data["seats_available"] >= 0, (
        f"{label}.seats_available is never allowed to go below zero, "
        f"got {data['seats_available']}"
    )
    assert_calendar_date(data.get("term_start_date"), f"{label}.term_start_date")
    assert_calendar_date(data.get("term_end_date"), f"{label}.term_end_date")


def assert_expense_category(data, label="expense_category"):
    assert_mutable_record(data, label)
    assert _UPPER_SNAKE.match(str(data.get("code"))), (
        f"{label}.code should be uppercase snake case, got {data.get('code')!r}"
    )
    assert_money_cents(data.get("per_year_cap_cents"), f"{label}.per_year_cap_cents")
    assert data["per_year_cap_cents"] >= 1, (
        f"{label}.per_year_cap_cents is a ceiling of at least 1 cent, "
        f"got {data['per_year_cap_cents']}"
    )
    for flag in ("allowable", "requires_preapproval", "requires_service_period"):
        assert isinstance(data.get(flag), bool), (
            f"{label}.{flag} should be a boolean, got {data.get(flag)!r}"
        )


def assert_student(data, label="student"):
    assert_mutable_record(data, label)
    assert_calendar_date(data.get("date_of_birth"), f"{label}.date_of_birth")
    assert data.get("income_band") in ("BAND_A", "BAND_B", "BAND_C"), (
        f"{label}.income_band is not a declared band: {data.get('income_band')!r}"
    )
    assert isinstance(data.get("category_flags"), list), (
        f"{label}.category_flags should be a list, got {data.get('category_flags')!r}"
    )
    assert isinstance(data.get("has_enrolled_sibling"), bool), (
        f"{label}.has_enrolled_sibling should be a boolean, "
        f"got {data.get('has_enrolled_sibling')!r}"
    )


def assert_application(data, label="application"):
    assert_mutable_record(data, label)
    assert data.get("status") in (
        "DRAFT",
        "SUBMITTED",
        "ELIGIBLE",
        "DENIED",
        "UNDER_APPEAL",
        "DENIED_FINAL",
        "AWARD_OFFERED",
        "WAITLISTED",
        "ACCEPTED",
        "EXPIRED",
        "WITHDRAWN",
        "COMPLETED",
    ), f"{label}.status is not a declared application state: {data.get('status')!r}"
    assert_bare_uuid(data.get("program_year_id"), f"{label}.program_year_id")
    assert_bare_uuid(data.get("student_id"), f"{label}.student_id")
    assert_money_cents(
        data.get("provisional_award_cents"), f"{label}.provisional_award_cents"
    )
    assert_money_cents(data.get("annual_award_cents"), f"{label}.annual_award_cents")
    assert isinstance(data.get("appeal_round_count"), int), (
        f"{label}.appeal_round_count should be an integer, "
        f"got {data.get('appeal_round_count')!r}"
    )


def assert_eligibility_determination(data, label="determination"):
    assert_append_only_record(data, label)
    assert data.get("outcome") in ("ELIGIBLE", "INELIGIBLE"), (
        f"{label}.outcome should be ELIGIBLE or INELIGIBLE, got {data.get('outcome')!r}"
    )
    assert data.get("residency_check") in ("PASS", "FAIL"), (
        f"{label}.residency_check should be PASS or FAIL, "
        f"got {data.get('residency_check')!r}"
    )
    assert data.get("prior_enrollment_check") in ("PASS", "FAIL"), (
        f"{label}.prior_enrollment_check should be PASS or FAIL, "
        f"got {data.get('prior_enrollment_check')!r}"
    )
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 1, (
        f"{label}.round_number is 1 for the first determination and one higher on "
        f"each re-determination, got {data.get('round_number')!r}"
    )
    assert isinstance(data.get("decided_by_user_id"), str), (
        f"{label}.decided_by_user_id should record the acting operator, "
        f"got {data.get('decided_by_user_id')!r}"
    )


def assert_account(data, label="account"):
    assert_mutable_record(data, label)
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "CLOSED"), (
        f"{label}.status should be ACTIVE, SUSPENDED or CLOSED, got {data.get('status')!r}"
    )
    for field in (
        "balance_cents",
        "encumbered_cents",
        "lifetime_disbursed_cents",
        "lifetime_admin_fee_cents",
        "lifetime_spent_cents",
        "lifetime_clawed_back_cents",
        "final_award_cents",
    ):
        assert_money_cents(data.get(field), f"{label}.{field}")
    assert isinstance(data.get("disbursement_count"), int), (
        f"{label}.disbursement_count should be an integer, "
        f"got {data.get('disbursement_count')!r}"
    )
    assert data["balance_cents"] >= 0, (
        f"{label}.balance_cents is never negative, got {data['balance_cents']}"
    )
    assert data["encumbered_cents"] >= 0, (
        f"{label}.encumbered_cents is never negative, got {data['encumbered_cents']}"
    )


def assert_disbursement(data, label="disbursement"):
    assert_append_only_record(data, label)
    for field in ("gross_amount_cents", "admin_fee_cents", "net_credited_cents"):
        assert_money_cents(data.get(field), f"{label}.{field}")
    assert (
        data["net_credited_cents"] == data["gross_amount_cents"] - data["admin_fee_cents"]
    ), (
        f"{label}.net_credited_cents should be the gross less the admin fee: "
        f"{data['gross_amount_cents']} - {data['admin_fee_cents']} != "
        f"{data['net_credited_cents']}"
    )
    assert 1 <= data.get("quarter", 0) <= 4, (
        f"{label}.quarter should name a quarter from 1 through 4, got {data.get('quarter')!r}"
    )


def assert_provider(data, label="provider"):
    assert_mutable_record(data, label)
    assert data.get("status") in (
        "DRAFT",
        "SCREENED",
        "APPROVED",
        "PROBATION",
        "DELISTED",
        "PERMANENTLY_BARRED",
    ), f"{label}.status is not a declared provider state: {data.get('status')!r}"
    for field in ("screening_score", "surveillance_score", "substantiated_case_count"):
        value = data.get(field)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{label}.{field} should be an integer, got {value!r}"
        )
    assert 0 <= data["screening_score"] <= 100, (
        f"{label}.screening_score is capped at 100, got {data['screening_score']}"
    )
    assert 0 <= data["surveillance_score"] <= 100, (
        f"{label}.surveillance_score is capped at 100, got {data['surveillance_score']}"
    )
    assert isinstance(data.get("authorized_category_codes"), list), (
        f"{label}.authorized_category_codes should be a list, "
        f"got {data.get('authorized_category_codes')!r}"
    )


def assert_fraud_screening(data, label="screening"):
    assert_append_only_record(data, label)
    assert data.get("recommended_status") in ("APPROVE", "PROBATION", "REJECT"), (
        f"{label}.recommended_status should be APPROVE, PROBATION or REJECT, "
        f"got {data.get('recommended_status')!r}"
    )
    score = data.get("screening_score")
    assert isinstance(score, int) and 0 <= score <= 100, (
        f"{label}.screening_score is a whole number capped at 100, got {score!r}"
    )
    assert_iso_millis(data.get("screened_at"), f"{label}.screened_at")


def assert_purchase_request(data, label="purchase_request"):
    assert_mutable_record(data, label)
    assert data.get("approval_status") in ("PENDING_REVIEW", "APPROVED", "DENIED", "VOID"), (
        f"{label}.approval_status is not a declared approval-track state: "
        f"{data.get('approval_status')!r}"
    )
    assert data.get("settlement_status") in (
        "UNSETTLED",
        "CLAIMED",
        "PAID",
        "REVERSED",
        "CANCELLED",
    ), (
        f"{label}.settlement_status is not a declared money-track state: "
        f"{data.get('settlement_status')!r}"
    )
    assert data.get("flow") in ("PREAPPROVAL", "REIMBURSEMENT"), (
        f"{label}.flow should be PREAPPROVAL or REIMBURSEMENT, got {data.get('flow')!r}"
    )
    assert_money_cents(data.get("amount_cents"), f"{label}.amount_cents")
    assert data["amount_cents"] >= 1, (
        f"{label}.amount_cents is at least 1 cent, got {data['amount_cents']}"
    )


def assert_misuse_case(data, label="misuse_case"):
    assert_mutable_record(data, label)
    assert data.get("status") in (
        "OPEN",
        "UNDER_REVIEW",
        "SUBSTANTIATED",
        "DISMISSED",
        "CLAWBACK_ISSUED",
        "UNDER_APPEAL",
        "RESOLVED",
        "REVERSED",
    ), f"{label}.status is not a declared misuse-case state: {data.get('status')!r}"
    assert data.get("detection_rule") in (
        "DUPLICATE_INVOICE",
        "NON_ALLOWABLE_EXPENSE",
        "PROVIDER_COLLUSION",
        "FALSIFIED_ENROLLMENT",
        "CAP_CIRCUMVENTION",
    ), f"{label}.detection_rule is not a declared rule: {data.get('detection_rule')!r}"
    assert_money_cents(
        data.get("disallowed_principal_cents"), f"{label}.disallowed_principal_cents"
    )
    assert isinstance(data.get("auto_opened"), bool), (
        f"{label}.auto_opened should be a boolean, got {data.get('auto_opened')!r}"
    )


def assert_clawback_entry(data, label="clawback_entry"):
    assert_append_only_record(data, label)
    assert data.get("entry_type") in ("ACCOUNT_DEBIT", "RECEIVABLE", "REVERSAL"), (
        f"{label}.entry_type is not a declared ledger entry type: "
        f"{data.get('entry_type')!r}"
    )
    assert_money_cents(data.get("amount_cents"), f"{label}.amount_cents")
    assert isinstance(data.get("created_by_user_id"), str), (
        f"{label}.created_by_user_id should record the acting operator or the literal "
        f"string system, got {data.get('created_by_user_id')!r}"
    )


def assert_renewal_review(data, label="renewal_review"):
    assert_mutable_record(data, label)
    assert data.get("status") in ("SUBMITTED", "APPROVED", "DENIED", "SUPERSEDED"), (
        f"{label}.status is not a declared review state: {data.get('status')!r}"
    )
    assert data.get("assessment_type") in ("NORM_REFERENCED_TEST", "PORTFOLIO"), (
        f"{label}.assessment_type should be NORM_REFERENCED_TEST or PORTFOLIO, "
        f"got {data.get('assessment_type')!r}"
    )


def assert_appeal(data, label="appeal"):
    assert_mutable_record(data, label)
    assert data.get("status") in ("FILED", "OVERTURNED", "UPHELD"), (
        f"{label}.status is not a declared appeal state: {data.get('status')!r}"
    )
    assert data.get("subject_type") in (
        "APPLICATION_DENIAL",
        "CLAWBACK",
        "PROVIDER_DELISTING",
    ), f"{label}.subject_type is not a declared subject: {data.get('subject_type')!r}"
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 1, (
        f"{label}.round_number is 1-based, got {data.get('round_number')!r}"
    )


def assert_ledger_identity(account, label="account"):
    """The lifetime credit identity that must hold after every operation.

    Every cent the disbursement runs credited is either still spendable, held
    against an approved purchase, spent, clawed back, or withheld as the
    administration fee.
    """
    accounted = (
        account["balance_cents"]
        + account["encumbered_cents"]
        + account["lifetime_spent_cents"]
        + account["lifetime_clawed_back_cents"]
        + account["lifetime_admin_fee_cents"]
        + account.get("forfeited_cents", 0)
        + account.get("rolled_out_cents", 0)
    )
    credited = account["lifetime_disbursed_cents"] + account.get("rollover_in_cents", 0)
    assert accounted == credited, (
        f"{label} ledger identity broken: balance {account['balance_cents']} + "
        f"encumbered {account['encumbered_cents']} + spent "
        f"{account['lifetime_spent_cents']} + clawed back "
        f"{account['lifetime_clawed_back_cents']} + fees "
        f"{account['lifetime_admin_fee_cents']} + forfeited "
        f"{account.get('forfeited_cents', 0)} + rolled out "
        f"{account.get('rolled_out_cents', 0)} = {accounted}, but disbursed plus "
        f"rolled in = {credited}"
    )


__all__ = [
    "assert_bare_uuid",
    "assert_iso_millis",
    "assert_calendar_date",
    "assert_instant_equals",
    "assert_money_cents",
    "assert_created_record",
    "assert_mutable_record",
    "assert_append_only_record",
    "assert_version_advanced_by",
    "assert_program_year",
    "assert_expense_category",
    "assert_student",
    "assert_application",
    "assert_eligibility_determination",
    "assert_account",
    "assert_disbursement",
    "assert_provider",
    "assert_fraud_screening",
    "assert_purchase_request",
    "assert_misuse_case",
    "assert_clawback_entry",
    "assert_renewal_review",
    "assert_appeal",
    "assert_ledger_identity",
]
