# Архитектура базы данных бюджетов

## Основные таблицы БД

* employees
* projects

* employee_salaries
* employee_bonuses

* expense_categories
* project_expenses

* project_incomes

* employee_compensations
* compensation_types

* redmine_time_entries

### Таблица employees

| поле       | тип  | описание      |
| ---------- | ---- | ------------- |
| id         | PK   | внутренний id |
| redmine_id | int  | id в Redmine  |
| first_name | text | имя           |
| last_name  | text | фамилия       |
| patronymic | text | отчество      |
| email      | text | email         |
| active     | bool | активен ли    |

Ограничения и индексы:

* UNIQUE(redmine_id)
* INDEX(email)
* INDEX(active)

### Таблица projects

| поле                 | тип                |
| -------------------- | ------------------ |
| id                   | PK                 |
| redmine_project_id   | int                |
| name                 | text               |
| name_1с              | text               |
| name_sanda           | text               |
| project_number       | text               |
| lead_department      | text               |
| project_manager_id   | FK -> employees.id |
| start_budget         | numeric(14,2)      |
| created_at           | timestamp          |
| updated_at           | timestamp          |
| budget_updated_by_id | FK -> auth_user.id |

Ограничения и индексы:

* UNIQUE(redmine_project_id)
* INDEX(project_number)
* INDEX(project_manager_id)

### Таблица employee_salaries

| поле         | тип                |
| ------------ | ------------------ |
| id           | PK                 |
| employee_id  | FK -> employees.id |
| year         | int                |
| month        | int                |
| base_salary  | numeric(14,2)      |
| extra_salary | numeric(14,2)      |
| created_at   | timestamp          |
| updated_at   | timestamp          |

Ограничения и индексы:

* UNIQUE(employee_id, year, month)
* INDEX(year, month)
* CHECK(month between 1 and 12)

### Таблица employee_bonuses

| поле          | тип                |
| ------------- | ------------------ |
| id            | PK                 |
| employee_id   | FK -> employees.id |
| year          | int                |
| month         | int                |
| bonus         | numeric(14,2)      |
| bonus_year    | int                |
| bonus_quarter | int                |
| extra_bonus   | numeric(14,2)      |
| created_at    | timestamp          |
| updated_at    | timestamp          |

Ограничения и индексы:

* UNIQUE(employee_id, bonus_year, bonus_quarter)
* INDEX(employee_id, year, month)
* CHECK(month between 1 and 12)
* CHECK(bonus_quarter between 1 and 4)

Принятая трактовка:

* year, month — месяц отражения премии в системе
* bonus_year, bonus_quarter — квартал, за который относится премия

### Таблица expense_categories

| поле        | тип       |
| ----------- | --------- |
| id          | PK        |
| name        | text      |
| description | text      |
| created_at  | timestamp |

Ограничения и индексы:

* UNIQUE(name)

Например:

* Премии
* Корпоратив
* Чай/кофе
* Мероприятия
* Прочие расходы

### Таблица project_expenses

| поле                    | тип                         |
| ----------------------- | --------------------------- |
| id                      | PK                          |
| project_id              | FK -> projects.id           |
| category_id             | FK -> expense_categories.id |
| amount                  | numeric(14,2)               |
| responsible_employee_id | FK -> employees.id          |
| description             | text                        |
| expense_date            | date                        |
| created_at              | timestamp                   |
| created_by_id           | FK -> auth_user.id          |

Ограничения и индексы:

* INDEX(project_id, expense_date)
* INDEX(category_id)
* INDEX(responsible_employee_id)
* INDEX(created_by_id)

### Таблица project_incomes

| поле                    | тип                |
| ----------------------- | ------------------ |
| id                      | PK                 |
| project_id              | FK -> projects.id  |
| amount                  | numeric(14,2)      |
| responsible_employee_id | FK -> employees.id |
| description             | text               |
| income_date             | date               |
| created_at              | timestamp          |
| created_by_id           | FK -> auth_user.id |

Ограничения и индексы:

* INDEX(project_id, income_date)
* INDEX(responsible_employee_id)
* INDEX(created_by_id)

### Таблица employee_compensations

| поле        | тип                         |
| ----------- | --------------------------- |
| id          | PK                          |
| employee_id | FK -> employees.id          |
| year        | int                         |
| month       | int                         |
| type_id     | FK -> compensation_types.id |
| amount      | numeric(14,2)               |
| created_at  | timestamp                   |
| updated_at  | timestamp                   |

Ограничения и индексы:

* UNIQUE(employee_id, year, month, type_id)
* INDEX(employee_id, year, month)
* CHECK(month between 1 and 12)

### Таблица compensation_types

| поле        | тип  |
| ----------- | ---- |
| id          | PK   |
| code        | text |
| name        | text |

Ограничения и индексы:

* UNIQUE(code)
* UNIQUE(name)

Заполненная таблица:

| id | code          | name         |
| -- | ------------- | ------------ |
| 1  | vacation      | Отпуск       |
| 2  | sick_leave    | Больничный   |
| 3  | business_trip | Командировка |

### Таблица redmine_time_entries

| поле                  | тип                |
| --------------------- | ------------------ |
| id                    | PK                 |
| project_id            | FK -> projects.id  |
| user_id               | FK -> employees.id |
| redmine_time_entry_id | int                |
| issue_id              | int                |
| hours                 | numeric(8,2)       |
| activity_id           | int                |
| spent_on              | date               |
| created_at            | timestamp          |

Ограничения и индексы:

* INDEX(project_id, spent_on)
* INDEX(user_id, spent_on)
* INDEX(issue_id)
* INDEX(activity_id)
* UNIQUE(redmine_time_entry_id)

Служебные таблицы:

* sync_state - состояние последней синхронизации по сущностям;
* sync_log - журнал запусков синхронизации;
* change_log - история изменений по финансовым сущностям.

## ER схема БД

employees  
   │  
   |             compensation_types
   |                   |
   ├──────────── employee_compensations
   |
   ├──────────── employee_salaries  
   │  
   └──────────── employee_bonuses  
                       │  
                       |             expense_categories  
                       |                   |  
projects ──────────────┼──────────── project_expenses  
                       │  
                       └──────────── project_incomes

## Связи в БД

employees 1---N employee_salaries  
employees 1---N employee_bonuses
employees 1---N employee_compensations

projects 1---N project_expenses  
projects 1---N project_incomes

expense_categories 1---N project_expenses
compensation_types 1---N employee_compensations
