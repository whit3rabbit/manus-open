import argparse
import os
import sys
import uvicorn

from app.logger import logger
from app.server import app

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Start the terminal and browser proxy server")
    
    parser.add_argument(
        "--port", 
        type=int, 
        default=8330, 
        help="Port to run the server on (default: 8330)"
    )
    
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host interface to bind to (default: 0.0.0.0)"
    )
    
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
        help="Logging level (default: info)"
    )
    
    parser.add_argument(
        "--chrome-path",
        type=str,
        default=None,
        help="Path to Chrome browser instance"
    )
    
    return parser.parse_args()

if __name__ == '__main__':
    # Parse command-line arguments
    args = parse_args()
    
    # Set Chrome instance path if provided
    if args.chrome_path:
        os.environ['CHROME_INSTANCE_PATH'] = args.chrome_path
        
    # Log startup information
    logger.info(f"Starting server on {args.host}:{args.port}")
    logger.info(f"Log level: {args.log_level}")
    logger.info(f"CHROME_INSTANCE_PATH env is {os.getenv('CHROME_INSTANCE_PATH', 'empty')}")
    
    # Start the server
    try:
        uvicorn.run(
            app, 
            host=args.host, 
            port=args.port, 
            log_level=args.log_level
        )
    except Exception as e:
        logger.critical(f"Failed to start server: {e}")
        sys.exit(1)