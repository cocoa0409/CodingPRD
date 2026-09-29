"""Blueprint registry."""
from routes.catalogue import bp as catalogue_bp
from routes.feeds import bp as feeds_bp
from routes.ltos import bp as ltos_bp
from routes.menu_items import bp as menu_items_bp
from routes.proposals import bp as proposals_bp
from routes.recipes import bp as recipes_bp
from routes.reviews import bp as reviews_bp
from routes.spec_orders import bp as spec_orders_bp

BLUEPRINTS = (
    catalogue_bp,
    feeds_bp,
    recipes_bp,
    menu_items_bp,
    proposals_bp,
    spec_orders_bp,
    reviews_bp,
    ltos_bp,
)
