"""HTTP endpoint for chat attachment downloads / previews.

The chat turn runtime persists every uploaded attachment to the
:class:`~deeptutor.services.storage.AttachmentStore` and records the public
URL on the message. The frontend preview drawer loads files via this
router, which only serves paths the store hands back — every component is
sanitised to defend against directory traversal.

URL shape::

    GET /api/attachments/{session_id}/{attachment_id}/{filename}

The session id functions as the ACL boundary, mirroring how the rest of
the app treats sessions today (single-tenant, session ownership is local
trust). Once multi-user auth lands we should swap this for signed URLs.
"""

from __future__ import annotations

import logging
import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from deeptutor.api.utils.http_headers import content_disposition
from deeptutor.services.storage import (
    LocalDiskAttachmentStore,
    get_attachment_store,
)

logger = logging.getLogger(__name__)

router = APIRouter()


_content_disposition = content_disposition


def _admin_attachment_store() -> LocalDiskAttachmentStore:
    """Attachment store rooted at the admin workspace (``data/user/...``).

    Chat attachments written before per-user path scoping landed live in the
    admin workspace (the deployment today is single-admin: the XiaoZhi shadow
    user resolves to the admin scope). The notebook/web UI references those
    files via their public URL, so serving must fall back to the admin root
    even when the current requester's scope resolves elsewhere (e.g. the
    anonymous guest scope used when manager-web loads the image).
    """
    from deeptutor.multi_user.paths import get_admin_path_service

    root = get_admin_path_service().get_user_root() / "workspace" / "chat" / "attachments"
    return LocalDiskAttachmentStore(root=root)


@router.get("/{session_id}/{attachment_id}/{filename:path}")
async def get_attachment(
    session_id: str,
    attachment_id: str,
    filename: str,
):
    """Serve a previously uploaded chat attachment.

    Responds with ``Content-Disposition: inline`` so browsers preview PDFs
    and images directly in an ``<iframe>`` / ``<img>``. For unknown types
    the browser still falls back to download, which is fine for the
    drawer's "Download" button path.
    """
    store = get_attachment_store()
    if not isinstance(store, LocalDiskAttachmentStore):
        # Future remote backends should issue a redirect to the signed URL
        # here. Local-disk is the only backend today, so this branch just
        # guards against an unexpected configuration.
        raise HTTPException(status_code=501, detail="Attachment backend not servable")

    target = store.resolve_path(
        session_id=session_id,
        attachment_id=attachment_id,
        filename=filename,
    )
    # Files under the admin workspace keep working for any requester scope.
    if target is None:
        target = _admin_attachment_store().resolve_path(
            session_id=session_id,
            attachment_id=attachment_id,
            filename=filename,
        )
    if target is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    media_type, _ = mimetypes.guess_type(target.name)
    if not media_type:
        media_type = "application/octet-stream"

    # ``inline`` lets the browser preview the file when possible while still
    # honouring the suggested filename for the drawer's download action.
    headers = {
        "Content-Disposition": _content_disposition(target.name),
        # User-uploaded data; do not let intermediaries cache it.
        "Cache-Control": "private, max-age=0, must-revalidate",
    }
    return FileResponse(path=str(target), media_type=media_type, headers=headers)
