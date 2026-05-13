from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db import connections


class RedmineReader:
    connection_alias = "redmine"

    def fetch_employees(self) -> list[dict[str, Any]]:
        query = """
        SELECT
            u.id AS redmine_id,
            u.firstname AS first_name,
            u.lastname AS last_name,
            cv.value AS patronymic,
            COALESCE(ea.address, '') AS email,
            (u.status = 1) AS active
        FROM users u

        LEFT JOIN email_addresses ea
            ON ea.user_id = u.id
           AND ea.is_default = 1

        LEFT JOIN custom_fields cf
            ON cf.type = 'UserCustomField'
           AND cf.name = 'Отчество'

        LEFT JOIN custom_values cv
            ON cv.custom_field_id = cf.id
           AND cv.customized_id = u.id
           AND cv.customized_type = 'Principal'

        WHERE u.type = 'User'

        ORDER BY u.lastname
        """
        return self._fetch_all(query)

    def fetch_projects(self) -> list[dict[str, Any]]:
        query = """
        SELECT
            p.id AS redmine_project_id,
            p.name,
            p.identifier AS project_number,
            p.parent_id AS parent_redmine_project_id,
            cv_1s.value AS name_1s,
            cv_sanda.value AS name_sanda,
            cv_dep.value AS lead_department,
            cv_manag.value AS redmine_project_manager_id
        FROM projects p

        LEFT JOIN custom_fields cf_1s
            ON cf_1s.type = 'ProjectCustomField'
           AND cf_1s.name = 'Наименование в 1С'

        LEFT JOIN custom_values cv_1s
            ON cv_1s.custom_field_id = cf_1s.id
           AND cv_1s.customized_id = p.id
           AND cv_1s.customized_type = 'Project'

        LEFT JOIN custom_fields cf_sanda
            ON cf_sanda.type = 'ProjectCustomField'
           AND cf_sanda.name = 'Наименование в Санде'

        LEFT JOIN custom_values cv_sanda
            ON cv_sanda.custom_field_id = cf_sanda.id
           AND cv_sanda.customized_id = p.id
           AND cv_sanda.customized_type = 'Project'

        LEFT JOIN custom_fields cf_dep
            ON cf_dep.type = 'ProjectCustomField'
           AND cf_dep.name = 'Ведущий отдел'

        LEFT JOIN custom_values cv_dep
            ON cv_dep.custom_field_id = cf_dep.id
           AND cv_dep.customized_id = p.id
           AND cv_dep.customized_type = 'Project'

        LEFT JOIN custom_fields cf_manag
            ON cf_manag.type = 'ProjectCustomField'
           AND cf_manag.name = 'Руководитель проекта'

        LEFT JOIN custom_values cv_manag
            ON cv_manag.custom_field_id = cf_manag.id
           AND cv_manag.customized_id = p.id
           AND cv_manag.customized_type = 'Project'

        WHERE p.status IN (1, 5)
        """
        return self._fetch_all(query)

    def fetch_time_entries(self) -> list[dict[str, Any]]:
        query = """
        SELECT
            te.id AS redmine_time_entry_id,
            te.project_id AS redmine_project_id,
            te.user_id AS redmine_user_id,
            te.issue_id,
            te.hours,
            te.activity_id,
            te.spent_on,
            te.created_on AS created_at
        FROM time_entries te
        """
        return self._fetch_all(query)

    def _fetch_all(
        self,
        query: str,
        params: Iterable[Any] | None = None,
    ) -> list[dict[str, Any]]:
        with connections[self.connection_alias].cursor() as cursor:
            cursor.execute(query, params or [])
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
