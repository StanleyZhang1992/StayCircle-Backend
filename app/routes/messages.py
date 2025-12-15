from typing import List, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, schemas
from .auth import get_current_user

router = APIRouter()
logger = logging.getLogger("staycircle.chat")


@router.get("/messages", response_model=List[schemas.MessageRead])
def list_messages(
    property_id: int = Query(..., ge=1),
    limit: int = Query(50, ge=1, le=100),
    since_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> List[schemas.MessageRead]:
    """
    Returns chat history for a property.
    Authorization:
      - tenant: allowed
      - landlord: must own the property
    Ordered ascending by created_at, then id (stable).
    Supports since_id pagination (strictly greater than).
    """
    # Validate property
    prop = db.get(models.Property, property_id)
    if not prop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    # Authorization
    if user.role == "landlord":
        if prop.owner_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not owner of property")
    elif user.role == "tenant":
        # tenants can read (public inquiry)
        pass
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    q = db.query(models.Message).filter(models.Message.property_id == property_id)
    if since_id is not None:
        q = q.filter(models.Message.id > since_id)

    q = q.order_by(models.Message.created_at.asc(), models.Message.id.asc()).limit(limit)

    items = q.all()

    logger.info(
        "messages.history",
        extra={
            "property_id": property_id,
            "since_id": since_id,
            "limit": limit,
            "count": len(items),
            "user_id": user.id,
            "role": user.role,
        },
    )
    # FastAPI/Pydantic will coerce ORM objects thanks to model_config(from_attributes=True)
    return items
