#include <opencv2/opencv.hpp>
#include <chrono>

// -- Camera Parameters --
// Camera Index
const int CAM_IDX = 0;
// Resolution
const int WIDTH = 1600;
const int HEIGHT = 1200;

// Framerate
const int FRAMERATE = 60;

// Custom framerate
const int CUSTOM_FRAMERATE = 10;

// Interval in milliseconds to achieve custom framerate
const int FRAME_INTERVAL = 1000 / CUSTOM_FRAMERATE;

// Used to set the pixel format to MJPEG/MJPG mode.
const int MJPG = cv::VideoWriter::fourcc('M', 'J', 'P', 'G');

int main() {
    // -- DEVICE SETUP --
    cv::VideoCapture stellarHD = cv::VideoCapture(CAM_IDX, cv::CAP_V4L2); // V4L2 -> Video 4 Linux

    // Set to MJPEG mode, by default idx 0 is YUYV
    // MJPG needs to be set, before resolution. Pixel format is always selected first
    stellarHD.set(cv::CAP_PROP_FOURCC, MJPG);

    stellarHD.set(cv::CAP_PROP_FRAME_WIDTH, WIDTH);
    stellarHD.set(cv::CAP_PROP_FRAME_HEIGHT, HEIGHT);

    // Set framerate
    stellarHD.set(cv::CAP_PROP_FPS, FRAMERATE);

    // (Optional) Disable auto exposure
    stellarHD.set(cv::CAP_PROP_AUTO_EXPOSURE, 1);
    stellarHD.set(cv::CAP_PROP_EXPOSURE, 90);

    // Create Matrix for frame data
    cv::Mat stellarHDFrame;

    // Timing variables
    auto lastFrameTime = std::chrono::high_resolution_clock::now();

    while(true) {
        auto start = std::chrono::high_resolution_clock::now();
        bool success = stellarHD.read(stellarHDFrame);

        if (success) {
            cv::imshow("stellarHD", stellarHDFrame);
        }

        auto elapsed = std::chrono::high_resolution_clock::now() - start;
        int elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count();

        // Calculate remaining time to wait to maintain the desired frame rate
        int waitTime = FRAME_INTERVAL - elapsed_ms;
        waitTime = std::max(1, waitTime); // Ensuring at least 1ms to prevent freezing

        if (cv::waitKey(waitTime) == 'q') {
            break;
        }
    }

    stellarHD.release();
    cv::destroyAllWindows();

    return 0;
}
