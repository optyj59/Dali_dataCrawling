import logging
import os
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs')
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def get_timestamped_log_filename():
    """Generates a timestamped log filename in the LOG_DIR."""
    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join(LOG_DIR, f"run_{run_timestamp}.log")

def setup_logger(name, log_file, level=logging.INFO):
    """
    Sets up a logger to write to a specific file.
    Creates a file handler for the given log file.
    """
    # Create a logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding handlers if they already exist
    if any(isinstance(h, logging.FileHandler) and h.baseFilename == log_file for h in logger.handlers):
        return logger

    # Create a file handler
    handler = logging.FileHandler(log_file, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(processName)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # Add the handler to the logger
    logger.addHandler(handler)
    
    # Also log to console for main process
    if name == 'main':
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
             logger.addHandler(stream_handler)

    return logger
