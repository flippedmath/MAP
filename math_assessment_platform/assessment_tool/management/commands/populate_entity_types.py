import json
from django.core.management.base import BaseCommand
from assessment_tool.models import EntityType  

class Command(BaseCommand):
    help = "Populates or updates the unmanaged entity_type table with master serialization schemas."

    def handle(self, *args, **options):
        # Master blueprint dictionary containing all structural variant schemas
        entity_blueprints = [
            # -------------------------------------------------------------
            # DYNAMIC CORE VARIABLES (Variables calculated per test attempt)
            # -------------------------------------------------------------
            {
                "name": "variable_numeric",
                "format_pattern": "Range [{min}, {max}], step {step}, excluding {exclude}",
                "insert_entity_pattern": json.dumps({
                    "type": "variable_numeric",
                    "token": "num1",
                    "min": -9,
                    "max": 9,
                    "exclude": [0],
                    "step": 1
                }, indent=2),
                "entity_name_list": "min, max, exclude, step"
            },
            {
                "name": "variable_equation",
                "format_pattern": "Formula: {formula} with variables: {variables}",
                "insert_entity_pattern": json.dumps({
                    "type": "variable_equation",
                    "token": "equation1",
                    "formula": "",
                    "variables": "x"
                }, indent=2),
                "entity_name_list": "formula, variables"
            },
            {
                "name": "variable_matrix",
                "format_pattern": "Matrix {rows}x{cols} cell configurations matrix grid",
                "insert_entity_pattern": json.dumps({
                    "type": "variable_matrix",
                    "token": "matrix1",
                    "rows": 3,
                    "cols": 3,
                    "cells": [["1", "0", "0"], ["0", "1", "0"], ["0", "0", "1"]]
                }, indent=2),
                "entity_name_list": "rows, cols, cells"
            },
            {
                "name": "variable_string_array",
                "format_pattern": "Array: {strings}, Sync target: {sync_target}",
                "insert_entity_pattern": json.dumps({
                    "type": "variable_string_array",
                    "token": "stringArray1",
                    "strings": ["Kyle", "Kylie", "Sean"],
                    "sync_target": ""
                }, indent=2),
                "entity_name_list": "strings, sync_target"
            },

            # -------------------------------------------------------------
            # GRADED ANSWER INPUT BLOCKS (Evaluated server-side via SymPy)
            # -------------------------------------------------------------
            {
                "name": "multiple_choice",
                "format_pattern": "MC Single: {single_choice}, Options Array Count: {choices_count}",
                "insert_entity_pattern": json.dumps({
                    "type": "multiple_choice",
                    "token": "mc1",
                    "points": 1.0,
                    "single_choice": True,
                    "append_helper_text": True,
                    "decoy_generation_mode": "sympy_random",
                    "choices": [
                        {"id": "c1", "content": "", "is_correct": True, "comment": ""}
                    ]
                }, indent=2),
                "entity_name_list": "points, single_choice, decoy_generation_mode, choices"
            },
            {
                "name": "mathematical_expression",
                "format_pattern": "SymPy Expression Evaluation mode. Criteria target: {expected_structural_form}",
                "insert_entity_pattern": json.dumps({
                    "type": "mathematical_expression",
                    "token": "math1",
                    "points": 1.0,
                    "expected_structural_form": "Factor",  # Factor, Simplify, Expand, etc.
                    "correct_formula": ""
                }, indent=2),
                "entity_name_list": "points, expected_structural_form, correct_formula"
            },
            {
                "name": "numeric_tolerance",
                "format_pattern": "Target: {correct_value} +/- Tolerance Buffer: {tolerance}",
                "insert_entity_pattern": json.dumps({
                    "type": "numeric_tolerance",
                    "token": "numInput1",
                    "points": 1.0,
                    "correct_value": "",
                    "tolerance": 0.01,
                    "reveal_tolerance_to_student": False
                }, indent=2),
                "entity_name_list": "points, correct_value, tolerance, reveal_tolerance_to_student"
            },
            {
                "name": "short_text_input",
                "format_pattern": "Short Text entry. Auto Grade: {auto_grade}",
                "insert_entity_pattern": json.dumps({
                    "type": "short_text_input",
                    "token": "textInput1",
                    "points": 1.0,
                    "auto_grade": True,
                    "allow_formula_submission": False,
                    "expected_answers": []
                }, indent=2),
                "entity_name_list": "points, auto_grade, allow_formula_submission, expected_answers"
            },
            {
                "name": "long_text_input",
                "format_pattern": "Manual evaluation descriptive text block",
                "insert_entity_pattern": json.dumps({
                    "type": "long_text_input",
                    "token": "paragraphBlock1",
                    "points": 1.0,
                    "placeholder": "Enter detailed response..."
                }, indent=2),
                "entity_name_list": "points, placeholder"
            },
            {
                "name": "matrix_input",
                "format_pattern": "Expected target solution Matrix reference placeholder: {correct_matrix_variable}",
                "insert_entity_pattern": json.dumps({
                    "type": "matrix_input",
                    "token": "matrixInput1",
                    "points": 1.0,
                    "correct_matrix_variable": "",  # Maps directly to a token key name like <matrix1>
                    "allow_student_dimension_changes": False
                }, indent=2),
                "entity_name_list": "points, correct_matrix_variable, allow_student_dimension_changes"
            },

            # -------------------------------------------------------------
            # GRAPH INTEGRATIONS
            # -------------------------------------------------------------
            {
                "name": "graph_equation_insert",
                "format_pattern": "Axes boundaries ranges with formula strings array",
                "insert_entity_pattern": json.dumps({
                    "type": "graph_equation_insert",
                    "token": "graph1",
                    "allow_student_drawing_overlay": False,
                    "x_axis": {"min": "-2", "max": "5", "step": "1"},
                    "y_axis": {"min": "-5", "max": "5", "step": "1"},
                    "formulas": []
                }, indent=2),
                "entity_name_list": "allow_student_drawing_overlay, x_axis, y_axis, formulas"
            },
            {
                "name": "graph_between_points",
                "format_pattern": "Dynamic piecewise geometric curves map connecting point ranges",
                "insert_entity_pattern": json.dumps({
                    "type": "graph_between_points",
                    "token": "pointGraph1",
                    "x_range": {"min": -5, "max": 5},
                    "y_range": {"min": -5, "max": 5},
                    "curves": []
                }, indent=2),
                "entity_name_list": "x_range, y_range, curves"
            },

            # -------------------------------------------------------------
            # NON-GRADED TOOL IMPLEMENTATIONS
            # -------------------------------------------------------------
            {
                "name": "canvas_notes",
                "format_pattern": "Student scratchpad drawing canvas layer",
                "insert_entity_pattern": json.dumps({
                    "type": "canvas_notes",
                    "token": "canvas1",
                    "height_pixels": 300
                }, indent=2),
                "entity_name_list": "height_pixels"
            },

            # -------------------------------------------------------------
            # COMBINATION MATRIX WRAPPERS
            # -------------------------------------------------------------
            {
                "name": "multi_answer",
                "format_pattern": "Nested multi-part composite sub-problem array",
                "insert_entity_pattern": json.dumps({
                    "type": "multi_answer",
                    "token": "multiGroup1",
                    "sub_entities_tokens_list": []
                }, indent=2),
                "entity_name_list": "sub_entities_tokens_list"
            }
        ]

        # 2. Loop and execute write state changes inside the target database
        self.stdout.write(self.style.NOTICE("Initializing entity_type master catalog mapping values..."))
        
        success_count = 0
        for blueprint in entity_blueprints:
            obj, created = EntityType.objects.update_or_create(
                name=blueprint["name"],
                defaults={
                    "format_pattern": blueprint["format_pattern"],
                    "insert_entity_pattern": blueprint["insert_entity_pattern"],
                    "entity_name_list": blueprint["entity_name_list"]
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Inserted blueprint type: '{obj.name}'"))
            else:
                self.stdout.write(self.style.WARNING(f"Updated blueprint type: '{obj.name}'"))
            success_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully processed {success_count} structural templates into the database."))