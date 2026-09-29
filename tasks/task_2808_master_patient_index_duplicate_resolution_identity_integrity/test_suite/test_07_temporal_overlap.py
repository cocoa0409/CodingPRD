"""Two windowing conventions that disagree about their shared boundary."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import (
    ERR_DISPATCH_CAPACITY_EXCEEDED,
    ERR_METRIC_WINDOW_OVERLAP,
)
from test_helpers.constants import (
    ATTRIBUTION_CREATION_SITE,
    ATTRIBUTION_SURVIVOR_SITE,
    RS_BASE_VERSION_LABEL,
    TASK_QUEUED,
    TASK_SENT,
)
from test_helpers.test_users import admin_headers

DW_OVERLAYS = (
    ("DW-1001", "Okonkwo", "Chidi", "1980-03-03", "M", "1111", "75201", "2145550101",
     "2145550901", "2026-07-01", "2026-07-04", 6),
    ("DW-1002", "Barros", "Luiza", "1993-07-21", "F", "2222", "75202", "2145550102",
     "2145550902", "2026-07-02", "2026-07-05", 7),
    ("DW-1003", "Tanaka", "Hiroshi", "1975-11-02", "M", "3333", "75203", "2145550103",
     "2145550903", "2026-07-03", "2026-07-06", 8),
)


def _three_queued_tasks(api):
    """Three QUEUED OVERLAY_CORRECTION tasks on a consumer allowing one dispatch."""
    site = F.create_site(
        api, "SITE-DW", name="Dispatch Window Clinic", region_code="US-TX",
        registrar_headcount=4,
    )
    system = F.create_system(
        api, "EHR-CORE", name="Core EHR", ack_required=True,
        max_concurrent_dispatch=1,
    )
    tasks = []
    for (
        mrn, last_name, first_name, dob, sex, ssn_last4, postal_code, phone,
        new_phone, from_date, to_date, elements,
    ) in DW_OVERLAYS:
        record = F.create_record(
            api, site["id"], mrn, last_name, first_name, dob, sex,
            ssn_last4=ssn_last4, postal_code=postal_code, phone=phone,
            clinical_element_count=elements,
        )
        overlay = F.create_overlay(
            api, record["id"], {"phone": new_phone}, 3, record["version"],
            encounter_from_date=from_date, encounter_to_date=to_date,
        )
        F.apply_overlay(api, overlay["id"])
        tasks.append(F.first_task_for_overlay(api, overlay["id"]))
    return system, tasks


class TestHalfOpenDispatchWindows:
    def test_a_window_starting_where_a_sent_window_ends_is_admitted(self, api):
        """Touching endpoints leave the single dispatch slot free.

        PRD §3.6: "Two windows overlap when the first starts before the second ends
        and the second starts before the first ends; touching endpoints therefore do
        not overlap, and back-to-back dispatches are always admissible."

        Design: Difficulty/resource_temporal_overlap/dispatch_window_half_open_adjacency_then_capacity_breach
        """
        _, tasks = _three_queued_tasks(api)
        for task in tasks:
            assert task["state"] == TASK_QUEUED
            A.assert_integer(task["attempt_count"], 0, "attempt_count")
            A.assert_instant(
                task["propagation_deadline_at"], "2026-08-04T00:00:00Z",
                "propagation_deadline_at",
            )

        first = F.send_task(
            api, tasks[0]["id"], "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z"
        )
        second = F.send_task(
            api, tasks[1]["id"], "2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z"
        )

        assert first["state"] == TASK_SENT
        A.assert_integer(first["attempt_count"], 1, "attempt_count")
        assert second["state"] == TASK_SENT
        A.assert_integer(second["attempt_count"], 1, "attempt_count")

    def test_a_window_straddling_the_seam_overlaps_both_and_breaches_capacity(
        self, api
    ):
        """Occupancy 2 against a ceiling of 1 is rejected and changes nothing.

        PRD §3.6: "And the consumer's dispatch capacity must not be exhausted:
        counting every **other** propagation task on the same consumer whose `state`
        is `SENT`, and treating each stored window as covering its start instant but
        not its end instant, the number of those windows that overlap the requested
        window must be strictly less than the consumer's `max_concurrent_dispatch`."

        Design: Difficulty/resource_temporal_overlap/dispatch_window_half_open_adjacency_then_capacity_breach
        """
        _, tasks = _three_queued_tasks(api)
        F.send_task(api, tasks[0]["id"], "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        F.send_task(api, tasks[1]["id"], "2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z")

        response = api.send_task(
            tasks[2]["id"],
            f.send_payload("2026-08-02T10:30:00Z", "2026-08-02T11:30:00Z"),
            admin_headers(),
        )

        A.assert_error_envelope(response, ERR_DISPATCH_CAPACITY_EXCEEDED, 409)
        untouched = F.get_task(api, tasks[2]["id"])
        assert untouched["state"] == TASK_QUEUED
        A.assert_integer(untouched["attempt_count"], 0, "attempt_count")
        A.assert_version(untouched, 1)
        assert untouched["dispatch_window_start_at"] is None
        assert untouched["dispatch_window_end_at"] is None

    def test_the_rejected_task_still_counts_as_unacknowledged_work(self, api):
        """Two dispatched tasks and one that never left both remain unacked.

        PRD §3.6: "Tasks in `QUEUED`, `ACKED`, `FAILED` or `CANCELLED` hold no
        capacity whatsoever."

        Design: Difficulty/resource_temporal_overlap/dispatch_window_half_open_adjacency_then_capacity_breach
        """
        system, tasks = _three_queued_tasks(api)
        F.send_task(api, tasks[0]["id"], "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        F.send_task(api, tasks[1]["id"], "2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z")
        api.send_task(
            tasks[2]["id"],
            f.send_payload("2026-08-02T10:30:00Z", "2026-08-02T11:30:00Z"),
            admin_headers(),
        )

        A.assert_integer(
            F.get_system(api, system["id"])["unacked_task_count"], 3,
            "unacked_task_count",
        )
        sent_rows = A.list_rows(
            api.list_tasks(
                admin_headers(),
                {"downstream_system_id": system["id"], "state": TASK_SENT},
            )
        )
        assert len(sent_rows) == 2


def _metric_site(api):
    """One site with one record created inside the first measurement window."""
    site = F.create_site(
        api, "SITE-MW", name="Metric Window Clinic", region_code="US-AZ",
        registrar_headcount=2,
    )
    F.create_rule_set(api, activate=True)
    F.create_record(
        api, site["id"], "MW-2001", "Fitzgerald", "Aoife", "1990-05-17", "F",
        ssn_last4="4455", postal_code="85004", phone="6025550101",
        clinical_element_count=3,
    )
    return site


class TestClosedMetricWindows:
    def test_the_first_run_measures_the_site_and_warns_about_the_sample(self, api):
        """One registration, no merges, and an insufficient sample size.

        PRD §3.9: "Finally `sample_size_sufficient` is true when `records_created` is
        at least 30, warning readers off drawing conclusions from a desk that
        registered a handful of patients, and `rule_set_version_label` snapshots the
        `version_label` of whichever rule set was `ACTIVE` when the run executed, as a
        plain audit string."

        Design: Difficulty/resource_temporal_overlap/metric_window_closed_adjacency_collides_but_other_variant_does_not
        """
        site = _metric_site(api)

        run = A.assert_created(
            F.run_metric(api, site["id"], "2026-08-01", "2026-08-15")
        )

        A.assert_integer(run["records_created"], 1, "records_created")
        A.assert_integer(run["confirmed_duplicates"], 0, "confirmed_duplicates")
        A.assert_integer(run["duplicate_rate_bps"], 0, "duplicate_rate_bps")
        assert run["sample_size_sufficient"] is False
        assert run["rule_set_version_label"] == RS_BASE_VERSION_LABEL

    def test_a_window_starting_on_the_earlier_run_s_end_date_collides(self, api):
        """Closed windows that merely abut are treated as overlapping.

        PRD §3.9: "Before anything is computed, the requested window is checked for
        exclusivity against every existing metric run on the **same** site with the
        **same** `attribution_variant`: because both boundary dates belong to their
        window, two windows collide whenever the first's start date is no later than
        the second's end date and the second's start date is no later than the first's
        end date, so windows that merely abut collide too."

        Design: Difficulty/resource_temporal_overlap/metric_window_closed_adjacency_collides_but_other_variant_does_not
        """
        site = _metric_site(api)
        A.assert_created(F.run_metric(api, site["id"], "2026-08-01", "2026-08-15"))

        response = F.run_metric(api, site["id"], "2026-08-15", "2026-08-31")

        A.assert_error_envelope(response, ERR_METRIC_WINDOW_OVERLAP, 409)

    def test_the_other_variant_accepts_the_very_same_dates(self, api):
        """Exclusivity is partitioned by attribution_variant, not by site alone.

        PRD §3.9: "Runs of the *other* variant are ignored entirely, so both
        attribution views may be computed over identical windows."

        Design: Difficulty/resource_temporal_overlap/metric_window_closed_adjacency_collides_but_other_variant_does_not
        """
        site = _metric_site(api)
        A.assert_created(F.run_metric(api, site["id"], "2026-08-01", "2026-08-15"))
        F.run_metric(api, site["id"], "2026-08-15", "2026-08-31")

        run = A.assert_created(
            F.run_metric(
                api, site["id"], "2026-08-15", "2026-08-31",
                attribution_variant=ATTRIBUTION_SURVIVOR_SITE,
            )
        )

        A.assert_integer(run["records_created"], 0, "records_created")
        A.assert_integer(run["duplicate_rate_bps"], 0, "duplicate_rate_bps")
        assert run["sample_size_sufficient"] is False
        assert run["attribution_variant"] == ATTRIBUTION_SURVIVOR_SITE

    def test_moving_the_start_one_day_clears_the_shared_boundary(self, api):
        """The collision was exactly the shared date, so 2026-08-16 is accepted.

        PRD §3.9: "`records_created` is the number of patient records registered at
        the site whose `created_at` date falls inside the closed window, compared
        date-only in UTC, counted with **no** `identity_state` filter at all — records
        later absorbed into a cluster still count, because the desk still created
        them."

        Design: Difficulty/resource_temporal_overlap/metric_window_closed_adjacency_collides_but_other_variant_does_not
        """
        site = _metric_site(api)
        A.assert_created(F.run_metric(api, site["id"], "2026-08-01", "2026-08-15"))
        F.run_metric(api, site["id"], "2026-08-15", "2026-08-31")

        run = A.assert_created(
            F.run_metric(api, site["id"], "2026-08-16", "2026-08-31")
        )

        A.assert_integer(run["records_created"], 0, "records_created")
        assert run["attribution_variant"] == ATTRIBUTION_CREATION_SITE

    def test_the_rejected_run_leaves_no_row_behind(self, api):
        """Three runs are readable and the variant filter splits them two to one.

        PRD §3.9: "A metric run is a write-once event record: it carries only `id`
        and `created_at`, and is never amended."

        Design: Difficulty/resource_temporal_overlap/metric_window_closed_adjacency_collides_but_other_variant_does_not
        """
        site = _metric_site(api)
        A.assert_created(F.run_metric(api, site["id"], "2026-08-01", "2026-08-15"))
        F.run_metric(api, site["id"], "2026-08-15", "2026-08-31")
        A.assert_created(
            F.run_metric(
                api, site["id"], "2026-08-15", "2026-08-31",
                attribution_variant=ATTRIBUTION_SURVIVOR_SITE,
            )
        )
        A.assert_created(F.run_metric(api, site["id"], "2026-08-16", "2026-08-31"))

        all_rows = A.list_rows(api.list_metric_runs(site["id"], admin_headers()))
        creation_rows = A.list_rows(
            api.list_metric_runs(
                site["id"], admin_headers(),
                {"attribution_variant": ATTRIBUTION_CREATION_SITE},
            )
        )

        assert len(all_rows) == 3
        assert len(creation_rows) == 2
