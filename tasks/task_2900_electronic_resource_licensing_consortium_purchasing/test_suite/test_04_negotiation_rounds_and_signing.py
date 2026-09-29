"""Negotiation rounds, the vendor answer, and the five gates that guard signing."""

from test_helpers import (
    MISSING_UUID,
    accept_response_payload,
    assert_negotiation,
    create_draft_trial,
    create_negotiation,
    endorse_trial,
    make_admin_headers,
    make_vendor_rep_headers,
    negotiation_payload,
    pledge,
    read_commitment,
    read_negotiation,
    read_trial,
    revise_payload,
    revise_round,
    setup_agreed_negotiation,
    setup_catalog,
    setup_endorsed_trial,
    setup_signed_subscription,
    sign_payload,
    submit_round,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_accepts,
    vendor_counters,
)


def test_a_new_negotiation_starts_in_drafting_with_no_granted_terms(api, admin):
    """A freshly opened negotiation concedes nothing and counts no rounds.

    PRD: "The negotiation is created in `DRAFTING` with `round_count` of 0, all
    four `granted_` fields null, `vendor_counter_price_cents` and
    `agreed_price_cents` null, and both `last_submitted_by_user_id` and
    `last_vendor_disposition` null."

    Design: Corner/state_machines/a_new_negotiation_starts_in_drafting_with_no_granted_terms
    """
    scenario = setup_endorsed_trial()

    response = api.create_negotiation(
        negotiation_payload(scenario["product"]["id"], scenario["trial"]["id"]), admin)
    data = validate_success(response, expected_status=201)

    assert_negotiation(data)
    assert data["status"] == "DRAFTING"
    assert data["round_count"] == 0
    assert data["granted_ill_mode"] is None
    assert data["granted_text_mining"] is None
    assert data["granted_accessibility_conformance"] is None
    assert data["granted_perpetual_access"] is None
    assert data["vendor_counter_price_cents"] is None
    assert data["agreed_price_cents"] is None
    assert data["last_vendor_disposition"] is None
    assert data["last_submitted_by_user_id"] is None


def test_revising_a_signed_negotiation_is_rejected(api, admin, negotiator):
    """SIGNED is terminal: no revision reopens a licence that is already executed.

    PRD: "If the answer is a counter, the negotiator revises the consortium's
    asks and the negotiation returns `COUNTERED → DRAFTING`, closing one full
    cycle."

    Design: Corner/state_machines/revising_a_signed_negotiation_is_rejected
    """
    scenario = setup_signed_subscription()
    negotiation_id = scenario["negotiation"]["id"]

    response = api.revise_negotiation(negotiation_id, revise_payload(), negotiator)
    validate_error(response, "ERR_NEGOTIATION_INVALID_STATE", 409)

    stored = read_negotiation(negotiation_id)
    assert stored["status"] == "SIGNED"
    assert stored["round_count"] == 1, "the refused revision burned no round"
    assert stored["requested_ill_mode"] == "SECURE_ELECTRONIC", (
        "the requested terms are untouched by the refusal"
    )

    subscription = validate_success(
        api.get_subscription(scenario["subscription"]["id"], admin))
    assert subscription["negotiated_price_cents"] == 9000000


def test_signing_without_an_accessibility_conformance_term_is_rejected(api, admin):
    """A licence that concedes no accessibility conformance cannot be signed.

    PRD: "Accessibility must be genuinely settled:
    `granted_accessibility_conformance` must not be `NONE`, **and** the product's
    vendor must have `vpat_on_file` set to true — either failing gives
    `ERR_ACCESSIBILITY_TERM_MISSING` (422)."

    Design: Corner/state_machines/signing_without_an_accessibility_conformance_term_is_rejected
    """
    scenario = setup_agreed_negotiation(
        granted={"granted_accessibility_conformance": "NONE"},
        negotiation_overrides={"requested_accessibility_conformance": "NONE"},
    )
    commitment = pledge(scenario["product"]["id"], scenario["member"]["id"])

    response = api.sign_negotiation(scenario["negotiation"]["id"], sign_payload(), admin)
    validate_error(response, "ERR_ACCESSIBILITY_TERM_MISSING", 422)

    assert read_negotiation(scenario["negotiation"]["id"])["status"] == "AGREED"
    assert read_commitment(commitment["id"])["status"] == "PLEDGED"
    _, meta = validate_paginated(api.list_subscriptions(admin))
    assert meta["total_count"] == 0, "the refused signature created no contract"


def test_vendor_response_granting_text_mining_the_product_forbids_is_rejected(api):
    """A publisher cannot concede in a round what the package never offered.

    PRD: "A publisher may not concede in the negotiation what it never put on the
    table for the package: on any vendor response, `granted_ill_mode` must be no
    stronger than the product's `ill_mode_offered` on the ordering where
    `PROHIBITED` is weakest, `PRINT_ONLY` is stronger and `SECURE_ELECTRONIC` is
    strongest; `granted_perpetual_access` must be no stronger than the product's
    `perpetual_access_mode_offered` on the ordering where `NONE` is weakest,
    `POST_CANCELLATION_SUBSET` is stronger and `FULL_ARCHIVE` is strongest; and
    `granted_text_mining` must be false whenever the product's
    `text_mining_offered` is false."

    PRD: "A `LicenseNegotiator` sends the current draft to the publisher,
    advancing `DRAFTING → VENDOR_REVIEW`; the transition increments `round_count`
    by 1 and stamps the acting negotiator's `X-User-ID` into
    `last_submitted_by_user_id`."

    Design: Corner/validations/vendor_response_granting_text_mining_the_product_forbids_is_rejected
    """
    scenario = setup_endorsed_trial(product_overrides={"text_mining_offered": False})
    negotiation = create_negotiation(scenario["product"]["id"], scenario["trial"]["id"])
    submit_round(negotiation["id"])

    response = api.vendor_response(
        negotiation["id"],
        accept_response_payload(9000000, granted_text_mining=True),
        make_vendor_rep_headers(scenario["vendor"]["id"]),
    )
    validate_error(response, "ERR_TERM_EXCEEDS_PRODUCT_OFFER", 422)

    stored = read_negotiation(negotiation["id"])
    assert stored["status"] == "VENDOR_REVIEW", (
        "the refused answer leaves the round awaiting the publisher"
    )
    assert stored["granted_text_mining"] is None
    assert stored["last_vendor_disposition"] is None
    assert stored["agreed_price_cents"] is None
    assert stored["round_count"] == 1


def test_signing_by_the_user_who_submitted_the_round_is_rejected(api):
    """One human may not both table the round and execute the licence.

    PRD: "The signer's `X-User-ID` must differ from `last_submitted_by_user_id`,
    otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/validations/signing_by_the_user_who_submitted_the_round_is_rejected
    """
    scenario = setup_agreed_negotiation(negotiator_user_id="shared-1")
    commitment = pledge(scenario["product"]["id"], scenario["member"]["id"])

    response = api.sign_negotiation(scenario["negotiation"]["id"], sign_payload(),
                                    make_admin_headers("shared-1"))
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 403)

    stored = read_negotiation(scenario["negotiation"]["id"])
    assert stored["status"] == "AGREED"
    assert stored["last_submitted_by_user_id"] == "shared-1"
    assert read_commitment(commitment["id"])["status"] == "PLEDGED"
    _, meta = validate_paginated(api.list_subscriptions(make_admin_headers("admin-1")))
    assert meta["total_count"] == 0, "the refused signature created no contract"


def test_negotiation_with_an_unknown_trial_id_is_rejected(api, admin):
    """Both body foreign keys are resolved, and the missing one decides the answer.

    PRD: "A negotiation is opened by the collections office and is anchored on two
    things: the package it concerns, named by `product_id`, and the trial whose
    endorsement will gate the eventual signature, named by `trial_id`."

    PRD: "Every foreign key supplied in the request body resolves to an existing
    row, yielding `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND` or `ERR_TRIAL_NOT_FOUND` (404) as appropriate."

    Design: Corner/endpoints/negotiation_with_an_unknown_trial_id_is_rejected
    """
    scenario = setup_endorsed_trial()

    response = api.create_negotiation(
        negotiation_payload(scenario["product"]["id"], MISSING_UUID), admin)
    validate_error(response, "ERR_TRIAL_NOT_FOUND", 404)

    _, meta = validate_paginated(api.list_negotiations(admin))
    assert meta["total_count"] == 0, "no negotiation was opened"
    assert read_trial(scenario["trial"]["id"])["status"] == "ENDORSED", (
        "the endorsed trial was not silently substituted"
    )


def _negotiation_at_the_round_limit():
    """Three submissions and three counters, so the round budget is spent."""
    scenario = setup_catalog()
    trial = create_draft_trial(scenario["product"]["id"], scenario["member"]["id"])
    negotiation = create_negotiation(scenario["product"]["id"], trial["id"])
    vendor_id = scenario["vendor"]["id"]

    submit_round(negotiation["id"])
    vendor_counters(negotiation["id"], vendor_id, 9900000)
    revise_round(negotiation["id"])
    submit_round(negotiation["id"])
    vendor_counters(negotiation["id"], vendor_id, 9800000)
    revise_round(negotiation["id"])
    submit_round(negotiation["id"])

    scenario["trial"] = trial
    scenario["negotiation"] = vendor_counters(negotiation["id"], vendor_id, 9750000)
    return scenario


def test_revising_after_the_third_counter_hits_the_round_limit(api, negotiator):
    """The bounded loop refuses a fourth pass once three rounds are burned.

    PRD: "The loop is bounded: both sending to the vendor and revising after a
    counter require `round_count` to be strictly less than 3 rounds, and a
    negotiation that has already burned its three rounds is refused with
    `ERR_NEGOTIATION_ROUND_LIMIT` (409)."

    Design: Difficulty/non_linear_state_machine/negotiation_counter_revise_cycle_rejected_at_round_limit
    """
    scenario = _negotiation_at_the_round_limit()
    negotiation_id = scenario["negotiation"]["id"]

    response = api.revise_negotiation(
        negotiation_id,
        revise_payload(requested_ill_mode="SECURE_ELECTRONIC", requested_text_mining=True,
                       requested_accessibility_conformance="WCAG_2_1_AA",
                       requested_perpetual_access="FULL_ARCHIVE"),
        negotiator,
    )
    validate_error(response, "ERR_NEGOTIATION_ROUND_LIMIT", 409)

    stored = read_negotiation(negotiation_id)
    assert stored["round_count"] == 3, "the refused revision burned no further round"
    assert stored["status"] == "COUNTERED", "the row stays where the counter left it"
    assert stored["vendor_counter_price_cents"] == 9750000
    assert stored["last_vendor_disposition"] == "COUNTER"
    assert stored["agreed_price_cents"] is None, "nothing was ever agreed"


def test_the_counter_revise_cycle_increments_the_round_count_twice_round(api, negotiator):
    """Each pass round the cycle returns to DRAFTING and only sending counts a round.

    PRD: "A `LicenseNegotiator` sends the current draft to the publisher,
    advancing `DRAFTING → VENDOR_REVIEW`; the transition increments `round_count`
    by 1 and stamps the acting negotiator's `X-User-ID` into
    `last_submitted_by_user_id`."

    PRD: "That amount is recorded as `vendor_counter_price_cents`,
    `last_vendor_disposition` becomes `COUNTER`, and the negotiation advances
    `VENDOR_REVIEW → COUNTERED`."

    Design: Difficulty/non_linear_state_machine/negotiation_counter_revise_cycle_rejected_at_round_limit
    """
    scenario = setup_catalog()
    trial = create_draft_trial(scenario["product"]["id"], scenario["member"]["id"])
    negotiation = create_negotiation(scenario["product"]["id"], trial["id"])
    negotiation_id = negotiation["id"]
    vendor_id = scenario["vendor"]["id"]

    first_send = submit_round(negotiation_id)
    assert first_send["status"] == "VENDOR_REVIEW"
    assert first_send["round_count"] == 1
    assert first_send["last_submitted_by_user_id"] == "neg-1"

    first_counter = vendor_counters(negotiation_id, vendor_id, 9900000)
    assert first_counter["status"] == "COUNTERED"
    assert first_counter["vendor_counter_price_cents"] == 9900000

    back_to_drafting = revise_round(negotiation_id)
    assert back_to_drafting["status"] == "DRAFTING", "one full cycle closed"
    assert back_to_drafting["round_count"] == 1, "revising does not count a round"

    assert submit_round(negotiation_id)["round_count"] == 2
    vendor_counters(negotiation_id, vendor_id, 9800000)
    assert revise_round(negotiation_id)["status"] == "DRAFTING"
    assert submit_round(negotiation_id)["round_count"] == 3
    third_counter = vendor_counters(negotiation_id, vendor_id, 9750000)
    assert third_counter["status"] == "COUNTERED"

    refused = api.revise_negotiation(negotiation_id, revise_payload(), negotiator)
    validate_error(refused, "ERR_NEGOTIATION_ROUND_LIMIT", 409)
    assert read_negotiation(negotiation_id)["round_count"] == 3


def _agreed_negotiation_on_a_draft_trial():
    """Every signing gate satisfied except the referenced trial's own state."""
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]
    trial = create_draft_trial(scenario["product"]["id"], member_id)
    negotiation = create_negotiation(scenario["product"]["id"], trial["id"])
    submit_round(negotiation["id"], "neg-1")
    scenario["negotiation"] = vendor_accepts(negotiation["id"], scenario["vendor"]["id"],
                                             9000000)
    scenario["trial"] = trial
    scenario["commitment"] = pledge(scenario["product"]["id"], member_id)
    scenario["member_id"] = member_id
    return scenario


def test_signing_is_refused_while_the_referenced_trial_is_still_draft(api, admin):
    """The sibling trial's state, not the negotiation's, decides the signature.

    PRD: "The trial named by the negotiation's `trial_id` must be in `ENDORSED`,
    otherwise `ERR_TRIAL_NOT_ENDORSED` (409)."

    Design: Difficulty/cross_entity_state_dependency/signing_rejected_while_the_referenced_trial_is_still_draft
    """
    scenario = _agreed_negotiation_on_a_draft_trial()

    response = api.sign_negotiation(scenario["negotiation"]["id"],
                                    sign_payload("2027-01-01"), admin)
    validate_error(response, "ERR_TRIAL_NOT_ENDORSED", 409)

    assert read_negotiation(scenario["negotiation"]["id"])["status"] == "AGREED", (
        "the negotiation's own axis was ready to move"
    )
    assert read_trial(scenario["trial"]["id"])["status"] == "DRAFT"

    commitment = read_commitment(scenario["commitment"]["id"])
    assert commitment["status"] == "PLEDGED"
    assert commitment["tier_price_cents"] is None
    _, meta = validate_paginated(api.list_subscriptions(admin))
    assert meta["total_count"] == 0, "no contract came into existence"


def test_endorsing_the_trial_afterwards_unblocks_the_same_signature(api, admin):
    """Once the sibling reaches ENDORSED the identical signature succeeds.

    PRD: "Both are terminal, as is `WITHDRAWN`, and only `ENDORSED` unlocks a
    signature downstream."

    PRD: "Signing is where five independent gates converge, and it is a
    `ConsortiumAdmin` capability that answers 201 rather than 200 because its
    whole purpose is to bring a new resource into existence."

    Design: Difficulty/cross_entity_state_dependency/signing_rejected_while_the_referenced_trial_is_still_draft
    """
    scenario = _agreed_negotiation_on_a_draft_trial()
    negotiation_id = scenario["negotiation"]["id"]

    validate_error(
        api.sign_negotiation(negotiation_id, sign_payload("2027-01-01"), admin),
        "ERR_TRIAL_NOT_ENDORSED", 409)

    endorsed = endorse_trial(scenario["trial"]["id"], scenario["member_id"])
    assert endorsed["status"] == "ENDORSED"

    data = validate_success(
        api.sign_negotiation(negotiation_id, sign_payload("2027-01-01"), admin),
        expected_status=201)
    assert data["negotiated_price_cents"] == 9000000
    assert data["contract_status"] == "PENDING_ACTIVATION"
    assert read_negotiation(negotiation_id)["status"] == "SIGNED"
    assert read_commitment(scenario["commitment"]["id"])["status"] == "CONFIRMED"
