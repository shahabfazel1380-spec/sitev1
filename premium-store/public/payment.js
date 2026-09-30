'use strict';
(async () => {
  const container = document.getElementById('payment-content');
  const authority = new URLSearchParams(location.search).get('authority');
  const money = number => `${new Intl.NumberFormat('fa-IR').format(number)} تومان`;
  try {
    if (!authority || !/^[a-f0-9-]{36}$/.test(authority)) throw new Error('نشانی سفارش معتبر نیست.');
    const login = await fetch('/api/auth/me', {signal:AbortSignal.timeout(12000)});
    if (!login.ok) {
      container.textContent = 'برای مشاهده و ادامه این سفارش ابتدا وارد حساب خود شوید.';
      const link = document.createElement('a');
      link.className = 'button primary full-width';
      link.href = '/account.html?return=' + encodeURIComponent(location.pathname + location.search);
      link.textContent = 'ورود به حساب';
      container.append(link);
      return;
    }
    const user = await login.json();
    const response = await fetch(`/api/payment/session/${encodeURIComponent(authority)}`, {signal:AbortSignal.timeout(12000)});
    if (!response.ok) throw new Error('سفارش پیدا نشد یا سرویس در دسترس نیست.');
    const order = await response.json();
    if (document.body.dataset.page === 'demo' && order.status === 'pending') {
      container.innerHTML = `<p>مبلغ سفارش آزمایشی</p><div class="payment-amount">${money(order.total_amount)}</div><div class="payment-actions"><button class="button primary" data-result="OK">شبیه‌سازی پرداخت موفق</button><button class="button secondary" data-result="NOK">شبیه‌سازی لغو پرداخت</button></div><p class="muted">مهلت این سفارش ۲۰ دقیقه است.</p><p id="payment-error" class="field-error" role="alert"></p>`;
      container.querySelectorAll('[data-result]').forEach(button => button.addEventListener('click', async () => {
        const buttons = container.querySelectorAll('[data-result]');
        buttons.forEach(b => b.disabled = true);
        try {
          const result = await fetch(`/api/payment/verify?Authority=${encodeURIComponent(authority)}&Status=${button.dataset.result}`, {method:'POST', headers:{'X-CSRF-Token':user.csrf}, signal:AbortSignal.timeout(12000)});
          const data = await result.json();
          if (!result.ok) throw new Error(data.detail || 'پرداخت تأیید نشد.');
          const destination = new URL(data.receipt_url, location.origin);
          if (destination.origin !== location.origin) throw new Error('نشانی رسید نامعتبر است.');
          location.assign(destination.href);
        } catch (error) {
          document.getElementById('payment-error').textContent = error.message;
          buttons.forEach(b => b.disabled = false);
        }
      }));
      return;
    }
    const success = order.status === 'success';
    const pending = order.status === 'pending';
    container.innerHTML = `<span class="payment-icon">${success ? '✓' : pending ? '◷' : '×'}</span><h1>${success ? (order.payment_mode==='demo'?'پرداخت آزمایشی موفق بود':'پرداخت با کیف پول انجام شد') : pending ? 'سفارش در انتظار پرداخت است' : 'پرداخت تکمیل نشد'}</h1><p>${success ? (order.payment_mode==='demo'?'سفارش آزمایشی ثبت شد. این رسید به معنی پرداخت یا خرید واقعی نیست.':'سفارش شما با موجودی کیف پول پرداخت شد.') : pending ? 'هنوز نتیجه نهایی برای این سفارش ثبت نشده است.' : 'پرداخت لغو شده یا زمان آن به پایان رسیده است. سبد خریدت برای تلاش دوباره حفظ شده.'}</p><div class="payment-amount">${money(order.order_total??order.total_amount)}</div><p>سهم کیف پول: ${money(order.wallet_used||0)}</p>`;
    if (success) {
      const ref = document.createElement('div'); ref.className = 'payment-ref'; ref.textContent = order.ref_id; container.append(ref);
      try {
        const snapshot = JSON.parse(sessionStorage.getItem('premium-pending-cart') || 'null');
        if (snapshot?.authority === authority) {
          const current = JSON.parse(localStorage.getItem('premium-cart') || '{}');
          for (const item of snapshot.items) { current[item.product_id] = Math.max(0, (current[item.product_id] || 0) - item.quantity); if (!current[item.product_id]) delete current[item.product_id]; }
          localStorage.setItem('premium-cart', JSON.stringify(current)); sessionStorage.removeItem('premium-pending-cart');
        }
      } catch { /* Storage is optional. Never prevent a receipt from rendering. */ }
    }
    if (pending) {
      const link = document.createElement('a'); link.className = 'button secondary full-width'; link.href = `/demo-payment.html?authority=${encodeURIComponent(authority)}`; link.textContent = 'ادامه پرداخت آزمایشی'; container.append(link);
    }
  } catch (error) { container.textContent = error.name === 'TimeoutError' ? 'ارتباط با سرور طول کشید؛ صفحه را دوباره بارگذاری کنید.' : error instanceof TypeError ? 'ارتباط با سرور برقرار نشد.' : error.message; container.classList.add('field-error'); }
})();
