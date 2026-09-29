"""Requests that break two rules at once, and which refusal the contract owes.

Each pair below is set up so that a single call genuinely violates both rules.
One test asserts the outranking refusal; a companion test clears the higher
condition and shows the outranked rule surfacing on its own, which proves it was
reachable all along and was merely out-ranked.
"""

from test_helpers import (
    BOND_ACTIVE,
    BOND_LAPSED,
    CATEGORY_TERMITE_APPLICATOR,
    CATEGORY_WDO_INSPECTOR,
    CONDUCIVE_EXCESS_MOISTURE,
    CONDUCIVE_WOOD_TO_GROUND,
    CONSTRUCTION_SLAB,
    ERR_INVALID_BOND_STATE,
    ERR_LICENSE_EXPIRED,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_PAYMENT_INSUFFICIENT,
    ERR_RENEWAL_WINDOW_NOT_OPEN,
    LICENSE_STATUS_ACTIVE,
    LICENSE_STATUS_EXPIRED,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    PURPOSE_INITIAL,
    RENEWAL_PAID,
    RENEWAL_PENDING,
    TIER_REPAIR_AND_RETREAT,
    assert_money,
    assert_renewal_invoice,
    assert_status,
    bonded_property,
    clean_initial_graph,
    completed_liquid_plan,
    conducive_finding_payload,
    issue_bond,
    next_license_number,
    open_renewal,
    register_inspector,
    register_property,
    renewal_completion_payload,
    renewal_graph,
    review_bond_term,
    set_clock,
    set_license_status,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Pair 1 -- an expired credential against an underpaid invoice
# ---------------------------------------------------------------------------


def _renewal_awaiting_completion(api):
    """A PENDING invoice whose renewal graph was signed on a credential that
    then ran out.

    The signer's licence expires 2027-08-31 and its status is never touched, so
    at the completion instant of 2027-09-04 the credential is expired by date
    while still ACTIVE by status.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    prop = register_property(
        api,
        address_line1="411 Cypress Row",
        state_code="FL",
        construction_type=CONSTRUCTION_SLAB,
        square_footage=2000,
        linear_footage=180,
        year_built=1995,
        has_attached_structures=False,
    )
    signer = register_inspector(
        api,
        full_name="Rosa Vance",
        license_number=next_license_number("FL"),
        license_state="FL",
        license_categories=[CATEGORY_WDO_INSPECTOR],
        license_expires_on="2027-08-31",
        ce_credits=12,
    )
    applicator = register_inspector(
        api,
        full_name="Dale Ortiz",
        license_number=next_license_number("FL"),
        license_state="FL",
        license_categories=[CATEGORY_TERMITE_APPLICATOR],
        license_expires_on="2029-06-30",
    )
    graph = clean_initial_graph(
        api,
        prop["id"],
        signer["id"],
        purpose=PURPOSE_INITIAL,
        scheduled_start_at="2026-08-01T13:00:00Z",
        scheduled_end_at="2026-08-01T15:00:00Z",
    )
    plan = completed_liquid_plan(api, prop["id"], graph["id"], applicator["id"])
    set_clock(api, "2026-09-01T00:00:00Z")
    bond = issue_bond(
        api,
        prop["id"],
        plan["id"],
        coverage_tier=TIER_REPAIR_AND_RETREAT,
        conducive_waiver_codes=[],
    )
    set_clock(api, "2027-08-20T09:00:00Z")
    renewal = open_renewal(api, bond["id"])
    rgraph = renewal_graph(
        api,
        prop["id"],
        signer["id"],
        graph["id"],
        findings=[
            conducive_finding_payload("A1", CONDUCIVE_EXCESS_MOISTURE, severity=2),
            conducive_finding_payload("B3", CONDUCIVE_WOOD_TO_GROUND, severity=1),
        ],
        scheduled_start_at="2027-08-20T09:00:00Z",
        scheduled_end_at="2027-08-20T11:00:00Z",
    )
    set_clock(api, "2027-09-04T00:00:00Z")
    return {
        "property": prop,
        "signer": signer,
        "bond": bond,
        "renewal": renewal,
        "renewal_graph": rgraph,
    }


def _attempt_completion(api, chain, amount_usd):
    """Tender ``amount_usd`` against the pending invoice, returning the raw response."""
    return api.complete_renewal(
        chain["renewal"]["id"],
        renewal_completion_payload(chain["renewal_graph"]["id"], amount_usd),
        MANAGER_HEADERS,
    )


def _reinstate_the_credential(api, chain):
    """Cycle the signer ACTIVE -> EXPIRED -> ACTIVE on a far-future expiry date."""
    signer_id = chain["signer"]["id"]
    set_license_status(api, signer_id, LICENSE_STATUS_EXPIRED)
    return set_license_status(
        api,
        signer_id,
        LICENSE_STATUS_ACTIVE,
        license_expires_on="2029-06-30",
        ce_credits=12,
    )


class TestExpiredLicenceOutranksUnderpayment:
    """POST /bond-renewals/{id}/complete: the compliance failure is reported."""

    def test_the_expired_credential_is_reported_not_the_shortfall(self, api):
        """One call breaks both rules and the licence rule is the one answered.

        PRD 3.8: "The inspector who signed that graph must hold an `ACTIVE`
        licence (`ERR_LICENSE_NOT_ACTIVE`) whose `license_expires_on` is not
        earlier than the clock date (`ERR_LICENSE_EXPIRED`) -- and because
        compliance outranks money, a completion that is both unlicensed and
        underpaid reports the licence failure."

        Design: Difficulty/priority_pair_validation_conflict/expired_licence_outranks_underpayment_on_renewal_completion
        """
        chain = _renewal_awaiting_completion(api)

        # Both rules really are broken: the credential ran out on 2027-08-31,
        # four days before the clock, and 100.00 is far below the repriced total.
        signer = validate_success(
            api.get_inspector(chain["signer"]["id"], OFFICER_HEADERS)
        )
        assert signer["license_expires_on"] == "2027-08-31"
        assert signer["status"] == LICENSE_STATUS_ACTIVE

        error = validate_error(
            _attempt_completion(api, chain, 100.00), ERR_LICENSE_EXPIRED
        )
        assert error["error_id"] != ERR_PAYMENT_INSUFFICIENT
        assert error["error_id"] != ERR_LICENSE_NOT_ACTIVE

    def test_the_outranking_rejection_moves_nothing(self, api):
        """A refused completion neither reprices the invoice nor rolls the term.

        PRD 3.8: "The payment check compares `amount_usd` against **this**
        recomputed total"; only "on success the invoice records the attached
        `inspection_id`, moves to `PAID`".

        Design: Difficulty/priority_pair_validation_conflict/expired_licence_outranks_underpayment_on_renewal_completion
        """
        chain = _renewal_awaiting_completion(api)
        validate_error(_attempt_completion(api, chain, 100.00), ERR_LICENSE_EXPIRED)

        renewal = validate_success(
            api.get_renewal(chain["renewal"]["id"], MANAGER_HEADERS)
        )
        assert_status(renewal, RENEWAL_PENDING, "bond renewal")
        assert renewal["inspection_id"] is None
        assert_renewal_invoice(
            renewal,
            base_renewal_fee_usd=83.17,
            inspection_fee_usd=128.10,
            conducive_surcharge_usd=0.00,
            late_fee_usd=0.00,
            invoice_total_usd=211.27,
        )

        bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
        assert_status(bond, BOND_ACTIVE, "bond")
        assert bond["term_index"] == 1

    def test_the_shortfall_surfaces_once_the_credential_is_good_again(self, api):
        """With the compliance rule satisfied, the money rule answers on its own.

        PRD 3.8: "The payment check compares `amount_usd` against **this**
        recomputed total, not the provisional figure stored earlier; a shortfall
        is `ERR_PAYMENT_INSUFFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/expired_licence_outranks_underpayment_on_renewal_completion
        """
        chain = _renewal_awaiting_completion(api)
        validate_error(_attempt_completion(api, chain, 100.00), ERR_LICENSE_EXPIRED)

        signer = _reinstate_the_credential(api, chain)
        assert signer["status"] == LICENSE_STATUS_ACTIVE
        assert signer["license_expires_on"] == "2029-06-30"

        error = validate_error(
            _attempt_completion(api, chain, 100.00), ERR_PAYMENT_INSUFFICIENT
        )
        assert error["error_id"] != ERR_LICENSE_EXPIRED

    def test_tendering_the_repriced_total_completes_the_renewal(self, api):
        """The repriced total is the provisional pair plus a surcharge and a late fee.

        PRD 3.8: "`conducive_surcharge_usd` becomes 7.335 for each
        conducive-condition notation on the attached renewal graph", and
        "`late_fee_usd` becomes 0.415 for each whole UTC day by which the clock's
        date has passed the bond's `current_term_end`".

        Design: Difficulty/priority_pair_validation_conflict/expired_licence_outranks_underpayment_on_renewal_completion
        """
        chain = _renewal_awaiting_completion(api)
        _reinstate_the_credential(api, chain)

        paid = validate_success(_attempt_completion(api, chain, 227.19))
        assert_status(paid, RENEWAL_PAID, "bond renewal")
        assert paid["inspection_id"] == chain["renewal_graph"]["id"]
        assert_money(paid["amount_paid_usd"], 227.19)
        assert_renewal_invoice(
            paid,
            base_renewal_fee_usd=83.17,
            inspection_fee_usd=128.10,
            conducive_surcharge_usd=14.67,
            late_fee_usd=1.25,
            invoice_total_usd=227.19,
        )

        bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
        assert_status(bond, BOND_ACTIVE, "bond")
        assert bond["term_index"] == 2


# ---------------------------------------------------------------------------
# Pair 2 -- a lapsed bond against a window that has already closed
# ---------------------------------------------------------------------------


def _two_bonds_one_lapsed(api):
    """Two bonds issued the same day, reviewed apart, read at one single instant.

    Both are outside their renewal window at 2027-10-05; only the first has been
    reviewed into LAPSED, so status is the single difference between them.
    """
    first = bonded_property(
        api,
        issue_instant="2026-09-01T00:00:00Z",
        conducive_waiver_codes=[],
        property_overrides={"address_line1": "411 Cypress Row"},
    )
    second = bonded_property(
        api,
        issue_instant="2026-09-01T00:00:00Z",
        conducive_waiver_codes=[],
        property_overrides={"address_line1": "413 Cypress Row"},
    )
    set_clock(api, "2027-10-05T00:00:00Z")
    lapsed = review_bond_term(api, first["bond"]["id"])
    return {"lapsed_bond": lapsed, "active_bond": second["bond"]}


class TestLapsedStateOutranksClosedWindow:
    """POST /bonds/{id}/renewals with both the state and the calendar against it."""

    def test_the_lapsed_bond_reports_its_state_not_its_calendar(self, api):
        """The lapsed bond breaks both rules and the state rule is the one answered.

        PRD 3.8: "The bond must also be `ACTIVE`; a lapsed bond that is
        additionally outside its window reports `ERR_INVALID_BOND_STATE`, because
        the state check outranks the window check."

        Design: Difficulty/priority_pair_validation_conflict/lapsed_bond_state_outranks_closed_renewal_window
        """
        pair = _two_bonds_one_lapsed(api)
        lapsed = pair["lapsed_bond"]

        # Both rules really are broken: the window ran 2027-07-03..2027-10-01
        # inclusive, and the bond is no longer ACTIVE.
        assert_status(lapsed, BOND_LAPSED, "bond")
        assert lapsed["lapse_date"] == "2027-10-01"
        assert lapsed["renewal_window_opens_on"] == "2027-07-03"
        assert lapsed["current_term_end"] == "2027-09-01"

        error = validate_error(
            api.create_renewal(lapsed["id"], {}, MANAGER_HEADERS),
            ERR_INVALID_BOND_STATE,
        )
        assert error["error_id"] != ERR_RENEWAL_WINDOW_NOT_OPEN

    def test_the_still_active_bond_reports_the_closed_window(self, api):
        """Identical in every respect but its status, the second bond answers 114.

        PRD 3.8: "the clock's UTC date must be on or after
        `renewal_window_opens_on` ... and no later than 30 days after
        `current_term_end`, both bounds inclusive ... Outside the window the
        attempt is `ERR_RENEWAL_WINDOW_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/lapsed_bond_state_outranks_closed_renewal_window
        """
        pair = _two_bonds_one_lapsed(api)
        active = validate_success(
            api.get_bond(pair["active_bond"]["id"], MANAGER_HEADERS)
        )
        assert_status(active, BOND_ACTIVE, "bond")
        assert active["current_term_end"] == "2027-09-01"

        error = validate_error(
            api.create_renewal(active["id"], {}, MANAGER_HEADERS),
            ERR_RENEWAL_WINDOW_NOT_OPEN,
        )
        assert error["error_id"] != ERR_INVALID_BOND_STATE

    def test_neither_refusal_opens_an_invoice_or_moves_a_bond(self, api):
        """Two different refusals at one instant, and both are pure rejections.

        PRD 3.8: "Opening an invoice creates a renewal row in status `PENDING`" --
        which only a successful call does, so a refused call leaves the bond's
        renewal collection empty and its version where it stood.

        Design: Difficulty/priority_pair_validation_conflict/lapsed_bond_state_outranks_closed_renewal_window
        """
        pair = _two_bonds_one_lapsed(api)
        lapsed_id = pair["lapsed_bond"]["id"]
        active_id = pair["active_bond"]["id"]

        before_lapsed = validate_success(api.get_bond(lapsed_id, MANAGER_HEADERS))
        before_active = validate_success(api.get_bond(active_id, MANAGER_HEADERS))

        validate_error(
            api.create_renewal(lapsed_id, {}, MANAGER_HEADERS), ERR_INVALID_BOND_STATE
        )
        validate_error(
            api.create_renewal(active_id, {}, MANAGER_HEADERS),
            ERR_RENEWAL_WINDOW_NOT_OPEN,
        )

        for bond_id in (lapsed_id, active_id):
            rows, meta = validate_paginated(
                api.list_renewals(MANAGER_HEADERS, bond_id=bond_id)
            )
            assert meta["total_count"] == 0
            assert rows == []

        after_lapsed = validate_success(api.get_bond(lapsed_id, MANAGER_HEADERS))
        after_active = validate_success(api.get_bond(active_id, MANAGER_HEADERS))
        assert after_lapsed["version"] == before_lapsed["version"]
        assert after_active["version"] == before_active["version"]
