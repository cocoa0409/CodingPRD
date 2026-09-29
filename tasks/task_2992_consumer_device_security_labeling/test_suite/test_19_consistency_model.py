"""Immediate consistency: a publication is fully visible to the very next request.

Nothing about activation is deferred to a sweep or a later refresh, so the
publication response itself already carries the window and every neighbouring
aggregate reads the activated label at once.
"""
from test_helpers import (
    DEFAULT_CLOCK,
    PUBLISHER,
    REVIEWER_2_USER_ID,
    api_client,
    assert_instant_equals,
    assert_score,
    assert_status,
    assert_grant_statuses,
    factories,
    fixtures,
    make_consumer_headers,
    plus_days,
    validate_success,
    validate_unpaginated,
)

DESIGN_CRITERIA = [
    {"criterion_code": "AUTH-1", "practice_area": "AUTHENTICATION", "weight": 10,
     "requires_lab_verification": False, "criterion_text": "Unique per-device credentials"},
    {"criterion_code": "UPD-1", "practice_area": "SOFTWARE_UPDATE", "weight": 10,
     "requires_lab_verification": False, "criterion_text": "Signed firmware updates"},
    {"criterion_code": "DAT-1", "practice_area": "DATA_PROTECTION", "weight": 10,
     "requires_lab_verification": False, "criterion_text": "Encryption of data at rest"},
    {"criterion_code": "VLN-1", "practice_area": "VULN_DISCLOSURE", "weight": 10,
     "requires_lab_verification": False, "criterion_text": "Published disclosure contact"},
]
PRODUCT = {"model_name": "Speaker One", "sku": "SPK-001", "firmware_version": "1.0.0",
           "declared_support_period_end": "2029-08-01T00:00:00Z",
           "update_policy_disclosed": True, "retail_units_shipped": 1000}
REGISTRY_CONTENT = {"update_policy_url": "https://acme.example/updates",
                    "update_cadence": "AUTOMATIC",
                    "vuln_disclosure_contact": "security@acme.example"}
VALID_UNTIL = plus_days(DEFAULT_CLOCK, 365)
DISPLAY_FROM = "2026-08-01T00:00:00Z"
DISPLAY_UNTIL = "2027-07-01T00:00:00Z"
CONSUMER = make_consumer_headers()


class TestPublicationIsImmediatelyVisible:
    """The label comes alive inside the publication call, not in some later pass."""

    def _pending_world(self):
        fixtures.reset_clock()
        program = fixtures.create_program(
            "SELF_ATTESTATION",
            tier_overrides={"min_overall_score": 70.00},
            category_overrides={"min_support_period_days": 180},
            criteria=DESIGN_CRITERIA,
        )
        sponsor = fixtures.enrol_manufacturer(
            legal_name="Acme Devices",
            contact_email="ops@acme.example",
            enterprise_class="SMALL",
            annual_us_revenue_cents=900000000,
        )
        store = fixtures.register_retailer(retailer_name="MegaMart")
        claim = fixtures.approved_claim(
            program=program, sponsor=sponsor, product_overrides=dict(PRODUCT)
        )
        grant = fixtures.pending_grant(claim, **REGISTRY_CONTENT)
        return grant, store

    def _publish(self, grant):
        return validate_success(
            api_client.decide_registry_publication(
                grant.id,
                factories.publication_payload("PUBLISHED", publication_note="Registry content verified"),
                PUBLISHER,
            ),
            201,
        )

    def test_the_publication_response_already_carries_the_activated_window(self):
        """No second read is needed: 201 returns ACTIVE, PUBLISHED and both instants.

        PRD: "A label's life begins at `valid_from`, the logical-clock instant of its first publication, and its nominal end is `valid_until`, computed by adding the program tier's `label_validity_days` to `valid_from` as that many exact periods of 86400 seconds."
        Design: Corner/consistency_model/immediate_publication_response_carries_the_window_and_the_code_resolves_at_once
        """
        grant, _store = self._pending_world()
        before = grant.refresh()
        assert_grant_statuses(before, "PENDING_REGISTRY", "DRAFT")

        published = self._publish(grant)
        assert_grant_statuses(published, "ACTIVE", "PUBLISHED")
        assert_instant_equals(published["valid_from"], DEFAULT_CLOCK, "valid_from")
        assert_instant_equals(published["valid_until"], VALID_UNTIL, "valid_until")

    def test_the_public_page_resolves_on_the_very_next_call(self):
        """A consumer scan immediately after publication returns the live label.

        PRD: "Given a `scannable_code`, it returns that code alongside the product's `model_name`, the sponsor's `manufacturer_legal_name`, the `device_category_code` and `program_tier_code` describing the regulatory context, the assessment's `grade` and `decided_overall_score`, the grant's `valid_from`, `valid_until` and `grant_status`, and the registry entry's `support_period_end`, `update_policy_url`, `update_cadence` and `vuln_disclosure_contact`."
        Design: Corner/consistency_model/immediate_publication_response_carries_the_window_and_the_code_resolves_at_once
        """
        grant, _store = self._pending_world()
        published = self._publish(grant)

        page = validate_success(api_client.scan_registry(grant.scannable_code, CONSUMER))
        assert_status(page, "grant_status", "ACTIVE")
        assert_status(page, "grade", "A")
        assert_score(page["decided_overall_score"], 100.00, "decided_overall_score")
        assert_instant_equals(page["valid_from"], published["valid_from"], "valid_from")
        assert_instant_equals(page["valid_until"], published["valid_until"], "valid_until")

    def test_a_display_authorization_on_the_fresh_grant_is_accepted_at_once(self):
        """Another aggregate can use the label in the request straight after publication.

        PRD: "A new authorization starts with `status` at `AUTHORIZED`, the initial value of a lifecycle whose full set is `AUTHORIZED`, `WITHDRAWN` and `EXPIRED`, and with `withdrawal_reason` null."
        Design: Corner/consistency_model/immediate_publication_response_carries_the_window_and_the_code_resolves_at_once
        """
        grant, store = self._pending_world()
        self._publish(grant)

        authorization = validate_success(
            api_client.create_display_authorization(
                factories.create_display_authorization_payload(
                    store.id, grant.id, DISPLAY_FROM, DISPLAY_UNTIL, channel="IN_STORE"
                ),
                store.headers,
            ),
            201,
        )
        assert_status(authorization, "status", "AUTHORIZED")
        assert authorization["withdrawal_reason"] is None

    def test_the_retailer_counts_are_recomputed_within_the_same_chain(self):
        """One active display leaves MegaMart at BASELINE, recounted immediately.

        PRD: "Then `participation_tier` is chosen: a retailer whose `education_materials_ack` is true and whose `active_display_count` is 5 or more is `PLATINUM`; failing that, a retailer whose `education_materials_ack` is true and whose `active_display_count` is 2 or more is `GOLD`; every other retailer is `BASELINE`."
        Design: Corner/consistency_model/immediate_publication_response_carries_the_window_and_the_code_resolves_at_once
        """
        grant, store = self._pending_world()
        self._publish(grant)
        validate_success(
            api_client.create_display_authorization(
                factories.create_display_authorization_payload(
                    store.id, grant.id, DISPLAY_FROM, DISPLAY_UNTIL, channel="IN_STORE"
                ),
                store.headers,
            ),
            201,
        )

        retailer = validate_success(api_client.get_retailer(store.id, store.headers))
        assert retailer["active_display_count"] == 1
        assert_status(retailer, "participation_tier", "BASELINE")

    def test_the_registry_entry_records_the_publishing_reviewer_and_instant(self):
        """`published_at` and `published_by_user_id` are stamped by the publication itself.

        PRD: "It stamps `valid_from` from the logical clock and computes `valid_until` per §3.7, stamps the registry entry's `published_at` from the logical clock and its `published_by_user_id` from the acting reviewer, and makes the public registry lookup resolve for this grant's `scannable_code`."
        Design: Corner/consistency_model/immediate_publication_response_carries_the_window_and_the_code_resolves_at_once
        """
        grant, _store = self._pending_world()
        self._publish(grant)

        entries = validate_unpaginated(
            api_client.get_registry_entry(grant.id, grant.claim.sponsor.headers)
        )
        assert len(entries) == 1
        assert_instant_equals(entries[0]["published_at"], DEFAULT_CLOCK, "published_at")
        assert entries[0]["published_by_user_id"] == REVIEWER_2_USER_ID
