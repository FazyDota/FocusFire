import cv2
import logging
import pyperclip
import webbrowser
import pygetwindow as gw
import pytesseract

from gooey import Gooey, GooeyParser
from warnings import simplefilter
from datetime import datetime
from time import sleep, time
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

import utility
from data import hero_name_to_id_map, character_whitelist
from utility import validate_extracted_text, replace_numbers, match_with_hero_names

simplefilter(action='ignore', category=FutureWarning)

# LOGGING SETUP
logging.basicConfig(handlers=[logging.FileHandler("full.log"), logging.StreamHandler()], encoding='utf-8',
                    format="%(asctime)s: %(levelname)s - %(message)s",
                    datefmt='%H:%M:%S', level=logging.INFO)


class DraftParser:
    start_time = 0
    total_running_times = []
    is_radiant = True

    def __init__(self, args):
        self.date_string = ""
        args_dict = vars(args)
        self.debug_flag = args_dict['Use Debug Mode']
        self.use_adp = args_dict['Use Ability Draft Plus']
        self.watch_time = args_dict['Track Processing Time']

        if not args_dict['Screenshot Path']:
            logging.debug("Locating Dota 2 screenshot path automatically.")
            self.screenshot_path = str(utility.try_to_locate_screenshot_folder())
            logging.debug(f"Autopath: {self.screenshot_path}, saved to config.")
            args_dict['Screenshot Path'] = self.screenshot_path
        else:
            self.screenshot_path = args_dict['Screenshot Path']

        utility.save_config(args_dict)

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
            logging.info(f'Screenshot spotted on {event.src_path}')
            logger = logging.getLogger()
            logger.setLevel(logging.INFO)
            if self.debug_flag:
                logger.setLevel(logging.DEBUG)
                import os
                debug_dir_paths = ["sectors", "screens", "sectors\\extra"]
                for dir_path in debug_dir_paths:
                    os.makedirs(dir_path, exist_ok=True)
            try:
                win = gw.getWindowsWithTitle('FocusFire')[0]
                win.activate()
            except gw.PyGetWindowException:
                pass
            self.handle_draft_sector_parsing(screenshot)

        patterns = ["*.jpg"]
        ignore_patterns = None
        ignore_directories = False
        case_sensitive = True
        watchdog_handler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
        watchdog_handler.on_created = on_created
        watchdog_observer = Observer()
        watchdog_observer.schedule(watchdog_handler, self.screenshot_path, recursive=False)
        watchdog_observer.start()
        logging.debug(f'Watchdog observer started, watching: {self.screenshot_path}')

        try:
            while True:
                sleep(0.1)
        except KeyboardInterrupt:
            watchdog_observer.stop()
            watchdog_observer.join()

    def handle_draft_sector_parsing(self, draft_screenshot):
        """
        Draft screen contains 10 regions where hero name text can be found. This function takes a screenshot of the
        draft screens,extracts those 10 regions of interest (ROI) and then performs pre-processing before calling
        an OCR function.

        :param draft_screenshot: OpenCV image, screenshot of the draft screen, 2560x1440 resolution is expected.
        :return: False if the first sector (top left) contains no meaningful text, True otherwise.
        """

        y_coords_ratios = [[196.0 / 1440.0, 236.0 / 1440.0],
                           [412.0 / 1440.0, 452.0 / 1440.0],
                           [628.0 / 1440.0, 668.0 / 1440.0],
                           [844.0 / 1440.0, 884.0 / 1440.0],
                           [1060.0 / 1440.0, 1100.0 / 1440.0]]

        x_coords_ratios_left = [455.0 / 2560.0, 765.0 / 2560.0]
        x_coords_ratios_right = [1790.0 / 2560.0, 2100.0 / 2560.0]

        # 16:9 percentage coords, y, x left, x right
        # [[0.1361111111111111, 0.1638888888888889],
        # [0.2861111111111111, 0.3138888888888889],
        # [0.4361111111111111, 0.4638888888888889],
        # [0.5861111111111111, 0.6138888888888889],
        # [0.7361111111111112, 0.7638888888888888]]
        # [0.177734375, 0.298828125]
        # [0.69921875, 0.8203125]

        screenshot_width = int(draft_screenshot.shape[1])
        screenshot_height = int(draft_screenshot.shape[0])

        if screenshot_width == 2560 and screenshot_height == 1400:
            extra_left = draft_screenshot[1005:1100, 910:1005]
            extra_right = draft_screenshot[1005:1100, 1315:1410]
            cv2.imwrite(f'sectors\\extra\\EXTRA_LEFT_{datetime.now().timestamp()}.png', extra_left)
            cv2.imwrite(f'sectors\\extra\\EXTRA_RIGHT_{datetime.now().timestamp()}.png', extra_right)

        calculated_sector_coords = []
        for sector in y_coords_ratios:
            y_min = sector[0] * float(screenshot_height)
            y_max = sector[1] * float(screenshot_height)
            x_min = x_coords_ratios_left[0] * float(screenshot_width)
            x_max = x_coords_ratios_left[1] * float(screenshot_width)
            calculated_sector_coords.append([int(y_min), int(y_max), int(x_min), int(x_max)])

        for sector in y_coords_ratios:
            y_min = sector[0] * float(screenshot_height)
            y_max = sector[1] * float(screenshot_height)
            x_min = x_coords_ratios_right[0] * float(screenshot_width)
            x_max = x_coords_ratios_right[1] * float(screenshot_width)
            calculated_sector_coords.append([int(y_min), int(y_max), int(x_min), int(x_max)])

        try:
            hero_sectors = []
            for sector_coords in calculated_sector_coords:
                sector = draft_screenshot[sector_coords[0]:sector_coords[1], sector_coords[2]:sector_coords[3]]
                hero_sectors.append(sector)
        except TypeError:
            logging.warning('Could not load the screenshot correctly.')
            return False

        result = ''
        url_result = ''
        error_count = 0

        logging.debug('Processing sector id:')
        self.date_string = datetime.now().strftime('%y%m%d_%H%M%S%f')[:-3]
        if self.debug_flag:
            cv2.imwrite(f'screens\\{self.date_string}_draft.png', draft_screenshot)

        for idx, hero_name_sector in enumerate(hero_sectors):
            logging.debug(f'{idx}')
            processed_image = cv2.GaussianBlur(hero_name_sector, (9, 9), 1)

            cv2.imwrite(f'sectors\\{self.date_string}_sector_{idx}_0_raw.png', hero_name_sector)
            if self.debug_flag:
                cv2.imwrite(f'sectors\\{self.date_string}_sector_{idx}_1_gaussian.png', processed_image)

            scale_percent = 200  # percent of original size
            screenshot_width = int(processed_image.shape[1] * scale_percent / 100)
            screenshot_height = int(processed_image.shape[0] * scale_percent / 100)
            dimensions = (screenshot_width, screenshot_height)

            scaled_image = cv2.resize(processed_image, dimensions, interpolation=cv2.INTER_CUBIC)

            if self.debug_flag:
                cv2.imwrite(f'sectors\\{self.date_string}_sector_{idx}_1_scaled.png', scaled_image)

            hero_text = self.try_to_extract_hero_name(scaled_image)

            if not hero_text or hero_text == "Unknown":
                error_count = error_count + 1
                url_result += 'null,'
                if error_count > 3:
                    logging.info("Draft parse unsuccessful, screenshot not might be right. Try again.")
                    return False

            if hero_text and hero_text != "Unknown":
                logging.debug(f'{hero_text} extracted')
                result += hero_text + '|'
                url_result += str(hero_name_to_id_map[hero_text]) + ','

        if result[-1] == '|':
            result = result[:-1]
        if url_result[-1] == ',':
            url_result = url_result[:-1]

        pyperclip.copy(result)
        logging.info(f'Copied into clipboard! Result:\n {result}')
        website_url = f"http://127.0.0.1:8000/abilities?heroes={url_result}"

        if self.use_adp:
            dire = url_result.split(",")[5:]
            aperetti_string = ",".join(url_result.split(",")[0:5] + ["null", "null"] + dire[::-1])
            website_url = f"https://abilitydraftplus.com/?heroes=[{aperetti_string}]"
        logging.info(f'Opening the website: {website_url}')
        firefox_path = "C:\\Program Files\\Mozilla Firefox\\firefox.exe"
        webbrowser.register('firefox', None, webbrowser.BackgroundBrowser(firefox_path))
        try:
            webbrowser.get('firefox').open(website_url)
        except webbrowser.Error:
            webbrowser.open_new(website_url)

        # Some debug profiling
        if self.watch_time:
            total_time = time() - self.start_time
            self.total_running_times.append(round(total_time, 4))
            logging.info(f'Total running normal time: {total_time}')
            logging.info(self.total_running_times)
        return True

    def try_to_extract_hero_name(self, input_image):
        return self.setup_for_OCR(input_image)

    def setup_for_OCR(self, input_image):
        extracted_text = self.OCR_text_from_image(255 - input_image)
        if validate_extracted_text(extracted_text):
            logging.debug(f"Successfully extracted meaningful text with white mask: {extracted_text}")
            return extracted_text

        extracted_text = self.OCR_text_from_image(input_image)
        if validate_extracted_text(extracted_text):
            logging.debug(f"Successfully extracted meaningful text with no mask: {extracted_text}")
            return extracted_text

        red_mask = cv2.inRange(input_image, (21, 30, 145), (35, 60, 205))
        extracted_text = self.OCR_text_from_image(255 - red_mask)
        if validate_extracted_text(extracted_text):
            logging.debug(f"Successfully extracted meaningful text with red mask: {extracted_text}")
            return extracted_text

        green_mask = cv2.inRange(input_image, (20, 120, 20), (70, 255, 70))
        extracted_text = self.OCR_text_from_image(255 - green_mask)
        if validate_extracted_text(extracted_text):
            logging.debug(f"Successfully extracted meaningful text with green mask: {extracted_text}")
            return extracted_text

        input_image = cv2.bitwise_not(input_image)
        _, binary = cv2.threshold(input_image, 150, 255, cv2.THRESH_BINARY)
        extracted_text = self.OCR_text_from_image(binary)
        if validate_extracted_text(extracted_text):
            logging.debug(f"Successfully extracted meaningful text with green mask: {extracted_text}")
            return extracted_text

        return "Unknown"

    def OCR_text_from_image(self, img):
        dt = datetime.now().strftime('%y%m%d_%H%M%S%f')[:-3]
        cv2.imwrite(f'sectors\\debug\\sector_{dt}_OCR_used.png', img)
        ocr_config = r'--oem 3 --psm 6'
        output = pytesseract.image_to_string(img, config=ocr_config)
        logging.debug(f"Pure OCR output: {output}")

        cleaned_output = replace_numbers(''.join(filter(character_whitelist.__contains__, output))).strip()
        matched_output = match_with_hero_names(cleaned_output)
        return matched_output


@Gooey(program_name="FocusFire", show_stop_warning=False, default_size=(1080, 640))
def main():
    parser = GooeyParser(description='FocusFire - AD draft screenshot parsing tool')
    config = utility.load_config()

    screenshot_group = parser.add_argument_group(
        "Important Settings",
    )
    screenshot_group.add_argument('-screenshot_path', '--Screenshot Path', widget="DirChooser",
                                  gooey_options={'initial_value': config['screenshot_path']},
                                  help='This folder will be watched for new screenshots when FocusFire is running.'
                                       ' Will try to auto-fill if left blank.'
                                       ' \nAuto-fill might find the wrong folder if '
                                       'there are more users with Dota 2 screenshot folders.')

    additional_settings = parser.add_argument_group(
        "Additional Settings",
        "You can keep these on default."
    )
    additional_settings.add_argument('-adp', '--Use Ability Draft Plus', action='store_true',
                                     gooey_options={'initial_value': config['adp']},
                                     help='If turned off, will attempt to use locally running Blur instance.'
                                          ' Keep on otherwise.')
    additional_settings.add_argument('-debug', '--Use Debug Mode', action='store_true',
                                     gooey_options={'initial_value': config['debug']},
                                     help='Additional log messages. '
                                          'Also will save pieces of screenshots to a subfolder.'
                                          ' Useful if something doesn\'t work.')
    additional_settings.add_argument('-time', '--Track Processing Time', action='store_true',
                                     gooey_options={'initial_value': config['watch_time']},
                                     help='Display basic information about processing time in the run log.')

    args = parser.parse_args()

    draft_parser = DraftParser(args)
    draft_parser.start_watching()


if __name__ == '__main__':
    main()
