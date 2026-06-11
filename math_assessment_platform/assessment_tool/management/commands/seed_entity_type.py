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
            "output": ["integer"],
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": "Produces a random integer within the range {min} to {max} (inclusive) ignoring all comma-separated {exclude} values. {step} represents the interval between possible results."
        },
        {
            "name": "Random Double",
            "token": "rand",
            "inputs": {
                "min": {"field": "double", "value": ["double"], "default": 0.0},
                "max": {"field": "double", "value": ["double"], "default": 1.0},
                "step": {"field": "double", "value": ["double"], "default": 0.01}
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
                "solve method": {"field": "dropdown", "value": ["string_match(['simplify', 'expand polynomial', 'solve for _', 'leave as formula'])"], "default": "leave as formula"},
                "variables": {"field": "text", "value": ["array(['string'])"], "default": ""},
                "solve for _": {"field": "text", "value": ["string_match([\"self('variables')\"])"]}
            },
            "output": ["double", "integer", "formula"],
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": "The input can be a LaTeX formula, or typed out. 'y = 4*x^3 + 2*x^2 + 5*x - 7' is equivalent to 'y = 4*x**3 + 2*x**2 + 5*x - 7'"
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
                "formulas": {"field": "array", "value": ["array(['formula'])"]},
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
            # 🎯 FIXED: pass an empty dict structure {} instead of None to fulfill the database's NOT NULL constraint
            entity_type_obj, created = EntityType.objects.using('default').get_or_create(
                name=blueprint["token"],
                defaults={
                    "format_pattern": blueprint,
                    "insert_entity_pattern": {},
                    "entity_name_list": [blueprint["entity_name_list"]]
                }
            )
            
            # If the record already existed, synchronize it with the latest structure
            if not created:
                entity_type_obj.format_pattern = blueprint
                entity_type_obj.insert_entity_pattern = {}
                entity_type_obj.entity_name_list = [blueprint["entity_name_list"]]
                entity_type_obj.save()

        status_text = "CREATED fresh rows successfully" if created else "UPDATED active schema maps successfully"
        self.stdout.write(self.style.SUCCESS(f"🚀 SUCCESS: '{blueprint['name']}' ({target_token}) was {status_text} inside the database."))