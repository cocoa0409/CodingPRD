"""The revision loop, the four independent license axes, and the two
multi-level cascades."""

from test_helpers import (
    BSD_HEADERS,
    FDM_HEADERS,
    assert_capacity_bands,
    assert_instant,
    assert_integer,
    assert_money,
    fixtures,
    get_success_data,
    make_owner_headers,
)
from test_helpers.constants import (
    DUE_DATE_EXTERIOR,
    DUE_DATE_GUESTROOM,
    DUE_DATE_LIFE_SAFETY,
)


# ─── The revision loop resets both review axes (PRD §3.3) ────────────

def _revision_cycle_world(api):
    """One application taken twice around the revision loop, with a full
    financial review and impact study inside each pass."""
    world = fixtures.setup_reviewable_application(api)
    application_id = world["application_id"]
    owner_headers = make_owner_headers(world["owner_id"])

    # First pass: both axes advanced, then a revision is requested.
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    fixtures.run_financial_review(api, application_id, "PORTFOLIO_ADJUSTED")
    fixtures.run_impact_analysis(api, application_id)
    fixtures.finalize_impact(api, application_id)
    get_success_data(
        api.request_application_revision(
            application_id,
            {"revision_notes": "Franchise disclosure receipt and updated STR report required."},
            FDM_HEADERS,
        )
    )

    # Second pass: the owner resubmits, both axes are advanced again, and a
    # second revision is requested and answered.
    get_success_data(
        api.resubmit_application(
            application_id,
            {"revision_response": "FDD receipt attached; STR report refreshed."},
            owner_headers,
        )
    )
    fixtures.run_financial_review(api, application_id, "STANDALONE")
    fixtures.run_impact_analysis(api, application_id)
    get_success_data(
        api.request_application_revision(
            application_id,
            {"revision_notes": "Second pass: environmental report still missing."},
            FDM_HEADERS,
        )
    )
    world["application"] = get_success_data(
        api.resubmit_application(
            application_id,
            {"revision_response": "Phase I environmental report attached."},
            owner_headers,
        )
    )
    return world


def test_second_revision_round_returns_the_application_to_under_review_at_round_two(api):
    """PRD §3.3: requesting a revision moves the application to
    REVISION_REQUESTED and a resubmission returns it to UNDER_REVIEW, counting
    the pass in revision_round, so a second trip around the loop leaves the
    application under review at round two rather than in any terminal state.

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_resets_both_review_axes_twice
    """
    world = _revision_cycle_world(api)
    application = world["application"]

    assert application["status"] == "UNDER_REVIEW"
    assert_integer(application["revision_round"], 2, "revision_round")
    assert application["revision_response"] == "Phase I environmental report attached."

    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["open_application_count"], 1, "open_application_count")


def test_second_revision_round_clears_both_review_axes_and_every_derived_field(api):
    """PRD §3.3: a resubmission resets both review axes to NOT_STARTED and
    nulls every field either axis derived - the capacity basis, score and band
    snapshot, the recorded reviewer, the preliminary and final impact scores,
    the claim window and the verdict - so no stale derivation survives the
    loop.

    Design: Difficulty/non_linear_state_machine/application_revision_cycle_resets_both_review_axes_twice
    """
    world = _revision_cycle_world(api)
    application = world["application"]

    assert application["financial_review_status"] == "NOT_STARTED"
    assert application["impact_study_status"] == "NOT_STARTED"
    for field in (
        "capacity_basis",
        "capacity_score_at_review",
        "capacity_band_at_review",
        "financial_reviewer_user_id",
        "preliminary_impact_score",
        "claim_window_closes_at",
        "final_impact_score",
        "encroachment_verdict",
    ):
        assert application[field] is None, (
            f"a resubmission must null {field}, got {application[field]!r}"
        )


# ─── Four license axes advance independently (PRD §2.8, §3.6) ─────────

def test_opening_the_hotel_leaves_all_four_onboarding_axes_at_their_summits(api):
    """PRD §3.6: training, systems and channel are three independent ladders
    and the opening check reads their summits; the compliance and
    de-identification axes are untouched by the opening, so an opened license
    reads COMPLETED, VALIDATED, CONNECTED, COMPLIANT and NOT_REQUIRED at once,
    with opened_at and executed_at each stamped from the clock as it stood.

    Design: Difficulty/non_linear_state_machine/license_agreement_four_axes_advance_independently_to_open
    """
    world = fixtures.setup_open_agreement(api)
    agreement = world["agreement"]

    assert agreement["status"] == "OPEN"
    assert_instant(agreement["opened_at"], "2026-11-01T00:00:00.000Z", "opened_at")
    assert agreement["training_status"] == "COMPLETED"
    assert agreement["systems_status"] == "VALIDATED"
    assert agreement["channel_status"] == "CONNECTED"
    assert agreement["compliance_status"] == "COMPLIANT"
    assert agreement["de_identification_status"] == "NOT_REQUIRED"
    assert_instant(agreement["executed_at"], "2026-09-10T00:00:00.000Z", "executed_at")


def test_opening_the_hotel_does_not_force_the_improvement_plan_to_completed(api):
    """PRD §3.6 and §3.7: the opening gate only requires that the life-safety
    and CRITICAL scope lines be verified.  The plan axis is independent of the
    license status axis, so the two ordinary lines stay PENDING and the plan
    stays IN_PROGRESS after the hotel opens.

    Design: Difficulty/non_linear_state_machine/license_agreement_four_axes_advance_independently_to_open
    """
    world = fixtures.setup_open_agreement(api)

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert plan["status"] == "IN_PROGRESS", (
        f"the opening must not complete a plan with open lines, got {plan['status']}"
    )

    for category in ("GUESTROOM", "EXTERIOR"):
        item_id = world["items_by_category"][category]["id"]
        rows, _ = _find_item(api, world["plan_id"], item_id)
        assert rows["status"] == "PENDING", (
            f"the {category} line must still be PENDING, got {rows['status']}"
        )


def _find_item(api, plan_id, item_id):
    """Read one scope line back out of its plan's item collection."""
    from test_helpers import validate_paginated_list

    rows, meta = validate_paginated_list(
        api.list_pip_items(plan_id, BSD_HEADERS, {"limit": 100})
    )
    matches = [row for row in rows if row["id"] == item_id]
    assert matches, f"scope line {item_id} is missing from the plan's collection"
    return matches[0], meta


# ─── The compliance sweep cascades four levels down (PRD §3.7) ────────

def _swept_world(api):
    """An accepted three-line plan with a REFINANCE consent request pending,
    swept on the day after the life-safety line's 2026-11-19 due date."""
    world = fixtures.setup_accepted_plan(api)
    fixtures.set_clock(api, "2026-10-10T00:00:00Z")
    fixtures.file_refinance_request(api, world)
    return fixtures.setup_defaulted_plan(api, world, sweep_clock="2026-11-20T00:00:00Z")


def test_compliance_sweep_carries_one_overdue_line_up_to_the_default_notice(api):
    """PRD §3.7: a scope line whose due date has passed moves to OVERDUE with
    overdue_at stamped, a CRITICAL or LIFE_SAFETY escalation defaults the plan,
    and the license's compliance axis moves to DEFAULT_NOTICE with the notice
    instant, a thirty-day cure deadline and the transfer block raised - while
    the license status axis itself is untouched.

    Design: Difficulty/transitive_cascade/compliance_sweep_cascades_item_to_plan_to_agreement_to_transfer_request
    """
    world = _swept_world(api)
    life_safety_id = world["items_by_category"]["LIFE_SAFETY"]["id"]
    item, _ = _find_item(api, world["plan_id"], life_safety_id)

    assert item["status"] == "OVERDUE"
    assert_instant(item["due_date"], DUE_DATE_LIFE_SAFETY, "due_date")
    assert_instant(item["overdue_at"], "2026-11-20T00:00:00.000Z", "overdue_at")

    plan = world["plan"]
    assert plan["status"] == "DEFAULTED"
    assert_integer(plan["items_overdue_count"], 1, "items_overdue_count")
    assert_integer(plan["items_pending_count"], 2, "items_pending_count")

    agreement = world["agreement"]
    assert agreement["compliance_status"] == "DEFAULT_NOTICE"
    assert_instant(
        agreement["default_notice_issued_at"], "2026-11-20T00:00:00.000Z", "default_notice_issued_at"
    )
    assert_instant(agreement["pip_cure_deadline"], "2026-12-20T00:00:00.000Z", "pip_cure_deadline")
    assert agreement["transfer_consent_blocked"] is True
    assert agreement["status"] == "EXECUTED", (
        f"the compliance cascade must not move the status axis, got {agreement['status']}"
    )


def test_compliance_sweep_auto_refuses_the_pending_consent_request_it_reaches(api):
    """PRD §3.7: the escalation reaches four levels down - line, plan, license
    and then every SUBMITTED consent request, each auto-refused with reason
    DEFAULT_NOTICE, decided_at stamped and decision_user_id left null because
    no human decided it, with the fee frozen at filing.  Lines that are not
    yet due keep their own deadlines and stay PENDING.

    Design: Difficulty/transitive_cascade/compliance_sweep_cascades_item_to_plan_to_agreement_to_transfer_request
    """
    world = _swept_world(api)
    request = get_success_data(
        api.get_transfer_request(world["transfer_request_id"], FDM_HEADERS)
    )

    assert request["status"] == "REFUSED"
    assert request["refusal_reason"] == "DEFAULT_NOTICE"
    assert_instant(request["decided_at"], "2026-11-20T00:00:00.000Z", "decided_at")
    assert request["decision_user_id"] is None, (
        f"an automatic refusal has no deciding user, got {request['decision_user_id']!r}"
    )
    assert_money(request["total_consent_fee"], 15_000.00, "total_consent_fee")

    for category, due_date in (
        ("GUESTROOM", DUE_DATE_GUESTROOM),
        ("EXTERIOR", DUE_DATE_EXTERIOR),
    ):
        item, _ = _find_item(api, world["plan_id"], world["items_by_category"][category]["id"])
        assert item["status"] == "PENDING"
        assert_instant(item["due_date"], due_date, f"{category} due_date")


# ─── A profile change reaches the application's review axis (PRD §3.2) ─

def _restated_profile_world(api):
    """An owner reviewed on the STANDALONE basis at 65.13 ADEQUATE, whose
    financial profile is then restated far downward."""
    world = fixtures.setup_reviewable_application(
        api,
        owner_overrides={
            "legal_name": "Token Ridge Lodging LLC",
            "contact_email": "cfo@tokenridge.example",
            "liquid_assets_amount": 3_200_000.00,
            "net_worth_amount": 9_000_000.00,
            "credit_score": 720,
            "existing_units_count": 1,
        },
        application_overrides={
            "property_name": "Token Ridge Inn",
            "market_code": "SEANE",
            "current_affiliation": "INDEPENDENT",
            "building_age_years": 12,
        },
    )
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    fixtures.run_financial_review(api, world["application_id"], "STANDALONE")
    fixtures.set_clock(api, "2026-08-20T00:00:00Z")
    world["owner"] = get_success_data(
        api.update_owner_financial_profile(
            world["owner_id"],
            {
                "liquid_assets_amount": 400_000.00,
                "net_worth_amount": 2_000_000.00,
                "credit_score": 620,
                "existing_units_count": 0,
            },
            FDM_HEADERS,
        )
    )
    return world


def test_restating_the_financial_profile_recomputes_both_capacity_variants(api):
    """PRD §3.2: a re-verification replaces all four inputs, advances
    financial_profile_revision by one and recomputes both variants from the new
    row; with no existing units the reserve deduction and the experience bonus
    both vanish, so the two variants coincide.

    Design: Difficulty/transitive_cascade/owner_profile_update_cascades_score_recompute_to_stale_financial_review
    """
    world = _restated_profile_world(api)
    owner = world["owner"]

    assert_money(owner["capacity_score_standalone"], 17.60, "capacity_score_standalone")
    assert_money(
        owner["capacity_score_portfolio_adjusted"], 17.60, "capacity_score_portfolio_adjusted"
    )
    assert owner["capacity_band_standalone"] == "INSUFFICIENT"
    assert owner["capacity_band_portfolio_adjusted"] == "INSUFFICIENT"
    assert_capacity_bands(owner)
    assert_integer(owner["financial_profile_revision"], 1, "financial_profile_revision")


def test_restating_the_financial_profile_stales_the_review_but_preserves_its_snapshot(api):
    """PRD §3.2: the recompute cascades to every application that is
    UNDER_REVIEW with a PASSED financial review, moving that axis to STALE
    while preserving the snapshot taken at review time - the score, the band
    and the basis - so the reviewer's record of what was relied on survives.

    Design: Difficulty/transitive_cascade/owner_profile_update_cascades_score_recompute_to_stale_financial_review
    """
    world = _restated_profile_world(api)
    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))

    assert application["financial_review_status"] == "STALE"
    assert_money(application["capacity_score_at_review"], 65.13, "capacity_score_at_review")
    assert application["capacity_band_at_review"] == "ADEQUATE"
    assert application["capacity_basis"] == "STANDALONE"
    assert application["status"] == "UNDER_REVIEW"
