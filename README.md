# UM3-Capture - Ultimaker 3 timelapse video capture service
Capture time-lapse videos using Ultimaker 3 apis. Inspired by https://github.com/unlimitedbacon/um3timelapse but designed to run continuously and unmonitored on a Raspberry Pi.
* Identifies when the target printer is on-line and printing capturing a new timelapse for every print
* Automatically captures frames at the rate needed to create a timelapse video of the target duration (20s by default)
* Output files are auto-named based on the print job name
* Videos are encoded in the background allowing the script to capture timelapses of back-to-back printing
* Behaves responsibly if the printer goes off-line, automatically resuming when it comes back on-line
* Lot's of configuration options
## Usage
|Option|Description|Default|
|------|-----------|-------|
|--ip  |IP address of the ultimaker|none|
|-t, --timelapsedir|Directory for the final timelapse video|/tmp|
|-d, --duration|Target duration of output video|20s|
|-n, --noclean|Don't clean up temporary files when done|clean up directories|
|-v, --verbosity|Output verbosity|0=errors only, 1=normal, 2=verbose, 3=debug|1|
|-f, --foreground|Encode video in the foreground (normally it's processed in the background|background|
|-s, --singeprint|Capture a single print then exit|continous capture|
