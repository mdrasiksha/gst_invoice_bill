(function(){
  const form=document.getElementById('invoiceForm'); if(!form) return;
  const table=document.getElementById('itemsTable');
  const field=(name)=>form.querySelector(`[name="${name}"]`);
  const money=(v)=>`₹${(Number(v)||0).toFixed(2)}`;
  function toWords(n){return `Rupees ${Math.round(n)} Only`}
  function isNewCustomer(){return field('customer_type')?.value==='new' || document.getElementById('customerNew')?.checked;}
  function customerData(){
    if(isNewCustomer()){
      const get=(n)=>field(n)?.value?.trim()||'';
      const address=[get('new_customer_address'),get('new_customer_city'),get('new_customer_state'),get('new_customer_pincode')].filter(Boolean).join(', ');
      return {name:get('new_customer_name')||'New customer', gstin:get('new_customer_gstin')||'Unregistered', address, phone:get('new_customer_phone'), email:get('new_customer_email')};
    }
    const sel=field('customer_id'); const opt=sel?.options[sel.selectedIndex];
    return {name:opt?.text||'Select customer', gstin:opt?.dataset.gstin||'Unregistered', address:opt?.dataset.address||'', phone:opt?.dataset.phone||'', email:opt?.dataset.email||''};
  }
  function updateCustomer(){
    const data=customerData();
    [['previewCustomer',data.name],['previewCustomerGstin',`GSTIN: ${data.gstin}`],['previewCustomerAddress',data.address],['previewCustomerPhone',data.phone?`Phone: ${data.phone}`:'']].forEach(([id,val])=>{const el=document.getElementById(id); if(el)el.textContent=val;});
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
  function bindRow(row){row.querySelectorAll('.live,.calc,input,select,textarea').forEach(el=>el.addEventListener('input',recalc)); const rm=row.querySelector('.remove-row'); if(rm)rm.addEventListener('click',()=>{if(table.querySelectorAll('tbody tr').length>1){row.remove();recalc();}});}
  table?.querySelectorAll('tbody tr').forEach(bindRow);
  document.getElementById('addRowBtn')?.addEventListener('click',()=>{const clone=table.querySelector('tbody tr').cloneNode(true);clone.querySelectorAll('input').forEach(input=>{input.value=input.name==='quantity[]'?'1':input.name==='unit_price[]'?'0':''});clone.querySelector('[name="gst_percentage[]"]').value='18.0';table.querySelector('tbody').appendChild(clone);bindRow(clone);recalc();});
  form.querySelectorAll('.live,input,select,textarea').forEach(el=>el.addEventListener('input',()=>{updateCustomerMode();recalc();}));
  form.querySelectorAll('[name="customer_type"]').forEach(el=>el.addEventListener('change',()=>{updateCustomerMode();recalc();}));
  form.addEventListener('submit',(e)=>{if(isNewCustomer() && !field('new_customer_name')?.value.trim()){e.preventDefault(); document.getElementById('newCustomerName')?.focus(); alert('Customer Name is required for a new customer.');}});
  updateCustomerMode(); recalc();
})();
