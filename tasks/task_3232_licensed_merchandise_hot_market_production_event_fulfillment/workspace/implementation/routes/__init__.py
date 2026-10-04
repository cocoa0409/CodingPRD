"""Route modules for the licensed-merchandise hot-market API.

Importing this package registers every endpoint on the shared API blueprint.
"""
from routes import (capacity, enforcement, fulfillment,  # noqa: F401
                    licensing, production)
