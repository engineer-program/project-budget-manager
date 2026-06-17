from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db import models

from .models import ChangeLog


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def serialize_instance(instance: models.Model, fields: list[str] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    allowed_fields = set(fields) if fields else None

    for field in instance._meta.concrete_fields:
        field_name = field.attname
        if allowed_fields is not None and field_name not in allowed_fields and field.name not in allowed_fields:
            continue
        data[field_name] = _json_value(getattr(instance, field_name))

    return data


def log_change(
    *,
    user,
    entity: models.Model,
    action: str,
    before_data: dict[str, Any] | None = None,
    after_data: dict[str, Any] | None = None,
) -> None:
    if before_data == after_data:
        return

    ChangeLog.objects.create(
        entity_name=entity._meta.label,
        entity_id=entity.pk,
        action=action,
        changed_by=user if getattr(user, "is_authenticated", False) else None,
        before_data=before_data,
        after_data=after_data,
    )
