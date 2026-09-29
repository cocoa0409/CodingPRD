"""State-machine behaviour of label grants, registry entries and shelf displays.

These scenarios exercise the clock-driven edges of the program: the expiry sweep
starting a booked bench window, the first publication bringing a label alive, the
support-period suspension that carves a tail out of a still-valid window, the
expiry cascade that pulls displays off the shelf, and the penalty payment that
reinstates a darkened grant without reinstating the display.
"""
from test_helpers import (
    ADMIN,
    ADMIN_2_USER_ID,
    CONSUMER_HEADERS,
    DEFAULT_CLOCK,
    PUBLISHER,
    REVIEWER,
    REVIEWER_2_USER_ID,
    api_client,
    assert_bench_hour_ledger,
    assert_case_statuses,
    assert_grant_statuses,
    assert_instant_equals,
    assert_money_cents,
    assert_penalty_ledger,
    assert_score,
    assert_status,
    factories,
    fixtures,
    make_admin_headers,
    validate_success,
    validate_unpaginated,
)

# Four equally weighted self-declared criteria, one per practice area: a claim
# that declares conformance with all four scores 100.00 and grades A.
SELF_DECLARED_CATALOGUE = [
    {
        "criterion_code": "AUTH-1",
        "practice_area": "AUTHENTICATION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Unique per-device credentials",
    },
    {
        "criterion_code": "UPD-1",
        "practice_area": "SOFTWARE_UPDATE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Signed firmware updates",
    },
    {
        "criterion_code": "DAT-1",
        "practice_area": "DATA_PROTECTION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Encryption of data at rest",
    },
    {
        "criterion_code": "VLN-1",
        "practice_area": "VULN_DISCLOSURE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Published disclosure contact",
    },
]

LONG_SUPPORT_PRODUCT = {
    "model_name": "Speaker One",
    "sku": "SPK-001",
    "firmware_version": "1.0.0",
    "declared_support_period_end": "2029-08-01T00:00:00Z",
    "update_policy_disclosed": True,
    "retail_units_shipped": 1000,
}
SHORT_SUPPORT_PRODUCT = dict(
    LONG_SUPPORT_PRODUCT, declared_support_period_end="2027-03-01T00:00:00Z"
)

REGISTRY_CONTENT = {
    "update_policy_url": "https://acme.example/updates",
    "update_cadence": "AUTOMATIC",
    "vuln_disclosure_contact": "security@acme.example",
}

CLOCK_AT_PUBLICATION = DEFAULT_CLOCK
BENCH_WINDOW_START = "2026-08-10T09:00:00Z"


def _program(tier_overrides=None):
    """A self-attestation tier whose category demands only 180 days of support."""
    return fixtures.create_program(
        "SELF_ATTESTATION",
        tier_overrides=dict({"min_overall_score": 70.00}, **(tier_overrides or {})),
        category_overrides={"min_support_period_days": 180},
        criteria=SELF_DECLARED_CATALOGUE,
    )


def _acme():
    return fixtures.enrol_manufacturer(
        legal_name="Acme Devices",
        contact_email="ops@acme.example",
        annual_us_revenue_cents=900000000,
    )


def _megamart():
    return fixtures.register_retailer(retailer_name="MegaMart")


def _approved_claim(program, product_overrides):
    """A SELF_ATTESTATION claim approved by reviewer-1 at score 100.00."""
    sponsor = _acme()
    product = fixtures.register_product(program, sponsor, **product_overrides)
    assessment = fixtures.open_assessment(program, sponsor, product)
    claim = fixtures.Claim(
        program=program, sponsor=sponsor, product=product, assessment=assessment
    )
    claim.responses = fixtures.attach_responses(program, sponsor, assessment)
    fixtures.submit_claim(claim)
    fixtures.decide_claim(claim, "APPROVED", REVIEWER)
    claim.refresh_product()
    return claim


def _grant_with_entry(claim):
    """A grant at PENDING_REGISTRY/DRAFT already carrying its registry content."""
    grant = fixtures.issue_grant(claim)
    fixtures.supply_registry_entry(grant, **REGISTRY_CONTENT)
    return grant


def _publish(grant, headers=None):
    """Publish the registry entry, asserting the 201 the endpoint promises."""
    grant.label_grant = validate_success(
        api_client.decide_registry_publication(
            grant.id,
            factories.publication_payload("PUBLISHED", publication_note="Registry content verified"),
            headers or PUBLISHER,
        ),
        201,
    )
    return grant


def _live_grant(product_overrides=None, tier_overrides=None):
    """An ACTIVE/PUBLISHED grant whose window opened on the default clock."""
    claim = _approved_claim(_program(tier_overrides), product_overrides or LONG_SUPPORT_PRODUCT)
    return _publish(_grant_with_entry(claim))


def _authorize(grant, store, channel, display_from, display_until):
    return validate_success(
        api_client.create_display_authorization(
            factories.create_display_authorization_payload(
                store.id, grant.id, display_from, display_until, channel=channel
            ),
            store.headers,
        ),
        201,
    )


def _sweep():
    """Run the administrator-only expiry sweep, asserting its 200 response."""
    return validate_success(api_client.run_expiry_sweep(ADMIN), 200)


def _entry_of(grant):
    entries = validate_unpaginated(api_client.get_registry_entry(grant.id, ADMIN))
    assert len(entries) == 1, f"expected exactly one registry entry, got {len(entries)}"
    return entries[0]


def _authorization(authorization_id):
    return validate_success(api_client.get_display_authorization(authorization_id, ADMIN))


# The sweep's engagement edge is inclusive at `window_start`, and it is the one
# sweep edge that moves a status without touching a ledger.
class TestSweepStartsTheScheduledEngagement:

    @staticmethod
    def _booked():
        fixtures.reset_clock()
        program = _program()
        sponsor = _acme()
        lab = fixtures.register_lab(lab_name="Northline Labs", total_bench_hours=200)
        product = fixtures.register_product(program, sponsor, **LONG_SUPPORT_PRODUCT)
        assessment = fixtures.open_assessment(program, sponsor, product)
        engagement = validate_success(
            api_client.create_test_engagement(
                factories.create_test_engagement_payload(
                    assessment["id"],
                    lab.id,
                    window_start=BENCH_WINDOW_START,
                    window_end="2026-08-12T09:00:00Z",
                    bench_hours=8,
                ),
                sponsor.headers,
            ),
            201,
        )
        fixtures.set_clock(BENCH_WINDOW_START)
        return lab, engagement

    def test_the_sweep_starts_the_engagement_at_exactly_its_window_start(self):
        """With the clock parked on `window_start` the sweep reports one engagement started and moves it to IN_PROGRESS.

        PRD: "Every test engagement whose `status` is `SCHEDULED` and whose `window_start` is at or before the logical clock moves `SCHEDULED → IN_PROGRESS`, leaving the laboratory's bench reservation untouched."
        Design: Corner/state_machines/valid_transition_sweep_advances_scheduled_engagement_at_the_inclusive_window_start
        """
        _lab, engagement = self._booked()

        report = _sweep()
        assert report["engagements_started"] == 1, report
        assert report["grants_expired"] == 0, report
        assert report["grants_suspended"] == 0, report
        assert report["authorizations_expired"] == 0, report

        started = validate_success(api_client.get_test_engagement(engagement["id"], ADMIN))
        assert_status(started, "status", "IN_PROGRESS")
        assert started["completed_at"] is None, started["completed_at"]

    def test_starting_the_engagement_leaves_the_bench_reservation_untouched(self):
        """SCHEDULED and IN_PROGRESS are both reserving states, so the eight hours stay reserved.

        PRD: "That transition leaves the laboratory's ledger completely unchanged, because `SCHEDULED` and `IN_PROGRESS` are both reserving states."
        Design: Corner/state_machines/valid_transition_sweep_advances_scheduled_engagement_at_the_inclusive_window_start
        """
        lab, _engagement = self._booked()

        _sweep()

        lab_row = lab.refresh()
        assert_bench_hour_ledger(lab_row, reserved=8)
        assert lab_row["available_bench_hours"] == 192, lab_row["available_bench_hours"]


# The first publication is a single decision with four side effects: both status
# dimensions move, the validity window is stamped, the entry is stamped, and the
# public page starts resolving.
class TestFirstPublicationActivatesTheGrant:

    def test_publication_moves_both_status_dimensions_at_once(self):
        """One PUBLISHED decision drives DRAFT to PUBLISHED and PENDING_REGISTRY to ACTIVE together.

        PRD: "On the publication dimension it drives `DRAFT → PUBLISHED`; on the grant dimension it drives `PENDING_REGISTRY → ACTIVE`."
        Design: Corner/state_machines/side_effect_execution_registry_publication_activates_grant_and_stamps_the_window
        """
        fixtures.reset_clock()
        grant = _live_grant()

        published = validate_success(api_client.get_label_grant(grant.id, ADMIN))
        assert_grant_statuses(published, "ACTIVE", "PUBLISHED")
        assert published["suspension_reason"] is None, published["suspension_reason"]
        assert published["renewal_required"] is False, published["renewal_required"]

    def test_publication_stamps_the_validity_window_from_the_logical_clock(self):
        """`valid_from` is the publication instant and `valid_until` is 365 exact days later.

        PRD: "A label's life begins at `valid_from`, the logical-clock instant of its first publication, and its nominal end is `valid_until`, computed by adding the program tier's `label_validity_days` to `valid_from` as that many exact periods of 86400 seconds."
        Design: Corner/state_machines/side_effect_execution_registry_publication_activates_grant_and_stamps_the_window
        """
        fixtures.reset_clock()
        grant = _live_grant()

        published = validate_success(api_client.get_label_grant(grant.id, ADMIN))
        assert_instant_equals(published["valid_from"], CLOCK_AT_PUBLICATION, "valid_from")
        assert_instant_equals(published["valid_until"], "2027-08-01T00:00:00.000Z", "valid_until")

    def test_the_issuance_fee_sits_in_the_no_surcharge_band(self):
        """A 40000-cent base fee with no renewal supplement is below 50000, so the fee is exactly the subtotal.

        PRD: "Then select the surcharge rate from that subtotal, exactly once and with no iteration: a subtotal below 50000 cents attracts no surcharge, a subtotal from 50000 cents up to but not including 150000 cents attracts 10 percent, and a subtotal of 150000 cents or more attracts 18 percent."
        Design: Corner/state_machines/side_effect_execution_registry_publication_activates_grant_and_stamps_the_window
        """
        fixtures.reset_clock()
        grant = _live_grant()

        published = validate_success(api_client.get_label_grant(grant.id, ADMIN))
        assert_money_cents(published["issuance_fee_cents"], 40000, "issuance_fee_cents")
        assert published["renewal_generation"] == 0, published["renewal_generation"]

    def test_publication_stamps_the_registry_entry_with_the_acting_reviewer(self):
        """The entry records the publication instant and the publishing reviewer, and discloses completely.

        PRD: "It stamps `valid_from` from the logical clock and computes `valid_until` per §3.7, stamps the registry entry's `published_at` from the logical clock and its `published_by_user_id` from the acting reviewer, and makes the public registry lookup resolve for this grant's `scannable_code`."
        Design: Corner/state_machines/side_effect_execution_registry_publication_activates_grant_and_stamps_the_window
        """
        fixtures.reset_clock()
        grant = _live_grant()

        entry = _entry_of(grant)
        assert_instant_equals(entry["published_at"], CLOCK_AT_PUBLICATION, "published_at")
        assert entry["published_by_user_id"] == REVIEWER_2_USER_ID, entry["published_by_user_id"]
        assert_status(entry, "disclosure_completeness", "COMPLETE")

    def test_the_entry_discloses_the_snapshotted_support_period(self):
        """`support_period_end` is the product's declared commitment frozen at entry creation.

        PRD: "`support_period_end` is not supplied — it is snapshotted from the product's `declared_support_period_end` at the moment the entry is created, freezing the support commitment the registry discloses even if the product's own declaration later moves."
        Design: Corner/state_machines/side_effect_execution_registry_publication_activates_grant_and_stamps_the_window
        """
        fixtures.reset_clock()
        grant = _live_grant()

        entry = _entry_of(grant)
        assert_instant_equals(entry["support_period_end"], "2029-08-01T00:00:00.000Z", "support_period_end")

    def test_the_public_page_resolves_for_the_scannable_code_after_publication(self):
        """The shopper's scan now resolves, carrying the decided score and grade of the backing claim.

        PRD: "Given a `scannable_code`, it returns that code alongside the product's `model_name`, the sponsor's `manufacturer_legal_name`, the `device_category_code` and `program_tier_code` describing the regulatory context, the assessment's `grade` and `decided_overall_score`, the grant's `valid_from`, `valid_until` and `grant_status`, and the registry entry's `support_period_end`, `update_policy_url`, `update_cadence` and `vuln_disclosure_contact`."
        Design: Corner/state_machines/side_effect_execution_registry_publication_activates_grant_and_stamps_the_window
        """
        fixtures.reset_clock()
        grant = _live_grant()

        page = validate_success(api_client.scan_registry(grant.scannable_code, CONSUMER_HEADERS), 200)
        assert page["scannable_code"] == grant.scannable_code
        assert_status(page, "grade", "A")
        assert_score(page["decided_overall_score"], 100.00, "decided_overall_score")
        assert_status(page, "grant_status", "ACTIVE")


# A 730-day label over a support commitment that ends in March 2027 has a
# suspended tail: the sweep darkens the label without moving `valid_until`.
class TestSupportPeriodEndSuspendsTheGrantMidWindow:

    @staticmethod
    def _swept():
        fixtures.reset_clock()
        grant = _live_grant(
            SHORT_SUPPORT_PRODUCT,
            {"tier_code": "TIER_1_LONG", "label_validity_days": 730},
        )
        store = _megamart()
        online = _authorize(grant, store, "ONLINE", "2026-09-01T00:00:00Z", "2027-06-30T00:00:00Z")
        in_store = _authorize(grant, store, "IN_STORE", "2026-09-01T00:00:00Z", "2027-06-30T00:00:00Z")
        before = store.refresh()
        fixtures.set_clock("2027-03-01T00:00:00Z")
        report = _sweep()
        return {
            "grant": grant,
            "store": store,
            "online": online,
            "in_store": in_store,
            "before": before,
            "report": report,
        }

    def test_the_sweep_suspends_the_grant_when_the_support_commitment_lapses(self):
        """A sweep at `support_period_end` moves the still-valid grant to SUSPENDED and demands a renewal.

        PRD: "Every grant whose `grant_status` is `ACTIVE`, whose registry entry's `support_period_end` is at or before the logical clock, and whose `valid_until` is still strictly after the logical clock, moves `ACTIVE → SUSPENDED` with `suspension_reason` set to `SUPPORT_PERIOD_ENDED` and `renewal_required` set to true, and each of its `AUTHORIZED` display authorizations moves to `WITHDRAWN` with `withdrawal_reason` set to `GRANT_SUSPENDED`."
        Design: Corner/state_machines/conditional_cascade_support_period_end_suspends_the_grant_mid_window
        """
        state = self._swept()
        report = state["report"]
        assert report["grants_suspended"] == 1, report
        assert report["grants_expired"] == 0, report
        assert report["authorizations_expired"] == 0, report

        suspended = validate_success(api_client.get_label_grant(state["grant"].id, ADMIN))
        assert_grant_statuses(suspended, "SUSPENDED", "PUBLISHED")
        assert_status(suspended, "suspension_reason", "SUPPORT_PERIOD_ENDED")
        assert suspended["renewal_required"] is True, suspended["renewal_required"]

    def test_the_lapsed_support_commitment_does_not_shorten_the_validity_window(self):
        """`valid_until` stays 730 exact days after `valid_from` even though the label is now dark.

        PRD: "The registry entry's `support_period_end` does **not** shorten `valid_until`."
        Design: Corner/state_machines/conditional_cascade_support_period_end_suspends_the_grant_mid_window
        """
        state = self._swept()

        suspended = validate_success(api_client.get_label_grant(state["grant"].id, ADMIN))
        assert_instant_equals(suspended["valid_from"], CLOCK_AT_PUBLICATION, "valid_from")
        assert_instant_equals(suspended["valid_until"], "2028-07-31T00:00:00.000Z", "valid_until")
        entry = _entry_of(state["grant"])
        assert_instant_equals(entry["support_period_end"], "2027-03-01T00:00:00.000Z", "support_period_end")

    def test_the_suspension_withdraws_both_displays_and_demotes_the_retailer(self):
        """Both channels are withdrawn as GRANT_SUSPENDED, dropping the retailer from GOLD to BASELINE.

        PRD: "Then `participation_tier` is chosen: a retailer whose `education_materials_ack` is true and whose `active_display_count` is 5 or more is `PLATINUM`; failing that, a retailer whose `education_materials_ack` is true and whose `active_display_count` is 2 or more is `GOLD`; every other retailer is `BASELINE`."
        Design: Corner/state_machines/conditional_cascade_support_period_end_suspends_the_grant_mid_window
        """
        state = self._swept()
        assert state["before"]["active_display_count"] == 2, state["before"]
        assert_status(state["before"], "participation_tier", "GOLD")

        for authorization in (state["online"], state["in_store"]):
            withdrawn = _authorization(authorization["id"])
            assert_status(withdrawn, "status", "WITHDRAWN")
            assert_status(withdrawn, "withdrawal_reason", "GRANT_SUSPENDED")
        after = state["store"].refresh()
        assert after["active_display_count"] == 0, after["active_display_count"]
        assert_status(after, "participation_tier", "BASELINE")


# At exactly `valid_until` the label expires, and the displays that ran right up
# to that instant are withdrawn rather than expired.
class TestExpirySweepEndsTheLabelAndItsDisplays:

    @staticmethod
    def _swept():
        fixtures.reset_clock()
        grant = _live_grant()
        store = _megamart()
        online = _authorize(grant, store, "ONLINE", "2026-09-01T00:00:00Z", "2027-08-01T00:00:00Z")
        in_store = _authorize(grant, store, "IN_STORE", "2026-09-01T00:00:00Z", "2027-08-01T00:00:00Z")
        before = store.refresh()
        fixtures.set_clock("2027-08-01T00:00:00Z")
        report = _sweep()
        return {
            "grant": grant,
            "store": store,
            "online": online,
            "in_store": in_store,
            "before": before,
            "report": report,
        }

    def test_the_sweep_expires_the_grant_at_exactly_its_valid_until(self):
        """A sweep with the clock on `valid_until` expires the grant and clears any suspension reason.

        PRD: "Every grant whose `grant_status` is `ACTIVE` or `SUSPENDED` and whose `valid_until` is at or before the logical clock moves to `EXPIRED`, with `renewal_required` set to true and `suspension_reason` cleared to null."
        Design: Corner/state_machines/cascade_down_expiry_sweep_expires_grant_and_withdraws_its_displays
        """
        state = self._swept()
        report = state["report"]
        assert report["grants_expired"] == 1, report
        assert report["grants_suspended"] == 0, report
        assert report["authorizations_expired"] == 0, report

        expired = validate_success(api_client.get_label_grant(state["grant"].id, ADMIN))
        assert_status(expired, "grant_status", "EXPIRED")
        assert expired["renewal_required"] is True, expired["renewal_required"]
        assert expired["suspension_reason"] is None, expired["suspension_reason"]

    def test_the_expiring_grant_withdraws_its_displays_rather_than_expiring_them(self):
        """A display running to exactly `valid_until` is WITHDRAWN as GRANT_EXPIRED, never EXPIRED.

        PRD: "This is the only way an authorization reaches `EXPIRED`: a grant-driven ending always produces `WITHDRAWN` instead, with the reason recording which kind of ending it was."
        Design: Corner/state_machines/cascade_down_expiry_sweep_expires_grant_and_withdraws_its_displays
        """
        state = self._swept()
        assert state["before"]["active_display_count"] == 2, state["before"]
        assert_status(state["before"], "participation_tier", "GOLD")

        for authorization in (state["online"], state["in_store"]):
            withdrawn = _authorization(authorization["id"])
            assert_status(withdrawn, "status", "WITHDRAWN")
            assert_status(withdrawn, "withdrawal_reason", "GRANT_EXPIRED")
        after = state["store"].refresh()
        assert after["active_display_count"] == 0, after["active_display_count"]
        assert_status(after, "participation_tier", "BASELINE")

    def test_expiry_leaves_the_publication_dimension_where_it_was(self):
        """The public page keeps resolving after expiry, now reporting `grant_status` EXPIRED.

        PRD: "A single edge couples them — the first publication of the registry entry is what moves the grant out of `PENDING_REGISTRY` — and beyond that edge each dimension advances on its own."
        Design: Corner/state_machines/cascade_down_expiry_sweep_expires_grant_and_withdraws_its_displays
        """
        state = self._swept()

        expired = validate_success(api_client.get_label_grant(state["grant"].id, ADMIN))
        assert_grant_statuses(expired, "EXPIRED", "PUBLISHED")
        page = validate_success(
            api_client.scan_registry(state["grant"].scannable_code, CONSUMER_HEADERS), 200
        )
        assert_status(page, "grant_status", "EXPIRED")


# Paying an assessed penalty compensates exactly the part of the delinquency
# cascade the ledger owns: the grant comes back, the shelf does not.
class TestPenaltyPaymentReinstatesTheGrantOnly:
    FABRICATED_CODE = "ZZ-NO-SUCH-CD004"
    PAYMENT_REFERENCE = "PAY-2026-77"

    @classmethod
    def _paid(cls):
        fixtures.reset_clock()
        grant = _live_grant()
        sponsor = grant.claim.sponsor
        store = _megamart()
        authorization = _authorize(
            grant, store, "ONLINE", "2026-09-01T00:00:00Z", "2026-12-31T00:00:00Z"
        )
        case = fixtures.open_case(
            sponsor,
            reported_scannable_code=cls.FABRICATED_CODE,
            violation_type="UNAUTHORIZED_DISPLAY",
            violation_line_items=[factories.violation_line("LST-1", "ONLINE", 6)],
            reporter_note="Label art on an unlisted model",
        )
        fixtures.issue_notice(case, ADMIN, notice_reference="NOT-2026-0010")
        upheld = fixtures.adjudicate(case, "UPHELD", make_admin_headers(ADMIN_2_USER_ID))
        suspended = validate_success(api_client.get_label_grant(grant.id, ADMIN))
        delinquent = sponsor.refresh()
        paid = validate_success(
            api_client.pay_penalty(
                case["id"],
                factories.penalty_payment_payload(payment_reference=cls.PAYMENT_REFERENCE),
                sponsor.headers,
            ),
            201,
        )
        return {
            "grant": grant,
            "sponsor": sponsor,
            "store": store,
            "authorization": authorization,
            "case": case,
            "upheld": upheld,
            "suspended": suspended,
            "delinquent": delinquent,
            "paid": paid,
        }

    def test_the_upheld_penalty_follows_the_statutory_schedule_for_a_small_subject(self):
        """One ONLINE line of six units at 4200 cents with a first-offender multiplier assesses 34020 cents.

        PRD: "Then walk `violation_line_items` in declared array order, and for each line multiply that per-unit amount by the line's `unit_count`, by the aggravation multiplier, and by the channel factor for the line's `channel` — 1.15 for `IN_STORE`, 1.35 for `ONLINE`."
        Design: Corner/state_machines/compensation_penalty_payment_reinstates_the_grant_but_not_the_display
        """
        state = self._paid()

        case = validate_success(api_client.get_enforcement_case(state["case"]["id"], ADMIN))
        assert_status(case, "penalty_variant", "STATUTORY_SCHEDULE")
        assert_score(case["aggravation_multiplier"], 1.00, "aggravation_multiplier")
        assert_money_cents(case["penalty_cents"], 34020, "penalty_cents")
        assert case["code_matches_registry"] is False, case["code_matches_registry"]
        assert case["violation_unit_count"] == 6, case["violation_unit_count"]

    def test_payment_moves_the_amount_from_outstanding_to_paid(self):
        """The case reaches ADJUDICATED_UPHELD/PAID and the ledger conserves the 34020 cents it already assessed.

        PRD: "Payment moves `penalty_status` from `ASSESSED` to `PAID`, which moves the amount out of `outstanding_penalty_cents` and into `paid_penalty_cents` with `total_assessed_penalty_cents` unchanged, and re-derives `standing`."
        Design: Corner/state_machines/compensation_penalty_payment_reinstates_the_grant_but_not_the_display
        """
        state = self._paid()
        assert_penalty_ledger(state["delinquent"], outstanding=34020, paid=0, vacated=0)
        assert_status(state["delinquent"], "standing", "DELINQUENT")

        case = validate_success(api_client.get_enforcement_case(state["case"]["id"], ADMIN))
        assert_case_statuses(case, "ADJUDICATED_UPHELD", "PAID")
        assert case["payment_reference"] == self.PAYMENT_REFERENCE, case["payment_reference"]
        manufacturer = state["sponsor"].refresh()
        assert_penalty_ledger(manufacturer, outstanding=0, paid=34020, vacated=0)
        assert_money_cents(
            manufacturer["total_assessed_penalty_cents"], 34020, "total_assessed_penalty_cents"
        )

    def test_payment_does_not_reduce_the_upheld_case_count(self):
        """Settling the money leaves the upheld count at one, and the recovered standing is GOOD.

        PRD: "Note that paying does **not** reduce `upheld_case_count`, so a subject with three upheld cases stays `BARRED` no matter how much it pays; only a vacate reduces that count."
        Design: Corner/state_machines/compensation_penalty_payment_reinstates_the_grant_but_not_the_display
        """
        state = self._paid()

        manufacturer = state["sponsor"].refresh()
        assert manufacturer["upheld_case_count"] == 1, manufacturer["upheld_case_count"]
        assert_status(manufacturer, "standing", "GOOD")

    def test_clearing_the_delinquency_reinstates_the_suspended_grant(self):
        """The grant suspended as SPONSOR_DELINQUENT returns to ACTIVE with its reason cleared.

        PRD: "If that clears the delinquency and brings the standing back to `GOOD`, grants suspended with `suspension_reason` `SPONSOR_DELINQUENT` and `renewal_required` false return to `ACTIVE`."
        Design: Corner/state_machines/compensation_penalty_payment_reinstates_the_grant_but_not_the_display
        """
        state = self._paid()
        assert_status(state["suspended"], "grant_status", "SUSPENDED")
        assert_status(state["suspended"], "suspension_reason", "SPONSOR_DELINQUENT")
        assert state["suspended"]["renewal_required"] is False, state["suspended"]["renewal_required"]

        reinstated = validate_success(api_client.get_label_grant(state["grant"].id, ADMIN))
        assert_grant_statuses(reinstated, "ACTIVE", "PUBLISHED")
        assert reinstated["suspension_reason"] is None, reinstated["suspension_reason"]

    def test_the_display_withdrawn_by_the_suspension_is_not_brought_back(self):
        """The withdrawn authorization stays WITHDRAWN as GRANT_SUSPENDED and the retailer stays at zero displays.

        PRD: "As §2.11 warns, reinstatement is deliberately asymmetric with the suspension cascade: display authorizations withdrawn when the grant was suspended are **not** brought back, and a retailer that wants to display the label again must request a fresh authorization."
        Design: Corner/state_machines/compensation_penalty_payment_reinstates_the_grant_but_not_the_display
        """
        state = self._paid()

        authorization = _authorization(state["authorization"]["id"])
        assert_status(authorization, "status", "WITHDRAWN")
        assert_status(authorization, "withdrawal_reason", "GRANT_SUSPENDED")
        retailer = state["store"].refresh()
        assert retailer["active_display_count"] == 0, retailer["active_display_count"]
        assert_status(retailer, "participation_tier", "BASELINE")
