import {Store,$,esc,fa,money,symbols} from './store.js';
let category='all',query='',timer;
const normalize=value=>value.toLowerCase().replace(/ي/g,'ی').replace(/ك/g,'ک').replace(/[\u200c\s]+/g,' ').trim();
function render(){
  let products=Store.products.filter(p=>(category==='all'||p.category===category)&&normalize(`${p.title} ${p.brand} ${p.description}`).includes(normalize(query)));
  const sort=$('#sort').value;if(sort!=='default')products.sort((a,b)=>sort==='price-asc'?a.price-b.price:b.price-a.price);
  $('#results-count').textContent=`${fa.format(products.length)} اشتراک برای انتخاب تو`;
  $('#product-grid').innerHTML=products.length?products.map(p=>`<article class="product-card"><div class="product-top">${p.images.length?`<img class="product-cover-thumb" src="${esc(p.images[0])}" alt="${esc(p.title)}" loading="lazy">`:`<span class="product-icon ${esc(p.icon)}" aria-hidden="true">${symbols[p.icon]}</span>`}${p.badge?`<span class="product-badge">${esc(p.badge)}</span>`:''}</div><h3><a href="/product.html?id=${p.id}">${esc(p.title)}</a></h3><span class="product-brand">${esc(p.brand)}</span><p class="product-description">${esc(p.description)}</p><ul class="features">${p.features.slice(0,3).map(f=>`<li>${esc(f)}</li>`).join('')}</ul><div class="product-price-row"><div><del class="original-price">${p.original_price>p.price?money(p.original_price):''}</del><strong class="product-price">${fa.format(p.price)} <small>تومان</small></strong></div><span class="price-period">${esc(p.period)}</span></div><a class="add-button" href="/product.html?id=${p.id}">${p.available?'خرید':'مشاهده محصول ناموجود'} <span>←</span></a></article>`).join(''):'<div class="empty-state"><h3>محصولی پیدا نشد</h3><p>عبارت دیگری جست‌وجو کن.</p><button class="button secondary" id="reset-search">نمایش همه محصولات</button></div>';
  $('#product-grid').setAttribute('aria-busy','false');
  $('#reset-search')?.addEventListener('click',()=>{category='all';query='';$('#search').value='';$('#sort').value='default';setCategories();render();});
}
function setCategories(){document.querySelectorAll('[data-category]').forEach(button=>{const active=button.dataset.category===category;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});}
document.querySelectorAll('[data-category]').forEach(button=>button.addEventListener('click',()=>{category=button.dataset.category;setCategories();render();}));
$('#search').addEventListener('input',event=>{clearTimeout(timer);timer=setTimeout(()=>{query=event.target.value;render();},300);});
$('#sort').addEventListener('change',render);
$('.search-trigger')?.addEventListener('click',()=>{$('#products').scrollIntoView();$('#search').focus();});
document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!document.querySelector('dialog[open]')){event.preventDefault();$('#search').focus();}});
Store.ready.then(()=>{render();$('#demo-notice').hidden=Store.config.payment_mode!=='demo';}).catch(()=>{$('#product-grid').setAttribute('aria-busy','false');$('#results-count').textContent='دریافت محصولات ناموفق بود';$('#product-grid').innerHTML='<div class="empty-state"><h3>ارتباط با فروشگاه برقرار نشد.</h3><button class="button secondary" id="reload-catalog">تلاش دوباره</button></div>';$('#reload-catalog').onclick=()=>location.reload();});
