#ifndef CAOS_BDFACE_H
#define CAOS_BDFACE_H

#include <stdint.h>

#ifdef _WIN32
#define CAOS_BDFACE_EXPORT __declspec(dllexport)
#else
#define CAOS_BDFACE_EXPORT
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void* CaosBdFaceHandle;

CAOS_BDFACE_EXPORT CaosBdFaceHandle caos_bdface_create(void);
CAOS_BDFACE_EXPORT void caos_bdface_destroy(CaosBdFaceHandle handle);
CAOS_BDFACE_EXPORT int caos_bdface_init(CaosBdFaceHandle handle, const char* model_path);
CAOS_BDFACE_EXPORT int caos_bdface_is_authorized(CaosBdFaceHandle handle);
CAOS_BDFACE_EXPORT int caos_bdface_device_id(CaosBdFaceHandle handle, char* out, int capacity);
CAOS_BDFACE_EXPORT int caos_bdface_detect(CaosBdFaceHandle handle,
                                          const uint8_t* pixels, int width,
                                          int height, int channels,
                                          float* boxes, int box_capacity,
                                          int* box_count);
CAOS_BDFACE_EXPORT int caos_bdface_extract(CaosBdFaceHandle handle,
                                           const uint8_t* pixels, int width,
                                           int height, int channels,
                                           float* feature, int feature_capacity,
                                           int* feature_size, float* box);
CAOS_BDFACE_EXPORT int caos_bdface_compare(CaosBdFaceHandle handle,
                                           const float* left, int left_size,
                                           const float* right, int right_size,
                                           float* score);
CAOS_BDFACE_EXPORT int caos_bdface_rgb_liveness(CaosBdFaceHandle handle,
                                                 const uint8_t* pixels,
                                                 int width, int height,
                                                 int channels, float* score);

#ifdef __cplusplus
}
#endif

#endif
