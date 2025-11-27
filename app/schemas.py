from pydantic import BaseModel, Field, ConfigDict, field_validator, EmailStr
from typing import Literal


class PropertyBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    price_cents: int = Field(..., ge=0)

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
