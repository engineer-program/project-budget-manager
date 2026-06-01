from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

import MySQLdb
from django.conf import settings


class RedmineReader:
    connection_alias = "redmine"

    def fetch_employees(self) -> list[dict[str, Any]]:
        query = """
        SELECT
            u.id AS redmine_id,
            u.firstname AS first_name,
            u.lastname AS last_name,
            cv_patr.value AS patronymic,
            cv_pos.value AS position,
            COALESCE(ea.address, '') AS email,
            (u.status = 1) AS active
        FROM users u

        LEFT JOIN email_addresses ea
            ON ea.user_id = u.id
           AND ea.is_default = 1

        LEFT JOIN custom_fields cf_patr
            ON cf_patr.type = 'UserCustomField'
        AND cf_patr.name = 'Отчество'

        LEFT JOIN custom_values cv_patr
            ON cv_patr.custom_field_id = cf_patr.id
        AND cv_patr.customized_id = u.id
        AND cv_patr.customized_type = 'Principal'

        LEFT JOIN custom_fields cf_pos
            ON cf_pos.type = 'UserCustomField'
        AND cf_pos.name = 'Должность'

        LEFT JOIN custom_values cv_pos
            ON cv_pos.custom_field_id = cf_pos.id
        AND cv_pos.customized_id = u.id
        AND cv_pos.customized_type = 'Principal'

        WHERE u.type = 'User'

        ORDER BY u.lastname
        """
        return self._fetch_all(query)

    def fetch_projects(self) -> list[dict[str, Any]]:
        query = """
        SELECT
            p.id AS redmine_project_id,
            p.name,
            cv_number.value AS project_number,
            p.parent_id AS parent_redmine_project_id,
            p.created_on AS redmine_created_on,
            p.updated_on AS redmine_updated_on,
            cv_1s.value AS name_1s,
            cv_sanda.value AS name_sanda,
            cv_dep.value AS lead_department,
            cv_manag.value AS redmine_project_manager_id
        FROM projects p

        LEFT JOIN custom_fields cf_number
            ON cf_number.type = 'ProjectCustomField'
           AND cf_number.name = 'Номер проекта'

        LEFT JOIN custom_values cv_number
            ON cv_number.custom_field_id = cf_number.id
           AND cv_number.customized_id = p.id
           AND cv_number.customized_type = 'Project'

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

        WHERE p.status IN (1, 5, 9, 15)
          AND COALESCE(p.easy_is_easy_template, 0) = 0
        """
        return self._fetch_all(query)

    def fetch_groups(self) -> list[dict[str, Any]]:
        query = """
        SELECT
            u.id AS redmine_group_id,
            u.lastname AS name,
            (u.status = 1) AS active
        FROM users u
        WHERE u.type = 'Group'
        ORDER BY u.lastname
        """
        return self._fetch_all(query)

    def fetch_group_memberships(self) -> list[dict[str, Any]]:
        query = """
        SELECT
            gu.group_id AS redmine_group_id,
            gu.user_id AS redmine_user_id
        FROM groups_users gu
        INNER JOIN users g
            ON g.id = gu.group_id
           AND g.type = 'Group'
        INNER JOIN users u
            ON u.id = gu.user_id
           AND u.type = 'User'
        """
        return self._fetch_all(query)

    def fetch_time_entries_chunk(
        self,
        *,
        after_id: int | None = None,
        changed_since: datetime | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        where_clauses: list[str] = []
        params: list[Any] = []

        if changed_since is not None:
            where_clauses.append("(te.created_on >= %s OR te.updated_on >= %s)")
            params.extend([changed_since, changed_since])
        if after_id is not None:
            where_clauses.append("te.id > %s")
            params.append(after_id)

        query = """
        SELECT
            te.id AS redmine_time_entry_id,
            te.project_id AS redmine_project_id,
            te.user_id AS redmine_user_id,
            te.issue_id,
            te.hours,
            te.activity_id,
            te.spent_on,
            te.created_on AS created_at,
            te.updated_on AS updated_at
        FROM time_entries te
        """

        if where_clauses:
            query += "\nWHERE " + " AND ".join(where_clauses)

        query += """
        ORDER BY te.id
        LIMIT %s
        """
        params.append(limit)
        return self._fetch_all(query, params)

    def _fetch_all(
        self,
        query: str,
        params: Iterable[Any] | None = None,
    ) -> list[dict[str, Any]]:
        connection_settings = settings.DATABASES[self.connection_alias]
        connection = MySQLdb.connect(
            host=connection_settings["HOST"],
            port=int(connection_settings["PORT"] or 3306),
            user=connection_settings["USER"],
            passwd=connection_settings["PASSWORD"],
            db=connection_settings["NAME"],
            charset=connection_settings.get("OPTIONS", {}).get("charset", "utf8mb4"),
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, params or [])
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
        finally:
            connection.close()
