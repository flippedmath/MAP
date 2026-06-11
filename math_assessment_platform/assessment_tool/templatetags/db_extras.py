import json
from django import template
register = template.Library()

@register.filter(name='get_attr')
def get_attr(obj, attr_name):
    """
    Safely retrieves model attributes dynamically.
    If the attribute value is a Python dict or list (JSON data structures),
    it safely returns it as an indented JSON string format for easy reading.
    """
    try:
        value = getattr(obj, attr_name)
        
        # 🎯 Check if the resolved attribute value is a native container type
        if isinstance(value, (dict, list)):
            return json.dumps(value, indent=2)
            
        return value
    except AttributeError:
        return ""