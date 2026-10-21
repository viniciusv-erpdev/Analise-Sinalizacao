from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("signaling", "0007_multiple_problem_solutions")]
    operations = [
        migrations.AlterModelOptions(
            name="signalingpoint",
            options={"permissions": [
                ("generate_signaling_report", "Pode gerar relatórios de sinalização"),
            ]},
        ),
    ]
