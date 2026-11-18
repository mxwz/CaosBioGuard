App({
  globalData: {
    // 真机调试请改成已在小程序后台配置的 HTTPS 域名，例如 https://caos.example.com
    baseUrl: 'http://127.0.0.1:5000',
    token: '',
    subject: '',
    role: ''
  },
  onLaunch() {
    const saved = wx.getStorageSync('caos-session') || {};
    this.globalData.token = saved.token || '';
    this.globalData.subject = saved.subject || '';
    this.globalData.role = saved.role || '';
  }
});
