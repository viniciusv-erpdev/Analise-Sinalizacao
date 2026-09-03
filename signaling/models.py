from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class SignalingPoint(models.Model):
    class Status(models.TextChoices):
        OK = "OK", "Adequada"
        INCOMPLETE = "INCOMPLETE", "Incompleta"
        ABSENT = "ABSENT", "Ausente"

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    status = models.CharField(max_length=10, choices=Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Ponto {self.pk} ({self.latitude}, {self.longitude})"


class SignalingIntervention(models.Model):
    class Type(models.TextChoices):
        TRAFFIC_LIGHT = "TRAFFIC_LIGHT", "Semáforo"

    class Condition(models.TextChoices):
        OK = "OK", "Presente"
        ABSENT = "ABSENT", "Ausente"

    signaling_point = models.ForeignKey(
        SignalingPoint,
        on_delete=models.CASCADE,
        related_name="interventions",
    )
    type = models.CharField(max_length=30, choices=Type.choices)
    condition = models.CharField(max_length=6, choices=Condition.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["signaling_point", "type"],
                name="unique_intervention_type_per_signaling_point",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_type_display()} - {self.get_condition_display()}"
