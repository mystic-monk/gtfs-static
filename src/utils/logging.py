"""
Logging utilities for the Irish GTFS Analytics Platform.
"""
import logging
import logging.handlers
from pathlib import Path
from typing import Optional
from src.config import settings


def setup_logging(
    name: str,
    log_file: Optional[Path] = None,
    level: str = "INFO",
) -> logging.Logger:
    """
    Setup and return a logger instance.
    
    Args:
        name: Logger name (typically __name__)
        log_file: Optional file path for file handler
        level: Logging level
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Format
    formatter = logging.Formatter(settings.LOG_FORMAT)
    console_handler.setFormatter(formatter)
    
    # Add console handler if not already present
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) 
               for h in logger.handlers):
        logger.addHandler(console_handler)

    # File handler
    if log_file is None:
        log_file = settings.LOG_FILE
    
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
    )
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    file_handler.setFormatter(formatter)
    
    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        logger.addHandler(file_handler)

    return logger


def log_layer_transition(
    logger: logging.Logger,
    from_layer: str,
    to_layer: str,
    total_records: int,
    processed_records: int,
    failed_records: int = 0,
    passed_records: int = 0,
) -> None:
    """
    Log a layer transition with statistics.
    
    Args:
        logger: Logger instance
        from_layer: Source layer name
        to_layer: Destination layer name
        total_records: Total records processed
        processed_records: Records successfully processed
        failed_records: Records that failed validation
        passed_records: Records that passed validation
    """
    pct_processed = (processed_records / total_records * 100) if total_records > 0 else 0
    
    msg = (
        f"Layer transition: {from_layer} -> {to_layer} | "
        f"Total: {total_records}, Processed: {processed_records} ({pct_processed:.1f}%)"
    )
    
    if failed_records > 0:
        msg += f", Failed: {failed_records}"
    
    if passed_records > 0:
        msg += f", Passed: {passed_records}"
    
    logger.info(msg)
