import os
import uvicorn
from app.logger import logger
from app.server import app

if __name__ == '__main__':
    port = 8330
    logger.info(f'''Starting tty proxy on port {port}''')
    logger.info(f'''CHROME_INSTANCE_PATH env is {os.getenv('CHROME_INSTANCE_PATH', 'empty')}''')
    uvicorn.run(app, host = '0.0.0.0', port = port, log_level = 'info')
