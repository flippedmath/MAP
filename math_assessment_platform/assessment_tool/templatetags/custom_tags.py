from django import template

from assessment_tool.folder_roots import course_is_under_workspace

register = template.Library()

@register.simple_tag
def define(val=None):
    """
    Allows defining a variable within a template context.
    Usage: {% define "some_value" as my_var %}
    """
    return val


@register.simple_tag
def course_allows_management(course):
    """False for courses whose explorer folder lives under Workspace."""
    if course is None:
        return False
    return not course_is_under_workspace(course)