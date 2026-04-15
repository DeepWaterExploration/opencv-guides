import cv2

# -- Camera Parameters --
# Camera Index
CAM_IDX = 0
# resolution
WIDTH = 1920
HEIGHT = 1080
# used to set the pixel format to MJPEG/MJPG mode.
MJPG = cv2.VideoWriter_fourcc(*'MJPG')

# For H.264, see this: https://github.com/opencv/opencv-python/issues/100#issuecomment-394159998

# -- DEVICE SETUP --
exploreHD = cv2.VideoCapture(CAM_IDX)

# set to MJPEG mode, by default idx 0 is YUYV
# MJPG needs to be set, before resolution. Pixel format is always selected first
exploreHD.set(cv2.CAP_PROP_FOURCC, MJPG)

exploreHD.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
exploreHD.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

# (Optional) Disable auto exposure
exploreHD.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
exploreHD.set(cv2.CAP_PROP_EXPOSURE, 90)

# Error Check
if ((exploreHD == None) or (not exploreHD.isOpened())):
    print('\nError - could not open video device.\n')
    exit(0)

while(True):
    success, frame = exploreHD.read()
    if (success):
        cv2.imshow('exploreHD', frame)
    
    # required for frames to buffer and show properly.
    k = cv2.waitKey(1)

    # press 'q' to quit
    if k == ord('q'):
        break
    
exploreHD.release()
cv2.destroyAllWindows()