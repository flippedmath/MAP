from django import template

register = template.Library()

@register.simple_tag
def define(val=None):
    """
    Allows defining a variable within a template context.
    Usage: {% define "some_value" as my_var %}
    """
    return val