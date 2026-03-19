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

### Таблица projects

| поле                 | тип           |
| -------------------- | ------------- |
| id                   | PK            |
| redmine_project_id   | int           |
| name                 | text          |
| name_1с              | text          |
| name_sanda           | text          |
| project_number       | text          |
| lead_department      | text          |
| project_manager_id   | FK            |
| start_budget         | numeric(14,2) |
| created_at           | timestamp     |
| updated_at           | timestamp     |
| budget_updated_by_id | FK            |

### Таблица employee_salaries

| поле         | тип           |
| ------------ | ------------- |
| id           | PK            |
| employee_id  | FK            |
| year         | int           |
| month        | int           |
| base_salary  | numeric(14,2) |
| extra_salary | numeric(14,2) |
| created_at   | timestamp     |
| updated_at   | timestamp     |

### Таблица employee_bonuses

| поле          | тип           |
| ------------- | ------------- |
| id            | PK            |
| employee_id   | FK            |
| year          | int           |
| month         | int           |
| bonus         | numeric(14,2) |
| bonus_year    | int           |
| bonus_quarter | int           |
| extra_bonus   | numeric(14,2) |
| created_at    | timestamp     |
| updated_at    | timestamp     |

### Таблица expense_categories

| поле        | тип       |
| ----------- | --------- |
| id          | PK        |
| name        | text      |
| description | text      |
| created_at  | timestamp |

Например:

* Премии
* Корпоратив
* Чай/кофе
* Мероприятия
* Прочие расходы

### Таблица project_expenses

| поле                    | тип           |
| ----------------------- | ------------- |
| id                      | PK            |
| project_id              | FK            |
| category_id             | FK            |
| amount                  | numeric(14,2) |
| responsible_employee_id | FK            |
| description             | text          |
| expense_date            | date          |
| created_at              | timestamp     |
| created_by_id           | FK            |

### Таблица project_incomes

| поле                    | тип           |
| ----------------------- | ------------- |
| id                      | PK            |
| project_id              | FK            |
| amount                  | numeric(14,2) |
| responsible_employee_id | FK            |
| description             | text          |
| income_date             | date          |
| created_at              | timestamp     |
| created_by_id           | FK            |

### Таблица employee_compensations

| поле        | тип           |
| ----------- | ------------- |
| id          | PK            |
| employee_id | FK            |
| year        | int           |
| month       | int           |
| type_id     | FK            |
| amount      | numeric(14,2) |
| created_at  | timestamp     |
| updated_at  | timestamp     |

### Таблица compensation_types

| поле        | тип  |
| ----------- | ---- |
| id          | PK   |
| code        | text |
| name        | text |

Заполненная таблица:

| id | code          | name         |
| -- | ------------- | ------------ |
| 1  | vacation      | Отпуск       |
| 2  | sick_leave    | Больничный   |
| 3  | business_trip | Командировка |

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
