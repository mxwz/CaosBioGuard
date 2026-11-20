cmake_minimum_required(VERSION 3.20)
project(caos_bdface LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "Baidu wrapper currently requires x64")
endif()

set(BDFACE_SDK_ROOT "" CACHE PATH "Path to extracted FaceOfflineSdk root")
if(NOT BDFACE_SDK_ROOT)
  message(FATAL_ERROR "Set BDFACE_SDK_ROOT to extracted FaceOfflineSdk directory")
endif()

set(SDK_DIR "${BDFACE_SDK_ROOT}/FaceOfflineSdk")

add_library(caos_bdface SHARED
  caos_bdface.cpp
  caos_bdface.h
)

target_include_directories(caos_bdface PRIVATE
  "${SDK_DIR}/include"
  "${SDK_DIR}/face_scene/include"
  "${SDK_DIR}/third_party/opencv-win/include"
)

target_link_libraries(caos_bdface PRIVATE
  "${SDK_DIR}/lib/x64/BaiduFaceApi.lib"
  "${SDK_DIR}/lib/x64/opencv_world320.lib"
)

if(MSVC)
  target_compile_options(caos_bdface PRIVATE /W3 /EHsc)
endif()
