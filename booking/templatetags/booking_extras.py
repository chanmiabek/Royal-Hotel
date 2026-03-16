from django import template

register = template.Library()


@register.filter(name="trim")
def trim(value):
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return value

