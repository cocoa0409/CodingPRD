"""Publication and activation: the cascade, the modifier table, quote gating."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_classification,
    advance_cycle_to,
    bind_quote,
    create_cycle,
    create_property,
    create_quote,
    create_score_sheet,
    finalize_score_sheet,
    get_community,
    get_success_data,
    premium_quote_payload,
    publish_classification,
    setup_classification_review,
    setup_classified_community,
    transition_cycle,
    validate_error,
)

COORD = TEST_USERS["evaluation_coordinator_headers"]
INSURER = TEST_USERS["insurer_headers"]
REGISTRAR = TEST_USERS["class_registrar_headers"]


def _triggerton(api):
    """Class-10 EFFECTIVE community, one property, one BOUND and one QUOTED
    quote, plus a second PUBLISHED classification from an identical rescore."""
    ctx = setup_classified_community(api, name="Triggerton")
    community_id = ctx["community"]["id"]
    prop = create_property(
        api, community_id, address="1 Pine St", distance_to_nearest_hydrant_ft=500,
        distance_to_nearest_station_road_miles=1.0, construction_type="FRAME",
        insured_value_cents=200000000,
    )
    q1 = create_quote(api, prop["id"], coverage_amount_cents=10000000, term_months=6)
    bind_quote(api, community_id, q1["id"])
    q2 = create_quote(
        api, prop["id"], coverage_amount_cents=5000000, term_months=3,
        coverage_start_date="2028-01-01", coverage_end_date="2028-03-31",
    )
    cycle2 = create_cycle(api, community_id)
    advance_cycle_to(api, cycle2["id"], "SCORING")
    sheet2 = create_score_sheet(api, cycle2["id"])
    finalize_score_sheet(api, sheet2["id"])
    transition_cycle(api, cycle2["id"], "CLASSIFICATION_REVIEW")
    cl2 = publish_classification(api, cycle2["id"], sheet2["id"])
    return ctx, prop, q1, q2, cl2


def test_activation_supersedes_prior_and_rewrites_community(api):
    """PRD §3.7: "The activation cascade then fires in full: the community's
    prior `EFFECTIVE` classification, if any, becomes `SUPERSEDED` with its
    `effective_until` set to the new `effective_from`; the community moves to
    `CLASSIFIED` with `current_class_number` set to the new `base_class`".

    Design: Difficulty/transitive_cascade/classification_activation_cascade
    """
    ctx, prop, q1, q2, cl2 = _triggerton(api)
    cl1_id = ctx["classification"]["id"]
    activate_classification(api, cl2["id"], effective_from="2026-09-01")
    cl1 = get_success_data(api.get_classification(cl1_id, COORD))
    assert cl1["status"] == "SUPERSEDED"
    assert cl1["effective_until"] == "2026-09-01"
    community = get_community(api, ctx["community"]["id"])
    assert community["status"] == "CLASSIFIED"
    assert community["current_class_number"] == 10
    assert community["current_premium_modifier"] == pytest.approx(1.25)


def test_activation_expires_quoted_but_not_bound_quotes(api):
    """PRD §3.7: "every premium quote still `QUOTED` on those properties
    becomes `EXPIRED`, because the classification it pinned has been
    superseded — `BOUND` quotes are untouched."

    Design: Difficulty/transitive_cascade/classification_activation_cascade
    """
    ctx, prop, q1, q2, cl2 = _triggerton(api)
    activate_classification(api, cl2["id"], effective_from="2026-09-01")
    refreshed_prop = get_success_data(api.get_property_risk_profile(prop["id"], INSURER))
    assert refreshed_prop["applicable_class"] == 10
    expired = get_success_data(api.get_premium_quote(q2["id"], INSURER))
    assert expired["status"] == "EXPIRED", "QUOTED quote pinned to the superseded classification"
    bound = get_success_data(api.get_premium_quote(q1["id"], INSURER))
    assert bound["status"] == "BOUND", "BOUND quotes are untouched by the cascade"
    community = get_community(api, ctx["community"]["id"])
    assert community["bound_exposure_cents"] == 10000000


def _gate_c(api):
    """Community in CLASSIFICATION_REVIEW with a FINAL sheet and a property,
    but no classification yet."""
    ctx = setup_classification_review(api, name="Gate C")
    prop = create_property(
        api, ctx["community"]["id"], address="3 Birch St",
        distance_to_nearest_hydrant_ft=300, distance_to_nearest_station_road_miles=1.0,
        construction_type="FRAME", insured_value_cents=100000000,
    )
    return ctx, prop


def test_quote_create_rejected_without_effective_classification(api):
    """PRD §3.8: "The community must hold an `EFFECTIVE` classification —
    otherwise quoting is rejected with `ERR_NO_EFFECTIVE_CLASSIFICATION`
    (HTTP 422)". A merely PUBLISHED classification does not lift the gate.

    Design: Difficulty/cross_entity_state_dependency/quote_create_requires_effective_classification
    """
    ctx, prop = _gate_c(api)
    assert prop["applicable_class"] is None, "no rating position before any effective classification"
    payload = premium_quote_payload(prop["id"], coverage_amount_cents=1000000)
    resp1 = api.create_premium_quote(payload, INSURER)
    validate_error(resp1, ApiErrorId.ERR_NO_EFFECTIVE_CLASSIFICATION)
    publish_classification(api, ctx["cycle"]["id"], ctx["sheet"]["id"])
    resp2 = api.create_premium_quote(dict(payload), INSURER)
    validate_error(resp2, ApiErrorId.ERR_NO_EFFECTIVE_CLASSIFICATION)
    quotes = get_success_data(api.list_premium_quotes(INSURER, params={"property_id": prop["id"]}))
    assert quotes == []


def test_quote_create_pins_classification_after_activation(api):
    """PRD §3.8: "the quote pins that classification as `classification_id`
    together with the property's current applicable modifier" and "both
    fields remain null while no effective classification exists" — activation
    unlocks quoting and the property's applicable_class becomes 10.

    Design: Difficulty/cross_entity_state_dependency/quote_create_requires_effective_classification
    """
    ctx, prop = _gate_c(api)
    classification = publish_classification(api, ctx["cycle"]["id"], ctx["sheet"]["id"])
    activate_classification(api, classification["id"])
    quote = create_quote(api, prop["id"], coverage_amount_cents=1000000)
    assert quote["classification_id"] == classification["id"], "the quote pins the EFFECTIVE classification"
    assert quote["status"] == "QUOTED"
    refreshed_prop = get_success_data(api.get_property_risk_profile(prop["id"], INSURER))
    assert refreshed_prop["applicable_class"] == 10


def test_classification_premium_modifier_stored_class_10(api):
    """PRD §3.7: "The premium modifier is keyed on the base class: class 1
    maps to 0.65, class 2 to 0.70, class 3 to 0.75, class 4 to 0.80, class 5
    to 0.85, class 6 to 0.90, class 7 to 0.95, class 8 to 1.00, class 9 to
    1.10, and class 10 to 1.25."

    Design: Corner/calculations/classification_premium_modifier_stored_class_10
    """
    ctx = setup_classification_review(api, name="Modville")
    classification = publish_classification(api, ctx["cycle"]["id"], ctx["sheet"]["id"])
    assert classification["base_class"] == 10
    assert classification["split_class_beyond_hydrant"] == 10
    assert classification["premium_modifier"] == pytest.approx(1.25)
    assert classification["status"] == "PUBLISHED"
    assert classification["published_by"] == "registrar-1"


def test_classification_activate_twice_returns_invalid_state(api):
    """PRD §3.7: "Activation requires the classification to be `PUBLISHED` —
    anything else is `ERR_CLASSIFICATION_INVALID_STATE`."

    Design: Corner/errors/classification_activate_twice_returns_invalid_state
    """
    ctx = setup_classified_community(api, name="TwiceAct")
    resp = api.activate_classification(
        ctx["classification"]["id"], {"effective_from": "2026-09-02"}, REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_CLASSIFICATION_INVALID_STATE)
