"""Prompt injection detection and mitigation."""

import re
from typing import List


class PromptInjectionDetector:
    """Detects and mitigates prompt injection attempts in user input."""

    INJECTION_PATTERNS = [
        r'ignore\s+(previous|above|all)\s+instructions',
        r'disregard\s+',
        r'forget\s+everything',
        r'new\s+instructions?:',
        r'system\s*:',
        r'you\s+are\s+now',
        r'roleplay\s+as',
        r'pretend\s+you',
    ]

    def sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename to prevent prompt injection.

        Removes control characters, limits length, and replaces
        suspicious patterns that could manipulate AI behavior.

        Args:
            filename: Raw filename from repository or user input

        Returns:
            Sanitized filename safe for use in prompts
        """
        # Remove control characters (including newlines, tabs, null bytes)
        sanitized = re.sub(r'[\n\r\t\x00-\x1f\x7f-\x9f]', '', filename)

        # Limit length (filesystem limit is 255, but we're more conservative)
        if len(sanitized) > 255:
            sanitized = sanitized[:255]

        # Check for injection patterns
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, sanitized, re.IGNORECASE):
                # Replace suspicious content with underscores
                sanitized = re.sub(r'[^\w\.\-/]', '_', sanitized)
                break

        return sanitized

    def detect_injection(self, text: str) -> bool:
        """
        Detect if text contains potential prompt injection.

        Args:
            text: Text to analyze

        Returns:
            True if injection patterns detected
        """
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
