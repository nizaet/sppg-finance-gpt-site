self.addEventListener('push',event=>{let data={};try{data=event.data.json();}catch{}event.waitUntil(self.registration.showNotification(data.title||'SPPG',{body:data.body||'Laporan penerimaan baru perlu diperiksa.',data:{url:'/'},tag:'sppg-receiving',renotify:true}));});
self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil(clients.openWindow('/'));});
