#include "caos_bdface.h"

#include <cstring>
#include <exception>
#include <string>
#include <vector>

#include "baidu_face_api.h"
#include "opencv2/opencv.hpp"
#include "struct_info.h"

namespace {

struct CaosBdFaceState {
    BaiduFaceApi* api = nullptr;
    bool initialized = false;
};

CaosBdFaceState* state_from(CaosBdFaceHandle handle) {
    return static_cast<CaosBdFaceState*>(handle);
}

cv::Mat to_mat(const uint8_t* pixels, int width, int height, int channels) {
    if (pixels == nullptr || width <= 0 || height <= 0) {
        throw std::invalid_argument("invalid image");
    }
    int type = CV_8UC1;
    if (channels == 3) {
        type = CV_8UC3;
    } else if (channels == 4) {
        type = CV_8UC4;
    } else if (channels != 1) {
        throw std::invalid_argument("unsupported channels");
    }
    cv::Mat source(height, width, type, const_cast<uint8_t*>(pixels));
    cv::Mat image = source.clone();
    if (channels == 4) {
        cv::cvtColor(image, image, cv::COLOR_BGRA2BGR);
    }
    return image;
}

int copy_string(const std::string& value, char* out, int capacity) {
    if (out == nullptr || capacity <= 0) {
        return -1;
    }
    std::strncpy(out, value.c_str(), static_cast<size_t>(capacity - 1));
    out[capacity - 1] = '\0';
    return 0;
}

}  // namespace

extern "C" {

CAOS_BDFACE_EXPORT CaosBdFaceHandle caos_bdface_create(void) {
    try {
        auto* state = new CaosBdFaceState();
        state->api = new BaiduFaceApi();
        return state;
    } catch (...) {
        return nullptr;
    }
}

CAOS_BDFACE_EXPORT void caos_bdface_destroy(CaosBdFaceHandle handle) {
    auto* state = state_from(handle);
    if (state == nullptr) {
        return;
    }
    if (state->api != nullptr) {
        delete state->api;
    }
    delete state;
}

CAOS_BDFACE_EXPORT int caos_bdface_init(CaosBdFaceHandle handle, const char* model_path) {
    auto* state = state_from(handle);
    if (state == nullptr || state->api == nullptr) {
        return -1;
    }
    try {
        const char* path = (model_path == nullptr || model_path[0] == '\0') ? nullptr : model_path;
        int result = state->api->sdk_init(path);
        state->initialized = (result == 0);
        return result;
    } catch (const std::exception&) {
        return -2;
    } catch (...) {
        return -3;
    }
}

CAOS_BDFACE_EXPORT int caos_bdface_is_authorized(CaosBdFaceHandle handle) {
    auto* state = state_from(handle);
    if (state == nullptr || state->api == nullptr || !state->initialized) {
        return 0;
    }
    try {
        return state->api->is_auth() ? 1 : 0;
    } catch (...) {
        return 0;
    }
}

CAOS_BDFACE_EXPORT int caos_bdface_device_id(CaosBdFaceHandle handle, char* out, int capacity) {
    auto* state = state_from(handle);
    if (state == nullptr || state->api == nullptr) {
        return -1;
    }
    try {
        std::string device_id;
        state->api->get_device_id(device_id);
        return copy_string(device_id, out, capacity);
    } catch (...) {
        return -2;
    }
}

CAOS_BDFACE_EXPORT int caos_bdface_detect(CaosBdFaceHandle handle,
                                          const uint8_t* pixels, int width,
                                          int height, int channels,
                                          float* boxes, int box_capacity,
                                          int* box_count) {
    auto* state = state_from(handle);
    if (state == nullptr || state->api == nullptr || box_count == nullptr) {
        return -1;
    }
    try {
        cv::Mat image = to_mat(pixels, width, height, channels);
        std::vector<FaceBox> faces;
        int rc = state->api->detect(faces, &image, 0);
        if (rc != 0) {
            *box_count = 0;
            return rc;
        }
        int count = static_cast<int>(faces.size());
        if (boxes != nullptr && box_capacity >= 0 && count > box_capacity) {
            count = box_capacity;
        }
        for (int i = 0; i < count; ++i) {
            const FaceBox& item = faces[static_cast<size_t>(i)];
            float values[6] = {
                static_cast<float>(item.index), item.center_x, item.center_y,
                item.width, item.height, item.score
            };
            if (boxes != nullptr) {
                std::memcpy(boxes + i * 6, values, sizeof(values));
            }
        }
        *box_count = count;
        return 0;
    } catch (const std::exception&) {
        return -2;
    } catch (...) {
        return -3;
    }
}

CAOS_BDFACE_EXPORT int caos_bdface_extract(CaosBdFaceHandle handle,
                                           const uint8_t* pixels, int width,
                                           int height, int channels,
                                           float* feature, int feature_capacity,
                                           int* feature_size, float* box) {
    auto* state = state_from(handle);
    if (state == nullptr || state->api == nullptr || feature == nullptr ||
        feature_size == nullptr || feature_capacity < 128) {
        return -1;
    }
    try {
        cv::Mat image = to_mat(pixels, width, height, channels);
        std::vector<Feature> features;
        std::vector<FaceBox> boxes;
        int rc = state->api->face_feature(features, boxes, &image, 0);
        if (rc != 0 || features.empty()) {
            *feature_size = 0;
            return rc != 0 ? rc : -4;
        }
        const Feature& item = features[0];
        int size = item.size;
        if (size > feature_capacity) {
            return -5;
        }
        std::memcpy(feature, item.data, static_cast<size_t>(size) * sizeof(float));
        *feature_size = size;
        if (box != nullptr && !boxes.empty()) {
            const FaceBox& b = boxes[0];
            float values[6] = {
                static_cast<float>(b.index), b.center_x, b.center_y,
                b.width, b.height, b.score
            };
            std::memcpy(box, values, sizeof(values));
        }
        return 0;
    } catch (const std::exception&) {
        return -2;
    } catch (...) {
        return -3;
    }
}

CAOS_BDFACE_EXPORT int caos_bdface_compare(CaosBdFaceHandle handle,
                                           const float* left, int left_size,
                                           const float* right, int right_size,
                                           float* score) {
    auto* state = state_from(handle);
    if (state == nullptr || state->api == nullptr || left == nullptr ||
        right == nullptr || score == nullptr || left_size <= 0 || right_size <= 0) {
        return -1;
    }
    try {
        Feature a{};
        Feature b{};
        a.size = left_size > 128 ? 128 : left_size;
        b.size = right_size > 128 ? 128 : right_size;
        std::memcpy(a.data, left, static_cast<size_t>(a.size) * sizeof(float));
        std::memcpy(b.data, right, static_cast<size_t>(b.size) * sizeof(float));
        *score = state->api->compare_feature(&a, &b, 0);
        return 0;
    } catch (const std::exception&) {
        return -2;
    } catch (...) {
        return -3;
    }
}

CAOS_BDFACE_EXPORT int caos_bdface_rgb_liveness(CaosBdFaceHandle handle,
                                                 const uint8_t* pixels,
                                                 int width, int height,
                                                 int channels, float* score) {
    auto* state = state_from(handle);
    if (state == nullptr || state->api == nullptr || score == nullptr) {
        return -1;
    }
    try {
        cv::Mat image = to_mat(pixels, width, height, channels);
        std::vector<FaceBox> boxes;
        return state->api->rgb_liveness(boxes, *score, &image);
    } catch (const std::exception&) {
        return -2;
    } catch (...) {
        return -3;
    }
}

}  // extern "C"
