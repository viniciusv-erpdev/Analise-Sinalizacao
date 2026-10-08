from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Prefetch

from signaling.intersection_problems import get_problem, validate_problem_solutions
from signaling.models import SignalingIntervention, SignalingPoint, SignalingPointProblem, SignalingPointProblemSolution


def get_signaling_map_data() -> list[dict[str, object]]:
    return [
        {
            "id": point.id,
            "latitude": float(point.latitude),
            "longitude": float(point.longitude),
            "status": point.status,
            "search_radius_meters": point.search_radius_meters,
            "interventions": [
                {
                    "id": intervention.id,
                    "type": intervention.type,
                    "condition": intervention.condition,
                    "notes": intervention.notes,
                }
                for intervention in point.interventions.all()
            ],
        }
        for point in SignalingPoint.objects.only(
            "id", "latitude", "longitude", "status", "search_radius_meters"
        ).prefetch_related(
            Prefetch(
                "interventions",
                queryset=SignalingIntervention.objects.only(
                    "id", "signaling_point_id", "type", "condition", "notes"
                ).order_by("id"),
            )
        ).order_by("id")
    ]


def serialize_point_problem(problem: SignalingPointProblem) -> dict[str, object]:
    definition = get_problem(problem.problem_code)
    selected = {solution.solution_code for solution in problem.solutions.all()}
    return {
        "id": problem.pk,
        "problem_code": problem.problem_code,
        "problem_text": definition.text,
        "solutions": [
            {"code": code, "text": text}
            for code, text in definition.solutions if code in selected
        ],
    }


def create_point_problem(
    point: SignalingPoint, problem_code: object, solution_codes: object,
) -> SignalingPointProblem:
    validate_problem_solutions(problem_code, solution_codes)
    problem = SignalingPointProblem(
        signaling_point=point, problem_code=problem_code,
    )
    problem.full_clean(validate_constraints=False)
    try:
        # A savepoint keeps the connection usable after a concurrent duplicate.
        with transaction.atomic():
            problem.save(force_insert=True)
            _create_problem_solutions(problem, solution_codes)
    except IntegrityError:
        if point.problems.filter(problem_code=problem_code).exists():
            raise ValidationError({
                "problem_code": "Este problema já está cadastrado neste waypoint.",
            }) from None
        raise
    return problem


def _create_problem_solutions(problem, solution_codes):
    SignalingPointProblemSolution.objects.bulk_create([
        SignalingPointProblemSolution(problem=problem, solution_code=code)
        for code in solution_codes
    ])


def update_point_problem_solutions(
    problem: SignalingPointProblem, solution_codes: object,
) -> SignalingPointProblem:
    with transaction.atomic():
        # Serialize concurrent replacements on databases supporting row locks.
        problem = SignalingPointProblem.objects.select_for_update().get(pk=problem.pk)
        validate_problem_solutions(problem.problem_code, solution_codes)
        problem.solutions.all().delete()
        _create_problem_solutions(problem, solution_codes)
        problem.save(update_fields=["updated_at"])
    return problem
