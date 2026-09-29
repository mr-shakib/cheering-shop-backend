"""The admin console's files: the React app in admin-web/, built into
app/static/admin (`make admin-build`, or the Docker image's first stage).

It is a single-page app. A reload or a shared link asks for a path like
/admin/orders?order=… or /admin/vendors/<id>, and no such file exists — the
router inside index.html resolves it. So a miss on anything that is not an
asset answers with index.html. A miss on an asset (a path with a file
extension) stays a 404: serving HTML where the browser expects a JavaScript
module fails with a MIME error far harder to diagnose than the 404.
"""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

NOT_BUILT = (
    "The admin console has not been built. Run `make admin-build`, "
    "or build the Docker image, which builds it."
)


def _is_asset(path: str) -> bool:
    return "." in path.rsplit("/", 1)[-1]


class AdminConsoleFiles(StaticFiles):
    def __init__(self, directory: Path) -> None:
        # check_dir=False: a checkout that has not built the console must still
        # start the API; the console answers 503 until it is built.
        super().__init__(directory=directory, html=True, check_dir=False)

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or _is_asset(path):
                raise
            response = await self._index(scope)
        if path.startswith("assets/") and response.status_code == 200:
            # Vite fingerprints every file under assets/ (index-3f2a1c.js), so
            # a new build is a new name and these never need revalidating.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    async def _index(self, scope: Scope) -> Response:
        try:
            return await super().get_response("index.html", scope)
        except HTTPException:
            return PlainTextResponse(NOT_BUILT, status_code=503)
