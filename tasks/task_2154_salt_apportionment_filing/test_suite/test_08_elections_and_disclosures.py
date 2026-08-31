"""Reporting elections, the filing calendar and voluntary disclosure agreements."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_money,
    create_election,
    create_legal_entity,
    create_registration,
    read_election,
    read_group,
    read_legal_entity,
    read_registration,
    read_vda_agreement,
    setup_bare_registration,
    setup_economic_nexus_registration,
    setup_filed_filing,
    setup_group_with_members,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["tax_manager_headers"]
SA = TEST_USERS["state_analyst_headers"]
AUD = TEST_USERS["auditor_headers"]


# ─── Election periods are closed integer-year intervals ───────────────────────

def _registration_with_first_election():
    ctx = setup_bare_registration(group_overrides={
        "name": "Interval Industries", "everywhere_sales": 6000000,
        "everywhere_property": 1000000, "everywhere_payroll": 900000,
    })
    ctx["election_a"] = create_election(
        ctx["registration_id"], election_basis="COMBINED_UNITARY",
        effective_tax_year=2024, binding_years=3,
    )
    return ctx


def test_election_sharing_a_single_year_is_rejected_as_an_overlap(api):
    """PRD 3.3: "An election occupies a closed interval of integer tax years on its registration, and two elections on the same registration may never occupy overlapping intervals. The proposed interval runs from `effective_tax_year` through `effective_tax_year` plus `binding_years` less one; if it intersects the occupied interval of any other election on that registration, the request is rejected with `ERR_ELECTION_PERIOD_OVERLAP`."
    PRD 3.3: "The registration the election binds is recorded as its `registration_id`, and the service computes `expires_after_tax_year` as the effective year plus the binding count, less one; a five-year election effective in 2024 therefore expires after 2028."

    Design: Difficulty/resource_temporal_overlap/election_binding_years_closed_interval_overlap
    """
    ctx = _registration_with_first_election()
    assert ctx["election_a"]["expires_after_tax_year"] == 2026

    response = api.create_election(ctx["registration_id"], {
        "election_basis": "SEPARATE_ENTITY", "effective_tax_year": 2026,
        "binding_years": 3,
    }, TM)

    validate_error(response, ApiErrorId.ERR_ELECTION_PERIOD_OVERLAP.value)
    assert response.status_code == 409
    rows, meta = validate_paginated(api.list_registration_elections(
        ctx["registration_id"], AUD, {"limit": 10, "offset": 0}
    ))
    assert meta["total_count"] == 1, "The rejected election must not be written"


def test_election_beginning_the_year_after_the_last_one_is_accepted(api):
    """PRD 3.3: "An election occupies a closed interval of integer tax years on its registration, and two elections on the same registration may never occupy overlapping intervals. The proposed interval runs from `effective_tax_year` through `effective_tax_year` plus `binding_years` less one; if it intersects the occupied interval of any other election on that registration, the request is rejected with `ERR_ELECTION_PERIOD_OVERLAP`."
    PRD 3.3: "A new election starts in `ELECTED` with `reinstatement_count` at 0, a null `revocation_tax_year` and a null `reason`."

    Design: Difficulty/resource_temporal_overlap/election_binding_years_closed_interval_overlap
    """
    ctx = _registration_with_first_election()
    validate_error(
        api.create_election(ctx["registration_id"], {
            "election_basis": "SEPARATE_ENTITY", "effective_tax_year": 2026,
            "binding_years": 3,
        }, TM),
        ApiErrorId.ERR_ELECTION_PERIOD_OVERLAP.value,
    )

    adjacent = validate_success(api.create_election(ctx["registration_id"], {
        "election_basis": "SEPARATE_ENTITY", "effective_tax_year": 2027,
        "binding_years": 3,
    }, TM), 201)

    assert adjacent["effective_tax_year"] == 2027
    assert adjacent["expires_after_tax_year"] == 2029
    assert adjacent["status"] == "ELECTED"
    _, meta = validate_paginated(api.list_registration_elections(
        ctx["registration_id"], AUD, {"limit": 10, "offset": 0}
    ))
    assert meta["total_count"] == 2, "Adjacency is not overlap"


def test_calendar_roll_expires_only_the_lapsed_election(api):
    """PRD 3.2: "Rolling the filing calendar is the last piece of registration maintenance. A `TaxManager` supplies a `through_tax_year`; the registration's `calendar_rolled_through_year` is set to that value, every `ELECTED` election on the registration whose `expires_after_tax_year` is strictly less than `through_tax_year` moves to `EXPIRED` with its own `version` advanced, and the registration's `version` advances by 1."

    Design: Corner/state_machines/roll_filing_calendar_expires_lapsed_election
    """
    ctx = setup_bare_registration(group_overrides={"name": "Calendar Roll Group"})
    election_a = create_election(
        ctx["registration_id"], election_basis="COMBINED_UNITARY",
        effective_tax_year=2023, binding_years=4,
    )
    election_b = create_election(
        ctx["registration_id"], election_basis="SEPARATE_ENTITY",
        effective_tax_year=2027, binding_years=3,
    )

    rolled = validate_success(api.roll_filing_calendar(
        ctx["registration_id"], {"through_tax_year": 2027}, TM
    ))

    assert rolled["calendar_rolled_through_year"] == 2027
    lapsed = read_election(election_a["id"])
    assert lapsed["status"] == "EXPIRED"
    assert lapsed["expires_after_tax_year"] == 2026
    still_live = read_election(election_b["id"])
    assert still_live["status"] == "ELECTED"
    assert still_live["expires_after_tax_year"] == 2029


def test_revocation_inside_the_binding_period_is_refused(api):
    """PRD 3.3: "Beyond that, the revocation year must be later than the election's `expires_after_tax_year`, *unless* the registration's `state_permits_early_revocation` is true; a revocation year that falls inside the binding period in a state that does not permit early revocation is rejected with `ERR_BINDING_PERIOD_ACTIVE`."

    Design: Corner/validations/binding_period_active_blocks_early_revocation
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "Binding Group"},
        registration_overrides={"state_permits_early_revocation": False},
    )
    election = create_election(
        ctx["registration_id"], election_basis="COMBINED_UNITARY",
        effective_tax_year=2024, binding_years=5,
    )

    response = api.revoke_election(
        election["id"], {"revocation_tax_year": 2026, "reason": "early exit"}, TM
    )

    validate_error(response, ApiErrorId.ERR_BINDING_PERIOD_ACTIVE.value)
    assert response.status_code == 422
    reread = read_election(election["id"])
    assert reread["status"] == "ELECTED"
    assert reread["revocation_tax_year"] is None
    assert reread["expires_after_tax_year"] == 2028


def test_return_referencing_an_election_that_ended_earlier_is_rejected(api):
    """PRD 3.4: "A supplied `election_id` must belong to the same registration, must still be `ELECTED`, and must actually cover the return's year — that is, the return's `tax_year` must fall at or after the election's `effective_tax_year` and at or before its `expires_after_tax_year`. An election that fails any of those three tests is rejected with `ERR_ELECTION_NOT_GOVERNING`."

    Design: Corner/validations/election_not_governing_filing_tax_year_returns_error
    """
    ctx = setup_bare_registration(group_overrides={"name": "Governing Group"})
    election = create_election(
        ctx["registration_id"], election_basis="COMBINED_UNITARY",
        effective_tax_year=2024, binding_years=2,
    )
    assert election["expires_after_tax_year"] == 2025

    response = api.create_filing(ctx["registration_id"], {
        "tax_year": 2026, "filing_basis": "COMBINED_UNITARY",
        "federal_taxable_income": 1000000, "election_id": election["id"],
    }, SA)

    validate_error(response, ApiErrorId.ERR_ELECTION_NOT_GOVERNING.value)
    rows, _ = validate_paginated(api.list_filings(AUD, {
        "registration_id": ctx["registration_id"], "limit": 10, "offset": 0,
    }))
    assert rows == [], "A rejected return create must persist nothing"


def test_reinstating_an_already_elected_election_is_refused(api):
    """PRD 3.3: "Election status is cyclic rather than terminal. An election in `REVOKED` may be re-elected over a fresh binding period, and may be revoked and re-elected any number of times."
    PRD 2.11: "10. The election's `status` is a legal source state (`ERR_INVALID_ELECTION_STATE`)."

    Design: Corner/endpoints/reinstate_on_elected_election_returns_invalid_election_state
    """
    ctx = setup_bare_registration(group_overrides={"name": "Reinstate Group"})
    election = create_election(
        ctx["registration_id"], election_basis="COMBINED_UNITARY",
        effective_tax_year=2024, binding_years=3,
    )

    response = api.reinstate_election(
        election["id"], {"effective_tax_year": 2027, "binding_years": 2}, TM
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ELECTION_STATE.value)
    assert response.status_code == 409
    reread = read_election(election["id"])
    assert reread["status"] == "ELECTED"
    assert reread["effective_tax_year"] == 2024
    assert reread["reinstatement_count"] == 0


# ─── Voluntary disclosure windows ─────────────────────────────────────────────

def _disclosure_scenario():
    """One member entity holding disclosures in two different states."""
    ctx = setup_group_with_members(
        group_overrides={
            "name": "Disclosure Group", "everywhere_sales": 9000000,
            "everywhere_property": 2000000, "everywhere_payroll": 1200000,
        },
        include_member_b=False,
    )
    member = create_legal_entity(
        ctx["group_id"], name="Meridian Services", incorporation_state_code="NV",
    )
    reg_ca = create_registration(
        ctx["group_id"], state_code="CA", factor_formula="SINGLE_SALES_FACTOR",
        tax_rate=0.0884, throwback_rule="NONE", service_sourcing_rule="MARKET_BASED",
    )
    reg_ny = create_registration(
        ctx["group_id"], state_code="NY", factor_formula="SINGLE_SALES_FACTOR",
        tax_rate=0.065, throwback_rule="NONE", service_sourcing_rule="MARKET_BASED",
    )
    ctx["le_id"] = member["id"]
    ctx["reg_ca_id"] = reg_ca["id"]
    ctx["reg_ny_id"] = reg_ny["id"]
    return ctx


def test_disclosure_inside_the_cooling_buffer_is_rejected(api):
    """PRD 3.9: "Disclosure windows are exclusive per member entity, and they are fenced by a two-year cooling period on each side. The proposed window — running from the first day of `lookback_start_year` up to, but not including, the first day of the year after `lookback_end_year` — is widened by 24 months at each end, and that widened window must not intersect the *un-widened* window of any other disclosure for the same `legal_entity_id` whose `status` is `DRAFT`, `SUBMITTED` or `EXECUTED`. An intersection is rejected with `ERR_VDA_WINDOW_OVERLAP`."
    PRD 3.9: "Under `LOOKBACK_LIMITED` it is the `estimated_exposure_tax` pro-rated to the negotiated window — multiplied by the effective lookback years and divided by seven — rounded half up to 2 decimal places, and the `waived_penalty_amount` is a quarter of that pro-rated figure, again rounded half up to 2 decimal places."

    Design: Difficulty/resource_temporal_overlap/vda_lookback_window_half_open_with_cooling_buffer
    """
    ctx = _disclosure_scenario()

    first = validate_success(api.create_vda_agreement(ctx["reg_ca_id"], {
        "legal_entity_id": ctx["le_id"], "anchor_tax_year": 2021,
        "lookback_years": 3, "exposure_variant": "LOOKBACK_LIMITED",
        "estimated_exposure_tax": 210000.00,
    }, TM), 201)
    assert first["lookback_start_year"] == 2019
    assert first["lookback_end_year"] == 2021
    assert_money(first["computed_exposure_tax"], 90000.00, "computed_exposure_tax")
    assert_money(first["waived_penalty_amount"], 22500.00, "waived_penalty_amount")

    response = api.create_vda_agreement(ctx["reg_ny_id"], {
        "legal_entity_id": ctx["le_id"], "anchor_tax_year": 2025,
        "lookback_years": 3, "exposure_variant": "LOOKBACK_LIMITED",
        "estimated_exposure_tax": 210000.00,
    }, TM)

    validate_error(response, ApiErrorId.ERR_VDA_WINDOW_OVERLAP.value)
    assert response.status_code == 409


def test_disclosure_clear_of_the_cooling_buffer_is_accepted(api):
    """PRD 3.9: "Disclosure windows are exclusive per member entity, and they are fenced by a two-year cooling period on each side. The proposed window — running from the first day of `lookback_start_year` up to, but not including, the first day of the year after `lookback_end_year` — is widened by 24 months at each end, and that widened window must not intersect the *un-widened* window of any other disclosure for the same `legal_entity_id` whose `status` is `DRAFT`, `SUBMITTED` or `EXECUTED`. An intersection is rejected with `ERR_VDA_WINDOW_OVERLAP`."
    PRD 3.9: "The `lookback_end_year` always equals the `anchor_tax_year`, and the `lookback_start_year` is the anchor year less the effective lookback years, plus one — so a four-year window anchored on 2024 runs from 2021 through 2024 inclusive."

    Design: Difficulty/resource_temporal_overlap/vda_lookback_window_half_open_with_cooling_buffer
    """
    ctx = _disclosure_scenario()
    validate_success(api.create_vda_agreement(ctx["reg_ca_id"], {
        "legal_entity_id": ctx["le_id"], "anchor_tax_year": 2021,
        "lookback_years": 3, "exposure_variant": "LOOKBACK_LIMITED",
        "estimated_exposure_tax": 210000.00,
    }, TM), 201)

    accepted = validate_success(api.create_vda_agreement(ctx["reg_ny_id"], {
        "legal_entity_id": ctx["le_id"], "anchor_tax_year": 2027,
        "lookback_years": 1, "exposure_variant": "LOOKBACK_LIMITED",
        "estimated_exposure_tax": 210000.00,
    }, TM), 201)

    assert accepted["lookback_start_year"] == 2027
    assert accepted["lookback_end_year"] == 2027
    assert accepted["status"] == "DRAFT"

    _, meta = validate_paginated(api.list_vda_agreements(AUD, {
        "legal_entity_id": ctx["le_id"], "limit": 10, "offset": 0,
    }))
    assert meta["total_count"] == 2


def test_lookback_beyond_four_years_is_rejected_for_the_limited_variant(api):
    """PRD 3.9: "Under `LOOKBACK_LIMITED` the `effective_lookback_years` equals the submitted `lookback_years`, and that submitted figure may not exceed four years — a longer request is rejected with `ERR_VDA_EXPOSURE_MISMATCH`."

    Design: Corner/validations/vda_lookback_over_maximum_returns_exposure_mismatch
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "VDA Max Group"}, include_member=True,
    )

    response = api.create_vda_agreement(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "anchor_tax_year": 2024,
        "lookback_years": 5, "exposure_variant": "LOOKBACK_LIMITED",
        "estimated_exposure_tax": 210000.00,
    }, TM)

    validate_error(response, ApiErrorId.ERR_VDA_EXPOSURE_MISMATCH.value)
    assert response.status_code == 422
    rows, _ = validate_paginated(api.list_vda_agreements(AUD, {
        "registration_id": ctx["registration_id"], "limit": 10, "offset": 0,
    }))
    assert rows == [], "A rejected disclosure draft must persist nothing"


def test_executing_a_disclosure_that_was_never_submitted_is_refused(api):
    """PRD 3.9: "The disclosure lifecycle is short. Submitting moves it `DRAFT → SUBMITTED` and advances its `version`."
    PRD 3.9: "Execution is the consequential step. A `TaxManager` executes a `SUBMITTED` disclosure, optionally supplying a `negotiated_tax` figure agreed with the state and a `negotiated_interest` figure; when `negotiated_tax` is not supplied, the `computed_exposure_tax` stands in its place."
    PRD 2.11: "11. The disclosure's `status` is a legal source state (`ERR_INVALID_VDA_STATE`)."

    Design: Corner/state_machines/vda_execute_from_draft_returns_invalid_vda_state
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "VDA State Group"}, include_member=True,
    )
    disclosure = validate_success(api.create_vda_agreement(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "anchor_tax_year": 2024,
        "lookback_years": 3, "exposure_variant": "LOOKBACK_LIMITED",
        "estimated_exposure_tax": 210000.00,
    }, TM), 201)

    response = api.execute_vda_agreement(disclosure["id"], {
        "negotiated_tax": 90000.00, "negotiated_interest": 5000.00,
    }, TM)

    validate_error(response, ApiErrorId.ERR_INVALID_VDA_STATE.value)
    assert response.status_code == 409
    reread = read_vda_agreement(disclosure["id"])
    assert reread["status"] == "DRAFT"
    assert reread["executed_on_date"] is None
    assert read_registration(ctx["registration_id"])["nexus_status"] == "NONE"


def test_executing_a_disclosure_converts_the_state_to_voluntary_compliance(api):
    """PRD 3.9: "Under `FULL_EXPOSURE` the `effective_lookback_years` is forced to seven regardless of what `lookback_years` was submitted."
    PRD 3.9: "Under `FULL_EXPOSURE` the `computed_exposure_tax` is simply the `estimated_exposure_tax` rounded to 2 decimal places, and the `waived_penalty_amount` is 0.00: coming forward for everything buys no penalty relief under this regime."
    PRD 3.9: "On success the disclosure moves `SUBMITTED → EXECUTED`, its `executed_on_date` is stamped from the logical clock, and its `shield_expires_at` is set to that instant advanced by 24 months. The disclosing member's `vda_shield_until` is set to the same instant — a two-year period during which the member's past exposure in that state is settled."
    PRD 3.9: "A three-link cascade then reshapes the registration and the group: the first link sets the registration's `nexus_status` to `VOLUNTARY` (from `NONE` or from `ECONOMIC`) and, when its `registration_status` is `REGISTRATION_REQUIRED`, moves that axis to `REGISTERED` with `state_account_number` set to the literal prefix `VDA-` followed by the agreement's own `id` and `registered_on_date` stamped from the logical clock; the second link, caused by the first, decrements the group's `open_registration_obligations` by 1; and the third link, caused by the second, re-derives the group's `compliance_posture`."

    Design: Corner/state_machines/vda_execution_cascades_to_registration_and_group
    """
    ctx = setup_economic_nexus_registration(
        group_overrides={"name": "VDA Cascade Group", "everywhere_sales": 10000000,
                         "everywhere_property": 4000000, "everywhere_payroll": 2000000},
    )
    assert ctx["registration"]["nexus_status"] == "ECONOMIC"
    assert ctx["registration"]["registration_status"] == "REGISTRATION_REQUIRED"
    assert read_group(ctx["group_id"])["compliance_posture"] == "EXPOSED"

    disclosure = validate_success(api.create_vda_agreement(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "anchor_tax_year": 2024,
        "lookback_years": 3, "exposure_variant": "FULL_EXPOSURE",
        "estimated_exposure_tax": 210000.00,
    }, TM), 201)
    validate_success(api.submit_vda_agreement(disclosure["id"], {}, TM))

    executed = validate_success(api.execute_vda_agreement(disclosure["id"], {
        "negotiated_tax": 210000.00, "negotiated_interest": 12000.00,
    }, TM))

    assert executed["status"] == "EXECUTED"
    assert executed["executed_on_date"].startswith("2026-08-01T00:00:00")
    assert executed["effective_lookback_years"] == 7
    assert executed["lookback_start_year"] == 2018
    assert executed["lookback_end_year"] == 2024
    assert_money(executed["computed_exposure_tax"], 210000.00, "computed_exposure_tax")
    assert_money(executed["waived_penalty_amount"], 0.00, "waived_penalty_amount")
    assert_money(executed["settlement_total"], 222000.00, "settlement_total")
    assert executed["shield_expires_at"].startswith("2028-08-01T00:00:00")

    assert read_legal_entity(ctx["le_a_id"])["vda_shield_until"].startswith(
        "2028-08-01T00:00:00"
    )
    registration = read_registration(ctx["registration_id"])
    assert registration["nexus_status"] == "VOLUNTARY"
    assert registration["registration_status"] == "REGISTERED"
    group = read_group(ctx["group_id"])
    assert group["open_registration_obligations"] == 0
    assert group["compliance_posture"] == "COMPLIANT"


def test_disclosure_covering_an_already_filed_year_cannot_execute(api):
    """PRD 3.9: "Execution is refused when the disclosure's window covers ground the group has already given up: if any return on the disclosure's registration has a `preparation_status` of `FILED` or `AMENDED` and a `tax_year` falling anywhere between `lookback_start_year` and `lookback_end_year` inclusive, the request is rejected with `ERR_VDA_YEAR_ALREADY_FILED`."
    PRD 3.9: "Under `LOOKBACK_LIMITED` it is the `estimated_exposure_tax` pro-rated to the negotiated window — multiplied by the effective lookback years and divided by seven — rounded half up to 2 decimal places, and the `waived_penalty_amount` is a quarter of that pro-rated figure, again rounded half up to 2 decimal places."

    Design: Corner/validations/vda_execution_blocked_by_already_filed_year
    """
    ctx = setup_filed_filing()

    disclosure = validate_success(api.create_vda_agreement(ctx["registration_id"], {
        "legal_entity_id": ctx["le_a_id"], "anchor_tax_year": 2026,
        "lookback_years": 3, "exposure_variant": "LOOKBACK_LIMITED",
        "estimated_exposure_tax": 140000.00,
    }, TM), 201)
    assert disclosure["lookback_start_year"] == 2024
    assert disclosure["lookback_end_year"] == 2026
    assert_money(disclosure["computed_exposure_tax"], 60000.00, "computed_exposure_tax")
    assert_money(disclosure["waived_penalty_amount"], 15000.00, "waived_penalty_amount")
    validate_success(api.submit_vda_agreement(disclosure["id"], {}, TM))

    response = api.execute_vda_agreement(disclosure["id"], {
        "negotiated_tax": 60000.00, "negotiated_interest": 4000.00,
    }, TM)

    validate_error(response, ApiErrorId.ERR_VDA_YEAR_ALREADY_FILED.value)
    reread = read_vda_agreement(disclosure["id"])
    assert reread["status"] == "SUBMITTED"
    assert reread["executed_on_date"] is None
    assert read_registration(ctx["registration_id"])["nexus_status"] == "PHYSICAL"
