"""
Compensating writes measured against the two arithmetic identities the system
re-checks after every disturbance: the unit pool on a service line, and the
family ledger on a cost-share determination.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    FISCAL_2_HEADERS,
    FISCAL_OFFICER_USER_ID,
    assert_authorization_units,
    assert_cents,
    assert_ledger,
    assert_unit_pool,
    build_accrued_visit_case,
    build_active_services,
    create_authorization,
    create_provider,
    document_visit,
    factories,
    read_authorization,
    read_cost_share,
    read_service_line,
    read_visit,
    schedule_visit,
    set_clock,
    validate_error,
    validate_success,
)

PROVIDER = {
    "agency_name": "Riverbend Pediatric Therapies",
    "qualified_service_types": ["SPEECH_THERAPY"],
    "credential_expiry_date": "2027-06-30",
}
REVOCATION_CLOCK = "2026-03-24T12:00:00Z"
REVOCATION_DATE = "2026-03-24"


def _build_partly_delivered_authorization(api):
    """
    A 24-unit authorization that has delivered 2 units, on a line whose pool has
    all 24 committed and 72 planned units still free.
    """
    case = build_active_services(api)
    case.provider_id = create_provider(api, **PROVIDER)
    case.provider_ids.append(case.provider_id)
    case.authorization_id = create_authorization(
        api,
        case.line_id,
        case.provider_id,
        start_date="2026-03-21",
        end_date="2026-04-30",
        authorized_units=24,
    )
    case.authorization_ids.append(case.authorization_id)
    case.visit_id = schedule_visit(
        api,
        case.authorization_id,
        "2026-03-23T09:00:00Z",
        "2026-03-23T09:30:00Z",
        setting_code="HOME",
    )
    case.visit_ids.append(case.visit_id)
    set_clock(api, REVOCATION_CLOCK)
    case.clock = REVOCATION_CLOCK
    document_visit(
        api,
        case.visit_id,
        case.provider_id,
        visit_status="DELIVERED",
        actual_units=2,
    )
    return case


def _revoke(api, authorization_id):
    response = api.revoke_authorization(
        authorization_id,
        factories.revoke_authorization_payload(
            revocation_reason_code="ADMIN_CORRECTION"
        ),
        ADMIN_HEADERS,
    )
    return validate_success(response, 200)


class TestUnitPoolSurvivesRevocation:
    """Revocation hands back the unspent remainder and nothing more."""

    def test_revocation_releases_only_what_was_never_delivered(self, api):
        """
        Revoking an authorization that has spent 2 of 24 units releases exactly
        the 22 it never spent.

        PRD 3.6: "Revoking sets `units_released` to the authorization's
        `units_remaining`, records `revoked_date` as the logical clock date and
        stores the `revocation_reason_code`; every session still in `SCHEDULED` on
        that authorization transitions to `CANCELLED_PROGRAM` with
        `billing_status` `CANCELLED_NO_CHARGE`; the line's `units_committed` and
        `units_pool_remaining` are recomputed, restoring the pool; and the
        provider's `active_authorization_count` is recomputed."

        Design: Difficulty/compensating_invariant/service_unit_pool_conserved_across_authorize_revoke
        """
        case = _build_partly_delivered_authorization(api)

        revoked = _revoke(api, case.authorization_id)
        assert revoked["status"] == "REVOKED"
        assert revoked["revocation_reason_code"] == "ADMIN_CORRECTION"
        assert revoked["revoked_date"] == REVOCATION_DATE
        assert_authorization_units(
            revoked, units_consumed=2, units_released=22, units_remaining=0
        )

        # The compensation does not disturb the delivery it compensates for.
        visit = read_visit(api, case.visit_id)
        assert visit["visit_status"] == "DELIVERED"
        assert visit["actual_units"] == 2

    def test_pool_identity_holds_across_the_compensation(self, api):
        """
        After the release the line keeps the 2 units it spent as committed and
        the two halves of the pool still sum to the planned total.

        PRD 2.10: "A line's `units_committed` plus its `units_pool_remaining`
        always equals its `planned_units_total`, and `units_pool_remaining` is
        always between 0 and `planned_units_total` inclusive."

        Design: Difficulty/compensating_invariant/service_unit_pool_conserved_across_authorize_revoke
        """
        case = _build_partly_delivered_authorization(api)

        before = read_service_line(api, case.line_id)
        assert_unit_pool(
            before, units_committed=24, units_pool_remaining=72, planned_units_total=96
        )

        _revoke(api, case.authorization_id)

        after = read_service_line(api, case.line_id)
        assert_unit_pool(
            after, units_committed=2, units_pool_remaining=94, planned_units_total=96
        )
        assert after["units_delivered"] == 2
        assert after["status"] == "IN_DELIVERY"
        assert read_authorization(api, case.authorization_id)["status"] == "REVOKED"


# ─── Money on the family ledger ───────────────────────────────────────

SHARE_PER_SESSION_CENTS = 650
WAIVED_CENTS = 200
LEDGER_CLOCK = "2026-03-24T12:00:00Z"
SESSION_WINDOWS = (
    ("2026-03-23T09:00:00Z", "2026-03-23T09:30:00Z"),
    ("2026-03-24T09:00:00Z", "2026-03-24T09:30:00Z"),
)


def _build_waived_two_accrual_case(api):
    """
    Two accrued sessions worth 650 cents each against a provisional TIER_1
    determination, with 200 cents waived by a second fiscal officer.
    """
    case = build_accrued_visit_case(
        api,
        cost_share={
            "household_size": 4,
            "declared_annual_gross_income_cents": 12_000_000,
            "insurance_use_consent": False,
        },
        provider=PROVIDER,
        authorization={
            "start_date": "2026-03-21",
            "end_date": "2026-04-30",
            "authorized_units": 24,
        },
        visit_windows=SESSION_WINDOWS,
        document_clock=LEDGER_CLOCK,
        actual_units=2,
    )
    waived = validate_success(
        api.waive_cost_share(
            case.cost_share_id,
            factories.waive_payload(
                waive_amount_cents=WAIVED_CENTS, waiver_reason_code="HARDSHIP"
            ),
            FISCAL_2_HEADERS,
        ),
        200,
    )
    assert_ledger(waived, 1_300, 1_100, WAIVED_CENTS)
    return case


def _void(api, visit_id):
    return api.void_visit(
        visit_id, factories.void_visit_payload(), ADMIN_HEADERS
    )


class TestFamilyLedgerSurvivesReversal:
    """One reversal is absorbed; the second would break the identity."""

    def test_void_reduces_assessed_and_balance_by_the_same_amount(self, api):
        """
        Reversing one accrued session takes its share off both the assessed total
        and the balance, leaving the waived cents alone and the identity intact.

        PRD 2.10: "A waiver moves cents from balance to waived and leaves the
        assessed total untouched; voiding a delivered visit removes that visit's
        contribution from the balance and reduces the assessed total by exactly
        the same amount, so the identity holds on both sides of the compensation."

        Design: Difficulty/compensating_invariant/family_ledger_conserved_across_accrual_and_void
        """
        case = _build_waived_two_accrual_case(api)

        voided = validate_success(_void(api, case.visit_ids[0]), 200)
        assert voided["visit_status"] == "VOIDED"
        assert voided["billing_status"] == "REVERSED"

        determination = read_cost_share(api, case.cost_share_id)
        assert_ledger(
            determination,
            SHARE_PER_SESSION_CENTS,
            SHARE_PER_SESSION_CENTS - WAIVED_CENTS,
            WAIVED_CENTS,
        )
        assert_cents(
            determination["month_accrued_cents"],
            SHARE_PER_SESSION_CENTS,
            "month_accrued_cents",
        )
        assert determination["waiver_reason_code"] == "HARDSHIP"
        assert determination["determined_by_user_id"] == FISCAL_OFFICER_USER_ID

    def test_second_void_is_refused_and_changes_nothing(self, api):
        """
        Reversing the remaining session would drive the balance below zero
        against the cents already waived, so it is refused outright and every
        figure stays where the first reversal left it.

        PRD 3.7: "A void that would drive the selected cost-share row's
        `family_balance_cents` below 0 is refused with
        `ERR_LEDGER_WOULD_UNBALANCE`."

        Design: Difficulty/compensating_invariant/family_ledger_conserved_across_accrual_and_void
        """
        case = _build_waived_two_accrual_case(api)
        validate_success(_void(api, case.visit_ids[0]), 200)

        refused = _void(api, case.visit_ids[1])
        validate_error(refused, ApiErrorId.LEDGER_WOULD_UNBALANCE.value, 409)

        survivor = read_visit(api, case.visit_ids[1])
        assert survivor["visit_status"] == "DELIVERED"
        assert survivor["billing_status"] == "ACCRUED"
        assert_cents(
            survivor["family_share_cents"],
            SHARE_PER_SESSION_CENTS,
            "family_share_cents",
        )

        determination = read_cost_share(api, case.cost_share_id)
        assert_ledger(
            determination,
            SHARE_PER_SESSION_CENTS,
            SHARE_PER_SESSION_CENTS - WAIVED_CENTS,
            WAIVED_CENTS,
        )
        assert_cents(
            determination["month_accrued_cents"],
            SHARE_PER_SESSION_CENTS,
            "month_accrued_cents",
        )

        assert_authorization_units(
            read_authorization(api, case.authorization_id),
            units_consumed=2,
            units_remaining=22,
        )
        assert read_service_line(api, case.line_id)["units_delivered"] == 2
