const api = require('../../utils/api');
const app = getApp();

Page({
  data: {
    mode: 'admin', token: '', subject: '', logged: false, role: '',
    loading: false, overview: null,
    stats: { users: 0, devices: 0, templates: 0, requests: 0, today: 0 }
  },

  onLoad() {
    if (app.globalData.token || app.globalData.subject) {
      this.setData({ logged: true, role: app.globalData.role });
      this.loadOverview();
    }
  },

  switchMode(e) {
    this.setData({ mode: e.currentTarget.dataset.mode });
  },

  onInput(e) {
    this.setData({ [e.currentTarget.dataset.field]: e.detail.value });
  },

  async login() {
    const body = this.data.mode === 'admin'
      ? { token: this.data.token.trim() }
      : { subject: this.data.subject.trim() };
    if (this.data.mode === 'admin' && !body.token) return wx.showToast({ title: '请输入 Token', icon: 'none' });
    if (this.data.mode === 'user' && !body.subject) return wx.showToast({ title: '请输入工号/姓名', icon: 'none' });
    this.setData({ loading: true });
    try {
      const out = await api.request('/api/mobile/login', { method: 'POST', data: body });
      app.globalData.token = this.data.mode === 'admin' ? body.token : '';
      app.globalData.subject = out.subject || '';
      app.globalData.role = out.role;
      wx.setStorageSync('caos-session', { token: app.globalData.token, subject: app.globalData.subject, role: out.role });
      this.setData({ logged: true, role: out.role });
      this.loadOverview();
    } catch (e) {
      wx.showToast({ title: e.message, icon: 'none' });
    } finally {
      this.setData({ loading: false });
    }
  },

  async loadOverview() {
    try {
      const d = await api.request('/api/mobile/overview');
      this.setData({
        overview: d,
        stats: {
          users: (d.stats && d.stats.user && d.stats.user.total) || 0,
          devices: (d.devices || []).length,
          templates: (d.biometrics && d.biometrics.total) || 0,
          requests: d.requests || 0,
          today: d.today_attendance || 0
        }
      });
    } catch (e) {
      wx.showToast({ title: e.message, icon: 'none' });
    }
  },

  goRecords() { wx.navigateTo({ url: '/pages/records/records' }); },
  goEnroll() { wx.navigateTo({ url: '/pages/enroll/enroll' }); },
  goProfile() { wx.navigateTo({ url: '/pages/profile/profile' }); },

  logout() {
    app.globalData.token = '';
    app.globalData.subject = '';
    app.globalData.role = '';
    wx.removeStorageSync('caos-session');
    this.setData({ logged: false, overview: null });
  }
});
