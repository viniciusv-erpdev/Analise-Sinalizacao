"""Synthetic local PDF PoC. No ORM writes, HTTP, sessions or reservations."""
import argparse
from datetime import date
from io import BytesIO
import os
from pathlib import Path
from types import SimpleNamespace


def build_sample_docx():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from PIL import Image, ImageDraw
    from signaling.models import SignalingPoint
    from signaling.report_generator import generate_signaling_report
    point = SignalingPoint(id=0, latitude=0, longitude=0, status="INCOMPLETE", search_radius_meters=100)
    author = SimpleNamespace(is_authenticated=True,
        get_full_name=lambda: "Autor sintético da PoC", get_username=lambda: "poc-sintetica")
    accidents = [{"id": f"SINTETICO-{i:02d}", "date": "01/10/2026", "accident_type": "Colisão",
        "record_type": "SINISTRO NAO FATAL", "street": "Via fictícia — sem endereço real",
        "distance_meters": i, "modes": [{"name":"Automóvel", "quantity":2}]} for i in range(1,31)]
    survey = {"radius_meters":100, "status":{"label":"Incompleta"}, "total_accidents":30,
        "summary":{"fatal":0,"non_fatal":30,"by_type":{"Colisão":30}}, "accidents":accidents,
        "filters":{"period":"Outubro de 2026", "categories":"Colisão", "gravity":"Não fatais"},
        "interventions":[{"type":"R1", "type_label":"R-1", "condition_label":"Ausente",
                          "notes":"Exemplo sintético de implantação e visibilidade."}],
        "problems":[{"problem_text":"Problema sintético de travessia", "solutions":[{"text":"Solução ilustrativa"}]}]}
    photos = []
    for index, color in enumerate(("#e0efff", "#ffe0cc", "#e0ffe0"),1):
        image = Image.new("RGB", (640,360), color)
        ImageDraw.Draw(image).text((25,25), f"POC - IMAGEM SINTETICA {index}", fill="black")
        stream = BytesIO()
        image.save(stream, format="PNG")
        stream.seek(0)
        photos.append(stream)
    return generate_signaling_report(point, survey, {
        "inspection_address":"Local inteiramente fictício — PoC",
        "inspection_date":date(2026,10,27), "occurrence_date":date(2026,10,1),
        "inspector_name":"Vistoriador sintético", "study_reason":"Validar conversão, sem dados reais.",
        "study_objective":"Conferir tabelas, gráficos, fotos, cabeçalho, rodapé e paginação.",
        "functional_classification":"Via fictícia", "geometric_configuration":"Cruzamento sintético",
        "regulated_speed":"40 km/h", "pgts":["Escola fictícia", "Unidade de saúde fictícia"],
        "technical_analysis":"Análise técnica sintética: avaliação da sinalização e segurança viária.\n"
            "Considerações finais: validar acentuação — ç, ã, é — e quebras de página.\n"
            "Este documento é somente um exemplo de teste.",
    }, photos, author=author).getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--libreoffice", help="Absolute path from trusted administrative configuration")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--output-dir", type=Path,
        help="Optional local synthetic artifacts for inspection; exclusive new directory")
    args = parser.parse_args()
    from signaling.pdf_conversion import ConversionOptions, PDFConversionError, convert_docx_to_pdf, validate_pdf
    original = build_sample_docx()
    if args.output_dir:
        # Exclusive creation: never overwrite existing files or touch a real document.
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "synthetic-report.docx").write_bytes(original)
    try:
        converted = convert_docx_to_pdf(original, options=ConversionOptions(
            executable=args.libreoffice, timeout_seconds=args.timeout))
    except PDFConversionError as error:
        print(f"PoC nao aprovada: {error.code}; exit_code={error.returncode}")
        return 2
    validate_pdf(converted)
    if args.output_dir:
        (args.output_dir / "synthetic-report.pdf").write_bytes(converted)
    print(f"Conversao real concluida: {len(converted)} bytes. Validacao visual ainda obrigatoria.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
