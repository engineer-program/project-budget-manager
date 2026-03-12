# Архитектура базы данных бюджетов

## Основные таблицы БД

* employees
* projects

* employee_salaries
* employee_bonuses

* expense_categories
* project_expenses

* income_categories
* project_incomes

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

| поле               | тип       |
| ------------------ | --------- |
| id                 | PK        |
| redmine_project_id | int       |
| name               | text      |
| name_1с            | text      |
| project_number     | text      |
| start_budget       | numeric   |
| created_at         | timestamp |

### Таблица employee_salaries

| поле         | тип       |
| ------------ | --------- |
| id           | PK        |
| employee_id  | FK        |
| year         | int       |
| month        | int       |
| base_salary  | numeric   |
| extra_salary | numeric   |
| created_at   | timestamp |

### Таблица employee_bonuses

| поле        | тип                 |
| ----------- | ------------------- |
| id          | PK                  |
| employee_id | FK                  |
| project_id  | FK                  |
| year        | int                 |
| month       | int                 |
| bonus       | numeric             |
| extra_bonus | numeric             |
| expense_id  | FK (источник денег) |

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

| поле                    | тип       |
| ----------------------- | --------- |
| id                      | PK        |
| project_id              | FK        |
| category_id             | FK        |
| amount                  | numeric   |
| responsible_employee_id | FK        |
| description             | text      |
| expense_date            | date      |
| created_at              | timestamp |

Возможно стоит добавить поле **edited_at** для отслеживания даты изменения статьи расхода при наличии функции корректировки статей расхода.

### Таблица income_categories

| поле | тип  |
| ---- | ---- |
| id   | PK   |
| name | text |

Например:

* Оплата клиента
* Дополнительные услуги
* Бонус заказчика

### Таблица project_incomes

| поле                    | тип       |
| ----------------------- | --------- |
| id                      | PK        |
| project_id              | FK        |
| category_id             | FK        |
| amount                  | numeric   |
| responsible_employee_id | FK        |
| income_date             | date      |
| description             | text      |
| created_at              | timestamp |

## ER схема БД

employees  
   │  
   ├──────────── employee_salaries  
   │  
   └──────────── employee_bonuses  
                       │  
                       |             expense_categories  
                       |                   |  
projects ──────────────┼──────────── project_expenses  
                       │  
                       └──────────── project_incomes  
                                           |  
                                     income_categories  

## Связи в БД

employees 1---N employee_salaries  
employees 1---N employee_bonuses

projects 1---N project_expenses  
projects 1---N project_incomes

expense_categories 1---N project_expenses  
income_categories 1---N project_incomes
