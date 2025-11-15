// static/sw.js

// 1. プッシュ通知を受け取った時の処理
self.addEventListener('push', function(event) {
    console.log('[Service Worker] Push Received.');
    
    let data = {};
    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            console.error('Push data is not JSON:', event.data.text());
            data = { title: '通知', body: event.data.text() };
        }
    } else {
        data = { title: 'UEC 掲示板', body: '新しい通知があります。' };
    }

    const title = data.title || 'UEC 掲示板';
    const options = {
        body: data.body || '新しい通知があります。',
        icon: data.icon || '/static/icons/android-chrome-192x192.png',
        badge: data.badge || '/static/icons/favicon-32x32.png',
        data: {
            url: data.data ? data.data.url : '/' // クリック時の遷移先URL
        }
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

// 2. 通知がクリックされた時の処理
self.addEventListener('notificationclick', function(event) {
    console.log('[Service Worker] Notification click Received.');

    event.notification.close(); // 通知を閉じる

    const urlToOpen = event.notification.data.url || '/';

    event.waitUntil(
        clients.matchAll({
            type: 'window'
        }).then(function(clientList) {
            // 既にタブが開いているかチェック
            for (let i = 0; i < clientList.length; i++) {
                const client = clientList[i];
                // このオリジンのタブが開いていればフォーカスする
                if (client.url.includes(self.location.origin) && 'focus' in client) {
                    client.navigate(urlToOpen); // タブのURLを更新
                    return client.focus(); // そのタブにフォーカス
                }
            }
            // 開いているタブがなければ新しいタブで開く
            if (clients.openWindow) {
                return clients.openWindow(urlToOpen);
            }
        })
    );
});

// 3. PWAインストール要件のための fetch イベント (中身は空でOK)
self.addEventListener('fetch', function(event) {
    // オフライン対応を実装する場合はここにロジックを追加
});