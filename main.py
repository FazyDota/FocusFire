import argparse

import cv2
import logging
import pyperclip
import webbrowser

from datetime import datetime
from time import sleep, time, process_time
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from data import hero_name_to_id_map
from utility import OCR_text_from_image, validated_extracted_text

## LOGGING SETUP
logging.basicConfig(handlers=[logging.FileHandler("full.log"), logging.StreamHandler()], encoding='utf-8',
                    format="%(asctime)s: %(levelname)s - %(message)s",
                    datefmt='%H:%M:%S', level=logging.INFO)


class DraftParser:
    start_time = 0
    total_running_times = []
    is_radiant = True

    def __init__(self, local, debug):
        self.date_string = ""
        self.debug_flag = debug
        self.local_site = local

    def start_watching(self):
        """
        Starts watching for a draft screenshot.
        If a screenshot comes, initiate parsing.
        """
        logging.info('Draft parse started, waiting for a screenshot.')

        def on_created(event):
            self.start_time = time()
            sleep(0.4)
            screenshot = cv2.imread(event.src_path)
            logging.debug(f'Screenshot spotted on {event.src_path}')
            logger = logging.getLogger()
            logger.setLevel(logging.INFO)
            if self.debug_flag:
                logger.setLevel(logging.DEBUG)
                import os
                debug_dir_paths = ["sectors", "screens", "sectors\\extra"]
                for dir_path in debug_dir_paths:
                    os.makedirs(dir_path, exist_ok=True)
            self.handle_draft_sector_parsing(screenshot)

        dota_screens_path = "C:\\Program Files (x86)\\Steam\\userdata\\67712324\\760\\remote\\570\\screenshots"

        patterns = ["*.jpg"]
        ignore_patterns = None
        ignore_directories = False
        case_sensitive = True
        watchdog_handler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
        watchdog_handler.on_created = on_created
        watchdog_observer = Observer()
        watchdog_observer.schedule(watchdog_handler, dota_screens_path, recursive=False)
        watchdog_observer.start()
        logging.debug(f'Watchdog observer started, watching: {dota_screens_path}')

        try:
            while True:
                sleep(0.1)
        except KeyboardInterrupt:
            watchdog_observer.stop()
            watchdog_observer.join()

    def handle_draft_sector_parsing(self, draft_screenshot):
        """
        Draft screen contains 10 regions where hero name text can be found. This function takes a screenshot of the draft screens,
        extracts those 10 regions of interest (ROI) and then performs pre-processing before calling an OCR function.
        :param draft_screenshot: OpenCV image, screenshot of the draft screen, 2560x1440 resolution is expected.
        :return: False if the first sector (top left) contains no meaningful text, True otherwise.
        """
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

            # Gathering for future use
            extra_left = draft_screenshot[1005:1100, 910:1005]
            extra_right = draft_screenshot[1005:1100, 1315:1410]
            cv2.imwrite(f'sectors\\extra\\EXTRA_LEFT_{datetime.now().timestamp()}.png', extra_left)
            cv2.imwrite(f'sectors\\extra\\EXTRA_RIGHT_{datetime.now().timestamp()}.png', extra_right)

        except TypeError:
            logging.warning('Could not load the screenshot correctly.')
            return False
        result = ''
        url_result = ''
        logging.debug('Processing hero id:')
        self.date_string = datetime.now().strftime('%y%m%d_%H%M%S%f')[:-3]
        if self.debug_flag:
            cv2.imwrite(f'screens\\{self.date_string}_draft.png', draft_screenshot)
            
        error_count = 0
        processing_time_total = 0
        extracting_time_total = 0

        for idx, hero_name_sector in enumerate(hero_sectors):
            t1_start = process_time()
            logging.debug(f'{idx} ')
            cv2.imwrite(f'sectors\\{self.date_string}_sector_{idx}_0_raw.png', hero_name_sector)
            processed_image = cv2.GaussianBlur(hero_name_sector, (5, 5), 1)
            cv2.imwrite(f'sectors\\{self.date_string}_sector_{idx}_1_gaussian.png', processed_image)
            t1_stop = process_time()
            processing_time_total += t1_stop - t1_start

            t1_start = process_time()
            hero_text = self.try_to_extract_hero_name(idx, processed_image)
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
                logging.info(f'{hero_text} extracted')
                result += hero_text + '|'
                url_result += str(hero_name_to_id_map[hero_text]) + ','

        if result[-1] == '|':
            result = result[:-1]
        if url_result[-1] == ',':
            url_result = url_result[:-1]

        pyperclip.copy(result)
        logging.info(f'Copied into clipboard! Result:\n {result}')
        website_url = f"https://vintage-stats.herokuapp.com/abilities?heroes={url_result}"

        if self.local_site:
            website_url = f"http://127.0.0.1:8000/abilities?heroes={url_result}"
        logging.info(f'Opening the website: {website_url}')
        firefox_path = "C:\\Program Files\\Mozilla Firefox\\firefox.exe"
        webbrowser.register('firefox', None, webbrowser.BackgroundBrowser(firefox_path))
        try:
            webbrowser.get('firefox').open(website_url)
        except webbrowser.Error:
            webbrowser.open_new(website_url)

        # Some debug profiling
        if self.debug_flag:
            logging.info(f'Image processing CPU time total: {processing_time_total}')
            logging.info(f'Text extraction CPU time total: {extracting_time_total}')

            total_time = time() - self.start_time
            self.total_running_times.append(round(total_time, 4))
            logging.info(f'Total running normal time: {total_time}')
            logging.info(self.total_running_times)
        return True

    def try_to_extract_hero_name(self, sector_idx, input_image):
        if sector_idx == 0:
            green_mask = cv2.inRange(input_image, (20, 120, 20), (70, 255, 70))
            extracted_text = OCR_text_from_image(255 - green_mask)
            cv2.imwrite(f'sectors\\{self.date_string}_sector_{sector_idx}_2_green.png', 255 - green_mask)
            logging.debug(f"Trying to extract from sector {sector_idx} via green mask, result: {extracted_text}")

            if validated_extracted_text(extracted_text):
                logging.debug(f"Successfully extracted meaningful text, returning and setting to RADIANT")
                self.is_radiant = True
                return extracted_text

            red_mask = cv2.inRange(input_image, (21, 30, 145), (35, 60, 205))
            extracted_text = OCR_text_from_image(255 - red_mask)
            cv2.imwrite(f'sectors\\{self.date_string}_sector_{sector_idx}_3_red.png', 255 - red_mask)
            logging.debug(f"Trying to extract from sector {sector_idx} via red mask, result: {extracted_text}")

            if validated_extracted_text(extracted_text):
                logging.debug(f"Successfully extracted meaningful text, returning and setting to DIRE")
                self.is_radiant = False
                return extracted_text

            extracted_text = OCR_text_from_image(255 - input_image)
            cv2.imwrite(f'sectors\\{self.date_string}_sector_{sector_idx}_4_white_hsv.png', 255 - input_image)
            cv2.imwrite(f'sectors\\{self.date_string}_sector_{sector_idx}_4_white.png', 255 - input_image)
            logging.debug(f"Trying to extract from sector {sector_idx} via white mask, result: {extracted_text}")

            if validated_extracted_text(extracted_text):
                logging.debug(f"Successfully extracted meaningful text, returning and setting to RADIANT")
                self.is_radiant = True
                return extracted_text

            return None
        else:
            if (sector_idx < 5 and self.is_radiant) or (not self.is_radiant and sector_idx > 4):
                green_mask = cv2.inRange(input_image, (20, 120, 20), (70, 255, 70))
                extracted_text = OCR_text_from_image(255 - green_mask)
                cv2.imwrite(f'sectors\\{self.date_string}_sector_{sector_idx}_green.png', 255 - green_mask)
                logging.debug(f"Trying to extract from sector {sector_idx} via green mask, result: {extracted_text}")

                if extracted_text != 'Bn' and extracted_text != 'Be' and len(extracted_text) > 2:
                    logging.debug(f"Successfully extracted meaningful text, returning")
                    return extracted_text

                extracted_text = OCR_text_from_image(255 - input_image)
                cv2.imwrite(f'sectors\\{self.date_string}_sector_{sector_idx}_white.png', 255 - input_image)
                logging.debug(f"Trying to extract from sector {sector_idx} via white mask, result: {extracted_text}")

                if validated_extracted_text(extracted_text):
                    logging.debug(f"Successfully extracted meaningful text, returning")
                    return extracted_text

                return None

            else:
                red_mask = cv2.inRange(input_image, (21, 30, 145), (35, 60, 205))
                extracted_text = OCR_text_from_image(255 - red_mask)
                cv2.imwrite(f'sectors\\{self.date_string}_sector_{sector_idx}_2_red.png', 255 - red_mask)
                logging.debug(f"Trying to extract from sector {sector_idx} via red mask, result: {extracted_text}")

                if validated_extracted_text(extracted_text):
                    logging.debug(f"Successfully extracted meaningful text, returning")
                    return extracted_text

                return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parse AD drafts.')
    parser.add_argument('-l', '--local', dest='local', action='store_true')
    parser.add_argument('-d', '--debug', dest='debug', action='store_true')
    args = parser.parse_args()

    draft_parser = DraftParser(local=args.local, debug=args.debug)
    draft_parser.start_watching()
