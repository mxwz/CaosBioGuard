/* Caos BioGuard PWA：仅缓存静态壳，API 永远走网络，避免数据陈旧。 */
const CACHE = 'caos-mobile-v1';
const ASSETS = ['/m/', '/m/index.html', '/m/styles.css', '/m/app.js', '/m/manifest.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;
  event.respondWith(
    caches.match(event.request).then(hit => hit || fetch(event.request).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(event.request, copy)).catch(() => {});
      return res;
    })).catch(() => caches.match('/m/index.html'))
  );
});
