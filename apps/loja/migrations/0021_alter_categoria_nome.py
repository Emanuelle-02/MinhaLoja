# Generated by Django 5.1.7 on 2025-07-28 16:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loja", "0020_alter_categoria_nome_movimentacaocaixa"),
    ]

    operations = [
        migrations.AlterField(
            model_name="categoria",
            name="nome",
            field=models.CharField(
                choices=[
                    ("Feminino", "Feminino"),
                    ("Masculino", "Masculino"),
                    ("Infantil", "Infantil"),
                ],
                default="--Selecionar--",
                max_length=100,
            ),
        ),
    ]
