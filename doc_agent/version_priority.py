"""
Version Priority Engine for intelligent documentation regeneration.

Implements decision logic to respect human edits while keeping
AI-generated documentation fresh.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from doc_agent.api_client import DocumentAPIClient
from doc_agent.repo_monitor import has_significant_changes, get_repo_unchanged_status


class VersionPriorityEngine:
    """
    Decision engine for determining when to regenerate documentation.

    Rules:
    1. No existing doc → GENERATE
    2. Human edit < 7 days → SKIP (respect fresh human edits)
    3. Human edit >= 7 days, repo unchanged → SKIP
    4. Human edit >= 7 days, minor changes (< 5 commits) → SKIP
    5. Human edit >= 7 days, major changes (>= 5 commits) → REGENERATE
    6. AI doc < 30 days, repo unchanged → SKIP
    7. AI doc >= 30 days OR repo changed → REGENERATE
    """

    def __init__(self, api_client: DocumentAPIClient, repo_path: Path):
        """
        Initialize priority engine.

        Args:
            api_client: API client for fetching document data
            repo_path: Path to the git repository
        """
        self.api_client = api_client
        self.repo_path = repo_path
        self.human_recent_threshold_days = 7
        self.ai_stale_threshold_days = 30
        self.commit_threshold = 5

    def should_regenerate(
        self,
        doc_id: str,
        current_commit_sha: str
    ) -> tuple[bool, str]:
        """
        Determine if documentation should be regenerated.

        Args:
            doc_id: Document ID
            current_commit_sha: Current commit SHA of the repository

        Returns:
            Tuple of (should_regenerate: bool, reason: str)
        """
        print(f"\n[VersionPriority] Checking if regeneration needed...")
        print(f"   Doc ID: {doc_id}")
        print(f"   Current commit: {current_commit_sha[:8]}")

        # Rule 1: Check if document exists
        existing_doc = self.api_client.get_document(doc_id)

        if not existing_doc:
            return True, "No existing document found"

        print(f"   Found existing document")

        # Get version history
        versions = self.api_client.get_document_versions(doc_id)

        if not versions:
            # Document exists but no version history - regenerate to create version
            return True, "Document exists but no version history"

        # Get latest version
        latest_version = versions[0]  # Assuming sorted by created_at desc
        author_type = latest_version.get("author_type", "ai")
        created_at_str = latest_version.get("created_at")

        print(f"   Latest version author: {author_type}")
        print(f"   Latest version created: {created_at_str}")

        # Parse creation timestamp
        try:
            created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            age_days = (datetime.now(created_at.tzinfo) - created_at).days
        except (ValueError, AttributeError) as e:
            print(f"[VersionPriority] Warning: Could not parse timestamp: {e}")
            # Can't determine age - regenerate to be safe
            return True, "Cannot determine document age, regenerating to be safe"

        print(f"   Document age: {age_days} days")

        # Get last commit SHA from metadata
        author_metadata = latest_version.get("author_metadata", {})
        last_commit_sha = author_metadata.get("repo_commit_sha", "unknown")

        print(f"   Last documented commit: {last_commit_sha[:8] if last_commit_sha != 'unknown' else 'unknown'}")

        # Check repo changes
        if last_commit_sha != "unknown":
            is_unchanged, change_reason = get_repo_unchanged_status(
                self.repo_path,
                last_commit_sha
            )
            print(f"   Repo status: {change_reason}")
        else:
            is_unchanged = False
            change_reason = "Previous commit SHA unknown, assuming changes"
            print(f"   Repo status: {change_reason}")

        # Apply decision rules based on author type
        if author_type == "human":
            return self._evaluate_human_version(
                age_days,
                is_unchanged,
                last_commit_sha
            )
        else:  # author_type == "ai" or unknown
            return self._evaluate_ai_version(
                age_days,
                is_unchanged,
                last_commit_sha
            )

    def _evaluate_human_version(
        self,
        age_days: int,
        is_unchanged: bool,
        last_commit_sha: str
    ) -> tuple[bool, str]:
        """
        Evaluate whether to regenerate a human-authored version.

        Args:
            age_days: Age of the document in days
            is_unchanged: Whether repository is unchanged
            last_commit_sha: Last documented commit SHA

        Returns:
            Tuple of (should_regenerate: bool, reason: str)
        """
        # Rule 2: Human edit < 7 days → SKIP
        if age_days < self.human_recent_threshold_days:
            return False, f"Recent human edit ({age_days} days old), preserving their work"

        # Human edit >= 7 days
        # Rule 3: Repo unchanged → SKIP
        if is_unchanged:
            return False, f"Human edit is {age_days} days old but repository unchanged, no need to regenerate"

        # Repo has changed - check if changes are significant
        if last_commit_sha == "unknown":
            # Can't determine significance - regenerate with warning
            return True, f"Human edit is {age_days} days old and repository changed (commit SHA unknown), regenerating with note for human review"

        # Rule 4 & 5: Check commit count
        is_significant = has_significant_changes(
            self.repo_path,
            last_commit_sha,
            self.commit_threshold
        )

        if is_significant:
            # Rule 5: Major changes → REGENERATE
            return True, f"Human edit is {age_days} days old and repository has significant changes, regenerating with note for human review"
        else:
            # Rule 4: Minor changes → SKIP
            return False, f"Human edit is {age_days} days old but repository changes are minor, preserving human version"

    def _evaluate_ai_version(
        self,
        age_days: int,
        is_unchanged: bool,
        last_commit_sha: str
    ) -> tuple[bool, str]:
        """
        Evaluate whether to regenerate an AI-authored version.

        Args:
            age_days: Age of the document in days
            is_unchanged: Whether repository is unchanged
            last_commit_sha: Last documented commit SHA

        Returns:
            Tuple of (should_regenerate: bool, reason: str)
        """
        # Rule 6: AI doc < 30 days AND repo unchanged → SKIP
        if age_days < self.ai_stale_threshold_days and is_unchanged:
            return False, f"AI documentation is fresh ({age_days} days old) and repository unchanged"

        # Rule 7: AI doc >= 30 days OR repo changed → REGENERATE
        if age_days >= self.ai_stale_threshold_days:
            return True, f"AI documentation is stale ({age_days} days old), regenerating"

        # Repo must have changed (since we already checked unchanged above)
        return True, f"Repository changed since last AI generation ({age_days} days ago), updating documentation"
