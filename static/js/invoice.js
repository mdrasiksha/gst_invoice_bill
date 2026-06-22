(function(){
  const form=document.getElementById('invoiceForm'); if(!form) return;
  const table=document.getElementById('itemsTable');
  const field=(name)=>form.querySelector(`[name="${name}"]`);
  const money=(v)=>`₹${(Number(v)||0).toFixed(2)}`;
  const descriptionSuggestions=JSON.parse(form.dataset.descriptionSuggestions||'[]');
  const normalizeText=(value)=>(value||'').toString().trim().toLowerCase();
  const escapeHtml=(value)=>(value||'').toString().replace(/[&<>'"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  function toWords(n){return `Rupees ${Math.round(n)} Only`}
  function isNewCustomer(){return field('customer_type')?.value==='new' || document.getElementById('customerNew')?.checked;}
  function customerData(){
    if(isNewCustomer()){
      const get=(n)=>field(n)?.value?.trim()||'';
      const address=[get('new_customer_address'),get('new_customer_city'),get('new_customer_state'),get('new_customer_pincode')].filter(Boolean).join(', ');
      return {name:get('new_customer_name')||'New customer', gstin:get('new_customer_gstin'), address, phone:get('new_customer_phone'), email:get('new_customer_email')};
    }
    const sel=field('customer_id'); const opt=sel?.options[sel.selectedIndex];
    return {name:opt?.text||'Select customer', gstin:opt?.dataset.gstin||'', address:opt?.dataset.address||'', phone:opt?.dataset.phone||'', email:opt?.dataset.email||''};
  }
  function updateCustomer(){
    const data=customerData();
    [['previewCustomer',data.name],['previewCustomerAddress',data.address],['previewCustomerPhone',data.phone?`Phone: ${data.phone}`:'']].forEach(([id,val])=>{const el=document.getElementById(id); if(el)el.textContent=val;}); const gstEl=document.getElementById('previewCustomerGstin'); if(gstEl){gstEl.textContent=data.gstin?`GSTIN: ${data.gstin}`:''; gstEl.classList.toggle('d-none', !data.gstin);}
  }
  function updateCustomerMode(){
    const existing=document.getElementById('existingCustomerFields'); const newer=document.getElementById('newCustomerFields'); const name=document.getElementById('newCustomerName');
    if(existing) existing.classList.toggle('d-none', isNewCustomer());
    if(newer) newer.classList.toggle('d-none', !isNewCustomer());
    if(name) name.required=isNewCustomer();
    const sel=field('customer_id'); if(sel) sel.required=!isNewCustomer();
    updateCustomer();
  }
  function updateText(){document.querySelectorAll('[data-preview]').forEach(el=>{const f=field(el.dataset.preview); if(f)el.textContent=f.value;}); const terms=document.getElementById('previewTerms'); const termsField=field('terms'); if(terms&&termsField)terms.textContent=termsField.value;}
  function recalc(){ if(!table) return; let taxable=0,gst=0,total=0,html=''; table.querySelectorAll('tbody tr').forEach((row,idx)=>{const name=row.querySelector('[name="item_name[]"]').value||'Item'; const hsn=row.querySelector('[name="hsn_sac[]"]').value||'-'; const qty=parseFloat(row.querySelector('[name="quantity[]"]').value)||0; const rate=parseFloat(row.querySelector('[name="unit_price[]"]').value)||0; const gstRate=parseFloat(row.querySelector('[name="gst_percentage[]"]').value)||0; const tx=Math.max(qty,0)*Math.max(rate,0); const gstAmt=tx*gstRate/100; const line=tx+gstAmt; row.querySelector('.line-total').textContent=money(line); taxable+=tx; gst+=gstAmt; total+=line; html+=`<tr><td>${idx+1}</td><td>${name}</td><td class="text-center">${hsn}</td><td class="text-center">${qty}</td><td class="text-center">${money(rate)}</td><td class="text-center">${gstRate}%</td><td class="text-center">${money(line)}</td></tr>`; }); const intra=isIntra(); const rounded=Math.round(total); const roundOff=rounded-total; const set=(id,val)=>{const el=document.getElementById(id); if(el) el.textContent=money(val)}; set('taxableTotal',taxable); const maxGst=Math.max(...Array.from(table.querySelectorAll('[name="gst_percentage[]"]')).map(el=>parseFloat(el.value)||0),0); const label=(id,text)=>{const el=document.getElementById(id); if(el)el.textContent=text}; label('cgstLabel',`CGST (${intra?maxGst/2:0}%)`); label('sgstLabel',`SGST (${intra?maxGst/2:0}%)`); label('igstLabel',`IGST (${intra?0:maxGst}%)`); set('cgstTotal',intra?gst/2:0); set('sgstTotal',intra?gst/2:0); set('igstTotal',intra?0:gst); set('roundOffTotal',roundOff); set('grandTotal',rounded); const words=document.getElementById('previewWords'); if(words)words.textContent=toWords(rounded); const pi=document.getElementById('previewItems'); if(pi) pi.innerHTML=html||'<tr><td colspan="7" class="text-muted">Add an item</td></tr>'; updateCustomer(); updateText(); }
  function isIntra(){return (document.body.dataset.companyState||'') === (field('state_code')?.value||'');}
  function closeDescriptionSuggestions(except){document.querySelectorAll('.description-suggestions').forEach(box=>{if(box!==except){box.classList.add('d-none');box.innerHTML='';}});}
  function applyDescriptionSuggestion(row,suggestion){
    const set=(name,value)=>{const el=row.querySelector(`[name="${name}"]`); if(el && value!=='' && value!==null && value!==undefined){el.value=value; el.dispatchEvent(new Event('input',{bubbles:true}));}};
    set('item_name[]',suggestion.description);
    set('hsn_sac[]',suggestion.hsn_sac);
    set('unit_price[]',suggestion.unit_price);
    set('gst_percentage[]',suggestion.gst_percentage);
    closeDescriptionSuggestions();
    recalc();
  }
  function updateDescriptionSuggestions(input){
    const row=input.closest('tr'); const box=row?.querySelector('.description-suggestions'); if(!box) return;
    const q=normalizeText(input.value); if(!q){box.classList.add('d-none');box.innerHTML='';return;}
    const matches=descriptionSuggestions.filter(item=>normalizeText(item.description).includes(q)).slice(0,8);
    if(!matches.length){box.classList.add('d-none');box.innerHTML='';return;}
    box.innerHTML=matches.map((item,idx)=>`<button type="button" class="description-suggestion" data-index="${idx}" role="option"><span>${escapeHtml(item.description)}</span><small>${escapeHtml([item.hsn_sac?`HSN/SAC ${item.hsn_sac}`:'',item.unit_price!==''?money(item.unit_price):'',item.gst_percentage!==''?`${item.gst_percentage}% GST`:''].filter(Boolean).join(' · '))}</small></button>`).join('');
    box.querySelectorAll('.description-suggestion').forEach((btn,idx)=>btn.addEventListener('mousedown',e=>{e.preventDefault();applyDescriptionSuggestion(row,matches[idx]);}));
    closeDescriptionSuggestions(box); box.classList.remove('d-none');
  }
  function bindRow(row){row.querySelectorAll('.live,.calc,input,select,textarea').forEach(el=>el.addEventListener('input',recalc)); const desc=row.querySelector('[name="item_name[]"]'); if(desc){desc.classList.add('description-input'); desc.setAttribute('autocomplete','off'); desc.addEventListener('input',()=>updateDescriptionSuggestions(desc)); desc.addEventListener('focus',()=>updateDescriptionSuggestions(desc)); desc.addEventListener('blur',()=>setTimeout(()=>closeDescriptionSuggestions(),120));} const rm=row.querySelector('.remove-row'); if(rm)rm.addEventListener('click',()=>{if(table.querySelectorAll('tbody tr').length>1){row.remove();recalc();}});}
  table?.querySelectorAll('tbody tr').forEach(bindRow);
  document.getElementById('addRowBtn')?.addEventListener('click',()=>{const clone=table.querySelector('tbody tr').cloneNode(true);clone.querySelectorAll('input').forEach(input=>{input.value=input.name==='quantity[]'?'1':input.name==='unit_price[]'?'0':''});clone.querySelectorAll('.description-suggestions').forEach(box=>{box.innerHTML='';box.classList.add('d-none');});clone.querySelector('[name="gst_percentage[]"]').value='18.0';table.querySelector('tbody').appendChild(clone);bindRow(clone);recalc();});
  form.querySelectorAll('.live,input,select,textarea').forEach(el=>el.addEventListener('input',()=>{updateCustomerMode();recalc();}));
  form.querySelectorAll('[name="customer_type"]').forEach(el=>el.addEventListener('change',()=>{updateCustomerMode();recalc();}));
  form.addEventListener('submit',async(e)=>{
    if(isNewCustomer()){const required=[['new_customer_name','Customer Name'],['new_customer_address','Customer Address'],['new_customer_city','Customer City'],['new_customer_state','Customer State'],['new_customer_pincode','Customer Pincode']]; const missing=required.find(([name])=>!field(name)?.value.trim()); if(missing){e.preventDefault(); field(missing[0])?.focus(); alert(`${missing[1]} is required for a new customer.`); return;}}
    e.preventDefault();
    const alertBox=document.getElementById('invoiceAlert');
    const overlay=document.getElementById('loadingOverlay');
    const submit=form.querySelector('#generatePdfBtn');
    alertBox?.classList.add('d-none');
    overlay?.classList.remove('d-none');
    if(submit) submit.disabled=true;
    try{
      const response=await fetch(form.action || window.location.href,{method:'POST',body:new FormData(form),headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
      const data=await response.json().catch(()=>({ok:false,message:'Unable to generate invoice.'}));
      if(response.status===403){
        const modalEl=document.getElementById('upgradeModal');
        if(modalEl && window.bootstrap){new bootstrap.Modal(modalEl).show();}
        else {alert(data.message || 'Monthly invoice limit reached. Please upgrade your plan to continue creating invoices.');}
        return;
      }
      if(!response.ok || !data.ok) throw new Error(data.message || 'Unable to generate invoice.');
      window.location.href=data.download_url;
    }catch(err){
      if(alertBox){alertBox.textContent=err.message; alertBox.className='alert alert-danger';}
      else alert(err.message);
    }finally{
      overlay?.classList.add('d-none');
      if(submit) submit.disabled=false;
    }
  });
  document.addEventListener('click',e=>{if(!e.target.closest('.description-suggest-wrap')) closeDescriptionSuggestions();});
  updateCustomerMode(); recalc();
})();
