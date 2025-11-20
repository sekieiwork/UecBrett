/**
 * rf-serviceworker.js
 * Webプッシュの表示等に関わるメソッド群です。
 *
 * 当ファイルは編集して利用しないでください。
 * お客様で編集した場合の動作の保証はできかねますのでご了承ください
 * Copyright © 2019年 INFOCITY,Inc. All rights reserved.
 */

/**
 * RichFlyerサーバより配信された通知を表示します。
 * 参照: https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerRegistration/showNotification
 * @param {string} Title 通知のタイトル
 * @param {string} Icon 表示する画像のURL。RichFlyerの管理サイトで指定した画像。Webプッシュ用にリサイズされている。
 * @param {string} Body 通知の本文
 * @param {string} notification_id RichFlyerで割り当てられた通知ID
 * @param {string} event_id イベント投稿の際に割り当てられたイベントID
 * @param {string} url 一番目のアクションボタンに設定したURL
 * @param {string} click_action 拡張プロパティに設定した文字列
 * @return {Promise} 結果
 */
function showNotification({
  Title: title = "",
  Icon: icon = "",
  Body: body = "(with empty payload)",
  notification_id: notification_id = "",
  event_id: event_id = "",
  url: url = null,
  click_action: click_action = null,
  action_buttons: action_buttons = null,
}) {
  var tag = notification_id;
  if (event_id && event_id.length > 0) {
    tag = event_id;
  }
  var param = {
    body,
    tag,
    vibrate: [400, 100, 400],
  };

  param.data = click_action ? click_action : url;

  const actions =
    action_buttons && Array.isArray(action_buttons)
      ? action_buttons.map((action) => ({
          title: action.label,
          action: action.value,
        }))
      : null;

  if (actions) {
    param.actions = actions;
  }
  if (icon && icon.length > 0) {
    param.icon = icon;
    param.image = icon;
  }

  return self.registration.showNotification(title, param);
}

/**
 * プッシュ通知を受信すると呼ばれます。
 * 受信した通知をshowNotificationに渡して表示処理を実行します。
 * @param {PushEvent} 受信したプッシュ通知のオブジェクト
 */
function receivePush(event) {

  const processes = [];
  processes.push(saveNotification(event));
  //通知の表示を実行
  if (event.data && "showNotification" in self.registration) {
    var data = event.data.json();
    processes.push(showNotification(data));
  }

  const processChain = Promise.all(processes);
  event.waitUntil(processChain);
}

/**
 * プッシュ通知の情報を保存します。
 * @param {PushEvent} 受信したプッシュ通知のオブジェクト
 */
async function saveNotification(event) {
  const jsonData = event.data.json();

  var actions = null;
  if (jsonData.action_buttons) {
    actions = Array.isArray(jsonData.action_buttons);
  }
  var extendedProperty = jsonData.click_action;
  var action = "";
  if (extendedProperty) {
    action = extendedProperty;
  } else if (actions && actions.length > 0) {
    action = actions[0].action;
  }
  const storedObjectName = getStoredObjectName();
  const rfObject = {
    name: storedObjectName,
    notification_id: jsonData.notification_id,
    title: jsonData.Title,
    body: jsonData.Body,
    extended_property: action,
    is_sent_event_log: 0,
    is_clicked_notification: 0,
    received_date: Math.floor(Date.now() / 1000)
  };

  const db = await openDatabase();
  await updateStoredObject(db, rfObject);
}

/**
 * showNotificationによって表示された通知をクリックもしくはタップしたときに呼ばれます。
 * 一番目のアクションボタンに設定されたURLを開きます。
 * アクションボタンが設定されていない場合は何もしません。
 * @param {NotificationEvent} クリックした通知のオブジェクト
 */
function notificationClick(event) {
  event.notification.close();

  var actions = event.notification.actions;
  var extendedProperty = event.notification.data;
  var selectedAction = event.action;

  var action;
  if (selectedAction) {
    action = selectedAction;
  } else if (extendedProperty) {
    action = extendedProperty;
  } else if (actions && actions.length > 0) {
    action = actions[0].action;
  }

  const processes = [];
  processes.push(updateClickedNotification());
  if (action) {
    processes.push(openUrl(action));
  }

  const processChain = Promise.all(processes);
  event.waitUntil(processChain);
}

function openUrl(url) {
  return clients.matchAll({ type: "window" }).then((clientsArr) => {
    return clients.openWindow(url);
  });  
}

async function updateClickedNotification() {
  const storedObjectName = getStoredObjectName();

  const db = await openDatabase();
  const rfObject = await getStoredObject(db);
  rfObject.is_clicked_notification = 1;
  await updateStoredObject(db, rfObject);
}

function openDatabase() {
  const promise = new Promise((resolve, reject) => {
    const db = indexedDB.open("richflyer_database", 1);
    db.onsuccess = (event) => resolve(event.target.result);
    db.onerror = (event) => reject();
    db.onupgradeneeded = (event) => onUpgradeDB(event.target.result);
  });

  return promise;
}

function onUpgradeDB(db) {
  const storeName = getObjectStoreName();
  if (!db.objectStoreNames.contains(storeName)) {
    db.createObjectStore(storeName, { keyPath: "name" });
  }

}

function getObjectStoreName() {
  return "notification";
}

function getStoredObjectName() {
  return "richflyer_notification";
}

async function getStoredObject(db) {
  return new Promise((resolve, reject) => {
    const storeName = getObjectStoreName();
    const storedObjectName = getStoredObjectName();

    const isExistobjectStore = db.objectStoreNames.contains(storeName);    
    if (!isExistobjectStore) {
      reject(null);
      return;
    }
    const transaction = db.transaction(storeName, "readonly");
    const objectStore = transaction.objectStore(storeName);
    const rfObject = objectStore.get(storedObjectName);
    rfObject.onsuccess = (event) => resolve(event.target.result);
    rfObject.onerror = reject;
  });
}

async function updateStoredObject(db, rfObject) {
  return new Promise((resolve, reject) => {
    const storeName = getObjectStoreName();

    const transaction = db.transaction(storeName, "readwrite");
    const store = transaction.objectStore(storeName);
    const result = store.put(rfObject);
    result.onsuccess = () => resolve(result.result);
    result.onerror = reject;
  });
}

self.addEventListener("install", function (event) {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener("push", receivePush, false);
self.addEventListener("notificationclick", notificationClick, false);
