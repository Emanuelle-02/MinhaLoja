from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from .models import *
from django.db.models import Sum, F, Exists, OuterRef
from django.utils import timezone
from django.urls import reverse_lazy
from apps.loja.forms import AdminAccountForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import get_object_or_404, redirect, render
from .forms import ProdutoForm, VariacaoFormSet, VendaForm, ItemVendaFormSet, MovimentacaoEstoqueForm, DespesaForm, ItemCarrinhoForm, ConcluirVendaForm, TrocaForm
from django.contrib import messages
from .forms import VariacaoFormSet
from django.urls import reverse_lazy
import logging
from django.db import transaction
from decimal import Decimal
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

class Index(LoginRequiredMixin, View):
    def get(self, request):
        # Calcular entradas (vendas + movimentações de caixa do tipo ENTRADA para trocas)
        total_entradas_vendas = Venda.objects.filter(is_active=True).aggregate(total_entradas=Sum('valor_total'))['total_entradas'] or 0
        total_entradas_caixa = MovimentacaoCaixa.objects.filter(
            is_active=True,
            tipo='ENTRADA',
            descricao__startswith='Troca: diferença de preço recebida'
        ).aggregate(total_entradas=Sum('valor'))['total_entradas'] or 0
        total_entradas = total_entradas_vendas + total_entradas_caixa

        # Calcular saídas (despesas)
        total_saidas = Despesa.objects.filter(is_active=True).aggregate(total_saidas=Sum('valor'))['total_saidas'] or 0

        # Calcular saldo total
        saldo_total = total_entradas - total_saidas

        total_produtos = Variacao.objects.filter(produto__is_active=True).aggregate(total=Sum('quantidade'))['total'] or 0

        # Calcula lucro total (lucro_caixa) usando historico de custo
        lucro_caixa = ItemVenda.objects.filter(venda__is_active=True).aggregate(
            total_profit=Sum((F('preco_unitario') - F('preco_custo_historico')) * F('quantidade'))
        )['total_profit'] or 0

        logger.debug(f"Total Entradas (Venda): {total_entradas_vendas} (from {Venda.objects.filter(is_active=True).count()} records)")
        logger.debug(f"Total Entradas (MovimentacaoCaixa ENTRADA, troca): {total_entradas_caixa} (from {MovimentacaoCaixa.objects.filter(is_active=True, tipo='ENTRADA', descricao__startswith='Troca: diferença de preço recebida').count()} records)")
        logger.debug(f"Total Saídas (Despesa): {total_saidas} (from {Despesa.objects.filter(is_active=True).count()} records)")
        logger.debug(f"Saldo Total: {saldo_total}")
        logger.debug(f"Lucro Caixa (Profit): {lucro_caixa}")
        logger.debug(f"Total Produtos (Estoque): {total_produtos}")
        logger.debug("Sample Venda records:")
        for venda in Venda.objects.filter(is_active=True)[:5]:
            logger.debug(f"  Venda ID: {venda.id}, Valor Total: {venda.valor_total}, Data: {venda.data}")
        logger.debug("Sample MovimentacaoCaixa ENTRADA records (troca):")
        for movimentacao in MovimentacaoCaixa.objects.filter(is_active=True, tipo='ENTRADA', descricao__startswith='Troca: diferença de preço recebida')[:5]:
            logger.debug(f"  MovimentacaoCaixa ID: {movimentacao.id}, Valor: {movimentacao.valor}, Descrição: {movimentacao.descricao}, Data: {movimentacao.data}")
        logger.debug("Sample Despesa records:")
        for despesa in Despesa.objects.filter(is_active=True)[:5]:
            logger.debug(f"  Despesa ID: {despesa.id}, Valor: {despesa.valor}, Descrição: {despesa.descricao}, Data: {despesa.data}")

        context = {
            'total_produtos': total_produtos,
            'vendas_hoje': Venda.objects.filter(is_active=True, data__date=timezone.now().date()).count(),
            'estoque_baixo': Produto.objects.filter(is_active=True, variacao__quantidade__lt=F('estoque_minimo')).distinct().count(),
            'valor_vendas_mes': Venda.objects.filter(is_active=True, data__month=timezone.now().month).aggregate(total=Sum('valor_total'))['total'] or 0,
            'saldo_total': saldo_total,
            'lucro_caixa': lucro_caixa,
            'request': request,
        }
        return render(request, 'index.html', context)

class VendaDetailView(LoginRequiredMixin, DetailView):
    model = Venda
    template_name = 'caixa/venda_detalhes.html'
    context_object_name = 'venda'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['items'] = ItemVenda.objects.filter(venda=self.object)
        context['movimentacoes_caixa'] = MovimentacaoCaixa.objects.filter(venda=self.object)
        context['movimentacoes_estoque'] = MovimentacaoEstoque.objects.filter(
            motivo__contains=f"venda {self.object.id}"
        )
        # Calcula subtotal na view
        for item in context['items']:
            item.subtotal = item.quantidade * item.preco_unitario
        # Adiciona desconto to context
        context['desconto'] = self.object.desconto if hasattr(self.object, 'desconto') and self.object.desconto else 0
        return context
    
@login_required
@user_passes_test(lambda u: u.is_staff)
def edit_account(request):
    if request.method == 'POST':
        form = AdminAccountForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save(commit=False)
            password = form.cleaned_data.get("password")
            if password:
                user.set_password(password)
            user.save()
            # Mantém a sessão ativa após alteração de senha
            if password:
                update_session_auth_hash(request, user)
            return redirect('index')
    else:
        form = AdminAccountForm(instance=request.user)
    
    return render(request, 'edit_account.html', {'form': form})

##### VIEWS RELACIONADAS À LOJA   
class ProdutoListView(LoginRequiredMixin, ListView):
    model = Produto
    template_name = 'estoque/produto_list.html'
    context_object_name = 'produtos'
    paginate_by = 10
    def get_queryset(self):
        # Anota produtos com estoque total e bandeira de vendas
        return Produto.objects.filter(is_active=True).annotate(
            total_stock=Sum('variacao__quantidade'),
            has_sales_annotation=Exists(ItemVenda.objects.filter(variacao__produto=OuterRef('pk')))
        ).order_by('-id')
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Meus Produtos'
        return context

class ProdutoDetailView(LoginRequiredMixin, DetailView):
    model = Produto
    template_name = 'estoque/produto_detail.html'
    context_object_name = 'produto'
    queryset = Produto.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Detalhes do Produto {self.object.nome}'
        return context

class ProdutoCreateView(LoginRequiredMixin, CreateView):
    model = Produto
    form_class = ProdutoForm
    template_name = 'estoque/produto_form.html'
    success_url = reverse_lazy('produto_list')
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_form()
        preco_custo = form.data.get('preco_custo', '0') if self.request.POST else '0'
        logger.debug(f"ProdutoCreateView.get_context_data: preco_custo={preco_custo}")
        if self.request.POST:
            context['formset'] = VariacaoFormSet(self.request.POST, instance=self.object, form_kwargs={'preco_custo': preco_custo})
            logger.debug(f"POST data: {self.request.POST}")
        else:
            context['formset'] = VariacaoFormSet(instance=self.object, form_kwargs={'preco_custo': preco_custo})
        context['title'] = 'Adicionar Produto'
        return context
    def form_valid(self, form):
        logger.debug("Processing form_valid in ProdutoCreateView")
        with transaction.atomic():
            # Disconecta o sinal para evitar interferências
            post_save.disconnect(update_despesas_on_preco_custo_change, sender=Produto)
            try:
                self.object = form.save()
                formset = VariacaoFormSet(self.request.POST, instance=self.object, form_kwargs={'preco_custo': form.cleaned_data.get('preco_custo', 0)})
                logger.debug(f"Formset data: {self.request.POST}")
                if formset.is_valid():
                    logger.debug("Formset is valid, saving variations")
                    saved_variations = formset.save()
                    logger.debug(f"Saved {len(saved_variations)} variations")
                    for variation in saved_variations:
                        logger.debug(f"Saved variation: id={variation.id}, quantidade={variation.quantidade}")
                    messages.success(self.request, "Produto e variações salvos com sucesso!")
                else:
                    logger.error(f"Formset errors: {formset.errors}, non_form_errors: {formset.non_form_errors()}")
                    messages.error(self.request, f"Erro ao salvar variações: {formset.errors}")
                    self.object.delete()
                    return self.form_invalid(form)
            finally:
                post_save.connect(update_despesas_on_preco_custo_change, sender=Produto)
            return super().form_valid(form)

class ProdutoUpdateView(LoginRequiredMixin, UpdateView):
    model = Produto
    form_class = ProdutoForm
    template_name = 'estoque/produto_form.html'
    success_url = reverse_lazy('produto_list')
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        preco_custo = self.get_form().data.get('preco_custo', '0') if self.request.POST else str(self.object.preco_custo)
        if self.request.POST:
            context['formset'] = VariacaoFormSet(self.request.POST, instance=self.object, form_kwargs={'preco_custo': preco_custo})
        else:
            context['formset'] = VariacaoFormSet(instance=self.object, form_kwargs={'preco_custo': preco_custo})
        context['title'] = 'Editar Produto'
        return context
    def form_valid(self, form):
        logger.debug("Processing form_valid in ProdutoUpdateView")
        with transaction.atomic():
            post_save.disconnect(update_despesas_on_preco_custo_change, sender=Produto)
            try:
                context = self.get_context_data()
                formset = context['formset']
                if formset.is_valid():
                    self.object = form.save()
                    formset.instance = self.object
                    saved_variations = formset.save()
                    logger.debug(f"Saved {len(saved_variations)} variations")
                    for variation in saved_variations:
                        logger.debug(f"Saved variation: id={variation.id}, quantidade={variation.quantidade}")
                    messages.success(self.request, 'Produto atualizado com sucesso!')
                    return super().form_valid(form)
                else:
                    logger.error(f"Formset errors: {formset.errors}, non_form_errors: {formset.non_form_errors()}")
                    messages.error(self.request, f"Erro ao salvar variação: {formset.errors}")
                    return self.form_invalid(form)
            finally:
                post_save.connect(update_despesas_on_preco_custo_change, sender=Produto)
            
class ProdutoArchiveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        produto = get_object_or_404(Produto, pk=pk)
        produto.is_active = False
        produto.save()
        messages.success(request, 'Produto arquivado com sucesso!')
        return redirect('produto_list')

class VendaListView(LoginRequiredMixin, ListView):
    model = Venda
    template_name = 'caixa/venda_list.html'
    context_object_name = 'vendas'
    queryset = Venda.objects.filter(is_active=True).order_by('-data')  # Ordenada da mais recente para mais antiga
    paginate_by = 10 

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Minhas Vendas'
        return context

class VendaRegistrarView(LoginRequiredMixin, View):
    template_name = 'caixa/venda_registrar.html'

    def get(self, request):
        form = ItemCarrinhoForm()
        carrinho = request.session.get('carrinho', [])
        logger.debug(f"Carrinho na sessão: {carrinho}")
        return render(request, self.template_name, {
            'form': form,
            'carrinho': carrinho,
            'title': 'Registrar Venda - Adicionar Itens'
        })

    def post(self, request):
        if 'remove_item' in request.POST:
            index = int(request.POST['remove_item'])
            carrinho = request.session.get('carrinho', [])
            if 0 <= index < len(carrinho):
                del carrinho[index]
                request.session['carrinho'] = carrinho
                request.session.modified = True
                messages.success(request, 'Item removido do carrinho.')
            return redirect('venda_registrar')
        form = ItemCarrinhoForm(request.POST)
        carrinho = request.session.get('carrinho', [])
        if form.is_valid():
            variacao = form.cleaned_data['variacao']
            quantidade = form.cleaned_data['quantidade']
            if variacao.quantidade < quantidade:
                form.add_error('quantidade', f"Estoque insuficiente para {variacao}. Disponível: {variacao.quantidade}.")
                logger.error(f"Estoque insuficiente para variacao_id {variacao.id}: solicitado {quantidade}, disponível {variacao.quantidade}")
                return render(request, self.template_name, {
                    'form': form,
                    'carrinho': carrinho,
                    'title': 'Registrar Venda - Adicionar Itens'
                })
            item = {
                'produto_id': variacao.produto.id,
                'produto_nome': str(variacao.produto),
                'variacao_id': variacao.id,
                'variacao_nome': str(variacao),
                'quantidade': quantidade,
                'preco_unitario': str(variacao.produto.preco_venda)
            }
            carrinho.append(item)
            request.session['carrinho'] = carrinho
            request.session.modified = True
            logger.debug(f"Item adicionado ao carrinho: {item}")
            messages.success(request, 'Item adicionado ao carrinho!')
            return redirect('venda_registrar')
        logger.debug(f"Form errors: {form.errors}")
        return render(request, self.template_name, {
            'form': form,
            'carrinho': carrinho,
            'title': 'Registrar Venda - Adicionar Itens'
        })

class VendaConcluirView(LoginRequiredMixin, View):
    template_name = 'caixa/venda_concluir.html'

    def get(self, request):
        carrinho = request.session.get('carrinho', [])
        if not carrinho:
            messages.error(request, 'O carrinho está vazio. Adicione itens antes de concluir.')
            return redirect('venda_registrar')
        valor_total = sum(Decimal(str(item['quantidade'])) * Decimal(str(item['preco_unitario'])) for item in carrinho)
        form = ConcluirVendaForm(initial={'valor_total': valor_total}, valor_total=valor_total)
        logger.debug(f"Carrinho na conclusão: {carrinho}")
        return render(request, self.template_name, {
            'form': form,
            'carrinho': carrinho,
            'valor_total': valor_total,
            'title': 'Concluir Venda'
        })

    def post(self, request):
        if 'remove_item' in request.POST:
            index = int(request.POST['remove_item'])
            carrinho = request.session.get('carrinho', [])
            if 0 <= index < len(carrinho):
                del carrinho[index]
                request.session['carrinho'] = carrinho
                request.session.modified = True
                messages.success(request, 'Item removido do carrinho.')
            return redirect('venda_concluir')
        carrinho = request.session.get('carrinho', [])
        if not carrinho:
            messages.error(request, 'O carrinho está vazio. Adicione itens antes de concluir.')
            return redirect('venda_registrar')
        valor_total = sum(Decimal(str(item['quantidade'])) * Decimal(str(item['preco_unitario'])) for item in carrinho)
        form = ConcluirVendaForm(request.POST, valor_total=valor_total)
        if form.is_valid():
            with transaction.atomic():
                venda = form.save(commit=False)
                desconto = form.cleaned_data['desconto'] or 0
                venda.valor_total = valor_total - desconto
                venda.is_active = True
                if venda.valor_total < 0:
                    form.add_error('desconto', 'O desconto não pode resultar em um valor total negativo.')
                    logger.error("Valor total negativo após desconto")
                    return self.form_invalid(request, form, carrinho)
                if form.cleaned_data['forma_pagamento'] == 'DIN':
                    venda.valor_recebido = form.cleaned_data['valor_recebido']
                    venda.troco = form.cleaned_data['troco']  # Use troco do form
                venda.save()
                for item in carrinho:
                    variacao = Variacao.objects.select_for_update().get(id=item['variacao_id'])
                    if variacao.quantidade < int(item['quantidade']):
                        form.add_error(None, f"Estoque insuficiente para {item['variacao_nome']}.")
                        venda.delete()
                        logger.error(f"Estoque insuficiente para variacao_id {item['variacao_id']}: solicitado {item['quantidade']}, disponível {variacao.quantidade}")
                        return self.form_invalid(request, form, carrinho)
                    ItemVenda.objects.create(
                        venda=venda,
                        produto_id=item['produto_id'],
                        variacao_id=item['variacao_id'],
                        quantidade=int(item['quantidade']),
                        preco_unitario=Decimal(item['preco_unitario'])
                    )
                MovimentacaoCaixa.objects.create(
                    venda=venda,
                    tipo='ENTRADA',
                    valor=venda.valor_total,
                    descricao=f'Venda {venda.id}',
                    usuario=request.user,
                    is_active=True
                )
                request.session['carrinho'] = []
                request.session.modified = True
                messages.success(request, 'Venda registrada com sucesso!')
                return redirect('venda_list')
        logger.debug(f"Form errors: {form.errors}")
        return self.form_invalid(request, form, carrinho)

    def form_invalid(self, request, form, carrinho):
        valor_total = sum(Decimal(str(item['quantidade'])) * Decimal(str(item['preco_unitario'])) for item in carrinho)
        return render(request, self.template_name, {
            'form': form,
            'carrinho': carrinho,
            'valor_total': valor_total,
            'title': 'Concluir Venda'
        })

class VendaArchiveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        venda = get_object_or_404(Venda, pk=pk)
        venda.is_active = False
        venda.save()
        messages.success(request, 'Venda arquivada com sucesso!')
        return redirect('venda_list')

class MovimentacaoEstoqueListView(LoginRequiredMixin, ListView):
    model = MovimentacaoEstoque
    template_name = 'estoque/movimentacao_list.html'
    context_object_name = 'movimentacoes'
    queryset = MovimentacaoEstoque.objects.filter(is_active=True).order_by('-data')  # Mais recente ao mais antigo
    paginate_by = 10

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Movimentações de Estoque'
        return context

class MovimentacaoDetailView(LoginRequiredMixin, DetailView):
    model = MovimentacaoEstoque
    template_name = 'estoque/movimentacao_detail.html'
    context_object_name = 'movimentacao'
    queryset = MovimentacaoEstoque.objects.filter(is_active=True).order_by('-data')
    paginate_by = 10  # Pagination para movimentações relacionadas

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Detalhes da Movimentação {self.object.pk}'

        # Pega movimentações relacionadas (mesmo produto e variação, com exceção do atual)
        related_movements = MovimentacaoEstoque.objects.filter(
            Q(produto=self.object.produto) &
            Q(variacao=self.object.variacao) &
            Q(is_active=True)
        ).exclude(pk=self.object.pk).order_by('-data')

        # Paginação de movimentações relacionadas
        paginator = Paginator(related_movements, self.paginate_by)
        page = self.request.GET.get('related_page')
        try:
            related_movements_paginated = paginator.page(page)
        except PageNotAnInteger:
            related_movements_paginated = paginator.page(1)
        except EmptyPage:
            related_movements_paginated = paginator.page(paginator.num_pages)

        # Adiciona detalhes de movimentação financeira e quantidade do produto trocado (para trocas)
        movimentacao_caixa = None
        despesa = None
        quantidade_trocada = None
        if self.object.motivo == 'troca':
            # Procura por MovimentacaoCaixa associada (Diferença de preço recebida pelo lojista)
            movimentacao_caixa = MovimentacaoCaixa.objects.filter(
                descricao__contains=f'Movimentação {self.object.pk}',
                is_active=True
            ).first()
            # Procura por Despesa associada (diferença de preço paga ao cliente)
            despesa = Despesa.objects.filter(
                descricao=f'Troco por motivo de troca',
                variacao=self.object.produto_trocado,
                is_active=True,
                data__gte=self.object.data
            ).first()
             # Busca a quantidade do produto substituído
            if self.object.tipo == 'E' and self.object.produto_trocado:
                # Para entrada: busca movimentação de saída correspondente(produto_trocado)
                related_exit = MovimentacaoEstoque.objects.filter(
                    variacao=self.object.produto_trocado,
                    tipo='S',
                    motivo='troca',
                    is_active=True,
                    data__gte=self.object.data - timezone.timedelta(seconds=1),
                    data__lte=self.object.data + timezone.timedelta(seconds=1)
                ).first()
                quantidade_trocada = related_exit.quantidade if related_exit else None
            elif self.object.tipo == 'S':
                # Para saída: busca movimentação de entrada correspondente onde a variação é produto_trocado
                related_entry = MovimentacaoEstoque.objects.filter(
                    produto_trocado=self.object.variacao,
                    tipo='E',
                    motivo='troca',
                    is_active=True,
                    data__gte=self.object.data - timezone.timedelta(seconds=1),
                    data__lte=self.object.data + timezone.timedelta(seconds=1)
                ).first()
                quantidade_trocada = self.object.quantidade if related_entry else None
        elif self.object.motivo == 'compra':
            # Produra por Despesa associada para compra
            despesa = Despesa.objects.filter(
                variacao=self.object.variacao,
                is_active=True,
                data__gte=self.object.data - timezone.timedelta(seconds=1),
                data__lte=self.object.data + timezone.timedelta(seconds=1)
            ).first()
            
        context['related_movements'] = related_movements_paginated
        context['movimentacao_caixa'] = movimentacao_caixa
        context['despesa'] = despesa
        context['quantidade_trocada'] = quantidade_trocada
        return context

class MovimentacaoEstoqueCreateView(LoginRequiredMixin, CreateView):
    model = MovimentacaoEstoque
    form_class = MovimentacaoEstoqueForm
    template_name = 'estoque/movimentacao_form.html'
    success_url = reverse_lazy('movimentacao_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Registrar Entrada de Estoque'
        # Pré-preencher o formulário com dados da sessão, se existirem
        if 'movimentacao_data' in self.request.session:
            initial_data = self.request.session['movimentacao_data']
            context['form'] = MovimentacaoEstoqueForm(initial=initial_data)
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            if 'confirm' in request.POST:
                # Processar a confirmação e salvar
                # Limpar a sessão após confirmação bem-sucedida
                if 'movimentacao_data' in request.session:
                    del request.session['movimentacao_data']
                return self.form_valid(form)
            else:
                # Exibir página de confirmação e armazenar dados na sessão
                movimentacao = form.save(commit=False)
                variacao = form.cleaned_data['variacao']
                produto = variacao.produto
                preco_custo = form.cleaned_data.get('preco_custo') or produto.preco_custo
                preco_venda = form.cleaned_data.get('preco_venda') or produto.preco_venda
                request.session['movimentacao_data'] = {
                    'variacao': variacao.id,
                    'quantidade': form.cleaned_data['quantidade'],
                    'motivo': form.cleaned_data['motivo'],
                    'preco_custo': str(preco_custo),  # Converter Decimal para string
                    'preco_venda': str(preco_venda)  # Converter Decimal para string
                }
                return render(request, 'estoque/movimentacao_confirm.html', {
                    'movimentacao': movimentacao,
                    'preco_custo': preco_custo,
                    'preco_venda': preco_venda,
                    'preco_custo_anterior': produto.preco_custo,
                    'preco_venda_anterior': produto.preco_venda,
                    'title': 'Confirmar Movimentação'
                })
        return self.form_invalid(form)

    def form_valid(self, form):
        self.object = form.save(commit=False)
        variacao = form.cleaned_data['variacao']
        produto = variacao.produto
        preco_custo = form.cleaned_data.get('preco_custo') or produto.preco_custo
        preco_venda = form.cleaned_data.get('preco_venda') or produto.preco_venda
        quantidade = form.cleaned_data['quantidade']
        self.object.tipo = 'E'  # Hardcode to Entrada

        # Depuração detalhada
        logger.debug(f"Form Data - Request POST Quantidade: {self.request.POST.get('quantidade')}")
        logger.debug(f"Form Data - Variacao ID: {variacao.pk}, Produto: {produto.nome}, Preco Custo: {preco_custo}, Quantidade: {quantidade}")
        logger.debug(f"Current Stock - Variacao ID: {variacao.pk}, Quantidade Atual: {variacao.quantidade}")

        # Update Variacao.quantidade
        initial_stock = variacao.quantidade
        Variacao.objects.filter(pk=variacao.pk).update(quantidade=F('quantidade') + quantidade)
        variacao.refresh_from_db()
        logger.debug(f"After Update - Variacao ID: {variacao.pk}, Novo Estoque: {variacao.quantidade}, Esperado: {initial_stock + quantidade}")

        # Atualiza preco_custo e preco_venda no Produto com atributo temporário
        if preco_custo != produto.preco_custo:
            produto.preco_custo = preco_custo
            produto._is_from_view = True  # Define o atributo temporário
            produto.save()  # Sem argumentos extras
        if preco_venda != produto.preco_venda:
            produto.preco_venda = preco_venda
            produto._is_from_view = True  # Define o atributo temporário
            produto.save()  # Sem argumentos extras

        # Cria a nova despesa para as unidades adicionadas
        despesa_value = preco_custo * quantidade
        despesa_description = f"Compra adicional de {quantidade} unidades de {produto.nome} ({variacao.tamanho or '-'}/{variacao.cor or '-'})"
        logger.debug(f"Despesa Calculada - Preco Custo: {preco_custo}, Quantidade: {quantidade}, Valor: {despesa_value}")
        Despesa.objects.create(
            valor=despesa_value,
            descricao=despesa_description,
            data=timezone.now(),
            variacao=variacao,
            is_manually_created=False
        )

        self.object.produto = produto
        self.object.preco_custo = preco_custo
        self.object.preco_venda = preco_venda
        self.object.save()
        messages.success(self.request, 'Entrada registrada com sucesso!')
        return super().form_valid(form)
    
class MovimentacaoEstoqueUpdateView(LoginRequiredMixin, UpdateView):
    model = MovimentacaoEstoque
    form_class = MovimentacaoEstoqueForm
    template_name = 'estoque/movimentacao_form.html'
    success_url = reverse_lazy('movimentacao_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Movimentação'
        return context

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Movimentação atualizada com sucesso!')
        return super().form_valid(form)

class MovimentacaoEstoqueArchiveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        movimentacao = get_object_or_404(MovimentacaoEstoque, pk=pk)
        movimentacao.is_active = False
        movimentacao.save()
        messages.success(request, 'Movimentação arquivada com sucesso!')
        return redirect('movimentacao_list')

class DespesaListView(LoginRequiredMixin, ListView):
    model = Despesa
    template_name = 'caixa/despesa_list.html'
    context_object_name = 'despesas'
    queryset = Despesa.objects.filter(is_active=True).order_by('-data') 
    paginate_by = 10 

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Despesas'
        return context

class DespesaCreateView(LoginRequiredMixin, CreateView):
    model = Despesa
    form_class = DespesaForm
    template_name = 'caixa/despesa_form.html'
    success_url = reverse_lazy('despesa_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Registrar Despesa'
        return context

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.is_manually_created = True  # Marca como criada manualmente
        self.object.save()
        messages.success(self.request, 'Despesa registrada com sucesso!')
        return super().form_valid(form)

class DespesaUpdateView(LoginRequiredMixin, UpdateView):
    model = Despesa
    form_class = DespesaForm
    template_name = 'caixa/despesa_form.html'
    success_url = reverse_lazy('despesa_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Editar Despesa'
        return context

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Despesa atualizada com sucesso!')
        return super().form_valid(form)

class DespesaArchiveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        despesa = get_object_or_404(Despesa, pk=pk)
        despesa.is_active = False
        despesa.save()
        messages.success(request, 'Despesa arquivada com sucesso!')
        return redirect('despesa_list')
    
class MovimentacaoTrocaCreateView(LoginRequiredMixin, View):
    template_name = 'estoque/movimentacao_troca_form.html'
    success_url = reverse_lazy('movimentacao_list')

    def get(self, request):
        initial_data = request.session.get('troca_data', {})
        form = TrocaForm(initial=initial_data)
        return render(request, self.template_name, {
            'form': form,
            'title': 'Registrar Troca de Estoque'
        })

    def post(self, request):
        if 'confirm' in request.POST:
            form = TrocaForm(request.session.get('troca_data', {}))
            if form.is_valid():
                return self.process_exchange(request, form)
            else:
                logger.error(f"Form validation failed on confirmation: {form.errors}")
                messages.error(request, 'Dados inválidos. Por favor, preencha o formulário novamente.')
                if 'troca_data' in request.session:
                    del request.session['troca_data']
                    request.session.modified = True
                return redirect('movimentacao_troca_create')

        form = TrocaForm(request.POST)
        if form.is_valid():
            variacao_trocada = form.cleaned_data['variacao_trocada']
            quantidade_trocada = form.cleaned_data['quantidade_trocada']
            variacao_substituta = form.cleaned_data['variacao_substituta']
            quantidade_substituta = form.cleaned_data['quantidade_substituta']
            diferenca_preco = form.cleaned_data['diferenca_preco']

            # Compute valor total e a diferença
            valor_trocado = variacao_trocada.produto.preco_venda * quantidade_trocada
            valor_substituto = variacao_substituta.produto.preco_venda * quantidade_substituta
            diferenca_preco_abs = abs(diferenca_preco)

            # Armazena dados do form data na sessão
            request.session['troca_data'] = {
                'variacao_trocada': str(variacao_trocada.id),
                'quantidade_trocada': quantidade_trocada,
                'variacao_substituta': str(variacao_substituta.id),
                'quantidade_substituta': quantidade_substituta,
                'motivo': 'troca'
            }
            request.session.modified = True
            logger.debug(f"Session troca_data stored: {request.session['troca_data']}")

            return render(request, 'estoque/movimentacao_troca_confirm.html', {
                'variacao_trocada': variacao_trocada,
                'quantidade_trocada': quantidade_trocada,
                'variacao_substituta': variacao_substituta,
                'quantidade_substituta': quantidade_substituta,
                'preco_venda_substituto': variacao_substituta.produto.preco_venda,
                'valor_trocado': valor_trocado,
                'valor_substituto': valor_substituto,
                'diferenca_preco': diferenca_preco,
                'diferenca_preco_abs': diferenca_preco_abs,
                'motivo': 'troca',
                'title': 'Confirmar Troca'
            })

        logger.debug(f"Form errors: {form.errors}")
        return render(request, self.template_name, {
            'form': form,
            'title': 'Registrar Troca de Estoque'
        })

    def process_exchange(self, request, form):
        with transaction.atomic():
            variacao_trocada = form.cleaned_data['variacao_trocada']
            quantidade_trocada = form.cleaned_data['quantidade_trocada']
            variacao_substituta = form.cleaned_data['variacao_substituta']
            quantidade_substituta = form.cleaned_data['quantidade_substituta']
            diferenca_preco = form.cleaned_data['diferenca_preco']

            variacao_substituta.refresh_from_db()
            if quantidade_substituta > variacao_substituta.quantidade:
                messages.error(request, f"Estoque insuficiente para {variacao_substituta}. Disponível: {variacao_substituta.quantidade}.")
                logger.error(f"Estoque insuficiente para variacao_id {variacao_substituta.id}: solicitado {quantidade_substituta}, disponível {variacao_substituta.quantidade}")
                if 'troca_data' in request.session:
                    del request.session['troca_data']
                    request.session.modified = True
                return redirect('movimentacao_troca_create')

            # Update stock
            Variacao.objects.filter(pk=variacao_trocada.pk).update(quantidade=F('quantidade') + quantidade_trocada)
            variacao_trocada.refresh_from_db()
            Variacao.objects.filter(pk=variacao_substituta.pk).update(quantidade=F('quantidade') - quantidade_substituta)
            variacao_substituta.refresh_from_db()

            # Registra movimentações de estoque
            movimentacao_entrada = MovimentacaoEstoque.objects.create(
                produto=variacao_trocada.produto,
                variacao=variacao_trocada,
                quantidade=quantidade_trocada,
                tipo='E',
                motivo='troca',
                produto_trocado=variacao_substituta,
                diferenca_preco=diferenca_preco
            )

            movimentacao_saida = MovimentacaoEstoque.objects.create(
                produto=variacao_substituta.produto,
                variacao=variacao_substituta,
                quantidade=quantidade_substituta,
                tipo='S',
                motivo='troca',
                produto_trocado=variacao_trocada,
                diferenca_preco=diferenca_preco
            )

            # Lida com movimentações financeiras
            if diferenca_preco > 0:
                # Cliente paga diferença: cria a MovimentacaoCaixa (Entrada)
                movimentacao_caixa = MovimentacaoCaixa.objects.create(
                    tipo='ENTRADA',
                    valor=diferenca_preco,
                    descricao=f'Troca: diferença de preço recebida (Movimentação {movimentacao_entrada.id})',
                    usuario=request.user,
                    data=timezone.now(),
                    is_active=True
                )
                logger.info(f"MovimentacaoCaixa created: ID {movimentacao_caixa.id}, valor {diferenca_preco}, descricao: {movimentacao_caixa.descricao}")
            elif diferenca_preco < 0:
                # Lojista paga diferença ao cliente: cria a Despesa
                despesa = Despesa.objects.create(
                    valor=abs(diferenca_preco),
                    descricao=f'Troco por motivo de troca',
                    variacao=variacao_substituta,
                    is_manually_created=True,
                    data=timezone.now()
                )
                logger.info(f"Despesa created: ID {despesa.id}, valor {abs(diferenca_preco)}, descricao: {despesa.descricao}")

            if 'troca_data' in request.session:
                del request.session['troca_data']
                request.session.modified = True

            messages.success(request, 'Troca registrada com sucesso!')
            return redirect(self.success_url)

        logger.error("Transaction failed")
        messages.error(request, 'Erro ao processar a troca. Tente novamente.')
        if 'troca_data' in request.session:
            del request.session['troca_data']
            request.session.modified = True
        return redirect('movimentacao_troca_create')