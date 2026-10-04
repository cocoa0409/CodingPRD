"""Depth tests: cross-entity state dependencies.

Shift-window planning is gated on the establishment's grant dimension, and
label resubmission is gated on the establishment's inspection dimension — the
child workflow opens and closes as the parent entity's state moves.
"""

from test_helpers import (
    ApiErrorId,
    assert_shift_window,
    factories as f,
    fixtures as fx,
    make_establishment_manager_headers,
    validate_error,
    validate_success,
)


class TestShiftWindowRequiresGrantedEstablishment:
    def test_planning_rejected_while_ungranted_accepted_after_grant(self, api):
        """PRD §3.2: "Planning requires the establishment to hold a grant
        (otherwise `ERR_ESTABLISHMENT_NOT_GRANTED`), to be free of suspension
        (otherwise `ERR_ESTABLISHMENT_SUSPENDED`), and not to be withdrawn
        (otherwise `ERR_ESTABLISHMENT_WITHDRAWN`)."
        PRD §2.5: "Granting inspection moves the pair to `GRANTED` × `ACTIVE`
        in a single request."

        Design: Difficulty/cross_entity_state_dependency/shift_window_requires_granted_establishment
        """
        est = fx.create_establishment(
            api, name="D14 Beef Plant", species_classes=["CATTLE"], slaughter_capable=True
        )
        manager = make_establishment_manager_headers(est["id"])

        rejected = api.create_shift_window(f.shift_window_payload(est["id"]), manager)
        validate_error(rejected, ApiErrorId.ERR_ESTABLISHMENT_NOT_GRANTED)

        application = fx.create_grant_application(api, est["id"])
        fx.begin_grant_review(api, application["id"])
        fx.record_all_adequate(api, application["id"])
        fx.decide_grant(api, application["id"], "GRANT")

        created = api.create_shift_window(f.shift_window_payload(est["id"]), manager)
        window = validate_success(created, 201)
        assert_shift_window(window)
        assert window["status"] == "PLANNED"

    def test_new_window_is_planned_with_null_gap_fields(self, api):
        """PRD §3.2: "A new window is `PLANNED`, and both of its gap fields,
        `provisional_gap_minutes` and `final_gap_minutes`, remain null until
        the first coverage verification."
        PRD §2.6: "The `version` is an integer that starts at 1 when the
        resource is created and increments by 1 on every mutation of that
        resource — including mutations caused by system cascades, so a client
        watching a parent's `version` sees every derived change."

        Design: Difficulty/cross_entity_state_dependency/shift_window_requires_granted_establishment
        """
        base = fx.create_granted_establishment(api, species_classes=["CATTLE"], name="D14 Null Plant")
        est_id = base["establishment"]["id"]

        created = api.create_shift_window(
            f.shift_window_payload(est_id), make_establishment_manager_headers(est_id)
        )
        window = validate_success(created, 201)

        assert window["status"] == "PLANNED"
        assert window["provisional_gap_minutes"] is None, "null until the first verification"
        assert window["final_gap_minutes"] is None, "null until the first verification"
        assert window["version"] == 1


class TestLabelResubmitBlockedWhileSuspended:
    def _returned_label_on_suspended_establishment(self, api):
        """Granted establishment; label RETURNED for revision (not subject to
        the HOLD cascade); establishment then suspended via egregious confirm."""
        base = fx.create_granted_establishment(api, species_classes=["CATTLE"], name="D15 Beef Plant")
        est = base["establishment"]
        label = fx.create_label_in_review(
            api, est["id"], product_name="Grass Chuck", label_claim="GRASS_FED",
            documentation_refs=["doc-g1"],
        )
        fx.decide_label(api, label["id"], "RETURN")
        pair = fx.create_inspector_pair(api, ["CATTLE"])
        cycle = fx.suspend_establishment_via_egregious_event(
            api, fx.get_establishment(api, est["id"]), pair["issuer"]["id"], pair["reviewer"]["id"],
            observed_at="2026-08-31T06:30:00Z",
        )
        return est, label, cycle

    def test_resubmit_rejected_with_establishment_suspended(self, api):
        """PRD §3.7: "A returned application may be resubmitted by the
        `EstablishmentManager` with refreshed `documentation_refs`:
        resubmission requires `RETURNED` status (otherwise
        `ERR_INVALID_STATE`), is ownership-pinned to the application's
        `establishment_id` (else `ERR_FORBIDDEN`), and is barred while the
        establishment is `SUSPENDED` (otherwise `ERR_ESTABLISHMENT_SUSPENDED`)."

        Design: Difficulty/cross_entity_state_dependency/label_resubmit_blocked_while_suspended
        """
        est, label, _cycle = self._returned_label_on_suspended_establishment(api)
        suspended = fx.get_establishment(api, est["id"])
        assert suspended["inspection_status"] == "SUSPENDED"

        resp = api.resubmit_label_application(
            label["id"],
            f.label_resubmit_payload(["doc-g1", "doc-g2"]),
            make_establishment_manager_headers(est["id"]),
        )

        validate_error(resp, ApiErrorId.ERR_ESTABLISHMENT_SUSPENDED)
        labels = fx.list_label_applications(api, est["id"])
        assert len(labels) == 1 and labels[0]["status"] == "RETURNED", "the rejection changes nothing"

    def test_resubmit_succeeds_after_suspension_lifted(self, api):
        """PRD §3.7: "It moves the application back to `SUBMITTED`, increments
        `revision_count` by 1, and replaces `documentation_refs` with the
        payload's array."
        PRD §3.4: "Lifting a `SUSPENSION` moves the establishment's
        `inspection_status` from `SUSPENDED` back to `ACTIVE`, moves every
        label application in `HELD` back to `UNDER_REVIEW`, and leaves blocked
        shift windows `BLOCKED` — their windows lie in the past and are not
        resurrected."

        Design: Difficulty/cross_entity_state_dependency/label_resubmit_blocked_while_suspended
        """
        est, label, cycle = self._returned_label_on_suspended_establishment(api)

        fx.lift_enforcement(api, cycle["enforcement_action"]["id"])
        active = fx.get_establishment(api, est["id"])
        assert active["inspection_status"] == "ACTIVE"

        resp = api.resubmit_label_application(
            label["id"],
            f.label_resubmit_payload(["doc-g1", "doc-g2"]),
            make_establishment_manager_headers(est["id"]),
        )
        resubmitted = validate_success(resp, 200)

        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1, "resubmission increments revision_count by 1"
        assert resubmitted["documentation_refs"] == ["doc-g1", "doc-g2"], (
            "documentation_refs replaced with the payload's array"
        )
