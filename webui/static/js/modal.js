/* Genel modal ac/kapa kontrolcusu — framework yok, tum sayfalarda ortak.
   Kullanim: HTML'de <div class="modal-backdrop" id="..." hidden> ... </div>,
   JS'den window.openModal("id") / window.closeModal(el). Kapanis: X butonu
   (data-modal-close), arka plana tiklama, veya Esc. Odak: acilista ilk
   odaklanabilir elemana, kapanista tetikleyen elemana geri doner. */
(function () {
  var lastTrigger = null;

  window.openModal = function (id, triggerEl) {
    var backdrop = document.getElementById(id);
    if (!backdrop) return;
    lastTrigger = triggerEl || document.activeElement;
    backdrop.hidden = false;
    document.body.style.overflow = "hidden";
    requestAnimationFrame(function () {
      backdrop.classList.add("open");
      var focusable = backdrop.querySelector(
        ".modal-close, [href], button, input, select, textarea, [tabindex]"
      );
      if (focusable) focusable.focus();
    });
  };

  window.closeModal = function (backdrop) {
    if (typeof backdrop === "string") backdrop = document.getElementById(backdrop);
    if (!backdrop || backdrop.hidden) return;
    backdrop.classList.remove("open");
    document.body.style.overflow = "";
    setTimeout(function () {
      backdrop.hidden = true;
    }, 150);
    if (lastTrigger && typeof lastTrigger.focus === "function") lastTrigger.focus();
  };

  document.addEventListener("click", function (e) {
    var closeTrigger = e.target.closest("[data-modal-close]");
    if (closeTrigger) {
      window.closeModal(closeTrigger.closest(".modal-backdrop"));
      return;
    }
    if (e.target.classList && e.target.classList.contains("modal-backdrop")) {
      window.closeModal(e.target);
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    document.querySelectorAll(".modal-backdrop.open").forEach(function (b) {
      window.closeModal(b);
    });
  });
})();
