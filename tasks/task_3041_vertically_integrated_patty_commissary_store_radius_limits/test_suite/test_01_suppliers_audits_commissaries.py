"""Suppliers, audits, and the commissary lifecycle (PRD sections 3.1/3.2)."""

from test_helpers import (
    ApiErrorId,
    assert_new_supplier,
    auditor_headers,
    create_approved_supplier,
    create_batch_payload,
    create_beef_delivery_payload,
    create_commissary_payload,
    create_open_store_with_manager,
    create_operational_commissary,
    create_store_payload,
    create_supplier_payload,
    get_success_data,
    planner_headers,
    real_estate_headers,
    scd_headers,
    set_clock,
    validate_error,
    validate_success,
)


class TestSupplierRegistration:
    def test_supplier_create_returns_defaults_and_probation_status(self, api):
        """PRD section 3.1: "A new supplier starts in `PROBATION` status with
        `days_since_last_passed_audit` initialized to 0."
        PRD section 2.4: "Every primary resource carries a standard set of
        system-managed fields: `id`, a server-minted UUID with no type prefix;
        `created_at`, an ISO 8601 UTC timestamp with three fractional digits
        recording creation; `updated_at`, an ISO 8601 UTC timestamp refreshed
        on every mutation; and `version`, an integer that increments by
        exactly one on every mutation of the resource."

        Design: Corner/entities/supplier_create_returns_defaults_and_probation_status
        """
        set_clock()
        resp = api.create_supplier(create_supplier_payload(), scd_headers())
        sup = validate_success(resp, expected_status=201)
        assert_new_supplier(sup)


class TestSupplierEligibilityFreshness:
    def test_stale_audit_blocks_receipt_even_when_status_approved(self, api):
        """PRD section 3.1: "Freshness is enforced independently of status.
        Whenever a beef shipment is dispatched or its receipt confirmed, the
        system counts the whole calendar days between the most recent `PASS`
        audit's `completed_at` (considering `RECORDED` audits only) and the
        logical clock; a supplier is eligible only while it is `APPROVED`
        **and** that day count is less than or equal to its
        `audit_frequency_days`. The boundary is inclusive: a count exactly
        equal to `audit_frequency_days` is eligible, and one day beyond it is
        not, surfacing `ERR_SUPPLIER_AUDIT_STALE` (HTTP 422)."

        Design: Difficulty/dual_variant_calc/supplier_eligibility_audit_freshness_dual_variant
        """
        set_clock("2026-09-01T00:00:00Z")
        env = create_operational_commissary()
        bd = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(env["commissary"]["id"],
                                         env["supplier"]["id"],
                                         raw_beef_lbs=1000),
            planner_headers()))
        get_success_data(api.ship_beef_delivery(bd["id"], planner_headers()))
        # 45 whole calendar days after the 2026-09-01 PASS audit.
        set_clock("2026-10-16T00:00:00Z")
        resp = api.confirm_receiving(bd["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_AUDIT_STALE)
        assert resp.status_code == 422
        supplier = get_success_data(api.get_supplier(
            env["supplier"]["id"], scd_headers()))
        assert supplier["status"] == "APPROVED"
        assert supplier["days_since_last_passed_audit"] == 45
        delivery = get_success_data(api.get_beef_delivery(bd["id"], planner_headers()))
        assert delivery["status"] == "IN_TRANSIT"

    def test_audit_freshness_boundary_inclusive(self, api):
        """PRD section 3.1: "The boundary is inclusive: a count exactly equal
        to `audit_frequency_days` is eligible, and one day beyond it is not,
        surfacing `ERR_SUPPLIER_AUDIT_STALE` (HTTP 422)."

        Design: Difficulty/dual_variant_calc/supplier_eligibility_audit_freshness_dual_variant
        """
        set_clock("2026-09-01T00:00:00Z")
        env = create_operational_commissary()
        deliveries = []
        for hour in ("06:00:00", "07:00:00"):
            bd = get_success_data(api.create_beef_delivery(
                create_beef_delivery_payload(
                    env["commissary"]["id"], env["supplier"]["id"],
                    raw_beef_lbs=100, shipped_at=f"2026-09-01T{hour}Z"),
                planner_headers()))
            get_success_data(api.ship_beef_delivery(bd["id"], planner_headers()))
            deliveries.append(bd["id"])
        # Exactly 30 whole days after the PASS audit: eligible.
        set_clock("2026-10-01T00:00:00Z")
        ok = validate_success(api.confirm_receiving(deliveries[0], planner_headers()))
        assert ok["status"] == "RECEIVED"
        # Thirty-one whole days after the PASS audit: stale.
        set_clock("2026-10-02T00:00:00Z")
        resp = api.confirm_receiving(deliveries[1], planner_headers())
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_AUDIT_STALE)


    def test_fresh_audit_boundary_one_day_beyond_rejected(self, api):
        """PRD section 3.1: "a supplier is eligible only while it is
        `APPROVED` **and** that day count is less than or equal to its
        `audit_frequency_days`. The boundary is inclusive: a count exactly
        equal to `audit_frequency_days` is eligible, and one day beyond it is
        not, surfacing `ERR_SUPPLIER_AUDIT_STALE` (HTTP 422)."

        Design: Difficulty/dual_variant_calc/supplier_eligibility_audit_freshness_dual_variant
        """
        # Ship while fresh (day 30 after the PASS audit), then let the audit
        # go stale before receipt: dispatch and receipt consult freshness
        # independently.
        set_clock("2026-09-01T00:00:00Z")
        env = create_operational_commissary()
        bd = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(env["commissary"]["id"],
                                         env["supplier"]["id"],
                                         raw_beef_lbs=100),
            planner_headers()))
        set_clock("2026-10-01T00:00:00Z")
        shipped = validate_success(api.ship_beef_delivery(bd["id"], planner_headers()))
        assert shipped["status"] == "IN_TRANSIT"
        set_clock("2026-10-02T00:00:00Z")
        resp = api.confirm_receiving(bd["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_AUDIT_STALE)
        assert resp.status_code == 422


class TestSupplierStatusCycle:
    def test_fail_then_pass_cycles_suspended_back_to_approved(self, api):
        """PRD section 3.1: "A recorded `PASS` on a `SUSPENDED` supplier lifts
        it back to `APPROVED`. In every passing case the supplier's
        `days_since_last_passed_audit` is reset to 0, restarting the
        stale-audit clock, and both the supplier's and the audit's `version`
        increment."
        PRD section 3.1: "A recorded `FAIL` on a `PROBATION` or `APPROVED`
        supplier moves it to `SUSPENDED` and fires the **suspension cascade**"

        Design: Difficulty/non_linear_state_machine/supplier_approved_suspended_cycle
        """
        set_clock()
        sup = create_approved_supplier()
        aud2 = get_success_data(api.create_audit(
            sup["id"], {"scheduled_date": "2026-09-02T00:00:00Z"},
            auditor_headers()))
        aud3 = get_success_data(api.create_audit(
            sup["id"], {"scheduled_date": "2026-09-03T00:00:00Z"},
            auditor_headers()))
        get_success_data(api.record_audit(
            sup["id"], aud2["id"],
            {"result": "FAIL", "findings": "cold room breach"},
            auditor_headers()))
        mid = get_success_data(api.get_supplier(sup["id"], scd_headers()))
        assert mid["status"] == "SUSPENDED"
        get_success_data(api.record_audit(
            sup["id"], aud3["id"], {"result": "PASS"}, auditor_headers()))
        final = get_success_data(api.get_supplier(sup["id"], scd_headers()))
        assert final["status"] == "APPROVED"
        assert final["days_since_last_passed_audit"] == 0

    def test_suspended_supplier_cannot_ship(self, api):
        """PRD section 3.1: "Separately, any operation that requires an
        approved supplier — beginning a commissary build, shipping beef, or
        confirming receipt — is rejected with `ERR_SUPPLIER_NOT_APPROVED`
        (HTTP 422) when the referenced supplier holds any other status."

        Design: Difficulty/non_linear_state_machine/supplier_approved_suspended_cycle
        """
        set_clock()
        sup = create_approved_supplier()
        com = get_success_data(api.create_commissary(
            create_commissary_payload(sup["id"]), scd_headers()))
        bd = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(com["id"], sup["id"]),
            planner_headers()))
        aud = get_success_data(api.create_audit(
            sup["id"], {"scheduled_date": "2026-09-02T00:00:00Z"},
            auditor_headers()))
        get_success_data(api.record_audit(
            sup["id"], aud["id"], {"result": "FAIL"}, auditor_headers()))
        resp = api.ship_beef_delivery(bd["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_APPROVED)


class TestAuditFailSuspensionCascade:
    def test_fail_cascade_rejects_deliveries_and_demotes_commissaries(self, api):
        """PRD section 3.1: "A recorded `FAIL` on a `PROBATION` or `APPROVED`
        supplier moves it to `SUSPENDED` and fires the **suspension cascade**,
        whose propagation order is pinned as a single pass, deliveries first,
        then commissaries: every `BeefDelivery` of that supplier in
        `SCHEDULED` or `IN_TRANSIT` status moves to `REJECTED`, processed in
        ascending `created_at` order; then every `Commissary` whose
        `supplier_id` is that supplier and whose status is `OPERATIONAL` is
        demoted to `BUILDING` with `regional_entry_open` recomputed to false,
        each demoted commissary's `version` incrementing alongside the
        supplier's and the audit's."

        Design: Difficulty/transitive_cascade/audit_fail_cascades_supplier_deliveries_commissaries
        """
        set_clock()
        env = create_operational_commissary()
        bd = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(env["commissary"]["id"],
                                         env["supplier"]["id"],
                                         raw_beef_lbs=1000),
            planner_headers()))
        get_success_data(api.ship_beef_delivery(bd["id"], planner_headers()))
        aud2 = get_success_data(api.create_audit(
            env["supplier"]["id"], {"scheduled_date": "2026-09-02T00:00:00Z"},
            auditor_headers()))
        get_success_data(api.record_audit(
            env["supplier"]["id"], aud2["id"],
            {"result": "FAIL", "findings": "spec drift"}, auditor_headers()))
        sup = get_success_data(api.get_supplier(env["supplier"]["id"], scd_headers()))
        assert sup["status"] == "SUSPENDED"
        delivery = get_success_data(api.get_beef_delivery(bd["id"], planner_headers()))
        assert delivery["status"] == "REJECTED"
        com = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        assert com["status"] == "BUILDING"
        assert com["regional_entry_open"] is False

    def test_fail_cascade_rejects_still_scheduled_delivery(self, api):
        """PRD section 3.1: "every `BeefDelivery` of that supplier in
        `SCHEDULED` or `IN_TRANSIT` status moves to `REJECTED`, processed in
        ascending `created_at` order"

        Design: Difficulty/transitive_cascade/audit_fail_cascades_supplier_deliveries_commissaries
        """
        set_clock()
        env = create_operational_commissary()
        bd = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(env["commissary"]["id"],
                                         env["supplier"]["id"]),
            planner_headers()))
        aud2 = get_success_data(api.create_audit(
            env["supplier"]["id"], {"scheduled_date": "2026-09-02T00:00:00Z"},
            auditor_headers()))
        get_success_data(api.record_audit(
            env["supplier"]["id"], aud2["id"], {"result": "FAIL"},
            auditor_headers()))
        delivery = get_success_data(api.get_beef_delivery(bd["id"], planner_headers()))
        assert delivery["status"] == "REJECTED"
        sup = get_success_data(api.get_supplier(env["supplier"]["id"], scd_headers()))
        assert sup["status"] == "SUSPENDED"


class TestBeefReceiptSupplierDependency:
    def test_cascade_rejected_delivery_cannot_be_received(self, api):
        """PRD section 3.3: "Wrong-state delivery actions are rejected with
        `ERR_DELIVERY_INVALID_STATE`."
        PRD section 3.1: "every `BeefDelivery` of that supplier in `SCHEDULED`
        or `IN_TRANSIT` status moves to `REJECTED`"

        Design: Difficulty/cross_entity_state_dependency/beef_receipt_requires_approved_supplier
        """
        set_clock()
        env = create_operational_commissary()
        bd = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(env["commissary"]["id"],
                                         env["supplier"]["id"],
                                         raw_beef_lbs=800),
            planner_headers()))
        get_success_data(api.ship_beef_delivery(bd["id"], planner_headers()))
        aud2 = get_success_data(api.create_audit(
            env["supplier"]["id"], {"scheduled_date": "2026-09-02T00:00:00Z"},
            auditor_headers()))
        get_success_data(api.record_audit(
            env["supplier"]["id"], aud2["id"], {"result": "FAIL"},
            auditor_headers()))
        resp = api.confirm_receiving(bd["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_DELIVERY_INVALID_STATE)
        assert resp.status_code == 409
        com = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        assert com["raw_beef_lbs_on_hand"] == 0

    def test_receipt_with_suspended_supplier_rejected_not_approved(self, api):
        """PRD section 3.1: "Separately, any operation that requires an
        approved supplier — beginning a commissary build, shipping beef, or
        confirming receipt — is rejected with `ERR_SUPPLIER_NOT_APPROVED`
        (HTTP 422) when the referenced supplier holds any other status."
        PRD section 3.1: "then every `Commissary` whose `supplier_id` is that
        supplier and whose status is `OPERATIONAL` is demoted to `BUILDING`
        with `regional_entry_open` recomputed to false"

        Design: Difficulty/cross_entity_state_dependency/beef_receipt_requires_approved_supplier
        """
        set_clock()
        supplier = create_approved_supplier()
        # Keep the commissary in PLANNING so the FAIL cascade cannot demote
        # it; the delivery stays IN_TRANSIT and the receipt attempt surfaces
        # the supplier-approval gate.
        com = get_success_data(api.create_commissary(
            create_commissary_payload(supplier["id"]), scd_headers()))
        bd = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(com["id"], supplier["id"]),
            planner_headers()))
        get_success_data(api.ship_beef_delivery(bd["id"], planner_headers()))
        aud2 = get_success_data(api.create_audit(
            supplier["id"], {"scheduled_date": "2026-09-02T00:00:00Z"},
            auditor_headers()))
        get_success_data(api.record_audit(
            supplier["id"], aud2["id"], {"result": "FAIL"}, auditor_headers()))
        resp = api.confirm_receiving(bd["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_APPROVED)
        assert resp.status_code == 422


class TestCommissaryCycle:
    def test_recertify_then_reactivate_toggles_regional_entry(self, api):
        """PRD section 3.2: "Activation moves `BUILDING` to `OPERATIONAL` and
        flips `regional_entry_open` to true — this is the exact moment
        regional entry opens and store-site creation against this commissary
        becomes legal. Recertification moves `OPERATIONAL` back to `BUILDING`,
        closing regional entry again by recomputing `regional_entry_open` to
        false"

        Design: Difficulty/non_linear_state_machine/commissary_operational_building_cycle
        """
        set_clock()
        env = create_operational_commissary()
        recert = validate_success(api.recertify_commissary(
            env["commissary"]["id"], scd_headers()))
        assert recert["status"] == "BUILDING"
        assert recert["regional_entry_open"] is False
        active = validate_success(api.activate_commissary(
            env["commissary"]["id"], scd_headers()))
        assert active["status"] == "OPERATIONAL"
        assert active["regional_entry_open"] is True

    def test_store_creation_blocked_while_regional_entry_closed(self, api):
        """PRD section 3.4: "Two gates run already at creation: the
        referenced commissary must have `regional_entry_open` true (a linkage
        failure otherwise)"

        Design: Difficulty/cross_entity_state_dependency/store_creation_requires_operational_commissary
        """
        set_clock()
        env = create_operational_commissary()
        # OPERATIONAL -> BUILDING closes regional entry again.
        get_success_data(api.recertify_commissary(
            env["commissary"]["id"], scd_headers()))
        fresh = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        resp = api.create_store(
            create_store_payload(env["commissary"]["id"],
                                 expected_commissary_version=fresh["version"]),
            real_estate_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        page = api.list_stores(scd_headers(),
                               params={"commissary_id": env["commissary"]["id"]})
        body = page.json()
        assert body["data"] == []
        assert body["meta"]["total_count"] == 0


    def test_recertify_reactivating_reopens_regional_entry(self, api):
        """PRD section 3.2: "Recertification moves `OPERATIONAL` back to
        `BUILDING`, closing regional entry again by recomputing
        `regional_entry_open` to false"
        PRD section 3.2: "Activation moves `BUILDING` to `OPERATIONAL` and
        flips `regional_entry_open` to true — this is the exact moment
        regional entry opens and store-site creation against this commissary
        becomes legal."

        Design: Difficulty/cross_entity_state_dependency/store_creation_requires_operational_commissary
        """
        set_clock()
        env = create_operational_commissary()
        get_success_data(api.recertify_commissary(
            env["commissary"]["id"], scd_headers()))
        blocked = api.create_store(
            create_store_payload(
                env["commissary"]["id"],
                expected_commissary_version=get_success_data(
                    api.get_commissary(env["commissary"]["id"],
                                       scd_headers()))["version"]),
            real_estate_headers())
        validate_error(blocked, ApiErrorId.ERR_INVALID_REQUEST)
        # Reactivating reopens the region, and the same site proposal now
        # succeeds.
        reactivated = validate_success(api.activate_commissary(
            env["commissary"]["id"], scd_headers()))
        assert reactivated["regional_entry_open"] is True
        ok = validate_success(api.create_store(
            create_store_payload(env["commissary"]["id"],
                                 expected_commissary_version=reactivated["version"]),
            real_estate_headers()), expected_status=201)
        assert ok["status"] == "SITE_REVIEW"


    def test_recertify_wrong_state_rejected(self, api):
        """PRD section 3.2: "Any lifecycle action attempted from the wrong
        status is rejected with `ERR_COMMISSARY_INVALID_STATE` (HTTP 409)"

        Design: Difficulty/non_linear_state_machine/commissary_operational_building_cycle
        """
        # While BUILDING, recertify is not a legal move — the cycle can only
        # run OPERATIONAL -> BUILDING -> OPERATIONAL.
        set_clock()
        env = create_operational_commissary()
        get_success_data(api.recertify_commissary(
            env["commissary"]["id"], scd_headers()))
        resp = api.recertify_commissary(env["commissary"]["id"], scd_headers())
        validate_error(resp, ApiErrorId.ERR_COMMISSARY_INVALID_STATE)
        assert resp.status_code == 409
        com = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        assert com["status"] == "BUILDING"
        assert com["regional_entry_open"] is False


class TestRecertifyGate:
    def test_recertify_blocked_by_open_batches(self, api):
        """PRD section 3.2: "Recertification moves `OPERATIONAL` back to
        `BUILDING`, closing regional entry again by recomputing
        `regional_entry_open` to false, and is permitted only while no
        delivery batch of this commissary sits in `PLANNED` or `LOADED`
        status; open batches block it with `ERR_OPEN_BATCHES_EXIST`
        (HTTP 409)."

        Design: Corner/errors/error_catalog_full_triggerability
        """
        # An OPEN store with a manager, plus one PLANNED batch.
        env = create_open_store_with_manager()
        store = env["store"]
        store_v = get_success_data(api.get_store(store["id"], planner_headers()))["version"]
        batch = get_success_data(api.create_batch(
            create_batch_payload(store["id"], store_v, "2026-09-02T00:00:00Z"),
            planner_headers()))
        assert batch["status"] == "PLANNED"
        resp = api.recertify_commissary(env["commissary"]["id"], scd_headers())
        validate_error(resp, ApiErrorId.ERR_OPEN_BATCHES_EXIST)
        assert resp.status_code == 409
        com = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        assert com["status"] == "OPERATIONAL"


class TestAuditImmutability:
    def test_audit_immutable_after_recording(self, api):
        """PRD section 3.1: "An audit may be cancelled while `SCHEDULED`,
        moving it to `CANCELLED`; either action attempted on an audit that is
        no longer `SCHEDULED` is rejected with `ERR_AUDIT_ALREADY_RECORDED`."

        Design: Corner/entities/audit_immutable_after_recording
        """
        set_clock()
        sup = get_success_data(api.create_supplier(
            create_supplier_payload(), scd_headers()))
        aud = get_success_data(api.create_audit(
            sup["id"], {"scheduled_date": "2026-09-01T00:00:00Z"},
            auditor_headers()))
        get_success_data(api.record_audit(
            sup["id"], aud["id"], {"result": "PASS"}, auditor_headers()))
        rerecord = api.record_audit(
            sup["id"], aud["id"], {"result": "FAIL"}, auditor_headers())
        validate_error(rerecord, ApiErrorId.ERR_AUDIT_ALREADY_RECORDED)
        assert rerecord.status_code == 409
        cancel = api.cancel_audit(sup["id"], aud["id"], auditor_headers())
        validate_error(cancel, ApiErrorId.ERR_AUDIT_ALREADY_RECORDED)
        assert cancel.status_code == 409
        stored = get_success_data(api.get_audit(aud["id"], auditor_headers()))
        assert stored["result"] == "PASS"
