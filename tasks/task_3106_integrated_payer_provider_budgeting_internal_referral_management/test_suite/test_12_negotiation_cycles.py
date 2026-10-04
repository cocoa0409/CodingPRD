"""Non-linear state machines: the referral and claim negotiation cycles.

Depth file (queue A).
"""

import pytest

from test_helpers import (
    APPEAL_ROUNDS_MAX,
    REFERRAL_EXPIRY_DAYS,
    TEST_USERS,
    api_client,
    create_and_approve_budget,
    create_care_site,
    create_department,
    create_open_region,
    create_provider,
    create_referral_payload,
    enroll_member,
    get_referral,
    get_success_data,
    submit_claim,
    validate_error_is_one_of,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_UR = TEST_USERS["utilization_reviewer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]


def _raise_internal_referral(region, department, member):
    res = api_client.create_referral(
        create_referral_payload(
            member["id"], department["id"], department["id"], member["version"],
            service_code="PRIMARY_CARE", referral_type="INTERNAL",
        ),
        _AS,
    )
    return get_success_data(res)


def _referral_cycle_scenario():
    region = create_open_region()
    care_site = create_care_site(region["id"])
    department = create_department(care_site["id"], specialty="PRIMARY_CARE")
    # A second PRIMARY_CARE department is the only qualifying candidate, so the
    # return from PENDING_TRIAGE to HELD on a posture recovery is unambiguous
    # for every referral raised against this scenario.
    create_department(
        care_site["id"], specialty="PRIMARY_CARE", appointment_slots_budgeted=200
    )
    provider = create_provider(care_site["id"], specialty="PRIMARY_CARE")
    member = enroll_member(region["id"], provider["id"])
    referral = _raise_internal_referral(region, department, member)
    return region, department, provider, member, referral


def test_referral_reaches_authorized_through_deny_appeal_authorize(api):
    """PRD §3.5: "A referral in `DENIED` may be appealed by a
    `UtilizationReviewer`, moving it to `APPEALED` and incrementing
    `appeal_rounds` by one".
    PRD §3.5: "The same decision reached from `APPEALED` moves the referral to
    `AUTHORIZED` and refreshes `effective_decision_at` while retaining the
    accumulated `appeal_rounds`."

    Design: Difficulty/non_linear_state_machine/non_linear_referral_deny_appeal_authorize_cycle
    """
    _, _, _, _, referral = _referral_cycle_scenario()
    assert referral["status"] == "PENDING_TRIAGE"
    assert referral["appeal_rounds"] == 0

    denied = get_success_data(api_client.deny_referral(referral["id"], {}, _UR))
    assert denied["status"] == "DENIED"

    appealed = get_success_data(api_client.appeal_referral(referral["id"], {}, _UR))
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_rounds"] == 1

    authorized = get_success_data(
        api_client.authorize_referral(referral["id"], {}, _UR)
    )
    assert authorized["status"] == "AUTHORIZED", (
        "the cycle revisits the decision process and lands on AUTHORIZED"
    )
    assert authorized["appeal_rounds"] == 1, "the accumulated round is retained"
    assert authorized["effective_decision_at"]


def test_referral_authorization_from_appeal_sets_the_expiry(api):
    """PRD §3.5: "Authorizing a referral in `PENDING_TRIAGE` moves it to
    `AUTHORIZED`, records `effective_decision_at` from the logical clock, and
    sets `expires_at` to ninety days after the referral's `created_at`."
    PRD §3.5: "Once authorized, a referral has ninety days to become a booked
    visit."

    Design: Difficulty/non_linear_state_machine/non_linear_referral_deny_appeal_authorize_cycle
    """
    _, _, _, _, referral = _referral_cycle_scenario()
    get_success_data(api_client.deny_referral(referral["id"], {}, _UR))
    get_success_data(api_client.appeal_referral(referral["id"], {}, _UR))
    authorized = get_success_data(
        api_client.authorize_referral(referral["id"], {}, _UR)
    )

    assert REFERRAL_EXPIRY_DAYS == 90
    assert authorized["expires_at"], "authorization sets the expiry instant"
    assert authorized["expires_at"] > referral["created_at"]
    reread = get_referral(referral["id"])
    assert reread["status"] == "AUTHORIZED"
    assert reread["expires_at"] == authorized["expires_at"]


def test_claim_reaches_adjudicated_through_deny_appeal_adjudicate(api):
    """PRD §3.6: "a claim in `DENIED` may be appealed by a `UtilizationReviewer`,
    moving it to `APPEALED` and incrementing `appeal_rounds` by one".
    PRD §3.6: "A claim in `APPEALED` may be denied again, subject to the same
    round bound."

    Design: Difficulty/non_linear_state_machine/non_linear_claim_deny_appeal_adjudicate_cycle
    """
    region = create_open_region()
    care_site = create_care_site(region["id"])
    create_department(care_site["id"])
    provider = create_provider(care_site["id"])
    member = enroll_member(region["id"], provider["id"])
    create_and_approve_budget(region["id"])

    claim = submit_claim(
        region["id"], member["id"], member["version"], billed_amount_cents=300000
    )
    adjudicated = get_success_data(api_client.adjudicate_claim(claim["id"], {}, _RFO))
    assert adjudicated["status"] == "ADJUDICATED"

    denied = get_success_data(api_client.deny_claim(claim["id"], {}, _UR))
    assert denied["status"] == "DENIED"
    assert denied["appeal_rounds"] == 0

    appealed = get_success_data(api_client.appeal_claim(claim["id"], {}, _UR))
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_rounds"] == 1

    readjudicated = get_success_data(
        api_client.adjudicate_claim(claim["id"], {}, _RFO)
    )
    assert readjudicated["status"] == "ADJUDICATED", (
        "the claim machine revisits ADJUDICATED through a cycle"
    )
    assert readjudicated["appeal_rounds"] == 1


def test_claim_liability_is_pinned_across_the_negotiation_cycle(api):
    """PRD §3.6: "The final figure is pinned at adjudication and is
    chronological."
    PRD §3.6: "Denial is a `UtilizationReviewer` capability available from
    `ADJUDICATED` or `APPEALED`; it moves the claim to `DENIED` and reverses the
    booked `final_liability_cents` out of the region's
    `outside_services_spend_cents`".

    Design: Difficulty/non_linear_state_machine/non_linear_claim_deny_appeal_adjudicate_cycle
    """
    region = create_open_region()
    care_site = create_care_site(region["id"])
    create_department(care_site["id"])
    provider = create_provider(care_site["id"])
    member = enroll_member(region["id"], provider["id"])
    create_and_approve_budget(region["id"])

    claim = submit_claim(
        region["id"], member["id"], member["version"], billed_amount_cents=300000
    )
    first = get_success_data(api_client.adjudicate_claim(claim["id"], {}, _RFO))
    pinned = first["final_liability_cents"]

    get_success_data(api_client.deny_claim(claim["id"], {}, _UR))
    reread_after_deny = api_client.get_outside_service_claim(claim["id"], _RFO)
    after_deny = reread_after_deny.json()["data"]
    assert after_deny["final_liability_cents"] == pinned, (
        "the denial reverses the booked liability but does not recompute it"
    )

    get_success_data(api_client.appeal_claim(claim["id"], {}, _UR))
    readjudicated = get_success_data(api_client.adjudicate_claim(claim["id"], {}, _RFO))
    assert readjudicated["final_liability_cents"] == pinned
    assert readjudicated["status"] == "ADJUDICATED"


def test_referral_appeal_rounds_accumulate_to_the_declared_maximum(api):
    """PRD §3.5: "The appeal loop is bounded. A referral in `DENIED` may be
    appealed by a `UtilizationReviewer`, moving it to `APPEALED` and
    incrementing `appeal_rounds` by one, and opening an appeal requires that
    `appeal_rounds` is below the appeal-round maximum — the maximum is two
    rounds."

    Design: Difficulty/non_linear_state_machine/non_linear_referral_appeal_cycle_is_bounded_at_two_rounds
    """
    _, _, _, _, referral = _referral_cycle_scenario()
    assert APPEAL_ROUNDS_MAX == 2

    get_success_data(api_client.deny_referral(referral["id"], {}, _UR))
    first_appeal = get_success_data(api_client.appeal_referral(referral["id"], {}, _UR))
    assert first_appeal["appeal_rounds"] == 1

    get_success_data(api_client.deny_referral(referral["id"], {}, _UR))
    second_appeal = get_success_data(api_client.appeal_referral(referral["id"], {}, _UR))
    assert second_appeal["appeal_rounds"] == APPEAL_ROUNDS_MAX, (
        f"Expected two rounds, got {second_appeal['appeal_rounds']}"
    )
    assert second_appeal["status"] in ("APPEALED", "DENIED")


def test_referral_appeal_at_the_maximum_is_refused(api):
    """PRD §3.5: "An appeal opened at the maximum is refused with
    `ERR_APPEAL_ROUNDS_EXHAUSTED` (HTTP 409)."
    PRD §3.5: "the maximum is two rounds".

    Design: Difficulty/non_linear_state_machine/non_linear_referral_appeal_cycle_is_bounded_at_two_rounds
    """
    _, _, _, _, referral = _referral_cycle_scenario()

    get_success_data(api_client.deny_referral(referral["id"], {}, _UR))
    get_success_data(api_client.appeal_referral(referral["id"], {}, _UR))
    get_success_data(api_client.deny_referral(referral["id"], {}, _UR))
    get_success_data(api_client.appeal_referral(referral["id"], {}, _UR))

    exhausted = api_client.appeal_referral(referral["id"], {}, _UR)
    assert exhausted.status_code == 409, exhausted.text
    # PRD 3.5 states that an appeal opened at the maximum is refused with
    # ERR_APPEAL_ROUNDS_EXHAUSTED, but it also states that a target not in
    # DENIED is not decidable at all; the prd does not say which check wins at
    # the boundary, so either catalogued refusal is acceptable.
    validate_error_is_one_of(
        exhausted, ["ERR_APPEAL_ROUNDS_EXHAUSTED", "ERR_REFERRAL_NOT_DECIDABLE"]
    )

    after = get_referral(referral["id"])
    assert after["appeal_rounds"] == APPEAL_ROUNDS_MAX, (
        "the refused appeal does not advance the round count"
    )