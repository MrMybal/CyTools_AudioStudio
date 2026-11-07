/* Static, dependency-free product showcase. Local resources only. */
(()=>{'use strict';
 const copy=JSON.parse(document.getElementById('site-copy').textContent);
 const languageButtons=[...document.querySelectorAll('[data-language]')];
 const dialog=document.querySelector('#image-viewer');
 const viewerImage=dialog.querySelector('img');
 const viewerTitle=dialog.querySelector('.viewer-title');
 const viewerCaption=dialog.querySelector('.viewer-caption');
 const shots=[...document.querySelectorAll('[data-image]')];
 let locale='en',activeImage=0,lastFocus=null;
 function text(key){return copy[key]?.[locale]||copy[key]?.en||'';}
 function setLanguage(next){
  locale=next==='fr'?'fr':'en';document.documentElement.lang=locale;
  document.querySelectorAll('[data-copy]').forEach(el=>{el.textContent=text(el.dataset.copy);});
  document.querySelectorAll('[data-copy-alt]').forEach(el=>{el.alt=text(el.dataset.copyAlt);});
  document.querySelectorAll('[data-copy-label]').forEach(el=>{el.setAttribute('aria-label',text(el.dataset.copyLabel));});
  document.querySelectorAll('[data-doc]').forEach(el=>{el.href='Documentation.html#/'+locale+'/'+el.dataset.doc;});
  languageButtons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.language===locale)));
  document.title=copy.product+' — '+text('intro');
  document.querySelector('meta[name="description"]').content=text('description');
  const url=new URL(location.href);if(locale==='fr')url.searchParams.set('lang','fr');else url.searchParams.delete('lang');
  history.replaceState(null,'',url);if(dialog.open)showImage(activeImage);
 }
 function showImage(index){
  activeImage=(index+shots.length)%shots.length;
  const shot=shots[activeImage];viewerImage.src=shot.dataset.image;
  viewerImage.alt=text(shot.dataset.caption);viewerTitle.textContent=(activeImage+1)+' / '+shots.length;
  viewerCaption.textContent=text(shot.dataset.caption);
 }
 shots.forEach((shot,index)=>shot.addEventListener('click',()=>{
  lastFocus=shot;showImage(index);dialog.showModal();document.body.classList.add('modal-open');dialog.querySelector('.viewer-close').focus();
 }));
 dialog.querySelector('.viewer-close').addEventListener('click',()=>dialog.close());
 dialog.querySelector('.viewer-prev').addEventListener('click',()=>showImage(activeImage-1));
 dialog.querySelector('.viewer-next').addEventListener('click',()=>showImage(activeImage+1));
 dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
 dialog.addEventListener('close',()=>{document.body.classList.remove('modal-open');lastFocus?.focus({preventScroll:true});});
 dialog.addEventListener('keydown',event=>{
  if(event.key==='ArrowRight'){event.preventDefault();showImage(activeImage+1);}
  if(event.key==='ArrowLeft'){event.preventDefault();showImage(activeImage-1);}
 });
 languageButtons.forEach(button=>button.addEventListener('click',()=>setLanguage(button.dataset.language)));
 setLanguage(new URLSearchParams(location.search).get('lang'));
 if('IntersectionObserver' in window){
  const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{
   if(entry.isIntersecting)document.querySelectorAll('.chapters a').forEach(a=>{a.classList.toggle('active',a.hash==='#'+entry.target.id);});
  }),{rootMargin:'-20% 0px -65% 0px'});
  document.querySelectorAll('main section[id]').forEach(section=>observer.observe(section));
 }
})();
