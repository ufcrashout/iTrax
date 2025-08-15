// iTrax Notification System
// Global notification system for all pages

class NotificationSystem {
    constructor() {
        this.notificationCount = 0;
        this.csrf_token = document.querySelector('meta[name=csrf-token]')?.getAttribute('content');
        this.init();
    }

    init() {
        // Load initial notification count
        this.loadNotificationCount();
        
        // Set up event listeners
        this.setupEventListeners();
        
        // Poll for new notifications every 30 seconds
        setInterval(() => this.loadNotificationCount(), 30000);
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
document.addEventListener('DOMContentLoaded', function() {
    window.notificationSystem = new NotificationSystem();
});