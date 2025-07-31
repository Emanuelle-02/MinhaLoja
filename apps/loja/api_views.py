# api_views.py
from django.http import JsonResponse
from .models import Variacao
from django.views import View
import logging

logger = logging.getLogger(__name__)

class VariacaoListView(View):
    def get(self, request, produto_id):
        logger.debug(f"Fetching variações for produto_id: {produto_id}")
        try:
            variacoes = Variacao.objects.filter(produto_id=produto_id, quantidade__gt=0).select_related('produto__categoria')
            data = [
                {
                    'id': variacao.id,
                    'tamanho': variacao.tamanho,
                    'cor': variacao.cor,
                    'quantidade': variacao.quantidade,
                    'produto_preco_venda': str(variacao.produto.preco_venda),
                    'produto_nome': variacao.produto.nome,
                    'categoria': variacao.produto.categoria.nome,
                }
                for variacao in variacoes
            ]
            logger.debug(f"Variações retornadas para produto_id {produto_id}: {data}")
            if not data:
                logger.warning(f"Nenhuma variação encontrada para produto_id {produto_id}")
            return JsonResponse(data, safe=False)
        except Exception as e:
            logger.error(f"Erro ao buscar variações para produto_id {produto_id}: {str(e)}")
            return JsonResponse({'error': 'Erro ao carregar variações'}, status=500)