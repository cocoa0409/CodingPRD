"""Non-linear lifecycle behaviour of the surplus-property state machines.

Three shapes are exercised here: the two independent status axes a SurplusAsset
carries at once, the screening cycle that re-enters OPEN after an award is
unwound, and the screening request that loops SUBMITTED -> INFO_REQUESTED ->
SUBMITTED more than once.
"""

from datetime import datetime

from test_helpers import (
    ASSESSOR_USER_ID,
    CLOCK_EPOCH,
    OFFICER_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    ApiErrorId,
    add_asset_with_payload,
    assert_clearance_certificate,
    assert_screening_cycle,
    assert_screening_request,
    assert_surplus_asset,
    assert_transfer_order,
    assert_turn_in,
    assess_asset,
    create_clearance_certificate_payload,
    create_condition_assessment_payload,
    create_draft_turn_in,
    create_screening_cycle_payload,
    create_screening_request_payload,
    create_transfer_order_payload,
    create_vehicle_asset_payload,
    file_screening_request,
    make_agency_officer_headers,
    make_clearance_technician_headers,
    make_disposal_officer_headers,
    make_surplus_assessor_headers,
    open_screening_cycle,
    read_asset,
    read_cycle,
    read_request,
    read_transfer_order,
    read_turn_in,
    register_agency,
    register_state_agency,
    review_turn_in,
    set_clock,
    submit_turn_in,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["disposal_officer_headers"]

# ─── Shared instants and dates for the dual-axis asset scenario ────────────

DUAL_AXIS_COST_CENTS = 10_472_195
DUAL_AXIS_FMV_CENTS = 10_472_195


def _instant(value) -> datetime:
    """Parse an ISO 8601 UTC instant so two spellings of the same moment compare
    equal regardless of how many fractional digits are rendered."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual, expected: str, label: str) -> None:
    assert _instant(actual) == _instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


# ─── Scenario builders ────────────────────────────────────────────────────

def _setup_dual_axis_asset() -> dict:
    """One HEAVY_EQUIPMENT item that is both data-bearing and restricted, so both
    certificate families are required, sitting on a SUBMITTED turn-in."""
    set_clock(CLOCK_EPOCH)
    agency = register_state_agency()
    turn_in = create_draft_turn_in(agency["id"])
    asset = add_asset_with_payload(
        agency["id"],
        {
            "turn_in_id": turn_in["id"],
            "category": "HEAVY_EQUIPMENT",
            "description": "Armored recovery vehicle with onboard mission computer",
            "acquisition_cost_cents": DUAL_AXIS_COST_CENTS,
            "acquisition_date": "2026-01-10",
            "is_data_bearing": True,
            "is_restricted": True,
            "demil_code": "C",
        },
    )
    submit_turn_in(agency["id"], turn_in["id"])
    return {"agency": agency, "turn_in": turn_in, "asset": asset}


def _record_governing_assessment(api, asset: dict) -> dict:
    payload = create_condition_assessment_payload(
        asset["version"],
        condition_code="C1",
        functional=True,
        repair_cost_estimate_cents=0,
        assessed_on="2026-07-31",
    )
    return validate_success(
        api.create_condition_assessment(
            asset["id"], payload, make_surplus_assessor_headers(ASSESSOR_USER_ID)
        ),
        201,
    )


def _file_certificate(api, asset_id: str, **overrides):
    """A ClearanceTechnician whose identity differs from every assessor on the
    asset, which the segregation-of-duties barrier requires."""
    return api.create_clearance_certificate(
        asset_id,
        create_clearance_certificate_payload(**overrides),
        make_clearance_technician_headers(TECHNICIAN_USER_ID),
    )


def _walk_to_blocked_clearance(api) -> dict:
    """Appraise the dual-flagged asset, cover the sanitisation family with a
    verified certificate and then fail verification on the demilitarisation
    family, which leaves the release-gate axis at BLOCKED."""
    scenario = _setup_dual_axis_asset()
    _record_governing_assessment(api, scenario["asset"])
    validate_success(
        _file_certificate(
            api, scenario["asset"]["id"],
            cert_type="DATA_SANITIZATION", method="NIST_PURGE",
            serials_verified=True, certified_on="2026-08-01",
        ),
        201,
    )
    validate_success(
        _file_certificate(
            api, scenario["asset"]["id"],
            cert_type="DEMILITARIZATION", method="MUTILATE",
            serials_verified=False, certified_on="2026-08-01",
            notes="Cutting torch unavailable; turret ring left intact",
        ),
        201,
    )
    scenario["asset"] = read_asset(scenario["asset"]["id"])
    return scenario


class TestAssetDualAxisIndependence:
    """The disposition axis and the release-gate axis on one SurplusAsset row."""

    def test_creation_sets_both_axes_and_first_assessment_moves_only_disposition(
        self, api
    ):
        """Creation initialises both axes at once, and the first assessment advances
        the custody axis while leaving the release gate exactly where it was.

        PRD: "Creation initialises both lifecycle axes at once. `disposition_status`
        begins at `INTAKE` in every case. `clearance_status` begins at
        `REQUIRED_PENDING` when either `is_data_bearing` or `is_restricted` is true,
        and at `NOT_REQUIRED` when both are false — in the latter case the release
        gate stands open from birth and no certificate may ever be filed against the
        item."
        PRD: "The first assessment on an asset drives `disposition_status` from
        `INTAKE` to `ASSESSED`."
        PRD: "Nothing on this axis constrains the disposition axis and nothing on the
        disposition axis constrains this one: an asset can be `LISTED` and bid on
        while its clearance is still `REQUIRED_PENDING`, and an asset can be
        `CLEARED` while it is still sitting in `ASSESSED`."

        Design: Difficulty/non_linear_state_machine/nlsm_asset_dual_axis_disposition_and_clearance_independence
        """
        scenario = _setup_dual_axis_asset()
        created = scenario["asset"]

        assert_surplus_asset(created)
        assert created["disposition_status"] == "INTAKE", (
            "a newly added item begins at INTAKE on the custody axis, got "
            f"{created['disposition_status']}"
        )
        assert created["clearance_status"] == "REQUIRED_PENDING", (
            "a data-bearing and restricted item begins at REQUIRED_PENDING on the "
            f"release-gate axis, got {created['clearance_status']}"
        )
        assert created["fair_market_value_cents"] is None, (
            "fair_market_value_cents stays null until the first assessment exists"
        )
        assert created["condition_code"] is None, (
            "condition_code stays null until the first assessment exists"
        )
        assert created["version"] == 1, (
            f"a freshly created asset carries version 1, got {created['version']}"
        )

        _record_governing_assessment(api, created)
        after = read_asset(created["id"])

        assert after["disposition_status"] == "ASSESSED", (
            "the first assessment drives the custody axis from INTAKE to ASSESSED, "
            f"got {after['disposition_status']}"
        )
        assert after["clearance_status"] == "REQUIRED_PENDING", (
            "the assessment must leave the release-gate axis untouched at "
            f"REQUIRED_PENDING, got {after['clearance_status']}"
        )
        assert after["fair_market_value_cents"] == DUAL_AXIS_FMV_CENTS, (
            f"fair_market_value_cents must be {DUAL_AXIS_FMV_CENTS}, got "
            f"{after['fair_market_value_cents']}"
        )
        assert after["condition_code"] == "C1", (
            f"the governing condition_code must be C1, got {after['condition_code']}"
        )
        assert after["version"] == 2, (
            f"the assessment increments the asset version to 2, got {after['version']}"
        )

    def test_certificates_move_only_the_clearance_axis(self, api):
        """A verified certificate that still leaves a required family uncovered is a
        self-transition, and an unverified one blocks the gate — neither touches the
        custody axis.

        PRD: "A `DATA_SANITIZATION` certificate is required when `is_data_bearing` is
        true; a `DEMILITARIZATION` certificate is required when `is_restricted` is
        true; an asset with both flags needs both, and only certificates with
        `serials_verified` true count towards the requirement."
        PRD: "Each accepted certificate re-evaluates the clearance axis and leaves
        `disposition_status` entirely untouched, incrementing the asset's `version` by
        1 either way."
        PRD: "From `REQUIRED_PENDING`, a verified certificate that completes every
        required `cert_type` moves the asset to `CLEARED`; a verified certificate that
        still leaves a required type uncovered leaves the asset at `REQUIRED_PENDING`."
        PRD: "A certificate with `serials_verified` false is persisted for audit and
        moves the asset to `BLOCKED`, whether it arrives at `REQUIRED_PENDING` or at
        `CLEARED` — a clearance that has already been granted can be revoked by a
        later failed verification, though only while the asset has not yet reached
        `RELEASED`."

        Design: Difficulty/non_linear_state_machine/nlsm_asset_dual_axis_disposition_and_clearance_independence
        """
        scenario = _setup_dual_axis_asset()
        asset_id = scenario["asset"]["id"]
        _record_governing_assessment(api, scenario["asset"])

        first = validate_success(
            _file_certificate(
                api, asset_id,
                cert_type="DATA_SANITIZATION", method="NIST_PURGE",
                serials_verified=True, certified_on="2026-08-01",
            ),
            201,
        )
        assert_clearance_certificate(first)
        assert first["cert_type"] == "DATA_SANITIZATION"
        assert first["method"] == "NIST_PURGE"
        assert first["serials_verified"] is True

        after_first = read_asset(asset_id)
        assert after_first["clearance_status"] == "REQUIRED_PENDING", (
            "the demilitarisation family is still uncovered, so the release gate "
            f"stays at REQUIRED_PENDING, got {after_first['clearance_status']}"
        )
        assert after_first["disposition_status"] == "ASSESSED", (
            "a clearance certificate leaves the custody axis entirely untouched at "
            f"ASSESSED, got {after_first['disposition_status']}"
        )
        assert after_first["version"] == 3, (
            f"the certificate increments the asset version to 3, got "
            f"{after_first['version']}"
        )

        second = validate_success(
            _file_certificate(
                api, asset_id,
                cert_type="DEMILITARIZATION", method="MUTILATE",
                serials_verified=False, certified_on="2026-08-01",
                notes="Cutting torch unavailable; turret ring left intact",
            ),
            201,
        )
        assert_clearance_certificate(second)
        assert second["serials_verified"] is False

        after_second = read_asset(asset_id)
        assert after_second["clearance_status"] == "BLOCKED", (
            "an unverified certificate moves the release gate to BLOCKED, got "
            f"{after_second['clearance_status']}"
        )
        assert after_second["disposition_status"] == "ASSESSED", (
            "the blocking certificate must leave the custody axis at ASSESSED, got "
            f"{after_second['disposition_status']}"
        )
        assert after_second["version"] == 4, (
            f"the second certificate increments the asset version to 4, got "
            f"{after_second['version']}"
        )

    def test_screening_opens_while_the_release_gate_is_blocked(self, api):
        """A blocked release gate is no obstacle to the custody axis: the asset enters
        screening while `clearance_status` stays `BLOCKED`.

        PRD: "Nothing on this axis constrains the disposition axis and nothing on the
        disposition axis constrains this one: an asset can be `LISTED` and bid on
        while its clearance is still `REQUIRED_PENDING`, and an asset can be
        `CLEARED` while it is still sitting in `ASSESSED`."
        PRD: "The asset must be in `disposition_status` `ASSESSED`, its turn-in must
        have been `ACCEPTED`, and its `fair_market_value_cents` must be at least two
        hundred fifty dollars — low-value property is statutorily exempt from tier
        screening and pushing a below-threshold item into a cycle is refused with
        `ERR_ASSET_NOT_DISPOSABLE`."
        PRD: "Opening the cycle also moves the asset from `ASSESSED` to `SCREENING`
        and increments the asset's `version` by 1."

        Design: Difficulty/non_linear_state_machine/nlsm_asset_dual_axis_disposition_and_clearance_independence
        """
        scenario = _walk_to_blocked_clearance(api)
        asset_id = scenario["asset"]["id"]
        assert scenario["asset"]["clearance_status"] == "BLOCKED", (
            "precondition: the release gate must already be BLOCKED, got "
            f"{scenario['asset']['clearance_status']}"
        )

        review_turn_in(scenario["turn_in"]["id"], "ACCEPT")

        cycle = validate_success(
            api.create_screening_cycle(
                create_screening_cycle_payload(
                    asset_id, opens_at=CLOCK_EPOCH, tier_window_days=5
                ),
                make_disposal_officer_headers(OFFICER_USER_ID),
            ),
            201,
        )
        assert_screening_cycle(cycle)
        assert cycle["status"] == "OPEN", (
            f"a new cycle is OPEN, got {cycle['status']}"
        )
        assert cycle["current_tier"] == "STATE_AGENCY", (
            f"a new cycle starts at the STATE_AGENCY tier, got {cycle['current_tier']}"
        )

        after = read_asset(asset_id)
        assert after["disposition_status"] == "SCREENING", (
            "opening the cycle moves the custody axis from ASSESSED to SCREENING even "
            f"though the release gate is BLOCKED, got {after['disposition_status']}"
        )
        assert after["clearance_status"] == "BLOCKED", (
            "opening the cycle must leave the release-gate axis at BLOCKED, got "
            f"{after['clearance_status']}"
        )
        assert after["version"] == 5, (
            f"opening the cycle increments the asset version to 5, got "
            f"{after['version']}"
        )

    def test_release_gate_clears_and_blocks_again_during_screening(self, api):
        """The release-gate axis has no terminal state: it walks BLOCKED -> CLEARED ->
        BLOCKED while the custody axis sits still at `SCREENING`.

        PRD: "`clearance_status` is the **release-gate axis**. Its values are
        `NOT_REQUIRED`, `REQUIRED_PENDING`, `CLEARED` and `BLOCKED`, and it has no
        terminal state — a cleared asset can be blocked again."
        PRD: "From `BLOCKED`, a verified certificate that completes the required set
        moves the asset back to `CLEARED`."
        PRD: "Each accepted certificate re-evaluates the clearance axis and leaves
        `disposition_status` entirely untouched, incrementing the asset's `version` by
        1 either way."
        PRD: "Because the axes are independent, a transition on one of them is still a
        mutation of the same physical row: it refreshes `updated_at` and increments
        `version` by 1."
        PRD: "Acceptance moves `status` from `SUBMITTED` to `ACCEPTED`, stamps
        `reviewed_at` from the logical clock, recomputes `appraised_total_cents`, and
        increments the turn-in's `version` by 1."

        Design: Difficulty/non_linear_state_machine/nlsm_asset_dual_axis_disposition_and_clearance_independence
        """
        scenario = _walk_to_blocked_clearance(api)
        asset_id = scenario["asset"]["id"]
        review_turn_in(scenario["turn_in"]["id"], "ACCEPT")
        open_screening_cycle(asset_id, opens_at=CLOCK_EPOCH, tier_window_days=5)

        validate_success(
            _file_certificate(
                api, asset_id,
                cert_type="DEMILITARIZATION", method="MUTILATE",
                serials_verified=True, certified_on="2026-08-01",
            ),
            201,
        )
        cleared = read_asset(asset_id)
        assert cleared["clearance_status"] == "CLEARED", (
            "a verified certificate completing the required set moves the gate from "
            f"BLOCKED back to CLEARED, got {cleared['clearance_status']}"
        )
        assert cleared["disposition_status"] == "SCREENING", (
            "the custody axis must stay at SCREENING while the gate clears, got "
            f"{cleared['disposition_status']}"
        )
        assert cleared["version"] == 6, (
            f"the clearing certificate increments the asset version to 6, got "
            f"{cleared['version']}"
        )

        validate_success(
            _file_certificate(
                api, asset_id,
                cert_type="DATA_SANITIZATION", method="NIST_CLEAR",
                serials_verified=False, certified_on="2026-08-01",
                notes="Re-scan found one drive unaccounted for",
            ),
            201,
        )
        blocked_again = read_asset(asset_id)
        assert blocked_again["clearance_status"] == "BLOCKED", (
            "a granted clearance can be revoked by a later failed verification, so "
            f"the gate returns to BLOCKED, got {blocked_again['clearance_status']}"
        )
        assert blocked_again["disposition_status"] == "SCREENING", (
            "the revocation must leave the custody axis at SCREENING, got "
            f"{blocked_again['disposition_status']}"
        )
        assert blocked_again["version"] == 7, (
            "seven mutations of the asset row — creation, one assessment, four "
            f"certificates and the cycle opening — give version 7, got "
            f"{blocked_again['version']}"
        )
        assert blocked_again["fair_market_value_cents"] == DUAL_AXIS_FMV_CENTS, (
            "no clearance certificate revalues the asset, so "
            f"fair_market_value_cents stays {DUAL_AXIS_FMV_CENTS}, got "
            f"{blocked_again['fair_market_value_cents']}"
        )

        certificates, meta = validate_paginated(
            api.list_clearance_certificates(asset_id, OFFICER)
        )
        assert meta["total_count"] == 4, (
            "every certificate is persisted for audit, including the two failed "
            f"verifications, so four are on file; got {meta['total_count']}"
        )
        assert len(certificates) == 4, (
            f"the first page must carry all four certificates, got {len(certificates)}"
        )

        turn_in = read_turn_in(scenario["turn_in"]["id"])
        assert_turn_in(turn_in)
        assert turn_in["status"] == "ACCEPTED", (
            f"the parent turn-in stays ACCEPTED, got {turn_in['status']}"
        )
        assert turn_in["appraised_total_cents"] == DUAL_AXIS_FMV_CENTS, (
            f"appraised_total_cents must be {DUAL_AXIS_FMV_CENTS}, got "
            f"{turn_in['appraised_total_cents']}"
        )


# ─── Screening-contest scenario shared by the cycle-loop tests ─────────────

PICKUP_FMV_CENTS = 297_620
STATE_TIER_BASE_CENTS = 74_405
STATE_TIER_FEE_CENTS = 5_000
STATE_TIER_PRICE_CENTS = 79_405


def _setup_screening_contest() -> dict:
    """One accepted pickup in an OPEN STATE_AGENCY tier with two competing
    requests filed inside the window."""
    set_clock(CLOCK_EPOCH)
    owner = register_state_agency()
    claimant = register_agency(
        name="State Department of Public Safety",
        agency_code="DPS-02",
        agency_type="STATE_AGENCY",
    )
    rival = register_agency(
        name="State Workforce Commission",
        agency_code="TWC-03",
        agency_type="STATE_AGENCY",
    )
    turn_in = create_draft_turn_in(owner["id"])
    asset = add_asset_with_payload(
        owner["id"], create_vehicle_asset_payload(turn_in["id"])
    )
    submit_turn_in(owner["id"], turn_in["id"])
    assess_asset(
        asset["id"], asset["version"],
        condition_code="C4", functional=True,
        repair_cost_estimate_cents=185000, assessed_on="2026-07-28",
    )
    review_turn_in(turn_in["id"], "ACCEPT")
    cycle = open_screening_cycle(
        asset["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
    )
    first = file_screening_request(
        cycle["id"], claimant["id"],
        intended_use="Highway patrol equipment hauling",
        justification=(
            "Patrol district 7 lost its only three-quarter ton truck to a collision."
        ),
        needed_by_date="2026-09-15",
    )
    second = file_screening_request(
        cycle["id"], rival["id"],
        intended_use="Mobile job-fair trailer towing",
        justification=(
            "Workforce outreach trailer currently has no tow vehicle at all."
        ),
        needed_by_date="2026-10-01",
    )
    return {
        "owner": owner, "claimant": claimant, "rival": rival,
        "turn_in": turn_in, "asset": asset, "cycle": cycle,
        "first_request": first, "second_request": second,
    }


def _award_and_document(api, scenario: dict) -> dict:
    """Award the first request and issue the transfer order that documents it."""
    validate_success(
        api.award_screening_cycle(
            scenario["cycle"]["id"], scenario["first_request"]["id"],
            make_disposal_officer_headers(OFFICER_USER_ID),
        ),
        200,
    )
    order = validate_success(
        api.create_transfer_order(
            create_transfer_order_payload(
                scenario["asset"]["id"], scenario["claimant"]["id"],
                scenario["first_request"]["id"],
            ),
            make_disposal_officer_headers(OFFICER_USER_ID),
        ),
        201,
    )
    return order


class TestScreeningCycleAwardThenVoidReturnsToOpen:
    """The cycle is not a one-way ladder: AWARDED walks back to OPEN."""

    def test_void_returns_the_cycle_to_open_with_a_fresh_tier_window(self, api):
        """Awarding leaves the cycle AWARDED with a stamped decision; voiding the
        documenting order walks it back to OPEN on the same tier with the award
        stamps cleared and a brand-new window.

        PRD: "The award stamps `awarded_by_user_id` from the officer's `X-User-ID` and
        `awarded_at` from the logical clock, and moves the cycle from `OPEN` to
        `AWARDED`."
        PRD: "It also resolves every competitor: the named request moves `SUBMITTED` →
        `APPROVED`, and every *other* request on the cycle whose `status` is
        `SUBMITTED` or `INFO_REQUESTED` moves to `DENIED` with `denial_reason` set to
        `LOST_AWARD`, processed in `created_at` ascending order."
        PRD: "Crossing into the asset, `disposition_status` moves from `SCREENING` to
        `AWARDED_TRANSFER`."
        PRD: "Second, multiply the asset's stored `fair_market_value_cents` by that
        factor and round the product half up to whole cents; the result is stored as
        `base_transfer_cents`."
        PRD: "Hop three, caused by hop two, follows from that request no longer being
        approved: the parent `ScreeningCycle` moves from `AWARDED` back to `OPEN`, with
        `current_tier` left exactly where it was, `tier_opened_at` reset to the logical
        clock, `tier_deadline_at` recomputed from that reset opening, and
        `awarded_by_user_id` and `awarded_at` cleared back to null — the tier gets a
        fresh full window to find another taker."
        PRD: "Hop four, caused by hop three, follows from the cycle being open again:
        the cycle's asset moves `disposition_status` from `AWARDED_TRANSFER` back to
        `SCREENING`."

        Design: Difficulty/non_linear_state_machine/nlsm_screening_cycle_award_then_void_returns_to_open
        """
        scenario = _setup_screening_contest()
        cycle_id = scenario["cycle"]["id"]

        order = _award_and_document(api, scenario)

        awarded = read_cycle(cycle_id)
        assert awarded["status"] == "AWARDED", (
            f"the award moves the cycle from OPEN to AWARDED, got {awarded['status']}"
        )
        _assert_instant(awarded["awarded_at"], CLOCK_EPOCH, "awarded_at")
        assert awarded["awarded_by_user_id"] == OFFICER_USER_ID, (
            "awarded_by_user_id is stamped from the deciding officer, got "
            f"{awarded['awarded_by_user_id']}"
        )

        winner = read_request(scenario["first_request"]["id"])
        assert winner["status"] == "APPROVED", (
            f"the named request moves SUBMITTED to APPROVED, got {winner['status']}"
        )
        loser = read_request(scenario["second_request"]["id"])
        assert loser["status"] == "DENIED", (
            f"the competing request moves to DENIED, got {loser['status']}"
        )
        assert loser["denial_reason"] == "LOST_AWARD", (
            f"the competitor's denial_reason must be LOST_AWARD, got "
            f"{loser['denial_reason']}"
        )
        assert read_asset(scenario["asset"]["id"])["disposition_status"] == (
            "AWARDED_TRANSFER"
        ), "the award moves the asset from SCREENING to AWARDED_TRANSFER"

        assert_transfer_order(order)
        assert order["base_transfer_cents"] == STATE_TIER_BASE_CENTS, (
            f"a STATE_AGENCY recipient pays a base of {STATE_TIER_BASE_CENTS} on a "
            f"{PICKUP_FMV_CENTS}-cent valuation, got {order['base_transfer_cents']}"
        )
        assert order["handling_fee_cents"] == STATE_TIER_FEE_CENTS, (
            f"a base below one thousand dollars draws a fifty-dollar handling fee, "
            f"got {order['handling_fee_cents']}"
        )
        assert order["transfer_price_cents"] == STATE_TIER_PRICE_CENTS, (
            f"transfer_price_cents must be {STATE_TIER_PRICE_CENTS}, got "
            f"{order['transfer_price_cents']}"
        )

        set_clock("2026-08-04T00:00:00Z")
        validate_success(
            api.void_transfer_order(
                order["id"], "Recipient garage lost its lift certification",
                make_disposal_officer_headers(OFFICER_USER_ID),
            ),
            200,
        )

        voided = read_transfer_order(order["id"])
        assert voided["status"] == "VOIDED", (
            f"hop one moves the order to VOIDED, got {voided['status']}"
        )
        reopened_winner = read_request(scenario["first_request"]["id"])
        assert reopened_winner["status"] == "DENIED", (
            "hop two moves the documented request from APPROVED to DENIED, got "
            f"{reopened_winner['status']}"
        )
        assert reopened_winner["denial_reason"] == "TRANSFER_VOIDED", (
            "the documented request's denial_reason must be TRANSFER_VOIDED, got "
            f"{reopened_winner['denial_reason']}"
        )

        reopened = read_cycle(cycle_id)
        assert reopened["status"] == "OPEN", (
            f"hop three walks the cycle from AWARDED back to OPEN, got "
            f"{reopened['status']}"
        )
        assert reopened["current_tier"] == "STATE_AGENCY", (
            "current_tier is left exactly where it was, got "
            f"{reopened['current_tier']}"
        )
        assert reopened["tier_advance_count"] == 0, (
            "reopening the tier is not an advance, so tier_advance_count stays 0, got "
            f"{reopened['tier_advance_count']}"
        )
        assert reopened["awarded_at"] is None, (
            f"awarded_at is cleared back to null, got {reopened['awarded_at']}"
        )
        assert reopened["awarded_by_user_id"] is None, (
            f"awarded_by_user_id is cleared back to null, got "
            f"{reopened['awarded_by_user_id']}"
        )
        _assert_instant(
            reopened["tier_opened_at"], "2026-08-04T00:00:00Z", "tier_opened_at"
        )
        _assert_instant(
            reopened["tier_deadline_at"], "2026-08-09T00:00:00Z", "tier_deadline_at"
        )
        assert read_asset(scenario["asset"]["id"])["disposition_status"] == "SCREENING", (
            "hop four walks the asset from AWARDED_TRANSFER back to SCREENING"
        )

    def test_reopened_cycle_accepts_a_new_request_and_can_be_awarded_again(self, api):
        """The reopened tier behaves exactly as it did the first time: it admits a
        fresh request inside its new window and can be awarded a second time.

        PRD: "Three checks follow existence resolution, in this order: the requesting
        organisation must not be `SUSPENDED`, or the filing is refused with
        `ERR_AGENCY_SUSPENDED`; the organisation's `agency_type` must equal the cycle's
        `current_tier`, or the filing is refused with `ERR_TIER_PRIORITY_VIOLATION` —
        this is what makes the ladder a ladder, and it also means a cycle sitting at
        `PUBLIC_SALE` admits no screening request at all, since no organisation's type
        is `PUBLIC_SALE`; and the logical clock must fall inside the closed interval
        running from `tier_opened_at` through `tier_deadline_at`, both endpoints
        included, or the filing is refused with `ERR_TIER_WINDOW_EXPIRED`."
        PRD: "Once a cycle has left `OPEN` its tier windows are over and no further
        request is admitted."
        PRD: "A filed request lands in `status` `SUBMITTED` with
        `information_request_note`, `denial_reason` all null and `resubmission_count`
        at 0, and it freezes `tier_at_submission` as a copy of the cycle's
        `current_tier` at that instant — one of `STATE_AGENCY`, `LOCAL_GOVERNMENT` or
        `ELIGIBLE_NONPROFIT`."
        PRD: "Filing also recomputes the cycle's `open_request_count`, which is the
        number of requests on that cycle whose `status` is `SUBMITTED` or
        `INFO_REQUESTED`."
        PRD: "It also resolves every competitor: the named request moves `SUBMITTED` →
        `APPROVED`, and every *other* request on the cycle whose `status` is
        `SUBMITTED` or `INFO_REQUESTED` moves to `DENIED` with `denial_reason` set to
        `LOST_AWARD`, processed in `created_at` ascending order."
        PRD: "Each hop that mutates a row refreshes that row's `updated_at` and
        increments its `version` by 1, so a cascade that touches an invoice, a lot, an
        asset and a bidder bumps four version counters."

        Design: Difficulty/non_linear_state_machine/nlsm_screening_cycle_award_then_void_returns_to_open
        """
        scenario = _setup_screening_contest()
        cycle_id = scenario["cycle"]["id"]
        order = _award_and_document(api, scenario)

        set_clock("2026-08-04T00:00:00Z")
        validate_success(
            api.void_transfer_order(
                order["id"], "Recipient garage lost its lift certification",
                make_disposal_officer_headers(OFFICER_USER_ID),
            ),
            200,
        )
        assert read_cycle(cycle_id)["status"] == "OPEN", (
            "precondition: the void must have returned the cycle to OPEN"
        )

        late_entrant = register_agency(
            name="State Parks and Wildlife Division",
            agency_code="PWD-04",
            agency_type="STATE_AGENCY",
        )
        third = validate_success(
            api.create_screening_request(
                create_screening_request_payload(
                    cycle_id, late_entrant["id"],
                    intended_use="Boat-ramp maintenance crew transport",
                    justification=(
                        "Two lake districts share one truck and cannot cover both."
                    ),
                    needed_by_date="2026-09-30",
                ),
                make_agency_officer_headers(late_entrant["id"]),
            ),
            201,
        )
        assert_screening_request(third)
        assert third["status"] == "SUBMITTED", (
            f"a freshly filed request lands in SUBMITTED, got {third['status']}"
        )
        assert third["tier_at_submission"] == "STATE_AGENCY", (
            "the reopened tier is still STATE_AGENCY, so tier_at_submission freezes "
            f"there, got {third['tier_at_submission']}"
        )
        assert third["resubmission_count"] == 0, (
            f"resubmission_count starts at 0, got {third['resubmission_count']}"
        )
        assert read_cycle(cycle_id)["open_request_count"] == 1, (
            "only the new request is SUBMITTED or INFO_REQUESTED, so "
            "open_request_count recomputes to 1"
        )

        validate_success(
            api.award_screening_cycle(
                cycle_id, third["id"],
                make_disposal_officer_headers(OFFICER_USER_ID),
            ),
            200,
        )

        rewarded = read_cycle(cycle_id)
        assert rewarded["status"] == "AWARDED", (
            "the reopened cycle can be awarded a second time, got "
            f"{rewarded['status']}"
        )
        _assert_instant(rewarded["awarded_at"], "2026-08-04T00:00:00Z", "awarded_at")
        assert rewarded["awarded_by_user_id"] == OFFICER_USER_ID, (
            "the second award restamps awarded_by_user_id, got "
            f"{rewarded['awarded_by_user_id']}"
        )
        assert rewarded["current_tier"] == "STATE_AGENCY", (
            f"the tier never moved, got {rewarded['current_tier']}"
        )
        assert rewarded["tier_advance_count"] == 0, (
            "no advance ever happened on this cycle, got "
            f"{rewarded['tier_advance_count']}"
        )
        assert rewarded["open_request_count"] == 0, (
            "the awarded request is APPROVED and every other request is DENIED, so "
            f"open_request_count recomputes to 0, got {rewarded['open_request_count']}"
        )
        assert rewarded["version"] > scenario["cycle"]["version"], (
            "every mutation of the cycle row increments its version, so the twice-"
            "awarded cycle must sit above the version it was opened with; got "
            f"{rewarded['version']} against {scenario['cycle']['version']}"
        )

        assert read_request(third["id"])["status"] == "APPROVED", (
            "the newly named request moves SUBMITTED to APPROVED"
        )
        assert read_asset(scenario["asset"]["id"])["disposition_status"] == (
            "AWARDED_TRANSFER"
        ), "the second award moves the asset from SCREENING to AWARDED_TRANSFER again"

        already_denied = read_request(scenario["first_request"]["id"])
        assert already_denied["status"] == "DENIED", (
            "the award touches only requests in SUBMITTED or INFO_REQUESTED, so the "
            f"previously denied request is untouched, got {already_denied['status']}"
        )
        assert already_denied["denial_reason"] == "TRANSFER_VOIDED", (
            "its denial_reason stays TRANSFER_VOIDED rather than being rewritten to "
            f"LOST_AWARD, got {already_denied['denial_reason']}"
        )


# ─── Single-request cycle shared by the request-loop tests ─────────────────

CYCLE_DEADLINE = "2026-08-06T00:00:00Z"
ORIGINAL_JUSTIFICATION = (
    "Patrol district 7 lost its only three-quarter ton truck to a collision."
)


def _setup_single_request_cycle() -> dict:
    """One accepted pickup in an OPEN STATE_AGENCY tier with a single request."""
    set_clock(CLOCK_EPOCH)
    owner = register_state_agency()
    claimant = register_agency(
        name="State Department of Public Safety",
        agency_code="DPS-02",
        agency_type="STATE_AGENCY",
    )
    turn_in = create_draft_turn_in(owner["id"])
    asset = add_asset_with_payload(
        owner["id"], create_vehicle_asset_payload(turn_in["id"])
    )
    submit_turn_in(owner["id"], turn_in["id"])
    assess_asset(
        asset["id"], asset["version"],
        condition_code="C4", functional=True,
        repair_cost_estimate_cents=185000, assessed_on="2026-07-28",
    )
    review_turn_in(turn_in["id"], "ACCEPT")
    cycle = open_screening_cycle(
        asset["id"], opens_at=CLOCK_EPOCH, tier_window_days=5
    )
    request = file_screening_request(
        cycle["id"], claimant["id"],
        intended_use="Highway patrol equipment hauling",
        justification=ORIGINAL_JUSTIFICATION,
        needed_by_date="2026-09-15",
    )
    return {
        "owner": owner, "claimant": claimant, "turn_in": turn_in,
        "asset": asset, "cycle": cycle, "request": request,
    }


def _request_info(api, request_id: str, note: str):
    return api.request_screening_info(
        request_id, note, make_disposal_officer_headers(OFFICER_USER_ID)
    )


def _resubmit(api, request_id: str, agency_id: str, justification: str):
    return api.resubmit_screening_request(
        request_id, justification, make_agency_officer_headers(agency_id)
    )


class TestScreeningRequestInfoRequestedResubmitLoop:
    """The request lifecycle is cyclic: SUBMITTED <-> INFO_REQUESTED, repeatedly."""

    def test_request_traverses_the_loop_twice(self, api):
        """Two full turns of the loop: each `request-info` parks the request, each
        answer returns it to contention, and the tier window is held open throughout.

        PRD: "Requests can be sent back for more information and returned to
        contention, which makes the request lifecycle cyclic."
        PRD: "A `DisposalOfficer` moves a `SUBMITTED` request to `INFO_REQUESTED`,
        recording an `information_request_note`; the parent cycle must still be `OPEN`."
        PRD: "A request in `INFO_REQUESTED` is no longer eligible to be awarded, but it
        still counts inside `open_request_count`, so it continues to hold the tier
        window open."
        PRD: "The answer supplies a replacement `justification`, which overwrites the
        previous one; `resubmission_count` increases by 1, `information_request_note`
        is cleared back to null, and `tier_at_submission` is left exactly as it was."
        PRD: "That frozen tier exists for audit and is **never** rewritten afterwards,
        not even when the request is revised."

        Design: Difficulty/non_linear_state_machine/nlsm_screening_request_info_requested_resubmit_loop
        """
        scenario = _setup_single_request_cycle()
        request_id = scenario["request"]["id"]
        cycle_id = scenario["cycle"]["id"]
        claimant_id = scenario["claimant"]["id"]

        assert scenario["request"]["information_request_note"] is None, (
            "a freshly filed request has a null information_request_note"
        )
        assert scenario["request"]["justification"] == ORIGINAL_JUSTIFICATION

        parked = validate_success(
            _request_info(
                api, request_id,
                "Confirm whether the district can fund the collision repairs.",
            ),
            200,
        )
        assert_screening_request(parked)
        assert parked["status"] == "INFO_REQUESTED", (
            f"request-info moves SUBMITTED to INFO_REQUESTED, got {parked['status']}"
        )
        assert parked["information_request_note"] == (
            "Confirm whether the district can fund the collision repairs."
        ), (
            "the officer's note is recorded on the request, got "
            f"{parked['information_request_note']!r}"
        )
        assert parked["resubmission_count"] == 0, (
            "parking the request is not an answer, so resubmission_count stays 0, got "
            f"{parked['resubmission_count']}"
        )
        assert parked["tier_at_submission"] == "STATE_AGENCY"
        assert read_cycle(cycle_id)["open_request_count"] == 1, (
            "an INFO_REQUESTED request still counts inside open_request_count and so "
            "holds the tier window open"
        )

        answered = validate_success(
            _resubmit(
                api, request_id, claimant_id,
                "District 7 has now budgeted the collision repairs in full.",
            ),
            200,
        )
        assert answered["status"] == "SUBMITTED", (
            "the answer returns the request from INFO_REQUESTED to SUBMITTED, got "
            f"{answered['status']}"
        )
        assert answered["resubmission_count"] == 1, (
            f"resubmission_count increases by 1, got {answered['resubmission_count']}"
        )
        assert answered["information_request_note"] is None, (
            "information_request_note is cleared back to null, got "
            f"{answered['information_request_note']!r}"
        )
        assert answered["justification"] == (
            "District 7 has now budgeted the collision repairs in full."
        ), (
            "the replacement justification overwrites the previous one, got "
            f"{answered['justification']!r}"
        )
        assert answered["tier_at_submission"] == "STATE_AGENCY", (
            "tier_at_submission is left exactly as it was, got "
            f"{answered['tier_at_submission']}"
        )

        parked_again = validate_success(
            _request_info(
                api, request_id,
                "Attach the signed budget amendment before the tier closes.",
            ),
            200,
        )
        assert parked_again["status"] == "INFO_REQUESTED", (
            "the request can be parked a second time, got "
            f"{parked_again['status']}"
        )
        assert parked_again["information_request_note"] == (
            "Attach the signed budget amendment before the tier closes."
        ), "the second note replaces the cleared one"
        assert parked_again["resubmission_count"] == 1, (
            "a second request-info does not touch resubmission_count, got "
            f"{parked_again['resubmission_count']}"
        )
        assert parked_again["tier_at_submission"] == "STATE_AGENCY", (
            "the frozen tier survives every revision, got "
            f"{parked_again['tier_at_submission']}"
        )
        assert read_cycle(cycle_id)["open_request_count"] == 1, (
            "the request is back in INFO_REQUESTED, so open_request_count is 1 again"
        )

    def test_answer_lands_exactly_on_the_tier_deadline(self, api):
        """The resubmission window is closed at its upper endpoint: an answer arriving
        at the very instant of `tier_deadline_at` still returns the request to
        contention.

        PRD: "Its `tier_deadline_at` is derived as the `tier_opened_at` plus
        `tier_window_days` whole days, where a day is an exact multiple of twenty-four
        hours."
        PRD: "Resubmission requires the parent cycle to be `OPEN` and requires the
        logical clock to be at or before the cycle's `tier_deadline_at`; a late answer
        is refused with `ERR_TIER_WINDOW_EXPIRED`."
        PRD: "The answer supplies a replacement `justification`, which overwrites the
        previous one; `resubmission_count` increases by 1, `information_request_note`
        is cleared back to null, and `tier_at_submission` is left exactly as it was."

        Design: Difficulty/non_linear_state_machine/nlsm_screening_request_info_requested_resubmit_loop
        """
        scenario = _setup_single_request_cycle()
        request_id = scenario["request"]["id"]
        claimant_id = scenario["claimant"]["id"]

        _assert_instant(
            scenario["cycle"]["tier_deadline_at"], CYCLE_DEADLINE, "tier_deadline_at"
        )

        validate_success(
            _request_info(api, request_id, "Confirm the repair funding."), 200
        )
        validate_success(
            _resubmit(api, request_id, claimant_id, "Repairs are funded in full."), 200
        )
        validate_success(
            _request_info(api, request_id, "Attach the signed budget amendment."), 200
        )

        set_clock(CYCLE_DEADLINE)
        answered = validate_success(
            _resubmit(
                api, request_id, claimant_id,
                "Budget amendment 2026-114 is attached and countersigned.",
            ),
            200,
        )
        assert answered["status"] == "SUBMITTED", (
            "an answer at exactly tier_deadline_at is inside the window and returns "
            f"the request to SUBMITTED, got {answered['status']}"
        )
        assert answered["resubmission_count"] == 2, (
            "two successful answers give resubmission_count 2, got "
            f"{answered['resubmission_count']}"
        )
        assert answered["information_request_note"] is None, (
            "information_request_note is cleared back to null, got "
            f"{answered['information_request_note']!r}"
        )
        assert answered["justification"] == (
            "Budget amendment 2026-114 is attached and countersigned."
        ), "the second answer overwrites the first replacement justification"
        assert answered["tier_at_submission"] == "STATE_AGENCY", (
            f"tier_at_submission is untouched, got {answered['tier_at_submission']}"
        )
        assert read_cycle(scenario["cycle"]["id"])["open_request_count"] == 1, (
            "the request is SUBMITTED again, so open_request_count is still 1"
        )

    def test_loop_survives_a_tier_advance_and_then_closes(self, api):
        """The deadline lets the officer advance past a tier that still holds an open
        request; the loop keeps working on the new tier until that window shuts.

        PRD: "An advance is permitted only when the cycle's `open_request_count` is
        zero — nobody in this tier wants the property — or when the logical clock has
        reached or passed `tier_deadline_at`, meaning the window has closed regardless
        of interest."
        PRD: "From `STATE_AGENCY`, `LOCAL_GOVERNMENT` or `ELIGIBLE_NONPROFIT`, the
        advance keeps the cycle in `OPEN` and moves `current_tier` exactly one step
        along the fixed order `STATE_AGENCY` → `LOCAL_GOVERNMENT` →
        `ELIGIBLE_NONPROFIT` → `PUBLIC_SALE`; `tier_opened_at` is reset to the logical
        clock, `tier_deadline_at` is recomputed from that new opening instant plus the
        same `tier_window_days`, `tier_advance_count` increases by 1, and the cycle's
        `version` increments by 1."
        PRD: "That frozen tier exists for audit and is **never** rewritten afterwards,
        not even when the request is revised."
        PRD: "Resubmission requires the parent cycle to be `OPEN` and requires the
        logical clock to be at or before the cycle's `tier_deadline_at`; a late answer
        is refused with `ERR_TIER_WINDOW_EXPIRED`."
        PRD: "Most resources additionally carry an `updated_at` — an ISO 8601 UTC
        timestamp refreshed on every mutation of the row — and a `version`, an integer
        that starts at 1 on insert and increments by exactly 1 on every mutation of
        that row, including mutations the server performs on its own initiative as part
        of a cascade and including recomputation of derived fields."

        Design: Difficulty/non_linear_state_machine/nlsm_screening_request_info_requested_resubmit_loop
        """
        scenario = _setup_single_request_cycle()
        request_id = scenario["request"]["id"]
        cycle_id = scenario["cycle"]["id"]
        claimant_id = scenario["claimant"]["id"]

        validate_success(
            _request_info(api, request_id, "Confirm the repair funding."), 200
        )
        validate_success(
            _resubmit(api, request_id, claimant_id, "Repairs are funded in full."), 200
        )
        validate_success(
            _request_info(api, request_id, "Attach the signed budget amendment."), 200
        )
        set_clock(CYCLE_DEADLINE)
        validate_success(
            _resubmit(api, request_id, claimant_id, "Amendment 2026-114 attached."),
            200,
        )
        assert read_cycle(cycle_id)["open_request_count"] == 1, (
            "precondition: the tier still holds one open request at its deadline"
        )

        advanced = validate_success(
            api.advance_screening_tier(
                cycle_id, make_disposal_officer_headers(OFFICER_USER_ID)
            ),
            200,
        )
        assert_screening_cycle(advanced)
        assert advanced["status"] == "OPEN", (
            f"the advance keeps the cycle in OPEN, got {advanced['status']}"
        )
        assert advanced["current_tier"] == "LOCAL_GOVERNMENT", (
            "the advance moves the tier exactly one step to LOCAL_GOVERNMENT, got "
            f"{advanced['current_tier']}"
        )
        assert advanced["tier_advance_count"] == 1, (
            f"tier_advance_count increases by 1, got {advanced['tier_advance_count']}"
        )
        _assert_instant(advanced["tier_opened_at"], CYCLE_DEADLINE, "tier_opened_at")
        _assert_instant(
            advanced["tier_deadline_at"], "2026-08-11T00:00:00Z", "tier_deadline_at"
        )

        after_advance = read_request(request_id)
        assert after_advance["tier_at_submission"] == "STATE_AGENCY", (
            "the frozen tier is never rewritten, not even when the cycle's own tier "
            f"moves on, got {after_advance['tier_at_submission']}"
        )
        assert after_advance["status"] == "SUBMITTED", (
            "the advance does not resolve the surviving request, got "
            f"{after_advance['status']}"
        )

        parked = validate_success(
            _request_info(
                api, request_id, "Reconfirm the need now that the tier has moved on."
            ),
            200,
        )
        assert parked["status"] == "INFO_REQUESTED", (
            "the loop still works while the cycle is OPEN on its new tier, got "
            f"{parked['status']}"
        )
        assert parked["resubmission_count"] == 2, (
            f"resubmission_count is unchanged at 2, got {parked['resubmission_count']}"
        )

        set_clock("2026-08-12T00:00:00Z")
        validate_error(
            _resubmit(
                api, request_id, claimant_id,
                "Late answer submitted after the new tier window shut.",
            ),
            ApiErrorId.ERR_TIER_WINDOW_EXPIRED,
        )

        unchanged = read_request(request_id)
        assert unchanged["status"] == "INFO_REQUESTED", (
            "the refused answer leaves the request parked at INFO_REQUESTED, got "
            f"{unchanged['status']}"
        )
        assert unchanged["resubmission_count"] == 2, (
            "a refused answer does not increment resubmission_count, got "
            f"{unchanged['resubmission_count']}"
        )
        assert unchanged["information_request_note"] == (
            "Reconfirm the need now that the tier has moved on."
        ), "the refused answer leaves the outstanding note in place"
        assert unchanged["version"] == 6, (
            "six mutations of the request row — filing, three request-info calls and "
            f"two successful answers — give version 6, got {unchanged['version']}"
        )
