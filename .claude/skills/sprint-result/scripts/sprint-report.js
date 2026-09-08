(function(){
  "use strict";
  /* Правки живут в браузере: страница лежит файлом и работает без сети
     (НФТ-SR-10). Круг правок закрывается по ревизии содержимого — пересобрали
     отчёт, значит правки уехали в работу и в следующий промт не идут. */
  var DOC = __DOC_JSON__;
  var KEY = __KEY_JSON__;
  var REV_KEY = KEY + ":rev";
  var REV = (function(){
    var s = (document.querySelector("main") || document.body).textContent, h = 5381;
    for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return (h >>> 0).toString(16);
  })();

  function load(){ try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch(e){ return []; } }
  function save(l){ try { localStorage.setItem(KEY, JSON.stringify(l)); } catch(e){} }
  function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  function open(){ return load().filter(function(c){ return !c.closedAt; }); }

  (function syncRev(){
    var seen = null;
    try { seen = localStorage.getItem(REV_KEY); } catch(e){ return; }
    if (seen && seen !== REV){
      var now = new Date().toISOString(), l = load(), n = 0;
      l.forEach(function(c){ if(!c.closedAt){ c.closedAt = now; n++; } });
      if (n) save(l);
    }
    try { localStorage.setItem(REV_KEY, REV); } catch(e){}
  })();
  var revOut = document.getElementById("revOut");
  if (revOut) revOut.textContent = REV;

  /* Раздел правки — ближайший заголовок над ней: агент правит раздел, а не
     «третий абзац сверху». */
  function sectionOf(node){
    var el = node.nodeType === 1 ? node : node.parentElement;
    while (el && el !== document.body){
      var prev = el.previousElementSibling;
      while (prev){
        if (/^H[123]$/.test(prev.tagName)){
          var h = prev.cloneNode(true), k = h.querySelector(".kicker");
          if (k) k.remove();
          return h.textContent.trim();
        }
        prev = prev.previousElementSibling;
      }
      el = el.parentElement;
    }
    return "Отчёт";
  }
  function anchorOf(node){
    var el = node.nodeType === 1 ? node : node.parentElement;
    var row = el && el.closest ? el.closest("tr.row") : null;
    if (row){
      var t = row.querySelector("td.task");
      return t ? t.textContent.replace(/\s+/g, " ").trim() : null;
    }
    return null;
  }

  var pop = null;
  function closePop(){ if (pop){ pop.remove(); pop = null; } }

  function openPop(x, y, section, anchor, quote){
    closePop();
    pop = document.createElement("div");
    pop.className = "popover";
    var existing = open().filter(function(c){ return c.anchor && c.anchor === anchor; });
    pop.innerHTML =
      (quote ? '<div class="pquote">' + esc(quote.slice(0, 160)) + '</div>' : "") +
      (existing.length ? '<div class="pquote">Уже есть: ' + esc(existing[0].text.slice(0, 90)) + '</div>' : "") +
      '<textarea placeholder="Что поправить в этой строке"></textarea>' +
      '<div class="prow"><button type="button" data-a="ok">Сохранить</button>' +
      '<button type="button" class="cancel" data-a="no">Отмена</button></div>';
    document.body.appendChild(pop);
    var w = pop.offsetWidth, left = Math.min(x, window.innerWidth - w - 12);
    pop.style.left = Math.max(8, left) + "px";
    pop.style.top = (y + window.scrollY + 8) + "px";
    var ta = pop.querySelector("textarea");
    ta.focus();
    function commit(){
      var text = ta.value.trim();
      if (text){
        var l = load();
        l.push({ section: section, anchor: anchor, quote: quote || "", text: text,
                 at: new Date().toISOString() });
        save(l);
        render();
      }
      closePop();
    }
    pop.addEventListener("click", function(e){
      var a = e.target.getAttribute && e.target.getAttribute("data-a");
      if (a === "ok") commit();
      if (a === "no") closePop();
    });
    ta.addEventListener("keydown", function(e){
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") commit();
      if (e.key === "Escape") closePop();
    });
  }

  document.addEventListener("click", function(e){
    if (pop && pop.contains(e.target)) return;
    if (e.target.closest(".promptbox, .rail, .drawer")) return;
    closePop();
    var row = e.target.closest("tr.row");
    if (row){
      var t = row.querySelector("td.task");
      openPop(e.clientX, e.clientY, sectionOf(row),
              t ? t.textContent.replace(/\s+/g, " ").trim() : null,
              t ? t.textContent.replace(/\s+/g, " ").trim() : "");
    }
  });

  document.addEventListener("mouseup", function(e){
    if (e.target.closest(".promptbox, .rail, .drawer, .popover")) return;
    if (e.target.closest("tr.row")) return;
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed) return;
    var q = sel.toString().trim();
    if (q.length < 3) return;
    openPop(e.clientX, e.clientY, sectionOf(sel.anchorNode), anchorOf(sel.anchorNode), q);
  });

  function buildPrompt(list){
    if (!list.length) return "";
    var out = ["Доработай отчёт " + DOC + " с учётом правок PO:", ""];
    list.forEach(function(c, i){
      out.push((i + 1) + ". [" + c.section + "]" +
               (c.anchor ? " (строка: «" + c.anchor + "»)" : "") + " " + c.text);
    });
    out.push("", "После правок — обязательно:",
             "1. Ре-прогон гейтов отчёта (docs/bft-sprint-result-slice1.md §3.2).",
             "2. Пересборка этой страницы — без неё правки придут повторно.");
    return out.join("\n");
  }

  function render(){
    var list = open();
    document.getElementById("editBtn").textContent = "Правки (" + list.length + ")";
    var body = list.length
      ? list.map(function(c, i){
          return '<div class="item"><div class="where">' + esc(c.section) +
                 (c.anchor ? " · " + esc(c.anchor) : "") + '</div>' + esc(c.text) +
                 ' <button type="button" data-del="' + i + '">снять</button></div>';
        }).join("")
      : '<p class="empty">Правок нет. Кликните строку таблицы или выделите текст.</p>';
    document.getElementById("editList").innerHTML = body;
    document.getElementById("editWalk").innerHTML = list.length
      ? list.map(function(c){
          return '<div class="edit-item"><span class="sec">' + esc(c.section) + '</span>' +
                 esc(c.anchor || "") + '<span class="said">' + esc(c.text) + '</span></div>';
        }).join("")
      : '<p class="empty">Правок нет.</p>';
    document.getElementById("promptOut").value = buildPrompt(list);

    var marked = {};
    list.forEach(function(c){ if (c.anchor) marked[c.anchor] = 1; });
    Array.prototype.forEach.call(document.querySelectorAll("tr.row"), function(r){
      var t = r.querySelector("td.task");
      var k = t ? t.textContent.replace(/\s+/g, " ").trim() : "";
      r.classList.toggle("commented", !!marked[k]);
    });
  }

  document.getElementById("editList").addEventListener("click", function(e){
    var i = e.target.getAttribute("data-del");
    if (i === null) return;
    var all = load(), o = open()[+i];
    save(all.filter(function(c){ return c !== o; }));
    render();
  });

  document.getElementById("editBtn").addEventListener("click", function(){
    document.getElementById("editPanel").classList.toggle("open");
  });
  document.getElementById("copyBtn").addEventListener("click", function(){
    var ta = document.getElementById("promptOut");
    if (!ta.value){ document.getElementById("hint").textContent = "Правок пока нет."; return; }
    ta.removeAttribute("readonly"); ta.select();
    try { document.execCommand("copy"); } catch(e){}
    if (navigator.clipboard) navigator.clipboard.writeText(ta.value).catch(function(){});
    ta.setAttribute("readonly", "readonly");
    document.getElementById("hint").textContent = "Промт скопирован — вставьте в чат с агентом.";
  });
  document.getElementById("finalBtn").addEventListener("click", function(){
    var n = open().length;
    document.getElementById("hint").textContent = n
      ? "Осталось " + n + " незакрытых правок — отчёт можно финализировать, но они не учтены."
      : "Отчёт финальный. Команда для агента: /sr-final " + __SPRINT_JSON__;
  });

  /* Оглавление строится из фактических h2 — не хардкодится. */
  document.getElementById("tocList").innerHTML =
    Array.prototype.map.call(document.querySelectorAll("main h2"), function(h){
      var c = h.cloneNode(true), k = c.querySelector(".kicker");
      if (k) k.remove();
      return '<a class="toc-link" href="#' + h.id + '">' + esc(c.textContent.trim()) + "</a>";
    }).join("");

  function drawer(tab, el){
    document.getElementById(tab).addEventListener("click", function(){
      var d = document.getElementById(el), was = d.classList.contains("open");
      document.querySelectorAll(".drawer").forEach(function(x){ x.classList.remove("open"); });
      if (!was) d.classList.add("open");
      document.body.classList.toggle("drawer-open",
        !!document.querySelector(".drawer.open"));
    });
  }
  drawer("tocTab", "tocDrawer");
  drawer("editTab", "editDrawer");

  Array.prototype.forEach.call(document.querySelectorAll("mark.unc"), function(m){
    var b = document.createElement("button");
    b.type = "button"; b.className = "unc-dot"; b.title = "Ответить на уточнение";
    m.after(b);
    b.addEventListener("click", function(e){
      e.stopPropagation();
      openPop(e.clientX, e.clientY, sectionOf(m), m.textContent.trim(), m.textContent.trim());
    });
  });

  render();
})();
