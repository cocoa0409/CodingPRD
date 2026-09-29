"""The four multi-hop cascades of PRD sections 2.9, 3.1, 3.8 and 3.9.

Every cascade is immediate and complete: all hops land inside the request that
triggered them, and every row actually mutated has its version bumped once.
"""

import calc
from store import store

HOP2_PLACEMENT_STATUSES = ("DRAFT", "VALIDATED")
HOP2_PROJECT_STATUSES = (
    "CONSULTATION",
    "RENDERED",
    "COMMUNITY_REVIEW",
    "REVISION_REQUESTED",
    "DESIGN_APPROVED",
    "CERTIFIED",
    "ORDERED",
)
HOP3_REVERTED_FROM = ("RENDERED", "COMMUNITY_REVIEW", "CERTIFIED")

CANCELLABLE_ORDER_STATUSES = ("CREATED", "IN_PRODUCTION")
CANCELLABLE_JOB_STATUSES = ("SCHEDULED", "IN_PROGRESS")


def expire_issued_quotes(project_id, exclude_id=None):
    """Move every ISSUED quote of the project to EXPIRED (PRD section 3.5)."""
    for quote in store.project_quotes(project_id):
        if quote["id"] == exclude_id:
            continue
        if quote["status"] == "ISSUED":
            quote["status"] = "EXPIRED"
            store.touch(quote)


# ------------------------------------------------------- standard supersession

def supersede_standard(retired, successor):
    """PRD section 3.1: the retirement of the ACTIVE edition, hop by hop."""
    retired["status"] = "SUPERSEDED"
    retired["superseded_by_standard_id"] = successor["id"]
    store.touch(retired)
    successor["status"] = "ACTIVE"
    store.touch(successor)

    # Hop one: models pinned to the retired edition lose their certification.
    decertified = []
    for model in store.all("model"):
        if (model["certified_against_standard_id"] == retired["id"]
                and model["certification_status"] == "CERTIFIED"):
            model["certification_status"] = "DECERTIFIED"
            store.touch(model)
            decertified.append(model["id"])
    decertified_ids = set(decertified)

    # Hop two: placements of those models need recertification.
    touched_area_ids = []
    affected_project_ids = []
    if decertified_ids:
        for placement in store.all("placement"):
            if placement["component_model_id"] not in decertified_ids:
                continue
            if placement["status"] not in HOP2_PLACEMENT_STATUSES:
                continue
            project = store.placement_project(placement)
            if project is None or project["design_status"] not in HOP2_PROJECT_STATUSES:
                continue
            placement["status"] = "NEEDS_RECERTIFICATION"
            store.touch(placement)
            if placement["play_area_id"] not in touched_area_ids:
                touched_area_ids.append(placement["play_area_id"])
            if project["id"] not in affected_project_ids:
                affected_project_ids.append(project["id"])

    # Hop three: the owning projects lose their compliance posture, and most of
    # them are reverted for repair.  DESIGN_APPROVED keeps its sign-off.
    reverted_project_ids = []
    for project_id in affected_project_ids:
        project = store.get("project", project_id)
        project["compliance_status"] = "RETROFIT_REQUIRED"
        if project["design_status"] in HOP3_REVERTED_FROM:
            project["design_status"] = "REVISION_REQUESTED"
            reverted_project_ids.append(project_id)
        store.touch(project)

    # Hop four: reverted projects lose their frozen rendering and their quote.
    for project_id in reverted_project_ids:
        for rendering in store.project_renderings(project_id):
            if rendering["status"] == "ISSUED":
                rendering["status"] = "SUPERSEDED"
                store.touch(rendering)
        for quote in store.project_quotes(project_id):
            if quote["status"] == "ISSUED":
                quote["status"] = "EXPIRED"
                store.touch(quote)

    # Derived surfacing numbers follow the shrunken placement input set.
    for area_id in touched_area_ids:
        area = store.get("area", area_id)
        if area is None:
            continue
        calc.recompute_area_geometry_quiet(area)
        store.touch(area)


# ----------------------------------------------------------- job cancellations

def cancel_installer_jobs(installer, exclude_job_id=None):
    """Cancel an installer's live jobs and re-derive its crew-day ledger."""
    for job in store.installer_jobs(installer["id"]):
        if job["id"] == exclude_job_id:
            continue
        if job["status"] in CANCELLABLE_JOB_STATUSES:
            job["status"] = "CANCELLED"
            store.touch(job)
    calc.recompute_committed_crew_days(installer)


# ------------------------------------------------------- project cancellation

def cancel_project(project):
    """PRD section 3.9: cancellation fans out to orders, jobs, pledges, quotes."""
    project["design_status"] = "CANCELLED"
    store.touch(project)

    touched_installer_ids = []
    for order in store.project_orders(project["id"]):
        if order["production_status"] not in CANCELLABLE_ORDER_STATUSES:
            continue
        order["production_status"] = "CANCELLED"
        store.touch(order)
        for job in store.order_jobs(order["id"]):
            if job["status"] not in CANCELLABLE_JOB_STATUSES:
                continue
            job["status"] = "CANCELLED"
            store.touch(job)
            if job["installer_id"] not in touched_installer_ids:
                touched_installer_ids.append(job["installer_id"])

    for installer_id in touched_installer_ids:
        installer = store.get("installer", installer_id)
        if installer is None:
            continue
        calc.recompute_committed_crew_days(installer)
        store.touch(installer)

    for pledge in store.project_pledges(project["id"]):
        if pledge["status"] in ("PLEDGED", "COLLECTED"):
            pledge["status"] = "REFUNDED"
            store.touch(pledge)

    for quote in store.project_quotes(project["id"]):
        if quote["status"] == "ISSUED":
            quote["status"] = "EXPIRED"
            store.touch(quote)

    calc.recompute_fundraising(project)


# ------------------------------------------------ post-installation audit fail

def audit_failure_cascade(job, project, installer):
    """PRD section 3.8 hops two through four of a failed post-install audit."""
    project["compliance_status"] = "NON_COMPLIANT"
    store.touch(project)

    calc.recompute_open_audit_failures(installer)
    if installer["open_audit_failures"] >= calc.AUDIT_FAILURE_SUSPENSION_THRESHOLD:
        installer["status"] = "SUSPENDED"
        cancel_installer_jobs(installer, exclude_job_id=job["id"])
    else:
        calc.recompute_committed_crew_days(installer)
    store.touch(installer)
