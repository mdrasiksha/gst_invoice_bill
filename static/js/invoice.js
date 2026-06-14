(function(){
  const table=document.getElementById('itemsTable');
  const addBtn=document.getElementById('addRowBtn');
  const form=document.getElementById('invoiceForm');
  function money(v){return '₹'+Number(v||0).toFixed(2)}
  function isIntra(){
    const company=document.querySelector('[name="company_gstin"]')?.value.trim().slice(0,2);
    const supply=document.querySelector('[name="state_code"]')?.value.trim();
    return !supply || company===supply;
  }
  function recalc(){
    if(!table) return;
    let taxable=0,gst=0,total=0;
    table.querySelectorAll('tbody tr').forEach(row=>{
      const qty=parseFloat(row.querySelector('[name="quantity[]"]').value)||0;
      const rate=parseFloat(row.querySelector('[name="unit_price[]"]').value)||0;
      const gstRate=parseFloat(row.querySelector('[name="gst_percentage[]"]').value)||0;
      const tx=Math.max(qty,0)*Math.max(rate,0);
      const gstAmt=tx*gstRate/100;
      const line=tx+gstAmt;
      row.querySelector('.taxable').textContent=tx.toFixed(2);
      row.querySelector('.gst-amount').textContent=gstAmt.toFixed(2);
      row.querySelector('.line-total').textContent=line.toFixed(2);
      taxable+=tx; gst+=gstAmt; total+=line;
    });
    const intra=isIntra();
    document.getElementById('taxableTotal').textContent=money(taxable);
    document.getElementById('cgstTotal').textContent=money(intra?gst/2:0);
    document.getElementById('sgstTotal').textContent=money(intra?gst/2:0);
    document.getElementById('igstTotal').textContent=money(intra?0:gst);
    document.getElementById('grandTotal').textContent=money(total);
  }
  function bindRow(row){row.querySelectorAll('.calc').forEach(el=>el.addEventListener('input',recalc));row.querySelector('.remove-row').addEventListener('click',()=>{if(table.querySelectorAll('tbody tr').length>1){row.remove();recalc();}})}
  if(table){table.querySelectorAll('tbody tr').forEach(bindRow);table.addEventListener('change',recalc)}
  if(addBtn){addBtn.addEventListener('click',()=>{const clone=table.querySelector('tbody tr').cloneNode(true);clone.querySelectorAll('input').forEach(input=>{input.value=input.name==='quantity[]'?'1':input.name==='unit_price[]'?'0':''});clone.querySelector('[name="gst_percentage[]"]').value='18.0';table.querySelector('tbody').appendChild(clone);bindRow(clone);recalc();});}
  document.querySelectorAll('[name="company_gstin"],[name="state_code"]').forEach(el=>el.addEventListener('input',recalc));
  if(form){form.addEventListener('submit',event=>{if(!form.checkValidity()){event.preventDefault();event.stopPropagation();}else{document.getElementById('loadingOverlay')?.classList.remove('d-none');}form.classList.add('was-validated');});form.addEventListener('reset',()=>setTimeout(recalc,0));}
  recalc();
})();
