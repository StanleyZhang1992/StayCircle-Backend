from pydantic import BaseModel, Field, ConfigDict, field_validator, EmailStr
from typing import Literal, Union, Optional
from datetime import date, datetime


class PropertyBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    price_cents: int = Field(..., ge=0)
    requires_approval: bool = False

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, v: str) -> str:
        # Normalize whitespace before validation
        if isinstance(v, str):
            v = v.strip()
        return v


class PropertyCreate(PropertyBase):
    pass


class PropertyRead(PropertyBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ----------------
# Booking Schemas
# ----------------
class BookingBase(BaseModel):
    property_id: int = Field(..., ge=1)
    start_date: date
    end_date: date


class BookingCreate(BookingBase):
    pass


class BookingRead(BookingBase):
    id: int
    guest_id: int
    status: Literal[
        "requested",
        "pending_payment",
        "confirmed",
        "cancelled",
        "cancelled_expired",
        "declined",
    ]
    total_cents: int
    currency: str = "USD"
    expires_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ----------------
# Booking Create Response (Sprint 7)
# ----------------
class NextActionAwaitApproval(BaseModel):
    type: Literal["await_approval"]


class NextActionPay(BaseModel):
    type: Literal["pay"]
    expires_at: datetime
    client_secret: str


class BookingCreateResponse(BaseModel):
    booking: BookingRead
    next_action: Union[NextActionAwaitApproval, NextActionPay]


# ----------------
# Payments (Sprint 8)
# ----------------
class PaymentInfoResponse(BaseModel):
    booking_id: int
    client_secret: str
    expires_at: datetime

# ----------------
# Auth/User Schemas
# ----------------

Role = Literal["landlord", "tenant"]


class UserBase(BaseModel):
    email: EmailStr
    role: Role

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip().lower()
        return v


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: Role = "tenant"

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip().lower()
        return v


class UserRead(UserBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip().lower()
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


# ----------------
# Messages (Sprint 9A)
# ----------------
class MessageRead(BaseModel):
    id: int
    property_id: int
    sender_id: int
    text: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageCreate(BaseModel):
    property_id: int
    text: str = Field(..., min_length=1, max_length=1000)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
        return v
