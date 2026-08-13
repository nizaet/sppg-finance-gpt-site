"""Production ASGI entrypoint.

Keep backend.app as the FastAPI route definition used by tests/schema builders,
then wrap it here with SPPG role/site enforcement for the deployed service.
The middleware is inert until all SPPG auth environment variables are configured.
"""

from backend.app import app as fastapi_app
from backend.auth_middleware import SppgAccessMiddleware

app = SppgAccessMiddleware(fastapi_app)
