from fastapi import APIRouter, Query, Response

from app.api.deps import Storage
from app.services.files import read_signed_object
from app.utils.filenames import safe_filename

router = APIRouter(prefix="/files")


@router.get("/{key:path}", include_in_schema=False)
async def download_signed(
    key: str,
    storage: Storage,
    exp: int = Query(ge=0),
    sig: str = Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
    filename: str | None = Query(default=None, max_length=255),
) -> Response:
    """Local-storage download. Access is granted by the signature, not by login."""
    data, content_type = await read_signed_object(storage, key=key, expires=exp, signature=sig)
    headers = {"Cache-Control": "private, no-store"}
    safe = safe_filename(filename)
    if safe:
        headers["Content-Disposition"] = f'attachment; filename="{safe}"'
    return Response(content=data, media_type=content_type, headers=headers)
