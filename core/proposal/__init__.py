"""Proposal generation package for the Freelance Agent system."""

from core.proposal.proposal_builder import ProposalBuilder
from core.proposal.proposal_generator import ProposalGenerator
from core.proposal.proposal_optimizer import ProposalOptimizer

__all__ = [
    "ProposalBuilder",
    "ProposalGenerator",
    "ProposalOptimizer",
]
