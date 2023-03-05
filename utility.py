import bisect
import logging
from titlecase import titlecase
from collections import deque
from sys import platform
import os
import ctypes
import json
from pathlib import Path

from data import hero_names, hero_names_lower

logging.basicConfig(handlers=[logging.FileHandler("full.log"), logging.StreamHandler()], encoding="utf-8",
                    format="%(asctime)s: %(message)s",
                    datefmt="%H:%M:%S", level=logging.DEBUG)

logging.getLogger('PIL').setLevel(logging.ERROR)


def replace_numbers(ocr_input):
    return ocr_input.replace("5", "S").replace("1", "I").replace("0", "O").replace("2", "Z")\
        .replace("4", "A").replace("8", "B")


def get_edit_distance(s1, s2):
    if len(s1) > len(s2):
        s1, s2 = s2, s1

    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2 + 1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]


def match_with_hero_names(ocr_hero_name):
    """
    Attempts to match an input string onto a Dota hero name (see data module),
    iterating through all available hero names and choosing the one with the smallest Levenshtein edit distance.
    Maximum allowed edit distance is one third of the input's string length.

    :param ocr_hero_name: A supposed hero name created in OCR of the draft screen.
    In case of bad read, result input could be just "Bn" or similar.
    :return: The closest matching hero name (only up to edit distance equal to 1/3 of input string) or the input string
    in case of no good match.
    """
    logging.debug(f'Calling match_with_hero_names({ocr_hero_name}).')
    if ocr_hero_name.lower() in hero_names_lower:
        logging.debug(f'Found a direct match: {titlecase(ocr_hero_name)}.')
        return titlecase(ocr_hero_name)

    shift = bisect.bisect_left(hero_names_lower, ocr_hero_name.lower())
    best_match = ocr_hero_name
    edit_distance_limit = len(ocr_hero_name) / 3 + len(ocr_hero_name) % 3
    best_edit_distance = len(ocr_hero_name)
    rotated_hero_names = deque(hero_names)
    rotated_hero_names.rotate(-shift)

    for full_name in rotated_hero_names:
        edit_distance = get_edit_distance(ocr_hero_name.lower(), full_name.lower())
        logging.debug(f'{ocr_hero_name.lower()} vs {full_name.lower()} - edit distance {edit_distance}')
        if edit_distance_limit > edit_distance < best_edit_distance:
            best_edit_distance = edit_distance
            best_match = full_name
        if edit_distance <= 1:
            return best_match

    logging.debug(f'Returning {best_match} as result, edit distance is {best_edit_distance}.')
    return best_match


def validate_extracted_text(text):
    return text.lower() in hero_names_lower


def try_to_locate_screenshot_folder():
    if platform in ['win32', 'cygwin']:
        # Get drive letters
        dmask = ctypes.windll.kernel32.GetLogicalDrives()
        drives = [chr(ord('A') + n) for n in range(26) if (dmask >> n) & 1]

        for drive in drives:
            for root, dirs, files in os.walk(f"{drive}:\\", topdown=False):
                for name in dirs:
                    current_path = Path(root, name)
                    if Path(root, name).match('760/remote/570/screenshots'):
                        logging.debug(f"Successfully located Dota 2 screenshot folder at: {current_path}")
                        return current_path
        logging.debug("Could not locate Dota 2 screenshot folder.")
        return None

    elif platform == 'darwin':
        for root, dirs, files in os.walk("/Users/", topdown=False):
            for name in dirs:
                current_path = Path(root, name)
                if Path(root, name).match('760/remote/570/screenshots'):
                    logging.debug(f"Successfully located Dota 2 screenshot folder at: {current_path}")
                    return current_path
        logging.debug("Could not locate Dota 2 screenshot folder.")
        return None

    elif platform == 'linux':
        for root, dirs, files in os.walk("~/.local/share/", topdown=False):
            for name in dirs:
                current_path = Path(root, name)
                if Path(root, name).match('760/remote/570/screenshots'):
                    logging.debug(f"Successfully located Dota 2 screenshot folder at: {current_path}")
                    return current_path
        logging.debug("Could not locate Dota 2 screenshot folder.")
        return None

    else:
        logging.debug("Unrecognized OS - could not locate Dota 2 screenshot folder.")
        return None


def load_config():
    config_path = Path('config.json')
    config_with_defaults = {'adp': True, 'debug': False, 'watch_time': False, 'screenshot_path': ""}

    if config_path.exists():
        with open(config_path) as config_file:
            try:
                config = json.load(config_file)
            except (json.decoder.JSONDecodeError, UnicodeDecodeError) as error:
                logging.debug(f"Config file had wrong format, encoding or something. Using defaults. Error: {error}")
                return config_with_defaults

            config_with_defaults['adp'] = config.get('use_ability_draft_plus', True)
            config_with_defaults['debug'] = config.get('debug_mode', False)
            config_with_defaults['watch_time'] = config.get('track_processing_time', False)
            config_with_defaults['screenshot_path'] = config.get('dota_screenshots_path', "")
            return config_with_defaults
    else:
        return config_with_defaults


def save_config(args_dict):
    config = {'use_ability_draft_plus': args_dict['Use Ability Draft Plus'],
              'debug_mode': args_dict['Use Debug Mode'],
              'track_processing_time': args_dict['Track Processing Time'],
              'dota_screenshots_path': args_dict['Screenshot Path']}

    logging.debug("Running save_config")
    config_path = Path('config.json')
    with open(config_path, 'w') as config_file:
        json.dump(config, config_file, indent=4)
