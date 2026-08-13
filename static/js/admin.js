/**
 * CBT Companion Admin Panel JavaScript
 * Handles authentication, API calls, and UI interactions
 */

const AdminPanel = {
    // Token Management
    getToken() {
        return localStorage.getItem('admin_token');
    },

    setToken(token) {
        localStorage.setItem('admin_token', token);
    },

    removeToken() {
        localStorage.removeItem('admin_token');
        localStorage.removeItem('admin_user');
    },

    getUser() {
        const user = localStorage.getItem('admin_user');
        return user ? JSON.parse(user) : null;
    },

    isAuthenticated() {
        return !!this.getToken();
    },

    // API Fetch Wrapper
    async fetchAPI(url, options = {}) {
        const token = this.getToken();

        const config = {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            }
        };

        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`;
        }

        try {
            const response = await fetch(url, config);

            // Handle 401 - redirect to login
            if (response.status === 401) {
                this.removeToken();
                window.location.href = '/admin/login';
                throw new Error('Session expired');
            }

            // Handle 403 - not admin
            if (response.status === 403) {
                this.showToast('Admin access required', 'error');
                throw new Error('Admin access required');
            }

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Request failed');
            }

            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },

    // Logout
    logout() {
        this.removeToken();
        window.location.href = '/admin/login';
    },

    // Toast Notifications
    showToast(message, type = 'info', duration = 4000) {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;

        // Icon based on type
        const icons = {
            success: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>',
            error: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>',
            warning: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>',
            info: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>'
        };

        toast.innerHTML = `
            ${icons[type] || icons.info}
            <span>${this.escapeHtml(message)}</span>
            <button onclick="this.parentElement.remove()" class="ml-2 text-current opacity-50 hover:opacity-100">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
            </button>
        `;

        container.appendChild(toast);

        // Auto remove after duration
        setTimeout(() => {
            toast.classList.add('toast-exit');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    },

    // Utility Functions
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    formatDate(dateString) {
        if (!dateString) return '--';
        const date = new Date(dateString);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        });
    },

    formatDateTime(dateString) {
        if (!dateString) return '--';
        const date = new Date(dateString);
        return date.toLocaleString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    },

    formatTimeAgo(dateString) {
        if (!dateString) return '--';

        const date = new Date(dateString);
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);

        if (seconds < 60) return 'just now';
        if (seconds < 3600) return Math.floor(seconds / 60) + ' minutes ago';
        if (seconds < 86400) return Math.floor(seconds / 3600) + ' hours ago';
        if (seconds < 604800) return Math.floor(seconds / 86400) + ' days ago';

        return this.formatDate(dateString);
    },

    // Generate initials from name
    getInitials(name) {
        if (!name) return '??';
        return name.split(' ')
            .map(n => n[0])
            .join('')
            .toUpperCase()
            .slice(0, 2);
    },

    // Generate avatar color from name
    getAvatarColor(name) {
        if (!name) return 'from-gray-400 to-gray-500';

        const colors = [
            'from-blue-400 to-indigo-500',
            'from-green-400 to-emerald-500',
            'from-purple-400 to-violet-500',
            'from-pink-400 to-rose-500',
            'from-yellow-400 to-orange-500',
            'from-cyan-400 to-teal-500',
            'from-red-400 to-pink-500',
            'from-indigo-400 to-purple-500'
        ];

        // Simple hash function
        let hash = 0;
        for (let i = 0; i < name.length; i++) {
            hash = name.charCodeAt(i) + ((hash << 5) - hash);
        }

        return colors[Math.abs(hash) % colors.length];
    },

    // Debounce utility
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    // Throttle utility
    throttle(func, limit) {
        let inThrottle;
        return function(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }
};

// Chart.js Default Configuration
if (typeof Chart !== 'undefined') {
    Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
    Chart.defaults.color = '#6B7280';

    // Custom tooltip styling
    Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(31, 41, 55, 0.9)';
    Chart.defaults.plugins.tooltip.titleColor = '#fff';
    Chart.defaults.plugins.tooltip.bodyColor = '#fff';
    Chart.defaults.plugins.tooltip.borderWidth = 0;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
    Chart.defaults.plugins.tooltip.padding = 12;
}

// Global error handler for unhandled promise rejections
window.addEventListener('unhandledrejection', event => {
    console.error('Unhandled promise rejection:', event.reason);
    AdminPanel.showToast('An unexpected error occurred', 'error');
});

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AdminPanel;
}
