# Generated by Django 5.1.7 on 2025-07-27 13:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("loja", "0004_despesa_is_active_movimentacaoestoque_is_active_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="categoria",
            name="nome",
            field=models.CharField(
                choices=[
                    ("Feminino", "Feminino"),
                    ("Infantil", "Infantil"),
                    ("Masculino", "Masculino"),
                ],
                default="--Selecionar--",
                max_length=100,
            ),
        ),
    ]
