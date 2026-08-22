"""Settlement drafting, exposure pricing, the authority ladder and offer responses."""

from test_helpers import (
    ApiErrorId,
    assert_instant,
    assert_settlement_offer,
    authorize_offer,
    create_contract_clause,
    create_precedent_case,
    draft_offer,
    file_grievance,
    grievance_version,
    read_grievance,
    set_clock,
    setup_authorized_offer,
    setup_base,
    setup_grievance,
    validate_error,
    validate_paginated,
    validate_success,
)

CAPPED_EXPEDITED_CLAUSE = {
    "clause_number": "ART-19",
    "title": "Safety and Health",
    "category": "SAFETY",
    "monetary_cap_cents": 500_000,
    "expedited": True,
}


def test_precedent_setting_multiplier_is_applied_before_the_clause_cap(api):
    """PRD §3.4: "The second stage applies the precedent-setting multiplier and then the
    clause cap, in that order. When `precedent_setting` is true the raw exposure is
    multiplied by 1.25 and rounded half up; when it is false the multiplier is 1.00. Only
    then, if the cited clause carries a non-null `monetary_cap_cents`, the result is reduced
    to that cap if it exceeds it."
    PRD §3.4: "The third stage picks the base tier **from the capped exposure**. An
    exposure of 50,000 cents or less sits in the `ANALYST` tier; above that and up to the
    agreement's `director_authority_cents` it is `DIRECTOR`; above that and up to
    `negotiator_authority_cents` it is `NEGOTIATOR`; anything above that is `BOARD`."

    Design: Difficulty/combinatorial_formula/settlement_exposure_tier_nested_min_max_branch
    """
    ctx = setup_grievance(
        clause_overrides=CAPPED_EXPEDITED_CLAUSE,
        statement="Unsafe machine guarding",
        incident_date="2026-07-20T00:00:00Z",
        discovery_date="2026-07-25T00:00:00Z",
        remedy_requested_cents=300_000,
        back_pay_hours_claimed=20,
    )

    offer = draft_offer(
        ctx["grievance"]["id"],
        monetary_cents=300_000,
        back_pay_hours=20,
        remedy_terms="POLICY_CHANGE",
        precedent_setting=True,
    )
    assert_settlement_offer(offer)

    assert offer["exposure_cents"] == 500_000, (
        "raw 520000 lifted to 650000 by the 1.25 multiplier, then clamped to the 500000 cap"
    )
    assert offer["authority_tier"] == "NEGOTIATOR"
    assert offer["precedent_deviation_bps"] is None


def test_reinstatement_loading_takes_the_larger_of_the_floor_and_forty_hours(api):
    """PRD §3.4: "The non-monetary bundle carries its own loading: `NONE` adds nothing,
    `RECORD_EXPUNGEMENT` adds 25,000 cents, `SENIORITY_RESTORATION` adds 75,000 cents,
    `POLICY_CHANGE` adds 150,000 cents, and `REINSTATEMENT` adds whichever is larger of a
    floor of 200,000 cents and the grievant's hourly rate multiplied by forty hours — one
    full working week at the grievant's rate."
    PRD §3.4: "The new offer is written at `DRAFT` with `round_number` 1 and
    `prepared_by_user_id` set to the drafting operator's `X-User-ID`, and with
    `authorized_by_user_id`, `authorized_at` and `expires_at` all null."

    Design: Difficulty/combinatorial_formula/settlement_exposure_tier_nested_min_max_branch
    """
    ctx = setup_grievance(
        clause_overrides=CAPPED_EXPEDITED_CLAUSE,
        statement="Unsafe machine guarding",
        incident_date="2026-07-20T00:00:00Z",
        discovery_date="2026-07-25T00:00:00Z",
    )

    offer = draft_offer(
        ctx["grievance"]["id"],
        monetary_cents=0,
        back_pay_hours=0,
        remedy_terms="REINSTATEMENT",
        precedent_setting=False,
    )

    assert offer["exposure_cents"] == 200_000, "the 200000 floor beats 3500 * 40 = 140000"
    assert offer["authority_tier"] == "DIRECTOR"
    assert offer["status"] == "DRAFT"
    assert offer["round_number"] == 1
    assert offer["authorized_by_user_id"] is None
    assert offer["authorized_at"] is None
    assert offer["expires_at"] is None


def test_board_tier_offer_is_beyond_every_role_including_the_negotiator(api, negotiator_headers):
    """PRD §3.4: "The offer's `authority_tier` must sit within the acting role's ceiling: a
    `LaborRelationsDirector` may authorize the `ANALYST` and `DIRECTOR` tiers, a
    `ChiefNegotiator` may authorize the `ANALYST`, `DIRECTOR` and `NEGOTIATOR` tiers, and
    **no role in this system may authorize a `BOARD`-tier offer at all** — every failure
    here is `ERR_AUTHORITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/offer_state_beats_authority_ceiling
    """
    ctx = setup_grievance(statement="Contracting out of unit work")
    offer = draft_offer(ctx["grievance"]["id"], monetary_cents=1_600_000)

    assert offer["exposure_cents"] == 1_600_000
    assert offer["authority_tier"] == "BOARD"

    response = api.authorize_settlement_offer(
        offer["id"],
        {"expected_grievance_version": grievance_version(ctx["grievance"]["id"])},
        negotiator_headers,
    )
    validate_error(response, ApiErrorId.ERR_AUTHORITY_EXCEEDED.value)


def test_offer_state_check_pre_empts_the_authority_ceiling(api, negotiator_headers, analyst_headers):
    """PRD §2.10: "When a single request would fail several checks, the outcome is not a
    matter of taste: the checks are evaluated strictly in the order below, and the **first**
    check that fails determines the error the caller receives."
    PRD §3.4: "The offer must still be at `DRAFT`, or the attempt is rejected with
    `ERR_OFFER_NOT_DRAFT`."

    Design: Difficulty/priority_pair_validation_conflict/offer_state_beats_authority_ceiling
    """
    ctx = setup_grievance(statement="Contracting out of unit work")
    offer = draft_offer(ctx["grievance"]["id"], monetary_cents=1_600_000)

    validate_success(
        api.withdraw_grievance(
            ctx["grievance"]["id"], {"reason": "Grievant resigned"}, ctx["steward_headers"]
        ),
        200,
    )
    voided = validate_success(api.get_settlement_offer(offer["id"], analyst_headers), 200)
    assert voided["status"] == "VOIDED"
    assert voided["authority_tier"] == "BOARD"
    assert read_grievance(ctx["grievance"]["id"])["status"] == "WITHDRAWN"

    response = api.authorize_settlement_offer(
        offer["id"],
        {"expected_grievance_version": grievance_version(ctx["grievance"]["id"])},
        negotiator_headers,
    )
    validate_error(response, ApiErrorId.ERR_OFFER_NOT_DRAFT.value)

    after = validate_success(api.get_settlement_offer(offer["id"], analyst_headers), 200)
    assert after["status"] == "VOIDED"
    assert after["authorized_by_user_id"] is None


def test_precedent_deviation_beyond_tolerance_escalates_the_tier_one_level(api, director_headers):
    """PRD §3.4: "If a precedent is cited, its `monetary_value_cents` is first
    scope-adjusted — multiplied by 1.00 for `UNIT_WIDE`, 0.75 for `DEPARTMENT` or 0.50 for
    `INDIVIDUAL`, rounded half up — and `precedent_deviation_bps` is then the absolute
    difference between `exposure_cents` and that scope-adjusted value, multiplied by
    10,000, divided by the scope-adjusted value or by 1 if that value is 0, and rounded half
    up."
    PRD §3.4: "When the deviation is strictly greater than the agreement's
    `precedent_deviation_tolerance_bps`, the `authority_tier` becomes the next rung up the
    ladder `ANALYST` → `DIRECTOR` → `NEGOTIATOR` → `BOARD`, with `BOARD` escalating to
    itself; when the deviation is within tolerance, the `authority_tier` equals the base
    tier."

    Design: Corner/calculations/precedent_deviation_escalates_authority_by_one_level
    """
    ctx = setup_grievance()
    unit_wide = create_precedent_case(ctx["clause"]["id"])
    department = create_precedent_case(
        ctx["clause"]["id"],
        citation="88 LA 101 (Reyes 2024)",
        decided_on="2024-02-11T00:00:00Z",
        outcome="SPLIT",
        monetary_value_cents=280_000,
        binding_scope="DEPARTMENT",
        arbitrator_name="L. Reyes",
    )

    escalated = draft_offer(
        ctx["grievance"]["id"], monetary_cents=75_000, back_pay_hours=50,
        precedent_case_id=unit_wide["id"],
    )
    within = draft_offer(
        ctx["grievance"]["id"], monetary_cents=75_000, back_pay_hours=50,
        precedent_case_id=department["id"],
    )

    assert escalated["exposure_cents"] == 250_000
    assert escalated["precedent_deviation_bps"] == 2_500
    assert escalated["authority_tier"] == "NEGOTIATOR"

    assert within["exposure_cents"] == 250_000
    assert within["precedent_deviation_bps"] == 1_905, "measured against 0.75 * 280000 = 210000"
    assert within["authority_tier"] == "DIRECTOR"


def test_escalated_tier_is_beyond_the_director_but_within_the_negotiator(
    api, director_headers, negotiator_headers
):
    """PRD §3.4: "The offer's `authority_tier` must sit within the acting role's ceiling: a
    `LaborRelationsDirector` may authorize the `ANALYST` and `DIRECTOR` tiers, a
    `ChiefNegotiator` may authorize the `ANALYST`, `DIRECTOR` and `NEGOTIATOR` tiers, and
    **no role in this system may authorize a `BOARD`-tier offer at all** — every failure
    here is `ERR_AUTHORITY_EXCEEDED`."
    PRD §3.1: "Precedents are immutable reference data — they carry no `updated_at` and no
    `version` — and report one derived counter, `cited_count`, the number of settlement
    offers naming them whose status is anything other than `VOIDED`, which reads 0 for a
    freshly recorded precedent."

    Design: Corner/calculations/precedent_deviation_escalates_authority_by_one_level
    """
    ctx = setup_grievance()
    unit_wide = create_precedent_case(ctx["clause"]["id"])
    offer = draft_offer(
        ctx["grievance"]["id"], monetary_cents=75_000, back_pay_hours=50,
        precedent_case_id=unit_wide["id"],
    )
    version = grievance_version(ctx["grievance"]["id"])

    refused = api.authorize_settlement_offer(
        offer["id"], {"expected_grievance_version": version}, director_headers
    )
    validate_error(refused, ApiErrorId.ERR_AUTHORITY_EXCEEDED.value)
    assert validate_success(
        api.get_settlement_offer(offer["id"], director_headers), 200
    )["status"] == "DRAFT"

    accepted = validate_success(
        api.authorize_settlement_offer(
            offer["id"], {"expected_grievance_version": version}, negotiator_headers
        ),
        200,
    )
    assert accepted["status"] == "AUTHORIZED"

    precedent = validate_success(
        api.get_precedent_case(unit_wide["id"], director_headers), 200
    )
    assert precedent["cited_count"] == 1


def test_authorizing_a_second_offer_lapses_the_authorized_one_only(api, director_headers):
    """PRD §3.4: "It also has two consequences beyond the offer itself: every **other**
    offer on the same grievance standing at `AUTHORIZED` is transitioned to `LAPSED` and can
    no longer be responded to, and the parent grievance's `version` increments by 1."

    Design: Corner/state_machines/authorizing_a_second_offer_lapses_the_first
    """
    ctx = setup_grievance()
    first = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    second = draft_offer(ctx["grievance"]["id"], monetary_cents=45_000)
    third = draft_offer(ctx["grievance"]["id"], monetary_cents=20_000)

    authorize_offer(first["id"], ctx["grievance"]["id"])
    version_before = grievance_version(ctx["grievance"]["id"])

    authorized = validate_success(
        api.authorize_settlement_offer(
            second["id"], {"expected_grievance_version": version_before}, director_headers
        ),
        200,
    )

    assert authorized["status"] == "AUTHORIZED"
    assert_instant(authorized["authorized_at"], "2026-08-01T00:00:00Z", "authorized_at")
    assert_instant(authorized["expires_at"], "2026-08-11T00:00:00Z", "expires_at")

    assert validate_success(
        api.get_settlement_offer(first["id"], director_headers), 200
    )["status"] == "LAPSED"
    assert validate_success(
        api.get_settlement_offer(third["id"], director_headers), 200
    )["status"] == "DRAFT", "a DRAFT sibling is untouched by the supersede cascade"

    assert grievance_version(ctx["grievance"]["id"]) == version_before + 1


def test_counter_response_spawns_a_fresh_draft_discoverable_only_through_the_listing(
    api, analyst_headers
):
    """PRD §3.4: "`COUNTER` moves the responded offer to `COUNTERED` and creates a **new**
    offer on the same grievance in `DRAFT`, with `offering_party` flipped to the responding
    side, `round_number` one greater than the countered offer's, and `prepared_by_user_id`
    set to the responding operator's `X-User-ID`."
    PRD §3.4: "That new draft is deliberately **not** returned by the response; the only way
    to discover it is to list the settlement offers of the grievance, filtered by
    `grievance_id`."

    Design: Corner/state_machines/counter_response_spawns_a_new_draft_only_visible_through_the_list
    """
    ctx = setup_authorized_offer(monetary_cents=40_000)

    countered = validate_success(
        api.respond_settlement_offer(
            ctx["offer"]["id"],
            {
                "decision": "COUNTER",
                "counter_monetary_cents": 48_000,
                "counter_back_pay_hours": 0,
                "counter_remedy_terms": "RECORD_EXPUNGEMENT",
                "counter_precedent_setting": False,
                "response_note": "Union counter",
            },
            ctx["steward_headers"],
        ),
        200,
    )
    assert countered["status"] == "COUNTERED"
    assert countered["round_number"] == 1

    rows, meta = validate_paginated(
        api.list_settlement_offers(
            analyst_headers, params={"grievance_id": ctx["grievance"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    counter = rows[1]
    assert counter["round_number"] == 2
    assert counter["status"] == "DRAFT"
    assert counter["offering_party"] == "UNION"
    assert counter["monetary_cents"] == 48_000
    assert counter["remedy_terms"] == "RECORD_EXPUNGEMENT"
    assert counter["exposure_cents"] == 73_000
    assert counter["authority_tier"] == "DIRECTOR"
    assert counter["prepared_by_user_id"] == ctx["steward"]["id"]

    assert read_grievance(ctx["grievance"]["id"])["status"] == "FILED"


def test_responding_to_a_draft_offer_is_refused(api, analyst_headers):
    """PRD §3.4: "The offer must be at `AUTHORIZED`, or the response is rejected with
    `ERR_OFFER_NOT_AUTHORIZED`, and the clock must be at or before `expires_at`, or it is
    rejected with `ERR_OFFER_EXPIRED`."

    Design: Corner/state_machines/responding_to_a_draft_offer_returns_offer_not_authorized
    """
    ctx = setup_grievance()
    offer = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)

    response = api.respond_settlement_offer(
        offer["id"], {"decision": "ACCEPT"}, ctx["steward_headers"]
    )
    validate_error(response, ApiErrorId.ERR_OFFER_NOT_AUTHORIZED.value)

    unchanged = validate_success(api.get_settlement_offer(offer["id"], analyst_headers), 200)
    assert unchanged["status"] == "DRAFT"
    assert unchanged["authorized_at"] is None
    assert unchanged["expires_at"] is None

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["status"] == "FILED"
    assert grievance["settled_amount_cents"] == 0


def test_responding_after_the_offer_expiry_is_refused(api, analyst_headers):
    """PRD §3.4: "An authorization that clears all three bars moves the offer from `DRAFT`
    to `AUTHORIZED`, stamps `authorized_by_user_id` with the acting `X-User-ID` and
    `authorized_at` with the clock's current instant, and sets `expires_at` to ten days
    after that instant."
    PRD §3.4: "The offer must be at `AUTHORIZED`, or the response is rejected with
    `ERR_OFFER_NOT_AUTHORIZED`, and the clock must be at or before `expires_at`, or it is
    rejected with `ERR_OFFER_EXPIRED`."

    Design: Corner/validations/responding_to_an_expired_offer_is_refused
    """
    ctx = setup_authorized_offer(monetary_cents=40_000)
    assert_instant(ctx["offer"]["expires_at"], "2026-08-11T00:00:00Z", "expires_at")

    set_clock("2026-08-12T00:00:00Z")
    response = api.respond_settlement_offer(
        ctx["offer"]["id"], {"decision": "ACCEPT"}, ctx["steward_headers"]
    )
    validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED.value)

    unchanged = validate_success(
        api.get_settlement_offer(ctx["offer"]["id"], analyst_headers), 200
    )
    assert unchanged["status"] == "AUTHORIZED"

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["status"] == "FILED"
    assert grievance["settled_amount_cents"] == 0


def test_director_tier_offer_without_a_precedent_is_refused(api, director_headers):
    """PRD §3.4: "Finally, precedent review is compulsory above the lowest tier: an offer
    whose base tier is `DIRECTOR` or above must cite a precedent, so an offer with no
    `precedent_case_id` may only be authorized when its tier is `ANALYST`, and otherwise the
    attempt is rejected with `ERR_PRECEDENT_REVIEW_REQUIRED`."

    Design: Corner/validations/director_tier_offer_without_a_precedent_is_refused
    """
    ctx = setup_grievance()
    director_tier = draft_offer(
        ctx["grievance"]["id"], monetary_cents=75_000, back_pay_hours=50
    )
    analyst_tier = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    version = grievance_version(ctx["grievance"]["id"])

    assert director_tier["exposure_cents"] == 250_000
    assert director_tier["authority_tier"] == "DIRECTOR"
    assert director_tier["precedent_deviation_bps"] is None

    refused = api.authorize_settlement_offer(
        director_tier["id"], {"expected_grievance_version": version}, director_headers
    )
    validate_error(refused, ApiErrorId.ERR_PRECEDENT_REVIEW_REQUIRED.value)
    assert validate_success(
        api.get_settlement_offer(director_tier["id"], director_headers), 200
    )["status"] == "DRAFT"

    assert analyst_tier["exposure_cents"] == 40_000
    assert analyst_tier["authority_tier"] == "ANALYST"
    accepted = validate_success(
        api.authorize_settlement_offer(
            analyst_tier["id"], {"expected_grievance_version": version}, director_headers
        ),
        200,
    )
    assert accepted["status"] == "AUTHORIZED"


def test_offer_citing_a_precedent_on_another_clause_is_refused(api, analyst_headers):
    """PRD §3.4: "An optional `precedent_case_id` cites a precedent from the library; when
    supplied, that precedent must construe the very clause the grievance cites, or the draft
    is rejected with `ERR_PRECEDENT_CLAUSE_MISMATCH`."

    Design: Corner/validations/settlement_citing_a_precedent_on_another_clause_rejected
    """
    ctx = setup_base()
    pay_clause = create_contract_clause(
        ctx["unit"]["id"], clause_number="ART-22", title="Wage Rates", category="PAY"
    )
    pay_precedent = create_precedent_case(
        pay_clause["id"],
        citation="44 LA 900 (Ng 2022)",
        decided_on="2022-04-04T00:00:00Z",
        monetary_value_cents=150_000,
        arbitrator_name="P. Ng",
    )
    grievance = file_grievance(ctx)

    response = api.create_settlement_offer(
        grievance["id"],
        {
            "offering_party": "EMPLOYER",
            "monetary_cents": 40_000,
            "precedent_case_id": pay_precedent["id"],
        },
        analyst_headers,
    )
    validate_error(response, ApiErrorId.ERR_PRECEDENT_CLAUSE_MISMATCH.value)

    _, meta = validate_paginated(
        api.list_settlement_offers(analyst_headers, params={"grievance_id": grievance["id"]})
    )
    assert meta["total_count"] == 0
    assert validate_success(
        api.get_precedent_case(pay_precedent["id"], analyst_headers), 200
    )["cited_count"] == 0


def test_authorization_carrying_a_pre_supersede_grievance_version_is_refused(
    api, director_headers
):
    """PRD §2.7: "Authorizing a settlement offer requires the request to carry
    `expected_grievance_version`, a non-optional field holding the `version` the client last
    observed on the offer's parent grievance. If that value does not equal the grievance's
    current `version`, the request is rejected with `ERR_STALE_GRIEVANCE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_layers/occ_rejects_authorization_carrying_a_pre_supersede_grievance_version
    """
    ctx = setup_grievance()
    first = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    second = draft_offer(ctx["grievance"]["id"], monetary_cents=45_000)
    stale_version = grievance_version(ctx["grievance"]["id"])

    authorized = validate_success(
        api.authorize_settlement_offer(
            first["id"], {"expected_grievance_version": stale_version}, director_headers
        ),
        200,
    )
    assert authorized["status"] == "AUTHORIZED"
    assert grievance_version(ctx["grievance"]["id"]) == stale_version + 1

    refused = api.authorize_settlement_offer(
        second["id"], {"expected_grievance_version": stale_version}, director_headers
    )
    validate_error(refused, ApiErrorId.ERR_STALE_GRIEVANCE_VERSION.value)

    assert validate_success(
        api.get_settlement_offer(second["id"], director_headers), 200
    )["status"] == "DRAFT"
    assert grievance_version(ctx["grievance"]["id"]) == stale_version + 1


def test_re_reading_the_grievance_lets_the_supersede_go_through(api, director_headers):
    """PRD §2.7: "The check exists because an authorization legitimately supersedes any
    other authorized offer on the same grievance — the superseded one is retired — so a
    writer holding a stale view of the grievance would silently retire an authorization it
    never saw. The stale-version rejection forces that writer to re-read the grievance
    first."

    Design: Corner/cross_cutting_layers/occ_rejects_authorization_carrying_a_pre_supersede_grievance_version
    """
    ctx = setup_grievance()
    first = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    second = draft_offer(ctx["grievance"]["id"], monetary_cents=45_000)
    stale_version = grievance_version(ctx["grievance"]["id"])
    authorize_offer(first["id"], ctx["grievance"]["id"])

    validate_error(
        api.authorize_settlement_offer(
            second["id"], {"expected_grievance_version": stale_version}, director_headers
        ),
        ApiErrorId.ERR_STALE_GRIEVANCE_VERSION.value,
    )

    fresh_version = grievance_version(ctx["grievance"]["id"])
    retried = validate_success(
        api.authorize_settlement_offer(
            second["id"], {"expected_grievance_version": fresh_version}, director_headers
        ),
        200,
    )

    assert retried["status"] == "AUTHORIZED"
    assert validate_success(
        api.get_settlement_offer(first["id"], director_headers), 200
    )["status"] == "LAPSED"
    assert grievance_version(ctx["grievance"]["id"]) == fresh_version + 1
