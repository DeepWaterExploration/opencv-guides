import cv2
import time

# -- Camera Parameters --
# Camera Index
CAM_IDX = 0
# resolution
WIDTH = 1600
HEIGHT = 1200

# Set a desired custom framerate, by reading frames at a custom interval
# custom framerate must be less than the highest supported framerate of camera
CUSTOM_FRAMERATE = 10

# Hardware supported framerate of the camera. Highest for best results.
FRAMERATE = 60

# used to set the pixel format to MJPEG/MJPG mode.
MJPG = cv2.VideoWriter_fourcc(*'MJPG')

# -- DEVICE SETUP --
stellarHD = cv2.VideoCapture(CAM_IDX)

# set to MJPEG mode, by default idx 0 is YUYV
# MJPG needs to be set, before resolution. Pixel format is always selected first
stellarHD.set(cv2.CAP_PROP_FOURCC, MJPG)

stellarHD.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
stellarHD.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

# Set framerate
stellarHD.set(cv2.CAP_PROP_FPS, FRAMERATE)

# (Optional) Disable auto exposure
stellarHD.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
stellarHD.set(cv2.CAP_PROP_EXPOSURE, 90)

# Calculate delay
frame_interval = int(1000 / CUSTOM_FRAMERATE)  # in milliseconds

# Error Check
if ((stellarHD == None) or (not stellarHD.isOpened())):
    print('\nError - could not open video device.\n')
    exit(0)

while(True):
    start_time = time.time()
    
    success, frame = stellarHD.read()
    if (success):
        cv2.imshow('stellarHD', frame)
    
    # Calculate remaining time to wait to maintain the desired frame rate
    elapsed_time = (time.time() - start_time) * 1000  # convert to ms
    wait_time = max(1, frame_interval - int(elapsed_time))  # calculate how long to wait

    # Use waitKey to introduce the delay and capture key press
    if cv2.waitKey(wait_time) == ord('q'):
        break

stellarHD.release()
cv2.destroyAllWindows()