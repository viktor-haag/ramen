from enum import StrEnum

from sqlalchemy import Enum


def str_enum(cls: type[StrEnum], name: str) -> Enum:
    """Enum stored as plain VARCHAR (values, not names), no CHECK constraint."""
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=False,
        values_callable=lambda e: [m.value for m in e],
        length=32,
    )
