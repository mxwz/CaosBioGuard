"""X2000 人脸 / 掌静脉识别模组 —— 通信协议常量与枚举。

本模块集中定义《X2000 人脸识别模组通信协议 V1.0》中的全部指令码、结果码、
状态码、录入方向等常量，以及对应的中文名称映射，供驱动层其它模块统一引用。

字节序约定（与官方协议一致，除特别注明外均为大端 / MSB）：
- 帧头 ``0xEF 0xAA``
- 帧长 ``Size`` 为 2 字节大端
- ``user_id`` 为 ``user_id_heb(高) + user_id_leb(低)`` 两字节大端
- 图片大小 / 偏移量均为 4 字节大端
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 帧头
# ---------------------------------------------------------------------------
SYNC_WORD = bytes([0xEF, 0xAA])

# ---------------------------------------------------------------------------
# 消息类型（模块 -> 主控）
# ---------------------------------------------------------------------------
MID_REPLY = 0x00   # 命令应答
MID_NOTE = 0x01    # 主动上报（READY / 人脸状态 / OTA 等）
MID_IMAGE = 0x02   # 图片数据

# ---------------------------------------------------------------------------
# 命令码（主控 -> 模块）
# ---------------------------------------------------------------------------
MID_RESET = 0x10                 # 复位到 standby
MID_GETSTATUS = 0x11             # 获取模块状态
MID_VERIFY = 0x12                # 鉴权解锁
MID_ENROLL = 0x13                # 交互式录入（五方向）
MID_SNAPIMAGE = 0x16             # 抓拍图片并存储
MID_GETSAVEDIMAGE = 0x17         # 获取待上传图片大小
MID_UPLOADIMAGE = 0x18           # 上传本地图片到主控
MID_ENROLL_SINGLE = 0x1D         # 单帧录入（正脸 / 掌静脉 / 照片下发）
MID_DELUSER = 0x20               # 删除单个用户
MID_DELALL = 0x21                # 批量删除用户
MID_GETUSERINFO = 0x22           # 获取用户信息
MID_FACERESET = 0x23             # 重置算法状态
MID_GET_ALL_USERID = 0x24        # 获取所有已注册用户 ID
MID_ENROLL_ITG = 0x26            # 集成录入（扩展所有录入方式）
MID_GET_VERSION = 0x30           # 获取软件版本
MID_START_OTA = 0x40             # 进入 OTA 升级模式
MID_STOP_OTA = 0x41              # 退出 OTA 并重启
MID_GET_OTA_STATUS = 0x42        # 获取 OTA 状态
MID_OTA_HEADER = 0x43            # 发送升级包头信息
MID_OTA_PACKET = 0x44            # 发送升级分包
MID_INIT_ENCRYPTION = 0x50       # 设置加密随机数
MID_CONFIG_BAUDRATE = 0x51       # OTA 模式设定波特率
MID_SET_RELEASE_ENC_KEY = 0x52   # 设定量产加密密钥（掉电保存）
MID_SET_DEBUG_ENC_KEY = 0x53     # 设定调试加密密钥（掉电丢失）
MID_GET_LOGFILE = 0x60           # 保存 log 到内存
MID_UPLOAD_LOGFILE = 0x61        # 上传 log 到主控
MID_UVC_DIR = 0x76               # 旋转镜头视频方向
MID_TRANS_FILE_PACKET = 0x90     # 传输文件数据（图片注册 / 注册数据下发）
MID_ENROLL_FROM_IMAGE = 0x91     # 从已下发图片注册
MID_GET_UID = 0x93               # 获取设备 ID
MID_CAMERA_FLIP = 0xC2           # 红外镜头识别方向
MID_FUNC_CTRL = 0xC7             # 打开 / 关闭特定功能
MID_SET_THRESHOLD_LEVEL = 0xD4   # 设置算法安全等级
MID_GETLIBRARY_VERSION = 0xF3    # 获取库版本信息
MID_DEMOMODE = 0xFE              # 演示模式
MID_SNAPIMAGE2 = 0xFF            # 抓取人脸部分图像

# ---------------------------------------------------------------------------
# 命令结果码（MID_REPLY 的 result 字段）
# ---------------------------------------------------------------------------
MR_SUCCESS = 0                     # 成功
MR_REJECTED = 1                    # 模块拒绝该命令
MR_ABORTED = 2                     # 录入 / 解锁算法已终止
MR_FAILED4_CAMERA = 4              # 相机打开失败
MR_FAILED4_UNKNOWNREASON = 5       # 未知错误
MR_FAILED4_INVALIDPARAM = 6        # 无效参数
MR_FAILED4_NOMEMORY = 7            # 内存不足
MR_FAILED4_UNKNOWNUSER = 8         # 没有已录入的用户
MR_FAILED4_MAXUSER = 9             # 超过最大用户数量
MR_FAILED4_FACEENROLLED = 10       # 人脸已录入
MR_FAILED4_LIVENESSCHECK = 12      # 活体检测失败
MR_FAILED4_TIMEOUT = 13            # 录入或解锁超时
MR_FAILED4_AUTHORIZATION = 14      # 加密芯片授权失败
MR_FAILED4_READ_FILE = 19          # 读文件失败
MR_FAILED4_WRITE_FILE = 20         # 写文件失败
MR_FAILED4_NO_ENCRYPT = 21         # 通信协议未加密
MR_FAILED4_NO_RGBIMAGE = 23        # RGB 图像没有 ready
MR_FAILED4_UNKNOWN_HANDUSER = 239  # 掌静脉验证失败
MR_FAILED4_NOCAMERA = 240          # 不支持彩色镜头
MR_FAILED4_HANDENROLLED = 241      # 掌静脉重复

# ---------------------------------------------------------------------------
# NOTE 消息 nid（模块主动上报）
# ---------------------------------------------------------------------------
NID_READY = 0        # 模块已准备好
NID_FACE_STATE = 1   # 算法执行成功，返回人脸信息
NID_UNKNOWNERROR = 2  # 未知错误
NID_OTA_DONE = 3     # OTA 升级完毕
NID_EYE_STATE = 4    # 解锁过程中睁闭眼状态

# ---------------------------------------------------------------------------
# 人脸 / 手掌状态（s_note_data_face.state）
# ---------------------------------------------------------------------------
FACE_STATE_NORMAL = 0                 # 人脸正常
FACE_STATE_NOFACE = 1                 # 未检测到人脸
FACE_STATE_TOOUP = 2                  # 人脸太靠近上边沿
FACE_STATE_TOODOWN = 3                # 人脸太靠近下边沿
FACE_STATE_TOOLEFT = 4                # 人脸太靠近左边沿
FACE_STATE_TOORIGHT = 5               # 人脸太靠近右边沿
FACE_STATE_FAR = 6                    # 人脸距离太远
FACE_STATE_CLOSE = 7                  # 人脸距离太近
FACE_STATE_EYEBROW_OCCLUSION = 8      # 眉毛遮挡
FACE_STATE_EYE_OCCLUSION = 9          # 眼睛遮挡
FACE_STATE_FACE_OCCLUSION = 10        # 脸部遮挡
FACE_STATE_DIRECTION_ERROR = 11       # 录入人脸方向错误
FACE_STATE_EYE_CLOSE_OPEN = 12        # 闭眼模式检测到睁眼
FACE_STATE_EYE_CLOSE = 13             # 闭眼状态
FACE_STATE_EYE_CLOSE_UNKNOWN = 14     # 无法判定睁闭眼
FACE_STATE_HAND_NORMAL = 128          # 检测到掌静脉
FACE_STATE_HAND_FAR = 129             # 手掌太远
FACE_STATE_HAND_CLOSE = 130           # 手掌太近
FACE_STATE_HAND_TOOUP = 131           # 手掌太靠近上边沿
FACE_STATE_HAND_TOODOWN = 132         # 手掌太靠近下边沿
FACE_STATE_HAND_TOOLEFT = 133         # 手掌太靠近左边沿
FACE_STATE_HAND_TOORIGHT = 134        # 手掌太靠近右边沿

# ---------------------------------------------------------------------------
# 录入方向（face_direction）
# ---------------------------------------------------------------------------
FACE_DIRECTION_UP = 0x10              # 朝上
FACE_DIRECTION_DOWN = 0x08            # 朝下
FACE_DIRECTION_LEFT = 0x04            # 朝左
FACE_DIRECTION_RIGHT = 0x02           # 朝右
FACE_DIRECTION_MIDDLE = 0x01          # 正向
FACE_DIRECTION_UNDEFINE = 0x00        # 未定义（默认正向）
FACE_DIRECTION_FACE_ONLY = 0x40       # 仅检测人脸注册（预留）
FACE_DIRECTION_RENT = 0xFC            # 单帧注册后回传注册数据
FACE_DIRECTION_HAND = 0xFD            # 录入掌静脉
FACE_DIRECTION_PICTURE = 0xFE         # 照片下发注册

# ---------------------------------------------------------------------------
# 鉴权模式（MID_VERIFY 的 verify_mode）
# ---------------------------------------------------------------------------
VERIFY_MODE_STANDARD = 0   # 标准（人脸）
VERIFY_MODE_PALM = 1       # 掌静脉（预留）
VERIFY_MODE_IRIS = 2       # 虹膜（预留）
VERIFY_MODE_QR = 4         # 二维码识别（预留）
VERIFY_MODE_FACE_PALM = 8  # 人脸 / 掌静脉（预留）

# ---------------------------------------------------------------------------
# 解锁状态（MID_VERIFY 应答的 unlockStatus）
# ---------------------------------------------------------------------------
UNLOCK_FACE_SUCCESS = 200            # 人脸验证成功
UNLOCK_FACE_SUCCESS_EYE_CLOSED = 204  # 人脸验证成功（闭眼）
UNLOCK_PALM_SUCCESS = 250            # 掌静脉验证成功

# ---------------------------------------------------------------------------
# 模块工作状态（MID_GETSTATUS 应答）
# ---------------------------------------------------------------------------
MS_STANDBY = 0   # 空闲，等待命令
MS_BUSY = 1      # 工作状态
MS_ERROR = 2     # 出错
MS_INVALID = 3   # 未初始化
MS_OTA = 4       # OTA 升级中

# ---------------------------------------------------------------------------
# 用户类型（MID_DELUSER 的 user_type）
# ---------------------------------------------------------------------------
USER_TYPE_FACE = 0   # 人脸
USER_TYPE_PALM = 1   # 掌静脉

# ---------------------------------------------------------------------------
# 批量删除类型（MID_DELALL 的 type）
# ---------------------------------------------------------------------------
DELALL_TYPE_ALL = 0          # 删除所有用户
DELALL_TYPE_FACE = 1         # 删除人脸用户
DELALL_TYPE_PALM = 2         # 删除掌静脉用户
DELALL_TYPE_NORMAL = 3       # 删除普通用户
DELALL_TYPE_RANGE = 4        # 删除指定范围用户

# ---------------------------------------------------------------------------
# 名称映射（用于日志与调试输出）
# ---------------------------------------------------------------------------
RESULT_NAMES = {
    MR_SUCCESS: '成功',
    MR_REJECTED: '模块拒绝该命令',
    MR_ABORTED: '算法已终止',
    MR_FAILED4_CAMERA: '相机打开失败',
    MR_FAILED4_UNKNOWNREASON: '未知错误',
    MR_FAILED4_INVALIDPARAM: '无效参数',
    MR_FAILED4_NOMEMORY: '内存不足',
    MR_FAILED4_UNKNOWNUSER: '没有已录入的用户',
    MR_FAILED4_MAXUSER: '超过最大用户数量',
    MR_FAILED4_FACEENROLLED: '人脸已录入',
    MR_FAILED4_LIVENESSCHECK: '活体检测失败',
    MR_FAILED4_TIMEOUT: '录入或解锁超时',
    MR_FAILED4_AUTHORIZATION: '加密芯片授权失败',
    MR_FAILED4_READ_FILE: '读文件失败',
    MR_FAILED4_WRITE_FILE: '写文件失败',
    MR_FAILED4_NO_ENCRYPT: '通信协议未加密',
    MR_FAILED4_NO_RGBIMAGE: 'RGB 图像没有 ready',
    MR_FAILED4_UNKNOWN_HANDUSER: '掌静脉验证失败',
    MR_FAILED4_NOCAMERA: '不支持彩色镜头',
    MR_FAILED4_HANDENROLLED: '掌静脉重复',
}

FACE_STATE_NAMES = {
    FACE_STATE_NORMAL: '人脸正常',
    FACE_STATE_NOFACE: '未检测到人脸',
    FACE_STATE_TOOUP: '人脸太靠上',
    FACE_STATE_TOODOWN: '人脸太靠下',
    FACE_STATE_TOOLEFT: '人脸太靠左',
    FACE_STATE_TOORIGHT: '人脸太靠右',
    FACE_STATE_FAR: '人脸距离太远',
    FACE_STATE_CLOSE: '人脸距离太近',
    FACE_STATE_EYEBROW_OCCLUSION: '眉毛遮挡',
    FACE_STATE_EYE_OCCLUSION: '眼睛遮挡',
    FACE_STATE_FACE_OCCLUSION: '脸部遮挡',
    FACE_STATE_DIRECTION_ERROR: '录入方向错误',
    FACE_STATE_EYE_CLOSE_OPEN: '闭眼模式检测到睁眼',
    FACE_STATE_EYE_CLOSE: '闭眼状态',
    FACE_STATE_EYE_CLOSE_UNKNOWN: '无法判定睁闭眼',
    FACE_STATE_HAND_NORMAL: '检测到掌静脉',
    FACE_STATE_HAND_FAR: '手掌太远',
    FACE_STATE_HAND_CLOSE: '手掌太近',
    FACE_STATE_HAND_TOOUP: '手掌太靠上',
    FACE_STATE_HAND_TOODOWN: '手掌太靠下',
    FACE_STATE_HAND_TOOLEFT: '手掌太靠左',
    FACE_STATE_HAND_TOORIGHT: '手掌太靠右',
}

MODULE_STATUS_NAMES = {
    MS_STANDBY: '空闲',
    MS_BUSY: '工作',
    MS_ERROR: '出错',
    MS_INVALID: '未初始化',
    MS_OTA: 'OTA 升级中',
}


def result_name(code):
    """返回结果码的可读名称，未知码返回十六进制形式。"""
    return RESULT_NAMES.get(code, '未知结果码 0x%02X' % code)


def face_state_name(state):
    """返回人脸 / 手掌状态的可读名称，未知码返回十进制形式。"""
    return FACE_STATE_NAMES.get(state, '未知状态 %d' % state)
