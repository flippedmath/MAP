# This command run will add a single token element from the set into the entity_type table.
# Here is an example command for adding a single entity_type row for 'randInt' token:
# python manage.py seed_entity_type --token=randInt

import json
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from assessment_tool.models import EntityType 

class Command(BaseCommand):
    help = "Seeds or updates a single entry in the entity_type table by its token designation."

    DYNAMIC_VARIABLES = [
        {
            "name": "Random Integer",
            "token": "randInt",
            "inputs": {
                "min": {"field": "integer", "value": ["integer"], "default": 1},
                "max": {"field": "integer", "value": ["integer"], "default": 9},
                "step": {"field": "integer", "value": ["integer"], "default": 1},
                "exclude": {"field": "text", "value": ["array(['integer'])"], "default": ""}
            },
            "output": ["integer", "double"],
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": "Produces a random integer within the range {min} to {max} (inclusive) ignoring all comma-separated {exclude} values. {step} represents the interval between possible results."
        },
        {
            "name": "Random Double",
            "token": "rand",
            "inputs": {
                "min": {"field": "double", "value": ["double", "integer"], "default": 0.0},
                "max": {"field": "double", "value": ["double", "integer"], "default": 1.0},
                "step": {"field": "double", "value": ["double", "integer"], "default": 0.01}
            },
            "output": ["double"],
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": "Produces a random decimal number between {min} and {max}. {step} represents the interval between possible results"
        },
        {
            "name": "Formula",
            "token": "formula",
            "inputs": {
                "formula": {"field": "text", "value": ["string", "array(['formula'])"]},
                "solve method": {"field": "dropdown", "value": ["string_match(['simplify', 'expand polynomial', 'factor polynomial', 'variable substitution', 'leave as formula'])"], "default": "leave as formula"},
                "variables": {"field": "text", "value": ["array(['string'])"], "default": ""},
                "variable substitution": {"field": "text", "value": ["string_match([\"self('variables')\"])", "or_null"], "default": ""},
                "variable to solve for": {"field": "text", "value": ["string", "or_null"], "default": ""}
            },
            "output": ["double", "integer", "formula"],
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": (
                "<div style='font-family: system-ui, sans-serif; font-size: 0.75rem; color: #1e293b; max-width: 480px; max-height: 400px; overflow-y: auto; padding-right: 4px;'>"
                "<p style='padding: 3px; color: #475569;'>When multiplying '*' must be used between terms. When identifying 'power of', two asterix should be used between the terms --> '**'</p>"
                # --- SECTION 1: ALGEBRA ---
                "<p style='margin: 8px 0 4px 0; font-weight: bold; color: #0284c7; border-bottom: 1px solid #cbd5e1;'>1. Algebra Components</p>"
                "<table style='width: 100%; border-collapse: collapse; margin-bottom: 8px; text-align: left;'>"
                "  <thead>"
                "    <tr style='background: #f1f5f9; border-bottom: 1px solid #cbd5e1;'><th style='padding: 3px;'>Math Notation</th><th style='padding: 3px;'>Valid SymPy String Example</th><th style='padding: 3px;'>Valid LaTeX</th><th style='padding: 3px;'>Syntax Breakdown</th></tr>"
                "  </thead>"
                "  <tbody>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(2x + 5\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"2*x + 5\"</td><td style='padding: 3px; font-family: monospace;'>\"2x + 5\"</td><td style='padding: 3px; color: #475569;'>Implicit multiplication is fine in LaTeX but requires * in SymPy.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(x^2 - 4\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"x**2 - 4\"</td><td style='padding: 3px; font-family: monospace;'>\"x^2 - 4\"</td><td style='padding: 3px; color: #475569;'>LaTeX uses ^ for powers; SymPy strictly requires **.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(\\frac{x+1}{x-1}\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"(x + 1) / (x - 1)\"</td><td style='padding: 3px; font-family: monospace;'>\"\\frac{x+1}{x-1}\"</td><td style='padding: 3px; color: #475569;'>LaTeX uses \\frac{num}{den}; SymPy uses standard / division.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(\\sqrt{x+2}\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"sqrt(x + 2)\"</td><td style='padding: 3px; font-family: monospace;'>\"\\sqrt{x + 2}\"</td><td style='padding: 3px; color: #475569;'>SymPy uses sqrt(); LaTeX wraps the inner terms in curly brackets {}.</td></tr>"
                "  </tbody>"
                "</table>"

                # --- SECTION 2: TRIGONOMETRY ---
                "<p style='margin: 12px 0 4px 0; font-weight: bold; color: #0284c7; border-bottom: 1px solid #cbd5e1;'>2. Trigonometry Components</p>"
                "<table style='width: 100%; border-collapse: collapse; margin-bottom: 8px; text-align: left;'>"
                "  <thead>"
                "    <tr style='background: #f1f5f9; border-bottom: 1px solid #cbd5e1;'><th style='padding: 3px;'>Math Notation</th><th style='padding: 3px;'>Valid SymPy String Example</th><th style='padding: 3px;'>Valid LaTeX</th><th style='padding: 3px;'>Syntax Breakdown</th></tr>"
                "  </thead>"
                "  <tbody>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(\\sin(x)\\cos(x)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"sin(x) * cos(x)\"</td><td style='padding: 3px; font-family: monospace;'>\"\\sin(x)\\cos(x)\"</td><td style='padding: 3px; color: #475569;'>LaTeX functions start with backslashes; SymPy uses plain Python functions.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(\\tan^2(x)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"tan(x)**2\"</td><td style='padding: 3px; font-family: monospace;'>\"\\tan^2(x)\"</td><td style='padding: 3px; color: #475569;'>LaTeX places the power right after the function name; SymPy puts it at the end.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(\\arcsin(x)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"asin(x)\"</td><td style='padding: 3px; font-family: monospace;'>\"\\arcsin(x)\" or r\"\\sin^{-1}(x)\"</td><td style='padding: 3px; color: #475569;'>SymPy shortens inverse functions to asin, acos, and atan.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(\\sin(2\\pi x)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"sin(2 * pi * x)\"</td><td style='padding: 3px; font-family: monospace;'>\"\\sin(2\\pi x)\"</td><td style='padding: 3px; color: #475569;'>Pi is represented as \\pi in LaTeX and simply pi in SymPy.</td></tr>"
                "  </tbody>"
                "</table>"

                # --- SECTION 3: CALCULUS ---
                "<p style='margin: 12px 0 4px 0; font-weight: bold; color: #0284c7; border-bottom: 1px solid #cbd5e1;'>3. Calculus Components</p>"
                "<table style='width: 100%; border-collapse: collapse; text-align: left;'>"
                "  <thead>"
                "    <tr style='background: #f1f5f9; border-bottom: 1px solid #cbd5e1;'><th style='padding: 3px;'>Calculus Operation</th><th style='padding: 3px;'>Math Notation</th><th style='padding: 3px;'>Valid SymPy String Example</th><th style='padding: 3px;'>Valid LaTeX</th><th style='padding: 3px;'>Syntax Breakdown</th></tr>"
                "  </thead>"
                "  <tbody>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>Derivative</td><td style='padding: 3px;'>\\(\\frac{d}{dx}(x^3)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"diff(x**3, x)\"</td><td style='padding: 3px; font-family: monospace;'>\"\\frac{d}{dx}(x^3)\"</td><td style='padding: 3px; color: #475569;'>LaTeX visually structures the fraction; SymPy uses functional diff(expr, var).</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>Higher-Order Derivative</td><td style='padding: 3px;'>\\(\\frac{d^2}{dx^2}(\\sin(x))\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"diff(sin(x), x, 2)\"</td><td style='padding: 3px; font-family: monospace;'>\"\\frac{d^2}{dx^2}(\\sin(x))\"</td><td style='padding: 3px; color: #475569;'>LaTeX adds powers to the d and dx; SymPy appends the order number at the end.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>Indefinite Integral</td><td style='padding: 3px;'>\\(\\int e^x dx\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"integrate(exp(x), x)\"</td><td style='padding: 3px; font-family: monospace;'>\"\\int e^x dx\"</td><td style='padding: 3px; color: #475569;'>LaTeX uses \\int; SymPy uses integrate() and converts \\(e^{x}\\) to exp(x).</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>Definite Integral</td><td style='padding: 3px;'>\\(\\int_{0}^{1} x^2 dx\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"integrate(x**2, (x, 0, 1))\"</td><td style='padding: 3px; font-family: monospace;'>\"\\int_{0}^{1} x^2 dx\"</td><td style='padding: 3px; color: #475569;'>LaTeX applies bounds with _ and ^; SymPy bundles them into a tuple (var, lower, upper).</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>Limit</td><td style='padding: 3px;'>\\(\\lim_{x \\to 0} \\frac{\\sin(x)}{x}\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"limit(sin(x)/x, x, 0)\"</td><td style='padding: 3px; font-family: monospace;'>\"\\lim_{x \\to 0} \\frac{\\sin(x)}{x}\"</td><td style='padding: 3px; color: #475569;'>LaTeX uses \\lim_{x \\to 0}; SymPy structures it as limit(expr, var, point).</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>Limit to Infinity</td><td style='padding: 3px;'>\\(\\lim_{x \\to \\infty} \\frac{1}{x}\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold;'>\"limit(1/x, x, oo)\"</td><td style='padding: 3px; font-family: monospace;'>\"\\lim_{x \\to \\infty} \\frac{1}{x}\"</td><td style='padding: 3px; color: #475569;'>Infinity is \\infty in LaTeX, but is written as two lowercase letters oo in SymPy.</td></tr>"
                "  </tbody>"
                "</table>"
                "</div>"
            )
        },
        {
            "name": "Matrix",
            "token": "matrix",
            "inputs": {
                "rows": {"field": "integer", "value": ["integer"], "default": 3},
                "cols": {"field": "integer", "value": ["integer"], "default": 3},
                "cells": {"field": "double", "value": ["array([array([['double', 'integer', 'formula', 'string']])])"], "default": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
            },
            "output": ["matrix"],
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": "Create a Matrix"
        },
        {
            "name": "Prime Factors",
            "token": "primeFactors",
            "inputs": {
                "number to factor": {"field": "integer", "value": ["integer"]}
            },
            "output": ["array(['integer'])"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": "Given an integer, find the factor list"
        },
        {
            "name": "Graph",
            "token": "graph",
            "answer_field": False,
            "inputs": {
                "formulas": {"field": "array", "value": ["string", "array(['formula'])"]},
                "variables": {"field": "text", "value": ["array(['string'])"], "default": "x,y"},
                "x-axis range": {"field": "<'double'> to <'double'> by interval <'double'>", "value": ["array(['double'])"], "default": [-5, 5, 0.5]},
                "y-axis range": {"field": "<'double'> to <'double'> by interval <'double'>", "value": ["array(['double'])"], "default": [-5, 5, 0.5]}
            },
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": "Create a graph using one or more formulas"
        }
    ]

    ANSWER_INPUT_FIELDS = [
        {
            "name": "Numeric Tolerance",
            "token": "numAnswer",
            "answer_field": True,
            "inputs": {
                "value": {"field": "double", "value": ["double"]},
                "tolerance": {"field": "double", "value": ["double"], "default": 0.0005}
            },
            "output": ["double"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "A tolerance of 0.0005 is equivalent to identifying that the user needs to be at least accurate up to 0.001"
        },
        {
            "name": "Short Answer",
            "token": "shortAnswer",
            "answer_field": True,
            "inputs": {
                "value": {"field": "text", "value": ["string"]}
            },
            "output": ["string"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "An exact match of text is looked for. Note: it does trim text and match upper/lower cases before comparing."
        },
        {
            "name": "Long Answer",
            "token": "longAnswer",
            "answer_field": True,
            "inputs": {
                "value": {"field": "paragraph", "value": ["string"]}
            },
            "output": ["string"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "An exact match of text is looked for. Note: it does trim text and match upper/lower cases before comparing."
        },
        {
            "name": "Array Matching (unordered)",
            "token": "arrayMatchingUnordered",
            "answer_field": True,
            "inputs": {
                "results": {"field": "string", "value": ["array([['integer', 'double', 'string', 'formula']])"]}
            },
            "output": ["array(['integer', 'double', 'string', 'formula'])"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "Given an array, compare to Student provided comma/space-separated array to count matches"
        },
        {
            "name": "Multiple Choice",
            "token": "multipleChoiceAnswer",
            "answer_field": True,
            "inputs": {
                "value": {"field": "checkboxes", "value": ["array(['content'])"]}
            },
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "Multiple choice question will display to Student as radio selection if only a single answer is specified by Teacher"
        },
        {
            "name": "Matrix",
            "token": "matrixAnswer",
            "answer_field": True,
            "inputs": {
                "rows": {"field": "integer", "value": ["integer"], "default": 3},
                "cols": {"field": "integer", "value": ["integer"], "default": 3},
                "cells": {"field": "double", "value": ["matrix", "array([array([['double', 'integer', 'formula']])])"], "default": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
            },
            "output": ["matrix"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "The input can be a LaTeX formula, or typed out."
        },
        {
            "name": "Matrix Calculations",
            "token": "matrixMath",
            "answer_field": True,
            "inputs": {
                "matrix A": {"field": "entity", "value": ["matrix"], "default": None},
                "matrix B": {"field": "entity", "value": ["matrix"], "default": None},
                "scalar": {"field": "double", "value": ["double"], "default": 1.0},
                "calculate": {"field": "dropdown", "value": ["string_match(['multiply', 'add', 'subtract', 'inversion', 'transpose', 'scalar', 'determinate'])"], "default": "scalar"}
            },
            "output": ["matrix", "double"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "Perform one of AxB/A+B/A-B/A^-1/transpose(A)/A*c/det(A) on matricies"
        },
        {
            "name": "Matrix Calculations By Index",
            "token": "matrixResultByIndex",
            "answer_field": True,
            "inputs": {
                "matrix": {"field": "entity", "value": ["matrix"]},
                "row": {"field": "integer", "value": ["integer"], "default": 1},
                "column": {"field": "integer", "value": ["integer"], "default": 1}
            },
            "output": ["double", "integer", "formula"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "Pull out a specific cell value in a given matrix"
        },
        {
            "name": "Graph Between Points",
            "token": "graphBetweenPoints",
            "answer_field": True,
            "inputs": {
                "coordinate groups": {"field": "array", "value": ["array([array(['double'])])"]},
                "x-axis range": {"field": "<'double'> to <'double'> by interval <'double'>", "value": ["array(['double'])"], "default": [-5, 5, 0.5]},
                "y-axis range": {"field": "<'double'> to <'double'> by interval <'double'>", "value": ["array(['double'])"], "default": [-5, 5, 0.5]}
            },
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "Create a graph using one or more lines"
        },
        {
            "name": "Canvas",
            "token": "canvas",
            "answer_field": True,
            "inputs": {
                "canvas": {"field": "whiteboard", "value": ["content"]}
            },
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 0.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "Create a freehand canvas or whiteboard field"
        }
    ]
    # add a slope field entity, lots of dots in a graph, make slope line on given points

    def add_arguments(self, parser):
        parser.add_argument(
            '--token',
            type=str,
            required=True,
            help="The specific token field string identifier to process (e.g., 'randInt', 'numAnswer')."
        )

    def handle(self, *args, **options):
        target_token = options['token']
        
        all_blueprints = self.DYNAMIC_VARIABLES + self.ANSWER_INPUT_FIELDS
        blueprint = next((item for item in all_blueprints if item["token"] == target_token), None)
        
        if not blueprint:
            raise CommandError(f"Token value '{target_token}' was not found in the verified JSON layouts lists.")

        self.stdout.write(self.style.NOTICE(f"Found token template for token '{target_token}'. Synchronizing table record..."))

        with transaction.atomic():
            serialized_format_pattern = json.dumps(blueprint)
            serialized_insert_entity_pattern = json.dumps({})
            serialized_entity_name_list = json.dumps([blueprint["entity_name_list"]])

            entity_type_obj, created = EntityType.objects.using('default').get_or_create(
                name=blueprint["token"],
                defaults={
                    "format_pattern": serialized_format_pattern,
                    "insert_entity_pattern": serialized_insert_entity_pattern,
                    "entity_name_list": serialized_entity_name_list
                }
            )
            
            # If the record already existed, synchronize it with the latest structure safely
            if not created:
                entity_type_obj.format_pattern = serialized_format_pattern
                entity_type_obj.insert_entity_pattern = serialized_insert_entity_pattern
                entity_type_obj.entity_name_list = serialized_entity_name_list
                entity_type_obj.save()

        status_text = "CREATED fresh rows successfully" if created else "UPDATED active schema maps successfully"
        self.stdout.write(self.style.SUCCESS(f"🚀 SUCCESS: '{blueprint['name']}' ({target_token}) was {status_text} inside the database."))