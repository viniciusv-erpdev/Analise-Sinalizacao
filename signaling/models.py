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
        PEDESTRIAN_CROSSING = "PEDESTRIAN_CROSSING", "Travessia segura"
        MINI_ROUNDABOUT = "MINI_ROUNDABOUT", "Minirrotatória"
        RIGHT_OF_WAY_REVERSAL = (
            "RIGHT_OF_WAY_REVERSAL",
            "Inversão de Pref. Passagem",
        )
        TRAFFIC_FLOW_CHANGE = "TRAFFIC_FLOW_CHANGE", "Alteração de circulação"
        PEDESTRIAN_REFUGE = "PEDESTRIAN_REFUGE", "Refúgios para pedestres"
        NO_PARKING = "NO_PARKING", "Proibido estacionar"
        GEOMETRY_ADJUSTMENT = "GEOMETRY_ADJUSTMENT", "Adequação na geometria"
        SPEED_REDUCTION = "SPEED_REDUCTION", "Redução de velocidade"
        VERTICAL_HORIZONTAL_SIGNALING = (
            "VERTICAL_HORIZONTAL_SIGNALING",
            "Sinalizações verticais e horizontais",
        )
        LOW_VISIBILITY = "LOW_VISIBILITY", "Visibilidade prejudicada"
        R1 = "R1", "R-1"
        STREET_LIGHTING = "STREET_LIGHTING", "Iluminação"
        SPEED_BUMP = "SPEED_BUMP", "Lombada"
        R5A = "R5A", "R-5a"
        R5B = "R5B", "R-5b"
        R4A = "R4A", "R-4a"
        R24A = "R24A", "R-24a"
        R6C = "R6C", "R-6c"
        R6A = "R6A", "R-6a"
        RAISED_CROSSWALK = "RAISED_CROSSWALK", "Faixa elevada"

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
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.get_type_display()} - {self.get_condition_display()}"
