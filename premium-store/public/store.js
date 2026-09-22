export const $ = (selector, root=document) => root.querySelector(selector);
export const esc = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const fa = new Intl.NumberFormat('fa-IR');
export const money = value => `${fa.format(value)} تومان`;
export const digits = value => value.replace(/[۰-۹]/g,c=>String('۰۱۲۳۴۵۶۷۸۹'.indexOf(c))).replace(/[٠-٩]/g,c=>String('٠١٢٣٤٥٦٧٨٩'.indexOf(c)));
export const symbols = {gpt:'✳',gemini:'✦',spotify:'≋',nord:'◭',trading:'Tᵛ',adobe:'Λ'};
export const date = value => new Intl.DateTimeFormat('fa-IR',{dateStyle:'medium',timeStyle:'short'}).format(new Date(typeof value==='number'?value*1000:value));
export const statusLabel = value => ({pending:'در انتظار پرداخت',success:'پرداخت موفق',failed:'ناموفق',open:'منتظر پاسخ پشتیبانی',answered:'پاسخ داده شده',closed:'بسته شده',processing:'در حال انجام',delivered:'تحویل شده',awaiting_payment:'در انتظار پرداخت',canceled:'لغو شده',demo_complete:'تکمیل آزمایشی',legacy:'سفارش قبلی'}[value]||value);
export const Store={user:null,config:{},products:[],cart:{},ready:null};
let afterLogin=null, otpMobile='', resendAt=0, quoteResult=null, coupon='', checkoutKey=null, quoteGeneration=0, chatId=null, chatCursor=0, chatLoading=false;

export async function api(path,options={}) {
  const headers={...options.headers};
  if(options.body && !(options.body instanceof Blob)) headers['Content-Type']='application/json';
  if(Store.user?.csrf) headers['X-CSRF-Token']=Store.user.csrf;
  const response=await fetch(path,{...options,headers,signal:options.signal||AbortSignal.timeout(20000)});
  const data=await response.json().catch(()=>({detail:'پاسخ سرور معتبر نیست.'}));
  if(!response.ok){const error=new Error(data.detail||'انجام درخواست ممکن نشد.');error.status=response.status;error.fields=data.fields;throw error;}
  return data;
}
export function toast(message,type='success') {
  const node=document.createElement('div');node.className=`toast ${type}`;node.textContent=message;$('#toasts').append(node);setTimeout(()=>node.remove(),4000);
}
export function errorText(error){return error.name==='TimeoutError'?'ارتباط با سرور طول کشید؛ دوباره تلاش کنید.':error instanceof TypeError?'ارتباط با سرور برقرار نشد.':error.message;}
export function openDialog(id){const node=document.getElementById(id);if(!node.open)node.showModal();}
function readCart(){try{const data=JSON.parse(localStorage.getItem('premium-cart')||'{}');Store.cart=Object.fromEntries(Object.entries(data||{}).filter(([id,q])=>/^\d+$/.test(id)&&Number.isInteger(q)&&q>0&&q<=10));}catch{Store.cart={};}}
export function items(){return Store.products.filter(p=>Store.cart[p.id]&&p.available).map(p=>({product_id:p.id,quantity:Store.cart[p.id]}));}
function total(){return Store.products.reduce((sum,p)=>sum+(Store.cart[p.id]||0)*p.price,0);}
function saveCart(){try{localStorage.setItem('premium-cart',JSON.stringify(Store.cart));}catch{}checkoutKey=null;coupon='';quoteResult=null;renderCart();if($('#checkout-dialog').open)refreshQuote();}
export function addToCart(id){const product=Store.products.find(p=>p.id===id);if(!product?.available)return toast('این محصول فعلاً موجود نیست.','error');if((Store.cart[id]||0)>=10)return toast('حداکثر تعداد هر محصول ۱۰ عدد است.','error');Store.cart[id]=(Store.cart[id]||0)+1;saveCart();toast('محصول به سبد خرید اضافه شد.');}
function renderCart(){
  const chosen=Store.products.filter(p=>Store.cart[p.id]);const count=chosen.reduce((sum,p)=>sum+Store.cart[p.id],0);
  $('#cart-count').textContent=fa.format(count);$('#open-cart').setAttribute('aria-label',`سبد خرید، ${fa.format(count)} محصول`);
  $('#cart-items').innerHTML=chosen.length?chosen.map(p=>`<article class="cart-item"><span class="product-icon ${esc(p.icon)}">${symbols[p.icon]||'✦'}</span><div><h3>${esc(p.title)}</h3><span class="item-price">${money(p.price)}</span><div class="quantity-controls"><button data-qty="${p.id}" data-delta="-1" aria-label="کاهش تعداد ${esc(p.title)}">−</button><span>${fa.format(Store.cart[p.id])}</span><button data-qty="${p.id}" data-delta="1" ${Store.cart[p.id]>=10?'disabled':''} aria-label="افزایش تعداد ${esc(p.title)}">+</button></div></div><button class="remove-item" data-remove="${p.id}" aria-label="حذف ${esc(p.title)}">×</button></article>`).join(''):'<div class="empty-state"><h3>سبد خریدت خالی است</h3><p>از صفحه محصول، اشتراک دلخواهت را اضافه کن.</p><a class="button secondary" href="/#products">دیدن محصولات</a></div>';
  $('#cart-footer').innerHTML=chosen.length?`<div class="summary-row total"><span>جمع سبد</span><strong>${money(total())}</strong></div><p class="form-note">کد تخفیف را در مرحله بعد وارد کن.</p><button class="button primary full-width" id="checkout-button">تکمیل سفارش ←</button>`:'';
}
export function userUpdated(){
  $('#account-button').textContent=Store.user?.registered?'حساب من':'ورود / ثبت‌نام';
  document.dispatchEvent(new CustomEvent('store:user'));
}
export async function refreshUser(){try{Store.user=await api('/api/auth/me');}catch(e){if(e.status===401||e.status===403)Store.user=null;else throw e;}userUpdated();return Store.user;}
export async function requireLogin(callback){
  await Store.ready;
  if(Store.user?.registered)return callback();
  afterLogin=callback;
  if(Store.user)showProfile();else showMobile();
  openDialog('login-dialog');
}
function showMobile(){
  $('#login-title').textContent='ورود / ثبت‌نام';
  $('#login-body').innerHTML='<p class="form-note">با شماره موبایل وارد شو. نیازی به رمز عبور نیست و ورودت تا دو روز حفظ می‌شود.</p><form id="mobile-form"><label>شماره موبایل<input name="mobile" dir="ltr" type="tel" inputmode="numeric" autocomplete="tel" maxlength="11" placeholder="09123456789" required></label><p class="field-error" role="alert"></p><button class="button primary full-width">دریافت کد ورود</button></form>';
  $('#mobile-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const mobile=digits(form.elements.mobile.value.trim());if(!/^09\d{9}$/.test(mobile))return $('.field-error',form).textContent='شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود.';await busy(form,async()=>{const result=await api('/api/auth/otp/request',{method:'POST',body:JSON.stringify({mobile})});otpMobile=mobile;resendAt=Date.now()+result.retry_after*1000;showCode(result);});});
}
function showCode(result){
  $('#login-title').textContent='کد ورود را وارد کن';
  $('#login-body').innerHTML=`<p class="form-note">شماره موبایل: <b dir="ltr">${esc(otpMobile)}</b> <button type="button" class="text-button" id="change-mobile">ویرایش شماره</button></p>${result.demo_code?`<p class="demo-warning">پیامک آزمایشی است. کد این ورود: <b dir="ltr">${esc(result.demo_code)}</b></p>`:''}<form id="code-form"><label>کد ۶ رقمی<input name="code" dir="ltr" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9۰-۹]{6}" required class="otp-input"></label><p class="field-error" role="alert"></p><button class="button primary full-width">تأیید و ورود</button></form><button class="text-button resend-button" id="resend-code" disabled>ارسال مجدد</button>`;
  $('#change-mobile').onclick=showMobile;
  $('#resend-code').onclick=async()=>{try{const data=await api('/api/auth/otp/request',{method:'POST',body:JSON.stringify({mobile:otpMobile})});resendAt=Date.now()+data.retry_after*1000;showCode(data);}catch(error){toast(errorText(error),'error');}};
  $('#code-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;await busy(form,async()=>{Store.user=await api('/api/auth/otp/verify',{method:'POST',body:JSON.stringify({mobile:otpMobile,code:digits(form.elements.code.value.trim())})});userUpdated();if(Store.user.registered)finishLogin();else showProfile();});});
  $('#code-form input').focus();
}
function showProfile(){
  $('#login-title').textContent='خوش آمدی؛ حسابت را تکمیل کن';
  $('#login-body').innerHTML=`<p class="form-note">این اطلاعات را فقط یک بار وارد می‌کنی و در سفارش‌های بعدی استفاده می‌شوند.</p><form id="register-form"><label>نام و نام خانوادگی<input name="full_name" autocomplete="name" minlength="3" maxlength="100" required value="${esc(Store.user?.full_name)}"></label><label>شناسه تلگرام (اختیاری)<input name="telegram_id" dir="ltr" maxlength="33" placeholder="@username" value="${esc(Store.user?.telegram_id)}"></label><p class="field-error" role="alert"></p><button class="button primary full-width">ذخیره و ادامه</button></form>`;
  $('#register-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;await busy(form,async()=>{Store.user=await api('/api/account/profile',{method:'PUT',body:JSON.stringify({full_name:form.elements.full_name.value,telegram_id:form.elements.telegram_id.value||null})});userUpdated();finishLogin();});});
}
function finishLogin(){$('#login-dialog').close();const next=afterLogin;afterLogin=null;if(next)Promise.resolve(next()).catch(error=>toast(errorText(error),'error'));}
export async function busy(form,action){const button=$('button[type="submit"],button:not([type])',form);const original=button?.textContent;if(button){button.disabled=true;button.textContent='لطفاً صبر کنید…';}const errorNode=$('.field-error',form);if(errorNode)errorNode.textContent='';try{await action();}catch(error){if(errorNode)errorNode.textContent=errorText(error);else toast(errorText(error),'error');}finally{if(button){button.disabled=false;button.textContent=original;}}}

async function checkout(){
  if(!items().length)return toast('سبد خریدت خالی است.','error');
  $('#checkout-dialog .checkout-contact').innerHTML=`<strong>${esc(Store.user.full_name)}</strong><span dir="ltr">${esc(Store.user.mobile)}</span><a href="/account.html#profile">ویرایش اطلاعات حساب</a>`;
  $('#coupon-code').value=coupon;$('#checkout-error').textContent='';openDialog('checkout-dialog');await refreshQuote();
}
async function refreshQuote(){
  const generation=++quoteGeneration;const button=$('#submit-order');button.disabled=true;quoteResult=null;
  try{const quote=await api('/api/checkout/quote',{method:'POST',body:JSON.stringify({items:items(),coupon})});if(generation!==quoteGeneration)return;quoteResult=quote;$('#quote-summary').innerHTML=`<div class="summary-row"><span>جمع سفارش</span><b>${money(quote.subtotal)}</b></div><div class="summary-row"><span>کد تخفیف ${esc(quote.coupon)}</span><b>${money(quote.discount)}</b></div><div class="summary-row total"><span>مبلغ نهایی</span><strong>${money(quote.total_amount)}</strong></div>`;$('#checkout-error').textContent='';button.disabled=Store.config.payment_mode==='disabled';button.textContent=Store.config.payment_mode==='disabled'?'پرداخت هنوز فعال نشده':'ادامه به پرداخت آزمایشی ←';}
  catch(error){if(generation!==quoteGeneration)return;$('#checkout-error').textContent=errorText(error);if(error.status===401){Store.user=null;$('#checkout-dialog').close();requireLogin(checkout);}}
}
async function submitOrder(){
  if(!quoteResult||!items().length)return;
  const button=$('#submit-order');button.disabled=true;button.textContent='در حال ثبت سفارش…';checkoutKey ||= crypto.randomUUID();
  try{const result=await api('/api/payment/request',{method:'POST',headers:{'Idempotency-Key':checkoutKey},body:JSON.stringify({items:items(),coupon})});const destination=new URL(result.payment_url,location.origin);if(destination.origin!==location.origin)throw new Error('نشانی پرداخت نامعتبر است.');try{sessionStorage.setItem('premium-pending-cart',JSON.stringify({authority:destination.searchParams.get('authority'),items:items()}));}catch{}location.assign(destination.href);}
  catch(error){$('#checkout-error').textContent=errorText(error);if(error.status===401){Store.user=null;$('#checkout-dialog').close();requireLogin(checkout);}}
  finally{button.disabled=false;button.textContent='ادامه به پرداخت آزمایشی ←';}
}

export function messageHTML(message){return `<article class="message ${message.sender==='staff'?'staff-message':'customer-message'}"><small>${message.sender==='staff'?'پشتیبانی':'شما'} · ${date(message.created_at)}</small><p>${esc(message.body)}</p></article>`;}
async function startChat(){
  openDialog('chat-dialog');$('#chat-messages').innerHTML='';chatId=null;chatCursor=0;
  try{const list=await api('/api/account/conversations?kind=chat');const active=list.items.find(c=>c.status!=='closed');chatId=active?.id||null;await pollChat();if(!chatId)$('#chat-messages').innerHTML='<div class="empty-state"><h3>چطور می‌توانیم کمکت کنیم؟</h3><p>پیامت را بنویس؛ سابقه گفت‌وگو در حساب تو می‌ماند.</p></div>';}
  catch(error){toast(errorText(error),'error');}
}
async function pollChat(){
  if(chatLoading||!$('#chat-dialog').open||document.hidden)return;chatLoading=true;
  try{const presence=await api('/api/support/presence');$('#chat-presence').textContent=presence.online?'کارشناس آنلاین است':'کارشناس آنلاین نیست؛ پیامت ذخیره می‌شود.';if(chatId){const data=await api(`/api/account/conversations/${chatId}?after=${chatCursor}`);if(data.messages.length){if(!chatCursor)$('#chat-messages').innerHTML='';$('#chat-messages').insertAdjacentHTML('beforeend',data.messages.map(messageHTML).join(''));chatCursor=data.messages.at(-1).id;$('#chat-messages').scrollTop=$('#chat-messages').scrollHeight;}$('#chat-send').disabled=data.conversation.status==='closed';if(data.conversation.status==='closed')$('#chat-presence').textContent='گفت‌وگو بسته شده است؛ برای شروع مجدد پنجره را باز کن.';}}
  catch(error){$('#chat-presence').textContent=errorText(error);}finally{chatLoading=false;}
}

function shell(){
  if(!$('#toasts'))document.body.insertAdjacentHTML('beforeend','<div id="toasts" class="toast-stack" aria-live="polite"></div>');
  if(!$('#account-button'))$('.nav-actions')?.insertAdjacentHTML('afterbegin','<button class="account-trigger" id="account-button">ورود / ثبت‌نام</button>');
  for(const id of ['cart-dialog','checkout-dialog','support-dialog'])document.getElementById(id)?.remove();
  document.body.insertAdjacentHTML('beforeend',`
  <dialog id="cart-dialog" class="cart-drawer" aria-labelledby="cart-title"><div class="dialog-header"><h2 id="cart-title">سبد خرید</h2><button class="icon-button" data-close="cart-dialog" aria-label="بستن سبد خرید">×</button></div><div id="cart-items" class="cart-items"></div><div id="cart-footer" class="cart-footer"></div></dialog>
  <dialog id="login-dialog" class="modal" aria-labelledby="login-title"><div class="dialog-header"><h2 id="login-title">ورود / ثبت‌نام</h2><button class="icon-button" data-close="login-dialog" aria-label="بستن ورود">×</button></div><div id="login-body"></div></dialog>
  <dialog id="checkout-dialog" class="modal" aria-labelledby="checkout-title"><div class="dialog-header"><h2 id="checkout-title">مرور و تکمیل سفارش</h2><button class="icon-button" data-close="checkout-dialog" aria-label="بستن تکمیل سفارش">×</button></div><div class="checkout-contact"></div><div class="coupon-entry"><label for="coupon-code">کد تخفیف داری؟</label><div><input id="coupon-code" dir="ltr" maxlength="40" placeholder="کد تخفیف"><button class="button secondary" id="apply-coupon">اعمال کد</button></div><button class="text-button" id="clear-coupon">حذف کد تخفیف</button></div><div id="quote-summary"></div><p class="demo-warning">پرداخت این نسخه آزمایشی است و وجهی دریافت نمی‌شود.</p><p id="checkout-error" class="field-error" role="alert"></p><button class="button primary full-width" id="submit-order" disabled>در حال محاسبه…</button></dialog>
  <button class="chat-launcher support-trigger" aria-label="گفت‌وگوی آنلاین با پشتیبانی">◌ <span>پشتیبانی آنلاین</span></button>
  <dialog id="chat-dialog" class="chat-panel" aria-labelledby="chat-title"><div class="dialog-header"><div><h2 id="chat-title">گفت‌وگوی آنلاین</h2><small id="chat-presence">در حال بررسی وضعیت…</small></div><button class="icon-button" data-close="chat-dialog" aria-label="بستن گفت‌وگو">×</button></div><div id="chat-messages" class="messages" aria-live="polite"></div><form id="chat-form"><label class="sr-only" for="chat-body">پیام به پشتیبانی</label><textarea id="chat-body" maxlength="5000" required placeholder="پیامت را بنویس…"></textarea><p class="field-error" role="alert"></p><button id="chat-send" class="button primary" type="submit">ارسال پیام ←</button></form><a class="text-button" href="/account.html#tickets">برای پیگیری جداگانه، تیکت ثبت کن ↖</a></dialog>`);
  document.addEventListener('click',event=>{const target=event.target.closest('button,a');if(!target)return;
    if(target.dataset.close)document.getElementById(target.dataset.close).close();
    if(target.id==='open-cart')openDialog('cart-dialog');
    if(target.id==='account-button')requireLogin(()=>location.assign('/account.html'));
    if(target.id==='checkout-button'){$('#cart-dialog').close();requireLogin(checkout);}
    if(target.matches('.support-trigger'))requireLogin(startChat);
    if(target.dataset.qty){const id=target.dataset.qty;Store.cart[id]=Math.max(0,Math.min(10,(Store.cart[id]||0)+Number(target.dataset.delta)));if(!Store.cart[id])delete Store.cart[id];saveCart();($('#cart-items').querySelector(`[data-qty="${id}"]`)||$('#cart-dialog .icon-button')).focus();}
    if(target.dataset.remove){delete Store.cart[target.dataset.remove];saveCart();}
  });
  document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}}));
  $('#apply-coupon').onclick=()=>{coupon=$('#coupon-code').value.trim().toUpperCase();checkoutKey=null;refreshQuote();};
  $('#clear-coupon').onclick=()=>{coupon='';checkoutKey=null;$('#coupon-code').value='';refreshQuote();};
  $('#submit-order').onclick=submitOrder;
  $('#chat-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;await busy(form,async()=>{const body=$('#chat-body').value.trim();if(!body)return;if(chatId)await api(`/api/account/conversations/${chatId}/messages`,{method:'POST',body:JSON.stringify({body})});else{const created=await api('/api/account/conversations',{method:'POST',body:JSON.stringify({kind:'chat',subject:'گفت‌وگو با پشتیبانی',body})});chatId=created.id;}$('#chat-body').value='';await pollChat();});});
  setInterval(()=>{const button=$('#resend-code');if(button){const remaining=Math.max(0,Math.ceil((resendAt-Date.now())/1000));button.disabled=remaining>0;button.textContent=remaining?`ارسال مجدد تا ${fa.format(remaining)} ثانیه دیگر`:'ارسال دوباره کد';}},1000);
  setInterval(pollChat,7000);
  window.addEventListener('storage',event=>{if(event.key==='premium-cart'){readCart();checkoutKey=null;renderCart();if($('#checkout-dialog').open)refreshQuote();}});
  $('#year') && ($('#year').textContent=new Intl.DateTimeFormat('fa-IR',{year:'numeric'}).format(new Date()));
}

shell();readCart();
Store.ready=(async()=>{
  const [catalog]=await Promise.all([api('/api/products'),refreshUser()]);
  Store.config=catalog;Store.products=catalog.products;
  Store.cart=Object.fromEntries(Object.entries(Store.cart).filter(([id])=>Store.products.some(p=>p.id===Number(id)&&p.available)));
  renderCart();
  if($('#social-links'))$('#social-links').innerHTML=[['telegram_url','کانال تلگرام ↗'],['instagram_url','اینستاگرام ↗']].filter(([key])=>Store.config[key]).map(([key,label])=>`<a href="${esc(Store.config[key])}" target="_blank" rel="noopener noreferrer">${label}</a>`).join('');
  if($('#store-notice')&&Store.config.store_notice){$('#store-notice').textContent=Store.config.store_notice;$('#store-notice').hidden=false;}
  return Store;
})();
Store.ready.catch(error=>toast(errorText(error),'error'));
