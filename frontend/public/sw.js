/* Notification-only worker. No fetch listener, so the browser loads
   every request from the network. This must not cache /api and must not
   replace a CloudFront 403 with index.html. */
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
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
