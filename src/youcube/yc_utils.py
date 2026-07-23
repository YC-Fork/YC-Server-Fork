#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Utils for string manipulation, data management etc.
"""

# Built-in modules
import json
from json import JSONDecodeError
from logging import getLogger
from os import mkdir, walk
from os.path import abspath, dirname, exists, getsize, join
from re import RegexFlag
from re import compile as re_compile
from typing import Tuple

VERSION = "2.00.001"

def is_compatible_version(v1: str, v2: str) -> bool:
    """Checks if Major and Minor version numbers match between v1 and v2 (e.g. 2 and 00 for '2.00.001')."""
    if not v1 or not v2:
        return False
    try:
        p1 = [int(x) for x in str(v1).split(".")[:2]]
        p2 = [int(x) for x in str(v2).split(".")[:2]]
        if len(p1) == 2 and len(p2) == 2:
            return p1[0] == p2[0] and p1[1] == p2[1]
    except Exception:
        pass
    return v1 == v2

def remove_whitespace(string: str) -> str:
    """
    Removes all Spaces / Whitespace from a string
    """
    return string.replace(" ", "")


# Only compile "ansi_escape_codes" once
ansi_escape_codes = re_compile(
    r"""
    \x1B  # ESC
    (?:   # 7-bit C1 Fe (except CSI)
        [@-Z\\-_]
    |     # or [ for CSI, followed by a control sequence
        \[
        [0-?]*  # Parameter bytes
        [ -/]*  # Intermediate bytes
        [@-~]   # Final byte
    )
""",
    RegexFlag.VERBOSE,
)


def remove_ansi_escape_codes(text: str) -> str:
    """
    Remove all Ansi Escape codes
    (7-bit C1 ANSI sequences)
    """
    return ansi_escape_codes.sub("", text)


def cap_width(width: int) -> int:
    """Caps the width"""
    return min(width, 328)


def cap_height(height: int) -> int:
    """Caps the height"""
    return min(height, 243)


def cap_width_and_height(width: int, height: int) -> Tuple[int, int]:
    """Caps the width and height"""
    return cap_width(width), cap_height(height)


VIDEO_FORMAT = "32vid"
AUDIO_FORMAT = "dfpwm"
ROOT_DIR = dirname(dirname(dirname(abspath(__file__))))
CONFIG_PATH = join(ROOT_DIR, "config.json")
DATA_FOLDER = join(ROOT_DIR, "data")
RAW_FOLDER = join(DATA_FOLDER, "raw")
CONVERTED_AUDIO_FOLDER = join(DATA_FOLDER, "converted-audio")
CONVERTED_VIDEO_FOLDER = join(DATA_FOLDER, "converted-video")


def get_video_name(media_id: str, width: int, height: int) -> str:
    """Returns the file name of the requested video"""
    return f"{media_id}({width}x{height}).{VIDEO_FORMAT}"


def get_audio_name(media_id: str) -> str:
    """Returns the file name of the requested audio"""
    return f"{media_id}.{AUDIO_FORMAT}"


def get_video_path(media_id: str, width: int, height: int) -> str:
    """Returns the absolute path to the requested video in converted-video folder"""
    return join(CONVERTED_VIDEO_FOLDER, get_video_name(media_id, width, height))


def get_audio_path(media_id: str) -> str:
    """Returns the absolute path to the requested audio in converted-audio folder"""
    return join(CONVERTED_AUDIO_FOLDER, get_audio_name(media_id))


def create_data_folder_if_not_present():
    """Creates the data folder and subfolders (raw, converted-audio, converted-video) if they do not exist"""
    for folder in (DATA_FOLDER, RAW_FOLDER, CONVERTED_AUDIO_FOLDER, CONVERTED_VIDEO_FOLDER):
        if not exists(folder):
            mkdir(folder)


def is_audio_already_downloaded(media_id: str) -> bool:
    """Returns True if the given audio is already downloaded"""
    return exists(get_audio_path(media_id))


def is_video_already_downloaded(media_id: str, width: int, height: int) -> bool:
    """Returns True if the given video is already downloaded"""
    return exists(get_video_path(media_id, width, height))


# Only compile "allowed_characters" once
allowed_characters = re_compile("^[a-zA-Z0-9-._]*$")


def is_save(string: str) -> bool:
    """Returns True if the given string does not contain special characters"""
    return bool(allowed_characters.match(string))


def load_config() -> dict:
    """Loads optional config.json settings."""
    logger = getLogger(__name__)
    if not exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, JSONDecodeError) as exc:
        logger.warning("Failed to read config.json: %s", exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("config.json must be a JSON object")
        return {}
    return data


def get_data_folder_size_formatted() -> str:
    """Calculates total size of DATA_FOLDER in MB/GB and formats it."""
    if not exists(DATA_FOLDER):
        return "0.0 MB"
    total_bytes = 0
    try:
        for root, _, files in walk(DATA_FOLDER):
            for f in files:
                fp = join(root, f)
                if exists(fp):
                    try:
                        total_bytes += getsize(fp)
                    except OSError:
                        pass
    except OSError:
        pass

    mb = total_bytes / (1024 * 1024)
    if mb >= 1024:
        gb = mb / 1024
        return f"{gb:.2f} GB"
    return f"{mb:.1f} MB"

