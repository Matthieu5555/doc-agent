"""Security validators for input validation."""

import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Tuple, Optional


class RepositoryValidator:
    """Validates and sanitizes repository URLs."""

    ALLOWED_HOSTS = ['github.com', 'gitlab.com', 'bitbucket.org']

    def validate_repo_url(self, repo_url: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validate repository URL for security.

        Prevents:
        - Path traversal attacks
        - Non-HTTPS protocols
        - Untrusted repository hosts
        - Malformed URLs

        Args:
            repo_url: Repository URL to validate

        Returns:
            Tuple of (is_valid, error_message, sanitized_url)
            - is_valid: True if URL passes all checks
            - error_message: Human-readable error (empty string if valid)
            - sanitized_url: Cleaned URL (None if invalid)
        """
        if not repo_url or len(repo_url) > 500:
            return False, "Invalid URL length", None

        try:
            parsed = urlparse(repo_url)
        except Exception as e:
            return False, f"Invalid URL format: {e}", None

        # Must use HTTPS
        if parsed.scheme != 'https':
            return False, "Only HTTPS URLs allowed", None

        # Host must be whitelisted
        if parsed.netloc not in self.ALLOWED_HOSTS:
            return False, f"Host not whitelisted. Allowed: {self.ALLOWED_HOSTS}", None

        # Check for path traversal in URL
        path_parts = parsed.path.strip('/').split('/')
        if len(path_parts) < 2:
            return False, "Invalid repository path (expected owner/repo)", None

        for part in path_parts[:2]:  # Only validate owner/repo parts
            if part in ['..', '.', ''] or not re.match(r'^[\w\-\.]+$', part):
                return False, "Invalid path component", None

        # Reconstruct sanitized URL (owner/repo only)
        sanitized = f"https://{parsed.netloc}/{path_parts[0]}/{path_parts[1]}"
        return True, "", sanitized

    @staticmethod
    def validate_local_path(path_str: str) -> Tuple[bool, str, Optional[str]]:
        """Validate a local repository path.

        Args:
            path_str: Filesystem path to validate

        Returns:
            Tuple of (is_valid, error_message, resolved_path)
        """
        path = Path(path_str)
        if not path.exists():
            return False, f"Path does not exist: {path_str}", None
        if not path.is_dir():
            return False, f"Path is not a directory: {path_str}", None
        if not (path / ".git").exists():
            return False, f"Path is not a git repository (no .git directory): {path_str}", None
        return True, "", str(path.resolve())


class PathValidator:
    """Validates filesystem paths to prevent traversal attacks."""

    @staticmethod
    def validate_collection(collection: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validate collection parameter against path traversal.

        Prevents:
        - Path traversal (../)
        - Absolute paths (/)
        - Special characters
        - Excessive length

        Args:
            collection: Collection path to validate

        Returns:
            Tuple of (is_valid, error_message, sanitized_path)
        """
        # Empty collection is valid (means root)
        if not collection:
            return True, "", ""

        if len(collection) > 200:
            return False, "Collection name too long", None

        # Only allow alphanumeric, dash, underscore, slash
        if not re.match(r'^[\w\-/]+$', collection):
            return False, "Invalid characters in collection", None

        # Check for path traversal
        if '..' in collection or collection.startswith('/'):
            return False, "Path traversal detected", None

        # Normalize: remove empty parts and dots
        parts = [p for p in collection.split('/') if p and p != '.']
        sanitized = '/'.join(parts)

        return True, "", sanitized
