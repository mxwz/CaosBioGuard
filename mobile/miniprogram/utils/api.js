const app = getApp();

function headers() {
  const h = { 'Content-Type': 'application/json' };
  if (app.globalData.token) h['Authorization'] = 'Bearer ' + app.globalData.token;
  if (app.globalData.subject) h['X-Mobile-Subject'] = app.globalData.subject;
  return h;
}

function request(path, options) {
  options = options || {};
  return new Promise((resolve, reject) => {
    wx.request({
      url: app.globalData.baseUrl + path,
      method: options.method || 'GET',
      data: options.data || {},
      header: headers(),
      success(res) {
        const body = res.data || {};
        if (res.statusCode >= 400 || body.status === 'error') {
          reject(new Error(body.error || ('HTTP ' + res.statusCode)));
        } else {
          resolve(body.data);
        }
      },
      fail(err) { reject(new Error(err.errMsg || '网络错误')); }
    });
  });
}

function upload(path, filePath, formData) {
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: app.globalData.baseUrl + path,
      filePath,
      name: 'file',
      formData,
      header: app.globalData.token ? { 'Authorization': 'Bearer ' + app.globalData.token } : {},
      success(res) {
        let body = {};
        try { body = JSON.parse(res.data); } catch (e) { /* ignore */ }
        if (res.statusCode >= 400 || body.status === 'error') {
          reject(new Error(body.error || ('HTTP ' + res.statusCode)));
        } else {
          resolve(body.data);
        }
      },
      fail(err) { reject(new Error(err.errMsg || '上传失败')); }
    });
  });
}

module.exports = { request, upload };
