from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, schemas
from .auth import require_landlord, get_current_user_optional
from ..rate_limit import rate_limit

router = APIRouter()


@router.get("/properties", response_model=List[schemas.PropertyRead])
def list_properties(db: Session = Depends(get_db), user: Optional[models.User] = Depends(get_current_user_optional)):
    if user and user.role == "landlord":
        items = (
            db.query(models.Property)
            .filter(models.Property.owner_id == user.id)
            .order_by(models.Property.id.desc())
            .all()
        )
    else:
        items = db.query(models.Property).order_by(models.Property.id.desc()).all()
    return items


@router.post(
    "/properties",
    response_model=schemas.PropertyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("write"))],
)
def create_property(payload: schemas.PropertyCreate, db: Session = Depends(get_db), user: models.User = Depends(require_landlord)):
    # Basic server-side validation already handled by Pydantic types.
    obj = models.Property(owner_id=user.id, title=payload.title, price_cents=payload.price_cents)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
