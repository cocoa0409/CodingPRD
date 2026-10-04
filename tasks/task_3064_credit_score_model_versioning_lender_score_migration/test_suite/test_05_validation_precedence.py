"""Which check wins when more than one could fire on one request."""

from test_helpers import api_client, get_success_data, COMPLIANCE, FAIR_LENDING, NON_EXISTENT_UUID, setup_reference_set_reconciled, setup_probationary_and_retired_licences, create_score_result_payload, licence_headers, create_and_activate_license


class TestExistenceBeatsState:

    def test_an_unknown_reason_code_is_reported_before_the_state_conflict(self, api):
        """PRD §2.12: "Authentication comes first: the headers must be present and
        the role must be declared, then the role must be authorised for the
        operation, then the role-identity binding must hold for an entity-backed
        role. Resource resolution follows — every path identifier left to right,
        then every foreign-key identifier supplied in the body. Only then do state
        and business rules apply"

        A nameable-but-unallocated reason code id must therefore surface as a 404
        resolution failure rather than as the 409 the reconciled set would otherwise
        provoke.

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_reason_code_existence_beats_state_edge
        """
        _, _, _, _, _, rs = setup_reference_set_reconciled()
        rs_current = get_success_data(
            api_client.get_reference_set(rs["id"], FAIR_LENDING), 200)
        res = api_client.attach_reason_code(rs["id"], NON_EXISTENT_UUID,
                                            rs_current["version"], FAIR_LENDING)
        assert res.status_code == 404
        assert res.json()["data"]["error_id"] == "ERR_REASON_CODE_NOT_FOUND"

    def test_a_resolvable_code_lets_the_state_check_produce_the_error(self, api):
        """PRD §3.6: "Reconciling is the terminal move and requires the bound code
        to have been archived first — reconciling against a code that is still
        `ACTIVE` is refused with `ERR_REASON_CODE_ACTIVE`."
        PRD §2.12: "the target must occupy the state named by the transition's
        originating clause and the transition must be declared on that entity"

        A reconciled set cannot re-enter BOUND, and with the body resolvable the
        state edge is what rejects the call.

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_reason_code_existence_beats_state_edge
        """
        _, _, _, rc_seg, _, rs = setup_reference_set_reconciled()
        rs_current = get_success_data(
            api_client.get_reference_set(rs["id"], FAIR_LENDING), 200)
        res = api_client.attach_reason_code(rs["id"], rc_seg["id"],
                                            rs_current["version"], FAIR_LENDING)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE_MACHINE_EDGE"

    def test_a_rejected_attach_leaves_the_set_reconciled_and_unbound(self, api):
        """PRD §3.6: "Whichever route is taken, the `reason_code_id` is cleared to
        null and every posting on the set has its `decision` reset to `UNDECIDED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_reason_code_existence_beats_state_edge
        """
        _, _, _, rc_seg, _, rs = setup_reference_set_reconciled()
        rs_current = get_success_data(
            api_client.get_reference_set(rs["id"], FAIR_LENDING), 200)
        api_client.attach_reason_code(rs["id"], NON_EXISTENT_UUID,
                                      rs_current["version"], FAIR_LENDING)
        api_client.attach_reason_code(rs["id"], rc_seg["id"],
                                      rs_current["version"], FAIR_LENDING)
        after = get_success_data(api_client.get_reference_set(rs["id"], FAIR_LENDING), 200)
        assert after["status"] == "RECONCILED"
        assert after["reason_code_id"] is None


class TestSafetyBeatsOwnership:

    def test_a_posting_against_a_superseded_version_is_refused_before_ownership(self, api):
        """PRD §2.12: "a posting, an activation or a reactivation against a version
        in `SUPERSEDED` or `RETIRED` is refused"
        PRD §3.8: "The write is refused with `ERR_MODEL_SUPERSEDED` when the licensed
        variant's model version has been superseded"

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_model_superseded_beats_license_ownership
        """
        fixture = setup_probationary_and_retired_licences()
        m1_variant = fixture["v1"]
        # The licence belongs to LEND-EAST; the caller presents itself as LEND-WEST's
        # pending licence, so ownership would also fail — the safety check wins.
        east = get_success_data(api_client.get_license(fixture["lic_e"]["id"], COMPLIANCE), 200)
        caller = fixture["lic_w"]["id"]
        payload = create_score_result_payload(
            consumer_id=fixture["consumer"]["id"], score_variant_id=m1_variant["id"],
            bureau_id=fixture["bureau"]["id"], license_id=east["id"],
            raw_posted_score=700, expected_license_version=east["version"])
        res = api_client.create_score_result(payload, licence_headers(caller))
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_MODEL_SUPERSEDED"

    def test_the_same_posting_against_a_live_variant_reports_ownership(self, api):
        """PRD §2.1: "A posting that names a `license_id` other than the caller's own
        identifier is refused with `ERR_LICENSE_NOT_OWNED`."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_model_superseded_beats_license_ownership
        """
        fixture = setup_probationary_and_retired_licences()
        m2_variant = fixture["v2"]
        east_live = create_and_activate_license(m2_variant["id"], lender_code="LEND-EAST2",
                                                entitled_count=500)
        west_live = create_and_activate_license(m2_variant["id"], lender_code="LEND-WEST2",
                                                entitled_count=500,
                                                window_start_month="2027-01",
                                                window_end_month="2028-01")
        payload = create_score_result_payload(
            consumer_id=fixture["consumer"]["id"], score_variant_id=m2_variant["id"],
            bureau_id=fixture["bureau"]["id"], license_id=east_live["id"],
            raw_posted_score=700, expected_license_version=east_live["version"])
        res = api_client.create_score_result(payload,
                                             licence_headers(west_live["id"]))
        assert res.status_code == 403
        assert res.json()["data"]["error_id"] == "ERR_LICENSE_NOT_OWNED"

    def test_neither_rejected_posting_settled_a_fee(self, api):
        """PRD §3.8: "Settlement closes the posting. A `MARGINAL_PRICING` entry is
        appended to the fee ledger — its `ledger_description` carrying the audit
        prose for the accrual, its `cumulative_count_before` recording the licence's
        cumulative count immediately before the entry was written"

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_model_superseded_beats_license_ownership
        """
        fixture = setup_probationary_and_retired_licences()
        east = get_success_data(api_client.get_license(fixture["lic_e"]["id"], COMPLIANCE), 200)
        payload = create_score_result_payload(
            consumer_id=fixture["consumer"]["id"], score_variant_id=fixture["v1"]["id"],
            bureau_id=fixture["bureau"]["id"], license_id=east["id"],
            raw_posted_score=700, expected_license_version=east["version"])
        api_client.create_score_result(payload,
                                       licence_headers(fixture["lic_w"]["id"]))
        after = get_success_data(api_client.get_license(east["id"], COMPLIANCE), 200)
        assert after["cumulative_score_count"] == 0
        assert after["cumulative_fee_cents"] == 0