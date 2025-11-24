"""Generated migration to add observacao field to Pedido."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pedidos", "0002_pedido_finalizado_em"),
    ]

    operations = [
        migrations.AddField(
            model_name="pedido",
            name="observacao",
            field=models.TextField(blank=True, null=True),
        ),
    ]
