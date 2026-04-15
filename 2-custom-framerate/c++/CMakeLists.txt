cmake_minimum_required(VERSION 3.0.0)
project(Main VERSION 0.1.0)

find_package(OpenCV REQUIRED)
include_directories( ${OpenCV_INCLUDE_DIRS} )

add_executable(main.bin main.cpp)

target_link_libraries( main.bin ${OpenCV_LIBS} )
