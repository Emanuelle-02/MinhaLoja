from django.contrib import admin
from .models import Categoria, Produto, Variacao, MovimentacaoEstoque, Venda, ItemVenda, Despesa

admin.site.register(Categoria)
admin.site.register(Produto)
admin.site.register(Variacao)
admin.site.register(MovimentacaoEstoque)
admin.site.register(Venda)
admin.site.register(ItemVenda)
admin.site.register(Despesa)