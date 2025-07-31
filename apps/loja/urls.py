from django.contrib import admin
from django.urls import path
from apps.loja.views import *
from .views import *
from .api_views import *


urlpatterns = [
    #####   ATRIBUIÇÕES DO ADMINISTRADOR    #####
    path("index/", Index.as_view(), name="index"),
    path('edit_account/', edit_account, name='edit_account'),
     # Produtos
    path('produtos/', ProdutoListView.as_view(), name='produto_list'),
    path('produtos/adicionar/', ProdutoCreateView.as_view(), name='produto_create'),
    path('produtos/editar/<int:pk>/', ProdutoUpdateView.as_view(), name='produto_update'),
    path('produtos/arquivar/<int:pk>/', ProdutoArchiveView.as_view(), name='produto_archive'),
    path('produtos/<int:pk>/', ProdutoDetailView.as_view(), name='produto_detail'),
    # Vendas
    path('vendas/', VendaListView.as_view(), name='venda_list'),
    path('vendas/<int:pk>/detalhes/', VendaDetailView.as_view(), name='venda_detalhes'),
    path('vendas/arquivar/<int:pk>/', VendaArchiveView.as_view(), name='venda_archive'),
    path('vendas/registrar/', VendaRegistrarView.as_view(), name='venda_registrar'),
    path('vendas/concluir/', VendaConcluirView.as_view(), name='venda_concluir'),
    path('vendas/', VendaListView.as_view(), name='venda_list'),
    path('api/variacoes/<int:produto_id>/', VariacaoListView.as_view(), name='variacao_list_api'),
    # Movimentações de Estoque
    path('movimentacoes/', MovimentacaoEstoqueListView.as_view(), name='movimentacao_list'),
    path('movimentacoes/registrar/', MovimentacaoEstoqueCreateView.as_view(), name='movimentacao_create'),
    path('movimentacoes/editar/<int:pk>/', MovimentacaoEstoqueUpdateView.as_view(), name='movimentacao_update'),
    path('movimentacoes/arquivar/<int:pk>/', MovimentacaoEstoqueArchiveView.as_view(), name='movimentacao_archive'),
    path('movimentacao/<int:pk>/detail/', MovimentacaoDetailView.as_view(), name='movimentacao_detail'),
    path('movimentacoes/troca/', MovimentacaoTrocaCreateView.as_view(), name='movimentacao_troca_create'),
    # Despesas
    path('despesas/', DespesaListView.as_view(), name='despesa_list'),
    path('despesas/registrar/', DespesaCreateView.as_view(), name='despesa_create'),
    path('despesas/editar/<int:pk>/', DespesaUpdateView.as_view(), name='despesa_update'),
    path('despesas/arquivar/<int:pk>/', DespesaArchiveView.as_view(), name='despesa_archive'),
    
]