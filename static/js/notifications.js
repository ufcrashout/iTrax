// iTrax Notification System
// Global notification system for all pages

class NotificationSystem {
    constructor() {
        this.notificationCount = 0;
        this.csrf_token = document.querySelector('meta[name=csrf-token]')?.getAttribute('content');
        this.pushSupported = false;
        this.serviceWorkerRegistration = null;
        this.init();
    }

    async init() {
        // Initialize push notifications
        await this.initializePushNotifications();
        
        // Load initial notification count
        this.loadNotificationCount();
        
        // Set up event listeners
        this.setupEventListeners();
        
        // Poll for new notifications every 30 seconds
        setInterval(() => this.loadNotificationCount(), 30000);
    }

    async initializePushNotifications() {
        // Check if service workers and push notifications are supported
        if ('serviceWorker' in navigator && 'PushManager' in window) {
            try {
                // Register service worker
                const registration = await navigator.serviceWorker.register('/static/sw.js');
                this.serviceWorkerRegistration = registration;
                this.pushSupported = true;
                console.log('Service Worker registered:', registration);

                // Request notification permission if not already granted
                if (Notification.permission === 'default') {
                    await this.requestNotificationPermission();
                }

                // Subscribe to push notifications if permission is granted
                if (Notification.permission === 'granted') {
                    await this.subscribeToPush();
                }
            } catch (error) {
                console.error('Service Worker registration failed:', error);
            }
        } else {
            console.log('Push notifications not supported');
        }
    }

    async requestNotificationPermission() {
        const permission = await Notification.requestPermission();
        if (permission === 'granted') {
            console.log('Notification permission granted');
            return true;
        } else {
            console.log('Notification permission denied');
            return false;
        }
    }

    async subscribeToPush() {
        try {
            // Check if already subscribed
            const existingSubscription = await this.serviceWorkerRegistration.pushManager.getSubscription();
            if (existingSubscription) {
                console.log('Already subscribed to push notifications');
                return;
            }

            // Subscribe to push notifications
            const subscription = await this.serviceWorkerRegistration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: this.urlBase64ToUint8Array(await this.getVAPIDPublicKey())
            });

            // Send subscription to server
            await this.sendSubscriptionToServer(subscription);
            console.log('Subscribed to push notifications:', subscription);
        } catch (error) {
            console.error('Failed to subscribe to push notifications:', error);
        }
    }

    async getVAPIDPublicKey() {
        try {
            const response = await fetch('/api/push/vapid-public-key');
            const data = await response.json();
            return data.publicKey;
        } catch (error) {
            console.error('Failed to get VAPID public key:', error);
            // Fallback VAPID key (you should generate your own)
            return 'BEl62iUYgUivxIkv69yViEuiBIa40HI0DLI5kz5Fs0cEiw7MrKp9t0pNDhLRCb7cWfpVRYvx3VfP-J3LNlLBxL4';
        }
    }

    async sendSubscriptionToServer(subscription) {
        try {
            const response = await fetch('/api/push/subscribe', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrf_token
                },
                body: JSON.stringify({
                    subscription: subscription.toJSON()
                })
            });

            if (!response.ok) {
                throw new Error('Failed to send subscription to server');
            }
        } catch (error) {
            console.error('Error sending subscription to server:', error);
        }
    }

    urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding)
            .replace(/-/g, '+')
            .replace(/_/g, '/');

        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);

        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    setupEventListeners() {
        // Load notifications when dropdown is opened
        const notificationDropdown = document.getElementById('notificationDropdown');
        if (notificationDropdown) {
            notificationDropdown.addEventListener('click', () => {
                this.loadNotifications();
            });
        }
    }

    // Load notification count
    async loadNotificationCount() {
        try {
            const response = await fetch('/api/notifications/count');
            const result = await response.json();
            
            if (result.success) {
                this.updateNotificationBadge(result.unread_count);
            }
        } catch (error) {
            console.error('Error loading notification count:', error);
        }
    }

    // Update notification badge
    updateNotificationBadge(count) {
        const badge = document.getElementById('notificationBadge');
        if (!badge) return;
        
        if (count > 0) {
            badge.textContent = count;
            badge.style.display = 'inline-block';
            if (count > this.notificationCount) {
                badge.classList.add('notification-badge-animate');
                setTimeout(() => badge.classList.remove('notification-badge-animate'), 500);
            }
        } else {
            badge.style.display = 'none';
        }
        this.notificationCount = count;
    }

    // Load notifications
    async loadNotifications(unreadOnly = true) {
        try {
            const response = await fetch(`/api/notifications?unread_only=${unreadOnly}&limit=10`);
            const result = await response.json();
            
            if (result.success) {
                this.displayNotifications(result.notifications);
            }
        } catch (error) {
            console.error('Error loading notifications:', error);
        }
    }

    // Display notifications in dropdown
    displayNotifications(notifications) {
        const notificationList = document.getElementById('notificationList');
        if (!notificationList) return;
        
        if (notifications.length === 0) {
            notificationList.innerHTML = `
                <div class="dropdown-item-text text-center text-muted py-4">
                    <i class="fas fa-bell-slash fa-2x mb-2"></i><br>
                    No notifications
                </div>
            `;
            return;
        }

        let html = '';
        notifications.forEach(notification => {
            const timeAgo = this.getTimeAgo(new Date(notification.timestamp));
            const isUnread = !notification.is_read;
            const priorityClass = `priority-${notification.priority}`;
            const typeClass = `notification-${notification.notification_type}`;
            
            html += `
                <div class="notification-item ${isUnread ? 'unread' : 'read'} ${priorityClass} ${typeClass}"
                     onclick="notificationSystem.markNotificationRead(${notification.id})"
                     data-notification-id="${notification.id}">
                    <div class="d-flex justify-content-between">
                        <div class="flex-grow-1">
                            <div class="d-flex align-items-center mb-1">
                                <i class="fas fa-${this.getNotificationIcon(notification.notification_type, notification.event_type)} me-2"></i>
                                <strong>${notification.display_name || notification.device_name}</strong>
                                ${isUnread ? '<span class="badge bg-primary ms-2">New</span>' : ''}
                            </div>
                            <p class="mb-1">${notification.message}</p>
                            <small class="text-muted">
                                <i class="fas fa-clock me-1"></i>${timeAgo}
                                ${notification.geofence_name ? `• <i class="fas fa-map-marker-alt me-1"></i>${notification.geofence_name}` : ''}
                            </small>
                        </div>
                    </div>
                </div>
            `;
        });

        notificationList.innerHTML = html;
    }

    // Get notification icon based on type and event
    getNotificationIcon(type, event) {
        switch(type) {
            case 'geofence':
                return event === 'entry' ? 'sign-in-alt' : event === 'exit' ? 'sign-out-alt' : 'map-marker-alt';
            case 'device':
                return 'mobile-alt';
            case 'system':
                return 'cog';
            default:
                return 'bell';
        }
    }

    // Calculate time ago
    getTimeAgo(date) {
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);
        
        if (diff < 60) return 'Just now';
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        return `${Math.floor(diff / 86400)}d ago`;
    }

    // Mark notification as read
    async markNotificationRead(notificationId) {
        try {
            const response = await fetch(`/api/notifications/${notificationId}/read`, {
                method: 'PUT',
                headers: {
                    'X-CSRFToken': this.csrf_token
                }
            });

            if (response.ok) {
                // Update UI
                const notificationItem = document.querySelector(`[data-notification-id="${notificationId}"]`);
                if (notificationItem) {
                    notificationItem.classList.remove('unread');
                    notificationItem.classList.add('read');
                    const newBadge = notificationItem.querySelector('.badge');
                    if (newBadge) newBadge.remove();
                }
                
                // Update count
                this.loadNotificationCount();
            }
        } catch (error) {
            console.error('Error marking notification as read:', error);
        }
    }

    // Mark all notifications as read
    async markAllNotificationsRead() {
        try {
            const response = await fetch('/api/notifications/mark-all-read', {
                method: 'PUT',
                headers: {
                    'X-CSRFToken': this.csrf_token
                }
            });

            if (response.ok) {
                // Reload notifications and count
                this.loadNotifications();
                this.loadNotificationCount();
            }
        } catch (error) {
            console.error('Error marking all notifications as read:', error);
        }
    }

    // Load all notifications (navigate to full notifications page)
    loadAllNotifications() {
        window.location.href = '/notifications/all';
    }
}

// Global functions for backwards compatibility and template access
function markAllNotificationsRead() {
    if (window.notificationSystem) {
        window.notificationSystem.markAllNotificationsRead();
    }
}

function loadAllNotifications() {
    if (window.notificationSystem) {
        window.notificationSystem.loadAllNotifications();
    }
}

// Initialize notification system when DOM is ready
document.addEventListener('DOMContentLoaded', async function() {
    window.notificationSystem = new NotificationSystem();
});