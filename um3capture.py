#!/bin/python3
#
# Copyright 2018 - Jeff Kunzelman
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS
# OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

import os
import argparse
import subprocess
import tempfile
import shutil
import concurrent.futures
import time
from time import sleep
import requests
from typing import Union


class JobStatus(object):
    def __init__(self, response=None, exception=None):
        # if no response is supplied, create 'error' status
        if response is None:
            self.__data = None
            if exception is not None:
                self.__state = 'error'
                self.__exception = exception
            else:
                self.__state = 'unknown'
                self.__exception = None
            return

        # Check for valid response:
        # the 'print_job' request will return 404 when no print job is running (we'll set faux state='no job'
        # the 'print_job' request will return 200 and data when a print job is running
        self.__response = response
        if self.__response.status_code != 200:
            self.__state = 'no job'
            self.__data = None
            return

        self.__data = response.json()
        self.__state = self.__kvd('state')

    def __kvd(self, key, default=None):
        if key in self.__data:
            return self.__data[key]
        return default

    @property
    def state(self) -> str:
        return self.__state

    @property
    def is_valid(self) -> bool:
        return self.__response.status_code == 200

    @property
    def is_printing(self) -> bool:
        return self.__state == 'printing'

    @property
    def is_preprint(self) -> bool:
        return self.__state == 'pre_print'

    @property
    def is_postprint(self) -> bool:
        return self.__state == 'post_print' or self.state == 'wait_cleanup'

    @property
    def is_error(self) -> bool:
        return self.__state == 'error' or self.__state == 'unknown'

    @property
    def error(self) -> Exception:
        return self.__exception

    @property
    def name(self) -> str:
        return self.__kvd('name', '')

    @property
    def time_remaining(self) -> float:
        if self.time_total != 0:
            return self.time_total - self.time_elapsed
        else:
            return -1

    @property
    def progress(self) -> float:
        if self.time_total != 0:
            return self.time_elapsed / self.time_total
        else:
            return 0

    @property
    def time_elapsed(self) -> float:
        return self.__kvd('time_elapsed', 0)

    @property
    def time_total(self) -> float:
        return self.__kvd('time_total', 0)


class UM3Api(object):
    def __init__(self, printer_ip):
        self.__ip = printer_ip
        self.__session = requests.sessions.Session()

    def __get(self, uri: str, port=80, timeout=5):
        return self.__session.get("http://{}:{}/{}".format(self.__ip, port, uri), timeout=timeout)

    @property
    def is_online(self) -> bool:
        try:
            self.__get("api/v1/printer/status", timeout=1).json()
            return True
        except requests.exceptions.Timeout:
            return False
        except requests.exceptions.RequestException as err:
            print(err)
            return False

    # return job status, on error JobStatus will have the 'error' state set
    def get_job_status(self) -> JobStatus:
        try:
            response = self.__get("api/v1/print_job")
            return JobStatus(response)
        except requests.exceptions.Timeout as err:
            return JobStatus(exception=err)
        except requests.exceptions.RequestException as err:
            print(err)
            return JobStatus(exception=err)

    # return camera image as binary data
    def get_snapshot(self) -> Union[bytes, None]:
        try:
            response = self.__get("?action=snapshot", port=8080)
            return response.content
        except requests.exceptions.Timeout:
            return None
        except requests.exceptions.RequestException as err:
            print(err)
            return None


def seconds_to_hms(time_in_seconds) -> str:
    days = int(time_in_seconds // (24 * 60 * 60))
    time_in_seconds = time_in_seconds % (24 * 60 * 60)
    hours = int(time_in_seconds // (60 * 60))
    time_in_seconds %= (60 * 60)
    mins = int(time_in_seconds // 60)
    time_in_seconds %= 60
    secs = int(time_in_seconds // 1)

    if days != 0:
        return "{:02d}:{:02d}:{:02d}:{:02d}s".format(days, hours, mins, secs)
    if hours != 0:
        return "{:02d}:{:02d}:{:02d}s".format(hours, mins, secs)
    elif mins != 0:
        return "{:02d}:{:02d}s".format(mins, secs)
    else:
        return "{:02d}s".format(secs)


# return 0 if not printing, delay time otherwise
def calc_delay(api, duration) -> float:
    job = api.get_job_status()
    if not job.is_printing:
        return 0

    time_remaining = job.time_remaining
    if time_remaining <= FAST_CAPTURE:  # Record often for the last part of the print
        delay_time = MIN_DELAY
    else:
        delay_time = job.time_total / (FPS * duration)
        delay_time = max(delay_time, MIN_DELAY)
        if delay_time >= time_remaining + MIN_DELAY:  # Make sure we can record often during the last part of printing
            delay_time = time_remaining - MIN_DELAY

    return delay_time


# returns done, delay used
def printing_delay(api, duration):
    delay_time = calc_delay(api, duration)
    if delay_time == 0:
        return True, 0

    sleep(delay_time)
    return False, delay_time


def capture_timelapse(api: UM3Api, print_name: str, video_dir: str, est_video_duration: float,
                      executor: concurrent.futures.ThreadPoolExecutor):
    # create tmp directory for images
    name = "um3_{}".format(print_name)
    frames_dir = tempfile.mkdtemp(prefix="{}_".format(name))

    # Print summary message
    est_time = api.get_job_status().time_total
    est_frames = est_video_duration * FPS
    est_frame_delay = est_time / est_frames
    if est_frame_delay < MIN_DELAY:
        est_frame_delay = MIN_DELAY
        est_frames = est_time / MIN_DELAY
        est_video_duration = int(est_frames / FPS)

    print("Capture estimate: Time: {}, Frames: {}, Video duration: {}, Time between frames: {}, Location: {}"
          .format(seconds_to_hms(est_time), int(est_frames), seconds_to_hms(est_video_duration),
                  seconds_to_hms(est_frame_delay), frames_dir))

    # capture the frames
    fn_template = os.path.join(frames_dir, "%05d.jpg")
    finished = False
    frame_number = 1
    last_delay = 0
    start_time = time.time()
    while not finished:
        # grab the frame image
        img = api.get_snapshot()

        # process the image, move on to the next frame
        if img is not None:
            filename = fn_template % frame_number
            fh = open(filename, 'wb')
            fh.write(img)
            fh.close()
            if VERBOSITY > VERBOSITY_NORMAL:
                print("Print progress:{:05.2%} Image:{:05d} Time between frames:{:5.2f}s"
                      .format(api.get_job_status().progress, frame_number, last_delay))
            finished, last_delay = printing_delay(api, est_video_duration)
            frame_number += 1

        # there was some sort of error getting the image, let's try to finish up.
        else:
            finished = True

    # convert to a video in the background
    actual_frames = frame_number - 1
    actual_time = time.time() - start_time
    print("Capture: Time: {}, Frames: {}, Video duration: {}"
          .format(seconds_to_hms(actual_time), actual_frames, seconds_to_hms(int(actual_frames / FPS))))
    if executor is not None:
        executor.submit(encode_video, video_dir, fn_template, frames_dir, name)
    else:
        encode_video(video_dir, fn_template, frames_dir, name)


def encode_video(target_dir: str, fn_template: str, image_dir: str, print_name: str):
        output_name = os.path.join(target_dir, print_name)
        output_name = find_best_filename(output_name, "mp4")
        if VERBOSITY == VERBOSITY_ULTRA:
            log_level = 'info'
        elif VERBOSITY == VERBOSITY_VERBOSE:
            log_level = 'fatal'
        else:
            log_level = 'fatal'

        #
        # For FFMPEG encoding preset info ('veryfast' performs best overall) see:
        # https://superuser.com/questions/490683/cheat-sheets-and-presets-settings-that-actually-work-with-ffmpeg-1-0
        # https://trac.ffmpeg.org/wiki/Encode/H.264
        #
        ffmpeg_command = \
            "ffmpeg -y -loglevel {} -r {} -i {} -vcodec libx264 -pix_fmt yuv420p -preset veryfast -crf 18 {}" \
            .format(log_level, FPS, fn_template, output_name)

        if VERBOSITY > VERBOSITY_NORMAL:
            print("Converting to video: {}".format(ffmpeg_command))
        elif VERBOSITY == VERBOSITY_NORMAL:
            print("Converting to video: {}".format(output_name))

        start_time = time.time()
        encode_result = subprocess.run(ffmpeg_command.split(' '), stderr=True, stdout=True)
        elapsed_time = time.time() - start_time

        # remove image directory on successful video creation
        if encode_result.returncode == 0:
            if VERBOSITY > VERBOSITY_SILENT:
                print("Video success:{}, encode time:{} ".format(output_name, seconds_to_hms(elapsed_time)))
            if not NO_CLEAN:
                shutil.rmtree(image_dir)
        else:
            print("Video encode failure: retained images directory @ {}", target_dir)
            print(encode_result)


def find_best_filename(base_name, suffix):
    counter = 0
    path = base_name + "." + suffix
    while os.path.exists(path):
        counter += 1
        path = "{}_{:03d}.{}".format(base_name, counter, suffix)
    return path


def print_error(err):
    print("Connection error: {0}".format(err))

#
# Some constants
#
VERSION = 0.91
VERBOSITY_ULTRA = 3
VERBOSITY_VERBOSE = 2
VERBOSITY_NORMAL = 1
VERBOSITY_SILENT = 0

MIN_DELAY = 0.5     # Minimum delay between frames during capture
FPS = 30            # Frames Per Second of target video
FAST_CAPTURE = 60   # fast capture of frames for the last N seconds of the print

#
# Parse parameters from the command line
#
cliParser = argparse.ArgumentParser(description='Continiously listen for prints on an UM3, then create time '
                                                'lapse videos of each print')
cliParser.add_argument('--ip', nargs='?', type=str, default='192.168.1.158',
                       help='IP address of the Ultimaker')
cliParser.add_argument('-t', '--timelapsedir', type=str, default='/tmp',
                       help='Directory for time lapse videos')
cliParser.add_argument('-d', '--duration', nargs='?', type=float, default=20,
                       help='Target duration of output video')
cliParser.add_argument('-n', '--noclean', action='store_true',
                       help="Don't clean up temporary directories when done")
cliParser.add_argument('-v', '--verbosity', nargs='?', type=int, default=VERBOSITY_NORMAL,
                       help='Output verbosity: 0 = errors only, 1 = normal, 2 = verbose, 3 = debug')
cliParser.add_argument('-f', '--foreground', action='store_true',
                       help='Encode video in the foreground (normally it is processed on a background thread)')
cliParser.add_argument('-s', '--singleprint', action='store_true',
                       help='Only capture a Single print then exit. Normally this will run continuously capturing '
                            'time lapse videos for each print.')

# Grab command line options
options = cliParser.parse_args()

# these are global in scope and are constants
NO_CLEAN = options.noclean
VERBOSITY = options.verbosity

# grab other command line options
ip = options.ip
capture_single_print = options.singleprint
video_duration = options.duration
video_be = not (options.foreground or capture_single_print)
video_directory = options.timelapsedir


# setup initial state
um = UM3Api(ip)
if video_be:
    video_encoding_executor = concurrent.futures.ThreadPoolExecutor()
else:
    video_encoding_executor = None

# display configuration info
if VERBOSITY != VERBOSITY_SILENT:
    if VERBOSITY == VERBOSITY_VERBOSE:
        print("Verbose output")
    elif VERBOSITY == VERBOSITY_ULTRA:
        print("Debug output")
    print("Ultimaker Capture v{}".format(VERSION))
    print("Printer IP: {}".format(ip))
    print("Target video duration:{}s, frame rate:{}fps, fast capture last:{}s"
          .format(video_duration, FPS, FAST_CAPTURE))
    print("Time lapse video directory:{}".format(video_directory))
    if video_be:
        print("Encode video:background")
    elif capture_single_print:
        print("Encode video:foreground (-s option forces this)")
    else:
        print("Encode video:foreground")
    if capture_single_print:
        print("Only capture a single print then exit")
    if NO_CLEAN:
        print("Don't clean up temporary files in \"{}\" when done".format(tempfile.gettempdir()))
    print("")

while True:
    # wait for the printer to be online
    if VERBOSITY != VERBOSITY_SILENT:
        print("Looking for printer at: {}...".format(ip))
    while not um.is_online:
        sleep(1)

    # wait for a print to start then grab job data
    print("Waiting for print to begin...")
    while um.is_online:
        job_details = um.get_job_status()
        if job_details.is_printing:
            capture_timelapse(um, job_details.name, video_directory, video_duration, video_encoding_executor)

            #  If single print, exit on a single capture
            if capture_single_print:
                exit(0)

            #  Indicate current state
            if VERBOSITY != VERBOSITY_SILENT:
                print("Waiting for print job...")
