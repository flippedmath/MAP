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
            "note": "Produces a random integer within the range {min} to {max} (inclusive). Use 'Add number to exclude' to omit specific integers from the result pool. {step} is the interval between possible results."
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
                "variable to solve for": {"field": "text", "value": ["string", "or_null"], "default": ""},
                "output rhs only": {"field": "checkbox", "value": ["boolean"], "default": False},
                "simplify after substitution": {"field": "checkbox", "value": ["boolean"], "default": False}
            },
            "output": ["double", "integer", "formula"],
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": (
                "<div style='font-family: system-ui, sans-serif; font-size: 0.75rem; color: #1e293b; max-width: 480px; max-height: 400px; overflow-y: auto; padding-right: 4px;'>"
                "<p style='padding: 3px; color: #475569;'><strong>Syntax Tip:</strong> Powers can be written using either <code>^</code> or <code>**</code> (e.g., <code>x^2</code> or <code>x**2</code>). Implicit multiplication is automatically supported for numbers next to variables, brackets, or math functions (e.g., <code>8x</code> or <code>(x+1)(x-1)</code>).</p>"

                # --- SECTION 1: VARIABLE FORMATS ---
                "<p style='margin: 8px 0 4px 0; font-weight: bold; color: #0284c7; border-bottom: 1px solid #cbd5e1;'>1. Valid Variable Identifiers</p>"
                "<table style='width: 100%; border-collapse: collapse; margin-bottom: 8px; text-align: left;'>"
                "  <thead>"
                "    <tr style='background: #f1f5f9; border-bottom: 1px solid #cbd5e1;'><th style='padding: 3px;'>Variable Type</th><th style='padding: 3px;'>Valid Examples</th><th style='padding: 3px;'>Syntax / Constraints</th></tr>"
                "  </thead>"
                "  <tbody>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>Standard Characters</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>x, y, z2, A5</td><td style='padding: 3px; color: #475569;'>A single letter optionally followed by digits. Note: <code>E</code> and <code>I</code>/<code>i</code> are reserved system constants (Euler’s number and the imaginary unit).</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>Standard Subscripts</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>x_1, y_22, A_0</td><td style='padding: 3px; color: #475569;'>A single letter followed by an underscore and one or more digits.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>Greek Letters</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>alpha, theta, phi, omega</td><td style='padding: 3px; color: #475569;'>Full lowercase spelled names. Note: bare <code>beta</code>, <code>gamma</code>, and <code>zeta</code> are reserved SymPy functions — use a subscript (e.g. <code>beta_1</code>) to use them as variables.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>Greek Subscripts</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>alpha_3, beta_1, gamma2, theta_12</td><td style='padding: 3px; color: #475569;'>Spelled Greek words followed directly by digits, or by an underscore and digits (required for beta/gamma/zeta).</td></tr>"
                "  </tbody>"
                "</table>"

                # --- SECTION 2: ALGEBRA & COUPLING ---
                "<p style='margin: 12px 0 4px 0; font-weight: bold; color: #0284c7; border-bottom: 1px solid #cbd5e1;'>2. Algebra Components & Implicit Math</p>"
                "<table style='width: 100%; border-collapse: collapse; margin-bottom: 8px; text-align: left;'>"
                "  <thead>"
                "    <tr style='background: #f1f5f9; border-bottom: 1px solid #cbd5e1;'><th style='padding: 3px;'>Math Notation</th><th style='padding: 3px;'>Valid Entry Example</th><th style='padding: 3px;'>Implicit Asterisk?</th><th style='padding: 3px;'>Syntax Breakdown</th></tr>"
                "  </thead>"
                "  <tbody>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(8(x + 1)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"8(x+1)\"</td><td style='padding: 3px; color: #16a34a; font-weight: 600;'>Auto-Injected</td><td style='padding: 3px; color: #475569;'>Server automatically handles numbers against opening parentheses.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\((x + 1)(x - 1)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"(x+1)(x-1)\"</td><td style='padding: 3px; color: #16a34a; font-weight: 600;'>Auto-Injected</td><td style='padding: 3px; color: #475569;'>Server detects adjacent parenthetical blocks and handles multiplication.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(4\\alpha_{3} + 7x\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"4alpha_3 + 7x\"</td><td style='padding: 3px; color: #16a34a; font-weight: 600;'>Auto-Injected</td><td style='padding: 3px; color: #475569;'>Coefficients are auto-multiplied to Greek words or standard variables.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(x^3y^2\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"x**3 * y**2\"</td><td style='padding: 3px; color: #ea580c;'>Manual Required</td><td style='padding: 3px; color: #475569;'>Powers use <code>**</code>. Side-by-side alpha characters (xy) require explicit <code>*</code>.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(\\frac{x+1}{x-1}\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"(x + 1) / (x - 1)\"</td><td style='padding: 3px; color: #64748b;'>N/A</td><td style='padding: 3px; color: #475569;'>Use forward slash <code>/</code> for fractions. Enclose blocks in brackets to preserve order.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(\\sqrt{x+2}\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"sqrt(x + 2)\"</td><td style='padding: 3px; color: #64748b;'>N/A</td><td style='padding: 3px; color: #475569;'>Standard functional root wrapping syntax.</td></tr>"
                "  </tbody>"
                "</table>"

                # --- SECTION 3: TRIGONOMETRY & CONSTANTS ---
                "<p style='margin: 12px 0 4px 0; font-weight: bold; color: #0284c7; border-bottom: 1px solid #cbd5e1;'>3. Trigonometry & Advanced Math Functions</p>"
                "<table style='width: 100%; border-collapse: collapse; margin-bottom: 8px; text-align: left;'>"
                "  <thead>"
                "    <tr style='background: #f1f5f9; border-bottom: 1px solid #cbd5e1;'><th style='padding: 3px;'>Math Notation</th><th style='padding: 3px;'>Valid Entry Example</th><th style='padding: 3px;'>Implicit Asterisk?</th><th style='padding: 3px;'>Syntax Breakdown</th></tr>"
                "  </thead>"
                "  <tbody>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(5\\sin(x)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"5sin(x)\"</td><td style='padding: 3px; color: #16a34a; font-weight: 600;'>Auto-Injected</td><td style='padding: 3px; color: #475569;'>Numbers preceding known math keywords are auto-spaced with multiplication.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(x\\cos(x)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"xcos(x)\"</td><td style='padding: 3px; color: #16a34a; font-weight: 600;'>Auto-Injected</td><td style='padding: 3px; color: #475569;'>Variables immediately preceding known operations are safely isolated.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(\\tan^2(x)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"tan(x)**2\"</td><td style='padding: 3px; color: #64748b;'>N/A</td><td style='padding: 3px; color: #475569;'>Functional operators are squared by placing exponents outside the parameter bracket.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(e^{2x}\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"exp(2x)\"</td><td style='padding: 3px; color: #16a34a; font-weight: 600;'>Auto-Injected</td><td style='padding: 3px; color: #475569;'>Euler's constant base uses <code>exp()</code> structure. Note the inner <code>2x</code> gets expanded.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(2\\pi\\theta\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"2 * pi * theta\"</td><td style='padding: 3px; color: #ea580c;'>Manual Required</td><td style='padding: 3px; color: #475569;'>Pi constant written as <code>pi</code>. Consecutive named variables need <code>*</code> splits.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px;'>\\(\\overline{4i-1}\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"conjugate(4*i-1)\"</td><td style='padding: 3px; color: #64748b;'>N/A</td><td style='padding: 3px; color: #475569;'>Complex conjugate. Lowercase <code>i</code> and capital <code>I</code> both mean the imaginary unit.</td></tr>"
                "  </tbody>"
                "</table>"

                # --- SECTION 4: INVERSE TRIGONOMETRY (NEW) ---
                "<p style='margin: 12px 0 4px 0; font-weight: bold; color: #0284c7; border-bottom: 1px solid #cbd5e1;'>4. Inverse Trigonometry Exact-Value Mapping</p>"
                "<p style='padding: 0 3px 4px 3px; color: #475569; font-size: 0.7rem;'>Note: Inverse functions evaluate exact numeric angles only when given standard value ratios (e.g., passing angles like <code>acos(pi/4)</code> will remain un-simplified).</p>"
                "<table style='width: 100%; border-collapse: collapse; margin-bottom: 8px; text-align: left;'>"
                "  <thead>"
                "    <tr style='background: #f1f5f9; border-bottom: 1px solid #cbd5e1;'><th style='padding: 3px;'>Input Ratio</th><th style='padding: 3px;'>Expected Output</th><th style='padding: 3px;'>Mathematical Evaluation</th></tr>"
                "  </thead>"
                "  <tbody>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"acos(sqrt(2)/2)\"</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #16a34a;'>pi/4</td><td style='padding: 3px; color: #475569;'>Arc-cosine of \\(\\frac{\\sqrt{2}}{2}\\) yields 45°</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"asin(1/2)\"</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #16a34a;'>pi/6</td><td style='padding: 3px; color: #475569;'>Arc-sine of \\(\\frac{1}{2}\\) yields 30°</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"atan(1)\"</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #16a34a;'>pi/4</td><td style='padding: 3px; color: #475569;'>Arc-tangent of \\(1\\) yields 45°</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"acos(0)\"</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #16a34a;'>pi/2</td><td style='padding: 3px; color: #475569;'>Arc-cosine of \\(0\\) yields 90°</td></tr>"
                "  </tbody>"
                "</table>"

                # --- SECTION 5: CALCULUS ---
                "<p style='margin: 12px 0 4px 0; font-weight: bold; color: #0284c7; border-bottom: 1px solid #cbd5e1;'>5. Calculus Operations & Analysis</p>"
                "<table style='width: 100%; border-collapse: collapse; text-align: left;'>"
                "  <thead>"
                "    <tr style='background: #f1f5f9; border-bottom: 1px solid #cbd5e1;'><th style='padding: 3px;'>Calculus Operation</th><th style='padding: 3px;'>Math Notation</th><th style='padding: 3px;'>Valid Entry Example</th><th style='padding: 3px;'>Syntax Breakdown</th></tr>"
                "  </thead>"
                "  <tbody>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>Derivative</td><td style='padding: 3px;'>\\(\\frac{d}{dx}(x^3)\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"diff(x**3, x)\"</td><td style='padding: 3px; color: #475569;'>Functional style: <code>diff(expression, variable)</code>.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>Higher Derivative</td><td style='padding: 3px;'>\\(\\frac{d^2}{dx^2}(\\sin(x))\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"diff(sin(x), x, 2)\"</td><td style='padding: 3px; color: #475569;'>Appends derivative calculation order integer value at the end.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>Indefinite Integral</td><td style='padding: 3px;'>\\(\\int 5e^y dy\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"integrate(5exp(y), y)\"</td><td style='padding: 3px; color: #475569;'>Functional integration structure: <code>integrate(expression, variable)</code>.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>Definite Integral</td><td style='padding: 3px;'>\\(\\int_{0}^{1} x^2 dx\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"integrate(x**2, (x, 0, 1))\"</td><td style='padding: 3px; color: #475569;'>Bounds grouped inside tuple format: <code>(variable, lower, upper)</code>.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>Limit Execution</td><td style='padding: 3px;'>\\(\\lim_{x \\to 0} \\frac{\\sin(x)}{x}\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"limit(sin(x)/x, x, 0)\"</td><td style='padding: 3px; color: #475569;'>Evaluation target layout configuration: <code>limit(expression, variable, point)</code>.</td></tr>"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>Limit to Infinity</td><td style='padding: 3px;'>\\(\\lim_{x \\to \\infty} \\frac{1}{x}\\)</td><td style='padding: 3px; font-family: monospace; font-weight: bold; color: #0f172a;'>\"limit(1/x, x, oo)\"</td><td style='padding: 3px; color: #475569;'>Infinity evaluation boundary parameter input is designated using two lowercase letters <code>oo</code>.</td></tr>"
                "  </tbody>"
                "</table>"
                "</div>"
            )
        },
        {
            "name": "Matrix",
            "token": "matrix",
            "inputs": {
                # Configuration & Sizing (Hidden visually if linked_matrix is populated)
                "rows": {"field": "integer", "value": ["integer"], "default": 3},
                "columns": {"field": "integer", "value": ["integer"], "default": 3},
                
                # 🎯 Declared variable lists input block (Matches formula configurations perfectly)
                "variables": {"field": "string", "value": ["string"], "default": ""},
                
                # 🎯 FIXED: Replaced legacy flat "entries" with the actual incoming 2D matrix_data schema
                "matrix_data": {
                    "field": "array", 
                    "value": ["array(['string'])"], 
                    "default": [
                        ["1", "0", "0"],
                        ["0", "1", "0"],
                        ["0", "0", "1"]
                    ]
                },
                
                # Pure alternative input override
                "linked_matrix": {"field": "entity", "value": ["matrix", "or_null"], "default": None},
                
                # Operation Configuration
                "calculate": {
                    "field": "dropdown", 
                    "value": ["string_match(['leave as matrix', 'simplify', 'multiply', 'add', 'subtract', 'inversion', 'transpose', 'scalar', 'determinate'])"], 
                    "default": "leave as matrix"
                },
                
                # Dependency Inputs (Conditionally revealed based on 'calculate')
                "matrix B": {"field": "entity", "value": ["matrix", "or_null"], "default": None},
                "scalar": {"field": "double", "value": ["double"], "default": 1.0}
            },
            "output": ["matrix", "double"],
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": (
                "<div style='font-family: system-ui, sans-serif; font-size: 0.75rem; color: #1e293b; max-width: 480px; max-height: 400px; overflow-y: auto; padding-right: 4px;'>\n"
                "<p style='padding: 3px; color: #475569;'><strong>Matrix Operations:</strong> Define a local grid size, declare custom algebraic variables, or link a source Matrix. Individual cells strictly accept manual numbers, declared input variables, or clean macro token entity links. Cell formulas use the same syntax rules as the Formula entity (e.g. <code>x^2</code> ≡ <code>x**2</code>, <code>5x</code> ≡ <code>5*x</code>).</p>\n"
                "<p style='margin: 8px 0 4px 0; font-weight: bold; color: #0284c7; border-bottom: 1px solid #cbd5e1;'>Calculation Rules & Constraints</p>\n"
                "<table style='width: 100%; border-collapse: collapse; margin-bottom: 8px; text-align: left;'>\n"
                "  <thead>\n"
                "    <tr style='background: #f1f5f9; border-bottom: 1px solid #cbd5e1;'><th style='padding: 3px;'>Action</th><th style='padding: 3px;'>Output Type</th><th style='padding: 3px;'>Requirements</th></tr>\n"
                "  </thead>\n"
                "  <tbody>\n"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>leave as matrix</td><td style='padding: 3px; color: #0284c7;'>matrix</td><td style='padding: 3px; color: #475569;'>Returns current state after substitutions without simplifying.</td></tr>\n"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>simplify</td><td style='padding: 3px; color: #0284c7;'>matrix</td><td style='padding: 3px; color: #475569;'>Same as leave as matrix, then simplifies each entry after substitutions.</td></tr>\n"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>multiply (AxB)</td><td style='padding: 3px; color: #0284c7;'>matrix</td><td style='padding: 3px; color: #475569;'>Requires <strong>Matrix B</strong> link. Columns A must equal Rows B.</td></tr>\n"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>add / subtract</td><td style='padding: 3px; color: #0284c7;'>matrix</td><td style='padding: 3px; color: #475569;'>Requires <strong>Matrix B</strong> link. Must share identical dimensions.</td></tr>\n"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>inversion (A^-1)</td><td style='padding: 3px; color: #0284c7;'>matrix</td><td style='padding: 3px; color: #475569;'>Must be a square matrix with a non-zero determinant.</td></tr>\n"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>transpose</td><td style='padding: 3px; color: #0284c7;'>matrix</td><td style='padding: 3px; color: #475569;'>Flips rows and columns smoothly across main diagonal.</td></tr>\n"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>scalar (A*c)</td><td style='padding: 3px; color: #0284c7;'>matrix</td><td style='padding: 3px; color: #475569;'>Multiplies all active indices against the <strong>scalar</strong> value.</td></tr>\n"
                "    <tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding: 3px; font-weight: 500;'>determinate</td><td style='padding: 3px; color: #16a34a; font-weight: 600;'>double</td><td style='padding: 3px; color: #475569;'>Must be a square matrix. Returns a scalar value.</td></tr>\n"
                "  </tbody>\n"
                "</table>\n"
                "</div>"
            )
        },
        {
            "name": "Matrix Cell By Index",
            "token": "matrixResultByIndex",
            "inputs": {
                "matrix": {"field": "entity", "value": ["matrix"]},
                "row": {"field": "integer", "value": ["integer"], "default": 1},
                "column": {"field": "integer", "value": ["integer"], "default": 1},
                "simplify": {"field": "checkbox", "value": ["boolean"], "default": False}
            },
            "output": ["double", "integer", "formula"],
            "entity_name_list": "Dynamic Variables",
            "disabled": False,
            "note": "Extract a single cell from a linked matrix. Row and column 1 identify the upper-left cell. Output type follows the cell (integer, double, or formula). Check Simplify to run SymPy simplify on the extracted cell."
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
            "name": "Numeric Answer",
            "token": "numAnswer",
            "answer_field": True,
            "inputs": {
                "value": {"field": "double", "value": ["double", "integer"]},
                "decimal_places": {"field": "integer", "value": ["integer"], "default": 3},
                "show_rounding_note": {"field": "checkbox", "value": ["boolean"], "default": False}
            },
            "output": ["double"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "Compare student number to the correct value after rounding both to N decimal places (default 3)."
        },
        {
            "name": "Short Answer",
            "token": "shortAnswer",
            "answer_field": True,
            "inputs": {
                "value": {"field": "text", "value": ["string", "formula"]},
                "accept_rounded_decimals": {"field": "checkbox", "value": ["boolean"], "default": False}
            },
            "output": ["string"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": (
                "Trim + case-insensitive exact match first. Otherwise sympy equivalence vs the simplified key; "
                "rearrangements allowed but answers that still need simplifying are incorrect. May link a formula entity. "
                "Optional checkbox accepts numeric answers that match after rounding both sides to 3 decimal places "
                "(e.g. 8/9 and 0.88889 both round to 0.889). "
                "Expression entry: \"**\" is the same as \"^\". \"*\" is only required between two variables "
                "(e.g. x*y); it is not required when a number is followed by a variable (e.g. 2x). "
                "Formatting follows the same rules as editing a formula entity field — see that entity's info note for more detail."
            )
        },
        {
            "name": "Long Answer",
            "token": "longAnswer",
            "answer_field": True,
            "inputs": {},
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": (
                "Free-response paragraph field. Students type into a large plain text box in the preview. "
                "There is no auto-grading — the Answer Grading (Preview) panel lists this item as "
                "<strong>to be graded manually</strong> (earned 0 of the card Points until scored by hand)."
            )
        },
        {
            "name": "Array Matching (unordered)",
            "token": "arrayMatchingUnordered",
            "answer_field": True,
            "inputs": {
                "results": {"field": "text", "value": ["string", "array(['integer'])"]},
                "partial_credit": {"field": "checkbox", "value": ["boolean"], "default": False},
                "ordered": {"field": "checkbox", "value": ["boolean"], "default": False}
            },
            "output": ["string"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": (
                "Comma-separated list. Optional outer <code>[...]</code> or <code>(...)</code> around the "
                "whole answer is stripped first (so <code>[2,3]</code> and <code>(2,3)</code> become "
                "<code>2,3</code>). Split on commas <em>outside</em> parentheses/brackets. "
                "Each item is graded like a short answer: exact trim+lowercase match, else "
                "equivalent formulas (e.g. <code>7x^2</code> matches <code>7*x**2</code>). "
                "Numbers also compare after rounding to 3 decimals. "
                "Default is unordered multiset matching; check <strong>Require order</strong> for "
                "positional match (e.g. coordinates). Default scoring is all-or-nothing. "
                "May link only a primeFactors entity."
                "<br>"
                "Partial credit for partial answer: with N key items and P points, sub = P/N. "
                "Earned = max(0, matches×sub − ½×sub×(missing + extras))."
            )
        },
        {
            "name": "Answers or DNE",
            "token": "answersOrDne",
            "answer_field": True,
            "inputs": {
                "correct_is_dne": {"field": "checkbox", "value": ["boolean"], "default": False},
                "grading_mode": {
                    "field": "dropdown",
                    "value": ["string_match(['all_or_nothing', 'per_answer'])"],
                    "default": "all_or_nothing"
                },
                "show_information": {"field": "checkbox", "value": ["boolean"], "default": False},
                "information_text": {"field": "paragraph", "value": ["string"], "default": ""},
                "answers": {
                    "field": "array",
                    "value": ["array(['entity'])"],
                    "default": []
                }
            },
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": (
                "For problems that may have one or more answers <em>or</em> no solution (DNE). "
                "Check <strong>Correct answer is DNE</strong> when there is no solution "
                "(linked answer rows must be empty). Otherwise add rows that each link a "
                "<code>shortAnswer</code>, <code>arrayMatchingUnordered</code>, <code>numAnswer</code>, "
                "or <code>formula</code> key card."
                "<br>"
                "A linked <code>formula</code> must use solve method <strong>simplify</strong> with a "
                "target variable selected. Its Or/And/Eq result expands into multiple answer slots: "
                "equalities → formula/string or number (e.g. <code>-1/2</code> / <code>-0.5</code>); "
                "bound ranges → coordinates (e.g. <code>[-oo,-1]</code>, where <code>oo</code> is infinity); "
                "multi-root lists like <code>x = [-4/3, -1, 0]</code> → one point slot per value."
                "<br>"
                "In the preview, students use <strong>Add answer</strong> (formula/string, coordinates, or number) "
                "or select <strong>DNE</strong>. DNE hides once any answer row exists; it returns if all rows are deleted. "
                "Optionally check <strong>Show information icon in preview</strong> to place a hover "
                "<code>ℹ</code> next to those controls with editable instructions "
                "(math via <code>\\(...\\)</code>); when unchecked the icon is omitted entirely. "
                "Formula/string and number entries cross-match when they are the same value "
                "(e.g. <code>-1/2</code> and <code>-0.5</code>). "
                "Each linked key is a separate slot (multiset): if two keys are both "
                "<code>-0.5</code>, the student must submit two matching values "
                "(any mix of <code>-0.5</code> / <code>-1/2</code>). "
                "Extra equivalent forms beyond the number of matching keys count as wrongs."
                "<br>"
                "Grading: <strong>All or nothing</strong>, or <strong>Split points per correct answer</strong> "
                "(sub = Pts/N; earned = max(0, matches×sub − ½×sub×wrong student entries)). "
                "Student DNE when keys exist is incorrect; values when author marked DNE are incorrect."
            )
        },
        {
            "name": "Multiple Choice",
            "token": "multipleChoiceAnswer",
            "answer_field": True,
            "inputs": {
                "randomize_order": {"field": "checkbox", "value": ["boolean"], "default": True},
                "force_radio": {"field": "checkbox", "value": ["boolean"], "default": True},
                "grading_method": {
                    "field": "dropdown",
                    "value": ["string_match(['all_or_nothing', 'practical', 'proportional'])"],
                    "default": "all_or_nothing"
                },
                "options": {
                    "field": "array",
                    "value": ["array(['content'])"],
                    "default": [
                        {"id": "opt_1", "content": "", "is_correct": False},
                        {"id": "opt_2", "content": "", "is_correct": False}
                    ]
                }
            },
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": (
                "Requires at least 2 choices. Zero or more may be marked correct. "
                "If none are marked correct, students must leave all choices unchecked for full credit. "
                "Options may be typed or linked from any Dynamic Variable. "
                "Typed choices may embed entity tokens such as <code>&lt;randInt1&gt;</code>; "
                "they are replaced with the live value when rendered. "
                "Tokens may sit inside LaTeX wrappers, e.g. "
                "<code>\\(p(&lt;randInt1&gt;)=&lt;randInt2&gt;\\) is a relative minimum</code>. "
                "To render part of a typed choice as math, wrap LaTeX in "
                "<code>\\(...\\)</code>, <code>LATEX(...)</code>, or <code>latex(...)</code> "
                "(not <code>$...$</code>). Example: <code>Area is LATEX(x^2)</code> or "
                "<code>\\(\\frac{1}{2}\\)</code>. Unwrapped text stays plain."
                "<br>"
                "Randomize answer order shuffles preview display. "
                "With exactly one correct answer, Display as radio buttons (default on) forces a single selection; "
                "turn it off to mark additional correct answers. "
                "Radio mode is unavailable when zero answers are marked correct (a radio selection cannot be cleared)."
                "<br>"
                "<strong>All or nothing (default):</strong> full points only if the selected set exactly matches the correct set "
                "(including the empty set when none are marked correct); else 0."
                "<br>"
                "<strong>Practical:</strong> points_per_correct = P / num_correct; penalty_per_wrong = points_per_correct / 2; "
                "score = max(0, correct_selected × points_per_correct − wrong_selected × penalty_per_wrong). "
                "When num_correct = 0, full credit only if nothing is selected."
                "<br>"
                "<strong>Proportional:</strong> score = max(0, P × (correct_selected/num_correct − incorrect_selected/num_incorrect)). "
                "If every option is correct (num_incorrect = 0), the wrong term is treated as 0. "
                "When num_correct = 0, full credit only if nothing is selected."
            )
        },
        {
            "name": "Matrix Answer",
            "token": "matrixAnswer",
            "answer_field": True,
            "inputs": {
                "matrix": {"field": "entity", "value": ["matrix"]},
                "grading_mode": {
                    "field": "dropdown",
                    "value": ["string_match(['points_per_cell', 'whole_matrix', 'per_cell'])"],
                    "default": "points_per_cell"
                },
                "solve_cells": {
                    "field": "array",
                    "value": ["array([array(['integer'])])"],
                    "default": []
                }
            },
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": (
                "Link a matrix Dynamic Variable. Click cells on the card to mark them as "
                "<strong>provided</strong> (shown in the preview) or <strong>set to solve</strong> "
                "(student fills them in). At least one solve cell is required."
                "<br>"
                "Each blank is graded like shortAnswer: trim + lowercase exact match, then sympy "
                "equivalence that does not require further simplification."
                "<br>"
                "<strong>Points per cell (default):</strong> earned = correct × P; max = N × P "
                "(selecting this mode resets Pts to 1 so each blank is worth 1 by default)."
                "<br>"
                "<strong>All or nothing:</strong> full P only if every solve cell is correct; else 0."
                "<br>"
                "<strong>Split points per cell:</strong> earned = P × (correct / N); max = P."
            )
        },
        {
            "name": "Graph Between Points",
            "token": "graphBetweenPoints",
            "answer_field": True,
            "inputs": {
                "show_grid": {"field": "checkbox", "value": ["boolean"], "default": True},
                "let_student_draw": {"field": "checkbox", "value": ["boolean"], "default": False},
                "x-axis range": {
                    "field": "<'double'> to <'double'> by interval <'double'>",
                    "value": ["array(['double'])"],
                    "default": [-5, 5, 1]
                },
                "y-axis range": {
                    "field": "<'double'> to <'double'> by interval <'double'>",
                    "value": ["array(['double'])"],
                    "default": [-5, 5, 1]
                },
                "segments": {"field": "array", "value": ["array(['content'])"], "default": []},
                "vertices": {"field": "array", "value": ["array(['content'])"], "default": []},
                "curve_seeds": {"field": "array", "value": ["content"], "default": {}}
            },
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": (
                "Piecewise graph from segments: each row is "
                "<code>coord | divider | type | divider | coord</code>. "
                "Types: concave-down / concave-up parabola, line, cubic parabola. "
                "Dividers draw open (<code>&lt;</code>/<code>&gt;</code>), filled "
                "(<code>&lt;=</code>/<code>&gt;=</code>), a directional arrow "
                "(<code>arrow</code> / →) along the segment, or no endpoint marker (<code>none</code>). "
                "<br>"
                "Optional <strong>vertex</strong> list binds to a segment row whose x-range contains "
                "the vertex (dropdown). Vertices are never required — missing peaks are synthesized "
                "in-bounds with a stable seed. Lines take 0 vertices; parabolas at most 1; cubics at most 2 "
                "(distinct x)."
                "<br>"
                "<strong>Let student draw</strong>: check segments the student must complete "
                "(those are hidden in preview). Segments with an assigned vertex cannot be student-drawn. "
                "Grading is per student-drawn segment (default 1 Pt each)."
                "<br>"
                "Coordinates must be strictly inside the y-axis range; x may sit on x min/max but not outside."
            )
        },
        {
            "name": "Canvas",
            "token": "canvas",
            "answer_field": True,
            "inputs": {
                "source": {"field": "entity", "value": ["content"], "default": None}
            },
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 0.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": (
                "Scratch paper for freehand drawing or writing in the preview. "
                "Points default to <strong>0</strong> (not graded); if you assign Pts, scoring is manual "
                "like a long answer."
                "<br>"
                "Optional: link any Dynamic Variable or answer field as a <strong>background</strong> "
                "(graph, formula, matrix, etc.). Students draw on top; eraser / undo / erase-all "
                "never remove the linked render."
                "<br>"
                "Tools: pan, draw (default), eraser, erase all, undo; zoom and resize the board. "
                "Unlinked answers are stored as vector strokes; linked answers flatten to a cropped "
                "image that includes the background (computed for Answer Grading Preview; not saved to DB yet)."
            )
        },
        {
            "name": "Slope Field Graph",
            "token": "slopeFieldGraph",
            "answer_field": True,
            "inputs": {
                "equation": {"field": "text", "value": ["string", "formula"], "default": "dy/dx = x + y"},
                "x-axis range": {"field": "<'double'> to <'double'> by interval <'double'>", "value": ["array(['double'])"], "default": [-5, 5, 1]},
                "y-axis range": {"field": "<'double'> to <'double'> by interval <'double'>", "value": ["array(['double'])"], "default": [-5, 5, 1]},
                "selected_points": {"field": "array", "value": ["array([array(['double'])])"], "default": []},
                "show_instructions": {"field": "checkbox", "value": ["boolean"], "default": False}
            },
            "output": ["content"],
            "points": {"field": "double", "value": ["double"], "default": 1.0},
            "entity_name_list": "Answer Input Fields",
            "disabled": False,
            "note": "Slope field answer: teacher marks lattice points; students align slope ticks on those points. Optional Show instructions checkbox appends brief how-to text under the preview graph."
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