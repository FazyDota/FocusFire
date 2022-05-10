import cv2
import logging
import pytesseract
import pyperclip
import webbrowser

from datetime import datetime
from time import sleep, time, process_time
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from data import hero_names, character_whitelist, hero_name_to_id_map
from utility import get_edit_distance

## LOGGING SETUP
logging.basicConfig(handlers=[logging.FileHandler("full.log"), logging.StreamHandler()], encoding='utf-8',
                    format="%(asctime)s: %(message)s",
                    datefmt='%H:%M:%S', level=logging.DEBUG)

DEBUG = False
total_running_times = []
start_time = 0


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
        # logging.info(f'{ocr_hero_name.lower()} vs {full_name.lower()} - edit distance {edit_distance}')
        if edit_distance_limit > edit_distance < best_edit_distance:
            best_edit_distance = edit_distance
            best_match = full_name

    logging.debug(f'Returning {best_match} as result, edit distance is {best_edit_distance}.')
    return best_match


def handle_draft_sector_parsing(draft_screenshot):
    """
    Draft screen contains 10 regions where hero name text can be found. This function takes a screenshot of the draft screens,
    extracts those 10 regions of interest (ROI) and then performs pre-processing before calling an OCR function.
    :param draft_screenshot: OpenCV image, screenshot of the draft screen, 2560x1440 resolution is expected.
    :return: False if the first sector (top left) contains no meaningful text, True otherwise.
    """
    # todo: Support for any resolution, use ratios etc
    try:
        hero_sectors = [draft_screenshot[193:233, 464:773],
                        draft_screenshot[410:450, 464:773],
                        draft_screenshot[628:668, 464:773],
                        draft_screenshot[845:885, 464:773],
                        draft_screenshot[1062:1102, 464:773],

                        draft_screenshot[193:233, 1789:2099],
                        draft_screenshot[410:450, 1789:2099],
                        draft_screenshot[628:668, 1789:2099],
                        draft_screenshot[845:885, 1789:2099],
                        draft_screenshot[1062:1102, 1789:2099]]
        # extra_ability_sectors = [draft_screenshot[1005:1100, 1315:1410], draft_screenshot[1005:1100, 910:1005]]
    except TypeError:
        logging.warning('Could not load the screenshot correctly.')
        return False
    result = ''
    url_result = ''
    logging.info('Processing hero id:')
    date_string = datetime.now().strftime('%y%m%d_%H%M%S%f')[:-3]
    is_radiant = True

    def validated_extracted_text(text):
        if text != 'Bn' and text != 'Be' and (len(text) > 2 or text.lower() == "io"):
            return True
        return False

    def try_to_extract_hero_name(sector_idx, input_image):
        nonlocal is_radiant
        nonlocal date_string
        if sector_idx == 0:
            green_mask = cv2.inRange(input_image, (20, 120, 20), (70, 255, 70))
            extracted_text = OCR_text_from_image(255 - green_mask)
            cv2.imwrite(f'sectors\\{date_string}_sector_{sector_idx}_2_green.png', 255 - green_mask)
            logging.debug(f"Trying to extract from sector {sector_idx} via green mask, result: {extracted_text}")

            if validated_extracted_text(extracted_text):
                logging.debug(f"Successfully extracted meaningful text, returning and setting to RADIANT")
                is_radiant = True
                return extracted_text

            red_mask = cv2.inRange(input_image, (21, 30, 145), (35, 60, 205))
            extracted_text = OCR_text_from_image(255 - red_mask)
            cv2.imwrite(f'sectors\\{date_string}_sector_{sector_idx}_3_red.png', 255 - red_mask)
            logging.debug(f"Trying to extract from sector {sector_idx} via red mask, result: {extracted_text}")

            if validated_extracted_text(extracted_text):
                logging.debug(f"Successfully extracted meaningful text, returning and setting to DIRE")
                is_radiant = False
                return extracted_text

            extracted_text = OCR_text_from_image(255 - input_image)
            cv2.imwrite(f'sectors\\{date_string}_sector_{sector_idx}_4_white_hsv.png', 255 - input_image)
            cv2.imwrite(f'sectors\\{date_string}_sector_{sector_idx}_4_white.png', 255 - input_image)
            logging.debug(f"Trying to extract from sector {sector_idx} via white mask, result: {extracted_text}")

            if validated_extracted_text(extracted_text):
                logging.debug(f"Successfully extracted meaningful text, returning and setting to RADIANT")
                is_radiant = True
                return extracted_text

            return None
        else:
            if (sector_idx < 5 and is_radiant) or (not is_radiant and sector_idx > 4):
                green_mask = cv2.inRange(input_image, (20, 120, 20), (70, 255, 70))
                extracted_text = OCR_text_from_image(255 - green_mask)
                cv2.imwrite(f'sectors\\{date_string}_sector_{sector_idx}_green.png', 255 - green_mask)
                logging.debug(f"Trying to extract from sector {sector_idx} via green mask, result: {extracted_text}")

                if extracted_text != 'Bn' and extracted_text != 'Be' and len(extracted_text) > 2:
                    logging.debug(f"Successfully extracted meaningful text, returning")
                    return extracted_text

                extracted_text = OCR_text_from_image(255 - input_image)
                cv2.imwrite(f'sectors\\{date_string}_sector_{sector_idx}_white.png', 255 - input_image)
                logging.debug(f"Trying to extract from sector {sector_idx} via white mask, result: {extracted_text}")

                if validated_extracted_text(extracted_text):
                    logging.debug(f"Successfully extracted meaningful text, returning")
                    return extracted_text

                return None

            else:
                red_mask = cv2.inRange(input_image, (21, 30, 145), (35, 60, 205))
                extracted_text = OCR_text_from_image(255 - red_mask)
                cv2.imwrite(f'sectors\\{date_string}_sector_{sector_idx}_2_red.png', 255 - red_mask)
                logging.debug(f"Trying to extract from sector {sector_idx} via red mask, result: {extracted_text}")

                if validated_extracted_text(extracted_text):
                    logging.debug(f"Successfully extracted meaningful text, returning")
                    return extracted_text

                return None

    error_count = 0
    processing_time_total = 0
    extracting_time_total = 0

    for idx, hero_name_sector in enumerate(hero_sectors):
        t1_start = process_time()
        logging.info(f'{idx} ')
        cv2.imwrite(f'sectors\\{date_string}_sector_{idx}_0_raw.png', hero_name_sector)
        processed_image = cv2.GaussianBlur(hero_name_sector, (5, 5), 1)
        cv2.imwrite(f'sectors\\{date_string}_sector_{idx}_1_gaussian.png', processed_image)
        t1_stop = process_time()
        processing_time_total += t1_stop - t1_start

        t1_start = process_time()
        hero_text = try_to_extract_hero_name(idx, processed_image)
        t1_stop = process_time()
        extracting_time_total += t1_stop - t1_start

        if not hero_text and idx == 0:
            logging.warning('No meaningful text found in the first sector with either cut, re-running.')
            return False

        if not hero_text:
            error_count = error_count + 1
            if error_count > 2:
                return False

        if hero_text:
            logging.info(f'Extracted {hero_text}, added to result string.')
            result += hero_text + '|'
            url_result += str(hero_name_to_id_map[hero_text]) + ','

    if result[-1] == '|':
        result = result[:-1]
    if url_result[-1] == ',':
        url_result = url_result[:-1]

    logger = logging.getLogger()
    logger.disabled = False

    pyperclip.copy(result)
    logging.info(f'Copied into clipboard! Result:\n {result}')
    website_url = f"https://vintage-stats.herokuapp.com/abilities?heroes={url_result}"
    logging.info(f'Opening the website: {website_url}')
    webbrowser.open(website_url)

    # Some debug profiling
    if DEBUG:
        logging.info(f'Image processing CPU time total: {processing_time_total}')
        logging.info(f'Text extraction CPU time total: {extracting_time_total}')
        global start_time
        global total_running_times
        total_time = time() - start_time
        total_running_times.append(round(total_time, 4))
        logging.info(f'Total running normal time: {total_time}')
        logging.info(total_running_times)
    return True


def start_draft_parse():
    """
    Starts the whole draft screenshot parsing procedure.
    """
    logging.info('Draft parse started, waiting for a screenshot.')

    def on_created(event):
        global start_time
        start_time = time()
        screenshot = cv2.imread(event.src_path)
        logging.debug(f'Screenshot spotted on {event.src_path}')
        logger = logging.getLogger()
        logger.disabled = not DEBUG
        handle_draft_sector_parsing(screenshot)

    path = "C:\\Program Files (x86)\\Steam\\userdata\\67712324\\760\\remote\\570\\screenshots"

    patterns = ["*.jpg"]
    ignore_patterns = None
    ignore_directories = False
    case_sensitive = True
    watchdog_handler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
    watchdog_handler.on_created = on_created
    watchdog_observer = Observer()
    watchdog_observer.schedule(watchdog_handler, path, recursive=False)
    watchdog_observer.start()
    logging.debug(f'Watchdog observer started, watching: {path}')

    try:
        while True:
            sleep(0.1)
    except KeyboardInterrupt:
        watchdog_observer.stop()
        watchdog_observer.join()


def OCR_text_from_image(img):
    ocr_config = r'--oem 3 --psm 7'
    output = pytesseract.image_to_string(img, config=ocr_config)

    cleaned_output = ''.join(filter(character_whitelist.__contains__, output))
    matched_output = match_with_hero_names(cleaned_output)
    return matched_output


if __name__ == '__main__':
    start_draft_parse()
