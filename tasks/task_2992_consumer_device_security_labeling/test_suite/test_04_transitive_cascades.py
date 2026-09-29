"""Three-link cascades fired from two unrelated triggers.

A manufacturer's firmware notice reaches an unnamed retailer's participation
tier three hops away, and an upheld adjudication reaches the same place by
crossing a money threshold on the subject's penalty ledger.
"""
from test_helpers import (
    ADMIN_INTAKE_USER_ID,
    DEFAULT_CLOCK,
    api_client,
    assert_case_statuses,
    assert_grant_statuses,
    assert_money_cents,
    assert_penalty_ledger,
    assert_status,
    factories,
    fixtures,
    make_admin_headers,
    validate_success,
)

INTAKE_ADMIN = make_admin_headers(ADMIN_INTAKE_USER_ID)

DISPLAY_FROM = "2026-08-10T00:00:00Z"
DISPLAY_UNTIL = "2026-09-10T00:00:00Z"
SPEC_SUMMARY = "Firmware 1.1.0 replaces the authentication stack."


def _authorization(authorization_id, store):
    return validate_success(
        api_client.get_display_authorization(authorization_id, store.headers)
    )


def _labelled_product_with_two_displays():
    """A live label carrying an IN_STORE and an ONLINE display for one retailer."""
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    sponsor = fixtures.enrol_manufacturer()
    store = fixtures.register_retailer(retailer_name="Cedar Home Retail")
    grant = fixtures.published_grant(
        fixtures.approved_claim(program=program, sponsor=sponsor)
    )
    in_store = fixtures.authorize_display(
        grant, store, channel="IN_STORE", display_from=DISPLAY_FROM, display_until=DISPLAY_UNTIL
    )
    online = fixtures.authorize_display(
        grant, store, channel="ONLINE", display_from=DISPLAY_FROM, display_until=DISPLAY_UNTIL
    )
    store.refresh()
    return grant, store, in_store, online


def _file_spec_change(grant):
    """File the spec-change notice against the labelled product."""
    product = grant.claim.refresh_product()
    response = api_client.create_spec_change(
        product["id"],
        factories.spec_change_payload(
            product["version"],
            change_summary=SPEC_SUMMARY,
            firmware_version="1.1.0",
        ),
        grant.claim.sponsor.headers,
    )
    validate_success(response, 201)
    return product


def _labelled_product_with_noticed_case(unit_count):
    """A live label with one display, plus a noticed case of `unit_count` units."""
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    sponsor = fixtures.enrol_manufacturer()
    store = fixtures.register_retailer(retailer_name="Cedar Home Retail")
    grant = fixtures.published_grant(
        fixtures.approved_claim(program=program, sponsor=sponsor)
    )
    authorization = fixtures.authorize_display(
        grant, store, channel="IN_STORE", display_from=DISPLAY_FROM, display_until=DISPLAY_UNTIL
    )
    store.refresh()
    case = fixtures.open_case(
        sponsor,
        "ZZ-NO-SUCH-CODE3",
        "UNAUTHORIZED_DISPLAY",
        [factories.violation_line("LST-STORE-C", "IN_STORE", unit_count)],
        headers=INTAKE_ADMIN,
        reporter_note="Program mark printed on cartons that never received a grant.",
    )
    fixtures.issue_notice(case, notice_reference="NOT-2026-1003")
    return sponsor, grant, store, authorization, case


class TestSpecChangeSuspendsGrantWithdrawsDisplayAndDemotesRetailer:
    """One firmware notice, three links, an unnamed retailer at the far end."""

    def test_the_notice_stales_the_product_and_suspends_its_active_grant(self):
        """Link 1: the spec revision moves on and the label goes dark.

        PRD: "First, every label grant of this product whose `grant_status` is `ACTIVE` moves to `SUSPENDED`, with `suspension_reason` set to `PRODUCT_SPEC_CHANGED` and `renewal_required` set to true."
        Design: Difficulty/transitive_cascade/spec_change_suspends_grant_withdraws_display_and_demotes_retailer
        """
        grant, _store, _in_store, _online = _labelled_product_with_two_displays()
        before = grant.claim.refresh_product()
        assert before["spec_revision"] == 1, before["spec_revision"]
        assert_status(before, "conformance_currency", "CURRENT")

        _file_spec_change(grant)

        product = grant.claim.refresh_product()
        assert product["spec_revision"] == before["spec_revision"] + 1, product["spec_revision"]
        assert_status(product, "conformance_currency", "STALE")
        assert_status(product, "firmware_version", "1.1.0")
        assert_status(product, "last_change_summary", SPEC_SUMMARY)
        suspended = grant.refresh()
        assert_grant_statuses(suspended, "SUSPENDED", "PUBLISHED")
        assert_status(suspended, "suspension_reason", "PRODUCT_SPEC_CHANGED")
        assert suspended["renewal_required"] is True, suspended["renewal_required"]

    def test_the_suspension_withdraws_every_authorized_display_of_that_grant(self):
        """Link 2: both surfaces come down with a cascade-specific reason.

        PRD: "Second, caused by the first link, every retailer display authorization of each newly suspended grant whose `status` is `AUTHORIZED` moves to `WITHDRAWN` with `withdrawal_reason` set to `GRANT_SUSPENDED`."
        Design: Difficulty/transitive_cascade/spec_change_suspends_grant_withdraws_display_and_demotes_retailer
        """
        grant, store, in_store, online = _labelled_product_with_two_displays()
        for authorization in (in_store, online):
            assert_status(_authorization(authorization["id"], store), "status", "AUTHORIZED")

        _file_spec_change(grant)

        for authorization in (in_store, online):
            withdrawn = _authorization(authorization["id"], store)
            assert_status(withdrawn, "status", "WITHDRAWN")
            assert_status(withdrawn, "withdrawal_reason", "GRANT_SUSPENDED")

    def test_the_withdrawals_recount_the_retailer_and_demote_its_tier(self):
        """Link 3: a retailer never named in the request drops from GOLD to BASELINE.

        PRD: "Third, caused by the second link, each affected retailer's `active_display_count` is recounted and its `participation_tier` re-derived by the rule in §3.8."
        Design: Difficulty/transitive_cascade/spec_change_suspends_grant_withdraws_display_and_demotes_retailer
        """
        grant, store, _in_store, _online = _labelled_product_with_two_displays()
        before = store.refresh()
        assert before["active_display_count"] == 2, before["active_display_count"]
        assert_status(before, "participation_tier", "GOLD")

        _file_spec_change(grant)

        after = store.refresh()
        assert after["active_display_count"] == 0, after["active_display_count"]
        assert_status(after, "participation_tier", "BASELINE")


class TestUpheldAdjudicationDelinquencySuspendsAllManufacturerGrants:
    """A money threshold on the ledger reaches the retailer's shelf."""

    def test_the_upheld_penalty_recomputes_the_ledger_and_turns_standing_delinquent(self):
        """Link 1 and 2: 28980 cents outstanding crosses the 25000 threshold.

        PRD: "Then `standing` is derived in this fixed order: a manufacturer whose `upheld_case_count` is 3 or more is `BARRED`; failing that, a manufacturer whose `outstanding_penalty_cents` is 25000 or more is `DELINQUENT`; every other manufacturer is `GOOD`."
        Design: Difficulty/transitive_cascade/upheld_adjudication_delinquency_suspends_all_manufacturer_grants
        """
        sponsor, _grant, _store, _authorization_row, case = _labelled_product_with_noticed_case(6)

        upheld = fixtures.adjudicate(case, "UPHELD")

        assert_case_statuses(upheld, "ADJUDICATED_UPHELD", "ASSESSED")
        assert upheld["code_matches_registry"] is False, upheld["code_matches_registry"]
        assert_money_cents(upheld["penalty_cents"], 28980, "penalty_cents")
        ledger = sponsor.refresh()
        assert_penalty_ledger(ledger, outstanding=28980, paid=0, vacated=0)
        assert_money_cents(
            ledger["total_assessed_penalty_cents"], 28980, "total_assessed_penalty_cents"
        )
        assert ledger["upheld_case_count"] == 1, ledger["upheld_case_count"]
        assert_status(ledger, "standing", "DELINQUENT")

    def test_the_delinquent_standing_darkens_the_label_and_clears_the_shelf(self):
        """Link 3: the grant suspends for a fiscal reason and the display comes down.

        PRD: "And because the standing changed, every label grant belonging to every product of that subject whose `grant_status` is `ACTIVE` moves to `SUSPENDED` with `suspension_reason` set to `SPONSOR_DELINQUENT` and `renewal_required` set to false; each of those grants' `AUTHORIZED` display authorizations moves to `WITHDRAWN` with `withdrawal_reason` set to `GRANT_SUSPENDED`; and every retailer touched has its `active_display_count` recounted and its `participation_tier` re-derived."
        Design: Difficulty/transitive_cascade/upheld_adjudication_delinquency_suspends_all_manufacturer_grants
        """
        _sponsor, grant, store, authorization_row, case = _labelled_product_with_noticed_case(6)

        fixtures.adjudicate(case, "UPHELD")

        suspended = grant.refresh()
        assert_grant_statuses(suspended, "SUSPENDED", "PUBLISHED")
        assert_status(suspended, "suspension_reason", "SPONSOR_DELINQUENT")
        assert suspended["renewal_required"] is False, suspended["renewal_required"]
        withdrawn = _authorization(authorization_row["id"], store)
        assert_status(withdrawn, "status", "WITHDRAWN")
        assert_status(withdrawn, "withdrawal_reason", "GRANT_SUSPENDED")
        retailer = store.refresh()
        assert retailer["active_display_count"] == 0, retailer["active_display_count"]
        assert_status(retailer, "participation_tier", "BASELINE")
        assert_status(grant.claim.refresh_product(), "conformance_currency", "CURRENT")

    def test_a_penalty_below_the_threshold_stops_after_the_ledger_hop(self):
        """24150 cents on five units leaves the standing GOOD and the label lit.

        PRD: "When the recomputed `standing` is anything other than `GOOD`, the consequences reach out across the program in three linked steps."
        Design: Difficulty/transitive_cascade/upheld_adjudication_delinquency_suspends_all_manufacturer_grants
        """
        sponsor, grant, store, authorization_row, case = _labelled_product_with_noticed_case(5)

        upheld = fixtures.adjudicate(case, "UPHELD")

        assert_money_cents(upheld["penalty_cents"], 24150, "penalty_cents")
        ledger = sponsor.refresh()
        assert_penalty_ledger(ledger, outstanding=24150, paid=0, vacated=0)
        assert_status(ledger, "standing", "GOOD")
        still_live = grant.refresh()
        assert_grant_statuses(still_live, "ACTIVE", "PUBLISHED")
        assert still_live["suspension_reason"] is None, still_live["suspension_reason"]
        assert_status(_authorization(authorization_row["id"], store), "status", "AUTHORIZED")
        retailer = store.refresh()
        assert retailer["active_display_count"] == 1, retailer["active_display_count"]
