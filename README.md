# UM3-Capture - Ultimaker 3 timelapse video capture service
Capture time-lapse videos using Ultimaker 3 apis. Designed to run continuously and automatically generate time 
lapse videos of every print done on an UM3.

I created this based on the concept of a set and forget UM3 timelapse
server that I could run on a Raspberry Pi and have it automagically generate time lapse videos that got dumped to
a folder on my Synology NAS. 

This was inspired by: https://github.com/unlimitedbacon/um3timelapse - Thank You!

* Identifies when the target printer is on-line and printing, then captures a new time lapse video for every print
* Automatically caluclates and captures frames at the rate needed to create a video of the target
duration (20s by default)
* Video files are auto-named based on the print job name
* Videos are encoded in the background allowing the script to capture and encode videos during back-to-back printing
* Behaves responsibly if the printer goes off-line, automatically resuming when it comes back on-line
* Lot's of configuration options
## Usage
|Option|Description|Default|
|------|-----------|-------|
|--ip|IP address of the ultimaker||
|-t, --timelapsedir|Directory for the final timelapse video|OS "/tmp"|
|-d, --duration|Target duration of output video|20s|
|-n, --noclean|Don't clean up temporary files when done||
|-v, --verbosity|Output verbosity|0=errors only, 1=normal, 2=verbose, 3=debug|1|
|-f, --foreground|Encode video in the foreground (normally it's processed in the background||
|-s, --singleprint|Capture a single print then exit||
