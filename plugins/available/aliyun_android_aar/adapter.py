from biometrics.adapters.aliyun import AliyunAndroidAARAdapter


class Plugin(AliyunAndroidAARAdapter):
    def __init__(self, config=None):
        super().__init__(config=config)
