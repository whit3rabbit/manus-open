import logging
import os
import uuid
from pathlib import Path
from dotenv import load_dotenv
from posthog import Posthog
from browser_use.telemetry.views import BaseTelemetryEvent
from browser_use.utils import singleton

load_dotenv()
logger = logging.getLogger(__name__)

POSTHOG_EVENT_SETTINGS = {
    'process_person_profile': True
}

@singleton
class ProductTelemetry:
    pass