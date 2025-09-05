// iTrax Service Worker for Push Notifications
const CACHE_NAME = 'itrax-v1';
const urlsToCache = [
  '/',
  '/static/css/bootstrap.min.css',
  '/static/js/bootstrap.bundle.min.js',
  '/static/js/notifications.js'
];

// Install service worker and cache resources
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        return cache.addAll(urlsToCache);
      })
  );
});

// Fetch event - serve from cache when offline
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        // Return cached version or fetch from network
        return response || fetch(event.request);
      }
    )
  );
});

// Push event - handle incoming push notifications
self.addEventListener('push', event => {
  const options = {
    body: 'You have a new notification',
    icon: '/static/images/favicon.ico',
    badge: '/static/images/badge.png',
    vibrate: [200, 100, 200],
    data: {
      dateOfArrival: Date.now(),
      primaryKey: 1
    },
    actions: [
      {
        action: 'explore',
        title: 'View Details',
        icon: '/static/images/checkmark.png'
      },
      {
        action: 'close',
        title: 'Close',
        icon: '/static/images/xmark.png'
      }
    ]
  };

  if (event.data) {
    try {
      const data = event.data.json();
      options.title = data.title || 'iTrax Notification';
      options.body = data.body || data.message || 'You have a new notification';
      options.icon = data.icon || '/static/images/favicon.ico';
      options.data = { ...options.data, ...data };
    } catch (e) {
      options.title = 'iTrax Notification';
      options.body = event.data.text() || 'You have a new notification';
    }
  } else {
    options.title = 'iTrax Notification';
  }

  event.waitUntil(
    self.registration.showNotification(options.title, options)
  );
});

// Notification click event
self.addEventListener('notificationclick', event => {
  event.notification.close();

  if (event.action === 'explore') {
    // Open the app to notifications page
    event.waitUntil(
      clients.openWindow('/notifications/all')
    );
  } else if (event.action === 'close') {
    // Just close the notification
    return;
  } else {
    // Default click - open main app
    event.waitUntil(
      clients.openWindow('/')
    );
  }
});

// Background sync for offline actions
self.addEventListener('sync', event => {
  if (event.tag === 'background-sync') {
    event.waitUntil(doBackgroundSync());
  }
});

function doBackgroundSync() {
  // Handle any queued actions when back online
  return Promise.resolve();
}