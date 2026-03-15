"""Platform-specific auto-application handlers."""

from core.auto_apply.platform_apply_handlers.linkedin_apply import LinkedInApplyHandler
from core.auto_apply.platform_apply_handlers.remoteok_apply import RemoteOKApplyHandler
from core.auto_apply.platform_apply_handlers.upwork_apply import UpworkApplyHandler

__all__ = [
    "LinkedInApplyHandler",
    "RemoteOKApplyHandler",
    "UpworkApplyHandler",
]
