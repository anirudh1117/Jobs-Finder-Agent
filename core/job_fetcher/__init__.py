"""Job fetching package for the Freelance Agent system."""

from core.job_fetcher.base_fetcher import BaseJobFetcher
from core.job_fetcher.linkedin_fetcher import LinkedInFetcher
from core.job_fetcher.mercor_fetcher import MercorFetcher
from core.job_fetcher.outlier_fetcher import OutlierFetcher
from core.job_fetcher.remoteok_fetcher import RemoteOKFetcher
from core.job_fetcher.upwork_fetcher import UpworkFetcher

__all__ = [
    "BaseJobFetcher",
    "LinkedInFetcher",
    "MercorFetcher",
    "OutlierFetcher",
    "RemoteOKFetcher",
    "UpworkFetcher",
]
