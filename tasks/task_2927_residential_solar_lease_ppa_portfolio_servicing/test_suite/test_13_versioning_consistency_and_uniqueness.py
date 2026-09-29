"""Version arithmetic, immediate visibility of cascades, and the uniqueness rules.

Three questions live together here because they are all about what a single
request leaves behind: how far the parent's version moved, whether the caller
can see the consequences without asking twice, and whether a rejected request
left anything at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.fixtures import (
    activate,
    book_ppa,
    make_buyer,
    make_homeowner,
    make_tariff,
    read_agreement,
    reconcile,
    record_period,
    set_clock,
)

A1_TERMS = {
    "contract_start_date": "2025-01-01",
    "escalator_pct": 0.029,
    "base_ppa_rate_per_kwh_millicents": 14750,
    "guaranteed_annual_kwh": 9600,
    "guarantee_band_pct": 0.05,
}

# June 2026 has fully elapsed at this instant and its due date, 2026-07-21, has
# not passed, so the month settles without a late fee.
JUNE_CLOCK = "2026-07-05T00:00:00Z"
OUTAGE_DETECTED_AT = "2026-07-04T09:00:00Z"

# The settled June figures, all derived from the A1 terms in contract year 2:
# the escalated rate is 14750 * 1.029 rounded to 15178 millicents, expectation
# is 9600 * 0.1120 = 1075 kWh, the floor is 1021 kWh, so 900 metered kWh is
# 121 kWh short and earns 121 * 15178 / 1000 = 1837 cents.
JUNE_METERED_KWH = 900
JUNE_RATE_MILLICENTS = 15178
JUNE_EXPECTED_KWH = 1075
JUNE_FLOOR_KWH = 1021
JUNE_SHORTFALL_KWH = 121
JUNE_CREDIT_CENTS = 1837
JUNE_GROSS_DUE_CENTS = 13660


def _active_ppa_with_june_recorded(api):
    """An ACTIVE PPA on the A1 terms whose June 2026 is RECORDED, not settled."""
    set_clock(api, JUNE_CLOCK)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    draft = book_ppa(api, owner["id"], schedule["id"], **A1_TERMS)
    activated = activate(api, draft["id"])
    month = record_period(api, draft["id"], 2026, 6, JUNE_METERED_KWH)
    return owner, draft, activated, month


def _assert_june_is_settled(month):
    """Every settled figure of the June month, whichever response carried it."""
    assert month["status"] == C.PERIOD_CREDIT_ISSUED
    assert month["escalated_rate_millicents"] == JUNE_RATE_MILLICENTS
    assert month["gross_expected_kwh"] == JUNE_EXPECTED_KWH
    assert month["adjusted_expected_kwh"] == JUNE_EXPECTED_KWH
    assert month["guarantee_floor_kwh"] == JUNE_FLOOR_KWH
    assert month["shortfall_kwh"] == JUNE_SHORTFALL_KWH
    assert month["credit_cents"] == JUNE_CREDIT_CENTS
    assert month["gross_due_cents"] == JUNE_GROSS_DUE_CENTS
    assert month["credit_applied_cents"] == 0
    assert month["net_due_cents"] == JUNE_GROSS_DUE_CENTS
    assert month["late_fee_cents"] == 0
    assert month["total_invoiced_cents"] == JUNE_GROSS_DUE_CENTS


def test_the_agreement_version_moves_once_per_write_and_never_on_a_read(api):
    """Activation, a credit-issuing reconcile and an alarm each add exactly one.

    §2.4: "`version`, an integer that begins at 1 and increases by exactly one
    on every mutation of that resource." §3.3 enumerates the whole effect of
    recording a month, and the agreement is not part of it: "Recording alone
    derives the month's `contract_year`, its `due_date`, its
    `gross_expected_kwh`, its `excused_days` and its `adjusted_expected_kwh`."
    §3.3 on the credit-issuing settlement, which moves three ledger counters at
    once: "Even though several counters move, the agreement's `version` advances
    exactly once for the whole transition." §3.5 on the alarm: "the agreement's
    `open_outage_count` incremented, its `monitoring_status` re-derived, and its
    `version` advanced."

    Design: Corner/cross_cutting_complexity_layers/agreement_version_increments_once_per_write_and_holds_across_reads
    """
    _, draft, activated, month = _active_ppa_with_june_recorded(api)

    v0 = draft["version"]
    assert v0 == 1
    v1 = activated["version"]
    assert v1 == v0 + 1, "activation is a write on the agreement"

    v2 = read_agreement(api, draft["id"])["version"]
    assert v2 == v1, "recording a month does not touch the agreement, nor does a read"

    settled = reconcile(api, month["id"], issue_credit=True)
    _assert_june_is_settled(settled)

    after_reconcile = read_agreement(api, draft["id"])
    v3 = after_reconcile["version"]
    assert v3 == v2 + 1, "the whole CREDIT_ISSUED transition is one version step"
    assert after_reconcile["credit_earned_cents"] == JUNE_CREDIT_CENTS
    assert after_reconcile["credit_applied_cents"] == 0
    assert after_reconcile["credit_balance_cents"] == JUNE_CREDIT_CENTS

    validate_success(
        api.create_outage_event(
            F.outage_event_payload(
                draft["id"],
                OUTAGE_DETECTED_AT,
                inverter_serial="INV-7781-A",
                outage_type=C.OUTAGE_TYPE_COMMS_LOSS,
            ),
            U.ops_headers(),
        ),
        201,
    )

    v4 = read_agreement(api, draft["id"], U.admin_headers())["version"]
    assert v4 == v3 + 1, "recording the alarm bumps the agreement once more"

    for _ in range(3):
        assert read_agreement(api, draft["id"])["version"] == v4, "reads never bump"


def test_every_cascade_is_readable_in_the_response_that_caused_it(api):
    """One reconcile, one alarm: no second call, no retry, no convergence step.

    §3.3: "When `issue_credit` is true **and** `credit_cents` resolves to a value
    strictly greater than 0, the month instead moves `RECORDED → CREDIT_ISSUED`:
    every effect of the plain reconciliation applies, and in addition the
    agreement's `credit_earned_cents` and `credit_balance_cents` are each
    increased by the month's `credit_cents`." §2.9: "`credit_balance_cents`
    equals `credit_earned_cents` minus `credit_applied_cents`, and it is never
    negative." §3.5: "A new alarm lands in `status` `OPEN` with `resolved_at`
    null and `excused` false, its `severity` graded immediately, and the
    agreement's `open_outage_count` incremented, its `monitoring_status`
    re-derived, and its `version` advanced." §3.5 on the re-derivation: "When
    `open_outage_count` is 0 the status is `MONITORING_OK`; when at least one
    event in the open set is `DISPATCHED` the status is
    `TRUCK_ROLL_DISPATCHED`; otherwise it is `OUTAGE_OPEN`."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_same_response_that_caused_it
    """
    owner, draft, _, month = _active_ppa_with_june_recorded(api)

    settled = validate_success(
        api.reconcile_period(month["id"], {"issue_credit": True}, U.agent_headers()),
        200,
    )
    _assert_june_is_settled(settled)

    ledger = read_agreement(api, draft["id"])
    assert ledger["credit_earned_cents"] == JUNE_CREDIT_CENTS
    assert ledger["credit_applied_cents"] == 0
    assert ledger["credit_balance_cents"] == JUNE_CREDIT_CENTS
    assert (
        ledger["credit_balance_cents"]
        == ledger["credit_earned_cents"] - ledger["credit_applied_cents"]
    )
    assert ledger["monitoring_status"] == C.MONITORING_OK
    assert ledger["open_outage_count"] == 0

    alarm = validate_success(
        api.create_outage_event(
            F.outage_event_payload(
                draft["id"],
                OUTAGE_DETECTED_AT,
                inverter_serial="INV-7781-A",
                outage_type=C.OUTAGE_TYPE_COMMS_LOSS,
            ),
            U.ops_headers(),
        ),
        201,
    )
    assert alarm["status"] == C.OUTAGE_OPEN
    assert alarm["resolved_at"] is None
    assert alarm["excused"] is False

    projected = read_agreement(api, draft["id"])
    assert projected["open_outage_count"] == 1
    assert projected["monitoring_status"] == C.MONITORING_OUTAGE_OPEN
    assert projected["credit_balance_cents"] == JUNE_CREDIT_CENTS

    reread = validate_success(
        api.get_period(month["id"], U.homeowner_headers(owner["id"])), 200
    )
    for field in (
        "status",
        "escalated_rate_millicents",
        "gross_expected_kwh",
        "adjusted_expected_kwh",
        "guarantee_floor_kwh",
        "shortfall_kwh",
        "credit_cents",
        "gross_due_cents",
        "credit_applied_cents",
        "net_due_cents",
        "late_fee_cents",
        "total_invoiced_cents",
    ):
        assert reread[field] == settled[field], f"{field} differs from the reconcile"


def test_a_rejected_transfer_leaves_the_agreement_exactly_where_it_was(api):
    """Two coherence rejections, then one success: exactly one transition.

    §3.8: "`ASSUMPTION` hands the contract to a qualified buyer and requires
    `buyer_homeowner_id`, the purchasing homeowner, which must not be the
    agreement's current `homeowner_id`". §3.8: "Any violation of that field
    matrix — a missing required field, a forbidden field supplied, or a buyer who
    is already the current homeowner — is rejected with
    `ERR_BUYER_FIELD_MISMATCH`." §3.8 on what a successful opening does: "An
    `ASSUMPTION` lands in `status` `CREDIT_REVIEW` with `payoff_method` set to
    `NONE` and `payoff_quote_cents` at 0, because nothing is being bought out."
    §3.8: "`seller_homeowner_id` is copied from the agreement's current
    `homeowner_id`, `successor_agreement_id` starts null" and "the agreement
    moves `ACTIVE → TRANSFER_PENDING` with its `version` advancing." §2.4:
    "`version`, an integer that begins at 1 and increases by exactly one on
    every mutation of that resource."

    Design: Corner/consistency_model/a_rejected_write_leaves_no_partial_state_behind
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    seller = make_homeowner(api)
    buyer = make_buyer(api)
    schedule = make_tariff(api)
    draft = book_ppa(api, seller["id"], schedule["id"], **A1_TERMS)
    activated = activate(api, draft["id"])
    version_before = activated["version"]

    validate_error(
        api.create_transfer_case(
            {
                "agreement_id": draft["id"],
                "transfer_type": C.TYPE_ASSUMPTION,
                "closing_date": "2026-09-15",
            },
            U.agent_headers(),
        ),
        E.ERR_BUYER_FIELD_MISMATCH,
    )
    validate_error(
        api.create_transfer_case(
            F.assumption_payload(draft["id"], "2026-09-15", seller["id"]),
            U.agent_headers(),
        ),
        E.ERR_BUYER_FIELD_MISMATCH,
    )

    untouched = read_agreement(api, draft["id"])
    assert untouched["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert untouched["version"] == version_before
    _, meta = validate_paginated(
        api.list_transfer_cases(U.agent_headers(), {"agreement_id": draft["id"]})
    )
    assert meta["total_count"] == 0, "a rejected creation left no partial case behind"

    case = validate_success(
        api.create_transfer_case(
            F.assumption_payload(draft["id"], "2026-09-15", buyer["id"]),
            U.agent_headers(),
        ),
        201,
    )
    assert case["status"] == C.TRANSFER_CREDIT_REVIEW
    assert case["payoff_method"] == C.PAYOFF_NONE
    assert case["payoff_quote_cents"] == 0
    assert case["seller_homeowner_id"] == seller["id"]
    assert case["buyer_homeowner_id"] == buyer["id"]
    assert case["successor_agreement_id"] is None

    moved = read_agreement(api, draft["id"])
    assert moved["lifecycle_state"] == C.LIFECYCLE_TRANSFER_PENDING
    assert moved["version"] == version_before + 1, "exactly one transition, not two"


def test_an_email_differing_only_in_letter_case_is_a_duplicate(api):
    """Uniqueness on email is compared without regard to letter case.

    §3.1: "Email uniqueness is enforced across the whole homeowner collection and
    is compared without regard to letter case; a collision is rejected with
    `ERR_DUPLICATE_EMAIL`." §3.1 also names what the address is for: "an `email`
    that must contain an at-sign and that doubles as the servicing-portal login
    handle".

    Design: Corner/validations/duplicate_homeowner_email_differing_only_in_case_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    first = make_homeowner(
        api, full_name="Dana Reyes", email="Dana.Reyes@Example.com"
    )
    assert first["email"] == "Dana.Reyes@Example.com"

    validate_error(
        api.create_homeowner(
            F.homeowner_payload(
                full_name="Dana R Reyes",
                email="dana.reyes@example.com",
                state_code="NV",
                fico_score=700,
                dti_ratio=0.3,
                monthly_income_cents=900000,
            ),
            U.agent_headers(),
        ),
        E.ERR_DUPLICATE_EMAIL,
    )

    rows, meta = validate_paginated(
        api.list_homeowners(U.agent_headers(), {"email": "Dana.Reyes@Example.com"})
    )
    assert meta["total_count"] == 1, "the collision created nothing"
    assert [row["id"] for row in rows] == [first["id"]]

    third = validate_success(
        api.create_homeowner(
            F.homeowner_payload(
                full_name="Dana R Reyes", email="dana.reyes+2@example.com"
            ),
            U.agent_headers(),
        ),
        201,
    )
    assert third["id"] != first["id"], "only the case-insensitive collision is refused"


def test_the_tariff_book_is_unique_on_the_pair_not_on_the_code_alone(api):
    """The same tariff_code may be republished under a different utility.

    §3.1: "The pair of `utility_code` and `tariff_code` must be unique across the
    book; a duplicate pair is rejected with `ERR_DUPLICATE_TARIFF_CODE`." §3.1 on
    the shape of a schedule: "A published schedule carries a `utility_code` of
    between 2 and 12 uppercase alphanumeric characters, the utility's own
    `tariff_code` of between 1 and 40 characters".

    Design: Corner/validations/duplicate_utility_and_tariff_code_pair_is_rejected_but_the_code_alone_is_not
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    published = make_tariff(api, utility_code="PGE", tariff_code="NEM2-ETOUC")
    assert published["utility_code"] == "PGE"
    assert published["tariff_code"] == "NEM2-ETOUC"

    validate_error(
        api.create_tariff(
            F.tariff_payload(
                utility_code="PGE",
                tariff_code="NEM2-ETOUC",
                retail_rate_per_kwh_millicents=33900,
                export_credit_rate_per_kwh_millicents=27000,
                monthly_fixed_charge_cents=1600,
                effective_from_date="2021-01-01",
            ),
            U.admin_headers(),
        ),
        E.ERR_DUPLICATE_TARIFF_CODE,
    )

    elsewhere = validate_success(
        api.create_tariff(
            F.tariff_payload(utility_code="SCE", tariff_code="NEM2-ETOUC"),
            U.admin_headers(),
        ),
        201,
    )
    assert elsewhere["utility_code"] == "SCE"
    assert elsewhere["tariff_code"] == "NEM2-ETOUC"
    assert elsewhere["id"] != published["id"]

    _, meta = validate_paginated(
        api.list_tariffs(U.admin_headers(), {"utility_code": "PGE"})
    )
    assert meta["total_count"] == 1, "the duplicate pair published nothing"


def test_product_terms_that_contradict_the_product_type_are_rejected_both_ways(api):
    """A lease carrying a PPA rate, and a PPA carrying none, both fail the pairing.

    §3.1: "Exactly one of the two base-rate fields is supplied:
    `base_monthly_lease_cents` carries the contract-year-1 monthly rent in cents
    and is required for a `LEASE` while it must be absent for a `PPA`;
    `base_ppa_rate_per_kwh_millicents` carries the contract-year-1 rate in
    millicents per kilowatt-hour and is required for a `PPA` while it must be
    absent for a `LEASE`." §3.1: "A payload that breaks that pairing in either
    direction — a lease without its rent, a lease carrying a PPA rate, a PPA
    without its rate, a PPA carrying a lease rent — is rejected with
    `ERR_PRODUCT_TERMS_MISMATCH`, and the same check is re-applied at
    activation." §3.2 on what the surviving lease then prices: "Under a `LEASE`,
    `escalated_rate_millicents` stays 0, the escalated rent for a contract year
    is `base_monthly_lease_cents` multiplied by the factor and rounded to a whole
    cent, recorded on a metered month as `escalated_monthly_rent_cents`".

    Design: Corner/validations/product_terms_that_contradict_product_type_are_rejected_both_ways
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)

    lease_with_a_ppa_rate = F.lease_agreement_payload(
        owner["id"],
        schedule["id"],
        site_address="77 Cedar Court, Fremont CA",
        base_monthly_lease_cents=12900,
        base_ppa_rate_per_kwh_millicents=14750,
    )
    validate_error(
        api.create_agreement(lease_with_a_ppa_rate, U.agent_headers()),
        E.ERR_PRODUCT_TERMS_MISMATCH,
    )

    ppa_without_its_rate = F.ppa_agreement_payload(owner["id"], schedule["id"])
    ppa_without_its_rate.pop("base_ppa_rate_per_kwh_millicents")
    response = api.create_agreement(ppa_without_its_rate, U.agent_headers())
    validate_error(response, E.ERR_PRODUCT_TERMS_MISMATCH)
    assert response.status_code != 400, "both base-rate fields are optional in the schema"

    clean = F.lease_agreement_payload(
        owner["id"],
        schedule["id"],
        site_address="77 Cedar Court, Fremont CA",
        base_monthly_lease_cents=12900,
    )
    booked = validate_success(api.create_agreement(clean, U.agent_headers()), 201)
    assert booked["lifecycle_state"] == C.LIFECYCLE_DRAFT
    assert booked["product_type"] == C.PRODUCT_LEASE
    assert booked["base_monthly_lease_cents"] == 12900

    activate(api, booked["id"])
    month = record_period(api, booked["id"], 2025, 3, 700)
    assert month["contract_year"] == 1
    settled = reconcile(api, month["id"], issue_credit=False)
    assert settled["escalated_monthly_rent_cents"] == 12900
    assert settled["escalated_rate_millicents"] == 0
    assert settled["gross_due_cents"] == 12900
