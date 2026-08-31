"""The placement search: broadcast rounds, the two fairness rules, and the
negotiation cycle that returns a referral to BROADCAST for another round."""
from test_helpers import (
    CASE_MANAGER,
    PLATFORM_ADMIN,
    ApiErrorId,
    assert_referral,
    get_success_data,
    make_liaison_headers,
    read_provider,
    read_referral,
    referral_payload,
    seed_network_contract,
    seed_provider,
    setup_broadcast_referral,
    setup_choice_pending_referral,
    setup_screened_episode,
    validate_error,
    validate_success,
)

LAKESIDE = {
    "name": "Lakeside Choice", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": False, "auth_expiry_days": 30,
}


def _snf_referral_ready_for_round_two(api, mrn):
    """A referral whose round-1 Cedar offer has been withdrawn, so every round-1
    offer is terminal and a rebroadcast is admissible."""
    env = setup_choice_pending_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": mrn, "full_name": "Fay Oyelaran", "date_of_birth": "1949-09-09",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        referral={"requested_level_of_care": "SNF", "projected_stay_days": 14,
                  "needed_by": "2026-08-20T00:00:00Z"},
        offer={"daily_rate_cents": 30000},
    )
    validate_success(
        api.withdraw_offer(env["offer"]["id"], make_liaison_headers(env["provider_a"]["id"]))
    )
    return env


def test_rebroadcast_opens_round_two_after_every_round_one_offer_went_terminal(api):
    """PRD §3.4: "A rebroadcast is only permitted from `CHOICE_PENDING`, and only once
    every bed offer carrying the current `round_index` has reached a terminal,
    non-accepted status — `DECLINED_BY_PATIENT`, `WITHDRAWN`, or `EXPIRED`."
    PRD §3.4: "A rebroadcast re-runs both fairness rules against the new slate, increments
    `round_index` again, replaces `broadcast_provider_ids`, credits each newly listed
    provider's `offers_received_count`, and advances `version`."
    PRD §3.4: "Broadcasting again later is how a fresh round opens, and that is the
    negotiation cycle: `BROADCAST → CHOICE_PENDING → BROADCAST` repeats one round per
    iteration."

    Design: Difficulty/non_linear_state_machine/referral_negotiation_cycle_returns_to_broadcast_for_round_two
    """
    env = _snf_referral_ready_for_round_two(api, "MRN-3101")
    slate = [p["id"] for p in env["providers"]]

    data = validate_success(
        api.broadcast_referral(env["referral"]["id"], {"provider_ids": slate}, CASE_MANAGER)
    )

    assert_referral(data)
    assert data["round_index"] == 2, f"the second round is index 2, got {data['round_index']}"
    assert data["status"] == "BROADCAST"
    assert data["broadcast_provider_ids"] == slate, "the slate is stored in the order given"
    assert read_provider(env["provider_a"]["id"])["offers_received_count"] == 2, (
        "each listed provider is credited with a second invitation"
    )
    assert read_provider(env["provider_a"]["id"])["held_bed_units"] == 0, (
        "the withdrawn round-1 hold was released"
    )


def test_round_two_offer_returns_the_referral_to_choice_pending(api):
    """PRD §3.4: "A created offer starts with `status` of `OFFERED`, copies the referral's
    current `round_index` into its own `round_index`, increments the provider's
    `held_bed_units` and `offers_submitted_count` by one each, computes its cost projection
    as described in §3.5, and advances the referral's `version` by one. The round's first
    offer also moves the referral `BROADCAST → CHOICE_PENDING`."
    PRD §3.4: "A liaison may withdraw its own outstanding offer, which moves it to
    `WITHDRAWN`, decrements that provider's `held_bed_units`, and makes the hold interval
    immediately reusable; withdrawing an offer that belongs to another provider is
    `ERR_NOT_OWNER`, and withdrawing one that is no longer `OFFERED` is
    `ERR_INVALID_OFFER_STATE`."

    Design: Difficulty/non_linear_state_machine/referral_negotiation_cycle_returns_to_broadcast_for_round_two
    """
    env = _snf_referral_ready_for_round_two(api, "MRN-3102")
    slate = [p["id"] for p in env["providers"]]
    round_two = get_success_data(
        api.broadcast_referral(env["referral"]["id"], {"provider_ids": slate}, CASE_MANAGER)
    )

    offer_b = validate_success(
        api.create_offer(
            env["referral"]["id"],
            {
                "expected_referral_version": round_two["version"],
                "bed_unit_code": "UNIT-A",
                "bed_available_from": "2026-08-06T00:00:00Z",
                "hold_expires_at": "2026-08-13T00:00:00Z",
                "daily_rate_cents": 28000,
            },
            make_liaison_headers(env["provider_b"]["id"]),
        ),
        201,
    )

    assert offer_b["round_index"] == 2, "the offer copies the referral's current round"
    assert offer_b["status"] == "OFFERED"
    assert read_referral(env["referral"]["id"])["status"] == "CHOICE_PENDING"

    withdrawn = validate_success(api.get_offer(env["offer"]["id"], CASE_MANAGER))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["round_index"] == 1, "the superseded round-1 offer keeps its round"
    assert read_provider(env["provider_a"]["id"])["held_bed_units"] == 0
    assert read_provider(env["provider_b"]["id"])["held_bed_units"] == 1


def test_rebroadcast_while_a_round_one_offer_is_still_live_is_refused(api):
    """PRD §3.4: "If any offer of the current round is still `OFFERED`, or one has already
    been accepted, the rebroadcast is refused with `ERR_ROUND_STILL_OPEN` (HTTP 422)."
    PRD §3.4: "A successful broadcast increments `round_index` by one — from 0 to 1 on the
    first round — replaces `broadcast_provider_ids` with the supplied list in the order
    given, increments each listed provider's `offers_received_count` by one, and advances
    the referral's `version` by one."

    Design: Corner/state_machines/referral_rebroadcast_with_live_offer_returns_round_still_open
    """
    env = setup_choice_pending_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-C208", "full_name": "Jax Kaur", "date_of_birth": "1942-10-10",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        offer={"daily_rate_cents": 30000},
    )
    slate = [p["id"] for p in env["providers"]]

    response = api.broadcast_referral(
        env["referral"]["id"], {"provider_ids": slate}, CASE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_ROUND_STILL_OPEN, 422)
    referral = read_referral(env["referral"]["id"])
    assert referral["round_index"] == 1
    assert referral["status"] == "CHOICE_PENDING"
    assert read_provider(env["provider_b"]["id"])["offers_received_count"] == 1, (
        "the refused rebroadcast credits nobody a second invitation"
    )
    assert validate_success(api.get_offer(env["offer"]["id"], CASE_MANAGER))["status"] == "OFFERED"


def test_broadcast_omitting_an_in_network_provider_violates_no_steering(api):
    """PRD §3.4: "Second, the no-steering rule: the slate must contain **every** `ACTIVE`
    provider whose `provider_type` equals the requested level of care and which holds a
    network contract with `in_network` set to true for the episode's payer. Omitting even
    one such provider is `ERR_REFERRAL_FAIRNESS_VIOLATION`."
    PRD §3.4: "A hospital may add out-of-network or non-contracted facilities to the slate
    freely; what it may not do is quietly leave an in-network competitor off it."

    Design: Corner/validations/broadcast_omitting_in_network_provider_returns_referral_fairness_violation
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-D005", "full_name": "Tal Ubeda", "date_of_birth": "1946-09-09",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    cedar = seed_provider(name="Cedar SNF", bed_unit_codes=["UNIT-A"])
    birch = seed_provider(name="Birch SNF", quality_star_rating=5,
                          distance_miles_from_hospital=22, bed_unit_codes=["UNIT-A"])
    alder = seed_provider(name="Alder SNF", quality_star_rating=3,
                          distance_miles_from_hospital=12, bed_unit_codes=["UNIT-A"])
    willow = seed_provider(name="Willow SNF", quality_star_rating=2,
                           distance_miles_from_hospital=30, bed_unit_codes=["UNIT-A"])
    seed_network_contract(env["payer"]["id"], cedar["id"], in_network=True,
                          negotiated_daily_rate_cents=30000)
    referral = get_success_data(
        api.create_referral(env["episode"]["id"], referral_payload(), CASE_MANAGER)
    )

    response = api.broadcast_referral(
        referral["id"],
        {"provider_ids": [birch["id"], alder["id"], willow["id"]]},
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_REFERRAL_FAIRNESS_VIOLATION, 422)
    assert response.json()["data"]["error_id"] != "ERR_INSUFFICIENT_PROVIDER_CHOICE"
    after = read_referral(referral["id"])
    assert after["status"] == "DRAFT"
    assert after["round_index"] == 0
    assert read_provider(birch["id"])["offers_received_count"] == 0


def test_broadcast_to_only_two_active_providers_is_refused(api):
    """PRD §3.4: "First, the breadth rule: the slate must contain at least three distinct
    providers whose `status` is `ACTIVE` and whose `provider_type` equals the referral's
    `requested_level_of_care`. Exactly three passes; two fails, and so does an empty slate.
    The refusal is `ERR_INSUFFICIENT_PROVIDER_CHOICE`, and its purpose is that patient
    choice must be presented from a genuine pool rather than from a foregone conclusion."
    PRD §3.4: "A successful broadcast increments `round_index` by one — from 0 to 1 on the
    first round — replaces `broadcast_provider_ids` with the supplied list in the order
    given, increments each listed provider's `offers_received_count` by one, and advances
    the referral's `version` by one."

    Design: Corner/validations/broadcast_with_only_two_providers_returns_insufficient_provider_choice
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-D006", "full_name": "Ura Vidal", "date_of_birth": "1945-10-10",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    cedar = seed_provider(name="Cedar SNF", bed_unit_codes=["UNIT-A"])
    birch = seed_provider(name="Birch SNF", quality_star_rating=5,
                          distance_miles_from_hospital=22, bed_unit_codes=["UNIT-A"])
    alder = seed_provider(name="Alder SNF", quality_star_rating=3,
                          distance_miles_from_hospital=12, bed_unit_codes=["UNIT-A"])
    referral = get_success_data(
        api.create_referral(env["episode"]["id"], referral_payload(), CASE_MANAGER)
    )

    refused = api.broadcast_referral(
        referral["id"], {"provider_ids": [cedar["id"], birch["id"]]}, CASE_MANAGER
    )
    validate_error(refused, ApiErrorId.ERR_INSUFFICIENT_PROVIDER_CHOICE, 422)
    interim = read_referral(referral["id"])
    assert interim["status"] == "DRAFT"
    assert interim["round_index"] == 0

    accepted = validate_success(
        api.broadcast_referral(
            referral["id"],
            {"provider_ids": [cedar["id"], birch["id"], alder["id"]]},
            CASE_MANAGER,
        )
    )
    assert accepted["round_index"] == 1, "exactly three providers passes the breadth rule"
    assert accepted["status"] == "BROADCAST"
    for provider in (cedar, birch, alder):
        assert read_provider(provider["id"])["offers_received_count"] == 1


def test_broadcast_naming_a_suspended_provider_is_refused_as_unavailable(api):
    """PRD §3.1: "Suspending a provider moves its `status` to `SUSPENDED` and removes it
    from every future referral candidate pool, but deliberately leaves any bed holds it
    already has outstanding untouched."
    PRD §3.4: "A slate naming a `SUSPENDED` provider is refused with
    `ERR_RESOURCE_UNAVAILABLE`, and a slate naming a provider id that resolves to nothing
    at all is refused with `ERR_PROVIDER_NOT_FOUND`."

    Design: Corner/validations/broadcast_including_suspended_provider_returns_resource_unavailable
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-D007", "full_name": "Vic Waller", "date_of_birth": "1944-11-11",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    cedar = seed_provider(name="Cedar SNF", bed_unit_codes=["UNIT-A"])
    birch = seed_provider(name="Birch SNF", quality_star_rating=5,
                          distance_miles_from_hospital=22, bed_unit_codes=["UNIT-A"])
    alder = seed_provider(name="Alder SNF", quality_star_rating=3,
                          distance_miles_from_hospital=12, bed_unit_codes=["UNIT-A"])
    willow = seed_provider(name="Willow SNF", quality_star_rating=2,
                           distance_miles_from_hospital=30, bed_unit_codes=["UNIT-A"])
    suspended = validate_success(api.suspend_provider(willow["id"], PLATFORM_ADMIN))
    assert suspended["status"] == "SUSPENDED"

    referral = get_success_data(
        api.create_referral(env["episode"]["id"], referral_payload(), CASE_MANAGER)
    )
    response = api.broadcast_referral(
        referral["id"],
        {"provider_ids": [cedar["id"], birch["id"], alder["id"], willow["id"]]},
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_RESOURCE_UNAVAILABLE, 422)
    after = read_referral(referral["id"])
    assert after["status"] == "DRAFT"
    assert after["round_index"] == 0
    for provider in (cedar, birch, alder, willow):
        assert read_provider(provider["id"])["offers_received_count"] == 0, (
            "the refused broadcast credits no invitation at all"
        )


def test_invited_provider_that_never_offered_reports_a_zero_acceptance_rate(api):
    """PRD §3.1: "Those five counters are the fairness telemetry:
    `offers_received_count` counts the broadcast rounds this provider was invited into,
    `offers_submitted_count` counts every bed offer it has ever created regardless of
    outcome, `offers_accepted_count` counts the ones a patient chose, and
    `acceptance_rate_pct` is `offers_accepted_count` multiplied by 100, divided by
    `offers_submitted_count`, rounded half up to one decimal place — with the special case
    that a provider which has submitted nothing reads exactly 0.0 rather than erroring on
    the division."

    Design: Difficulty/boundary_precision_check/empty_offer_pool_yields_zero_acceptance_rate_and_null_recommendation
    """
    env = setup_broadcast_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-6101", "full_name": "Nia Osei", "date_of_birth": "1957-03-03",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )

    data = validate_success(api.get_provider(env["provider_c"]["id"], CASE_MANAGER))

    assert data["offers_received_count"] == 1, "the provider was invited into one round"
    assert data["offers_submitted_count"] == 0
    assert data["offers_accepted_count"] == 0
    assert data["acceptance_rate_pct"] == 0.0, (
        "a zero denominator reads exactly 0.0 rather than erroring, got "
        f"{data['acceptance_rate_pct']}"
    )
    assert data["held_bed_units"] == 0


def test_broadcast_referral_with_no_offers_recommends_nothing(api):
    """PRD §3.5: "The eligible set is the offers belonging to that referral whose
    `round_index` equals the referral's current `round_index`, whose `status` is `OFFERED`,
    whose `hold_expires_at` is strictly later than the logical clock now, and whose
    provider's `status` is `ACTIVE`."
    PRD §3.5: "When the eligible set is empty, `recommended_bed_offer_id` is null and no
    error is raised on read."

    Design: Difficulty/boundary_precision_check/empty_offer_pool_yields_zero_acceptance_rate_and_null_recommendation
    """
    env = setup_broadcast_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-6102", "full_name": "Nia Osei", "date_of_birth": "1957-03-03",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )

    data = validate_success(api.get_referral(env["referral"]["id"], CASE_MANAGER))

    assert_referral(data)
    assert data["recommended_bed_offer_id"] is None, (
        "an empty eligible set yields a null recommendation, got "
        f"{data['recommended_bed_offer_id']}"
    )
    assert data["status"] == "BROADCAST"
    assert data["round_index"] == 1
