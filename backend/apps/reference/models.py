from django.db import models


class CompensationType(models.Model):
    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = "compensation_types"
        ordering = ["name"]

    def __str__(self):
        return self.name

