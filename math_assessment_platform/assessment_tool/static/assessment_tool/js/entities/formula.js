// entities/formula.js

/**
 * Standardized entity module for processing mathematical formulas.
 * 
 * @param {Object} contextData - Data passed from the main workspace controller (e.g., raw LaTeX, configuration variables).
 * @returns {Promise<Object>} The structured data required to render or evaluate the formula.
 */
export async function processEntity(contextData) {
    // 1. Extract necessary properties from the context provided by the main controller
    const { expression, format = 'latex', isDisplayMode = false } = contextData || {};

    if (!expression) {
        console.warn('Formula entity requires an expression in the contextData.');
        return { error: 'Missing expression data' };
    }

    try {
        // 2. Execute formula-specific logic for problem creation
        // Examples: validating syntax, calculating standard forms, or generating MathJax/KaTeX compatible output
        
        const cssClass = isDisplayMode ? 'formula-display' : 'formula-inline';
        
        // 3. Construct the standardized response object for the global controller
        const entityData = {
            entityType: 'formula',
            originalExpression: expression,
            format: format,
            renderReadyHtml: `<span class="${cssClass}">${expression}</span>`,
            metadata: {
                processedAt: Date.now(),
                requiresMathEngine: true
            }
        };

        return entityData;

    } catch (error) {
        console.error('Failed to process formula entity:', error);
        return { 
            error: 'Processing failed', 
            details: error.message 
        };
    }
}