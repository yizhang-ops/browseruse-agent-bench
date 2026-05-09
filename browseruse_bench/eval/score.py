"""Score extraction and pass/fail derivation for benchmark evaluators."""
from __future__ import annotations

import re


def extract_score_from_response(response: str) -> int:
    """Extract numerical score from evaluation response.

    Args:
        response: Evaluation response text

    Returns:
        Extracted score (0 if not found)
    """
    # Try to find "总分: XX" or "Total Score: XX" or "Score: XX"
    # Enumerate possible formats here, add more if new formats are encountered
    # Note: Support formats with calculation process, e.g. "最终得分：**60 - 55 = 5分**"
    patterns = [
        r'###\s*最终得分[：:]\s*\*?\*?[^*=\n]{0,100}=\s*\*?\*?(-?\d+)\s*分?\*?\*?',
        r'###\s*总分[：:]\s*\*?\*?[^*=\n]{0,100}=\s*\*?\*?(-?\d+)\s*分?\*?\*?',
        r'###\s*(?:Total|Final)\s+Score[：:][^=\n]{0,100}=\s*\*?\*?\s*(-?\d+)\s*(?:points?)?\*?\*?',
        r'###\s*(?:Total|Final)\s+Score[^0-9\n]{0,50}(\d+)\s*/\s*\d+',
        r'###\s*最终得分[：:]\s*\*?\*?(\d+)\s*分?\*?\*?',
        r'###\s*总分[：:]\s*\*?\*?(\d+)\s*分?\*?\*?',
        r'###\s*(?:Total|Final)\s+Score[：:][^\d\n]{0,30}(\d+)\s*(?:points?)?',
        r'###\s*Score[：:]\s*\*?\*?(\d+)\s*(?:points?)?\*?\*?',
        r'###\s*最终得分[：:]\s*(\d+)',
        # === Chinese format (with calculation) ===
        # Match formats with calculation: 最终得分：**60 - 55 = 5分** or 最终得分：60 - 55 = 5分
        # Extract the number after equals sign (the result), supports negative numbers
        r'最终得分[：:]\s*\*?\*?[^*=\n]{0,100}=\s*\*?\*?(-?\d+)\s*分?\*?\*?',
        r'总分[：:]\s*\*?\*?[^*=\n]{0,100}=\s*\*?\*?(-?\d+)\s*分?\*?\*?',

        # === English format (with calculation) ===
        # Match: Total Score: **A - B = C points** or Final Score: **A - B = C points**
        # Extract the number after equals sign (the result), supports negative numbers
        # Limit: max 100 chars before '=', no newline crossing
        r'(?:Total|Final)\s+Score[：:][^=\n]{0,100}=\s*\*?\*?\s*(-?\d+)\s*(?:points?)?\*?\*?',

        # === English format (fraction with slash) ===
        # Match: **Final Score:** **70/100** or Final Score: 60 / 100 (extract first number)
        # Limit: max 50 chars between Score and slash
        r'(?:Total|Final)\s+Score[^0-9\n]{0,50}(\d+)\s*/\s*\d+',

        # === Chinese format (without calculation) ===
        # Match formats with asterisks: 最终得分：**5分** or 最终得分：**100分**
        r'最终得分[：:]\s*\*?\*?(\d+)\s*分?\*?\*?',
        # Match total score (with asterisks): 总分: **100分** or 总分: 100分
        r'总分[：:]\s*\*?\*?(\d+)\s*分?\*?\*?',

        # === English format (normal format with limited range) ===
        # Match: **Final Score:** **100 points** or - **Final Score:** 20 points
        # Limit: max 30 chars between colon and number, no newline crossing
        r'(?:Total|Final)\s+Score[：:][^\d\n]{0,30}(\d+)\s*(?:points?)?',

        # === General Score format ===
        r'Score[：:]\s*\*?\*?(\d+)\s*(?:points?)?\*?\*?',

        # === Simple format (fallback) ===
        r'最终得分[：:]\s*(\d+)',
    ]

    # Special handling: check for direct negative number format first (return 0)
    # Examples: Total Score: **-40 points** or 总分: **-50分**
    # Must be placed first to avoid matching the number part by normal patterns
    negative_patterns = [
        r'(?:总分|最终得分)[：:][^\d\n]*-\d+',
        r'(?:Total|Final)\s+Score[：:][^\d\n]*-\d+',
    ]
    for pattern in negative_patterns:
        if re.search(pattern, response, re.IGNORECASE):
            return 0

    # Normal pattern matching
    for pattern in patterns:
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            score = int(match.group(1))
            # Return 0 for negative numbers (for negatives after equals, e.g. = -35)
            return max(0, score)

    # If not found, return 0
    return 0


def calculate_success(score: int, threshold: int = 60) -> bool:
    """Determine if task is successful based on score threshold.

    Args:
        score: Task score
        threshold: Success threshold (default: 60)

    Returns:
        True if score >= threshold
    """
    return score >= threshold
