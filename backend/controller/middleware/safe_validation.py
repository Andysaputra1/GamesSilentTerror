"""Keep credentials out of FastAPI validation error responses."""

from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class SafeValidationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": [
                            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                            for item in error.errors()
                        ]
                    },
                    headers={"Cache-Control": "no-store"},
                )

        return safe_handler
