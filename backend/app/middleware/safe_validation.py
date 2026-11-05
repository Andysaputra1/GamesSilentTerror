"""Jaga agar kredensial tidak ikut terkirim di respons error validasi FastAPI."""

from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class SafeValidationRoute(APIRoute):
    def get_route_handler(self):
        penangan_asli = super().get_route_handler()

        # Hanya loc, msg, dan type yang dikirim; kolom input bisa berisi password.
        async def penangan_aman(request):
            try:
                return await penangan_asli(request)
            except RequestValidationError as error:
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": [
                            {"loc": galat["loc"], "msg": galat["msg"], "type": galat["type"]}
                            for galat in error.errors()
                        ]
                    },
                    headers={"Cache-Control": "no-store"},
                )

        return penangan_aman
