"""Post-processes generated proposals to enforce clean plain-text formatting."""

from __future__ import annotations

import re


class ProposalOptimizer:
    """Applies deterministic cleanup rules to generated proposals.

    This optimizer does not call external services. It keeps output readable,
    plain-text-only, and free from common AI formatting artifacts.
    """

    def optimize_proposal(self, proposal_text: str) -> str:
        """Clean and normalize proposal text for consistent output quality.

        Cleanup rules:
        - Remove markdown-like symbols (e.g., *, **, --).
        - Remove leading list markers such as '-', '*', or numbered prefixes.
        - Collapse excessive whitespace and blank lines.

        Args:
            proposal_text: Raw proposal text from the generator.

        Returns:
            Optimized plain-text proposal.
        """

        text = proposal_text.strip()

        # Remove markdown symbols that make output look auto-generated.
        text = text.replace("**", "")
        text = text.replace("*", "")
        text = text.replace("--", "-")

        # Remove line-leading bullets / numbered list prefixes.
        text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
        text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)

        # Normalize spacing and cap repeated blank lines.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()
