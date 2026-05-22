from datetime import date

from django import forms


MONTH_CHOICES = [
    (1, "Январь"),
    (2, "Февраль"),
    (3, "Март"),
    (4, "Апрель"),
    (5, "Май"),
    (6, "Июнь"),
    (7, "Июль"),
    (8, "Август"),
    (9, "Сентябрь"),
    (10, "Октябрь"),
    (11, "Ноябрь"),
    (12, "Декабрь"),
]

YEAR_CHOICES = [(year, str(year)) for year in range(2019, 2051)]


class EmployeeSalaryPeriodForm(forms.Form):
    month = forms.ChoiceField(choices=MONTH_CHOICES, label="Месяц")
    year = forms.ChoiceField(choices=YEAR_CHOICES, label="Год")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = date.today()
        self.fields["month"].initial = today.month
        self.fields["year"].initial = today.year

    def clean_month(self) -> int:
        return int(self.cleaned_data["month"])

    def clean_year(self) -> int:
        return int(self.cleaned_data["year"])
