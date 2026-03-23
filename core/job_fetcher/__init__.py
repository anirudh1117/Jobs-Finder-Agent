"""Job fetching package for the Freelance Agent system."""

from core.job_fetcher.base_fetcher import BaseJobFetcher
from core.job_fetcher.google_jobs_fetcher import GoogleJobsFetcher
from core.job_fetcher.linkedin_fetcher import LinkedInFetcher
from core.job_fetcher.mercor_fetcher import MercorFetcher
from core.job_fetcher.outlier_fetcher import OutlierFetcher
from core.job_fetcher.freelancer_fetcher import FreelancerFetcher
from core.job_fetcher.remoteok_fetcher import RemoteOKFetcher
from core.job_fetcher.remotive_fetcher import RemotiveFetcher
from core.job_fetcher.upwork_fetcher import UpworkFetcher
from core.job_fetcher.weworkremotely_fetcher import WeWorkRemotelyFetcher

__all__ = [
    "BaseJobFetcher",
    "GoogleJobsFetcher",
    "LinkedInFetcher",
    "MercorFetcher",
    "OutlierFetcher",
    "FreelancerFetcher",
    "RemoteOKFetcher",
    "RemotiveFetcher",
    "UpworkFetcher",
    "WeWorkRemotelyFetcher",
]
