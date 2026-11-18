/* Caos BioGuard 移动端 */
(function () {
  const SKEY = 'caos-mobile-session';
  let session = null;
  let mode = 'admin';
  let modalities = [];
  let overview = null;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  function toast(msg, bad) {
    const el = $('toast');
    el.textContent = msg;
    el.className = 'toast show' + (bad ? ' bad' : '');
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.className = 'toast'; }, 2600);
  }

  function headers() {
    const h = {};
    if (session && session.token) h['Authorization'] = 'Bearer ' + session.token;
    if (session && session.subject) h['X-Mobile-Subject'] = session.subject;
    return h;
  }

  async function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign(headers(), opts.headers || {});
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({status: 'error', error: 'invalid json'}));
    if (!res.ok || data.status === 'error') throw new Error(data.error || ('HTTP ' + res.status));
    return data.data;
  }

  function saveSession(s) {
    session = s;
    try { localStorage.setItem(SKEY, JSON.stringify(s)); } catch (e) { /* ignore */ }
  }

  function clearSession() {
    session = null;
    try { localStorage.removeItem(SKEY); } catch (e) { /* ignore */ }
  }

  function showApp() {
    $('loginView').classList.add('hide');
    $('appView').classList.remove('hide');
    $('roleText').textContent = session.role === 'admin' ? '管理员工作台' : '员工工作台 · ' + (session.subject || '');
    $('recordSearchWrap').classList.toggle('hide', session.role !== 'admin');
    $('requestsBlock').classList.toggle('hide', session.role !== 'admin');
    $('requestsList').classList.toggle('hide', session.role !== 'admin');
    $('profileName').textContent = session.subject || '管理员';
    $('avatar').textContent = (session.subject || 'A').slice(0, 1).toUpperCase();
    $('enrollSubject').value = session.subject || '';
    $('enrollSubject').disabled = session.role !== 'admin';
    loadAll();
  }

  function showLogin() {
    $('appView').classList.add('hide');
    $('loginView').classList.remove('hide');
  }

  function switchTab(name) {
    document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + name));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    if (name === 'records') loadRecords();
    if (name === 'profile') loadProfile();
    if (name === 'enroll') loadModalities();
  }

  function item(name, sub, rightHtml) {
    return '<div class="item"><div class="left"><span class="name">' + esc(name) + '</span><span class="sub">' + esc(sub) + '</span></div><div class="right">' + rightHtml + '</div></div>';
  }

  function renderOverview(d) {
    overview = d;
    $('todayCount').textContent = d.today_attendance || 0;
    $('statUsers').textContent = (d.stats && d.stats.user && d.stats.user.total) || 0;
    $('statDevices').textContent = (d.devices || []).length + ((d.local_device && d.local_device.device_id) ? 1 : 0);
    $('statTemplates').textContent = (d.biometrics && d.biometrics.total) || 0;
    $('statRequests').textContent = d.requests || 0;

    const devices = (d.devices || []).map(x =>
      item(x.device_id || 'unknown', '最近在线 ' + (x.last_seen || '—'), '<span class="badge ' + (x.is_online ? 'ok' : 'off') + '">' + (x.is_online ? '在线' : '离线') + '</span>')
    );
    if (d.local_device && d.local_device.device_id) {
      devices.unshift(item(d.local_device.device_id, '本机 · ' + (d.local_device.ip || d.local_device.hostname || 'local'), '<span class="badge ok">本机</span>'));
    }
    $('deviceList').innerHTML = devices.join('') || '<div class="item"><div class="left"><span class="sub">暂无设备</span></div></div>';
    $('recentList').innerHTML = (d.recent || []).length ? d.recent.map(r =>
      item(r.user_name || '—', r.device_id || '—', '<span class="badge ok">' + esc(r.status || '通过') + '</span><div class="sub" style="margin-top:4px;">' + esc(r.timestamp || '') + '</div>')
    ).join('') : '<div class="item"><div class="left"><span class="sub">暂无通行记录</span></div></div>';
  }

  async function loadOverview() {
    try {
      const d = await api('/api/mobile/overview');
      renderOverview(d);
      if (session.role === 'admin') loadRequests();
    } catch (e) { toast('概览加载失败：' + e.message, true); }
  }

  async function loadRecords() {
    try {
      let q = '';
      if (session.role === 'admin') {
        const s = $('recordSearch').value.trim();
        if (s) q = '?subject=' + encodeURIComponent(s);
      }
      const rows = await api('/api/mobile/records' + q);
      $('recordCount').textContent = rows.length + ' 条';
      $('recordsList').innerHTML = rows.length ? rows.map(r =>
        item(r.user_name || '—', (r.device_id || '—') + ' · ' + (r.timestamp || ''), '<span class="badge ' + (String(r.status).indexOf('拒') >= 0 ? 'warn' : 'ok') + '">' + esc(r.status || '通过') + '</span>')
      ).join('') : '<div class="item"><div class="left"><span class="sub">暂无记录</span></div></div>';
    } catch (e) { toast('记录加载失败：' + e.message, true); }
  }

  async function loadProfile() {
    try {
      const subj = session.role === 'admin' ? (session.subject || '') : (session.subject || '');
      if (!subj) {
        $('profileModalities').innerHTML = '<span class="chip">管理员账号无需个人模板</span>';
        $('profileRecent').innerHTML = '';
        return;
      }
      const d = await api('/api/mobile/profile?subject=' + encodeURIComponent(subj));
      $('profileName').textContent = d.subject;
      $('profileModalities').innerHTML = (d.modalities || []).length ? d.modalities.map(m =>
        '<span class="chip">' + esc(labelOf(m)) + '</span>'
      ).join('') : '<span class="chip">尚未注册模板</span>';
      $('profileRecent').innerHTML = (d.recent || []).length ? d.recent.map(r =>
        item(r.device_id || '—', r.timestamp || '', '<span class="badge ok">' + esc(r.status || '通过') + '</span>')
      ).join('') : '<div class="item"><div class="left"><span class="sub">暂无记录</span></div></div>';
    } catch (e) { toast('个人资料加载失败：' + e.message, true); }
  }

  async function loadModalities() {
    try {
      modalities = await api('/api/mobile/modalities');
      const sel = $('enrollModality');
      const options = modalities.filter(m => m.name !== 'face').map(m =>
        '<option value="' + m.name + '">' + esc(m.label) + (m.available ? '' : '（依赖缺失）') + '</option>'
      ).join('');
      if (sel.innerHTML !== options) sel.innerHTML = options;
      syncEnrollHint();
    } catch (e) { toast('模态加载失败：' + e.message, true); }
  }

  function labelOf(name) {
    const m = modalities.find(x => x.name === name);
    return m ? m.label : name;
  }

  function syncEnrollHint() {
    const m = $('enrollModality').value;
    const file = $('enrollFile');
    const hint = $('enrollHint');
    const wrap = $('strokeWrap');
    wrap.classList.toggle('hide', m !== 'signature');
    if (m === 'voiceprint') { file.accept = '.wav,audio/wav'; hint.textContent = '声纹：上传 16kHz 左右单声道 WAV。'; }
    else if (m === 'gait') { file.accept = 'video/*,.mp4,.avi,.mov'; hint.textContent = '步态：上传 3~8 秒、全身入镜视频。'; }
    else if (m === 'signature') { file.accept = 'image/*'; hint.textContent = '签名：可只填轨迹 JSON，或上传签名图。'; }
    else { file.accept = 'image/*'; hint.textContent = '上传清晰的单张图片。'; }
  }

  async function loadRequests() {
    try {
      const rows = await api('/api/mobile/enroll-requests');
      $('requestsList').innerHTML = rows.length ? rows.map(r =>
        item(r.subject + ' · ' + labelOf(r.modality), r.created_at + (r.note ? ' · ' + r.note : ''),
          r.status === 'pending' ? '<button class="badge ok" data-approve="' + esc(r.id) + '" style="cursor:pointer;">通过</button>' : '<span class="badge ok">已通过</span>')
      ).join('') : '<div class="item"><div class="left"><span class="sub">暂无待审申请</span></div></div>';
    } catch (e) { /* 非管理员忽略 */ }
  }

  async function doLogin() {
    const body = mode === 'admin'
      ? {token: $('tokenInput').value.trim()}
      : {subject: $('subjectInput').value.trim()};
    if (mode === 'admin' && !body.token) return toast('请输入 API Token', true);
    if (mode === 'user' && !body.subject) return toast('请输入工号或姓名', true);
    try {
      const d = await api('/api/mobile/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      saveSession({role: d.role, subject: d.subject, token: mode === 'admin' ? body.token : ''});
      showApp();
      toast('已进入工作台');
    } catch (e) { toast('登录失败：' + e.message, true); }
  }

  async function doEnroll() {
    const subject = $('enrollSubject').value.trim();
    const modality = $('enrollModality').value;
    if (!subject) return toast('请填写主体', true);
    const file = $('enrollFile').files[0];
    const strokes = $('enrollStrokes').value.trim();
    if (session.role !== 'admin') {
      try {
        await api('/api/mobile/enroll-request', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({subject: subject, modality: modality, note: '移动端提交'})
        });
        $('enrollResult').className = 'result ok';
        $('enrollResult').textContent = '申请已提交，等待管理员在边缘端或后台完成采集。';
        toast('申请已提交');
      } catch (e) { $('enrollResult').className = 'result bad'; $('enrollResult').textContent = e.message; }
      return;
    }
    if (!file && !strokes) return toast('请选择样本文件', true);
    const fd = new FormData();
    fd.append('subject', subject);
    fd.append('modality', modality);
    if (file) fd.append('file', file);
    if (strokes) {
      try { fd.append('strokes', JSON.stringify(JSON.parse(strokes))); }
      catch (e) { return toast('签名轨迹不是合法 JSON', true); }
    }
    const btn = $('enrollBtn');
    btn.disabled = true;
    $('enrollResult').className = 'result';
    $('enrollResult').textContent = '正在提取特征…';
    try {
      const out = await api('/api/biometrics/enroll', {method: 'POST', body: fd});
      $('enrollResult').className = 'result ok';
      $('enrollResult').textContent = '注册成功：质量 ' + (out.quality != null ? Number(out.quality).toFixed(2) : '—') + '，模板 ' + (out.template_bytes || 0) + ' 字节';
      toast('注册成功');
      loadOverview();
    } catch (e) {
      $('enrollResult').className = 'result bad';
      $('enrollResult').textContent = '注册失败：' + e.message;
    } finally { btn.disabled = false; }
  }

  async function loadAll() {
    await Promise.all([loadOverview(), loadModalities()]);
    if (session.role !== 'admin') loadProfile();
    else loadRequests();
  }

  // 事件
  document.querySelectorAll('.seg-btn').forEach(btn => btn.addEventListener('click', () => {
    mode = btn.dataset.mode;
    document.querySelectorAll('.seg-btn').forEach(b => b.classList.toggle('active', b === btn));
    $('adminFields').classList.toggle('hide', mode !== 'admin');
    $('userFields').classList.toggle('hide', mode !== 'user');
  }));
  $('loginBtn').addEventListener('click', doLogin);
  $('logoutBtn').addEventListener('click', () => { clearSession(); showLogin(); });
  $('refreshBtn').addEventListener('click', loadAll);
  document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));
  $('recordSearchBtn').addEventListener('click', loadRecords);
  $('recordSearch').addEventListener('keydown', e => { if (e.key === 'Enter') loadRecords(); });
  $('enrollModality').addEventListener('change', syncEnrollHint);
  $('enrollBtn').addEventListener('click', doEnroll);
  $('requestsList').addEventListener('click', async (ev) => {
    const id = ev.target.dataset && ev.target.dataset.approve;
    if (!id) return;
    try {
      await api('/api/mobile/enroll-requests/' + encodeURIComponent(id) + '/approve', {method: 'POST'});
      loadRequests();
      toast('已标记通过');
    } catch (e) { toast('操作失败：' + e.message, true); }
  });

  // 启动
  try { session = JSON.parse(localStorage.getItem(SKEY) || 'null'); } catch (e) { session = null; }
  if (session && (session.token || session.subject)) showApp(); else showLogin();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/m/sw.js').catch(() => {});
  }
})();
