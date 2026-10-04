"""Formulation change branches, rematch fan-out, and deferred effectiveness."""
from test_helpers import (
    ADMIN,
    CLA,
    RM,
    ApiErrorId,
    api_client,
    create_formulation_change_payload,
    get_success_data,
    make_dealer_principal_headers,
    set_clock,
    setup_base,
    setup_dealer,
    setup_effective_change,
    setup_equipment,
    setup_formula,
    setup_license,
    setup_onboarded_dealer,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCancelVsEffectiveBranches:
    def test_cancel_from_announced_creates_no_rematch_tasks(self, api):
        """PRD section 3.8: "A change may be cancelled from either `DRAFT` or
        `ANNOUNCED` to `CANCELLED`, which also increments its `version` by
        1."
        PRD section 3.8: "The make-effective action fans out the rematch
        wave. Every formula of the change's product line whose status is
        `ACTIVE` has its `formulation_version` incremented by 1 and its
        `rematch_pending` set true; and for each such formula paired with
        each dealer holding a license in `ACTIVE` or `SUSPENDED` status on
        the product line's colorant system, the server creates a rematch task
        in `PENDING`".

        Design: Difficulty/non_linear_state_machine/formulation_change_branching_cancel_vs_complete_paths
        """
        ctx = setup_onboarded_dealer()
        setup_formula(ctx["line"]["id"])
        change = get_success_data(
            api_client.create_formulation_change(
                create_formulation_change_payload(ctx["line"]["id"]), CLA,
            )
        )
        validate_success(
            api_client.announce_formulation_change(
                change["id"], {"expected_change_version": change["version"]}, CLA,
            )
        )
        cancelled = validate_success(api.cancel_formulation_change(change["id"], CLA))
        assert cancelled["status"] == "CANCELLED"
        tasks, _meta = validate_paginated(
            api.list_rematch_tasks(CLA, params={"formulation_change_id": change["id"]})
        )
        assert tasks == []

    def test_effective_fans_out_tasks_and_auto_completes(self, api):
        """PRD section 3.8: "The make-effective action fans out the rematch
        wave. Every formula of the change's product line whose status is
        `ACTIVE` has its `formulation_version` incremented by 1 and its
        `rematch_pending` set true; and for each such formula paired with
        each dealer holding a license in `ACTIVE` or `SUSPENDED` status on
        the product line's colorant system, the server creates a rematch task
        in `PENDING` recording the `formulation_change_id`, `dealer_id`,
        `color_formula_id`, the `old_formulation_version` (the formula's
        version before the change), and the `new_formulation_version` (one
        higher)."
        PRD section 3.8: "when the completed task was the last `PENDING` task
        of its change, the change bubbles up from `EFFECTIVE` to `COMPLETED`,
        clearing `rematch_pending` on every formula whose tasks are all
        `DONE`."

        Design: Difficulty/non_linear_state_machine/formulation_change_branching_cancel_vs_complete_paths
        """
        ctx = setup_onboarded_dealer()
        formula = setup_formula(ctx["line"]["id"])
        change, tasks_resp = setup_effective_change(ctx)
        assert change["status"] == "EFFECTIVE"
        tasks, _meta = validate_paginated(tasks_resp)
        assert len(tasks) == 1
        assert tasks[0]["old_formulation_version"] == 1
        assert tasks[0]["new_formulation_version"] == 2
        assert tasks[0]["status"] == "PENDING"
        refreshed_formula = validate_success(api.get_formula(formula["id"], CLA))
        assert refreshed_formula["formulation_version"] == 2
        assert refreshed_formula["rematch_pending"] is True
        validate_success(
            api.complete_rematch_task(
                tasks[0]["id"], make_dealer_principal_headers(ctx["dealer"]["id"])
            )
        )
        final = validate_success(api.get_formulation_change(change["id"], CLA))
        assert final["status"] == "COMPLETED"
        done_formula = validate_success(api.get_formula(formula["id"], CLA))
        assert done_formula["rematch_pending"] is False


class TestRematchFanoutFiltering:
    def test_pending_licensed_dealer_gets_no_task(self, api):
        """PRD section 3.8: "and for each such formula paired with each
        dealer holding a license in `ACTIVE` or `SUSPENDED` status on the
        product line's colorant system, the server creates a rematch task in
        `PENDING`".

        Design: Corner/calculations/rematch_fanout_skips_suspended_licenses_and_archived_formulas
        """
        ctx = setup_onboarded_dealer()
        setup_formula(ctx["line"]["id"])
        # Second dealer: ONBOARDING, license PENDING (unit never calibrated).
        dealer2 = setup_dealer(
            ctx["region"]["id"], legal_name="Second Paint Co",
            latitude=43.0, longitude=-72.0,
        )
        get_success_data(api.begin_onboarding(dealer2["id"], RM))
        setup_equipment(dealer2["id"], ctx["system"]["id"], serial_no="SN-200")
        lic2 = setup_license(dealer2["id"], ctx["system"]["id"])
        assert lic2["status"] == "PENDING"
        _change, tasks_resp = setup_effective_change(ctx)
        tasks, meta = validate_paginated(tasks_resp)
        assert meta["total_count"] == 1
        assert tasks[0]["dealer_id"] == ctx["dealer"]["id"]

    def test_formula_without_eligible_dealers_bumps_version_without_pending(self, api):
        """PRD section 3.8: "A formula with zero eligible dealers still bumps
        its `formulation_version` but keeps `rematch_pending` false, since no
        outstanding work exists."

        Design: Corner/calculations/rematch_fanout_skips_suspended_licenses_and_archived_formulas
        """
        # No dealer at all: just region + system + line + formula.
        ctx = setup_base()
        formula = setup_formula(ctx["line"]["id"])
        change, tasks_resp = setup_effective_change(ctx)
        tasks, meta = validate_paginated(tasks_resp)
        assert meta["total_count"] == 0
        refreshed = validate_success(api.get_formula(formula["id"], CLA))
        assert refreshed["formulation_version"] == 2
        assert refreshed["rematch_pending"] is False


class TestEffectiveDateRules:
    def test_announce_with_past_effective_date_rejected(self, api):
        """PRD section 3.8: "Announcing the change — an OCC-guarded action
        requiring `expected_change_version` per §2.5 — moves it from `DRAFT`
        to `ANNOUNCED` and requires the `effective_date` to be strictly after
        the current logical time; an effective date at or before now is
        rejected with `ERR_EFFECTIVE_DATE_INVALID` (HTTP 422)."

        Design: Corner/validations/announce_with_past_effective_date_rejected
        """
        ctx = setup_base()
        change = get_success_data(
            api_client.create_formulation_change(
                create_formulation_change_payload(
                    ctx["line"]["id"], title="Retro change",
                    effective_date="2026-08-01T00:00:00Z",
                ),
                CLA,
            )
        )
        resp = api.announce_formulation_change(
            change["id"], {"expected_change_version": change["version"]}, CLA,
        )
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_INVALID)

    def test_make_effective_before_effective_date_rejected(self, api):
        """PRD section 3.8: "Making the change effective moves it from
        `ANNOUNCED` to `EFFECTIVE` and requires the `effective_date` to be at
        or before now — a change may only take effect on or after its
        declared date, and a still-future date is rejected with
        `ERR_EFFECTIVE_DATE_INVALID`."

        Design: Corner/validations/make_effective_before_effective_date_rejected
        """
        ctx = setup_base()
        change = get_success_data(
            api_client.create_formulation_change(
                create_formulation_change_payload(
                    ctx["line"]["id"], title="Future change",
                    effective_date="2026-09-05T00:00:00Z",
                ),
                CLA,
            )
        )
        validate_success(
            api.announce_formulation_change(
                change["id"], {"expected_change_version": change["version"]}, CLA,
            )
        )
        resp = api.make_effective_formulation_change(change["id"], CLA)
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_INVALID)

    def test_make_effective_succeeds_once_clock_reaches_date(self, api):
        """PRD section 3.8: "Making the change effective moves it from
        `ANNOUNCED` to `EFFECTIVE` and requires the `effective_date` to be at
        or before now — a change may only take effect on or after its
        declared date, and a still-future date is rejected with
        `ERR_EFFECTIVE_DATE_INVALID`."

        Design: Corner/cross-cutting complexity layers/scheduled_deferred_formulation_change_takes_effect_at_date
        """
        ctx = setup_base()
        change = get_success_data(
            api_client.create_formulation_change(
                create_formulation_change_payload(
                    ctx["line"]["id"], title="Deferred change",
                    effective_date="2026-09-05T00:00:00Z",
                ),
                CLA,
            )
        )
        validate_success(
            api.announce_formulation_change(
                change["id"], {"expected_change_version": change["version"]}, CLA,
            )
        )
        set_clock("2026-09-05T00:00:00Z")
        effective = validate_success(api.make_effective_formulation_change(change["id"], CLA))
        assert effective["status"] == "EFFECTIVE"

    def test_announce_with_stale_version_rejected_after_cancel(self, api):
        """PRD section 2.5: "Announcing a formulation change likewise
        requires `expected_change_version` matching the change's current
        `version`; if another writer has cancelled the draft in the meantime,
        the announce is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 3.8: "A change may be cancelled from either `DRAFT` or
        `ANNOUNCED` to `CANCELLED`, which also increments its `version` by
        1."

        Design: Corner/cross-cutting complexity layers/occ_stale_version_on_formulation_announce
        """
        ctx = setup_base()
        change = get_success_data(
            api_client.create_formulation_change(
                create_formulation_change_payload(
                    ctx["line"]["id"], title="OCC change",
                    effective_date="2026-09-05T00:00:00Z",
                ),
                CLA,
            )
        )
        validate_success(api.cancel_formulation_change(change["id"], CLA))
        resp = api.announce_formulation_change(
            change["id"], {"expected_change_version": change["version"]}, CLA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestRematchTaskShape:
    def test_rematch_task_has_no_version_or_updated_at(self, api):
        """PRD section 2.4: "Two resource types — `RematchTask` and
        `DealerChannelEvent` — are exceptions: they carry only `id` and
        `created_at`; both `updated_at` and `version` are absent from these
        resources."

        Design: Corner/entities/rematch_task_immutable_no_version_field
        """
        ctx = setup_onboarded_dealer()
        setup_formula(ctx["line"]["id"])
        _change, tasks_resp = setup_effective_change(ctx)
        tasks, _meta = validate_paginated(tasks_resp)
        assert len(tasks) == 1
        task = tasks[0]
        assert task["status"] == "PENDING"
        assert "id" in task and "created_at" in task
        assert "version" not in task
        assert "updated_at" not in task


class TestRematchSubresources:
    def test_dealer_and_change_subresource_listings_agree(self, api):
        """PRD section 3.8: "Rematch tasks can be listed filtered by
        `dealer_id`, `formulation_change_id`, or `color_formula_id`, and are
        also exposed as sub-resource listings under a formulation change, a
        dealer, or a formula."

        Design: Corner/endpoints/fk_reverse_reachability_subresources
        """
        ctx = setup_onboarded_dealer()
        setup_formula(ctx["line"]["id"])
        change, _tasks_resp = setup_effective_change(ctx)
        by_dealer, _m1 = validate_paginated(
            api.list_dealer_rematch_tasks(ctx["dealer"]["id"], RM)
        )
        by_change, _m2 = validate_paginated(
            api.list_change_rematch_tasks(change["id"], RM)
        )
        assert len(by_dealer) == 1
        assert len(by_change) == 1
        assert by_dealer[0]["id"] == by_change[0]["id"]
