import logging
import pytesseract
from data import character_whitelist, hero_names

logging.basicConfig(handlers=[logging.FileHandler("full.log"), logging.StreamHandler()], encoding="utf-8",
                    format="%(asctime)s: %(message)s",
                    datefmt="%H:%M:%S", level=logging.DEBUG)


def replace_numbers(ocr_input):
    return ocr_input.replace("5", "S").replace("1", "I").replace("0", "O").replace("2", "Z").replace("4", "A").replace("8", "B")


def OCR_text_from_image(img):
    ocr_config = r'--oem 1 --psm 7'
    output = pytesseract.image_to_string(img, config=ocr_config)
    logging.debug(f"Pure OCR output: {output}")

    cleaned_output = replace_numbers(''.join(filter(character_whitelist.__contains__, output))).strip()
    matched_output = match_with_hero_names(cleaned_output)
    return matched_output


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
    :return: The closest matching hero name (only up to edit distance equal to 1/3 of input string) or the input string in case of no good match.
    """
    logging.debug(f'Calling match_with_hero_names({ocr_hero_name}).')
    best_match = ocr_hero_name
    edit_distance_limit = len(ocr_hero_name) / 3 + len(ocr_hero_name) % 3
    best_edit_distance = len(ocr_hero_name)
    for full_name in hero_names:
        edit_distance = get_edit_distance(ocr_hero_name.lower(), full_name.lower())
        logging.debug(f'{ocr_hero_name.lower()} vs {full_name.lower()} - edit distance {edit_distance}')
        if edit_distance_limit > edit_distance < best_edit_distance:
            best_edit_distance = edit_distance
            best_match = full_name
        if edit_distance == 0:
            return best_match

    logging.debug(f'Returning {best_match} as result, edit distance is {best_edit_distance}.')
    return best_match


def validate_extracted_text(text):
    if text != 'Bn' and text != 'Be' and (len(text) > 2 or text.lower() == "io"):
        return True
    return False
