// 轻量交互：表单提交后自动刷新提示、确认对话框等
document.addEventListener('click', function(e){
  const t = e.target;
  if (t.matches('[data-confirm]')) {
    if (!confirm(t.dataset.confirm)) e.preventDefault();
  }
});

// 自动消失的 flash
setTimeout(function(){
  document.querySelectorAll('.alert.success').forEach(el => {
    el.style.transition = 'opacity .5s'; el.style.opacity = '0';
    setTimeout(()=>el.remove(), 600);
  });
}, 3500);
