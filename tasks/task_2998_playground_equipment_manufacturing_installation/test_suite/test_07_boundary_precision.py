"""Behaviour exactly on the inclusive boundaries the API declares.

Two boundaries are exercised here: the community-review turnout floor together
with the inclusive 60.0-percent approval comparison, and the emptiness boundary
of a quote's pricing scope, where a design holding exactly one DRAFT placement
prices as PROVISIONAL but has nothing at all for a FIRM quote to price.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_paginated_list,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ==========================================================================
# Community review: the 25-vote turnout floor and the inclusive 60.0 threshold
# ==========================================================================
def _setup_rendered_design() -> dict:
    """A RENDERED project whose single VALIDATED deck backs one ISSUED rendering."""
    scenario = fx.setup_single_placement_design(
        model_key="deck",
        placement_overrides={"color_choice": "SKY_BLUE", "x_start_cm": 700},
    )
    scenario["project"] = fx.get_project(scenario["project"]["id"])
    return scenario


def test_closing_a_review_one_vote_below_the_turnout_floor_is_refused():
    """A review carrying 24 ballots is one short of the floor and cannot be closed at all.

    PRD: "Turnout is checked first: the sum of `yes_votes` and `no_votes` must be at least 25, and a review closed on thinner participation is refused with `ERR_INSUFFICIENT_COMMUNITY_INPUT` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/community_approval_exactly_sixty_pct_approves_design
    """
    scenario = _setup_rendered_design()
    rendering_id = scenario["rendering"]["id"]
    project_id = scenario["project"]["id"]

    batch = validate_success(
        api_client.record_community_votes(
            rendering_id, f.community_votes_payload(yes_votes=12, no_votes=12), fx.CLIENT
        ),
        200,
    )
    a.assert_rendering(batch)
    assert batch["yes_votes"] == 12, f"expected 12, got {batch['yes_votes']}"
    assert batch["no_votes"] == 12, f"expected 12, got {batch['no_votes']}"
    assert batch["community_approval_pct"] == 50.0, (
        f"expected 50.0, got {batch['community_approval_pct']} on 12 yes of 24 ballots"
    )
    assert fx.get_project(project_id)["design_status"] == "COMMUNITY_REVIEW", (
        "recording a batch must move the project into COMMUNITY_REVIEW"
    )

    response = api_client.close_review(rendering_id, fx.CONSULTANT)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_COMMUNITY_INPUT.value, 422)

    rendering_after = fx.get_rendering(rendering_id)
    project_after = fx.get_project(project_id)
    assert rendering_after["status"] == "ISSUED", (
        f"expected ISSUED, got {rendering_after['status']} after the refused close"
    )
    assert project_after["design_status"] == "COMMUNITY_REVIEW", (
        f"expected COMMUNITY_REVIEW, got {project_after['design_status']} after the refused close"
    )
    assert project_after["revision_rounds"] == 0, (
        f"expected 0, got {project_after['revision_rounds']}; a refused close ends no round"
    )


def test_community_approval_pct_is_rounded_half_up_to_one_decimal_place():
    """Batches accumulate and 14 yes votes of 26 ballots read as exactly 53.8 percent.

    PRD: "Each batch supplies `yes_votes` and `no_votes`, and the values are **added to** the rendering's running `yes_votes` and `no_votes` rather than replacing them."
    PRD: "otherwise it is one hundred multiplied by the accumulated `yes_votes`, divided by the sum of `yes_votes` and `no_votes`, rounded half up to exactly one decimal place."

    Design: Difficulty/boundary_precision_check/community_approval_exactly_sixty_pct_approves_design
    """
    scenario = _setup_rendered_design()
    rendering_id = scenario["rendering"]["id"]

    validate_success(
        api_client.record_community_votes(
            rendering_id, f.community_votes_payload(yes_votes=12, no_votes=12), fx.CLIENT
        ),
        200,
    )
    second = validate_success(
        api_client.record_community_votes(
            rendering_id, f.community_votes_payload(yes_votes=2, no_votes=0), fx.CLIENT
        ),
        200,
    )

    assert second["yes_votes"] == 14, (
        f"expected 14, got {second['yes_votes']}; batches are added, not replaced"
    )
    assert second["no_votes"] == 12, (
        f"expected 12, got {second['no_votes']}; batches are added, not replaced"
    )
    assert second["community_approval_pct"] == 53.8, (
        f"expected 53.8, got {second['community_approval_pct']} for 14 yes of 26 ballots"
    )


def test_exactly_sixty_percent_approval_approves_the_design():
    """A round closed below threshold reopens the project, and the next round closing on exactly 60.0 percent approves it.

    PRD: "Once turnout clears, `community_approval_pct` selects the branch and never itself raises an error, and the comparison is **inclusive** — exactly 60.0 percent approves."
    PRD: "On the **revise branch**, where `community_approval_pct` is below 60.0, three further things happen beyond the status move: the rendering's `status` becomes `WITHDRAWN`, the project's `design_status` becomes `REVISION_REQUESTED` and its `revision_rounds` counter is incremented by one, and every `Quote` of the project still in `ISSUED` status is moved to `EXPIRED`."
    PRD: "On the **approve branch**, where `community_approval_pct` is greater than or equal to 60.0, the project's `design_status` moves `COMMUNITY_REVIEW → DESIGN_APPROVED` and the rendering is left in `ISSUED` status precisely so that it can go on to back a quote; `revision_rounds` is not touched, no quote is expired, and the rendering is not withdrawn."

    Design: Difficulty/boundary_precision_check/community_approval_exactly_sixty_pct_approves_design
    """
    scenario = _setup_rendered_design()
    project_id = scenario["project"]["id"]
    first_rendering_id = scenario["rendering"]["id"]

    fx.record_votes(first_rendering_id, 12, 12)
    below = validate_success(
        api_client.record_community_votes(
            first_rendering_id, f.community_votes_payload(yes_votes=2, no_votes=0), fx.CLIENT
        ),
        200,
    )
    assert below["community_approval_pct"] == 53.8, (
        f"expected 53.8, got {below['community_approval_pct']} before the revise branch"
    )

    revised_project = validate_success(
        api_client.close_review(first_rendering_id, fx.CONSULTANT), 200
    )
    a.assert_project(revised_project)
    assert revised_project["design_status"] == "REVISION_REQUESTED", (
        f"expected REVISION_REQUESTED, got {revised_project['design_status']} "
        "after closing below threshold"
    )
    assert revised_project["revision_rounds"] == 1, (
        f"expected 1, got {revised_project['revision_rounds']} after one revised round"
    )
    assert fx.get_rendering(first_rendering_id)["status"] == "WITHDRAWN", (
        "closing below threshold must withdraw the rendering"
    )

    second_rendering = validate_success(
        api_client.issue_rendering(
            project_id, f.rendering_payload(scenario["standard"]["id"]), fx.CONSULTANT
        ),
        201,
    )
    assert second_rendering["round_number"] == 2, (
        f"expected 2, got {second_rendering['round_number']} for the second round"
    )
    assert fx.get_rendering(first_rendering_id)["status"] == "WITHDRAWN", (
        "a withdrawn rendering is not displaced into SUPERSEDED by the next round"
    )

    on_threshold = validate_success(
        api_client.record_community_votes(
            second_rendering["id"], f.community_votes_payload(yes_votes=15, no_votes=10), fx.CLIENT
        ),
        200,
    )
    assert on_threshold["yes_votes"] + on_threshold["no_votes"] == 25, (
        "the second round must sit exactly on the turnout floor"
    )
    assert on_threshold["community_approval_pct"] == 60.0, (
        f"expected 60.0, got {on_threshold['community_approval_pct']} for 15 yes of 25 ballots"
    )

    approved_project = validate_success(
        api_client.close_review(second_rendering["id"], fx.CONSULTANT), 200
    )
    assert approved_project["design_status"] == "DESIGN_APPROVED", (
        f"expected DESIGN_APPROVED, got {approved_project['design_status']} "
        "for a review closed on exactly 60.0 percent"
    )
    assert approved_project["revision_rounds"] == 1, (
        f"expected 1, got {approved_project['revision_rounds']}; the approve branch "
        "must not touch the counter"
    )
    assert fx.get_rendering(second_rendering["id"])["status"] == "ISSUED", (
        "the approve branch leaves the rendering ISSUED so it can back a quote"
    )


# ==========================================================================
# One DRAFT placement: priceable as PROVISIONAL, empty scope as FIRM
# ==========================================================================
def _setup_draft_only_design() -> dict:
    """A RENDERED project whose only placement is a DRAFT SKY_BLUE deck.

    Nothing in the project is VALIDATED, so the FIRM input set is empty while the
    PROVISIONAL set holds exactly one unit.
    """
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Willow Field School"}
    )
    scenario["placement"] = fx.create_placement(
        scenario["area"]["id"],
        scenario["deck"]["id"],
        color_choice="SKY_BLUE",
        x_start_cm=700,
        quantity=1,
    )
    scenario["rendering"] = fx.issue_rendering(
        scenario["project"]["id"], scenario["standard"]["id"]
    )
    return scenario


def _quote_response(project_id: str, rendering_id: str, variant: str):
    """Fire a quote issuance of the given variant at the project's live version."""
    payload = f.quote_payload(
        project_id, rendering_id, fx.project_version(project_id), variant=variant
    )
    return api_client.create_quote(payload, fx.CONSULTANT)


def test_provisional_variant_prices_the_lone_draft_placement():
    """A PROVISIONAL quote includes the DRAFT placement and prices it with the non-default colour surcharge.

    PRD: "A `PROVISIONAL` quote includes placements in `DRAFT` *and* `VALIDATED`, because an early budgetary number is meant to price a design that is still being validated."
    PRD: "When the placement's `color_choice` differs from the first element of the model's `color_options`, the raw line is the base line increased by seven percent — that is, the base line multiplied by one plus seven hundredths."
    PRD: "`freight_cents` is a flat base of 48000 cents plus 1250 cents for every priced unit."

    Design: Difficulty/boundary_precision_check/firm_quote_with_empty_validated_placement_set_rejected
    """
    scenario = _setup_draft_only_design()
    assert scenario["placement"]["status"] == "DRAFT", (
        f"expected DRAFT, got {scenario['placement']['status']} for the only placement"
    )

    quote = validate_success(
        _quote_response(
            scenario["project"]["id"], scenario["rendering"]["id"], "PROVISIONAL"
        ),
        201,
    )
    a.assert_quote(quote)
    a.assert_freight(quote)
    a.assert_quote_arithmetic(quote)

    assert quote["variant"] == "PROVISIONAL", (
        f"expected PROVISIONAL, got {quote['variant']}"
    )
    assert quote["priced_unit_count"] == 1, (
        f"expected 1, got {quote['priced_unit_count']} priced units"
    )
    assert quote["subtotal_cents"] == 68855, (
        f"expected 68855, got {quote['subtotal_cents']} for the surcharged deck line"
    )
    assert quote["freight_cents"] == 49250, (
        f"expected 49250, got {quote['freight_cents']} for one priced unit"
    )
    assert quote["discount_cents"] == 0, (
        f"expected 0, got {quote['discount_cents']} below the first discount tier"
    )
    assert quote["total_cents"] == 118105, (
        f"expected 118105, got {quote['total_cents']}"
    )


def test_firm_variant_rejects_the_empty_validated_placement_set():
    """A FIRM quote over a design holding only a DRAFT placement has nothing to price.

    PRD: "A `FIRM` quote includes only placements in `VALIDATED`."
    PRD: "If the resulting set is empty there is nothing to price, and the request is refused with `ERR_QUOTE_EMPTY_SCOPE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/firm_quote_with_empty_validated_placement_set_rejected
    """
    scenario = _setup_draft_only_design()
    project_id = scenario["project"]["id"]

    response = _quote_response(project_id, scenario["rendering"]["id"], "FIRM")
    validate_error(response, ApiErrorId.ERR_QUOTE_EMPTY_SCOPE.value, 422)

    assert_paginated_list(
        api_client.list_quotes(fx.CONSULTANT, {"project_id": project_id}),
        expected_total=0,
    )
    placement_after = fx.get_placement(scenario["placement"]["id"])
    assert placement_after["status"] == "DRAFT", (
        f"expected DRAFT, got {placement_after['status']} after the rejected issuance"
    )


def test_the_same_design_prices_provisional_and_then_refuses_firm():
    """On one unchanged design the PROVISIONAL variant issues and the FIRM variant is refused, leaving a single quote row.

    PRD: "A `PROVISIONAL` quote includes placements in `DRAFT` *and* `VALIDATED`, because an early budgetary number is meant to price a design that is still being validated."
    PRD: "If the resulting set is empty there is nothing to price, and the request is refused with `ERR_QUOTE_EMPTY_SCOPE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/firm_quote_with_empty_validated_placement_set_rejected
    """
    scenario = _setup_draft_only_design()
    project_id = scenario["project"]["id"]
    rendering_id = scenario["rendering"]["id"]

    provisional = validate_success(
        _quote_response(project_id, rendering_id, "PROVISIONAL"), 201
    )
    assert provisional["total_cents"] == 118105, (
        f"expected 118105, got {provisional['total_cents']}"
    )

    validate_error(
        _quote_response(project_id, rendering_id, "FIRM"),
        ApiErrorId.ERR_QUOTE_EMPTY_SCOPE.value,
        422,
    )

    quotes, _meta = assert_paginated_list(
        api_client.list_quotes(fx.CONSULTANT, {"project_id": project_id}),
        expected_total=1,
    )
    assert quotes[0]["variant"] == "PROVISIONAL", (
        f"expected PROVISIONAL, got {quotes[0]['variant']} for the only surviving quote"
    )
    assert quotes[0]["id"] == provisional["id"], (
        "the refused FIRM issuance must not have created a second quote"
    )
    assert fx.get_placement(scenario["placement"]["id"])["status"] == "DRAFT", (
        "neither issuance may promote the DRAFT placement"
    )
