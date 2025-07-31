from django import template
from decimal import Decimal, DecimalException

register = template.Library()

@register.filter
def multiply(value, arg):
    try:
        return Decimal(str(value)) * Decimal(str(arg))
    except (ValueError, TypeError, DecimalException):
        return Decimal('0')

@register.filter
def total_carrinho(carrinho):
    try:
        return sum(Decimal(str(item['quantidade'])) * Decimal(str(item['preco_unitario'])) for item in carrinho)
    except (ValueError, TypeError, DecimalException):
        return Decimal('0')