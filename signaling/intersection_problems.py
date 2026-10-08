"""Catálogo oficial de problemas e soluções; os registros persistem apenas códigos."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class IntersectionProblem:
    code: str
    text: str
    solutions: tuple[tuple[str, str], ...]


_PROBLEMS = (
    IntersectionProblem(
        "P1",
        "O condutor não enxerga as brechas e transpõe a intersecção em condições impróprias.",
        (
            ("P1A", "Remoção de interferências visuais."),
            ("P1B", "Avanço do alinhamento da via perpendicular por meio de construção de avanço de calçada e implantação de linha de retenção ou de continuidade do alinhamento."),
        ),
    ),
    IntersectionProblem(
        "P2",
        "Não há brechas para transposição.",
        (
            ("P2A", "Implantação de rotatória ou mini rotatória."),
            ("P2B", "Implantação de sinalização semafórica."),
        ),
    ),
    IntersectionProblem(
        "P3",
        "As velocidades de aproximação são elevadas ou há dificuldade para avaliar a velocidade de aproximação de veículos da transversal.",
        (
            ("P3A", "Implantação de sinalização de regulamentação de velocidade."),
            ("P3B", "Implantação de fiscalização de velocidade."),
            ("P3C", "Implantação de redutores de velocidade."),
            ("P3D", "Implantação de sinalização semafórica."),
        ),
    ),
    IntersectionProblem(
        "P4",
        "As normas de preferência de passagem não são respeitadas.",
        (
            ("P4A", "Definição da preferencial por meio de sinal R-1 – Parada Obrigatória ou R-2 – Dê a Preferência."),
            ("P4B", "Redefinição da via preferencial – inversão da sinalização de preferência de passagem."),
            ("P4C", "Implantação de sinalização semafórica de advertência."),
            ("P4D", "Implantação de rotatória ou mini rotatória."),
            ("P4E", "Implantação de sinalização semafórica de regulamentação."),
        ),
    ),
    IntersectionProblem(
        "P5",
        "Muitos movimentos conflitantes.",
        (
            ("P5A", "Proibição de movimentos por meio de sinalização."),
            ("P5B", "Implantação de rotatória ou mini rotatória."),
            ("P5C", "Alteração de circulação."),
            ("P5D", "Implantação de sinalização semafórica (pares de vias com mão única de circulação, em sentidos opostos)."),
        ),
    ),
)


def get_problem(code: object) -> IntersectionProblem | None:
    return next((problem for problem in _PROBLEMS if problem.code == code), None)


def get_problem_solutions(code: object) -> tuple[tuple[str, str], ...]:
    problem = get_problem(code)
    return problem.solutions if problem else ()


def problem_solution_codes() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (problem.code, tuple(code for code, _ in problem.solutions))
        for problem in _PROBLEMS
    )


def is_valid_problem_solution(problem_code: object, solution_code: object) -> bool:
    return (
        isinstance(problem_code, str)
        and isinstance(solution_code, str)
        and any(code == solution_code for code, _ in get_problem_solutions(problem_code))
    )


def validate_problem_solution(problem_code: object, solution_code: object) -> None:
    if not isinstance(problem_code, str) or get_problem(problem_code) is None:
        raise ValidationError({"problem_code": "Selecione um problema válido."})
    if not is_valid_problem_solution(problem_code, solution_code):
        raise ValidationError({
            "solution_code": "Selecione uma solução pertencente ao problema informado.",
        })


def serialize_problem_catalog() -> list[dict[str, object]]:
    return [
        {
            "code": problem.code,
            "text": problem.text,
            "solutions": [
                {"code": code, "text": text} for code, text in problem.solutions
            ],
        }
        for problem in _PROBLEMS
    ]


def validate_problem_solutions(problem_code: object, solution_codes: object) -> None:
    if not isinstance(problem_code, str) or get_problem(problem_code) is None:
        raise ValidationError({"problem_code": "Selecione um problema válido."})
    if not isinstance(solution_codes, list) or not solution_codes:
        raise ValidationError({"solution_codes": "Selecione pelo menos uma solução."})
    if any(not is_valid_problem_solution(problem_code, code) for code in solution_codes):
        raise ValidationError({"solution_codes": "Todas as soluções devem pertencer ao problema."})
    if len(set(solution_codes)) != len(solution_codes):
        raise ValidationError({"solution_codes": "Não repita soluções."})
