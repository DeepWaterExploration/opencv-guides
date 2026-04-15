#include <opencv2/opencv.hpp>

// -- Camera Parameters --
// Camera Index
const int CAM_IDX = 0;
// resolution
const int WIDTH = 1920;
const int HEIGHT = 1080;
// used to set the pixel format to MJPEG/MJPG mode.
const int MJPG = cv::VideoWriter::fourcc('M', 'J', 'P', 'G');

// For H.264, see this: https://github.com/opencv/opencv-python/issues/100#issuecomment-394159998

int main() {

    // -- DEVICE SETUP --
    cv::VideoCapture exploreHD = cv::VideoCapture(CAM_IDX, cv::CAP_V4L2); //V4L2 -> Video 4 Linux

    // set to MJPEG mode, by default idx 0 is YUYV
    // MJPG needs to be set, before resolution. Pixel format is always selected first
    exploreHD.set(cv::CAP_PROP_FOURCC, MJPG);

    exploreHD.set(cv::CAP_PROP_FRAME_WIDTH, WIDTH);
    exploreHD.set(cv::CAP_PROP_FRAME_HEIGHT, HEIGHT);

    // (Optional) Disable auto exposure
    exploreHD.set(cv::CAP_PROP_AUTO_EXPOSURE, 1);
    exploreHD.set(cv::CAP_PROP_EXPOSURE, 90);

    // create Matrix for frame data
    cv::Mat exploreHDFrame;

    while(true) {
        bool success = exploreHD.read(exploreHDFrame);

        if (success) {
            cv::imshow("exploreHD", exploreHDFrame);
        }

        // required for frames to buffer and show properly.
        if (cv::waitKey(1) == 'q') {
            break;
        }
    }

    exploreHD.release();
    cv::destroyAllWindows();

    return 0;
}