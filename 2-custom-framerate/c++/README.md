# Overview

This repository contains a simple C++ program, `main.cpp`, designed to interface with an stellarHD camera and display the MJPEG frames from the camera in a window at a specified custom framerate. By using a higher hardware framerate, and sampling frames at your desired frequency, you can achieve a high-quality result. The project is configured using CMake, and this README file provides instructions on how to build and run the application.

## Prerequisites

Before running the application, ensure that you have the following prerequisites installed on your system:

- C++ compiler (supporting C++11 and above)
- CMake (version 3.0.0 and above)
- OpenCV library
  - Must add the environment variable `OpenCV_INCLUDE_DIRS` and point to your OpenCV include directory.
    - `echo $OpenCV_INCLUDE_DIRS` in terminal, output: `/usr/local/include/opencv4`

## Build Instructions

1. Create a build directory and navigate into it:

    ```bash
    mkdir build
    cd build
    ```

2. Run CMake to configure the build:

    ```bash
    cmake ..
    ```

3. Build the executable:

    ```bash
    make
    ```

## Running the Application

Once the build is successful, you can run the application by executing the following command:

```bash
./main.bin
```

This will launch the program, which will attempt to connect to the stellarHD camera and display the MJPEG frames in a window.

## Configuration

If you have specific configuration requirements, you can modify the relevant parameters in the `main.cpp` file. Look for comments or constants related to camera settings and adjust them accordingly.
