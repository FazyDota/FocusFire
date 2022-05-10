import logging
logging.basicConfig(handlers=[logging.FileHandler("full.log"), logging.StreamHandler()], encoding='utf-8',
                    format="%(asctime)s: %(message)s",
                    datefmt='%H:%M:%S', level=logging.DEBUG)


def get_edit_distance(s1, s2):
    if len(s1) > len(s2):
        s1, s2 = s2, s1

    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2+1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]


def test_screenshots(amount):
    """
    Tests the screenshot function, taking and saving given amount of screenshots.
    Takes a screenshot roughly once per second.
    :param amount:
    :return: No return value.
    """
    logging.info(f'Running {amount} screenshot tests, one roughly each 1 second.')
    with mss() as sct:
        for i in range(amount):
            t0 = time()
            date_string = datetime.now().strftime('%d%m_%H%M%S_%f')[:-3]
            filename = sct.shot(mon=1, output=f'screens\\test_screenshot_{i}_{date_string}.png')
            logging.info(f'Saved {filename}.png')
            passed_time = (time() - t0)
            if passed_time < 1:
                logging.debug(f'Sleeping for {1 - passed_time}')
                sleep(1 - passed_time - 0.02)