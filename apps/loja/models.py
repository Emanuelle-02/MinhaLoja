from django.db import models
from apps.accounts.models import User
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.timezone import now
import logging

logger = logging.getLogger(__name__)

GENDER_CHOICES = {
    ("Feminino", "Feminino"),
    ("Masculino", "Masculino"),
    ("Infantil", "Infantil"),
}

class Categoria(models.Model):
    nome = models.CharField(max_length=100, choices=GENDER_CHOICES, default="--Selecionar--")

    def __str__(self):
        return self.nome

class Produto(models.Model):
    nome = models.CharField(max_length=200)
    codigo = models.CharField(max_length=50, blank=True, null=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True)
    preco_custo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    preco_venda = models.DecimalField(max_digits=10, decimal_places=2)
    estoque_minimo = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    class Meta:
        verbose_name = 'Produto'
        verbose_name_plural = 'Produtos'
    def __str__(self):
        return f"{self.nome} ({self.categoria})"

    @property
    def has_sales(self):
        """Check if the product has been sold (has associated ItemVenda records)."""
        return ItemVenda.objects.filter(variacao__produto=self).exists()

class Variacao(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    tamanho = models.CharField(max_length=10, blank=True)
    cor = models.CharField(max_length=50, blank=True)
    quantidade = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.produto.nome} - {self.tamanho}/{self.cor}"

    def save(self, *args, **kwargs):
        logger.debug(f"Saving Variacao: produto={self.produto}, tamanho={self.tamanho}, cor={self.cor}, quantidade={self.quantidade}, pk={self.pk}")
        if hasattr(self, '_saving'):
            logger.warning("Recursion detected, exiting save.")
            return
        self._saving = True
        is_sale = kwargs.pop('is_sale', False)  # Flag para indicar if ativado por venda
        is_from_view = kwargs.pop('is_from_view', False)  # Nova flag para view

        try:
            old_quantidade = 0
            is_new = not self.pk
            if not is_new:
                try:
                    old_variacao = Variacao.objects.get(pk=self.pk)
                    old_quantidade = old_variacao.quantidade
                except Variacao.DoesNotExist:
                    logger.error(f"Variacao with pk={self.pk} does not exist.")
                    raise

            super().save(*args, **kwargs)
            diff = self.quantidade - old_quantidade

            # Cria movimento de estoque apenas se não for ativado por venda ou view
            if diff != 0 and not is_sale and not is_from_view:
                logger.debug(f"Updated variation: diff={diff}, creating MovimentacaoEstoque")
                MovimentacaoEstoque.objects.create(
                    produto=self.produto,
                    variacao=self,
                    quantidade=abs(diff),
                    tipo='E' if diff > 0 else 'S',
                    motivo=f"{'Entrada' if diff > 0 else 'Saída'} via atualização de variação"
                )

            # Despesa lógica apenas para mudanças non-sale, non-view
            if not is_sale and not is_from_view:
                despesa_description = f"Compra inicial de {self.quantidade} unidades de {self.produto.nome} ({self.tamanho}/{self.cor})"
                despesa_valor = self.produto.preco_custo * self.quantidade

                if is_new and self.quantidade > 0:
                    logger.debug(f"New variation: creating Despesa: {despesa_description}, Valor: {despesa_valor}")
                    Despesa.objects.create(
                        valor=despesa_valor,
                        descricao=despesa_description,
                        data=timezone.now(),
                        variacao=self
                    )
                elif not is_new and diff != 0:
                    despesas = Despesa.objects.filter(
                        variacao=self,
                        descricao__startswith=f"Compra inicial de"
                    )
                    if diff > 0:
                        if despesas.exists():
                            despesa = despesas.first()
                            logger.debug(f"Updating Despesa: {despesa_description}, Old Valor: {despesa.valor}, New Valor: {despesa_valor}")
                            despesa.valor = despesa_valor
                            despesa.descricao = despesa_description
                            despesa.data = timezone.now()
                            despesa.save()
                        else:
                            logger.debug(f"No Despesa found for variacao {self.pk}, creating new: {despesa_description}, Valor: {despesa_valor}")
                            Despesa.objects.create(
                                valor=despesa_valor,
                                descricao=despesa_description,
                                data=timezone.now(),
                                variacao=self
                            )
                    elif diff < 0:
                        if despesas.exists():
                            despesa = despesas.first()
                            logger.debug(f"Updating Despesa for reduction: {despesa_description}, Old Valor: {despesa_valor}")
                            despesa.valor = despesa_valor
                            despesa.descricao = despesa_description
                            despesa.data = timezone.now()
                            despesa.save()
                        else:
                            logger.debug(f"No Despesa found for variacao {self.pk} to update for reduction")

        except Exception as e:
            logger.error(f"Error in Variacao.save: {str(e)}")
            raise
        finally:
            del self._saving

class MovimentacaoEstoque(models.Model):
    TIPO_MOV = (('E', 'Entrada'), ('S', 'Saída'))
    MOTIVO_CHOICES = (
        ('compra', 'Compra'),
        ('troca', 'Troca'),
        ('devolucao', 'Devolução'),
    )
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    variacao = models.ForeignKey(Variacao, on_delete=models.CASCADE, null=True)
    quantidade = models.PositiveIntegerField()
    tipo = models.CharField(max_length=1, choices=TIPO_MOV)
    data = models.DateTimeField(auto_now_add=True)
    motivo = models.CharField(max_length=100, choices=MOTIVO_CHOICES, default='compra')
    is_active = models.BooleanField(default=True)
    produto_trocado = models.ForeignKey(Variacao, on_delete=models.SET_NULL, null=True, blank=True, related_name='trocado_em')  # Novo campo
    diferenca_preco = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # Novo campo
    
    def __str__(self):
        return f"{self.get_tipo_display()} - {self.produto.nome} - {self.quantidade}"

    def save(self, *args, **kwargs):
        logger.debug(f"Saving MovimentacaoEstoque: produto={self.produto}, variacao={self.variacao}, quantidade={self.quantidade}, tipo={self.tipo}, pk={self.pk}")
        super().save(*args, **kwargs)

class Venda(models.Model):
    nome_cliente = models.CharField(max_length=255, blank=True, null=True)
    forma_pagamento = models.CharField(max_length=3, choices=[
        ('DIN', 'Dinheiro'),
        ('PIX', 'PIX'),
        ('CRE', 'Crédito'),
        ('DEB', 'Débito'),
    ])
    desconto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    valor_total = models.DecimalField(max_digits=10, decimal_places=2)
    valor_recebido = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    troco = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    data = models.DateTimeField(default=now)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Venda {self.id} - {self.nome_cliente or 'Anônimo'}"

class ItemVenda(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    variacao = models.ForeignKey(Variacao, on_delete=models.CASCADE, null=True)
    quantidade = models.PositiveIntegerField()
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)  # Preço de venda na época
    preco_custo_historico = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Custo na época

    def __str__(self):
        return f"{self.produto.nome} - {self.quantidade} unidades"

    def save(self, *args, **kwargs):
        if self.pk:  # Edição de item existente
            old_item = ItemVenda.objects.get(pk=self.pk)
            if old_item.variacao and old_item.quantidade != self.quantidade:
                old_item.variacao.quantidade += old_item.quantidade
                old_item.variacao.save(is_sale=False)  # Pass is_sale=False for reversions
                MovimentacaoEstoque.objects.create(
                    produto=old_item.produto,
                    variacao=old_item.variacao,
                    quantidade=old_item.quantidade,
                    tipo='E',
                    motivo=f"Reversão de venda {self.venda.id} (edição)"  
                )
        if self.variacao:  # Nova ou edição
            if not self.pk:  # Novo item
                self.preco_custo_historico = self.variacao.produto.preco_custo
            self.variacao.quantidade -= self.quantidade
            self.variacao.save(is_sale=True)  # Pass is_sale=True para vendas
            MovimentacaoEstoque.objects.create(
                produto=self.produto,
                variacao=self.variacao,
                quantidade=self.quantidade,
                tipo='S',
                motivo=f"Saída por venda"  
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.variacao:
            self.variacao.quantidade += self.quantidade
            self.variacao.save(is_sale=False)  # Pass is_sale=False for reversions
            MovimentacaoEstoque.objects.create(
                produto=self.produto,
                variacao=self.variacao,
                quantidade=self.quantidade,
                tipo='E',
                motivo=f"Reversão de venda {self.venda.id} (exclusão)"  
            )
        super().delete(*args, **kwargs)

class Despesa(models.Model):
    data = models.DateTimeField(auto_now_add=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    descricao = models.CharField(max_length=200)
    variacao = models.ForeignKey(Variacao, on_delete=models.SET_NULL, null=True, blank=True)
    is_manually_created = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Despesa de R${self.valor} - {self.descricao}"

receiver(post_save, sender=Produto)
def update_despesas_on_preco_custo_change(sender, instance, **kwargs):
    logger.debug(f"Produto.save triggered for produto={instance.nome}, preco_custo={instance.preco_custo}, created={kwargs.get('created', False)}")
    # Verifica se a mudança vem da view usando o atributo temporário
    if getattr(instance, '_is_from_view', False):
        logger.debug(f"Change from MovimentacaoEstoqueCreateView, skipping despesa update for {instance.nome}")
        return

    variacoes = Variacao.objects.filter(produto=instance)
    for variacao in variacoes:
        despesa_description = f"Compra inicial de {variacao.quantidade} unidades de {variacao.produto.nome} ({variacao.tamanho}/{variacao.cor})"
        despesa_valor = instance.preco_custo * variacao.quantidade
        despesas = Despesa.objects.filter(
            variacao=variacao,
            descricao__startswith="Compra inicial de"
        )
        if despesas.exists():
            despesa = despesas.first()
            logger.debug(f"Updating Despesa for variacao {variacao.pk}: {despesa_description}, New Valor: {despesa_valor}")
            despesa.valor = despesa_valor
            despesa.descricao = despesa_description
            despesa.data = timezone.now()
            despesa.save()
        else:
            logger.debug(f"No Despesa found for variacao {variacao.pk}, creating new: {despesa_description}, Valor: {despesa_valor}")
            Despesa.objects.create(
                valor=despesa_valor,
                descricao=despesa_description,
                data=timezone.now(),
                variacao=variacao
            )
            
class MovimentacaoCaixa(models.Model):
    TIPO_MOVIMENTACAO = [
        ('ENTRADA', 'Entrada'),
        ('SAIDA', 'Saída'),
    ]
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, null=True, blank=True)
    tipo = models.CharField(max_length=10, choices=TIPO_MOVIMENTACAO)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.DateTimeField(default=now)
    descricao = models.CharField(max_length=255, blank=True)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.tipo} - R${self.valor} ({self.data})"

    def save(self, *args, **kwargs):
        logger.debug(f"Saving MovimentacaoCaixa: venda={self.venda}, tipo={self.tipo}, valor={self.valor}, usuario={self.usuario}")
        super().save(*args, **kwargs)