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
    """
    Service for capturing anonymized telemetry data.

    If the environment variable `ANONYMIZED_TELEMETRY=False`, anonymized telemetry will be disabled.
    """
    
    USER_ID_PATH = str(Path.home() / '.cache' / 'browser_use' / 'telemetry_user_id')
    PROJECT_API_KEY = 'phc_[REDACTED]' # API key was seen in bytecode
    HOST = 'https://eu.i.posthog.com'
    UNKNOWN_USER_ID = 'UNKNOWN'
    
    def __init__(self):
        # Check if telemetry is disabled via environment variable
        telemetry_disabled = os.getenv('ANONYMIZED_TELEMETRY', 'true').lower() == 'false'
        
        # Set debug logging based on environment variable
        self.debug_logging = os.getenv('BROWSER_USE_LOGGING_LEVEL', 'info').lower() == 'debug'
        
        if telemetry_disabled:
            self._posthog_client = None
        else:
            logging.info('Anonymized telemetry enabled. See https://docs.browser-use.com/development/telemetry for more information.')
            self._posthog_client = Posthog(
                project_api_key=self.PROJECT_API_KEY,
                host=self.HOST,
                disable_geoip=False
            )
            
            # Disable PostHog's own logging if we're not in debug mode
            if not self.debug_logging:
                posthog_logger = logging.getLogger('posthog')
                posthog_logger.disabled = True
        
        # Log if telemetry is disabled
        if self._posthog_client is None:
            logger.debug('Telemetry disabled')
        
        # Initialize user ID 
        self._curr_user_id = None
    
    def capture(self, event: BaseTelemetryEvent) -> None:
        """
        Capture a telemetry event
        """
        if self._posthog_client is None:
            return
        
        if self.debug_logging:
            logger.debug(f'Telemetry event: {event.name} {event.properties}')
        
        self._direct_capture(event)
    
    def _direct_capture(self, event: BaseTelemetryEvent) -> None:
        """
        Should not be thread blocking because posthog magically handles it
        """
        if self._posthog_client is None:
            return
        
        try:
            self._posthog_client.capture(
                self.user_id,
                event.name,
                {**event.properties, **POSTHOG_EVENT_SETTINGS}
            )
        except Exception as e:
            logger.error(f'Failed to send telemetry event {event.name}: {e}')
    
    @property
    def user_id(self) -> str:
        """
        Get or create a unique user ID for telemetry
        """
        if self._curr_user_id:
            return self._curr_user_id
            
        try:
            # Check if user ID file exists
            if not os.path.exists(self.USER_ID_PATH):
                # Create directory if it doesn't exist
                os.makedirs(os.path.dirname(self.USER_ID_PATH), exist_ok=True)
                
                # Generate and save a new user ID
                with open(self.USER_ID_PATH, 'w') as f:
                    user_id = str(uuid.uuid4())
                    f.write(user_id)
                
                self._curr_user_id = user_id
            else:
                # Read existing user ID
                with open(self.USER_ID_PATH, 'r') as f:
                    self._curr_user_id = f.read()
        except Exception:
            # Use fallback user ID if any error occurs
            self._curr_user_id = self.UNKNOWN_USER_ID
            
        return self._curr_user_id