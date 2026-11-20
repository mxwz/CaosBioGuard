from biometrics.adapters.aliyun import AliyunFacebodyAdapter


class Plugin(AliyunFacebodyAdapter):
    def __init__(self, config=None):
        super().__init__(config=config)
