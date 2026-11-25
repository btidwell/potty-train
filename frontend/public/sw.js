/* Notification-only worker. No fetch listener, so the browser loads
   every request from the network. This must not cache /api and must not
   replace a CloudFront 403 with index.html. */
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let title = 'Potty log';
  let body = '';
  let tag = 'potty';
  try {
    const payload = event.data ? event.data.json() : null;
    if (payload && typeof payload === 'object') {
      if (payload.title) {
        title = String(payload.title);
      }
      if (payload.body) {
        body = String(payload.body);
      }
      if (payload.tag) {
        tag = String(payload.tag);
      }
    }
  } catch {
    title = 'Potty log';
  }
  event.waitUntil(self.registration.showNotification(title, { body, tag }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      const open = clients.find((client) => 'focus' in client);
      if (open) {
        return open.focus();
      }
      return self.clients.openWindow('./');
    }),
  );
});
