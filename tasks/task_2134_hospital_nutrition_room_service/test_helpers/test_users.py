"""Pre-built role headers.

Identity is opaque for all five roles (PRD 2.1): the X-User-ID is never
compared to any entity's id, only to a previously recorded actor identifier
for the segregation-of-duties checks of PRD 2.10. Distinct identifiers are
therefore what matters, and the builders below let a test choose one.
"""
from prd_bench_local_runner.testing import build_user_headers

PHYSICIAN_1 = "u-phys-1"
PHYSICIAN_2 = "u-phys-2"
DIETITIAN_1 = "u-rd-1"
DIETITIAN_2 = "u-rd-2"
DIET_CLERK_1 = "u-clerk-1"
TRAY_AIDE_1 = "u-aide-1"
TRAY_AIDE_2 = "u-aide-2"
NUTRITION_MANAGER_1 = "u-mgr-1"

TEST_USERS = {
    "physician_headers": build_user_headers(PHYSICIAN_1, "Physician"),
    "physician_2_headers": build_user_headers(PHYSICIAN_2, "Physician"),
    "dietitian_headers": build_user_headers(DIETITIAN_1, "Dietitian"),
    "dietitian_2_headers": build_user_headers(DIETITIAN_2, "Dietitian"),
    "diet_clerk_headers": build_user_headers(DIET_CLERK_1, "DietClerk"),
    "tray_aide_headers": build_user_headers(TRAY_AIDE_1, "TrayAide"),
    "tray_aide_2_headers": build_user_headers(TRAY_AIDE_2, "TrayAide"),
    "nutrition_manager_headers": build_user_headers(NUTRITION_MANAGER_1, "NutritionManager"),
}

# Headers carrying neither X-User-ID nor X-User-Role (PRD 2.1 authentication).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_physician_headers(user_id: str) -> dict:
    """Physician acting under an explicitly chosen opaque identifier."""
    return build_user_headers(user_id, "Physician")


def make_dietitian_headers(user_id: str) -> dict:
    """Dietitian acting under an explicitly chosen opaque identifier."""
    return build_user_headers(user_id, "Dietitian")


def make_diet_clerk_headers(user_id: str) -> dict:
    """DietClerk acting under an explicitly chosen opaque identifier."""
    return build_user_headers(user_id, "DietClerk")


def make_tray_aide_headers(user_id: str) -> dict:
    """TrayAide acting under an explicitly chosen opaque identifier."""
    return build_user_headers(user_id, "TrayAide")


def make_nutrition_manager_headers(user_id: str) -> dict:
    """NutritionManager acting under an explicitly chosen opaque identifier."""
    return build_user_headers(user_id, "NutritionManager")
