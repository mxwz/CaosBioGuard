const api = require('../../utils/api');
const app = getApp();

Page({
  data: { subject: '', modalities: [], recent: [], isAdmin: false },

  onLoad() {
    this.setData({ subject: app.globalData.subject || '', isAdmin: app.globalData.role === 'admin' });
    this.load();
  },

  async load() {
    const subject = this.data.subject;
    if (!subject) return;
    try {
      const d = await api.request('/api/mobile/profile?subject=' + encodeURIComponent(subject));
      this.setData({ modalities: d.modalities || [], recent: d.recent || [] });
    } catch (e) { wx.showToast({ title: e.message, icon: 'none' }); }
  }
});
