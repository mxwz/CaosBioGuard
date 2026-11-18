const api = require('../../utils/api');
const app = getApp();

Page({
  data: {
    modalities: [], modalityIndex: 0, subject: '', filePath: '', strokes: '',
    isAdmin: false, result: '', busy: false
  },

  onLoad() {
    this.setData({ isAdmin: app.globalData.role === 'admin', subject: app.globalData.subject || '' });
    this.loadModalities();
  },

  async loadModalities() {
    try {
      const list = await api.request('/api/mobile/modalities');
      this.setData({ modalities: list.filter(m => m.name !== 'face') });
    } catch (e) { wx.showToast({ title: e.message, icon: 'none' }); }
  },

  onSubject(e) { this.setData({ subject: e.detail.value }); },
  onStrokes(e) { this.setData({ strokes: e.detail.value }); },
  onModality(e) { this.setData({ modalityIndex: Number(e.detail.value), filePath: '' }); },

  current() { return this.data.modalities[this.data.modalityIndex] || {}; },

  choose() {
    const m = this.current();
    if (!m.name) return;
    if (m.kind === 'audio') {
      wx.chooseMessageFile({
        count: 1, type: 'file', extension: ['wav'],
        success: res => this.setData({ filePath: res.tempFiles[0].path })
      });
    } else if (m.kind === 'frames') {
      wx.chooseMedia({
        count: 1, mediaType: ['video'], sourceType: ['album', 'camera'],
        success: res => this.setData({ filePath: res.tempFiles[0].tempFilePath })
      });
    } else {
      wx.chooseMedia({
        count: 1, mediaType: ['image'], sourceType: ['album', 'camera'],
        success: res => this.setData({ filePath: res.tempFiles[0].tempFilePath })
      });
    }
  },

  async submit() {
    const m = this.current();
    const subject = this.data.subject.trim();
    if (!subject) return wx.showToast({ title: '请填写主体', icon: 'none' });
    if (!m.name) return;
    if (!this.data.isAdmin) {
      try {
        await api.request('/api/mobile/enroll-request', {
          method: 'POST', data: { subject, modality: m.name, note: '小程序提交' }
        });
        this.setData({ result: '申请已提交，等待管理员采集。' });
        wx.showToast({ title: '已提交' });
      } catch (e) { this.setData({ result: '提交失败：' + e.message }); }
      return;
    }
    if (!this.data.filePath && !this.data.strokes) {
      return wx.showToast({ title: '请选择样本或填写签名轨迹', icon: 'none' });
    }
    this.setData({ busy: true, result: '正在提取特征…' });
    try {
      let out;
      if (this.data.filePath) {
        out = await api.upload('/api/biometrics/enroll', this.data.filePath, {
          subject, modality: m.name
        });
      } else {
        let strokes;
        try { strokes = JSON.parse(this.data.strokes); }
        catch (e) { throw new Error('签名轨迹不是合法 JSON'); }
        out = await api.request('/api/biometrics/enroll', {
          method: 'POST', data: { subject, modality: m.name, strokes }
        });
      }
      this.setData({ result: '注册成功：质量 ' + (out.quality != null ? out.quality.toFixed(2) : '—') });
      wx.showToast({ title: '注册成功' });
    } catch (e) {
      this.setData({ result: '注册失败：' + e.message });
    } finally {
      this.setData({ busy: false });
    }
  }
});
