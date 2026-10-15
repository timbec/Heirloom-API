from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field


def _blank_to_none(value: object) -> object:
    """Trim strings and turn empty ones into None, as Laravel's TrimStrings and
    ConvertEmptyStringsToNull middleware did. The frontend sends "" for blank fields."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


OptionalText = Annotated[str | None, BeforeValidator(_blank_to_none)]
# The length limit sits on the str branch so it isn't applied to None.
OptionalShortText = Annotated[
    Annotated[str, Field(max_length=255)] | None, BeforeValidator(_blank_to_none)
]
Stripped = BeforeValidator(_strip)


class ListResponse[T](BaseModel):
    """`{data: [...]}`, the envelope the frontend reads (Laravel's paginator used to add more)."""

    data: list[T]


class MessageResponse(BaseModel):
    message: str
