import argparse
import cv2
import logging
import pyperclip
import webbrowser
import pygetwindow as gw
import numpy as np

from gooey import Gooey, GooeyParser
from sklearn.cluster import KMeans
from warnings import simplefilter
from datetime import datetime
from time import sleep, time
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from data import hero_name_to_id_map
from utility import OCR_text_from_image, validate_extracted_text

simplefilter(action='ignore', category=FutureWarning)

# LOGGING SETUP
logging.basicConfig(handlers=[logging.FileHandler("full.log"), logging.StreamHandler()], encoding='utf-8',
                    format="%(asctime)s: %(levelname)s - %(message)s",
                    datefmt='%H:%M:%S', level=logging.INFO)


def guess_color_scheme(color_list):
    red = color_list[0]
    green = color_list[1]
    blue = color_list[2]

    if 8 < red < 23 and 30 < green < 55 and 10 < blue < 25:
        return "green"

    if 30 < red < 55 and 8 < green < 23 and 6 < blue < 17:
        return "red"

    return "unknown"


def get_dominant_colors(image_orig, count=1):
    image = cv2.cvtColor(image_orig, cv2.COLOR_BGR2RGB)
    reshape = image.reshape((image.shape[0] * image.shape[1], 3))
    cluster = KMeans(n_clusters=count).fit(reshape)
    labels = np.arange(0, len(np.unique(cluster.labels_)) + 1)
    (hist, _) = np.histogram(cluster.labels_, bins=labels)
    hist = hist.astype("float")
    hist /= hist.sum()
    colors = sorted([(percent, color) for (percent, color) in zip(hist, cluster.cluster_centers_)])

    color_list = []

    for (percent, color) in colors:
        color_list.append([int(color[0]), int(color[1]), int(color[2])])

    return color_list


def setup_for_OCR(input_image, assumed_color):
    extracted_text = OCR_text_from_image(255 - input_image)
    if validate_extracted_text(extracted_text):
        logging.debug(f"Successfully extracted meaningful text with white mask: {extracted_text}")
        return extracted_text

    masks_tried = 0
    if assumed_color == "green":
        green_mask = cv2.inRange(input_image, (20, 120, 20), (70, 255, 70))
        extracted_text = OCR_text_from_image(255 - green_mask)
        if validate_extracted_text(extracted_text):
            logging.debug(f"Successfully extracted meaningful text with green mask: {extracted_text}")
            return extracted_text
        masks_tried += 1
    elif assumed_color == "red":
        red_mask = cv2.inRange(input_image, (21, 30, 145), (35, 60, 205))
        extracted_text = OCR_text_from_image(255 - red_mask)
        if validate_extracted_text(extracted_text):
            logging.debug(f"Successfully extracted meaningful text with red mask: {extracted_text}")
            return extracted_text
        masks_tried += 2

    if masks_tried == 1:
        red_mask = cv2.inRange(input_image, (21, 30, 145), (35, 60, 205))
        extracted_text = OCR_text_from_image(255 - red_mask)
        if validate_extracted_text(extracted_text):
            logging.debug(f"Successfully extracted meaningful text with red mask: {extracted_text}")
            return extracted_text

    if masks_tried == 2:
        green_mask = cv2.inRange(input_image, (20, 120, 20), (70, 255, 70))
        extracted_text = OCR_text_from_image(255 - green_mask)
        if validate_extracted_text(extracted_text):
            logging.debug(f"Successfully extracted meaningful text with green mask: {extracted_text}")

    logging.debug(f"Wasn't able to extract meaningful text with any mask: {extracted_text}")
    return "Unknown"


def try_to_extract_hero_name(sector_idx, input_image):
    assumed_color = "unknown"
    if sector_idx in [0, 5]:
        dominant_colors = get_dominant_colors(input_image)[0]
        assumed_color = guess_color_scheme(dominant_colors)
        logging.debug(f"SECTOR {sector_idx}: Assumed scheme: {assumed_color}")

    elif assumed_color == "unknown":
        dominant_colors = get_dominant_colors(input_image)[0]
        assumed_color = guess_color_scheme(dominant_colors)
        logging.debug(f"SECTOR {sector_idx}: Assumed scheme: {assumed_color}")

    return setup_for_OCR(input_image, assumed_color)


class DraftParser:
    start_time = 0
    total_running_times = []
    is_radiant = True

    def __init__(self, aperetti, debug, watch_time, screenshot_path=""):
        self.date_string = ""
        self.debug_flag = debug
        self.aperetti = aperetti
        self.watch_time = watch_time
        self.screenshot_path = screenshot_path

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

        if self.screenshot_path:
            dota_screens_path = self.screenshot_path
        else:
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
        Draft screen contains 10 regions where hero name text can be found. This function takes a screenshot of the
        draft screens,extracts those 10 regions of interest (ROI) and then performs pre-processing before calling
        an OCR function.

        :param draft_screenshot: OpenCV image, screenshot of the draft screen, 2560x1440 resolution is expected.
        :return: False if the first sector (top left) contains no meaningful text, True otherwise.
        """

        try:
            hero_sectors = [draft_screenshot[193:233, 455:773],
                            draft_screenshot[410:450, 455:773],
                            draft_screenshot[628:668, 455:773],
                            draft_screenshot[845:885, 455:773],
                            draft_screenshot[1062:1102, 455:773],

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
        
        for idx, hero_name_sector in enumerate(hero_sectors):
            logging.debug(f'{idx}')
            processed_image = cv2.GaussianBlur(hero_name_sector, (9, 9), 1)

            if self.debug_flag:
                cv2.imwrite(f'sectors\\{self.date_string}_sector_{idx}_0_raw.png', hero_name_sector)
            if self.debug_flag:
                cv2.imwrite(f'sectors\\{self.date_string}_sector_{idx}_1_gaussian.png', processed_image)

            scale_percent = 200  # percent of original size
            width = int(processed_image.shape[1] * scale_percent / 100)
            height = int(processed_image.shape[0] * scale_percent / 100)
            dim = (width, height)

            scaled_image = cv2.resize(processed_image, dim, interpolation=cv2.INTER_CUBIC)

            if self.debug_flag:
                cv2.imwrite(f'sectors\\{self.date_string}_sector_{idx}_1_smaller.png', scaled_image)

            hero_text = try_to_extract_hero_name(idx, scaled_image)

            if not hero_text or hero_text == "Unknown":
                error_count = error_count + 1
                if error_count > 4:
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

        if self.aperetti:
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


@Gooey(program_name="FocusFire")
def main():
    parser = GooeyParser(description='FocusFire - AD draft screenshot parsing tool')
    parser.add_argument('-adp', '--aperetti', dest='aperetti', action='store_true', default=True)
    parser.add_argument('-d', '--debug', dest='debug', action='store_true')
    parser.add_argument('-t', '--time', dest='watch_time', action='store_true', default=True)
    parser.add_argument('-path', '--screenshot-path', dest='screenshot_path', widget="FileChooser")
    args = parser.parse_args()

    draft_parser = DraftParser(aperetti=args.aperetti, debug=args.debug, watch_time=args.watch_time,
                               screenshot_path=args.screenshot_path)
    from os import system

    system("title " + "FocusFire")
    draft_parser.start_watching()


if __name__ == '__main__':
    main()
