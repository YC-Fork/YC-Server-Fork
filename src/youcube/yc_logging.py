#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Everything logging related
"""

# Built-in modules
from datetime import datetime
from logging import (
    CRITICAL,
    DEBUG,
    ERROR,
    INFO,
    WARNING,
    Formatter,
    Logger,
    LogRecord,
    StreamHandler,
    FileHandler,
    getLogger,
)
from os import getenv, mkdir, environ
from os.path import abspath, dirname, exists, join

# local modules
from yc_colours import RESET, Foreground

LOGLEVEL = getenv("LOGLEVEL") or DEBUG
NO_COLOR = getenv("NO_COLOR") or False
# Don't call "getLogger" every time we need the logger
logger = getLogger("__main__")

ROOT_DIR = dirname(dirname(dirname(abspath(__file__))))
LOGS_DIR = join(ROOT_DIR, "logs")


class ColordFormatter(Formatter):
    """Logging colored formatter, adapted from https://stackoverflow.com/a/56944256/3638629"""

    # noinspection SpellCheckingInspection
    def __init__(self, fmt=None, datefmt="%H:%M:%S") -> None:
        super().__init__()
        self.fmt = fmt
        self.datefmt = datefmt
        self.formats = {
            DEBUG: f"{Foreground.BRIGHT_BLACK}{self.fmt}{RESET}",
            INFO: f"{Foreground.BRIGHT_WHITE}{self.fmt}{RESET}",
            WARNING: f"{Foreground.BRIGHT_YELLOW}{self.fmt}{RESET}",
            ERROR: f"{Foreground.BRIGHT_RED}{self.fmt}{RESET}",
            CRITICAL: f"{Foreground.RED}{self.fmt}{RESET}",
        }

    def format(self, record: LogRecord) -> str:
        log_fmt = self.formats.get(record.levelno)
        formatter = Formatter(log_fmt, datefmt=self.datefmt)
        return formatter.format(record)


class YTDLPLogger:
    """https://github.com/yt-dlp/yt-dlp#adding-logger-and-progress-hook"""

    def __init__(self) -> None:
        if NO_COLOR:
            self.prefix = "[yt-dlp] "
        else:
            self.prefix = f"{Foreground.BRIGHT_MAGENTA}[yt-dlp]{RESET} "

    def _should_ignore(self, msg: str) -> bool:
        # Ignore download progress spam (e.g. '[download] 12.4% of ...')
        if msg.startswith("[download] ") and "%" in msg and "100%" not in msg and "100.0%" not in msg:
            return True
            
        # Ignore SABR format skip warnings and expired cookie warnings
        ignore_keywords = [
            "SABR streaming",
            "missing a URL",
            "formats have been skipped",
            "forcing SABR",
            "cookies are no longer valid",
            "rotated in the browser",
        ]
        if any(kw in msg for kw in ignore_keywords):
            return True
            
        return False

    def debug(self, msg: str) -> None:
        """Pass msg to the main logger"""
        if self._should_ignore(msg):
            return

        # For compatibility with youtube-dl, both debug and info are passed into debug
        # You can distinguish them by the prefix '[debug] '
        if msg.startswith("[debug] "):
            logger.debug("%s%s", self.prefix, msg)
        else:
            self.info(msg)

    def info(self, msg: str) -> None:
        """Pass msg to the main logger"""
        if self._should_ignore(msg):
            return
        logger.debug("%s%s", self.prefix, msg)

    def warning(self, msg: str) -> None:
        """Pass msg to the main logger"""
        if self._should_ignore(msg):
            return
        logger.warning("%s%s", self.prefix, msg)

    def error(self, msg: str) -> None:
        """Pass msg to the main logger"""
        logger.error("%s%s", self.prefix, msg)


def setup_logging() -> Logger:
    """Sets the main logger up"""
    if logger.handlers:
        return logger

    # Always set root logger to DEBUG to process all logs
    logger.setLevel(DEBUG)

    # 1. Console Logging (respects LOGLEVEL environment variable)
    if NO_COLOR:
        console_formatter = Formatter(
            fmt="[%(asctime)s %(levelname)s] [YC-Fork-Server] %(message)s"
        )
    else:
        console_formatter = ColordFormatter(
            fmt=f"[%(asctime)s %(levelname)s] {Foreground.BRIGHT_WHITE}[YC-Fork-Server]{RESET} %(message)s"
        )

    logging_handler = StreamHandler()
    logging_handler.setLevel(LOGLEVEL)
    logging_handler.setFormatter(console_formatter)
    logger.addHandler(logging_handler)

    # 2. File Logging (always logs everything to logs/YYYY-MM-DD_HH-MM-SS.txt)
    if not exists(LOGS_DIR):
        try:
            mkdir(LOGS_DIR)
        except OSError:
            pass

    if exists(LOGS_DIR):
        log_file_path = getenv("YC_LOG_FILE")
        if not log_file_path:
            start_time_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            log_file_path = join(LOGS_DIR, f"{start_time_str}.txt")
            environ["YC_LOG_FILE"] = log_file_path

        file_formatter = Formatter(
            fmt="[%(asctime)s %(levelname)s] [YC-Fork-Server] %(message)s"
        )

        file_handler = FileHandler(log_file_path, encoding="utf-8")
        file_handler.setLevel(DEBUG)  # Always log everything to file
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger
