from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable constraint names, so Alembic can drop and rename them later.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Load server-generated values (created_at, updated_at, server defaults) via RETURNING on
    # insert/update. Without this, reading them later triggers lazy IO, which async forbids.
    __mapper_args__ = {"eager_defaults": True}

    # sort_order puts id first and timestamps last in every table.
    id: Mapped[int] = mapped_column(primary_key=True, sort_order=-10)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), sort_order=10
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), sort_order=10
    )


def str_enum(enum_cls: type[StrEnum]) -> Enum:
    """Store a StrEnum as its plain string value (VARCHAR), validated in Python."""
    return Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
        length=20,
    )
