const api = require('../../utils/api');
const app = getApp();

Page({
  data: { rows: [], loading: false, keyword: '', isAdmin: false },

  onLoad() {
    this.setData({ isAdmin: app.globalData.role === 'admin' });
    this.load();
  },

  onInput(e) { this.setData({ keyword: e.detail.value }); },

  async load() {
    this.setData({ loading: true });
    try {
      const q = this.data.isAdmin && this.data.keyword ? ('?subject=' + encodeURIComponent(this.data.keyword)) : '';
      const rows = await api.request('/api/mobile/records' + q);
      this.setData({ rows });
    } catch (e) {
      wx.showToast({ title: e.message, icon: 'none' });
    } finally {
      this.setData({ loading: false });
    }
  }
});
