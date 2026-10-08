from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from signaling.intersection_problems import problem_solution_codes, validate_problem_solution


DEFAULT_SIGNALING_SEARCH_RADIUS_METERS = 50
MIN_SIGNALING_SEARCH_RADIUS_METERS = 10
MAX_SIGNALING_SEARCH_RADIUS_METERS = 300


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
    search_radius_meters = models.PositiveSmallIntegerField(
        default=DEFAULT_SIGNALING_SEARCH_RADIUS_METERS,
        validators=[
            MinValueValidator(MIN_SIGNALING_SEARCH_RADIUS_METERS),
            MaxValueValidator(MAX_SIGNALING_SEARCH_RADIUS_METERS),
        ],
    )
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


class SignalingPointProblem(models.Model):
    signaling_point = models.ForeignKey(
        SignalingPoint, on_delete=models.CASCADE, related_name="problems",
    )
    problem_code = models.CharField(
        max_length=2,
        choices=[(code, code) for code, _ in problem_solution_codes()],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["problem_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["signaling_point", "problem_code"],
                name="unique_problem_per_signaling_point",
            ),
            models.CheckConstraint(
                condition=models.Q(problem_code__in=[code for code, _ in problem_solution_codes()]),
                name="valid_signaling_problem_code",
            ),
        ]

    def __str__(self) -> str:
        return f"Ponto {self.signaling_point_id}: {self.problem_code}"


class SignalingPointProblemSolution(models.Model):
    problem = models.ForeignKey(
        SignalingPointProblem, on_delete=models.CASCADE, related_name="solutions",
    )
    solution_code = models.CharField(
        max_length=3,
        choices=[
            (solution, solution)
            for _, solutions in problem_solution_codes()
            for solution in solutions
        ],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["solution_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["problem", "solution_code"], name="unique_solution_per_point_problem",
            ),
            models.CheckConstraint(
                condition=models.Q(solution_code__in=[
                    solution for _, solutions in problem_solution_codes() for solution in solutions
                ]),
                name="valid_point_problem_solution_code",
            ),
        ]

    def clean(self):
        super().clean()
        if self.problem_id:
            validate_problem_solution(self.problem.problem_code, self.solution_code)

    def __str__(self) -> str:
        return f"{self.problem_id}: {self.solution_code}"
