from django import forms
from django.db import transaction
from apps.accounts.models import User
from django.core.exceptions import ValidationError
from django.utils.timezone import now
from django.forms import inlineformset_factory
from .models import Produto, Variacao, Categoria, Venda, ItemVenda, MovimentacaoEstoque, Despesa
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div
import logging
import json

logger = logging.getLogger(__name__)

# forms relacionados ao usuário
class AdminAccountForm(forms.ModelForm):
    password = forms.CharField(
        label="Nova senha",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text="Deixe em branco para não alterar a senha."
    )
    password_confirm = forms.CharField(
        label="Confirme a nova senha",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text="Repita a senha para confirmação."
    )

    def __init__(self, *args, **kwargs):
        super(AdminAccountForm, self).__init__(*args, **kwargs)
        # Personalizando o help_text do campo username
        self.fields['username'].help_text = (
        "<ul>"
        "<li>Deixe inalterado caso não queira mudar o nome de usuário. Caso queira mudar, lembre-se:</li>"
        "<li>O nome de usuário deve possuir no máximo 150 caracteres. Apenas letras, dígitos e @/./+/-/_ são permitidos.</li>"
        "</ul>"
        )
        
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'first_name': 'Nome',
            'last_name': 'Sobrenome',
            'username': 'Nome de Usuário',
            'email': 'Email', 
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        # Validar senhas apenas se pelo menos uma foi preenchida
        if password or password_confirm:
            if password != password_confirm:
                raise ValidationError("As senhas não coincidem.")
            if len(password) < 8:
                raise ValidationError("A senha deve ter pelo menos 8 caracteres.")
        
        return cleaned_data

# forms referentes a loja
class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = ['nome', 'codigo', 'categoria', 'preco_custo', 'preco_venda', 'estoque_minimo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do produto'}),
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Código (opcional)'}),
            'categoria': forms.Select(attrs={'class': 'form-control'}),
            'preco_custo': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Preço de custo'}),
            'preco_venda': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Preço de venda'}),
            'estoque_minimo': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Estoque mínimo'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categoria'].empty_label = 'Selecione uma categoria'

class VariacaoForm(forms.ModelForm):
    total_custo = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly', 'placeholder': 'Custo total'})
    )

    class Meta:
        model = Variacao
        fields = ['tamanho', 'cor', 'quantidade', 'total_custo']
        widgets = {
            'tamanho': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tamanho (ex.: P, M, G)'}),
            'cor': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Cor (ex.: Vermelho)'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Quantidade'}),
        }

    def __init__(self, *args, **kwargs):
        preco_custo = kwargs.pop('preco_custo', '0')  # Default preco_custo para '0' caso não informado
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Div('tamanho', 'cor', 'quantidade', 'total_custo', css_class='row')
        )
        # Set atributo data-preco-custo para cálculo com JavaScript
        try:
            if self.instance.pk and self.instance.produto_id:  # Checa produto_id para evitar erro RelatedObjectDoesNotExist
                self.fields['quantidade'].widget.attrs['data-preco-custo'] = str(self.instance.produto.preco_custo)
            else:
                self.fields['quantidade'].widget.attrs['data-preco-custo'] = str(preco_custo)
        except Exception as e:
            logger.debug(f"Error setting data-preco-custo: {str(e)}")
            self.fields['quantidade'].widget.attrs['data-preco-custo'] = '0'

class VariacaoFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.preco_custo = kwargs.pop('preco_custo', '0')
        super().__init__(*args, **kwargs)
        for form in self.forms:
            form.preco_custo = self.preco_custo  # Passa preco_custo para cada form

    def clean(self):
        super().clean()
        logger.debug("Validating VariacaoFormSet")
        for i, form in enumerate(self.forms):
            if form.cleaned_data:
                tamanho = form.cleaned_data.get('tamanho', '')
                cor = form.cleaned_data.get('cor', '')
                quantidade = form.cleaned_data.get('quantidade', 0)
                logger.debug(f"Form {i}: tamanho={tamanho}, cor={cor}, quantidade={quantidade}")
                if not tamanho and not cor and quantidade == 0:
                    logger.debug(f"Form {i} is empty, skipping validation")
                    continue
                if not tamanho or not cor:
                    form.add_error(None, "Tamanho e cor são obrigatórios se a quantidade for informada.")

VariacaoFormSet = inlineformset_factory(
    Produto, Variacao, form=VariacaoForm, extra=1, max_num=1, can_delete=False, formset=VariacaoFormSet
)

class ItemVendaForm(forms.ModelForm):
    class Meta:
        model = ItemVenda
        fields = ['produto', 'variacao', 'quantidade']
        widgets = {
            'produto': forms.Select(attrs={'class': 'form-control produto-select'}),
            'variacao': forms.Select(attrs={'class': 'form-control variacao-select'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Quantidade'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['produto'].queryset = Produto.objects.filter(is_active=True).select_related('categoria')
        produto_id = None
        if self.data and self.prefix:
            try:
                produto_id = self.data.get(f'{self.prefix}-produto')
                if produto_id:
                    produto_id = int(produto_id)
                logger.debug(f"Form {self.prefix}: Produto ID from POST: {produto_id}")
            except (ValueError, TypeError):
                logger.debug(f"Form {self.prefix}: No valid produto_id in POST")
        if self.instance.pk and self.instance.produto:
            produto_id = self.instance.produto.id
            logger.debug(f"Form {self.prefix}: Produto ID from instance: {produto_id}")
        if produto_id:
            try:
                self.fields['variacao'].queryset = Variacao.objects.filter(
                    produto_id=produto_id,
                    quantidade__gt=0
                ).select_related('produto__categoria')
                logger.debug(f"Form {self.prefix}: Variacao queryset: {list(self.fields['variacao'].queryset.values('id', 'tamanho', 'cor', 'quantidade'))}")
            except Exception as e:
                logger.error(f"Form {self.prefix}: Error setting variacao queryset: {str(e)}")
                self.fields['variacao'].queryset = Variacao.objects.none()
        else:
            self.fields['variacao'].queryset = Variacao.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        produto = cleaned_data.get('produto')
        variacao = cleaned_data.get('variacao')
        quantidade = cleaned_data.get('quantidade')
        logger.debug(f"Form {self.prefix}: Cleaning - produto={produto}, variacao={variacao}, quantidade={quantidade}")
        if produto or variacao or quantidade:
            if not produto:
                raise ValidationError("Selecione um produto.")
            if not variacao:
                raise ValidationError("Selecione uma variação.")
            if not quantidade:
                raise ValidationError("Informe a quantidade.")
            if variacao and variacao.produto != produto:
                raise ValidationError(f"A variação {variacao} não pertence ao produto {produto}.")
            if variacao and not variacao.produto.preco_venda:
                raise ValidationError(f"O produto {produto} não tem preço de venda definido.")
            if variacao and quantidade:
                current_quantidade = self.instance.quantidade if self.instance.pk else 0
                quantidade_diff = quantidade - current_quantidade
                if quantidade_diff > variacao.quantidade:
                    raise ValidationError(f"A quantidade solicitada ({quantidade}) excede o estoque disponível ({variacao.quantidade}).")
        return cleaned_data

ItemVendaFormSet = inlineformset_factory(
    Venda, ItemVenda, form=ItemVendaForm, extra=3, can_delete=True
)

class MovimentacaoEstoqueForm(forms.ModelForm):
    variacao = forms.ModelChoiceField(
        queryset=Variacao.objects.filter(quantidade__gt=0).select_related('produto'),
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_variacao'}),
        label='Produto e Variação'
    )
    preco_custo = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Preço de Custo', 'step': '0.01'}),
        label='Preço de Custo'
    )
    preco_venda = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Preço de Venda', 'step': '0.01'}),
        label='Preço de Venda'
    )

    class Meta:
        model = MovimentacaoEstoque
        fields = ['variacao', 'quantidade', 'motivo', 'preco_custo', 'preco_venda']
        widgets = {
            'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Quantidade'}),
            'motivo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Motivo (opcional)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Customiza o display de escolhas de variação para incluir detalhes do produto
        self.fields['variacao'].label_from_instance = lambda obj: f"{obj.produto.nome} ({obj.produto.categoria.nome}) - {obj.tamanho or '-'}/{obj.cor or '-'}"
        # Populate dados do proputo para JavaScript (for preco_custo e preco_venda)
        products_data = {
            str(v.id): {
                'preco_custo': str(v.produto.preco_custo),
                'preco_venda': str(v.produto.preco_venda)
            } for v in Variacao.objects.filter(quantidade__gt=0).select_related('produto')
        }
        self.fields['preco_custo'].widget.attrs['data-products'] = json.dumps(products_data)
        self.fields['preco_venda'].widget.attrs['data-products'] = json.dumps(products_data)

class DespesaForm(forms.ModelForm):
    class Meta:
        model = Despesa
        fields = ['valor', 'descricao']
        widgets = {
            'valor': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Valor (R$)'}),
            'descricao': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descrição'}),
        }

ItemVendaFormSet = inlineformset_factory(
    Venda, ItemVenda, form=ItemVendaForm, extra=1, can_delete=False
)

class ItemCarrinhoForm(forms.Form):
    variacao = forms.ModelChoiceField(
        queryset=Variacao.objects.filter(quantidade__gt=0).select_related('produto__categoria'),
        widget=forms.Select(attrs={'class': 'form-control variacao-select'}),
        label='Produto e Variação',
        empty_label="Selecione um produto e variação"
    )
    quantidade = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Quantidade'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Costuomiza display para incluir detalhes de produto e variação
        self.fields['variacao'].label_from_instance = lambda obj: f"{obj.produto.nome} ({obj.produto.categoria.nome}) - {obj.tamanho or '-'}/{obj.cor or '-'} (Estoque: {obj.quantidade})"

    def clean(self):
        cleaned_data = super().clean()
        variacao = cleaned_data.get('variacao')
        quantidade = cleaned_data.get('quantidade')
        logger.debug(f"Cleaning ItemCarrinhoForm: variacao={variacao}, quantidade={quantidade}")
        if variacao and quantidade:
            if quantidade > variacao.quantidade:
                raise forms.ValidationError(f"A quantidade solicitada ({quantidade}) excede o estoque disponível ({variacao.quantidade}).")
        elif variacao or quantidade:
            raise forms.ValidationError("Preencha todos os campos (produto e variação e quantidade).")
        return cleaned_data

class VendaForm(forms.ModelForm):  # Remove definição duplicada
    valor_recebido = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Valor recebido (R$)'})
    )
    troco = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly', 'placeholder': 'Troco (R$)'})
    )

    class Meta:
        model = Venda
        fields = ['nome_cliente', 'forma_pagamento', 'desconto', 'valor_recebido', 'troco']
        widgets = {
            'nome_cliente': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do cliente (opcional)'}),
            'forma_pagamento': forms.Select(attrs={'class': 'form-control'}),
            'desconto': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Desconto (R$)'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        forma_pagamento = cleaned_data.get('forma_pagamento')
        valor_recebido = cleaned_data.get('valor_recebido')
        if forma_pagamento == 'DIN':
            if valor_recebido is None:
                self.add_error('valor_recebido', 'O valor recebido é obrigatório para pagamento em dinheiro.')
        else:
            cleaned_data['valor_recebido'] = None
            cleaned_data['troco'] = None
        return cleaned_data

class ConcluirVendaForm(forms.ModelForm):
    valor_recebido = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Valor recebido (R$)', 'id': 'id_valor_recebido'})
    )
    troco = forms.DecimalField(
        max_digits=10, decimal_places=2, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly', 'placeholder': 'Troco (R$)', 'id': 'id_troco'})
    )

    def __init__(self, *args, **kwargs):
        self.valor_total = kwargs.pop('valor_total', 0)
        super().__init__(*args, **kwargs)
        logger.debug(f"ConcluirVendaForm initialized with valor_total: {self.valor_total}")

    class Meta:
        model = Venda
        fields = ['nome_cliente', 'forma_pagamento', 'desconto', 'valor_recebido', 'troco']
        widgets = {
            'nome_cliente': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do cliente (opcional)'}),
            'forma_pagamento': forms.Select(attrs={'class': 'form-control', 'id': 'id_forma_pagamento'}),
            'desconto': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Desconto (R$)', 'id': 'id_desconto'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        forma_pagamento = cleaned_data.get('forma_pagamento')
        valor_recebido = cleaned_data.get('valor_recebido')
        desconto = cleaned_data.get('desconto') or 0
        final_value = self.valor_total - desconto

        if final_value < 0:
            self.add_error('desconto', 'O desconto não pode resultar em um valor total negativo.')
        if forma_pagamento == 'DIN':
            if valor_recebido is None:
                self.add_error('valor_recebido', 'O valor recebido é obrigatório para pagamento em dinheiro.')
            elif valor_recebido < final_value:
                self.add_error('valor_recebido', 'O valor recebido deve ser maior ou igual ao valor total após desconto.')
            else:
                cleaned_data['troco'] = valor_recebido - final_value
        else:
            cleaned_data['valor_recebido'] = None
            cleaned_data['troco'] = None
        return cleaned_data
    
class TrocaForm(forms.Form):
    variacao_trocada = forms.ModelChoiceField(
        queryset=Variacao.objects.filter(quantidade__gt=0).select_related('produto__categoria'),
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_variacao_trocada'}),
        label='Produto e Variação a Ser Trocado (Retornado ao Estoque)',
        empty_label='Selecione um produto e variação'
    )
    quantidade_trocada = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Quantidade', 'id': 'id_quantidade_trocada'}),
        label='Quantidade Trocada'
    )
    variacao_substituta = forms.ModelChoiceField(
        queryset=Variacao.objects.filter(quantidade__gt=0).select_related('produto__categoria'),
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_variacao_substituta'}),
        label='Produto e Variação Substituta (Saída do Estoque)',
        empty_label='Selecione um produto e variação'
    )
    quantidade_substituta = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Quantidade', 'id': 'id_quantidade_substituta'}),
        label='Quantidade Substituta'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ['variacao_trocada', 'variacao_substituta']:
            self.fields[field].label_from_instance = lambda obj: (
                f"{obj.produto.nome} ({obj.produto.categoria.nome}) - {obj.tamanho or '-'}/{obj.cor or '-'} "
                f"(Estoque: {obj.quantidade})"
            )
        products_data = {
            str(v.id): {
                'preco_venda': str(v.produto.preco_venda)
            } for v in Variacao.objects.filter(quantidade__gt=0).select_related('produto')
        }
        self.fields['variacao_substituta'].widget.attrs['data-products'] = json.dumps(products_data)

    def clean(self):
        cleaned_data = super().clean()
        variacao_trocada = cleaned_data.get('variacao_trocada')
        quantidade_trocada = cleaned_data.get('quantidade_trocada')
        variacao_substituta = cleaned_data.get('variacao_substituta')
        quantidade_substituta = cleaned_data.get('quantidade_substituta')

        if not all([variacao_trocada, quantidade_trocada, variacao_substituta, quantidade_substituta]):
            raise forms.ValidationError("Todos os campos são obrigatórios.")

        if quantidade_substituta > variacao_substituta.quantidade:
            self.add_error(
                'quantidade_substituta',
                f"A quantidade solicitada ({quantidade_substituta}) excede o estoque disponível ({variacao_substituta.quantidade})."
            )

        valor_trocado = variacao_trocada.produto.preco_venda * quantidade_trocada
        valor_substituto = variacao_substituta.produto.preco_venda * quantidade_substituta
        cleaned_data['diferenca_preco'] = valor_substituto - valor_trocado

        return cleaned_data