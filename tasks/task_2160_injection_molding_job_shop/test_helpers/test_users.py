"""Pre-built role headers for every role in the PRD.

Five of the six roles bind ``X-User-ID`` to an opaque operator identifier that
is never compared to any entity's ``id``.  ``CustomerRep`` is different: its
``X-User-ID`` is the ``id`` of the acting ``Customer``, and every ownership
check compares the resource's customer foreign key to it -- so a CustomerRep
call must always be built with :func:`make_customer_rep_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

# Two distinct QualityEngineer principals: the PRD's only segregation-of-duties
# rule is enforced on the person, not the role.
QE_SUBMITTER_USER_ID = "qe-alice"
QE_REVIEWER_USER_ID = "qe-bob"

TEST_USERS = {
    "plant_admin_headers": build_user_headers("pa-1", "PlantAdmin"),
    "sales_engineer_headers": build_user_headers("se-carol", "SalesEngineer"),
    "process_engineer_headers": build_user_headers("pe-dan", "ProcessEngineer"),
    "quality_engineer_headers": build_user_headers(QE_SUBMITTER_USER_ID, "QualityEngineer"),
    "quality_reviewer_headers": build_user_headers(QE_REVIEWER_USER_ID, "QualityEngineer"),
    "toolroom_tech_headers": build_user_headers("tt-erin", "ToolroomTech"),
    # Placeholder only: a CustomerRep call that touches an ownership check must
    # use make_customer_rep_headers(customer["id"]) instead.
    "customer_rep_headers": build_user_headers("cr-unbound", "CustomerRep"),
}


def make_customer_rep_headers(customer_id: str) -> dict:
    """Headers for a CustomerRep acting for the Customer whose id is given.

    Pass the actual Customer id: every ownership check compares the resource's
    customer foreign key to this value.
    """
    return build_user_headers(customer_id, "CustomerRep")


def make_quality_engineer_headers(user_id: str) -> dict:
    """Headers for a named QualityEngineer principal."""
    return build_user_headers(user_id, "QualityEngineer")


def make_plant_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantAdmin")


def make_headers_without_role(user_id: str = "pa-1") -> dict:
    """Headers carrying X-User-ID but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
