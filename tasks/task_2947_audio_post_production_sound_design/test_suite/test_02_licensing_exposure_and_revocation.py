"""Licence clearance, the two exposure scores and the withdrawal cascade."""

from test_helpers.assertions import assert_decimal, assert_hour_ledger


class TestTheTwoLicenceExposureVariants:
    """One usage pair, scored twice with deliberately divergent weights."""

    def _exposure(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        rights_managed = world.library_asset(
            kind="MUSIC_LIBRARY",
            license_type="RIGHTS_MANAGED",
            territory_scope="WORLDWIDE",
            fee_cents=25000,
            expires_at_utc="2026-09-11T00:00:00Z",
        )
        royalty_free = world.library_asset(
            kind="SFX",
            license_type="ROYALTY_FREE",
            territory_scope="DOMESTIC",
            fee_cents=17890,
        )
        project = world.locked_project()
        package = world.stem_package(project["id"])
        cleared = world.asset_usage(
            rights_managed["id"], package["id"], usage_seconds=100, territory_declared="WORLDWIDE"
        )
        unlicensed = world.asset_usage(
            royalty_free["id"], package["id"], usage_seconds=60, territory_declared="WORLDWIDE"
        )
        return project, cleared, unlicensed

    def test_the_intake_snapshot_counts_cleared_usages_only(self, world):
        """The snapshot scores the licensed mix and reads 20.00 over this pair.

        PRD §3.4: "It counts, among **cleared usages only**, how many reference a
        `RIGHTS_MANAGED` asset and how many reference a `ROYALTY_FREE` asset,
        multiplies those counts by 20 and 5 respectively, adds the two products, rounds
        the sum half up, and then caps the result at 100.00."

        Design: Difficulty/dual_variant_calc/license_risk_intake_snapshot_vs_delivery_audit_divergence
        """
        project, cleared, _unlicensed = self._exposure(world)

        assert cleared["clearance_status"] == "CLEARED"
        assert cleared["accrued_fee_cents"] == 100000

        project_after = world.get_project(project["id"])
        assert_decimal(project_after["license_risk_score_intake"], 20.00)
        assert project_after["license_fee_accrued_cents"] == 100000
        assert project_after["billing_total_cents"] == 100000

        ledger = world.ledger(project["id"])
        assert_decimal(ledger["license_risk_score_intake"], 20.00)
        assert ledger["license_fee_accrued_cents"] == 100000

    def test_the_delivery_audit_adds_the_unlicensed_and_near_expiry_terms(self, world):
        """The audit variant scores every usage and reads 65.00 over the same pair.

        PRD §3.4: "Consider a project holding one cleared rights-managed usage whose
        licence expires 10 days out, plus one unlicensed royalty-free usage: the intake
        snapshot reads 20.00, counting only the cleared rights-managed usage, while the
        delivery audit reads 20 plus 5 plus 30 plus 10, or 65.00."

        Design: Difficulty/dual_variant_calc/license_risk_intake_snapshot_vs_delivery_audit_divergence
        """
        project, _cleared, unlicensed = self._exposure(world)

        assert unlicensed["clearance_status"] == "UNLICENSED"
        assert unlicensed["unlicensed_reason"] == "TERRITORY_OUT_OF_SCOPE"
        assert unlicensed["accrued_fee_cents"] == 0
        assert unlicensed["cleared_at_utc"] is None

        project_after = world.get_project(project["id"])
        assert_decimal(project_after["license_risk_score_audit"], 65.00)
        assert_decimal(project_after["license_risk_score_intake"], 20.00)
        assert project_after["unlicensed_usage_count"] == 1
        assert project_after["posture"] == "RESTRICTED"

        ledger = world.ledger(project["id"])
        assert_decimal(ledger["license_risk_score_audit"], 65.00)
        assert ledger["billing_total_cents"] == 100000


class TestRevocationCascade:
    """Withdrawing a facility-wide licence reaches the project's stage ledger."""

    def _environment(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        spec = world.platform_spec(platform="THEATRICAL")
        stage = world.mix_stage(hourly_rate_cents=120000)
        mixer = world.mixer(certified_platforms=["THEATRICAL"])
        asset = world.library_asset(fee_cents=25000)
        project = world.locked_project()
        package = world.conformed_package(project["id"], cue_durations=(120, 120))
        usage = world.asset_usage(
            asset["id"], package["id"], usage_seconds=100, territory_declared="WORLDWIDE"
        )
        booking = world.booking(
            project["id"], stage["id"], mixer["id"], booking_type="FINAL_MIX", platform="THEATRICAL"
        )
        world.confirm_booking(booking["id"], mixer["id"])
        deliverable = world.deliverable(project["id"], spec["id"], package["id"], booking["id"])
        assert world.ledger(project["id"])["billing_total_cents"] == 466000
        return {
            "asset": asset,
            "project": project,
            "package": package,
            "usage": usage,
            "booking": booking,
            "deliverable": deliverable,
        }

    def test_revocation_unlicenses_the_usage_and_stales_the_conformed_package(self, world):
        """The first two hops of the withdrawal chain, with their own reason codes.

        PRD §3.4: "Then, **because** those usages became unlicensed, each one's stem
        package, if its `status` is `CONFORMED`, moves `CONFORMED → STALE` with
        `stale_reason` set to `LICENSE_REVOKED`."

        Design: Difficulty/transitive_cascade/library_asset_revoke_cascade_reaches_booking_and_billing
        """
        environment = self._environment(world)
        world.revoke_asset(
            environment["asset"]["id"], revocation_reason="rights holder withdrew the cue"
        )

        assert world.get_asset(environment["asset"]["id"])["status"] == "REVOKED"

        usage = world.get_usage(environment["usage"]["id"])
        assert usage["clearance_status"] == "UNLICENSED"
        assert usage["unlicensed_reason"] == "ASSET_REVOKED"
        assert usage["accrued_fee_cents"] == 0

        package = world.get_stem_package(environment["package"]["id"])
        assert package["status"] == "STALE"
        assert package["stale_reason"] == "LICENSE_REVOKED"

        project = world.get_project(environment["project"]["id"])
        assert project["picture_status"] == "LOCKED"
        assert project["posture"] == "RESTRICTED"
        assert project["unlicensed_usage_count"] == 1
        assert project["stale_stem_count"] == 1
        assert project["conformed_stem_count"] == 0

        ledger = world.ledger(environment["project"]["id"])
        assert ledger["license_fee_accrued_cents"] == 0
        assert_decimal(ledger["license_risk_score_intake"], 0.00)
        assert_decimal(ledger["license_risk_score_audit"], 50.00)

    def test_revocation_reaches_the_deliverable_the_booking_and_the_billing_total(self, world):
        """Hops three and four return the stage hours and collapse the billing total.

        PRD §2.10: "Third — **because** each of those deliverables became invalidated —
        the mix stage booking identified by that deliverable's `mix_booking_id` moves to
        `RELEASED` with `release_reason` set to the string `DELIVERABLE_INVALIDATED`, but
        only if that booking's `status` is `RESERVED` or `CONFIRMED`."

        Design: Difficulty/transitive_cascade/library_asset_revoke_cascade_reaches_booking_and_billing
        """
        environment = self._environment(world)
        world.revoke_asset(
            environment["asset"]["id"], revocation_reason="rights holder withdrew the cue"
        )

        deliverable = world.get_deliverable(environment["deliverable"]["id"])
        assert deliverable["status"] == "INVALIDATED"
        assert deliverable["invalidation_reason"] == "STEM_STALE"

        booking = world.get_booking(environment["booking"]["id"])
        assert booking["status"] == "RELEASED"
        assert booking["release_reason"] == "DELIVERABLE_INVALIDATED"
        assert booking["final_cost_cents"] is None

        project = world.get_project(environment["project"]["id"])
        assert_hour_ledger(project, 0.00, 0.00, 40.00)

        ledger = world.ledger(environment["project"]["id"])
        assert ledger["stage_cost_subtotal_cents"] == 0
        assert ledger["conform_fee_total_cents"] == 6000
        assert ledger["billing_total_cents"] == 6000


class TestLicenceAccrualReversal:
    """A revocation reverses exactly one asset's accrual and nothing else."""

    def _two_licensed_usages(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        asset_a = world.library_asset(
            kind="MUSIC_LIBRARY",
            license_type="RIGHTS_MANAGED",
            territory_scope="WORLDWIDE",
            fee_cents=25000,
        )
        asset_b = world.library_asset(
            kind="FOLEY",
            license_type="RIGHTS_MANAGED",
            territory_scope="WORLDWIDE",
            fee_cents=20000,
        )
        project = world.locked_project()
        package = world.conformed_package(project["id"], cue_durations=(120, 120))
        usage_a = world.asset_usage(
            asset_a["id"], package["id"], usage_seconds=100, territory_declared="WORLDWIDE"
        )
        usage_b = world.asset_usage(
            asset_b["id"], package["id"], usage_seconds=60, territory_declared="WORLDWIDE"
        )
        assert usage_a["accrued_fee_cents"] == 100000
        assert usage_b["accrued_fee_cents"] == 40000
        before = world.ledger(project["id"])
        assert before["license_fee_accrued_cents"] == 140000
        assert before["billing_total_cents"] == 146000
        assert_decimal(before["license_risk_score_intake"], 40.00)
        assert_decimal(before["license_risk_score_audit"], 40.00)
        return asset_a, asset_b, project, package, usage_a, usage_b

    def test_only_the_revoked_asset_loses_its_accrual(self, world):
        """140000 falls to exactly 40000: no double subtraction, no negative residue.

        PRD §3.4: "The accrual reversal is a genuine compensating movement: the money the
        withdrawn licence had accrued leaves the project's licence ledger entirely,
        rather than being offset by a negative entry."

        Design: Difficulty/compensating_invariant/license_accrual_reversal_is_exact_and_never_negative
        """
        asset_a, asset_b, project, _package, usage_a, usage_b = self._two_licensed_usages(world)

        world.revoke_asset(asset_a["id"], revocation_reason="licence terminated by the publisher")

        revoked_usage = world.get_usage(usage_a["id"])
        assert revoked_usage["clearance_status"] == "UNLICENSED"
        assert revoked_usage["unlicensed_reason"] == "ASSET_REVOKED"
        assert revoked_usage["accrued_fee_cents"] == 0

        untouched_usage = world.get_usage(usage_b["id"])
        assert untouched_usage["clearance_status"] == "CLEARED"
        assert untouched_usage["accrued_fee_cents"] == 40000
        assert world.get_asset(asset_b["id"])["status"] == "ACTIVE"

        ledger = world.ledger(project["id"])
        assert ledger["license_fee_accrued_cents"] == 40000
        assert ledger["license_fee_accrued_cents"] >= 0
        assert ledger["conform_fee_total_cents"] == 6000
        assert ledger["billing_total_cents"] == 46000

    def test_the_two_exposure_scores_move_in_opposite_directions(self, world):
        """The snapshot falls as a cleared usage leaves; the audit rises on the penalty.

        PRD §3.4: "Second, it adds two further terms: 30 points for each usage whose
        `clearance_status` is `UNLICENSED`, and 10 points for each usage whose
        `clearance_status` is `CLEARED` whose asset has a non-null `expires_at_utc` that
        lies strictly after the current logical-clock instant and no more than 30 days
        after it."

        Design: Difficulty/compensating_invariant/license_accrual_reversal_is_exact_and_never_negative
        """
        asset_a, _asset_b, project, package, _usage_a, _usage_b = self._two_licensed_usages(world)

        world.revoke_asset(asset_a["id"], revocation_reason="licence terminated by the publisher")

        ledger = world.ledger(project["id"])
        assert_decimal(ledger["license_risk_score_intake"], 20.00)
        assert_decimal(ledger["license_risk_score_audit"], 70.00)

        stale_package = world.get_stem_package(package["id"])
        assert stale_package["status"] == "STALE"
        assert stale_package["stale_reason"] == "LICENSE_REVOKED"

        project_after = world.get_project(project["id"])
        assert project_after["unlicensed_usage_count"] == 1
        assert project_after["posture"] == "RESTRICTED"
